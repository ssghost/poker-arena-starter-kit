import argparse
import json
import sys
import time
from pathlib import Path
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent
EXAMPLES_DIR = PROJECT_ROOT / "examples"

if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from my_agent import decide

CREDS_PATH = Path(".arena-credentials")
BASE_URL = "https://arena.dev.fun/api/arena"
BIG_BLIND = 2


def load() -> str:
    if not CREDS_PATH.exists():
        print("Error: .arena-credentials file not found.", file=sys.stderr)
        sys.exit(1)

    try:
        creds = json.loads(CREDS_PATH.read_text())
    except Exception as e:
        print(f"Error reading .arena-credentials: {e}", file=sys.stderr)
        sys.exit(1)

    key = creds.get("apiKey")
    return key


def get_hero_stack(table: dict) -> int:
    self_seat = table.get("selfSeatNumber")
    seats = table.get("seats") or []
    for s in seats:
        if s.get("seatNumber") == self_seat:
            val = s.get("stackChips")
            if isinstance(val, (int, float)):
                return int(val)
    return 0


def run_pvp_loop(competition_id: str, max_hands: int = 50):
    key = load()
    headers = {"x-arena-api-key": key, "Content-Type": "application/json"}
    client = httpx.Client(timeout=30.0)

    try:
        r = client.post(
            f"{BASE_URL}/texas/join",
            headers=headers,
            json={"competitionId": competition_id},
        )
        if r.status_code == 400 and "already in" in r.text.lower():
            print(f"Agent already joined {competition_id}.")
        elif r.status_code != 200:
            print(f"Join status: {r.status_code} - {r.text}")
        else:
            print(f"Joined competition {competition_id}.")
    except Exception as e:
        print(f"Join request error: {e}")

    hands_finished = 0
    wins = 0
    losses = 0
    pushes = 0
    start_time = time.time()

    initial_stack: int | None = None
    prev_stack: int | None = None
    net_chips: int = 0

    print(f"Running until {max_hands} finished hands...")

    try:
        while hands_finished < max_hands:
            pending_resp = client.get(
                f"{BASE_URL}/texas/pending-actions?competitionId={competition_id}",
                headers=headers,
            )
            pending_resp.raise_for_status()
            pending_data = pending_resp.json()
            tables = pending_data.get("tables", [])

            if not tables:
                time.sleep(1.0)
                continue

            for table in tables:
                table_id = table.get("tableId")
                deadline_ms = table.get("actionDeadlineAt") or 0
                deadline_s = (
                    max(0.5, (deadline_ms / 1000.0) - time.time())
                    if deadline_ms
                    else 10.0
                )

                current_stack = get_hero_stack(table)

                if initial_stack is None and current_stack > 0:
                    initial_stack = current_stack
                    prev_stack = current_stack

                board = table.get("boardCards") or []
                hand_finished = len(board) == 0 and prev_stack is not None

                if hand_finished and current_stack != prev_stack:
                    diff = current_stack - prev_stack
                    hands_finished += 1
                    net_chips = current_stack - (initial_stack or current_stack)

                    if diff > 0:
                        wins += 1
                        result_str = f"+{diff}"
                    elif diff < 0:
                        losses += 1
                        result_str = f"{diff}"
                    else:
                        pushes += 1
                        result_str = "0"

                    print(
                        f"[{hands_finished}/{max_hands}] "
                        f"Hand Net: {result_str} | Total Net: {net_chips:+d}"
                    )

                    prev_stack = current_stack

                action_payload = decide(table, deadline_s=deadline_s)
                action_payload["tableId"] = table_id

                act_resp = client.post(
                    f"{BASE_URL}/texas/action",
                    headers=headers,
                    json=action_payload,
                )

                if act_resp.status_code != 200:
                    print(f"Action Error {act_resp.status_code}: {act_resp.text}")

            time.sleep(0.5)

    finally:
        client.close()
        elapsed = time.time() - start_time
        hands_per_sec = (hands_finished / elapsed) if elapsed > 0 else 0.0
        bb_per_100 = (
            (net_chips / hands_finished) * (100 / BIG_BLIND)
            if hands_finished > 0
            else 0.0
        )

        print("\n=== Final Results ===")
        print(f"  hands       : {hands_finished}")
        print(f"  wins/losses : {wins}/{losses}  (push: {pushes})")
        print(f"  net chips   : {net_chips:+d}")
        print(f"  bb/100      : {bb_per_100:+.1f}")
        print(f"  elapsed     : {elapsed:.1f}s  ({hands_per_sec:.2f} hands/s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Agent on Devfun Arena PVP")
    parser.add_argument("--competition-id", required=True, help="Competition ID")
    parser.add_argument("--max-hands", type=int, default=50, help="Finished hands target")
    args = parser.parse_args()

    run_pvp_loop(
        competition_id=args.competition_id,
        max_hands=args.max_hands,
    )