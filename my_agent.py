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

# CONFIG 
MAX_RISK_RATIO = 0.35         
RIVER_EXTRA_MARGIN = 0.15      
OVERBET_STRONG_REQ = 0.70      
STACK_OFF_REQ = 0.85           
C_BET_FREQ_IP = 0.65
C_BET_FREQ_OOP = 0.40

PREMIUM = {"AA", "KK", "QQ", "JJ", "AKs", "AKo"}
STRONG = {"TT", "99", "AQs", "AQo", "AJs", "KQs"}
MEDIUM = {
    "88","77","66","55","44","33","22",
    "ATs","KJs","QJs","JTs","T9s","98s","87s","76s"
}

def tier(cls: str) -> str:
    if cls in PREMIUM: return "P"
    if cls in STRONG: return "S"
    if cls in MEDIUM: return "M"
    return "W"

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

    pot_odds = call_chips / max(pot + call_chips, 1) if call_chips else 0
    risk_ratio = call_chips / stack if stack > 0 else 0

    btn = table.get("buttonSeatNumber")
    in_pos = self_seat == btn
    active = len([s for s in seats if not s.get("isFolded") and s.get("seatNumber")!=self_seat])

    bb = max(int(table.get("bigBlind") or 2), 1)
    stack_bb = stack / bb if bb else 100

    cls = _hand_class(hole)
    t = tier(cls)

    # SHORT STACK PUSH/FOLD
    if not board and stack_bb <= 10:
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
        wide = active <= 2

        if call_chips == 0:
            if t in ("P","S") or (wide and t=="M"):
                if allowed.get("canBet"):
                    br = allowed.get("betRange") or {}
                    min_b = int(br.get("min") or bb*2)
                    max_b = int(br.get("max") or min_b)
                    size = min(max_b, max(min_b, int(pot*0.7)+bb))
                    return _build("bet", size, table, allowed,
                                  eq=0.5, po=0, msg="Open")
            if "check" in available:
                return _build("check", None, table, allowed, eq=0, po=0, msg="Check")
            return _build("fold", None, table, allowed, eq=0, po=0, msg="Fold")

        equity = estimate_equity(hole, board, sims=500, deadline_s=deadline_s)

        # Risk cap preflop
        if risk_ratio > MAX_RISK_RATIO and equity < STACK_OFF_REQ:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Risk fold PF")

        if t=="P" and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            min_r = int(rr.get("min") or call_chips*2)
            max_r = int(rr.get("max") or min_r)
            size = min(max_r, max(min_r, int(pot*0.8)+call_chips))
            return _build("raise", size, table, allowed,
                          eq=equity, po=pot_odds, msg="3bet")

        if equity > pot_odds and "call" in available:
            return _build("call", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Call PF")

        return _build("fold", None, table, allowed,
                      eq=equity, po=pot_odds, msg="Fold PF")

    # POSTFLOP
    equity = estimate_equity(hole, board, sims=600, deadline_s=deadline_s)
    draw = is_draw(board, hole)
    is_river = len(board) == 5
    overbet = call_chips > pot

    # Facing Bet 
    if call_chips > 0:

        # Risk control
        if risk_ratio > MAX_RISK_RATIO and equity < STACK_OFF_REQ:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Risk fold")

        # River tighten
        if is_river:
            if equity < pot_odds + RIVER_EXTRA_MARGIN:
                return _build("fold", None, table, allowed,
                              eq=equity, po=pot_odds, msg="River fold")

        # Overbet tighten
        if overbet and equity < OVERBET_STRONG_REQ:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Overbet fold")

        # Strong raise
        if equity > 0.85 and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            min_r = int(rr.get("min") or call_chips*2)
            max_r = int(rr.get("max") or min_r)
            size = min(max_r, max(min_r, int(pot*0.75)+call_chips))
            return _build("raise", size, table, allowed,
                          eq=equity, po=pot_odds, msg="Value raise")

        if equity > pot_odds:
            return _build("call", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Call")

        return _build("fold", None, table, allowed,
                      eq=equity, po=pot_odds, msg="Fold")

    #  No Bet
    if allowed.get("canBet"):

        # Strong value
        if equity > 0.70:
            br = allowed.get("betRange") or {}
            min_b = int(br.get("min") or pot//2 or 1)
            max_b = int(br.get("max") or min_b)
            size = min(max_b, max(min_b, int(pot*0.7)))
            return _build("bet", size, table, allowed,
                          eq=equity, po=0, msg="Value")

        # Semi bluff
        if draw and 0.35 <= equity <= 0.65:
            br = allowed.get("betRange") or {}
            min_b = int(br.get("min") or pot//3 or 1)
            max_b = int(br.get("max") or min_b)
            size = min(max_b, max(min_b, int(pot*0.5)))
            return _build("bet", size, table, allowed,
                          eq=equity, po=0, msg="Semi bluff")

        # C-bet
        freq = C_BET_FREQ_IP if in_pos else C_BET_FREQ_OOP
        if random.random() < freq:
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