import argparse
import json
import sys
import time
from pathlib import Path
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from my_agent import decide

CREDS_PATH = Path(".arena-credentials")
BASE_URL = "https://arena.dev.fun/api/arena"
BIG_BLIND = 2
DEFAULT_HANDS = 20
PROGRESS_INTERVAL = 5

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

def run_pvp_loop(competition_id: str, max_hands: int = DEFAULT_HANDS):
    key = load()
    headers = {"x-arena-api-key": key}
    client = httpx.Client(timeout=20.0)

    print(f"[arena] hero=decide() from my_agent.py")
    print(f"[arena] competition={competition_id}")
    print(f"[arena] blinds=1/{BIG_BLIND}")
    print(f"[arena] playing {max_hands} hands ...")

    hands = 0
    wins = losses = pushes = 0
    net = 0
    start = time.time()

    prev_stack = None
    initial_stack = None

    while hands < max_hands:
        try:
            resp = client.get(
                f"{BASE_URL}/texas/pending-actions",
                params={"competitionId": competition_id},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.RemoteProtocolError:
            client.close()
            client = httpx.Client(timeout=20.0)
            continue
        except Exception:
            time.sleep(0.5)
            continue

        tables = data.get("tables", [])
        if not tables:
            time.sleep(0.3)
            continue

        for table in tables:
            table_id = table.get("tableId")

            stack = get_stack(table)

            if initial_stack is None and stack:
                initial_stack = stack
                prev_stack = stack

            # hand ends when board resets
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

            action = decide(table, deadline_s=5)
            action["tableId"] = table_id

            try:
                client.post(
                    f"{BASE_URL}/texas/action",
                    headers=headers,
                    json=action,
                )
            except httpx.RemoteProtocolError:
                client.close()
                client = httpx.Client(timeout=20.0)
                continue

        time.sleep(0.25)

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
    parser.add_argument("--max-hands", type=int, default=DEFAULT_HANDS)
    args = parser.parse_args()

    run_pvp_loop(args.competition_id, args.max_hands)