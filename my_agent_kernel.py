from __future__ import annotations
import sys
import math
from typing import Optional
from examples.agent import _build, estimate_equity, main

from agent.strategy import load_strategy, StrategyProfile
from agent.tracker import OpponentTracker
from agent.ranges import (
    is_in_open_range,
    is_in_3bet_range,
    is_in_call_3bet_range,
)
from agent.evaluator import (
    evaluate_board_texture,
    evaluate_blockers,
    classify_hand,
    compute_equity_realization,
    BoardTexture,
)

_GLOBAL_CONTEXT = {
    "strategy": load_strategy("tag"),
    "tracker": OpponentTracker(),
    "vpip_ema": 0.30,
    "last_hand_id": None,
}

def get_stack(table: dict) -> int:
    self_seat = table.get("selfSeatNumber")
    for s in table.get("seats", []):
        if s.get("seatNumber") == self_seat:
            return int(s.get("stackChips") or 0)
    return 0

def extract_actions(table: dict) -> list[str]:
    history = table.get("actionHistory") or table.get("currentRoundActions") or table.get("history") or []
    actions = []
    if isinstance(history, list) and history:
        for a in history:
            if isinstance(a, dict):
                actions.append(str(a.get("action", "")).lower())
            elif isinstance(a, str):
                actions.append(a.lower())
    if not actions:
        recent_events = table.get("recentEvents") or []
        if isinstance(recent_events, list):
            for ev in recent_events:
                if isinstance(ev, dict):
                    summary = ev.get("summary") or {}
                    act = ""
                    if isinstance(summary, dict):
                        act = str(summary.get("action") or "").lower()
                    if not act:
                        act = str(ev.get("action") or "").lower()
                    if act:
                        actions.append(act)
    return actions

def get_position_info(table: dict, self_seat: int) -> tuple[bool, int, int]:
    seats = table.get("seats") or []
    btn = table.get("buttonSeatNumber") or 0
    active_seats = [
        s for s in seats
        if s.get("status") == "Active" and not s.get("folded") and not s.get("isFolded")
    ]
    if not active_seats:
        return True, 1, 0

    all_seat_nums = [s.get("seatNumber") for s in seats if s.get("seatNumber") is not None]
    max_seats = max(all_seat_nums) + 1 if all_seat_nums else 6

    def dist_from_btn(sn: int) -> int:
        return (sn - btn) % max_seats

    active_nums = [s.get("seatNumber") for s in active_seats if s.get("seatNumber") is not None]
    active_nums.sort(key=dist_from_btn)

    n_active = len(active_nums)
    if self_seat not in active_nums:
        return False, n_active, 0

    pos_idx = active_nums.index(self_seat)
    in_pos = pos_idx >= (n_active // 2) or pos_idx == n_active - 1
    return in_pos, n_active, pos_idx

def get_action_line_likelihood(table: dict, call_chips: int, pot: int, street_idx: int, actions: list[str]) -> float:
    if call_chips <= 0 or pot <= 0:
        return 1.0

    is_check_raise = "check" in actions and "raise" in actions
    raise_count = actions.count("raise")
    bet_count = actions.count("bet")
    total_agg = raise_count + bet_count
    beta = call_chips / max(pot, 1)

    if is_check_raise:
        return 3.5
    if raise_count >= 2:
        return 3.0 if street_idx >= 2 else 2.2
    if street_idx >= 2 and total_agg >= 2 and beta >= 0.35:
        return 2.5
    if street_idx >= 1 and beta >= 0.75:
        return 2.2
    if total_agg >= 1 or beta >= 0.35:
        return 1.5
    if beta >= 0.15:
        return 1.2
    return 0.9

def update_bayesian_equity(raw_eq: float, call_chips: int, pot: int, blockers: dict[str, bool], wetness: float, street_idx: int, likelihood_ratio: float) -> float:
    if call_chips <= 0 or pot <= 0:
        return raw_eq

    beta = call_chips / max(pot, 1)
    decay = 1.0 + (beta * likelihood_ratio * 0.55) * (1.0 + 0.30 * street_idx) * (1.0 + 0.45 * wetness)

    if blockers.get("nfd_blocker"):
        decay *= 0.90
    if blockers.get("top_blocker"):
        decay *= 0.93

    clamped_eq = max(0.01, min(0.99, raw_eq))
    prior_odds = clamped_eq / (1.0 - clamped_eq)
    post_odds = prior_odds / max(1.0, decay)
    post_eq = post_odds / (1.0 + post_odds)
    return max(0.05, min(0.98, post_eq))

def kelly_criterion_fraction(equity: float, pot: int, call_chips: int, fraction: float) -> float:
    if call_chips <= 0:
        b = max(pot, 1) / max(pot * 0.5, 1.0)
    else:
        b = pot / max(call_chips, 1)
    p = equity
    q = 1.0 - p
    if b <= 0:
        return 0.0
    f_star = (b * p - q) / b
    if f_star <= 0:
        return 0.0
    return fraction * f_star

def compute_geometric_bet_size(pot: int, spr: float, street_idx: int) -> float:
    n = max(1, 4 - street_idx) if street_idx > 0 else 3
    if spr <= 0:
        return 0.33
    return ((1.0 + spr) ** (1.0 / n) - 1.0) / 2.0

def compute_kelly_bet_size(equity: float, pot: int, min_b: int, max_b: int, fraction: float, spr: float, wetness: float, street_idx: int) -> int:
    edge = max(0.0, (equity - 0.50) * 2.0)
    if edge <= 0.0:
        return min_b
    geom_s = compute_geometric_bet_size(pot, spr, street_idx)
    spr_factor = 1.0 + max(-0.25, min(0.25, (5.0 - spr) * 0.05))
    wet_factor = 1.0 + (wetness * 0.18)
    f_star = fraction * edge * spr_factor
    kelly_scaling = (0.33 + f_star * 1.50) * wet_factor
    scaling = max(kelly_scaling, geom_s * (0.8 + 0.4 * edge)) if equity >= 0.60 else kelly_scaling
    target = int(pot * scaling)
    return min(max_b, max(min_b, target))

def compute_dynamic_open_size(equity: float, in_pos: bool, bb: int, min_r: int, max_r: int, pot: int) -> int:
    pos_mult = 2.0 if in_pos else 2.30
    edge_add = max(0.0, (equity - 0.45) * 1.8)
    dead_money = max(0, pot - int(bb * 1.5))
    target = int(bb * (pos_mult + edge_add)) + dead_money
    return min(max_r, max(min_r, target))

def compute_dynamic_3bet_size(pot: int, call_chips: int, in_pos: bool, equity: float, min_r: int, max_r: int) -> int:
    mult = (2.5 if in_pos else 3.0) + max(0.0, (equity - 0.55) * 1.8)
    target = int(call_chips * mult) + int(pot * 0.25)
    return min(max_r, max(min_r, target))

def compute_dynamic_cbet_size(equity: float, pot: int, min_b: int, max_b: int, in_pos: bool, wetness: float, spr: float, street_idx: int) -> int:
    alpha = min_b / max(pot + min_b, 1)
    base_ratio = alpha * (0.8 if in_pos else 1.0)
    edge_ratio = max(0.0, (equity - 0.45) * 0.45)
    wet_ratio = wetness * 0.15
    spr_adjust = -0.04 if spr > 8.0 else (0.04 if spr < 2.5 else 0.0)
    base_size = min(0.70, max(0.20, base_ratio + edge_ratio + wet_ratio + spr_adjust))
    geom_s = compute_geometric_bet_size(pot, spr, street_idx)
    if equity >= 0.65:
        ratio = max(base_size, min(1.3, geom_s))
    else:
        ratio = base_size
    target = int(pot * ratio)
    return min(max_b, max(min_b, target))

def decide(table: dict, deadline_s: float = 10.0,
           research_context: Optional[dict] = None) -> dict:

    ctx = research_context if research_context is not None else _GLOBAL_CONTEXT
    strategy: StrategyProfile = ctx.get("strategy") or load_strategy("tag")
    tracker: OpponentTracker = ctx.get("tracker") or _GLOBAL_CONTEXT["tracker"]

    vpip_ema = float(ctx.get("vpip_ema", strategy.target_vpip))
    delta = vpip_ema - strategy.target_vpip

    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []

    self_seat = table.get("selfSeatNumber")
    seats = table.get("seats") or []
    hero = next((s for s in seats if s.get("seatNumber") == self_seat), {})

    hole = hero.get("holeCards") or []
    board = table.get("boardCards") or []

    pot = int(table.get("potChips") or 0)
    call_chips = int(allowed.get("callChips") or 0)
    call_amount = int(allowed.get("callAmount") or table.get("callAmount") or call_chips)
    stack = get_stack(table)

    if call_amount > call_chips and call_chips > 0:
        pot_eff = max(1, pot + 2 * call_chips - call_amount)
        pot_odds_eff = call_chips / max(pot_eff + call_chips, 1)
    else:
        pot_eff = pot
        pot_odds_eff = call_chips / max(pot + call_chips, 1) if call_chips else 0.0

    bb = max(int(table.get("bigBlindChips") or table.get("bigBlind") or 2), 1)
    stack_bb = stack / bb if bb else 100.0
    spr = stack / max(pot_eff, 1)

    mdf = 1.0 - pot_odds_eff if pot_odds_eff > 0 else 1.0
    risk_ratio = call_chips / stack if stack > 0 else 0.0

    in_pos, n_active, pos_idx = get_position_info(table, self_seat)

    is_pf = len(board) == 0
    street_idx = 0 if is_pf else (1 if len(board) == 3 else (2 if len(board) == 4 else 3))

    actions = extract_actions(table)
    raise_count = actions.count("raise")
    bet_count = actions.count("bet")
    total_agg = raise_count + bet_count

    texture: BoardTexture = evaluate_board_texture(board)
    blockers = evaluate_blockers(hole, board)
    hand_cat = classify_hand(hole, board) if not is_pf else "preflop"

    opp_offsets = {"open_offset": 0.0, "cbet_offset": 0.0, "call_offset": 0.0}
    for s in seats:
        s_num = s.get("seatNumber")
        if s_num is not None and s_num != self_seat and s.get("status") == "Active":
            p_id = str(s.get("playerId") or s.get("id") or s.get("name") or "")
            if p_id:
                opp_offsets = tracker.get_exploit_offsets(p_id)
                break

    kelly_f = max(
        strategy.risk.kelly_fraction_min,
        min(strategy.risk.kelly_fraction_max, 1.0 / (2.0 + (max(stack_bb, 1.0) / strategy.risk.kelly_fraction_scale)))
    )
    max_risk = max(
        strategy.risk.max_risk_floor,
        min(strategy.risk.max_risk_cap, 1.0 / (1.8 + 0.12 * spr + 0.008 * max(stack_bb, 1.0)))
    )
    stack_off_req = min(
        strategy.risk.stack_off_req_cap,
        max(strategy.risk.stack_off_req_floor, 0.50 + 0.45 * (max(stack_bb, 1.0) / (max(stack_bb, 1.0) + 35.0)) + 0.04 * texture.wetness)
    )

    realization = compute_equity_realization(in_pos, texture, hand_cat, spr, street_idx, n_active)
    likelihood_ratio = get_action_line_likelihood(table, call_chips, pot_eff, street_idx, actions=actions)

    sims_count = 160 if is_pf else 280
    safe_deadline = min(deadline_s, 2.0) if deadline_s else 2.0
    try:
        raw_equity = estimate_equity(hole, board, sims=sims_count, deadline_s=safe_deadline)
    except Exception:
        raw_equity = max(0.30, min(0.45, 0.38 - 0.10 * delta))

    equity = update_bayesian_equity(raw_equity, call_chips, pot_eff, blockers, texture.wetness, street_idx, likelihood_ratio)
    realized_equity = min(0.99, equity * realization)
    kf = kelly_criterion_fraction(realized_equity, pot_eff, call_chips, fraction=kelly_f)

    def _build_tracked(act: str, amount: Optional[int], eq: float = 0.0, po: float = 0.0, msg: str = "") -> dict:
        if is_pf:
            h_id = table.get("handNumber") or table.get("handId") or table.get("id")
            if h_id is None or h_id != ctx.get("last_hand_id"):
                ctx["last_hand_id"] = h_id
                v_val = 1.0 if act in ("call", "bet", "raise") else 0.0
                ctx["vpip_ema"] = vpip_ema * (1.0 - strategy.vpip_ema_alpha) + v_val * strategy.vpip_ema_alpha
        return _build(act, amount, table, allowed, eq=eq, po=po, msg=msg)

    short_stack_threshold = strategy.preflop.short_stack_threshold_ip if in_pos else strategy.preflop.short_stack_threshold_oop
    if is_pf and stack_bb <= short_stack_threshold:
        dead_money_equity_bonus = pot_eff / max(stack, 1) * 0.15
        if (raw_equity + dead_money_equity_bonus >= 0.44) and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            max_r = int(rr.get("max") or stack)
            return _build_tracked("raise", max_r, eq=equity, po=0, msg="Push short")
        if "check" in available:
            return _build_tracked("check", None, eq=equity, po=0, msg="Check short")
        if raw_equity >= pot_odds_eff:
            return _build_tracked("call", None, eq=equity, po=pot_odds_eff, msg="Call short")
        return _build_tracked("fold", None, eq=equity, po=pot_odds_eff, msg="Fold short")

    if is_pf:
        if call_chips <= bb:
            min_open_eq = (
                strategy.preflop.open_base_eq
                + strategy.preflop.open_not_ip_penalty * (1 if not in_pos else 0)
                + strategy.preflop.open_active_player_penalty * max(0, n_active - 2)
                + strategy.preflop.open_spr_factor * math.log1p(spr)
                + strategy.preflop.open_delta_factor * delta
                + opp_offsets.get("open_offset", 0.0)
            )
            min_limp_eq = min_open_eq - strategy.preflop.limp_offset - 0.01 * max(0, n_active - 3) + 0.10 * delta

            in_open_range_lookup = is_in_open_range(hole, pos_idx, n_active)
            min_r = int((allowed.get("raiseRange") or {}).get("min") or bb * 2)
            max_r = int((allowed.get("raiseRange") or {}).get("max") or min_r)
            open_size = compute_dynamic_open_size(raw_equity, in_pos, bb, min_r, max_r, pot_eff)

            if (in_open_range_lookup or raw_equity >= min_open_eq or realized_equity >= min_open_eq) and (allowed.get("canRaise") or allowed.get("canBet")):
                if allowed.get("canRaise"):
                    return _build_tracked("raise", open_size, eq=equity, po=pot_odds_eff, msg="Ranged EV Open Raise")
                if allowed.get("canBet"):
                    return _build_tracked("bet", open_size, eq=equity, po=0, msg="Ranged EV Open Bet")

            if "check" in available:
                return _build_tracked("check", None, eq=equity, po=0, msg="Check BB PF")

            if raw_equity >= min_limp_eq or realized_equity >= min_limp_eq:
                return _build_tracked("call", None, eq=equity, po=pot_odds_eff, msg="Call Limp EV")

            return _build_tracked("fold", None, eq=equity, po=pot_odds_eff, msg="Fold PF Unopened")

        call_bb = call_chips / max(bb, 1)
        if raise_count >= 2 or call_bb >= strategy.preflop.anti_blunder_call_bb or risk_ratio >= strategy.preflop.anti_blunder_risk_ratio:
            req_pf = pot_odds_eff + 0.04 * math.log1p(call_bb) + 0.03 * (1 if not in_pos else 0) + 0.01 * max(0, n_active - 2) + 0.15 * delta + 0.10 * risk_ratio
            if (raw_equity < req_pf and equity < req_pf) and not is_in_call_3bet_range(hole, in_pos):
                return _build_tracked("fold", None, eq=equity, po=pot_odds_eff, msg="3bet Anti-Blunder Fold")

        if risk_ratio > max_risk:
            req_risk_eq = pot_odds_eff + 0.08 * risk_ratio + 0.02 * min(raise_count, 3) + 0.02 * (stack_bb / (stack_bb + 50.0)) + 0.10 * delta
            if equity < req_risk_eq and realized_equity < req_risk_eq:
                return _build_tracked("fold", None, eq=equity, po=pot_odds_eff, msg="Risk fold PF")

        ev_call = realized_equity * (pot_eff + call_chips) - call_chips
        if ev_call >= 0 or realized_equity >= pot_odds_eff or raw_equity >= pot_odds_eff * 0.90:
            if (is_in_3bet_range(hole) or kf > 0.05 or raw_equity >= strategy.preflop.min_3bet_equity) and allowed.get("canRaise"):
                rr = allowed.get("raiseRange") or {}
                min_r = int(rr.get("min") or call_chips * 2)
                max_r = int(rr.get("max") or min_r)
                size = compute_dynamic_3bet_size(pot_eff, call_chips, in_pos, realized_equity, min_r, max_r)
                to_amount = size
                commit = to_amount / max(stack + to_amount, 1)
                req_eq_jam = pot_odds_eff + 0.12 * commit + 0.03 * raise_count + 0.15 * delta
                if commit < 0.20 or raw_equity >= req_eq_jam or realized_equity >= req_eq_jam or is_in_3bet_range(hole):
                    return _build_tracked("raise", size, eq=equity, po=pot_odds_eff, msg="Dynamic Value 3bet")
            return _build_tracked("call", None, eq=equity, po=pot_odds_eff, msg="Dynamic Call PF")

        return _build_tracked("fold", None, eq=equity, po=pot_odds_eff, msg="Fold PF vs Raise")

    if call_chips > 0:
        beta = call_chips / max(pot_eff, 1)
        rr = risk_ratio
        agg_count = total_agg
        base_req_eq = pot_odds_eff + 0.03 * street_idx + 0.08 * beta + 0.10 * rr + 0.15 * delta + opp_offsets.get("call_offset", 0.0)
        req_eq = base_req_eq * (1.0 + 0.10 * agg_count) * (1.0 + texture.wetness)

        is_3bet_pot = raise_count >= 2 or pot_eff >= bb * 12
        if (is_3bet_pot or agg_count >= 2 or beta >= 0.35 or street_idx >= 2) and hand_cat in ("marginal_pair", "weak_draw", "air"):
            if equity < req_eq or realized_equity < req_eq:
                return _build_tracked("fold", None, eq=equity, po=pot_odds_eff, msg="Multi-Street Pressure Fold")
        elif street_idx == 3 and (beta >= strategy.postflop.river_heavy_bet_pot_ratio or rr >= strategy.postflop.river_heavy_bet_risk_ratio):
            river_floor = strategy.postflop.river_hard_equity_floor
            if equity < max(req_eq, river_floor) or realized_equity < max(req_eq, river_floor):
                return _build_tracked("fold", None, eq=equity, po=pot_odds_eff, msg="River Heavy Bet Fold")

        if risk_ratio > max_risk:
            req_risk_eq = pot_odds_eff + 0.08 * risk_ratio + 0.02 * min(total_agg, 3) + 0.02 * (stack_bb / (stack_bb + 50.0)) + 0.10 * delta
            if equity < req_risk_eq and realized_equity < req_risk_eq:
                return _build_tracked("fold", None, eq=equity, po=pot_odds_eff, msg="Risk fold Postflop")

        ev_call = realized_equity * (pot_eff + call_chips) - call_chips

        if ev_call >= 0 or realized_equity >= pot_odds_eff:
            is_monster = hand_cat in ("nut_made", "tptk")
            if (is_monster or realized_equity >= stack_off_req or raw_equity >= strategy.postflop.monster_raise_equity) and allowed.get("canRaise") and kf > 0.05:
                rr = allowed.get("raiseRange") or {}
                min_r = int(rr.get("min") or call_chips * 2)
                max_r = int(rr.get("max") or min_r)
                size = compute_kelly_bet_size(realized_equity, pot_eff + call_chips, min_r, max_r, kelly_f, spr, texture.wetness, street_idx)
                return _build_tracked("raise", size, eq=equity, po=pot_odds_eff, msg="Dynamic Monster Raise")
            return _build_tracked("call", None, eq=equity, po=pot_odds_eff, msg="Dynamic Value Call")

        if call_chips <= pot_eff * strategy.postflop.mdf_max_call_pot_ratio and (realized_equity >= pot_odds_eff * mdf or raw_equity >= pot_odds_eff * 0.85):
            return _build_tracked("call", None, eq=equity, po=pot_odds_eff, msg="MDF Defense Call")

        return _build_tracked("fold", None, eq=equity, po=pot_odds_eff, msg="Negative EV Fold")

    if allowed.get("canBet"):
        min_b = int((allowed.get("betRange") or {}).get("min") or max(pot_eff // 3, 2))
        max_b = int((allowed.get("betRange") or {}).get("max") or min_b)
        alpha = min_b / max(pot_eff + min_b, 1)

        cbet_threshold = (
            alpha if texture.wetness < strategy.postflop.cbet_dry_threshold
            else max(strategy.postflop.cbet_wet_threshold, alpha + strategy.postflop.cbet_wet_factor * texture.wetness)
        ) + opp_offsets.get("cbet_offset", 0.0)

        can_cbet = (
            realized_equity >= cbet_threshold
            or (in_pos and texture.wetness < 0.40 and raw_equity >= 0.35)
            or hand_cat in ("nut_made", "tptk", "combo_draw", "strong_draw")
        )
        if can_cbet:
            size = compute_dynamic_cbet_size(realized_equity, pot_eff, min_b, max_b, in_pos, texture.wetness, spr, street_idx)
            return _build_tracked("bet", size, eq=equity, po=0, msg="Dynamic EV C-Bet")

    if "check" in available:
        return _build_tracked("check", None, eq=equity, po=0, msg="Check")

    return _build_tracked("fold", None, eq=equity, po=pot_odds_eff, msg="Fallback Fold")

if __name__ == "__main__":
    sys.exit(main())