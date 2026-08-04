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

RIVER_MARGIN_STD = 0.18
RIVER_MARGIN_DEEP = 0.25

OVERBET_REQ_STD = 0.75
OVERBET_REQ_DEEP = 0.85

PREMIUM = {"AA", "KK", "QQ", "JJ", "AKs", "AKo"}
STRONG = {"TT", "99", "AQs", "AQo", "AJs", "KQs"}
MEDIUM = {
    "88","77","66","55","44","33","22",
    "ATs","KJs","QJs","JTs","T9s","98s","87s","76s"
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
    return pair in TRASH_OFFSUIT_LOW

def get_stack(table: dict) -> int:
    self_seat = table.get("selfSeatNumber")
    for s in table.get("seats", []):
        if s.get("seatNumber") == self_seat:
            return int(s.get("stackChips") or 0)
    return 0

def is_draw(board, hole):
    suits = [c[-1] for c in board + hole]
    for s in "shdc":
        if suits.count(s) >= 4:
            return True
    return False

def decide(table: dict, deadline_s: float = 10.0,
           research_context: Optional[dict] = None) -> dict:

    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []

    self_seat = table.get("selfSeatNumber")
    seats = table.get("seats") or []
    hero = next((s for s in seats if s.get("seatNumber")==self_seat), {})

    hole = hero.get("holeCards") or []
    board = table.get("boardCards") or []

    pot = int(table.get("potChips") or 0)
    call_chips = int(allowed.get("callChips") or 0)
    stack = get_stack(table)

    bb = max(int(table.get("bigBlind") or 2), 1)
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
    else:
        max_risk = STD_MAX_RISK
        stack_off_req = STACK_OFF_REQ_STD
        river_margin = RIVER_MARGIN_STD
        overbet_req = OVERBET_REQ_STD

    # SHORT STACK PUSH/FOLD
    if not board and stack_bb <= SHORT_STACK_BB:
        if t in ("P","S","M") and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            max_r = int(rr.get("max") or stack)
            return _build("raise", max_r, table, allowed,
                          eq=0.5, po=0, msg="Push short")
        if "check" in available:
            return _build("check", None, table, allowed, eq=0, po=0, msg="Check short")
        return _build("fold", None, table, allowed, eq=0, po=pot_odds, msg="Fold short")

    # PREFLOP
    if not board:
        if call_chips > 0 and is_unsuited_trash(hole):
            if "check" in available:
                return _build("check", None, table, allowed, eq=0, po=0, msg="Trash check PF")
            return _build("fold", None, table, allowed, eq=0, po=pot_odds, msg="Trash fold PF")

        if call_chips == 0:
            if t in ("P", "S", "M"):
                if allowed.get("canBet"):
                    br = allowed.get("betRange") or {}
                    min_b = int(br.get("min") or bb*2)
                    max_b = int(br.get("max") or min_b)
                    size = min(max_b, max(min_b, int(pot*0.7)+bb))
                    return _build("bet", size, table, allowed,
                                  eq=0.5, po=0, msg="Open PFR")

            if "check" in available:
                return _build("check", None, table, allowed, eq=0, po=0, msg="Check PF")
            return _build("fold", None, table, allowed, eq=0, po=0, msg="Fold PF")

        equity = estimate_equity(hole, board, sims=500, deadline_s=deadline_s)

        if risk_ratio > max_risk and equity < stack_off_req:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Risk fold PF")

        if t in ("P", "S") or (t == "M" and equity > 0.55):
            if allowed.get("canRaise"):
                rr = allowed.get("raiseRange") or {}
                min_r = int(rr.get("min") or call_chips*2)
                max_r = int(rr.get("max") or min_r)
                size = min(max_r, max(min_r, int(pot*0.8)+call_chips))
                return _build("raise", size, table, allowed,
                              eq=equity, po=pot_odds, msg="Raise/3bet PF")

        if t == "W" and equity < 0.52:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Weak fold PF")

        if equity > pot_odds + 0.10:
            return _build("call", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Call PF")

        return _build("fold", None, table, allowed,
                      eq=equity, po=pot_odds, msg="Fold PF")

    # POSTFLOP
    equity = estimate_equity(hole, board, sims=700, deadline_s=deadline_s)
    draw = is_draw(board, hole)
    is_river = len(board) == 5
    overbet = call_chips > pot

    board_ranks = [c[:-1] for c in board]
    hole_ranks = [c[:-1] for c in hole]
    is_pair = len(hole_ranks) == 2 and hole_ranks[0] == hole_ranks[1]
    has_made_pair = any(r in board_ranks for r in hole_ranks) or is_pair

    if call_chips > 0:
        # Strict Defense
        if not has_made_pair and not draw:
            if len(board) >= 4:
                return _build("fold", None, table, allowed,
                              eq=equity, po=pot_odds, msg="Turn/River no hit fold")
            if call_chips > pot * 0.20 and equity < 0.50:
                return _build("fold", None, table, allowed,
                              eq=equity, po=pot_odds, msg="Flop no hit fold")

        if is_pair and not draw:
            rank_order = "23456789TJQKA"
            pocket_val = rank_order.find(hole_ranks[0])
            over_cards = sum(1 for r in board_ranks if rank_order.find(r) > pocket_val)
            if over_cards >= 2 and call_chips > pot * 0.35:
                return _build("fold", None, table, allowed,
                              eq=equity, po=pot_odds, msg="Underpair overcard fold")

        if risk_ratio > max_risk and equity < stack_off_req:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Risk fold")

        if is_river and equity < pot_odds + river_margin:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="River fold")

        if overbet and equity < overbet_req:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Overbet fold")

        if call_chips > pot * 0.4 and draw and equity < 0.60:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Weak draw fold")

        if equity > stack_off_req and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            min_r = int(rr.get("min") or call_chips*2)
            max_r = int(rr.get("max") or min_r)
            size = min(max_r, max(min_r, int(pot*0.9)+call_chips))
            return _build("raise", size, table, allowed,
                          eq=equity, po=pot_odds, msg="Stack off")

        if equity > pot_odds + 0.05:
            return _build("call", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Call")

        return _build("fold", None, table, allowed,
                      eq=equity, po=pot_odds, msg="Fold")

    if allowed.get("canBet"):
        if not has_made_pair and not draw and equity < 0.60:
            if "check" in available:
                return _build("check", None, table, allowed,
                              eq=equity, po=0, msg="No hit check")

        if stack_bb > DEEP_STACK_BB:
            if equity > 0.85:
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or pot//2 or 1)
                max_b = int(br.get("max") or min_b)
                size = min(max_b, max(min_b, int(pot*0.8)))
                return _build("bet", size, table, allowed,
                              eq=equity, po=0, msg="Deep value")

            if draw and 0.35 <= equity <= 0.65:
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or pot//3 or 1)
                max_b = int(br.get("max") or min_b)
                size = min(max_b, max(min_b, int(pot*0.5)))
                return _build("bet", size, table, allowed,
                              eq=equity, po=0, msg="Deep semi")
        else:
            if equity > 0.80:
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or pot//2 or 1)
                max_b = int(br.get("max") or min_b)
                size = min(max_b, max(min_b, int(pot*0.9)))
                return _build("bet", size, table, allowed,
                              eq=equity, po=0, msg="Value")

            if draw and 0.35 <= equity <= 0.65:
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or pot//3 or 1)
                max_b = int(br.get("max") or min_b)
                size = min(max_b, max(min_b, int(pot*0.6)))
                return _build("bet", size, table, allowed,
                              eq=equity, po=0, msg="Semi")

        if random.random() < (0.65 if in_pos else 0.45):
            br = allowed.get("betRange") or {}
            min_b = int(br.get("min") or pot//3 or 1)
            max_b = int(br.get("max") or min_b)
            size = min(max_b, max(min_b, int(pot*0.4)))
            return _build("bet", size, table, allowed,
                          eq=equity, po=0, msg="Cbet")

    if "check" in available:
        return _build("check", None, table, allowed,
                      eq=equity, po=0, msg="Check")

    return _build("fold", None, table, allowed,
                  eq=equity, po=pot_odds, msg="Fallback")

if __name__ == "__main__":
    sys.exit(main())