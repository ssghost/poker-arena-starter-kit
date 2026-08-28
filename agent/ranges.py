from __future__ import annotations
from typing import Set

RANK_ORDER = "23456789TJQKA"

def get_canonical_hand(hole: list) -> str:
    if len(hole) != 2:
        return ""
    c1, c2 = hole[0], hole[1]
    r1, r2 = c1[:-1], c2[:-1]
    s1, s2 = c1[-1], c2[-1]
    v1, v2 = RANK_ORDER.find(r1), RANK_ORDER.find(r2)
    if v1 < 0 or v2 < 0:
        return ""
    if v1 < v2:
        r1, r2 = r2, r1
        v1, v2 = v2, v1
    if v1 == v2:
        return f"{r1}{r2}"
    suffix = "s" if s1 == s2 else "o"
    return f"{r1}{r2}{suffix}"

RANGE_UTG_OPEN: Set[str] = {
    "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77",
    "AKs", "AQs", "AJs", "ATs", "A5s", "A4s",
    "KQs", "KJs", "KTs",
    "QJs", "QTs",
    "JTs", "T9s", "98s",
    "AKo", "AQo"
}

RANGE_MP_OPEN: Set[str] = RANGE_UTG_OPEN | {
    "66", "55",
    "A9s", "A8s", "A3s", "A2s",
    "K9s", "Q9s", "J9s", "87s", "76s",
    "AJo", "KQo"
}

RANGE_CO_OPEN: Set[str] = RANGE_MP_OPEN | {
    "44", "33", "22",
    "A7s", "A6s",
    "K8s", "K7s", "K6s",
    "Q8s", "J8s", "T8s", "65s", "54s",
    "ATo", "KJo", "QJo", "JTo"
}

RANGE_BTN_OPEN: Set[str] = RANGE_CO_OPEN | {
    "K5s", "K4s", "K3s", "K2s",
    "Q7s", "Q6s", "Q5s", "Q4s",
    "J7s", "J6s", "T7s", "97s", "86s", "75s", "64s", "53s", "43s",
    "A9o", "A8o", "A7o", "A6o", "A5o",
    "KTo", "K9o", "QTo", "Q9o", "J9o", "T9o", "98o"
}

RANGE_SB_OPEN: Set[str] = {
    "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
    "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
    "KQs", "KJs", "KTs", "K9s", "K8s", "K7s", "K6s", "K5s",
    "QJs", "QTs", "Q9s", "Q8s", "Q7s",
    "JTs", "J9s", "J8s", "T9s", "T8s", "98s", "87s", "76s", "65s", "54s",
    "AKo", "AQo", "AJo", "ATo", "A9o", "A8o",
    "KQo", "KJo", "KTo", "QJo", "QTo", "JTo"
}

RANGE_PREMIUM_3BET: Set[str] = {
    "AA", "KK", "QQ", "JJ", "AKs", "AKo", "AQs"
}

RANGE_VALUE_3BET: Set[str] = RANGE_PREMIUM_3BET | {
    "TT", "AJs", "KQs", "AQo"
}

RANGE_CALL_3BET_IP: Set[str] = {
    "99", "88", "77", "66",
    "ATs", "A9s", "A5s", "A4s",
    "KJs", "KTs", "QJs", "QTs", "JTs", "T9s", "98s",
    "AJo", "KQo"
}

def is_in_open_range(hole: list, position_idx: int, total_active: int) -> bool:
    canonical = get_canonical_hand(hole)
    if not canonical:
        return False
    if position_idx == total_active - 1:
        target_range = RANGE_BTN_OPEN
    elif position_idx == total_active - 2:
        target_range = RANGE_CO_OPEN
    elif position_idx == 0:
        target_range = RANGE_UTG_OPEN
    else:
        target_range = RANGE_MP_OPEN
    return canonical in target_range

def is_in_3bet_range(hole: list) -> bool:
    canonical = get_canonical_hand(hole)
    return canonical in RANGE_VALUE_3BET

def is_in_call_3bet_range(hole: list, in_pos: bool) -> bool:
    canonical = get_canonical_hand(hole)
    if canonical in RANGE_VALUE_3BET:
        return True
    if in_pos and canonical in RANGE_CALL_3BET_IP:
        return True
    return False