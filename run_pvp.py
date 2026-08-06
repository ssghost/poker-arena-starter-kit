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
DEFAULT_HANDS = 10
PROGRESS_INTERVAL = 5
WAIT_LOG_INTERVAL = 150
REJOIN_INTERVAL = 300  

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
            print("[arena] Joined the competition.")
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

def run_pvp_loop(competition_id: str, decide_fn, max_hands: int,
                 run_until_big_loss: bool = False,
                 run_until_big_win_or_loss: bool = False):
    key = load()
    headers = {"x-arena-api-key": key}
    client = httpx.Client(timeout=20.0)
    try_join(client, headers, competition_id)

    print(f"[arena] hero=decide()")
    print(f"[arena] competition={competition_id}")
    print(f"[arena] blinds=1/{BIG_BLIND}")

    infinite_hands_mode = run_until_big_loss or run_until_big_win_or_loss

    if run_until_big_win_or_loss:
        print("[arena] mode: run until big win or loss (>=50 chips) ...")
    elif run_until_big_loss:
        print("[arena] mode: run until big loss (>=50 chips) ...")
    else:
        print(f"[arena] playing {max_hands} hands ...")

    hands = 0
    wins = losses = pushes = 0
    net = 0
    start = time.time()

    vpip_hands = 0
    pfr_hands = 0
    river_calls = 0
    big_loss_hands = []
    big_win_hands = []

    prev_stack = None
    initial_stack = None
    last_table_snapshot = None

    last_wait_log = time.time()
    last_rejoin_time = time.time()

    stop_run = False

    while (infinite_hands_mode or hands < max_hands) and not stop_run:
        if time.time() - last_rejoin_time > REJOIN_INTERVAL:
            print("[arena] 300s elapsed → force rejoin")
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

            if stack < 20:
                print(f"\n[ALERT] Low chips warning: stack = {stack} (< 20 chips).")
                print("[ALERT] Exiting current table. Please rebuy chips manually.")
                leave_competition(client, headers, competition_id)
                client.close()
                return

            if initial_stack is None and stack:
                initial_stack = stack
                prev_stack = stack

            if prev_stack is not None and stack != prev_stack and table.get("boardCards") == []:
                diff = stack - prev_stack
                hands += 1
                net = stack - initial_stack

                if diff > 0:
                    wins += 1
                    if diff >= 50:
                        big_win_hands.append((hands, diff))
                        if last_table_snapshot:
                            with open("big_win_hands.jsonl", "a", encoding="utf-8") as f:
                                f.write(json.dumps({
                                    "hand_num": hands,
                                    "win_chips": diff,
                                    "timestamp": time.time(),
                                    "table_snapshot": last_table_snapshot
                                }, ensure_ascii=False) + "\n")
                        if run_until_big_win_or_loss:
                            print(f"\n[ALERT] Big win detected: +{diff} chips at hand #{hands}. Terminating run.")
                            stop_run = True
                elif diff < 0:
                    losses += 1
                    if abs(diff) >= 50:
                        big_loss_hands.append((hands, diff))
                        if last_table_snapshot:
                            with open("big_loss_hands.jsonl", "a", encoding="utf-8") as f:
                                f.write(json.dumps({
                                    "hand_num": hands,
                                    "loss_chips": diff,
                                    "timestamp": time.time(),
                                    "table_snapshot": last_table_snapshot
                                }, ensure_ascii=False) + "\n")
                        if run_until_big_loss or run_until_big_win_or_loss:
                            print(f"\n[ALERT] Big loss detected: {diff} chips at hand #{hands}. Terminating run.")
                            stop_run = True
                else:
                    pushes += 1

                prev_stack = stack

                target_str = f"/{max_hands}" if not infinite_hands_mode else ""
                if hands % PROGRESS_INTERVAL == 0 or stop_run or (not infinite_hands_mode and hands == max_hands):
                    print(f"  ... {hands}{target_str} hands  net={net:+d} chips")

                if stop_run:
                    break

            if not table.get("allowedActions"):
                continue

            last_table_snapshot = table

            action = decide_fn(table, deadline_s=5)
            action["tableId"] = table_id

            act_name = str(action.get("action", "")).lower()
            street = str(table.get("street", "")).lower()

            if act_name in ["call", "bet", "raise", "all-in", "all_in"]:
                vpip_hands += 1
            if act_name in ["raise", "bet"]:
                pfr_hands += 1
            if street == "river" and act_name == "call":
                river_calls += 1

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

    vpip_pct = (vpip_hands / hands * 100) if hands else 0
    pfr_pct = (pfr_hands / hands * 100) if hands else 0

    print(f"  hands       : {hands}")
    print(f"  opponent    : Arena Live")
    print(f"  wins/losses : {wins}/{losses}  (push: {pushes})")
    print(f"  net chips   : {net:+d}")
    print(f"  bb/100      : {bb100:+.1f}")
    print(f"  elapsed     : {elapsed:.1f}s  ({hands_per_sec:.2f} hands/s)")
    print(f"  VPIP %      : {vpip_pct:.1f}% ({vpip_hands}/{hands})")
    print(f"  PFR %       : {pfr_pct:.1f}% ({pfr_hands}/{hands})")
    print(f"  River Calls : {river_calls}")
    print(f"  Big Wins    : {len(big_win_hands)} hands (>=50 chips win: {big_win_hands})")
    print(f"  Big Losses  : {len(big_loss_hands)} hands (>=50 chips loss: {big_loss_hands})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition-id", required=True)
    parser.add_argument("--agent", default="my_agent.py")
    parser.add_argument("--max-hands", type=int, default=DEFAULT_HANDS)
    parser.add_argument("--run-until-big-loss", action="store_true", default=False)
    parser.add_argument("--run-until-big-win-or-loss", action="store_true", default=False)
    args = parser.parse_args()

    decide_fn = load_agent(args.agent)

    run_pvp_loop(
        competition_id=args.competition_id,
        decide_fn=decide_fn,
        max_hands=args.max_hands,
        run_until_big_loss=args.run_until_big_loss,
        run_until_big_win_or_loss=args.run_until_big_win_or_loss,
    )