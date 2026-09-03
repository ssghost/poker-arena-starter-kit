import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.strategy import load_strategy
from agent.tracker import OpponentTracker

CREDS_PATH = Path(".arena-credentials")
BASE_URL = "https://arena.dev.fun/api/arena"
DEFAULT_HANDS = 10
REJOIN_INTERVAL = 300
STATUS_REPORT_INTERVAL = 600

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

def try_join(client, headers, competition_id, silent: bool = False):
    if not silent:
        print("[arena] attempting to join competition...")
    try:
        r = client.post(
            f"{BASE_URL}/texas/join",
            headers=headers,
            json={"competitionId": competition_id},
        )
        if not silent:
            if r.status_code == 200:
                print("[arena] Joined the competition.")
            elif r.status_code == 400 and "already" in r.text.lower():
                print("[arena] already joined.")
            elif r.status_code == 409:
                print("[arena] already seated (table limit).")
            elif r.status_code == 402:
                req = r.json().get("paymentRequirements") or {}
                ref = req.get("paymentReference")
                print(f"[arena] 402 Payment required (sponsored: {req.get('sponsored')}, ref: {ref})")
                if ref:
                    r_retry = client.post(
                        f"{BASE_URL}/texas/join",
                        headers=headers,
                        json={"competitionId": competition_id, "paymentReference": ref},
                    )
                    print(f"[arena] retry join response: {r_retry.status_code} {r_retry.text}")
            else:
                print(f"[arena] join response: {r.status_code} {r.text}")
    except Exception as e:
        if not silent:
            print(f"[arena] join failed: {e}")

def leave_competition(client, headers, competition_id, silent: bool = True):
    try:
        r = client.post(
            f"{BASE_URL}/texas/leave",
            headers=headers,
            json={"competitionId": competition_id},
            timeout=10.0,
        )
        if not silent:
            print(f"[arena] left competition ({r.status_code})")
    except Exception as e:
        if not silent:
            print(f"[arena] leave failed: {e}")

def join_competition(client, headers, competition_id, silent: bool = True):
    try:
        r = client.post(
            f"{BASE_URL}/texas/join",
            headers=headers,
            json={"competitionId": competition_id},
            timeout=10.0,
        )
        if not silent:
            print(f"[arena] rejoined table ({r.status_code})")
    except Exception as e:
        if not silent:
            print(f"[arena] rejoin failed: {e}")

def calc_sharpe(deltas: list) -> float:
    if not deltas or len(deltas) <= 1:
        return 0.0
    mean = sum(deltas) / len(deltas)
    variance = sum((x - mean) ** 2 for x in deltas) / (len(deltas) - 1)
    std_dev = math.sqrt(variance)
    return (mean / std_dev) if std_dev > 0 else 0.0

def record_chunk_extremes(records: list):
    wins_in_chunk = [r for r in records if r["chip_delta"] > 0]
    losses_in_chunk = [r for r in records if r["chip_delta"] < 0]

    top_win = max(wins_in_chunk, key=lambda x: x["chip_delta"]) if wins_in_chunk else None
    worst_loss = min(losses_in_chunk, key=lambda x: x["chip_delta"]) if losses_in_chunk else None

    chunk_big_wins = []
    chunk_big_losses = []

    if top_win:
        chunk_big_wins.append((top_win["hand_num"], top_win["chip_delta"]))
    if worst_loss:
        chunk_big_losses.append((worst_loss["hand_num"], worst_loss["chip_delta"]))

    return chunk_big_wins, chunk_big_losses

def print_analytics(chunk_hands, wins, losses, pushes, net, elapsed,
                    vpip_hands, pfr_hands, river_calls, big_wins, big_losses,
                    deltas=None,
                    chunk_title="10",
                    big_blind=2):
    hands_per_sec = chunk_hands / elapsed if elapsed > 0 else 0
    bb100 = (net / chunk_hands * (100 / big_blind)) if chunk_hands else 0
    vpip_pct = (vpip_hands / chunk_hands * 100) if chunk_hands else 0
    pfr_pct = (pfr_hands / chunk_hands * 100) if chunk_hands else 0
    sharpe = calc_sharpe(deltas) if deltas else 0.0

    print(f"\n{chunk_title} Hands Analytics")
    print(f"  hands       : {chunk_hands}")
    print(f"  opponent    : Arena Live")
    print(f"  wins/losses : {wins}/{losses}  (push: {pushes})")
    print(f"  net chips   : {net:+d}")
    print(f"  bb/100      : {bb100:+.1f}")
    print(f"  Sharpe      : {sharpe:+.3f}")
    print(f"  elapsed     : {elapsed:.1f}s  ({hands_per_sec:.2f} hands/s)")
    print(f"  VPIP %      : {vpip_pct:.1f}% ({vpip_hands}/{chunk_hands})")
    print(f"  PFR %      : {pfr_pct:.1f}% ({pfr_hands}/{chunk_hands})")
    print(f"  River Calls : {river_calls}")
    print(f"  Big Wins    : {len(big_wins)} hands (max win: {big_wins})")
    print(f"  Big Losses  : {len(big_losses)} hands (max loss: {big_losses})")

def update_tracker_from_table(tracker: OpponentTracker, table: dict):
    seats = table.get("seats") or []
    self_seat = table.get("selfSeatNumber")
    recent_events = table.get("recentEvents") or []

    seat_actions_map = {}
    for ev in recent_events:
        if isinstance(ev, dict):
            s_num = ev.get("seatNumber")
            if s_num is not None and s_num != self_seat:
                summary = ev.get("summary") or {}
                act = str(summary.get("action") or ev.get("action") or "").lower()
                street = str(summary.get("street") or ev.get("street") or "").lower()
                if act:
                    if s_num not in seat_actions_map:
                        seat_actions_map[s_num] = []
                    seat_actions_map[s_num].append({"action": act, "street": street})

    for s in seats:
        s_num = s.get("seatNumber")
        if s_num is not None and s_num != self_seat and s_num in seat_actions_map:
            p_id = str(s.get("playerId") or s.get("id") or s.get("name") or s_num)
            p_name = str(s.get("name") or "")
            tracker.record_hand_actions(p_id, p_name, seat_actions_map[s_num])

def run_pvp_loop(competition_id: str, decide_fn, max_hands: int,
                 strategy_name: str = "tag",
                 run_until_big_loss: bool = False,
                 run_until_big_win_or_loss: bool = False,
                 continuous: bool = False,
                 tournament: bool = False):
    key = load()
    headers = {"x-arena-api-key": key, "Content-Type": "application/json"}
    client = httpx.Client(timeout=20.0)

    big_blind = 10 if tournament else 2
    small_blind = 5 if tournament else 1
    chunk_size = 10 if tournament else 50

    strategy_profile = load_strategy(strategy_name)
    tracker = OpponentTracker()

    research_context = {
        "strategy": strategy_profile,
        "tracker": tracker,
        "vpip_ema": strategy_profile.target_vpip,
        "last_hand_id": None,
    }

    try_join(client, headers, competition_id, silent=continuous)

    if not continuous:
        print(f"[arena] hero=decide() | strategy={strategy_profile.name}")
        print(f"[arena] competition={competition_id}")
        print(f"[arena] blinds={small_blind}/{big_blind}")

    infinite_hands_mode = run_until_big_loss or run_until_big_win_or_loss or continuous or tournament

    if tournament:
        print(f"[arena] mode: tournament play (blinds {small_blind}/{big_blind}, report per 10 hands, stop on 2x negative Sharpe chunks, auto-queue active) ...")
    elif continuous:
        print("[arena] mode: continuous background (silent, report per 50 hands, stop on big loss / 2x negative Sharpe chunks) ...")
    elif run_until_big_win_or_loss:
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
    hand_deltas = []

    c_hands = 0
    c_wins = c_losses = c_pushes = 0
    c_net = 0
    c_start = time.time()
    c_vpip_hands = 0
    c_pfr_hands = 0
    c_river_calls = 0
    c_hand_deltas = []
    c_hand_records = []

    consecutive_negative_sharpe_chunks = 0

    initial_stack = None
    last_known_chips = None
    start_server_hands = None
    last_server_hands = None

    current_hand_actions = {"vpip": False, "pfr": False, "river_call": False}

    last_rejoin_time = time.time()
    last_status_report_time = time.time()
    last_idle_join_time = time.time()

    stop_run = False

    try:
        while (infinite_hands_mode or hands < max_hands) and not stop_run:
            now = time.time()

            if not continuous and (now - last_status_report_time >= STATUS_REPORT_INTERVAL):
                time_str = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{time_str}] Periodic Status: {hands} hands completed | Net chips: {net:+d}")
                last_status_report_time = now

            if not tournament and (now - last_rejoin_time > REJOIN_INTERVAL):
                leave_competition(client, headers, competition_id, silent=True)
                time.sleep(2)
                join_competition(client, headers, competition_id, silent=True)
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

            participant = data.get("participant") or {}
            tables = data.get("tables") or []

            server_total_hands = participant.get("totalHands")
            server_total_chips = participant.get("totalChips")
            bankroll_chips = participant.get("bankrollChips", 0)
            table_chips = participant.get("tableChips", 0)
            chip_state = str(participant.get("chipState") or "").lower()

            current_chips = server_total_chips if server_total_chips is not None else (bankroll_chips + table_chips)

            if initial_stack is None and current_chips > 0:
                initial_stack = current_chips
                last_known_chips = current_chips
                start_server_hands = server_total_hands if server_total_hands is not None else 0
                last_server_hands = start_server_hands

            if tournament and (current_chips <= 0 or chip_state == "busted"):
                print(f"\n[ALERT] Tournament Busted: stack = {current_chips}, chipState = {chip_state}.")
                print("[ALERT] Stopping process to preserve state (single ticket policy).")
                stop_run = True
                break

            if not tournament and current_chips > 0 and current_chips < 20:
                print(f"\n[ALERT] Low chips warning: stack = {current_chips} (< 20 chips).")
                print("[ALERT] Exiting current table. Please rebuy chips manually.")
                stop_run = True
                break

            if server_total_hands is not None and last_server_hands is not None and server_total_hands > last_server_hands:
                hand_delta = server_total_hands - last_server_hands
                chip_delta = current_chips - (last_known_chips if last_known_chips is not None else current_chips)

                hands += hand_delta
                c_hands += hand_delta
                net = current_chips - initial_stack
                c_net += chip_delta

                hand_deltas.append(chip_delta)
                c_hand_deltas.append(chip_delta)
                c_hand_records.append({
                    "hand_num": hands,
                    "chip_delta": chip_delta,
                })

                if current_hand_actions["vpip"]:
                    vpip_hands += 1
                    c_vpip_hands += 1
                if current_hand_actions["pfr"]:
                    pfr_hands += 1
                    c_pfr_hands += 1
                if current_hand_actions["river_call"]:
                    river_calls += 1
                    c_river_calls += 1

                current_hand_actions = {"vpip": False, "pfr": False, "river_call": False}

                if chip_delta > 0:
                    wins += 1
                    c_wins += 1
                    if chip_delta >= 50 and run_until_big_win_or_loss:
                        print(f"\n[ALERT] Big win detected: +{chip_delta} chips at hand #{hands}.")
                        stop_run = True
                elif chip_delta < 0:
                    losses += 1
                    c_losses += 1
                    if not tournament and abs(chip_delta) >= 50 and (run_until_big_loss or run_until_big_win_or_loss or continuous):
                        print(f"\n[ALERT] Big loss detected: {chip_delta} chips at hand #{hands}.")
                        stop_run = True
                else:
                    pushes += 1
                    c_pushes += 1

                last_server_hands = server_total_hands
                last_known_chips = current_chips

                if c_hands >= chunk_size:
                    c_elapsed = time.time() - c_start
                    c_sharpe = calc_sharpe(c_hand_deltas)
                    c_big_wins, c_big_losses = record_chunk_extremes(c_hand_records)
                    big_win_hands.extend(c_big_wins)
                    big_loss_hands.extend(c_big_losses)

                    if continuous or tournament:
                        print_analytics(c_hands, c_wins, c_losses, c_pushes, c_net, c_elapsed,
                                        c_vpip_hands, c_pfr_hands, c_river_calls, c_big_wins, c_big_losses,
                                        deltas=c_hand_deltas,
                                        chunk_title=f"Hands {hands - c_hands + 1}-{hands}",
                                        big_blind=big_blind)

                        if c_sharpe < 0:
                            consecutive_negative_sharpe_chunks += 1
                            if consecutive_negative_sharpe_chunks >= 2:
                                mode_str = "tournament" if tournament else "continuous"
                                print(f"\n[ALERT] 2 consecutive {chunk_size}-hand chunks had negative Sharpe Ratio. Stopping {mode_str} mode.")
                                stop_run = True
                        else:
                            consecutive_negative_sharpe_chunks = 0

                    c_hands = 0
                    c_wins = c_losses = c_pushes = 0
                    c_net = 0
                    c_start = time.time()
                    c_vpip_hands = c_pfr_hands = c_river_calls = 0
                    c_hand_deltas = []
                    c_hand_records = []

                if stop_run or (not infinite_hands_mode and hands >= max_hands):
                    stop_run = True
                    break

            if not tables:
                if tournament and current_chips > 0 and (now - last_idle_join_time > 30):
                    try_join(client, headers, competition_id, silent=True)
                    last_idle_join_time = now
                time.sleep(1)
                continue

            for table in tables:
                table_id = table.get("tableId") or table.get("id")

                if not table.get("allowedActions"):
                    continue

                update_tracker_from_table(tracker, table)

                action = decide_fn(table, deadline_s=5, research_context=research_context)
                action["tableId"] = table_id

                act_name = str(action.get("action", "")).lower()
                street = str(table.get("street", "")).lower()

                if act_name in ["call", "bet", "raise", "all-in", "all_in"]:
                    current_hand_actions["vpip"] = True
                if act_name in ["raise", "bet"]:
                    current_hand_actions["pfr"] = True
                if street == "river" and act_name == "call":
                    current_hand_actions["river_call"] = True

                try:
                    client.post(
                        f"{BASE_URL}/texas/action",
                        headers=headers,
                        json=action,
                    )
                except Exception:
                    continue

            time.sleep(0.3)

    except KeyboardInterrupt:
        print("\n[arena] Interrupted by user.")
    finally:
        leave_competition(client, headers, competition_id, silent=True)
        client.close()

        if c_hands > 0:
            c_big_wins, c_big_losses = record_chunk_extremes(c_hand_records)
            big_win_hands.extend(c_big_wins)
            big_loss_hands.extend(c_big_losses)
            if continuous or tournament:
                c_elapsed = time.time() - c_start
                start_hand = hands - c_hands + 1
                print_analytics(c_hands, c_wins, c_losses, c_pushes, c_net, c_elapsed,
                                c_vpip_hands, c_pfr_hands, c_river_calls, c_big_wins, c_big_losses,
                                deltas=c_hand_deltas,
                                chunk_title=f"Final Partial (Hands {start_hand}-{hands})",
                                big_blind=big_blind)

        if not continuous or hands > 0:
            elapsed = time.time() - start
            print_analytics(hands, wins, losses, pushes, net, elapsed,
                            vpip_hands, pfr_hands, river_calls, big_win_hands, big_loss_hands,
                            deltas=hand_deltas,
                            chunk_title="Total",
                            big_blind=big_blind)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition-id", required=True)
    parser.add_argument("--agent", default="my_agent.py")
    parser.add_argument("--strategy", default="tag")
    parser.add_argument("--max-hands", type=int, default=DEFAULT_HANDS)
    parser.add_argument("--run-until-big-loss", action="store_true", default=False)
    parser.add_argument("--run-until-big-win-or-loss", action="store_true", default=False)
    parser.add_argument("--continuous", action="store_true", default=False)
    parser.add_argument("--tournament", action="store_true", default=False)
    args = parser.parse_args()

    decide_fn = load_agent(args.agent)

    run_pvp_loop(
        competition_id=args.competition_id,
        decide_fn=decide_fn,
        strategy_name=args.strategy,
        max_hands=args.max_hands,
        run_until_big_loss=args.run_until_big_loss,
        run_until_big_win_or_loss=args.run_until_big_win_or_loss,
        continuous=args.continuous,
        tournament=args.tournament,
    )