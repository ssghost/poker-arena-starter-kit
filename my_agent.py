from __future__ import annotations

import sys
import random
from typing import Optional, List

from examples.agent import (
    _build,
    _hand_class,
    estimate_equity,
    main,
)

PREMIUM = {"AA", "KK", "QQ", "JJ", "AKs", "AKo"}
STRONG = {
    "TT", "99", "AQs", "AQo", "AJs", "AJo",
    "KQs", "KQo", "KJs", "QJs"
}
MEDIUM = {
    "88", "77", "66", "55", "44", "33", "22",
    "ATs", "ATo", "KTs", "QTs", "JTs",
    "T9s", "98s", "87s", "76s"
}

def _tier(cls: str) -> str:
    if cls in PREMIUM:
        return "PREMIUM"
    if cls in STRONG:
        return "STRONG"
    if cls in MEDIUM:
        return "MEDIUM"
    return "WEAK"

def _effective_stack(table: dict) -> int:
    seats = table.get("seats") or []
    stacks = [int(s.get("stackChips") or 0) for s in seats if not s.get("isFolded")]
    return min(stacks) if stacks else 0

def _is_draw(board: List[str], hole: List[str]) -> bool:
    suits = [c[-1] for c in board + hole]
    for s in "shdc":
        if suits.count(s) >= 4:
            return True
    return False

def _range_equity(hole, board, tight=False, deadline_s=5.0):
    sims = 600 if deadline_s > 4 else 300
    base = estimate_equity(hole, board, sims=sims, deadline_s=deadline_s)
    if tight:
        base *= 0.88
    return base

def decide(table: dict, deadline_s: float = 10.0,
           research_context: Optional[dict] = None) -> dict:

    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []

    self_seat_num = table.get("selfSeatNumber")
    seats = table.get("seats") or []
    self_seat = next((s for s in seats if s.get("seatNumber") == self_seat_num), {})

    hole = list(self_seat.get("holeCards") or [])
    board = list(table.get("boardCards") or [])

    pot = int(table.get("potChips") or 0)
    call_chips = int(allowed.get("callChips") or 0)
    pot_odds = call_chips / max(pot + call_chips, 1) if call_chips > 0 else 0.0

    btn = table.get("buttonSeatNumber")
    in_position = self_seat_num == btn

    active_opponents = len([
        s for s in seats
        if s.get("seatNumber") != self_seat_num and not s.get("isFolded")
    ])

    eff_stack = _effective_stack(table)
    bb = max(int(table.get("bigBlind") or 20), 1)
    stack_bb = eff_stack / bb if bb > 0 else 100

    hand_cls = _hand_class(hole)
    tier = _tier(hand_cls)

    # SHORT STACK PUSH/FOLD
    if not board and stack_bb <= 12:
        if tier in ("PREMIUM", "STRONG", "MEDIUM") and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            max_r = int(rr.get("max") or eff_stack)
            return _build("raise", max_r, table, allowed,
                          eq=0.5, po=0.0,
                          msg="Short stack push")
        if call_chips == 0 and "check" in available:
            return _build("check", None, table, allowed,
                          eq=0.0, po=0.0,
                          msg="Short stack check")
        return _build("fold", None, table, allowed,
                      eq=0.0, po=pot_odds,
                      msg="Short stack fold")

    # PREFLOP
    if not board:

        wide_open = active_opponents <= 2

        if call_chips == 0:
            if tier in ("PREMIUM", "STRONG") or (wide_open and tier == "MEDIUM"):
                if allowed.get("canBet"):
                    br = allowed.get("betRange") or {}
                    min_b = int(br.get("min") or bb * 2)
                    max_b = int(br.get("max") or min_b)
                    size = min(max_b, max(min_b, int(pot * (0.7 if in_position else 0.9))))
                    return _build("bet", size, table, allowed,
                                  eq=0.5, po=0.0,
                                  msg="Preflop open")
            if "check" in available:
                return _build("check", None, table, allowed,
                              eq=0.0, po=0.0,
                              msg="Preflop check")
            return _build("fold", None, table, allowed,
                          eq=0.0, po=0.0,
                          msg="Preflop fold")

        else:
            tight = call_chips > pot * 0.6
            equity = _range_equity(hole, board, tight, deadline_s)

            if tier == "PREMIUM" and allowed.get("canRaise"):
                rr = allowed.get("raiseRange") or {}
                min_r = int(rr.get("min") or call_chips * 2)
                max_r = int(rr.get("max") or min_r)
                size = min(max_r, max(min_r, int(pot * 0.9 + call_chips)))
                return _build("raise", size, table, allowed,
                              eq=equity, po=pot_odds,
                              msg="Preflop 3bet")

            if equity > pot_odds and "call" in available:
                return _build("call", None, table, allowed,
                              eq=equity, po=pot_odds,
                              msg="Preflop call")

            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds,
                          msg="Preflop fold")

    # POSTFLOP
    tight = call_chips > pot * 0.6
    equity = _range_equity(hole, board, tight, deadline_s)
    has_draw = _is_draw(board, hole)

    # --- C-BET ENGINE ---
    if call_chips == 0:
        if allowed.get("canBet"):

            if equity >= 0.7:
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or max(1, int(pot * 0.5)))
                max_b = int(br.get("max") or min_b)
                size = min(max_b, max(min_b, int(pot * 0.75)))
                return _build("bet", size, table, allowed,
                              eq=equity, po=0.0,
                              msg="Value bet")

            if has_draw and 0.35 <= equity <= 0.65:
                if random.random() < 0.7:
                    br = allowed.get("betRange") or {}
                    min_b = int(br.get("min") or max(1, int(pot * 0.4)))
                    max_b = int(br.get("max") or min_b)
                    size = min(max_b, max(min_b, int(pot * 0.5)))
                    return _build("bet", size, table, allowed,
                                  eq=equity, po=0.0,
                                  msg="Semi bluff")

            if random.random() < (0.6 if in_position else 0.4):
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or max(1, int(pot * 0.3)))
                max_b = int(br.get("max") or min_b)
                size = min(max_b, max(min_b, int(pot * 0.4)))
                return _build("bet", size, table, allowed,
                              eq=equity, po=0.0,
                              msg="C-bet bluff")

        if "check" in available:
            return _build("check", None, table, allowed,
                          eq=equity, po=0.0,
                          msg="Check back")

    else:

        if equity >= 0.8 and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            min_r = int(rr.get("min") or call_chips * 2)
            max_r = int(rr.get("max") or min_r)
            size = min(max_r, max(min_r, int(pot * 0.8 + call_chips)))
            return _build("raise", size, table, allowed,
                          eq=equity, po=pot_odds,
                          msg="Value raise")

        if has_draw and equity > pot_odds and random.random() < 0.5 and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            min_r = int(rr.get("min") or call_chips * 2)
            max_r = int(rr.get("max") or min_r)
            size = min(max_r, max(min_r, int(pot * 0.6 + call_chips)))
            return _build("raise", size, table, allowed,
                          eq=equity, po=pot_odds,
                          msg="Semi bluff raise")

        if equity > pot_odds and "call" in available:
            return _build("call", None, table, allowed,
                          eq=equity, po=pot_odds,
                          msg="Call by pot odds")

        return _build("fold", None, table, allowed,
                      eq=equity, po=pot_odds,
                      msg="Postflop fold")

    return _build("fold", None, table, allowed,
                  eq=equity, po=pot_odds,
                  msg="Fallback")

if __name__ == "__main__":
    sys.exit(main())