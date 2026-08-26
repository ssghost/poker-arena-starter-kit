from __future__ import annotations
import sys
import random
from typing import Optional
from examples.agent import (
    _build,
    _hand_class,
    estimate_equity,
    main,
)

PREMIUM_3BET = {"AA", "KK", "QQ", "JJ", "AKs", "AKo", "AQs"}
PREMIUM = {"AA", "KK", "QQ", "JJ", "AKs", "AKo"}
STRONG = {
    "TT", "99", "88", "77",
    "AQs", "AQo", "AJs", "AJo", "ATs",
    "KQs", "KQo", "KJs", "KJo", "QJs", "JTs"
}

MEDIUM = {
    "66", "55", "44", "33", "22",
    "A9s", "A8s", "A7s", "A5s", "A4s", "A3s", "A2s",
    "KTs", "QTs", "QJo", "JTo",
    "T9s", "98s", "87s", "76s", "65s", "54s"
}

TRASH_OFFSUIT_LOW = {
    ("2", "3"), ("2", "4"), ("2", "5"), ("2", "6"), ("2", "7"), ("2", "8"), ("2", "9"),
    ("3", "4"), ("3", "5"), ("3", "6"), ("3", "7"), ("3", "8"), ("3", "9"),
    ("4", "5"), ("4", "6"), ("4", "7"), ("4", "8"), ("4", "9"),
    ("5", "6"), ("5", "7"), ("5", "8"), ("5", "9"),
    ("6", "7"), ("6", "8"), ("6", "9"),
    ("7", "8"), ("7", "9"),
    ("2", "K"), ("3", "K"), ("4", "K"), ("5", "K"),
    ("2", "Q"), ("3", "Q"), ("4", "Q"), ("5", "Q"),
    ("2", "J"), ("3", "J"), ("4", "J"), ("5", "J"),
    ("3", "8"), ("3", "9"), ("5", "9"), ("3", "Q"), ("3", "A"),
    ("3", "K"), ("2", "A"), ("4", "A"), ("5", "A"), ("6", "A"), ("7", "A"), ("8", "A")
}

def tier(cls: str) -> str:
    if cls in PREMIUM: return "P"
    if cls in STRONG: return "S"
    if cls in MEDIUM: return "M"
    return "W"

def is_unsuited_trash(hole: list) -> bool:
    if len(hole) != 2:
        return False
    c1, c2 = hole[0], hole[1]
    if c1[-1] == c2[-1]:
        return False
    r1, r2 = c1[:-1], c2[:-1]
    pair = tuple(sorted([r1, r2]))
    if pair in TRASH_OFFSUIT_LOW:
        return True
    rank_order = "23456789TJQKA"
    v1, v2 = rank_order.find(r1), rank_order.find(r2)
    if min(v1, v2) <= 4 and max(v1, v2) <= 10:
        return True
    if min(v1, v2) <= 6 and max(v1, v2) == 12:
        return True
    return False

def get_stack(table: dict) -> int:
    self_seat = table.get("selfSeatNumber")
    for s in table.get("seats", []):
        if s.get("seatNumber") == self_seat:
            return int(s.get("stackChips") or 0)
    return 0

def is_draw(board: list, hole: list) -> bool:
    suits = [c[-1] for c in board + hole]
    for s in "shdc":
        if suits.count(s) >= 4:
            return True
    return False

def is_true_monster(hole: list, board: list) -> bool:
    if len(hole) != 2 or len(board) < 3:
        return False
    
    hole_ranks = [c[:-1] for c in hole]
    board_ranks = [c[:-1] for c in board]
    is_pair = hole_ranks[0] == hole_ranks[1]
    
    if is_pair and hole_ranks[0] in board_ranks:
        return True
    
    if not is_pair and hole_ranks[0] in board_ranks and hole_ranks[1] in board_ranks:
        return True

    suits = [c[-1] for c in hole + board]
    if any(suits.count(s) >= 5 for s in "shdc"):
        return True

    return False

def is_monster_hand(hole: list, board: list) -> bool:
    if len(hole) != 2 or len(board) < 3:
        return False
    
    if is_true_monster(hole, board):
        return True

    rank_order = "23456789TJQKA"
    hole_ranks = [c[:-1] for c in hole]
    board_ranks = [c[:-1] for c in board]
    hole_vals = [rank_order.find(r) for r in hole_ranks]
    board_vals = [rank_order.find(r) for r in board_ranks]
    is_pair = hole_ranks[0] == hole_ranks[1]
    
    if is_pair and hole_vals[0] > max(board_vals):
        return True

    return False

def is_top_pair_good_kicker(hole: list, board: list) -> bool:
    if len(hole) != 2 or len(board) < 3:
        return False
    rank_order = "23456789TJQKA"
    hole_ranks = [c[:-1] for c in hole]
    board_ranks = [c[:-1] for c in board]
    board_max_val = max(rank_order.find(r) for r in board_ranks)
    
    h0_val = rank_order.find(hole_ranks[0])
    h1_val = rank_order.find(hole_ranks[1])
    
    if h0_val == board_max_val and h1_val >= 9:
        return True
    if h1_val == board_max_val and h0_val >= 9:
        return True
    return False

def evaluate_board_texture(board: list) -> tuple[float, bool]:
    if len(board) < 3:
        return 0.0, False
    
    rank_order = "23456789TJQKA"
    board_ranks = [c[:-1] for c in board]
    board_suits = [c[-1] for c in board]
    
    is_paired = len(set(board_ranks)) < len(board_ranks)
    
    suit_counts = [board_suits.count(s) for s in "shdc"]
    max_suit = max(suit_counts)
    flush_wetness = (max_suit - 1) / max(len(board) - 1, 1) if max_suit >= 2 else 0.0
    
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

def dynamic_kelly_fraction(stack_bb: float) -> float:
    return max(0.05, min(0.35, 1.0 / (2.0 + (max(stack_bb, 1.0) / 60.0))))

def dynamic_max_risk(stack_bb: float, spr: float) -> float:
    base = 1.0 / (2.0 + 0.15 * spr + 0.01 * max(stack_bb, 1.0))
    return max(0.10, min(0.50, base))

def dynamic_stack_off_req(stack_bb: float, wetness: float) -> float:
    base = 0.50 + 0.50 * (max(stack_bb, 1.0) / (max(stack_bb, 1.0) + 30.0))
    return min(0.98, max(0.60, base + 0.05 * wetness))

def dynamic_call_margin(street_idx: int, wetness: float, spr: float) -> float:
    base = (0.04 + 0.025 * street_idx) * (1.0 + wetness)
    spr_adj = min(1.5, max(0.6, spr / 6.0))
    return max(0.02, min(0.25, base * spr_adj))

def dynamic_action_frequency(edge: float, wetness: float, in_pos: bool) -> float:
    pos_bonus = 0.10 if in_pos else -0.05
    freq = 0.50 + (edge * 1.5) - (wetness * 0.25) + pos_bonus
    return max(0.05, min(0.95, freq))

def update_bayesian_equity(raw_eq: float, hole: list, board: list, call_chips: int, pot: int, bb: int, blockers: dict[str, bool], wetness: float) -> float:
    if call_chips <= 0:
        return raw_eq
    
    is_pf = len(board) == 0
    street_idx = 0 if is_pf else (1 if len(board) == 3 else (2 if len(board) == 4 else 3))
    
    tm = is_true_monster(hole, board) if not is_pf else False
    m = is_monster_hand(hole, board) if not is_pf else False
    tptk = is_top_pair_good_kicker(hole, board) if not is_pf else False
    
    if is_pf:
        cls = _hand_class(hole)
        ratio = call_chips / max(bb, 1)
        if ratio >= 20.0:
            if cls == "AA": return 0.85
            if cls == "KK": return 0.44
            if cls == "QQ": return 0.32
            return max(0.08, raw_eq * 0.30)
        elif ratio >= 10.0:
            if cls == "AA": return 0.88
            if cls == "KK": return 0.58
            if cls == "QQ": return 0.40
            if cls in ("JJ", "AKs"): return 0.36
            return max(0.12, raw_eq * 0.42)
        elif ratio >= 4.0:
            if cls == "AA": return 0.90
            if cls == "KK": return 0.72
            if cls in ("QQ", "JJ", "AKs"): return 0.58
            if cls in ("TT", "99", "AKo", "AQs"): return 0.45
            return max(0.15, raw_eq * 0.55)
        elif ratio >= 2.0:
            if cls in PREMIUM: return max(0.68, raw_eq)
            if cls in STRONG: return max(0.52, raw_eq * 0.88)
            return raw_eq * 0.80
        return raw_eq

    bet_ratio = call_chips / max(pot, 1)
    
    if tm:
        decay = 1.0 + 0.10 * bet_ratio
    elif m:
        blocker_mod = 0.80 if blockers.get("nfd_blocker") else 1.0
        decay = (1.0 + (0.55 + 0.35 * street_idx) * bet_ratio * (1.0 + 0.9 * wetness)) * blocker_mod
    elif tptk:
        blocker_mod = 0.78 if blockers.get("nfd_blocker") else 1.0
        decay = (1.0 + (0.90 + 0.55 * street_idx) * bet_ratio * (1.0 + 1.2 * wetness)) * blocker_mod
    elif is_draw(board, hole):
        decay = 1.0 + (1.10 + 0.45 * street_idx) * bet_ratio * (1.0 + 0.5 * wetness)
    else:
        decay = 1.0 + (1.65 + 0.95 * street_idx) * bet_ratio * (1.0 + 1.6 * wetness)

    clamped_eq = max(0.01, min(0.99, raw_eq))
    prior_odds = clamped_eq / (1.0 - clamped_eq)
    post_odds = prior_odds / max(1.0, decay)
    post_eq = post_odds / (1.0 + post_odds)
    return max(0.03, min(0.98, post_eq))

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

def compute_kelly_bet_size(equity: float, pot: int, min_b: int, max_b: int, fraction: float, spr: float, wetness: float) -> int:
    edge = max(0.0, (equity - 0.50) * 2.0)
    if edge <= 0.0:
        return min_b
    spr_factor = 1.0 + max(-0.30, min(0.30, (5.0 - spr) * 0.06))
    wet_factor = 1.0 + (wetness * 0.22)
    f_star = fraction * edge * spr_factor
    scaling = (0.33 + f_star * 1.65) * wet_factor
    target = int(pot * scaling)
    return min(max_b, max(min_b, target))

def compute_dynamic_open_size(equity: float, in_pos: bool, bb: int, min_r: int, max_r: int, t: str, pot: int) -> int:
    pos_factor = 2.0 if in_pos else 2.30
    tier_multipliers = {"P": 0.80, "S": 0.40, "M": 0.12, "W": 0.0}
    tier_add = tier_multipliers.get(t, 0.0) + max(0.0, (equity - 0.50) * 1.1)
    dead_money_add = max(0, pot - int(bb * 1.5)) if pot > bb * 2 else 0
    target = int(bb * (pos_factor + tier_add)) + dead_money_add
    return min(max_r, max(min_r, target))

def compute_dynamic_3bet_size(pot: int, call_chips: int, in_pos: bool, equity: float, min_r: int, max_r: int) -> int:
    mult = (2.7 if in_pos else 3.4) + max(0.0, (equity - 0.60) * 1.8)
    target = int(call_chips * mult) + int(pot * 0.32)
    return min(max_r, max(min_r, target))

def compute_dynamic_cbet_size(equity: float, pot: int, min_b: int, max_b: int, in_pos: bool, wetness: float, spr: float) -> int:
    alpha = min_b / max(pot + min_b, 1)
    base_ratio = alpha if not in_pos else (alpha * 0.8)
    edge_ratio = max(0.0, (equity - 0.50) * 0.5)
    wet_ratio = wetness * 0.20
    spr_adjust = -0.05 if spr > 8.0 else (0.05 if spr < 2.5 else 0.0)
    ratio = min(0.75, max(0.20, base_ratio + edge_ratio + wet_ratio + spr_adjust))
    target = int(pot * ratio)
    return min(max_b, max(min_b, target))

def decide(table: dict, deadline_s: float = 10.0,
           research_context: Optional[dict] = None) -> dict:

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
    stack_bb = stack / bb if bb else 100
    spr = stack / max(pot, 1)

    pot_odds = call_chips / max(pot + call_chips, 1) if call_chips else 0.0
    mdf = 1.0 - pot_odds if pot_odds > 0 else 1.0
    risk_ratio = call_chips / stack if stack > 0 else 0.0

    btn = table.get("buttonSeatNumber")
    in_pos = self_seat == btn

    cls = _hand_class(hole)
    t = tier(cls)

    wetness, is_paired_board = evaluate_board_texture(board)
    blockers = evaluate_blockers(hole, board)

    max_risk = dynamic_max_risk(stack_bb, spr)
    stack_off_req = dynamic_stack_off_req(stack_bb, wetness)
    kelly_f = dynamic_kelly_fraction(stack_bb)
    
    is_pf = len(board) == 0
    street_idx = 0 if is_pf else (1 if len(board) == 3 else (2 if len(board) == 4 else 3))
    call_margin = dynamic_call_margin(street_idx, wetness, spr)
    min_kf_threshold = call_margin * 0.4

    short_stack_threshold = (8.0 + (4.0 if in_pos else 0.0)) * (1.5 if bb else 1.0)
    if not board and stack_bb <= short_stack_threshold:
        if t in ("P", "S") and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            max_r = int(rr.get("max") or stack)
            return _build("raise", max_r, table, allowed,
                          eq=0.5, po=0, msg="Push short")
        if "check" in available:
            return _build("check", None, table, allowed, eq=0, po=0, msg="Check short")
        return _build("fold", None, table, allowed, eq=0, po=pot_odds, msg="Fold short")

    if not board:
        if call_chips > 0 and (is_unsuited_trash(hole) or t == "W"):
            if "check" in available:
                return _build("check", None, table, allowed, eq=0, po=0, msg="Trash check PF")
            return _build("fold", None, table, allowed, eq=0, po=pot_odds, msg="Trash fold PF")

        raw_equity = estimate_equity(hole, board, sims=500, deadline_s=deadline_s)
        equity = update_bayesian_equity(raw_equity, hole, board, call_chips, pot, bb, blockers, wetness)
        kf = kelly_criterion_fraction(equity, pot, call_chips, fraction=kelly_f)

        if call_chips <= bb:
            open_freq = dynamic_action_frequency(raw_equity - pot_odds - 0.40, 0.0, in_pos)
            if t in ("P", "S") or (t == "M" and (in_pos or call_chips == 0 or random.random() < open_freq)):
                if allowed.get("canRaise"):
                    rr = allowed.get("raiseRange") or {}
                    min_r = int(rr.get("min") or bb * 2)
                    max_r = int(rr.get("max") or min_r)
                    size = compute_dynamic_open_size(raw_equity, in_pos, bb, min_r, max_r, t, pot)
                    return _build("raise", size, table, allowed,
                                  eq=equity, po=pot_odds, msg="Open PFR TAG")
                elif allowed.get("canBet"):
                    br = allowed.get("betRange") or {}
                    min_b = int(br.get("min") or bb * 2)
                    max_b = int(br.get("max") or min_b)
                    size = compute_dynamic_open_size(raw_equity, in_pos, bb, min_b, max_b, t, pot)
                    return _build("bet", size, table, allowed,
                                  eq=equity, po=0, msg="Open PFR Bet")

            if "check" in available:
                return _build("check", None, table, allowed, eq=0.5, po=0, msg="Check BB PF")
            
            if t in ("P", "S") or (t == "M" and in_pos):
                return _build("call", None, table, allowed, eq=0.5, po=pot_odds, msg="Call 1BB PF")

            return _build("fold", None, table, allowed, eq=0, po=pot_odds, msg="Fold PF")

        if risk_ratio > max_risk and equity < stack_off_req:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Risk fold PF")

        commitment_ratio = call_chips / max(stack + call_chips, 1)
        if commitment_ratio >= 0.50 or call_chips >= bb * 20:
            if cls == "AA":
                if allowed.get("canRaise"):
                    rr = allowed.get("raiseRange") or {}
                    max_r = int(rr.get("max") or stack)
                    return _build("raise", max_r, table, allowed, eq=equity, po=pot_odds, msg="AA All-In PF")
                return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="AA Call PF")
            else:
                return _build("fold", None, table, allowed, eq=equity, po=pot_odds, msg="Fold Extreme 5bet+ PF")

        elif commitment_ratio >= 0.25 or call_chips >= bb * 8:
            if cls == "AA":
                if allowed.get("canRaise"):
                    rr = allowed.get("raiseRange") or {}
                    min_r = int(rr.get("min") or call_chips * 2)
                    max_r = int(rr.get("max") or min_r)
                    size = compute_dynamic_3bet_size(pot, call_chips, in_pos, raw_equity, min_r, max_r)
                    return _build("raise", size, table, allowed, eq=equity, po=pot_odds, msg="AA 4bet PF")
                return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="AA Call PF")
            elif cls == "KK" and kf > min_kf_threshold:
                return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="KK Flat 4bet PF")
            else:
                return _build("fold", None, table, allowed, eq=equity, po=pot_odds, msg="Fold 4bet PF")

        else:
            if cls in PREMIUM_3BET:
                if allowed.get("canRaise"):
                    rr = allowed.get("raiseRange") or {}
                    min_r = int(rr.get("min") or call_chips * 2)
                    max_r = int(rr.get("max") or min_r)
                    size = compute_dynamic_3bet_size(pot, call_chips, in_pos, raw_equity, min_r, max_r)
                    return _build("raise", size, table, allowed,
                                  eq=equity, po=pot_odds, msg="Value 3bet PF")

            if t in ("P", "S") and equity > pot_odds + (call_margin * 0.6) and kf > min_kf_threshold * 0.75:
                return _build("call", None, table, allowed,
                              eq=equity, po=pot_odds, msg="Call PF Solid Kelly")

            if t == "M" and in_pos and equity > pot_odds + (call_margin * 0.8) and kf > min_kf_threshold:
                return _build("call", None, table, allowed,
                              eq=equity, po=pot_odds, msg="Call PF Pos Kelly")

            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Fold PF")

    raw_equity = estimate_equity(hole, board, sims=700, deadline_s=deadline_s)
    equity = update_bayesian_equity(raw_equity, hole, board, call_chips, pot, bb, blockers, wetness)
    draw = is_draw(board, hole)
    monster = is_monster_hand(hole, board)
    true_monster = is_true_monster(hole, board)
    tptk = is_top_pair_good_kicker(hole, board)

    is_flop = len(board) == 3
    is_turn = len(board) == 4
    is_river = len(board) == 5
    overbet = call_chips > pot

    board_ranks = [c[:-1] for c in board]
    hole_ranks = [c[:-1] for c in hole]
    is_pair = len(hole_ranks) == 2 and hole_ranks[0] == hole_ranks[1]
    has_made_pair = any(r in board_ranks for r in hole_ranks) or is_pair

    is_underpair = False
    over_cards = 0
    if is_pair:
        rank_order = "23456789TJQKA"
        pocket_val = rank_order.find(hole_ranks[0])
        over_cards = sum(1 for r in board_ranks if rank_order.find(r) > pocket_val)
        if over_cards >= 1:
            is_underpair = True

    kf = kelly_criterion_fraction(equity, pot, call_chips, fraction=kelly_f)
    bet_to_pot = call_chips / max(pot, 1)

    if call_chips > 0:
        if not has_made_pair and not draw:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="No hit / Air fold")

        draw_pot_odds_hurdle = pot_odds + call_margin * (1.0 + wetness)
        if draw and (equity < draw_pot_odds_hurdle or kf <= 0.0):
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Weak draw stop-loss fold")

        underpair_pot_odds_hurdle = pot_odds + call_margin * 1.5
        if is_pair and is_underpair and over_cards >= 1 and (equity < underpair_pot_odds_hurdle or kf < min_kf_threshold):
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Underpair overcard fold")

        facing_heavy_bet_threshold = 1.0 / (2.0 + wetness)
        wet_board_threshold = 0.55 if in_pos else 0.45
        if (wetness > wet_board_threshold or bet_to_pot > facing_heavy_bet_threshold) and not true_monster and kf < (min_kf_threshold * 1.5):
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Facing Raise / Wet Board Non-Monster Fold")

        if (is_turn or is_river) and not monster and not tptk:
            danger_bet_threshold = (1.0 / (4.0 + wetness))
            if (wetness > (0.45 if in_pos else 0.35) or is_underpair) and bet_to_pot > danger_bet_threshold:
                return _build("fold", None, table, allowed,
                              eq=equity, po=pot_odds, msg="Dangerous board fold")
            if bet_to_pot > (1.0 / (3.0 + wetness)) or kf < min_kf_threshold:
                return _build("fold", None, table, allowed,
                              eq=equity, po=pot_odds, msg="Non-monster heavy bet fold")

        if risk_ratio > max_risk and equity < stack_off_req:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Risk fold")

        if is_river and (equity < pot_odds + call_margin or kf < (call_margin * 0.5)):
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="River fold Kelly")

        overbet_equity_req = min(0.96, max(0.70, pot_odds + call_margin + (0.05 * wetness)))
        if overbet and (equity < overbet_equity_req or kf < (call_margin * 2.0)):
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Overbet fold")

        monster_raise_equity_threshold = max(0.68, 1.0 - (pot_odds * 0.5) - (0.05 if blockers.get("top_blocker") else 0.0))
        if is_flop and not in_pos and monster and equity >= monster_raise_equity_threshold and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            min_r = int(rr.get("min") or call_chips * 2)
            max_r = int(rr.get("max") or min_r)
            size = compute_kelly_bet_size(equity, pot + call_chips, min_r, max_r, kelly_f, spr, wetness)
            return _build("raise", size, table, allowed,
                          eq=equity, po=pot_odds, msg="OOP Flop Monster Check-Raise Kelly")

        if true_monster and equity >= stack_off_req and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            min_r = int(rr.get("min") or call_chips * 2)
            max_r = int(rr.get("max") or min_r)
            size = compute_kelly_bet_size(equity, pot + call_chips, min_r, max_r, kelly_f, spr, wetness)
            return _build("raise", size, table, allowed,
                          eq=equity, po=pot_odds, msg="Monster Kelly Raise")

        if equity > pot_odds + call_margin and kf > min_kf_threshold:
            return _build("call", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Call Solid Kelly")

        return _build("fold", None, table, allowed,
                      eq=equity, po=pot_odds, msg="Fold Margin Kelly")

    if allowed.get("canBet"):
        flop_trap_req = stack_off_req * 0.85
        if is_flop and not in_pos and monster and raw_equity >= flop_trap_req:
            trap_freq = dynamic_action_frequency(raw_equity - 0.50, wetness, in_pos)
            if random.random() < trap_freq and "check" in available:
                return _build("check", None, table, allowed,
                              eq=raw_equity, po=0, msg="OOP Flop Monster Trap Check")

        true_monster_bet_threshold = max(0.65, 0.50 + (1.0 / (2.0 + spr)) + 0.05 * wetness)
        if true_monster and raw_equity >= true_monster_bet_threshold:
            br = allowed.get("betRange") or {}
            min_b = int(br.get("min") or pot // 2 or 1)
            max_b = int(br.get("max") or min_b)
            size = compute_kelly_bet_size(raw_equity, pot, min_b, max_b, kelly_f, spr, wetness)
            return _build("bet", size, table, allowed,
                          eq=raw_equity, po=0, msg="True Monster Kelly Bet")

        solid_value_threshold = max(0.58, 0.50 + call_margin + 0.06 * wetness - (0.04 if blockers.get("top_blocker") else 0.0))
        if raw_equity > solid_value_threshold:
            br = allowed.get("betRange") or {}
            min_b = int(br.get("min") or pot // 2 or 1)
            max_b = int(br.get("max") or min_b)
            size = compute_kelly_bet_size(raw_equity, pot, min_b, max_b, kelly_f, spr, wetness)
            return _build("bet", size, table, allowed,
                          eq=raw_equity, po=0, msg="Solid Value Kelly Bet")

        cbet_min_size = int(allowed.get("betRange", {}).get("min") or max(pot // 3, 2))
        cbet_alpha = cbet_min_size / max(pot + cbet_min_size, 1)
        cbet_equity_threshold = max(0.32, cbet_alpha + 0.10 * wetness)
        cbet_wetness_limit = 0.65 if in_pos else 0.50
        if is_flop and in_pos and wetness < cbet_wetness_limit and (tptk or (raw_equity >= cbet_equity_threshold and t in ("P", "S", "M"))):
            cbet_freq = dynamic_action_frequency(raw_equity - cbet_alpha, wetness, in_pos)
            if random.random() < cbet_freq:
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or max(pot // 3, 2))
                max_b = int(br.get("max") or min_b)
                size = compute_dynamic_cbet_size(raw_equity, pot, min_b, max_b, in_pos, wetness, spr)
                return _build("bet", size, table, allowed,
                              eq=raw_equity, po=0, msg="Flop Positional C-Bet")

        turn_tptk_threshold = max(0.55, 0.50 + call_margin * 1.5 + 0.06 * wetness)
        turn_wetness_limit = 0.60 if in_pos else 0.45
        if is_turn and tptk and wetness < turn_wetness_limit and raw_equity >= turn_tptk_threshold:
            turn_freq = dynamic_action_frequency(raw_equity - 0.50, wetness, in_pos)
            if random.random() < turn_freq:
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or max(pot // 2, 2))
                max_b = int(br.get("max") or min_b)
                size = compute_kelly_bet_size(raw_equity, pot, min_b, max_b, kelly_f, spr, wetness)
                return _build("bet", size, table, allowed,
                              eq=raw_equity, po=0, msg="Turn TPTK Dry Value Kelly Bet")

        wet_check_limit = 0.55 if in_pos else 0.45
        if (not has_made_pair and not draw) or is_underpair or wetness >= wet_check_limit:
            if "check" in available:
                return _build("check", None, table, allowed,
                              eq=raw_equity, po=0, msg="Air/Underpair/Wet Check")

        if is_turn and not true_monster and not tptk:
            if "check" in available:
                return _build("check", None, table, allowed,
                              eq=raw_equity, po=0, msg="Turn Pot Control Check")

    if "check" in available:
        return _build("check", None, table, allowed,
                      eq=raw_equity, po=0, msg="Check")

    return _build("fold", None, table, allowed,
                  eq=raw_equity, po=pot_odds, msg="Fallback")

if __name__ == "__main__":
    sys.exit(main())