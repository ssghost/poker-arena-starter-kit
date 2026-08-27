from __future__ import annotations
import sys
import random
import math
from typing import Optional
from examples.agent import (
    _build,
    estimate_equity,
    main,
)

_GLOBAL_CONTEXT = {}

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

def get_position_info(table: dict, self_seat: int) -> tuple[bool, int]:
    seats = table.get("seats") or []
    btn = table.get("buttonSeatNumber")
    if btn is None:
        btn = 0
    active_seats = [
        s for s in seats 
        if s.get("status") == "Active" and not s.get("folded") and not s.get("isFolded")
    ]
    if not active_seats:
        return True, 1
    
    all_seat_nums = [s.get("seatNumber") for s in seats if s.get("seatNumber") is not None]
    max_seats = max(all_seat_nums) + 1 if all_seat_nums else 6
    
    def dist_from_btn(sn: int) -> int:
        return (sn - btn) % max_seats

    active_nums = [s.get("seatNumber") for s in active_seats if s.get("seatNumber") is not None]
    active_nums.sort(key=dist_from_btn)
    
    n_active = len(active_nums)
    if self_seat not in active_nums:
        return False, n_active
        
    pos_idx = active_nums.index(self_seat)
    in_pos = pos_idx >= (n_active // 2) or pos_idx == n_active - 1
    return in_pos, n_active

def evaluate_board_texture(board: list) -> tuple[float, bool]:
    if len(board) < 3:
        return 0.0, False
    
    rank_order = "23456789TJQKA"
    board_ranks = [c[:-1] for c in board]
    board_suits = [c[-1] for c in board]
    
    is_paired = len(set(board_ranks)) < len(board_ranks)
    
    suit_counts = [board_suits.count(s) for s in "shdc"]
    max_suit = max(suit_counts)
    flush_wetness = max(0.0, (max_suit - 1) / max(len(board) - 1, 1))
    
    vals = sorted([rank_order.find(r) for r in board_ranks])
    conn_count = 0
    for i in range(len(vals) - 1):
        diff = vals[i+1] - vals[i]
        if diff == 1:
            conn_count += 2
        elif diff == 2:
            conn_count += 1
            
    conn_wetness = min(0.50, conn_count / max(len(vals) * 2, 1))
    paired_penalty = -0.10 if is_paired else 0.0
    
    wetness = max(0.0, min(1.0, flush_wetness + conn_wetness + paired_penalty))
    return wetness, is_paired

def evaluate_blockers(hole: list, board: list) -> dict[str, bool]:
    if len(hole) != 2:
        return {"nfd_blocker": False, "top_blocker": False}
    
    rank_order = "23456789TJQKA"
    board_suits = [c[-1] for c in board]
    dominant_suit = None
    for s in "shdc":
        if board_suits.count(s) >= 2:
            dominant_suit = s
            break
            
    nfd_blocker = False
    if dominant_suit:
        for c in hole:
            if c[-1] == dominant_suit and c[:-1] in ("A", "K"):
                nfd_blocker = True
                break
                
    board_ranks = [c[:-1] for c in board]
    board_max = max([rank_order.find(r) for r in board_ranks]) if board_ranks else -1
    hole_ranks = [c[:-1] for c in hole]
    top_blocker = any(rank_order.find(r) >= board_max for r in hole_ranks) if board_max >= 0 else False
    
    return {"nfd_blocker": nfd_blocker, "top_blocker": top_blocker}

def is_strong_preflop_hand(hole: list, raw_equity: float) -> bool:
    if raw_equity >= 0.52:
        return True
    if len(hole) != 2:
        return False
    rank_order = "23456789TJQKA"
    r1, r2 = hole[0][:-1], hole[1][:-1]
    s1, s2 = hole[0][-1], hole[1][-1]
    v1, v2 = rank_order.find(r1), rank_order.find(r2)
    if v1 < 0 or v2 < 0:
        return False
    if v1 == v2:
        return True
    is_suited = (s1 == s2)
    diff = abs(v1 - v2)
    if is_suited and diff <= 2 and min(v1, v2) >= 3:
        return True
    if min(v1, v2) >= 8:
        return True
    if max(v1, v2) == 12 and (is_suited or min(v1, v2) >= 7):
        return True
    if max(v1, v2) == 11 and is_suited and min(v1, v2) >= 6:
        return True
    return False

def is_top_pair_plus_or_strong_draw(hole: list, board: list) -> bool:
    if len(hole) != 2 or len(board) < 3:
        return False
    rank_order = "23456789TJQKA"
    board_ranks = [c[:-1] for c in board]
    hole_ranks = [c[:-1] for c in hole]
    board_vals = [rank_order.find(r) for r in board_ranks if rank_order.find(r) >= 0]
    hole_vals = [rank_order.find(r) for r in hole_ranks if rank_order.find(r) >= 0]
    if not board_vals or len(hole_vals) < 2:
        return False
    
    max_b = max(board_vals)
    if hole_vals[0] == hole_vals[1] and hole_vals[0] >= max_b:
        return True
    if any(v >= max_b and v in board_vals for v in hole_vals):
        return True
    
    hit_count = sum(1 for v in hole_vals if v in board_vals)
    if hit_count >= 2:
        return True
    if hole_vals[0] == hole_vals[1] and hole_vals[0] in board_vals:
        return True

    suits = [c[-1] for c in board + hole]
    hole_suits = [c[-1] for c in hole]
    for s in "shdc":
        if suits.count(s) >= 4 and s in hole_suits:
            for c in hole:
                if c[-1] == s and c[:-1] in ("A", "K", "Q"):
                    return True
    return False

def compute_geometric_bet_size(pot: int, spr: float, street_idx: int) -> float:
    n = max(1, 4 - street_idx) if street_idx > 0 else 3
    if spr <= 0:
        return 0.33
    return ((1.0 + spr) ** (1.0 / n) - 1.0) / 2.0

def compute_equity_realization(in_pos: bool, wetness: float, spr: float, street_idx: int, n_active: int) -> float:
    if street_idx == 0:
        pos_factor = 1.05 if in_pos else 0.95
        return max(0.85, min(1.15, pos_factor))
    
    pos_factor = 1.10 if in_pos else 0.90
    wet_factor = 1.0 - (wetness * 0.12)
    spr_factor = 1.0 / (1.0 + 0.015 * min(spr, 20.0))
    street_factor = 1.0 + 0.02 * street_idx
    r0 = pos_factor * wet_factor * spr_factor * street_factor
    multiway_adj = 1.0 / math.sqrt(max(1.0, 1.0 + 0.35 * (n_active - 1)))
    return max(0.40, min(1.25, r0 * multiway_adj))

def dynamic_kelly_fraction(stack_bb: float) -> float:
    return max(0.08, min(0.35, 1.0 / (2.0 + (max(stack_bb, 1.0) / 70.0))))

def dynamic_max_risk(stack_bb: float, spr: float) -> float:
    return max(0.12, min(0.50, 1.0 / (1.8 + 0.12 * spr + 0.008 * max(stack_bb, 1.0))))

def dynamic_stack_off_req(stack_bb: float, wetness: float) -> float:
    base = 0.50 + 0.45 * (max(stack_bb, 1.0) / (max(stack_bb, 1.0) + 35.0))
    return min(0.96, max(0.58, base + 0.04 * wetness))

def get_action_line_likelihood(table: dict, call_chips: int, pot: int, street_idx: int, actions: Optional[list[str]] = None) -> float:
    if call_chips <= 0 or pot <= 0:
        return 1.0
    if actions is None:
        actions = extract_actions(table)

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
    vpip_ema = float(ctx.get("vpip_ema", 0.30))
    delta = vpip_ema - 0.30

    actions = extract_actions(table)
    raise_count = actions.count("raise")
    bet_count = actions.count("bet")
    total_agg = raise_count + bet_count

    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []

    self_seat = table.get("selfSeatNumber")
    seats = table.get("seats") or []
    hero = next((s for s in seats if s.get("seatNumber") == self_seat), {})

    hole = hero.get("holeCards") or []
    board = table.get("boardCards") or []

    pot = int(table.get("potChips") or 0)
    call_chips = int(allowed.get("callChips") or 0)
    stack = get_stack(table)

    bb = max(int(table.get("bigBlindChips") or table.get("bigBlind") or 2), 1)
    stack_bb = stack / bb if bb else 100.0
    spr = stack / max(pot, 1)

    pot_odds = call_chips / max(pot + call_chips, 1) if call_chips else 0.0
    mdf = 1.0 - pot_odds if pot_odds > 0 else 1.0
    risk_ratio = call_chips / stack if stack > 0 else 0.0

    in_pos, n_active = get_position_info(table, self_seat)

    is_pf = len(board) == 0
    street_idx = 0 if is_pf else (1 if len(board) == 3 else (2 if len(board) == 4 else 3))

    wetness, is_paired_board = evaluate_board_texture(board)
    blockers = evaluate_blockers(hole, board)

    max_risk = dynamic_max_risk(stack_bb, spr)
    stack_off_req = dynamic_stack_off_req(stack_bb, wetness)
    kelly_f = dynamic_kelly_fraction(stack_bb)
    realization = compute_equity_realization(in_pos, wetness, spr, street_idx, n_active)
    likelihood_ratio = get_action_line_likelihood(table, call_chips, pot, street_idx, actions=actions)

    sims_count = 160 if is_pf else 280
    safe_deadline = min(deadline_s, 2.0) if deadline_s else 2.0
    try:
        raw_equity = estimate_equity(hole, board, sims=sims_count, deadline_s=safe_deadline)
    except Exception:
        raw_equity = max(0.30, min(0.45, 0.38 - 0.10 * delta))

    equity = update_bayesian_equity(raw_equity, call_chips, pot, blockers, wetness, street_idx, likelihood_ratio)
    realized_equity = min(0.99, equity * realization)
    kf = kelly_criterion_fraction(realized_equity, pot, call_chips, fraction=kelly_f)

    def _build_tracked(act: str, amount: Optional[int], eq: float = 0.0, po: float = 0.0, msg: str = "") -> dict:
        if is_pf:
            h_id = table.get("handNumber") or table.get("handId") or table.get("id")
            if h_id is None or h_id != ctx.get("last_hand_id"):
                ctx["last_hand_id"] = h_id
                v_val = 1.0 if act in ("call", "bet", "raise") else 0.0
                ctx["vpip_ema"] = vpip_ema * 0.95 + v_val * 0.05
        return _build(act, amount, table, allowed, eq=eq, po=po, msg=msg)

    short_stack_threshold = 18.0 if in_pos else 14.0
    if is_pf and stack_bb <= short_stack_threshold:
        dead_money_equity_bonus = pot / max(stack, 1) * 0.15
        if (raw_equity + dead_money_equity_bonus >= 0.44) and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            max_r = int(rr.get("max") or stack)
            return _build_tracked("raise", max_r, eq=equity, po=0, msg="Push short")
        if "check" in available:
            return _build_tracked("check", None, eq=equity, po=0, msg="Check short")
        if raw_equity >= pot_odds:
            return _build_tracked("call", None, eq=equity, po=pot_odds, msg="Call short")
        return _build_tracked("fold", None, eq=equity, po=pot_odds, msg="Fold short")

    if is_pf:
        if call_chips <= bb:
            min_open_eq = 0.46 + 0.04 * (1 if not in_pos else 0) + 0.015 * max(0, n_active - 2) + 0.02 * math.log1p(spr) + 0.25 * delta
            min_limp_eq = min_open_eq - 0.03 - 0.01 * max(0, n_active - 3) + 0.10 * delta
            
            min_r = int((allowed.get("raiseRange") or {}).get("min") or bb * 2)
            max_r = int((allowed.get("raiseRange") or {}).get("max") or min_r)
            open_size = compute_dynamic_open_size(raw_equity, in_pos, bb, min_r, max_r, pot)
            
            if (raw_equity >= min_open_eq or realized_equity >= min_open_eq) and (allowed.get("canRaise") or allowed.get("canBet")):
                if allowed.get("canRaise"):
                    return _build_tracked("raise", open_size, eq=equity, po=pot_odds, msg="Dynamic EV Open Raise")
                if allowed.get("canBet"):
                    return _build_tracked("bet", open_size, eq=equity, po=0, msg="Dynamic EV Open Bet")

            if "check" in available:
                return _build_tracked("check", None, eq=equity, po=0, msg="Check BB PF")
            
            if raw_equity >= min_limp_eq or realized_equity >= min_limp_eq:
                return _build_tracked("call", None, eq=equity, po=pot_odds, msg="Call Limp EV")

            return _build_tracked("fold", None, eq=equity, po=pot_odds, msg="Fold PF Unopened")

        call_bb = call_chips / max(bb, 1)
        if raise_count >= 2 or call_bb >= 4.0 or call_chips >= stack * 0.12 or risk_ratio >= 0.12:
            req_pf = pot_odds + 0.04 * math.log1p(call_bb) + 0.03 * (1 if not in_pos else 0) + 0.01 * max(0, n_active - 2) + 0.15 * delta + 0.10 * risk_ratio
            if (raw_equity < req_pf and equity < req_pf) and not is_strong_preflop_hand(hole, raw_equity):
                return _build_tracked("fold", None, eq=equity, po=pot_odds, msg="3bet Anti-Blunder Fold")

        if risk_ratio > max_risk and equity < stack_off_req:
            return _build_tracked("fold", None, eq=equity, po=pot_odds, msg="Risk fold PF")

        ev_call = realized_equity * (pot + call_chips) - call_chips
        if ev_call >= 0 or realized_equity >= pot_odds or raw_equity >= pot_odds * 0.90:
            if (kf > 0.05 or raw_equity >= 0.62) and allowed.get("canRaise"):
                rr = allowed.get("raiseRange") or {}
                min_r = int(rr.get("min") or call_chips * 2)
                max_r = int(rr.get("max") or min_r)
                size = compute_dynamic_3bet_size(pot, call_chips, in_pos, realized_equity, min_r, max_r)
                return _build_tracked("raise", size, eq=equity, po=pot_odds, msg="Dynamic Value 3bet")
            return _build_tracked("call", None, eq=equity, po=pot_odds, msg="Dynamic Call PF")

        return _build_tracked("fold", None, eq=equity, po=pot_odds, msg="Fold PF vs Raise")

    if call_chips > 0:
        beta = call_chips / max(pot, 1)
        rr = risk_ratio
        agg_count = total_agg
        base_req_eq = pot_odds + 0.03 * street_idx + 0.08 * beta + 0.10 * rr + 0.15 * delta
        req_eq = base_req_eq * (1.0 + 0.10 * agg_count) * (1.0 + wetness)

        is_3bet_pot = raise_count >= 2 or pot >= bb * 12
        if (is_3bet_pot or agg_count >= 2 or beta >= 0.35 or street_idx >= 2) and not is_top_pair_plus_or_strong_draw(hole, board):
            if equity < req_eq or realized_equity < req_eq:
                return _build_tracked("fold", None, eq=equity, po=pot_odds, msg="Multi-Street Pressure Fold")
        elif street_idx == 3 and (beta >= 0.50 or rr >= 0.20):
            if equity < max(req_eq, 0.65) or realized_equity < max(req_eq, 0.65):
                return _build_tracked("fold", None, eq=equity, po=pot_odds, msg="River Heavy Bet Fold")

        if risk_ratio > max_risk and equity < stack_off_req:
            return _build_tracked("fold", None, eq=equity, po=pot_odds, msg="Risk fold Postflop")

        ev_call = realized_equity * (pot + call_chips) - call_chips
        
        if ev_call >= 0 or realized_equity >= pot_odds:
            if (realized_equity >= stack_off_req or raw_equity >= 0.75) and allowed.get("canRaise") and kf > 0.05:
                rr = allowed.get("raiseRange") or {}
                min_r = int(rr.get("min") or call_chips * 2)
                max_r = int(rr.get("max") or min_r)
                size = compute_kelly_bet_size(realized_equity, pot + call_chips, min_r, max_r, kelly_f, spr, wetness, street_idx)
                return _build_tracked("raise", size, eq=equity, po=pot_odds, msg="Dynamic Monster Raise")
            return _build_tracked("call", None, eq=equity, po=pot_odds, msg="Dynamic Value Call")

        if call_chips <= pot * 0.35 and (realized_equity >= pot_odds * mdf or raw_equity >= pot_odds * 0.85):
            return _build_tracked("call", None, eq=equity, po=pot_odds, msg="MDF Defense Call")

        return _build_tracked("fold", None, eq=equity, po=pot_odds, msg="Negative EV Fold")

    if allowed.get("canBet"):
        min_b = int((allowed.get("betRange") or {}).get("min") or max(pot // 3, 2))
        max_b = int((allowed.get("betRange") or {}).get("max") or min_b)
        alpha = min_b / max(pot + min_b, 1)

        cbet_threshold = alpha if wetness < 0.45 else max(0.38, alpha + 0.08 * wetness)
        if realized_equity >= cbet_threshold or (in_pos and wetness < 0.40 and raw_equity >= 0.35):
            size = compute_dynamic_cbet_size(realized_equity, pot, min_b, max_b, in_pos, wetness, spr, street_idx)
            return _build_tracked("bet", size, eq=equity, po=0, msg="Dynamic EV C-Bet")

    if "check" in available:
        return _build_tracked("check", None, eq=equity, po=0, msg="Check")

    return _build_tracked("fold", None, eq=equity, po=pot_odds, msg="Fallback Fold")

if __name__ == "__main__":
    sys.exit(main())