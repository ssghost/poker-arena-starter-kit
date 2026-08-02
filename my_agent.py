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

# ✅ 保留 v1 結構，只加強風險控制
DEEP_MAX_RISK = 0.20        # 原 0.25 → 降低
STD_MAX_RISK = 0.35         # 原 0.40 → 略降

STACK_OFF_REQ_STD = 0.90    # 原 0.88 → 提高
STACK_OFF_REQ_DEEP = 0.96   # 原 0.93 → 明顯提高

RIVER_MARGIN_STD = 0.22     # 原 0.18 → 提高
RIVER_MARGIN_DEEP = 0.32    # 原 0.25 → 提高

OVERBET_REQ_STD = 0.82      # 原 0.75 → 提高
OVERBET_REQ_DEEP = 0.92     # 原 0.85 → 提高

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

def board_is_wet(board):
    if len(board) < 3:
        return False
    suits = [c[-1] for c in board]
    ranks = [c[0] for c in board]
    if max(suits.count(s) for s in suits) >= 3:
        return True
    if len(set(ranks)) < len(ranks):
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
    active = len([s for s in seats if not s.get("isFolded") and s.get("seatNumber")!=self_seat])

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

    # SHORT STACK
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

        wide = active <= 2

        if call_chips == 0:
            if (t in ("P","S")) or (wide and t=="M"):
                if allowed.get("canBet"):
                    br = allowed.get("betRange") or {}
                    min_b = int(br.get("min") or bb*2)
                    max_b = int(br.get("max") or min_b)
                    size = min(max_b, max(min_b, int(pot*0.7)+bb))
                    return _build("bet", size, table, allowed,
                                  eq=0.5, po=0, msg="Open")
            if "check" in available:
                return _build("check", None, table, allowed, eq=0, po=0, msg="Check PF")
            return _build("fold", None, table, allowed, eq=0, po=0, msg="Fold PF")

        equity = estimate_equity(hole, board, sims=500, deadline_s=deadline_s)

        if risk_ratio > max_risk and equity < stack_off_req:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Risk fold PF")

        if t in ("P","S") and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            min_r = int(rr.get("min") or call_chips*2)
            max_r = int(rr.get("max") or min_r)
            size = min(max_r, max(min_r, int(pot*0.8)+call_chips))
            return _build("raise", size, table, allowed,
                          eq=equity, po=pot_odds, msg="3bet")

        if equity > pot_odds:
            return _build("call", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Call PF")

        return _build("fold", None, table, allowed,
                      eq=equity, po=pot_odds, msg="Fold PF")

    # POSTFLOP
    equity = estimate_equity(hole, board, sims=700, deadline_s=deadline_s)
    draw = is_draw(board, hole)
    is_river = len(board) == 5
    overbet = call_chips > pot
    wet_board = board_is_wet(board)

    if call_chips > 0:

        # ✅ 嚴格風險限制
        if risk_ratio > max_risk and equity < stack_off_req:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Risk fold")

        if is_river and equity < pot_odds + river_margin:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="River fold")

        if overbet and equity < overbet_req:
            return _build("fold", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Overbet fold")

        # ✅ 不在濕板面 stack off
        if equity > stack_off_req and not wet_board and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            min_r = int(rr.get("min") or call_chips*2)
            max_r = int(rr.get("max") or min_r)
            size = min(max_r, max(min_r, int(pot*0.9)+call_chips))
            return _build("raise", size, table, allowed,
                          eq=equity, po=pot_odds, msg="Stack off")

        if equity > pot_odds:
            return _build("call", None, table, allowed,
                          eq=equity, po=pot_odds, msg="Call")

        return _build("fold", None, table, allowed,
                      eq=equity, po=pot_odds, msg="Fold")

    if allowed.get("canBet"):

        if stack_bb > DEEP_STACK_BB:
            # ✅ 深碼只在極強牌 build pot
            if equity > 0.90:
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or pot//2 or 1)
                max_b = int(br.get("max") or min_b)
                size = min(max_b, max(min_b, int(pot*0.75)))
                return _build("bet", size, table, allowed,
                              eq=equity, po=0, msg="Deep value")

        else:
            if equity > 0.82:
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or pot//2 or 1)
                max_b = int(br.get("max") or min_b)
                size = min(max_b, max(min_b, int(pot*0.85)))
                return _build("bet", size, table, allowed,
                              eq=equity, po=0, msg="Value")

        if draw and 0.35 <= equity <= 0.65:
            br = allowed.get("betRange") or {}
            min_b = int(br.get("min") or pot//3 or 1)
            max_b = int(br.get("max") or min_b)
            size = min(max_b, max(min_b, int(pot*0.5)))
            return _build("bet", size, table, allowed,
                          eq=equity, po=0, msg="Semi")

        if random.random() < (0.6 if in_pos else 0.4):
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