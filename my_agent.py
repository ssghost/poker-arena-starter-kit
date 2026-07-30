from __future__ import annotations

import sys
from typing import Optional

from examples.agent import (
    _build,
    _hand_class,
    estimate_equity,
    main,
)

_GTO_PREFLOP_TIERS = {
    "PREMIUM": {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs"},
    "STRONG": {"99", "88", "77", "AQo", "AJs", "AJo", "ATs", "KQs", "KQo", "KJs"},
    "PLAYABLE": {"66", "55", "44", "33", "22", "ATo", "KTs", "QJs", "JTs", "T9s", "98s", "87s"},
}

def _get_preflop_tier(cls: str) -> str:
    for tier, hands in _GTO_PREFLOP_TIERS.items():
        if cls in hands:
            return tier
    return "MARGINAL"


def retrieve_solver_context(table: dict) -> dict:
    """Fetches table statistics to calculate opponent aggression profiles."""
    seats = table.get("seats") or []
    self_seat = table.get("selfSeatNumber")
    
    opponents = [s for s in seats if s.get("seatNumber") != self_seat and not s.get("isFolded")]
    
    total_opponents = len(opponents)
    is_heads_up = (total_opponents == 1)
    
    return {
        "is_heads_up": is_heads_up,
        "active_opponents": total_opponents,
        "aggression_adjustment": 0.02 if is_heads_up else 0.05,
    }


def decide(table: dict, deadline_s: float = 10.0,
           research_context: Optional[dict] = None) -> dict:
    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []

    if deadline_s < 1.5:
        if allowed.get("canCheck"):
            return _build("check", None, table, allowed, eq=0.5, po=0.0,
                          msg="time boundary, taking free option")
        return _build("fold", None, table, allowed, eq=0.0, po=1.0,
                      msg="time boundary, folding to protect stack")

    self_seat_num = table.get("selfSeatNumber")
    seats = table.get("seats") or []
    self_seat = next((s for s in seats if s.get("seatNumber") == self_seat_num), {})
    hole = list(self_seat.get("holeCards") or [])
    board = list(table.get("boardCards") or [])

    pot = int(table.get("potChips") or 0)
    call_chips = int(allowed.get("callChips") or 0)
    pot_odds = call_chips / max(pot + call_chips, 1) if call_chips > 0 else 0.0

    ctx = research_context or retrieve_solver_context(table)
    ev_margin = ctx.get("aggression_adjustment", 0.03)

    bet_relative_to_pot = call_chips / max(pot, 1)
    if bet_relative_to_pot > 0.5:
        ev_margin += 0.05

    sims = 400 if deadline_s > 4.0 else 200
    equity = estimate_equity(hole, board, sims=sims, deadline_s=deadline_s)
    
    hand_cls = _hand_class(hole)
    tier = _get_preflop_tier(hand_cls)

    action_name: str
    amount: Optional[int] = None

    # --- Preflop Logic (GTO Range Guided) ---
    if not board:
        if call_chips == 0:
            if tier in ("PREMIUM", "STRONG") and allowed.get("canBet"):
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or max(int(pot * 0.5), 1))
                max_b = int(br.get("max") or min_b)
                action_name, amount = "bet", max(min_b, min(int(pot * 0.66), max_b))
            elif "check" in available:
                action_name = "check"
            else:
                action_name = "fold"
        else:
            if tier == "PREMIUM" and allowed.get("canRaise"):
                rr = allowed.get("raiseRange") or {}
                min_r = int(rr.get("min") or call_chips * 2)
                max_r = int(rr.get("max") or min_r)
                action_name, amount = "raise", max(min_r, min(int(pot * 0.75 + call_chips * 2), max_r))
            elif tier in ("PREMIUM", "STRONG") and "call" in available:
                action_name = "call"
                cta = allowed.get("callToAmount")
                if cta is not None:
                    amount = int(cta)
            elif tier == "PLAYABLE" and pot_odds <= 0.25 and "call" in available:
                action_name = "call"
                cta = allowed.get("callToAmount")
                if cta is not None:
                    amount = int(cta)
            elif "check" in available:
                action_name = "check"
            else:
                action_name = "fold"

    # --- Postflop Logic (EV & Equity Guided) ---
    else:
        if call_chips == 0:
            if equity >= 0.65 and allowed.get("canBet"):
                br = allowed.get("betRange") or {}
                min_b = int(br.get("min") or max(int(pot * 0.5), 1))
                max_b = int(br.get("max") or min_b)
                target = max(min_b, min(int(pot * 0.66), max_b))
                action_name, amount = "bet", target
            elif "check" in available:
                action_name = "check"
            else:
                action_name = "fold"
        else:
            if equity > 0.80 and allowed.get("canRaise"):
                rr = allowed.get("raiseRange") or {}
                min_r = int(rr.get("min") or call_chips * 2)
                max_r = int(rr.get("max") or min_r)
                target = max(min_r, min(int(pot * 0.75 + call_chips * 2), max_r))
                action_name, amount = "raise", target
            elif equity >= (pot_odds + ev_margin) and "call" in available:
                action_name = "call"
                cta = allowed.get("callToAmount")
                if cta is not None:
                    amount = int(cta)
            elif "check" in available:
                action_name = "check"
            else:
                action_name = "fold"

    if action_name in ("fold", "check", "call"):
        amount = None

    msg = f"L2 GTO/EV Anti-Drawdown: Tier={tier}, Equity={equity:.2f}, Margin={ev_margin:.2f} -> {action_name}"
    return _build(action_name, amount, table, allowed, eq=equity, po=pot_odds, msg=msg)


if __name__ == "__main__":
    sys.exit(main())
