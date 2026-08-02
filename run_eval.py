import argparse
import json
import os
import sys
import time
from pathlib import Path
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CREDS_PATH = Path(".arena-credentials")
ENV_PATH = Path(".env")
BASE_URL = "https://arena.dev.fun/api/arena"
POLL_INTERVAL = 5

def load_gemini_key() -> str:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key
    print("[error] GEMINI_API_KEY not found.", file=sys.stderr)
    sys.exit(1)


def load_credentials() -> tuple[str, str]:
    if not CREDS_PATH.exists():
        print("[error] Missing .arena-credentials file.", file=sys.stderr)
        sys.exit(1)
    creds = json.loads(CREDS_PATH.read_text())
    return creds.get("apiKey"), creds.get("agentId") or "Unknown"


def configure_sandbox_settings(client: httpx.Client, headers: dict, gemini_key: str):
    print("[arena] Updating Gemini API Key...")
    payload = {
        "benchflowAgent": "gemini",
        "modelName": "gemini-2.5-flash",
        "credentials": {
            "geminiApiKey": gemini_key
        }
    }
    try:
        r = client.put(f"{BASE_URL}/submissions/settings", headers=headers, json=payload, timeout=15.0)
        r.raise_for_status()
        res = r.json()
        access = res.get("access", {}).get("sandboxBenchmark", {})
        print(f"[arena] Sandbox Settings Updated!")
        print(f"        Claimed: {access.get('claimed')} | XVerified: {access.get('xVerified')}")
        print(f"        Status : {access.get('message')}")
    except httpx.HTTPStatusError as e:
        print(f"[error] Failed to update sandbox settings ({e.response.status_code}): {e.response.text}", file=sys.stderr)
        sys.exit(1)


def upload_agent_submission(client: httpx.Client, headers: dict, agent_path: str, competition_id: str) -> str:
    file_p = Path(agent_path).resolve()
    if not file_p.exists():
        print(f"[error] Agent file not found: {file_p}", file=sys.stderr)
        sys.exit(1)

    print(f"[arena] Submitting {file_p.name} as strategy.py to competition {competition_id}...")
    upload_headers = {"x-arena-api-key": headers["x-arena-api-key"]}
    
    with open(file_p, "rb") as f:
        files = {"file": ("strategy.py", f, "text/x-python")}
        data = {"competitionId": competition_id, "template": "static-agent"}
        try:
            r = client.post(f"{BASE_URL}/submissions", headers=upload_headers, data=data, files=files, timeout=30.0)
            r.raise_for_status()
            res = r.json()
            sub_id = res.get("id")
            print(f"[arena] Submission Created.")
            print(f"        Submission ID: {sub_id}")
            print(f"        Initial Status: {res.get('status')}")
            return sub_id
        except httpx.HTTPStatusError as e:
            print(f"[error] Submission Upload Failed ({e.response.status_code}): {e.response.text}", file=sys.stderr)
            sys.exit(1)


def monitor_benchmark_progress(client: httpx.Client, headers: dict, competition_id: str):
    print(f"[arena] Monitoring server-side benchmark progress for competition: {competition_id}...")
    start_time = time.time()
    last_completed = -1

    while True:
        try:
            r = client.get(f"{BASE_URL}/texas/benchmark/status", params={"competitionId": competition_id}, headers=headers, timeout=15.0)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[warning] Status poll error: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        match_info = data.get("match", {})
        status = match_info.get("status")
        phase = match_info.get("phase")
        completed_hands = match_info.get("completedHands", 0)
        target_hands = match_info.get("targetHands", 500)
        raw_bb100 = match_info.get("rawBbPer100", 0.0)
        adjusted_bb100 = match_info.get("adjustedBbPer100", 0.0)

        if completed_hands != last_completed:
            last_completed = completed_hands
            print(f"  ... [{completed_hands}/{target_hands} hands] status={status} phase={phase} raw_bb100={raw_bb100:+.1f} adjusted_bb100={adjusted_bb100:+.1f}")

        if status in ["Completed", "Failed", "Cancelled", "Succeeded", "TimedOut"]:
            elapsed = time.time() - start_time
            print(f"  Final Status   : {status}")
            print(f"  Completed Hands: {completed_hands}/{target_hands}")
            print(f"  Raw bb/100     : {raw_bb100:+.1f}")
            print(f"  Adjusted bb100 : {adjusted_bb100:+.1f}")
            print(f"  Total Elapsed  : {elapsed:.1f}s")
            break

        time.sleep(POLL_INTERVAL)


def run_eval_loop(competition_id: str, agent_path: str):
    gemini_key = load_gemini_key()
    api_key, _ = load_credentials()
    headers = {"x-arena-api-key": api_key, "Content-Type": "application/json"}
    
    with httpx.Client(timeout=30.0) as client:
        configure_sandbox_settings(client, headers, gemini_key)
        
        upload_agent_submission(client, headers, agent_path, competition_id)
        
        monitor_benchmark_progress(client, headers, competition_id)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Submit Agent and Run Server-Hosted Gemini Eval Benchmark")
    parser.add_argument(
        "--competition-id",
        default="seed_poker_eval_s1",
    )
    parser.add_argument(
        "--agent",
        default="my_agent_s11_v1.py",
    )
    args = parser.parse_args()

    run_eval_loop(competition_id=args.competition_id, agent_path=args.agent)