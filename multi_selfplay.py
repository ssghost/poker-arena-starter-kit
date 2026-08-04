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
    decide_funcs: list[Callable],
    agent_seat_map: list[int],
    starting_stack: int,
    small_blind: int,
    big_blind: int,
    stats_a: dict,
) -> int:
    stacks = [starting_stack, starting_stack, starting_stack]

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
        raw_blinds_or_straddles=(small_blind, big_blind, 0),
        min_bet=big_blind,
        raw_starting_stacks=(starting_stack, starting_stack, starting_stack),
        player_count=3,
    )

    seat_to_agent = [0, 0, 0]
    for agent_idx, seat_idx in enumerate(agent_seat_map):
        seat_to_agent[seat_idx] = agent_idx

    hero_a_seat = agent_seat_map[0]
    hero_a_vpip = False
    hero_a_pfr = False
    hero_a_river_call = False

    while state.status and state.actor_index is not None:
        actor = state.actor_index
        agent_idx = seat_to_agent[actor]
        fn = decide_funcs[agent_idx]

        table = _build_table(
            state,
            actor,
            "triple",
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

        if actor == hero_a_seat:
            act_type = action.get("action")
            street = table.get("street")
            if act_type in ("call", "bet", "raise") and street == "Preflop":
                hero_a_vpip = True
            if act_type in ("bet", "raise") and street == "Preflop":
                hero_a_pfr = True
            if act_type == "call" and street == "River":
                hero_a_river_call = True

        _apply_action(state, action, big_blind)

    delta_a = int(state.stacks[hero_a_seat]) - starting_stack

    stats_a["vpip"] += int(hero_a_vpip)
    stats_a["pfr"] += int(hero_a_pfr)
    stats_a["river_calls"] += int(hero_a_river_call)
    stats_a["net"] += delta_a

    return delta_a

def run_triple(
    agent_a: str, agent_b: str, agent_c: str, hands: int, seed: Optional[int]
):
    if seed is not None:
        random.seed(seed)

    decide_a = load_decide(agent_a)
    decide_b = load_decide(agent_b)
    decide_c = load_decide(agent_c)
    decide_funcs = [decide_a, decide_b, decide_c]

    starting_stack = 1000
    small_blind = 1
    big_blind = 2

    print(f"[triple-selfplay] Target Agent A = {agent_a}")
    print(f"[triple-selfplay] Opponents = B: {agent_b}, C: {agent_c}")
    print(f"[triple-selfplay] stacks={starting_stack} blinds={small_blind}/{big_blind}")
    print(f"[triple-selfplay] playing {hands} hands ...")

    stats_a = {"vpip": 0, "pfr": 0, "river_calls": 0, "net": 0}
    t0 = time.time()

    for i in range(hands):
        seat_a = i % 3
        seat_b = (i + 1) % 3
        seat_c = (i + 2) % 3

        play_one_hand(
            decide_funcs,
            [seat_a, seat_b, seat_c],
            starting_stack,
            small_blind,
            big_blind,
            stats_a,
        )

        if (i + 1) % max(1, hands // 10) == 0:
            print(f"  ... {i+1}/{hands} hands  netA={stats_a['net']:+d}")

    elapsed = time.time() - t0

    bb100_a = (stats_a["net"] / big_blind) / hands * 100
    vpip_pct_a = (stats_a["vpip"] / hands) * 100
    pfr_pct_a = (stats_a["pfr"] / hands) * 100
    river_call_pct_a = (stats_a["river_calls"] / hands) * 100

    print(f"Agent A bb/100       : {bb100_a:+.1f}")
    print(f"Agent A Net Chips    : {stats_a['net']:+d}")
    print(f"Agent A VPIP %       : {vpip_pct_a:.1f}%")
    print(f"Agent A PFR %        : {pfr_pct_a:.1f}%")
    print(f"Agent A River Calls %: {river_call_pct_a:.1f}%")
    print(f"Elapsed Time         : {elapsed:.1f}s")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-a", required=True)
    parser.add_argument("--agent-b", required=True)
    parser.add_argument("--agent-c", required=True)
    parser.add_argument("--hands", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    run_triple(args.agent_a, args.agent_b, args.agent_c, args.hands, args.seed)