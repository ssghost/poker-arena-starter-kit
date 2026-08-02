import argparse
import json
import sys
import time
import importlib.util
from pathlib import Path
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CREDS_PATH = Path(".arena-credentials")
BASE_URL = "https://arena.dev.fun/api/arena"
BIG_BLIND = 2
DEFAULT_HANDS = 20
PROGRESS_INTERVAL = 5
WAIT_LOG_INTERVAL = 10
REJOIN_INTERVAL = 100  


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


def get_stack(table: dict):
    self_seat = table.get("selfSeatNumber")
    for s in table.get("seats", []):
        if s.get("seatNumber") == self_seat:
            return int(s.get("stackChips") or 0)
    return 0


def try_join(client, headers, competition_id):
    print("[arena] attempting to join competition...")
    try:
        r = client.post(
            f"{BASE_URL}/texas/join",
            headers=headers,
            json={"competitionId": competition_id},
        )
        if r.status_code == 200:
            print("[arena] successfully joined competition.")
        elif r.status_code == 400 and "already" in r.text.lower():
            print("[arena] already joined.")
        elif r.status_code == 409:
            print("[arena] already seated (table limit).")
        else:
            print(f"[arena] join response: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[arena] join failed: {e}")


def leave_competition(client, headers, competition_id):
    try:
        client.post(
            f"{BASE_URL}/texas/leave",
            headers=headers,
            json={"competitionId": competition_id},
        )
        print("[arena] left table")
    except Exception as e:
        print(f"[arena] leave failed: {e}")


def join_competition(client, headers, competition_id):
    try:
        client.post(
            f"{BASE_URL}/texas/join",
            headers=headers,
            json={"competitionId": competition_id},
        )
        print("[arena] rejoined table")
    except Exception as e:
        print(f"[arena] rejoin failed: {e}")


def run_pvp_loop(competition_id: str, decide_fn, max_hands: int):
    key = load()
    headers = {"x-arena-api-key": key}
    client = httpx.Client(timeout=20.0)
    try_join(client, headers, competition_id)

    print(f"[arena] hero=decide()")
    print(f"[arena] competition={competition_id}")
    print(f"[arena] blinds=1/{BIG_BLIND}")
    print(f"[arena] playing {max_hands} hands ...")

    hands = 0
    wins = losses = pushes = 0
    net = 0
    start = time.time()

    prev_stack = None
    initial_stack = None

    last_wait_log = time.time()
    last_rejoin_time = time.time()

    while hands < max_hands:
        if time.time() - last_rejoin_time > REJOIN_INTERVAL:
            print("[arena] 100s elapsed → force rejoin")
            leave_competition(client, headers, competition_id)
            time.sleep(2)
            join_competition(client, headers, competition_id)
            last_rejoin_time = time.time()

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

        tables = data.get("tables", [])

        if not tables:
            if time.time() - last_wait_log > WAIT_LOG_INTERVAL:
                print("[arena] waiting for table / opponent...")
                last_wait_log = time.time()
            time.sleep(1)
            continue

        for table in tables:
            table_id = table.get("tableId")
            stack = get_stack(table)

            if initial_stack is None and stack:
                initial_stack = stack
                prev_stack = stack

            if prev_stack is not None and stack != prev_stack and table.get("boardCards") == []:
                diff = stack - prev_stack
                hands += 1
                net = stack - initial_stack

                if diff > 0:
                    wins += 1
                elif diff < 0:
                    losses += 1
                else:
                    pushes += 1

                prev_stack = stack

                if hands % PROGRESS_INTERVAL == 0 or hands == max_hands:
                    print(f"  ... {hands}/{max_hands} hands  net={net:+d} chips")

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

        time.sleep(0.3)

    client.close()

    elapsed = time.time() - start
    hands_per_sec = hands / elapsed if elapsed > 0 else 0
    bb100 = (net / hands * (100 / BIG_BLIND)) if hands else 0

    print(f"  hands       : {hands}")
    print(f"  opponent    : Arena Live")
    print(f"  wins/losses : {wins}/{losses}  (push: {pushes})")
    print(f"  net chips   : {net:+d}")
    print(f"  bb/100      : {bb100:+.1f}")
    print(f"  elapsed     : {elapsed:.1f}s  ({hands_per_sec:.2f} hands/s)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition-id", required=True)
    parser.add_argument("--agent", default="my_agent.py")
    parser.add_argument("--max-hands", type=int, default=DEFAULT_HANDS)
    args = parser.parse_args()

    decide_fn = load_agent(args.agent)

    run_pvp_loop(
        competition_id=args.competition_id,
        decide_fn=decide_fn,
        max_hands=args.max_hands,
    )