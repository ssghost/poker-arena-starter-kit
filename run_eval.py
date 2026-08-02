import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CREDS_PATH = Path(".arena-credentials")
BASE_URL = "https://arena.dev.fun/api/arena"
BIG_BLIND = 2
DEFAULT_HANDS = 20
WAIT_LOG_INTERVAL = 10

def load_agent(agent_path: str):
    p = Path(agent_path).resolve()
    if not p.exists():
        print(f"Agent file not found: {p}")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("user_agent", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "decide"):
        print(f"{agent_path} does not define decide()")
        sys.exit(1)

    return mod.decide


def load():
    if not CREDS_PATH.exists():
        print("Missing .arena-credentials")
        sys.exit(1)
    return json.loads(CREDS_PATH.read_text())["apiKey"]


def start_eval_benchmark(client: httpx.Client, headers: dict, competition_id: str):
    print("[arena] attempting to start eval benchmark...")
    try:
        r = client.post(
            f"{BASE_URL}/texas/benchmark/start",
            headers=headers,
            json={"competitionId": competition_id},
        )
        if r.status_code == 200:
            print("[arena] successfully started eval benchmark.")
            return r.json()
        else:
            print(f"[arena] start response: {r.status_code} {r.text}")
            return None
    except Exception as e:
        print(f"[arena] start benchmark failed: {e}")
        return None


def run_eval_loop(competition_id: str, decide_fn, max_hands: int):
    key = load()
    headers = {"x-arena-api-key": key, "Content-Type": "application/json"}
    client = httpx.Client(timeout=20.0)

    start_eval_benchmark(client, headers, competition_id)

    print(f"[arena] hero=decide()")
    print(f"[arena] competition={competition_id}")
    print(f"[arena] blinds=1/{BIG_BLIND}")
    print(f"[arena] target hands={max_hands} ...")

    start_time = time.time()
    last_wait_log = time.time()

    completed_hands = 0
    raw_bb100 = 0.0
    raw_chip_delta = 0

    while completed_hands < max_hands:
        try:
            resp = client.get(
                f"{BASE_URL}/texas/pending-actions",
                params={"competitionId": competition_id},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            time.sleep(1)
            continue

        match_info = data.get("match") or {}
        if match_info:
            current_completed = match_info.get("completedHands", 0)
            if current_completed != completed_hands:
                completed_hands = current_completed
                raw_chip_delta = match_info.get("rawChipDelta", 0)
                raw_bb100 = match_info.get("rawBbPer100", 0.0)
                print(
                    f"  ... {completed_hands}/{max_hands} hands  net={raw_chip_delta:+d} chips  bb/100={raw_bb100:+.1f}"
                )

            if match_info.get("status") in ["Completed", "Failed", "Cancelled"]:
                print(f"[arena] benchmark session status: {match_info.get('status')}")
                break

        tables = data.get("tables", [])

        if not tables:
            if time.time() - last_wait_log > WAIT_LOG_INTERVAL:
                print("[arena] waiting for panel / table action...")
                last_wait_log = time.time()
            time.sleep(0.5)
            continue

        for table in tables:
            table_id = table.get("tableId")
            if not table.get("allowedActions"):
                continue

            action = decide_fn(table, deadline_s=5)
            action["tableId"] = table_id

            try:
                client.post(
                    f"{BASE_URL}/texas/action",
                    headers=headers,
                    json=action,
                )
            except Exception:
                continue

        time.sleep(0.2)

    client.close()
    elapsed = time.time() - start_time
    hands_per_sec = completed_hands / elapsed if elapsed > 0 else 0

    print("\n" + "=" * 40)
    print(f"  hands       : {completed_hands}")
    print(f"  opponent    : Reference Panel (PVE)")
    print(f"  net chips   : {raw_chip_delta:+d}")
    print(f"  bb/100      : {raw_bb100:+.1f}")
    print(f"  elapsed     : {elapsed:.1f}s  ({hands_per_sec:.2f} hands/s)")
    print("=" * 40)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Poker PVE Eval Benchmark")
    parser.add_argument(
        "--competition-id",
        default="seed_poker_eval_s1",
        help="Competition ID for Eval (default: seed_poker_eval_s1)",
    )
    parser.add_argument("--agent", default="my_agent.py", help="Path to agent script")
    parser.add_argument(
        "--max-hands",
        type=int,
        default=DEFAULT_HANDS,
        help="Target hands to play",
    )
    args = parser.parse_args()

    decide_fn = load_agent(args.agent)

    run_eval_loop(
        competition_id=args.competition_id,
        decide_fn=decide_fn,
        max_hands=args.max_hands,
    )