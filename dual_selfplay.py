from __future__ import annotations

import argparse
import importlib.util
import random
import time
from pathlib import Path
from typing import Callable, Optional

from pokerkit import (  # type: ignore
    Automation,
    NoLimitTexasHoldem,
    State,
)

from examples.selfplay import _build_table, _apply_action


def load_decide(path: str) -> Callable:
    p = Path(path).resolve()
    if not p.exists():
        raise SystemExit(f"Agent file not found: {p}")

    spec = importlib.util.spec_from_file_location("user_agent", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "decide"):
        raise SystemExit(f"{p} does not define decide()")

    return mod.decide


def play_one_hand(
    decide_a: Callable,
    decide_b: Callable,
    starting_stack: int,
    small_blind: int,
    big_blind: int,
    hero_a_index: int,
    stats: dict,
    hand_id: int,
) -> int:
    stacks = [starting_stack, starting_stack]

    state: State = NoLimitTexasHoldem.create_state(
        automations=(
            Automation.ANTE_POSTING,
            Automation.BET_COLLECTION,
            Automation.BLIND_OR_STRADDLE_POSTING,
            Automation.CARD_BURNING,
            Automation.HOLE_DEALING,
            Automation.BOARD_DEALING,
            Automation.RUNOUT_COUNT_SELECTION,
            Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
            Automation.HAND_KILLING,
            Automation.CHIPS_PUSHING,
            Automation.CHIPS_PULLING,
        ),
        ante_trimming_status=True,
        raw_antes=0,
        raw_blinds_or_straddles=(small_blind, big_blind),
        min_bet=big_blind,
        raw_starting_stacks=(starting_stack, starting_stack),
        player_count=2,
    )

    hero_vpip = False
    hero_pfr = False
    hero_river_call = False

    while state.status and state.actor_index is not None:
        actor = state.actor_index
        fn = decide_a if actor == hero_a_index else decide_b

        table = _build_table(
            state,
            actor,
            "dual",
            stacks,
            small_blind,
            big_blind,
        )

        try:
            action = fn(table, deadline_s=10.0)
        except TypeError:
            action = fn(table)

        if not isinstance(action, dict):
            action = {"action": "fold"}

        if actor == hero_a_index:
            if action.get("action") in ("call", "bet", "raise"):
                if table["street"] == "Preflop":
                    hero_vpip = True
            if action.get("action") in ("bet", "raise"):
                if table["street"] == "Preflop":
                    hero_pfr = True
            if action.get("action") == "call" and table["street"] == "River":
                hero_river_call = True

        _apply_action(state, action, big_blind)

    delta = int(state.stacks[hero_a_index]) - starting_stack

    stats["vpip"] += int(hero_vpip)
    stats["pfr"] += int(hero_pfr)
    stats["river_calls"] += int(hero_river_call)
    stats["hands"] += 1
    stats["deltas"].append(delta)

    return delta


def run_dual(agent_a: str, agent_b: str, hands: int, seed: Optional[int]):

    if seed is not None:
        random.seed(seed)

    decide_a = load_decide(agent_a)
    decide_b = load_decide(agent_b)

    starting_stack = 1000
    small_blind = 1
    big_blind = 2

    print(f"[dual-selfplay] A = {agent_a}")
    print(f"[dual-selfplay] B = {agent_b}")
    print(f"[dual-selfplay] stacks={starting_stack} blinds={small_blind}/{big_blind}")
    print(f"[dual-selfplay] playing {hands} hands ...")

    net_a = 0
    stats = {
        "vpip": 0,
        "pfr": 0,
        "river_calls": 0,
        "hands": 0,
        "deltas": [],
    }

    t0 = time.time()

    for i in range(hands):
        hero_index = i % 2
        delta = play_one_hand(
            decide_a,
            decide_b,
            starting_stack,
            small_blind,
            big_blind,
            hero_index,
            stats,
            i + 1,
        )
        net_a += delta

        if (i + 1) % max(1, hands // 10) == 0:
            print(f"  ... {i+1}/{hands} hands  netA={net_a:+d}")

    elapsed = time.time() - t0
    bb100_a = (net_a / big_blind) / hands * 100
    bb100_b = -bb100_a

    vpip_pct = stats["vpip"] / hands * 100
    pfr_pct = stats["pfr"] / hands * 100
    river_call_pct = stats["river_calls"] / hands * 100

    print(f"Agent A bb/100      : {bb100_a:+.1f}")
    print(f"Agent B bb/100      : {bb100_b:+.1f}")
    print(f"net A chips         : {net_a:+d}")
    print(f"VPIP %              : {vpip_pct:.1f}")
    print(f"PFR %               : {pfr_pct:.1f}")
    print(f"River Calls %       : {river_call_pct:.1f}")
    print(f"elapsed             : {elapsed:.1f}s")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-a", required=True)
    parser.add_argument("--agent-b", required=True)
    parser.add_argument("--hands", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    run_dual(args.agent_a, args.agent_b, args.hands, args.seed)