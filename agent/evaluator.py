from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict

RANK_ORDER = "23456789TJQKA"

@dataclass
class BoardTexture:
    wetness: float
    is_paired: bool
    is_monotone: bool
    is_two_tone: bool
    is_rainbow: bool
    max_suit_count: int
    high_card_count: int

def evaluate_board_texture(board: list) -> BoardTexture:
    if len(board) < 3:
        return BoardTexture(
            wetness=0.0,
            is_paired=False,
            is_monotone=False,
            is_two_tone=False,
            is_rainbow=True,
            max_suit_count=0,
            high_card_count=0,
        )

    board_ranks = [c[:-1] for c in board]
    board_suits = [c[-1] for c in board]

    is_paired = len(set(board_ranks)) < len(board_ranks)

    suit_counts = [board_suits.count(s) for s in "shdc"]
    max_suit = max(suit_counts)
    is_monotone = max_suit >= 3
    is_two_tone = max_suit == 2 and len(set(board_suits)) <= 3
    is_rainbow = len(set(board_suits)) >= len(board)

    flush_wetness = max(0.0, (max_suit - 1) / max(len(board) - 1, 1))

    vals = sorted([RANK_ORDER.find(r) for r in board_ranks if RANK_ORDER.find(r) >= 0])
    conn_count = 0
    for i in range(len(vals) - 1):
        diff = vals[i + 1] - vals[i]
        if diff == 1:
            conn_count += 2
        elif diff == 2:
            conn_count += 1

    conn_wetness = min(0.50, conn_count / max(len(vals) * 2, 1))
    paired_penalty = -0.10 if is_paired else 0.0

    wetness = max(0.0, min(1.0, flush_wetness + conn_wetness + paired_penalty))
    high_card_count = sum(1 for v in vals if v >= 9)

    return BoardTexture(
        wetness=wetness,
        is_paired=is_paired,
        is_monotone=is_monotone,
        is_two_tone=is_two_tone,
        is_rainbow=is_rainbow,
        max_suit_count=max_suit,
        high_card_count=high_card_count,
    )

def evaluate_blockers(hole: list, board: list) -> Dict[str, bool]:
    if len(hole) != 2:
        return {"nfd_blocker": False, "top_blocker": False}

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
    board_max = max([RANK_ORDER.find(r) for r in board_ranks if RANK_ORDER.find(r) >= 0], default=-1)
    hole_ranks = [c[:-1] for c in hole]
    top_blocker = any(RANK_ORDER.find(r) >= board_max for r in hole_ranks if RANK_ORDER.find(r) >= 0) if board_max >= 0 else False

    return {"nfd_blocker": nfd_blocker, "top_blocker": top_blocker}

def classify_hand(hole: list, board: list) -> str:
    if len(hole) != 2 or len(board) < 3:
        return "air"

    board_ranks = [c[:-1] for c in board]
    hole_ranks = [c[:-1] for c in hole]
    board_vals = [RANK_ORDER.find(r) for r in board_ranks if RANK_ORDER.find(r) >= 0]
    hole_vals = [RANK_ORDER.find(r) for r in hole_ranks if RANK_ORDER.find(r) >= 0]
    if not board_vals or len(hole_vals) < 2:
        return "air"

    max_b = max(board_vals)
    h1, h2 = hole_vals[0], hole_vals[1]
    is_pocket_pair = (h1 == h2)

    all_suits = [c[-1] for c in board + hole]
    hole_suits = [c[-1] for c in hole]
    is_flush = any(all_suits.count(s) >= 5 for s in "shdc")

    hit_count = sum(1 for v in hole_vals if v in board_vals)
    is_trips_or_set = (is_pocket_pair and h1 in board_vals) or any(board_ranks.count(r) >= 2 and r in hole_ranks for r in hole_ranks)

    if is_flush or is_trips_or_set or hit_count >= 2:
        return "nut_made"

    if (is_pocket_pair and h1 > max_b) or any(v == max_b and v in board_vals for v in hole_vals):
        return "tptk"

    has_flush_draw = False
    for s in "shdc":
        if all_suits.count(s) == 4 and s in hole_suits:
            has_flush_draw = True
            break

    all_vals = sorted(list(set(board_vals + hole_vals)))
    has_oesd = False
    has_gutshot = False
    if len(all_vals) >= 4:
        for i in range(len(all_vals) - 3):
            sub = all_vals[i:i+4]
            span = sub[-1] - sub[0]
            if span == 3:
                has_oesd = True
                break
            elif span == 4:
                has_gutshot = True

    if has_flush_draw and (has_oesd or has_gutshot):
        return "combo_draw"
    if has_flush_draw or has_oesd:
        return "strong_draw"
    if hit_count == 1 or is_pocket_pair:
        return "marginal_pair"
    if has_gutshot:
        return "weak_draw"

    return "air"

def compute_equity_realization(in_pos: bool, texture: BoardTexture, hand_cat: str, spr: float, street_idx: int, n_active: int) -> float:
    if street_idx == 0:
        pos_factor = 1.05 if in_pos else 0.95
        return max(0.85, min(1.15, pos_factor))

    pos_factor = 1.10 if in_pos else 0.90
    wet_factor = 1.0 - (texture.wetness * 0.12)
    spr_factor = 1.0 / (1.0 + 0.015 * min(spr, 20.0))

    cat_factors = {
        "nut_made": 1.25,
        "tptk": 1.05,
        "combo_draw": 1.15,
        "strong_draw": 1.00,
        "marginal_pair": 0.75,
        "weak_draw": 0.55,
        "air": 0.35,
    }
    cat_factor = cat_factors.get(hand_cat, 0.80)

    r0 = pos_factor * wet_factor * spr_factor * cat_factor
    multiway_adj = 1.0 / math.sqrt(max(1.0, 1.0 + 0.35 * (n_active - 1)))
    return max(0.20, min(1.35, r0 * multiway_adj))