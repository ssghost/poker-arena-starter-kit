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

DEEP_STACK_BB = 200
SHORT_STACK_BB = 25

DEEP_MAX_RISK = 0.25
STD_MAX_RISK = 0.40

STACK_OFF_REQ_STD = 0.88
STACK_OFF_REQ_DEEP = 0.93

RIVER_MARGIN_STD = 0.20
RIVER_MARGIN_DEEP = 0.28

OVERBET_REQ_STD = 0.75
OVERBET_REQ_DEEP = 0.85

KELLY_FRACTION_STD = 0.35
KELLY_FRACTION_DEEP = 0.25

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
    ("3", "8"), ("3", "9"), ("5", "9"), ("3", "Q"), ("3", "A")
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
    if min(v1, v2) <= 3 and max(v1, v2) <= 10:
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

def update_bayesian_equity(raw_eq: float, hole: list, board: list, call_chips: int, pot: int, bb: int) -> float:
    if call_chips <= 0:
        return raw_eq
    
    is_pf = len(board) == 0
    is_flop = len(board) == 3
    is_turn = len(board) == 4
    is_river = len(board) == 5
    
    tm = is_true_monster(hole, board) if not is_pf else False
    m = is_monster_hand(hole, board) if not is_pf else False
    tptk = is_top_pair_good_kicker(hole, board) if not is_pf else False
    
    if is_pf:
        cls = _hand_class(hole)
        if call_chips >= bb * 15:
            if cls == "AA": return 0.85
            if cls == "KK": return 0.52
            if cls == "QQ": return 0.42
            if cls in ("JJ", "AKs", "AKo"): return 0.38
            return max(0.15, raw_eq * 0.45)
        elif call_chips >= bb * 6:
            if cls == "AA": return 0.88
            if cls == "KK": return 0.72
            if cls in ("QQ", "JJ", "AKs"): return 0.60
            if cls in ("TT", "99", "AKo", "AQs"): return 0.50
            return max(0.20, raw_eq * 0.65)
        elif call_chips >= bb * 2:
            if cls in PREMIUM: return max(0.70, raw_eq)
            if cls in STRONG: return max(0.55, raw_eq * 0.90)
            return raw_eq * 0.82
        return raw_eq

    bet_ratio = call_chips / max(pot, 1)
    
    if tm:
        if bet_ratio > 1.0:
            return max(0.70, raw_eq * 0.92)
        return raw_eq
    
    if m:
        if is_river and bet_ratio > 0.40:
            return raw_eq * 0.75
        if is_turn and bet_ratio > 0.50:
            return raw_eq * 0.82
        if bet_ratio > 0.80:
            return raw_eq * 0.78
        return raw_eq * 0.90
    
    if tptk:
        if is_river:
            if bet_ratio > 0.50: return raw_eq * 0.50
            if bet_ratio > 0.25: return raw_eq * 0.65
            return raw_eq * 0.80
        if is_turn:
            if bet_ratio > 0.50: return raw_eq * 0.60
            if bet_ratio > 0.25: return raw_eq * 0.72
            return raw_eq * 0.85
        if bet_ratio > 0.60:
            return raw_eq * 0.70
        return raw_eq * 0.88
    
    if is_draw(board, hole):
        if bet_ratio > 0.50: return raw_eq * 0.60
        if bet_ratio > 0.25: return raw_eq * 0.75
        return raw_eq * 0.88
    
    if is_river:
        if bet_ratio > 0.25: return raw_eq * 0.35
        return raw_eq * 0.55
    if is_turn:
        if bet_ratio > 0.30: return raw_eq * 0.45
        return raw_eq * 0.65
    if bet_ratio > 0.40:
        return raw_eq * 0.50
    return raw_eq * 0.75

def kelly_criterion_fraction(equity: float, pot: int, call_chips: int, fraction: float = 0.35) -> float:
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

def compute_kelly_bet_size(equity: float, pot: int, min_b: int, max_b: int, fraction: float = 0.35) -> int:
    edge = max(0.0, (equity - 0.50) * 2.0)
    if edge <= 0.0:
        return min_b
    f_star = fraction * edge
    scaling = 0.40 + f_star * 1.60
    target = int(pot * scaling)
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

    pot_odds = call_chips / max(pot + call_chips, 1) if call_chips else 0
    risk_ratio = call_chips / stack if stack > 0 else 0

    btn = table.get("buttonSeatNumber")
    in_pos = self_seat == btn

    cls = _hand_class(hole)
    t = tier(cls)

    if stack_bb > DEEP_STACK_BB:
        max_risk = DEEP_MAX_RISK
        stack_off_req = STACK_OFF_REQ_DEEP
        river_margin = RIVER_MARGIN_DEEP
        overbet_req = OVERBET_REQ_DEEP
        kelly_f = KELLY_FRACTION_DEEP
    else:
        max_risk = STD_MAX_RISK
        stack_off_req = STACK_OFF_REQ_STD
        river_margin = RIVER_MARGIN_STD
        overbet_req = OVERBET_REQ_STD
        kelly_f = KELLY_FRACTION_STD

    if not board and stack_bb <= SHORT_STACK_BB:
        if t in ("P", "S", "M") and allowed.get("canRaise"):
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

        if call_chips <= bb:
            if t in ("P", "S", "M"):
                if allowed.get("canRaise"):
                    rr = allowed.get("raiseRange") or {}
                    min_r = int(rr.get("min") or bb * 2)
                    max_r = int(rr.get("max") or min_r)
                    size = min(max_r, max(min_r, int(pot * 0.85) + bb * 3))
                    return _build("raise", size, table, allowed,
                                  eq=0.55, po=pot_odds, msg="Open PFR TAG")
                elif allowed.get("canBet"):
                    br = allowed.get("betRange") or {}
                    min_b = int(br.get("min") or bb * 2)
                    max_b = int(br.get("max") or min_b)
                    size = min(max_b, max(min_b, int(pot * 0.85) + bb * 3))
                    return _build("bet", size, table, allowed,
                                  eq=0.55, po=0, msg="Open PFR Bet")

            if "check" in available:
                return _build("check", None, table, allowed, eq=0.5, po=0, msg="Check BB PF")
            
            if t in ("P", "S", "M"):
                return _build("call", None, table, allowed, eq=0.5, po=pot_odds, msg="Call 1BB PF")

            return _build("fold", None, table, allowed, eq=0, po=pot_odds, msg="Fold PF")

        raw_equity = estimate_equity(hole, board, sims=500, deadline_s=deadline_s)
        equity = update_bayesian_equity(raw_equity, hole, board, call_chips, pot, bb)
        kf = kelly_criterion_fraction(equity, pot, call_chips, fraction=kelly_f)

        if risk_ratio > max_risk and equity < stack_off_req:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Risk fold PF")

        if call_chips >= bb * 20:
            if cls == "AA":
                if allowed.get("canRaise"):
                    rr = allowed.get("raiseRange") or {}
                    max_r = int(rr.get("max") or stack)
                    return _build("raise", max_r, table, allowed, eq=equity, po=pot_odds, msg="AA All-In PF")
                return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="AA Call PF")
            elif cls == "KK" and call_chips <= bb * 35 and kf > 0.08:
                return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="KK Flat Extreme 4bet PF")
            else:
                return _build("fold", None, table, allowed, eq=equity, po=pot_odds, msg="Fold Extreme 4bet+ PF")

        elif call_chips >= bb * 8:
            if cls == "AA":
                if allowed.get("canRaise"):
                    rr = allowed.get("raiseRange") or {}
                    min_r = int(rr.get("min") or call_chips * 2)
                    max_r = int(rr.get("max") or min_r)
                    size = min(max_r, max(min_r, int(pot * 0.90) + call_chips))
                    return _build("raise", size, table, allowed, eq=equity, po=pot_odds, msg="AA 4bet PF")
                return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="AA Call PF")
            elif cls == "KK":
                return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="KK Control Flat 4bet PF")
            elif cls in ("QQ", "JJ", "AKs") and kf > 0.05:
                return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="Strong Flat 3bet PF")
            else:
                return _build("fold", None, table, allowed, eq=equity, po=pot_odds, msg="Fold Heavy 3bet PF")

        else:
            if cls in PREMIUM_3BET:
                if allowed.get("canRaise"):
                    rr = allowed.get("raiseRange") or {}
                    min_r = int(rr.get("min") or call_chips * 2)
                    max_r = int(rr.get("max") or min_r)
                    size = min(max_r, max(min_r, int(pot * 0.90) + call_chips * 2))
                    return _build("raise", size, table, allowed,
                                  eq=equity, po=pot_odds, msg="Value 3bet PF")

            if (t in ("P", "S") or (t == "M" and in_pos)) and kf > 0.02:
                return _build("call", None, table, allowed,
                              eq=equity, po=pot_odds, msg="Call PF Solid Kelly")

            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Fold PF")

    raw_equity = estimate_equity(hole, board, sims=700, deadline_s=deadline_s)
    equity = update_bayesian_equity(raw_equity, hole, board, call_chips, pot, bb)
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

    board_suits = [c[-1] for c in board]
    has_3flush_board = any(board_suits.count(s) >= 3 for s in "shdc")
    kf = kelly_criterion_fraction(equity, pot, call_chips, fraction=kelly_f)

    if call_chips > 0:
        if not has_made_pair and not draw:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="No hit / Air fold")

        if draw and (call_chips > pot * 0.30 or kf <= 0.0) and equity < 0.52:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Weak draw stop-loss fold")

        if is_pair and is_underpair and over_cards >= 1 and (call_chips > pot * 0.18 or kf < 0.05):
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Underpair overcard fold")

        if (has_3flush_board or call_chips > pot * 0.40) and not true_monster and kf < 0.08:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Facing Raise / Wet Board Non-Monster Fold")

        if (is_turn or is_river) and not monster and not tptk:
            if (has_3flush_board or is_underpair) and call_chips > pot * 0.18:
                return _build("fold", None, table, allowed,
                              eq=equity, po=pot_odds, msg="Dangerous board fold")
            if call_chips > pot * 0.28 or kf < 0.06:
                return _build("fold", None, table, allowed,
                              eq=equity, po=pot_odds, msg="Non-monster heavy bet fold")

        if risk_ratio > max_risk and equity < stack_off_req:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Risk fold")

        if is_river and (equity < pot_odds + river_margin or kf < 0.08):
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="River fold Kelly")

        if overbet and (equity < overbet_req or kf < 0.15):
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Overbet fold")

        if is_flop and not in_pos and monster and equity >= 0.78 and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            min_r = int(rr.get("min") or call_chips * 2)
            max_r = int(rr.get("max") or min_r)
            size = compute_kelly_bet_size(equity, pot + call_chips, min_r, max_r, fraction=kelly_f)
            return _build("raise", size, table, allowed,
                          eq=equity, po=pot_odds, msg="OOP Flop Monster Check-Raise Kelly")

        if true_monster and equity >= stack_off_req and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            min_r = int(rr.get("min") or call_chips * 2)
            max_r = int(rr.get("max") or min_r)
            size = compute_kelly_bet_size(equity, pot + call_chips, min_r, max_r, fraction=kelly_f)
            return _build("raise", size, table, allowed,
                          eq=equity, po=pot_odds, msg="Monster Kelly Raise")

        call_margin = 0.16 if (is_turn or is_river) else 0.12
        if equity > pot_odds + call_margin and kf > 0.04:
            return _build("call", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Call Solid Kelly")

        return _build("fold", None, table, allowed,
                      eq=equity, po=pot_odds, msg="Fold Margin Kelly")

    if allowed.get("canBet"):
        if is_flop and not in_pos and monster and raw_equity >= 0.78:
            if "check" in available:
                return _build("check", None, table, allowed,
                              eq=raw_equity, po=0, msg="OOP Flop Monster Trap Check")

        if true_monster and raw_equity >= 0.80:
            br = allowed.get("betRange") or {}
            min_b = int(br.get("min") or pot // 2 or 1)
            max_b = int(br.get("max") or min_b)
            size = compute_kelly_bet_size(raw_equity, pot, min_b, max_b, fraction=kelly_f)
            return _build("bet", size, table, allowed,
                          eq=raw_equity, po=0, msg="True Monster Kelly Bet")

        if raw_equity > 0.72:
            br = allowed.get("betRange") or {}
            min_b = int(br.get("min") or pot // 2 or 1)
            max_b = int(br.get("max") or min_b)
            size = compute_kelly_bet_size(raw_equity, pot, min_b, max_b, fraction=kelly_f)
            return _build("bet", size, table, allowed,
                          eq=raw_equity, po=0, msg="Solid Value Kelly Bet")

        if is_flop and in_pos and not has_3flush_board and (tptk or (raw_equity >= 0.45 and t in ("P", "S", "M"))):
            br = allowed.get("betRange") or {}
            min_b = int(br.get("min") or max(pot // 3, 2))
            max_b = int(br.get("max") or min_b)
            size = min(max_b, max(min_b, int(pot * 0.33)))
            return _build("bet", size, table, allowed,
                          eq=raw_equity, po=0, msg="Flop Positional C-Bet")

        if is_turn and tptk and not has_3flush_board and raw_equity >= 0.65:
            br = allowed.get("betRange") or {}
            min_b = int(br.get("min") or max(pot // 2, 2))
            max_b = int(br.get("max") or min_b)
            size = compute_kelly_bet_size(raw_equity, pot, min_b, max_b, fraction=kelly_f)
            return _build("bet", size, table, allowed,
                          eq=raw_equity, po=0, msg="Turn TPTK Dry Value Kelly Bet")

        if (not has_made_pair and not draw) or is_underpair:
            if "check" in available:
                return _build("check", None, table, allowed,
                              eq=raw_equity, po=0, msg="Air/Underpair Check")

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