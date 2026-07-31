"""Devfun Arena PVP Match Runner (Playground & Tournament)."""
import argparse
import json
import sys
import time
from pathlib import Path
import httpx

from my_agent import decide

sys.path.insert(0, str(Path(__file__).resolve().parent / "examples"))

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
    if (val := next((int(table[k]) for k in ["heroStack", "stack", "chips", "myStack"] 
        if k in table and isinstance(table[k], (int, float))), None)) is not None:
        return val

    players = table.get("players", [])
    if isinstance(players, list):
        if (val := next((int(p[k]) 
            for p in players if isinstance(p, dict) and (p.get("isHero") or p.get("hero") or p.get("isMe"))
            for k in ["stack", "chips", "amount"] if k in p and isinstance(p[k], (int, float))), None)) is not None:
            return val

    return 0


def run_pvp_loop(competition_id: str, max_hands: int = 50):
    key = load()
    headers = {"x-arena-api-key": key, "Content-Type": "application/json"}

    client = httpx.Client(timeout=30.0)

    try:
        r = client.post(f"{BASE_URL}/texas/join", headers=headers, json={"competitionId": competition_id})
        if r.status_code == 400 and "already in" in r.text.lower():
            print(f"Agent has already joined the competition {competition_id}.")
        elif r.status_code != 200:
            print(f"Join status: {r.status_code} - {r.text}")
        else:
            print(f"Agent has joined the competition {competition_id}.")
    except Exception as e:
        print(f"Request error{e}")

    hands_acted = 0
    wins = 0
    losses = 0
    pushes = 0
    start_time = time.time()
    
    initial_stack = None
    current_stack = 0
    net_chips = 0
    print(f"Pending Actions (Targeted to {max_hands} hands)...")

    try:
        while hands_acted < max_hands:
            try:
                pending_resp = client.get(
                    f"{BASE_URL}/texas/pending-actions?competitionId={competition_id}",
                    headers=headers,
                )
                pending_resp.raise_for_status()
                pending_data = pending_resp.json()
                tables = pending_data.get("tables", [])

                if tables:
                    for table in tables:
                        table_id = table.get("tableId")
                        deadline_ms = table.get("actionDeadlineAt") or 0
                        deadline_s = max(0.5, (deadline_ms / 1000.0) - time.time()) if deadline_ms else 10.0

                        hero_stack = get_hero_stack(table)
                        if initial_stack is None and hero_stack > 0:
                            initial_stack = hero_stack
                            current_stack = hero_stack

                        action_payload = decide(table, deadline_s=deadline_s)
                        action_payload["tableId"] = table_id

                        act_resp = client.post(f"{BASE_URL}/texas/action", headers=headers, json=action_payload)
                        if act_resp.status_code == 200:
                            hands_acted += 1
                            new_stack = get_hero_stack(table)
                            if new_stack == 0:
                                new_stack = current_stack
                            hand_net = new_stack - current_stack
                            current_stack = new_stack
                            net_chips = current_stack - (initial_stack or current_stack)

                            if hand_net > 0:
                                wins += 1
                                result_str = f"+{hand_net}"
                            elif hand_net < 0:
                                losses += 1
                                result_str = f"-{hand_net}"
                            else:
                                pushes += 1
                                result_str = "0"

                            print(
                                f"Submitted: [{hands_acted}/{max_hands}] "
                                f"Hand Net: {result_str} | Total Net: {net_chips:+d} | "
                                f"Actions: {action_payload.get('action')} | "
                                f"Messages: {action_payload.get('message')}"
                            )
                        else:
                            print(f"Action Response: {act_resp.status_code}: {act_resp.text}")

                time.sleep(1.0)

            except httpx.HTTPStatusError as e:
                print(f"HTTP Error {e.response.status_code}: {e.response.text}", file=sys.stderr)
            except Exception as e:
                print(f"Failed to fetch status: {e}", file=sys.stderr)

        print(f"Finished {hands_acted} hands action.")

    finally:
        client.close()
        elapsed = time.time() - start_time
        hands_per_sec = (hands_acted / elapsed) if elapsed > 0 else 0
        
        bb_per_100 = (net_chips / hands_acted * (100 / BIG_BLIND)) if hands_acted > 0 else 0.0

        print(f"  hands       : {hands_acted}")
        print(f"  wins/losses : {wins}/{losses}  (push: {pushes})")
        print(f"  net chips   : {net_chips:+d}")
        print(f"  bb/100      : {bb_per_100:+.1f}")
        print(f"  elapsed     : {elapsed:.1f}s  ({hands_per_sec:.1f} hands/s)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Agent on Devfun Arena PVP")
    parser.add_argument("--competition-id", required=True, help="Competition ID")
    parser.add_argument("--max-hands", type=int, default=50, help="Max hands to play")
    args = parser.parse_args()

    run_pvp_loop(competition_id=args.competition_id, max_hands=args.max_hands)
