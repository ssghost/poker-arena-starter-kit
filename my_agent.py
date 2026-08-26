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

def get_stack(table: dict) -> int:
    self_seat = table.get("selfSeatNumber")
    for s in table.get("seats", []):
        if s.get("seatNumber") == self_seat:
            return int(s.get("stackChips") or 0)
    return 0

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

def compute_equity_realization(in_pos: bool, wetness: float, spr: float, street_idx: int) -> float:
    pos_factor = 1.10 if in_pos else 0.90
    wet_factor = 1.0 - (wetness * 0.15)
    spr_factor = 1.0 / (1.0 + 0.02 * min(spr, 20.0))
    street_factor = 1.0 + 0.03 * street_idx
    return max(0.50, min(1.30, pos_factor * wet_factor * spr_factor * street_factor))

def dynamic_kelly_fraction(stack_bb: float) -> float:
    return max(0.05, min(0.35, 1.0 / (2.0 + (max(stack_bb, 1.0) / 60.0))))

def dynamic_max_risk(stack_bb: float, spr: float) -> float:
    return max(0.10, min(0.50, 1.0 / (2.0 + 0.15 * spr + 0.01 * max(stack_bb, 1.0))))

def dynamic_stack_off_req(stack_bb: float, wetness: float) -> float:
    base = 0.50 + 0.50 * (max(stack_bb, 1.0) / (max(stack_bb, 1.0) + 30.0))
    return min(0.98, max(0.60, base + 0.05 * wetness))

def update_bayesian_equity(raw_eq: float, call_chips: int, pot: int, blockers: dict[str, bool], wetness: float, street_idx: int) -> float:
    if call_chips <= 0 or pot <= 0:
        return raw_eq

    beta = call_chips / max(pot, 1)
    decay = 1.0 + beta * (1.0 + 0.5 * street_idx) * (1.0 + 0.8 * wetness)
    
    if blockers.get("nfd_blocker"):
        decay *= 0.85
    if blockers.get("top_blocker"):
        decay *= 0.90

    clamped_eq = max(0.01, min(0.99, raw_eq))
    prior_odds = clamped_eq / (1.0 - clamped_eq)
    post_odds = prior_odds / max(1.0, decay)
    post_eq = post_odds / (1.0 + post_odds)
    return max(0.02, min(0.98, post_eq))

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

def compute_dynamic_open_size(equity: float, in_pos: bool, bb: int, min_r: int, max_r: int, pot: int) -> int:
    pos_mult = 2.0 if in_pos else 2.35
    edge_add = max(0.0, (equity - 0.45) * 2.0)
    dead_money = max(0, pot - int(bb * 1.5))
    target = int(bb * (pos_mult + edge_add)) + dead_money
    return min(max_r, max(min_r, target))

def compute_dynamic_3bet_size(pot: int, call_chips: int, in_pos: bool, equity: float, min_r: int, max_r: int) -> int:
    mult = (2.6 if in_pos else 3.2) + max(0.0, (equity - 0.55) * 2.0)
    target = int(call_chips * mult) + int(pot * 0.30)
    return min(max_r, max(min_r, target))

def compute_dynamic_cbet_size(equity: float, pot: int, min_b: int, max_b: int, in_pos: bool, wetness: float, spr: float) -> int:
    alpha = min_b / max(pot + min_b, 1)
    base_ratio = alpha * (0.8 if in_pos else 1.0)
    edge_ratio = max(0.0, (equity - 0.45) * 0.5)
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
    stack_bb = stack / bb if bb else 100.0
    spr = stack / max(pot, 1)

    pot_odds = call_chips / max(pot + call_chips, 1) if call_chips else 0.0
    mdf = 1.0 - pot_odds if pot_odds > 0 else 1.0
    risk_ratio = call_chips / stack if stack > 0 else 0.0

    btn = table.get("buttonSeatNumber")
    in_pos = self_seat == btn

    is_pf = len(board) == 0
    street_idx = 0 if is_pf else (1 if len(board) == 3 else (2 if len(board) == 4 else 3))

    wetness, is_paired_board = evaluate_board_texture(board)
    blockers = evaluate_blockers(hole, board)

    max_risk = dynamic_max_risk(stack_bb, spr)
    stack_off_req = dynamic_stack_off_req(stack_bb, wetness)
    kelly_f = dynamic_kelly_fraction(stack_bb)
    realization = compute_equity_realization(in_pos, wetness, spr, street_idx)

    sims_count = 500 if is_pf else 700
    raw_equity = estimate_equity(hole, board, sims=sims_count, deadline_s=deadline_s)
    equity = update_bayesian_equity(raw_equity, call_chips, pot, blockers, wetness, street_idx)
    realized_equity = min(0.99, equity * realization)
    kf = kelly_criterion_fraction(realized_equity, pot, call_chips, fraction=kelly_f)

    short_stack_threshold = (8.0 + (4.0 if in_pos else 0.0)) * (1.5 if bb else 1.0)
    if is_pf and stack_bb <= short_stack_threshold:
        if realized_equity >= 0.50 and allowed.get("canRaise"):
            rr = allowed.get("raiseRange") or {}
            max_r = int(rr.get("max") or stack)
            return _build("raise", max_r, table, allowed, eq=equity, po=0, msg="Push short")
        if "check" in available:
            return _build("check", None, table, allowed, eq=0, po=0, msg="Check short")
        return _build("fold", None, table, allowed, eq=0, po=pot_odds, msg="Fold short")

    if is_pf:
        if call_chips <= bb:
            opponents_behind = max(1, sum(1 for s in seats if s.get("status") == "Active" and s.get("seatNumber") != self_seat))
            p_fold_each = 0.45 + (0.10 if in_pos else 0.0)
            p_fold_all = p_fold_each ** opponents_behind
            
            min_r = int((allowed.get("raiseRange") or {}).get("min") or bb * 2)
            max_r = int((allowed.get("raiseRange") or {}).get("max") or min_r)
            open_size = compute_dynamic_open_size(realized_equity, in_pos, bb, min_r, max_r, pot)
            
            ev_raise = p_fold_all * pot + (1.0 - p_fold_all) * (realized_equity * (pot + open_size * 2) - open_size)
            
            if ev_raise > 0 and (allowed.get("canRaise") or allowed.get("canBet")):
                if allowed.get("canRaise"):
                    return _build("raise", open_size, table, allowed, eq=equity, po=pot_odds, msg="Dynamic EV Open Raise")
                if allowed.get("canBet"):
                    return _build("bet", open_size, table, allowed, eq=equity, po=0, msg="Dynamic EV Open Bet")

            if "check" in available:
                return _build("check", None, table, allowed, eq=equity, po=0, msg="Check BB PF")
            
            ev_call = realized_equity * (pot + call_chips) - call_chips
            if ev_call >= 0:
                return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="Call Limp EV")

            return _build("fold", None, table, allowed, eq=equity, po=pot_odds, msg="Fold PF Unopened")

        if risk_ratio > max_risk and equity < stack_off_req:
            return _build("fold", None, table, allowed, eq=equity, po=pot_odds, msg="Risk fold PF")

        ev_call = realized_equity * (pot + call_chips) - call_chips
        if ev_call >= 0 or realized_equity >= pot_odds:
            if kf > 0.08 and allowed.get("canRaise"):
                rr = allowed.get("raiseRange") or {}
                min_r = int(rr.get("min") or call_chips * 2)
                max_r = int(rr.get("max") or min_r)
                size = compute_dynamic_3bet_size(pot, call_chips, in_pos, realized_equity, min_r, max_r)
                return _build("raise", size, table, allowed, eq=equity, po=pot_odds, msg="Dynamic Value 3bet")
            return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="Dynamic Call PF")

        return _build("fold", None, table, allowed, eq=equity, po=pot_odds, msg="Fold PF vs Raise")

    if call_chips > 0:
        if risk_ratio > max_risk and equity < stack_off_req:
            return _build("fold", None, table, allowed, eq=equity, po=pot_odds, msg="Risk fold Postflop")

        ev_call = realized_equity * (pot + call_chips) - call_chips
        
        if ev_call >= 0 or realized_equity >= pot_odds:
            if realized_equity >= stack_off_req and allowed.get("canRaise") and kf > 0.08:
                rr = allowed.get("raiseRange") or {}
                min_r = int(rr.get("min") or call_chips * 2)
                max_r = int(rr.get("max") or min_r)
                size = compute_kelly_bet_size(realized_equity, pot + call_chips, min_r, max_r, kelly_f, spr, wetness)
                return _build("raise", size, table, allowed, eq=equity, po=pot_odds, msg="Dynamic Monster Raise")
            return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="Dynamic Value Call")

        if realized_equity >= pot_odds * mdf and kf > 0.0:
            return _build("call", None, table, allowed, eq=equity, po=pot_odds, msg="MDF Defense Call")

        return _build("fold", None, table, allowed, eq=equity, po=pot_odds, msg="Negative EV Fold")

    if allowed.get("canBet"):
        min_b = int((allowed.get("betRange") or {}).get("min") or max(pot // 3, 2))
        max_b = int((allowed.get("betRange") or {}).get("max") or min_b)
        alpha = min_b / max(pot + min_b, 1)

        if realized_equity >= alpha:
            size = compute_dynamic_cbet_size(realized_equity, pot, min_b, max_b, in_pos, wetness, spr)
            return _build("bet", size, table, allowed, eq=equity, po=0, msg="Dynamic EV C-Bet")

    if "check" in available:
        return _build("check", None, table, allowed, eq=equity, po=0, msg="Check")

    return _build("fold", None, table, allowed, eq=equity, po=pot_odds, msg="Fallback Fold")

if __name__ == "__main__":
    sys.exit(main())