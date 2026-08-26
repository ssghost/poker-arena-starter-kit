import json
import sys
from pathlib import Path
import httpx
import time

CREDS_PATH = Path(".arena-credentials")
BASE_URL = "https://arena.dev.fun/api/arena"

def load() -> tuple[str, str]:
    if not CREDS_PATH.exists():
        print("Error: .arena-credentials file not found.", file=sys.stderr)
        sys.exit(1)

    try:
        creds = json.loads(CREDS_PATH.read_text())
    except Exception as e:
        print(f"Error reading .arena-credentials: {e}", file=sys.stderr)
        sys.exit(1)

    key = creds.get("apiKey")
    agent_id = creds.get("agentId") or creds.get("id") or "Unknown"
    return key, agent_id

def claim() -> None:
    key, agent_id = load()
    if not key:
        print("Error: apiKey missing in .arena-credentials.", file=sys.stderr)
        sys.exit(1)

    print(f"Agent ID: {agent_id}")
    print("Requesting claim URL...")
    try:
        response = httpx.get(
            f"{BASE_URL}/auth/claim/status",
            headers={"x-arena-api-key": key},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

        claim_url = data.get("claimUrl") or data.get("url")
        if claim_url:
            print(f"Claim Link: {claim_url}")
            print("Please open the link above to verify your account.")
        else:
            print(f"No claimUrl field found: {data}")

    except httpx.HTTPStatusError as e:
        print(f"HTTP Error {e.response.status_code}: {e.response.text}", file=sys.stderr)
    except Exception as e:
        print(f"Failed to fetch status: {e}", file=sys.stderr)

def rename() -> None:
    new_name = str(input("new name: ")) or "sitara bot 01"
    new_quote = str(input("new quote: ")) or "probability over swagger"
    key, agent_id = load()
    print(f"Agent ID: {agent_id}")

    try:
        response = httpx.patch(
            f"{BASE_URL}/agent/me",
            headers={
                "x-arena-api-key": key,
                "Content-Type": "application/json",
            },
            json={"name": new_name, "quote": new_quote},
            timeout=10.0,
        )
        response.raise_for_status()

        print(f"Agent profile updated with new name {new_name}, new quote {new_quote}.")
    except httpx.HTTPStatusError as e:
        print(f"HTTP Error {e.response.status_code}: {e.response.text}", file=sys.stderr)
    except Exception as e:
        print(f"Failed to fetch status: {e}", file=sys.stderr)

def list_competitions() -> None:
    try:
        response = httpx.get(f"{BASE_URL}/competition/list-active", timeout=10.0)
        response.raise_for_status()
        competitions = response.json()

        if not isinstance(competitions, list):
            print(f"Unexpected data form received: {competitions}.")
            return []

        for comp in competitions:
            comp_id = comp.get("id", "N/A")
            name = comp.get("name", "N/A")
            season = comp.get("seasonNumber", "N/A")
            game_type = comp.get("gameType", "N/A")

            print(f"Name: {name} (Season {season})")
            print(f"Type: {game_type}")
            print(f"Competition ID: {comp_id}")

    except httpx.HTTPStatusError as e:
        print(f"HTTP Error {e.response.status_code}: {e.response.text}", file=sys.stderr)
    except Exception as e:
        print(f"Failed to fetch status: {e}", file=sys.stderr)

def check_status(competition_id: str = "cms7hrnjg20czv7oi85cho570") -> None:
    key, _ = load()
    headers = {"x-arena-api-key": key, "Content-Type": "application/json"}
    url = f"{BASE_URL}/texas/pending-actions?competitionId={competition_id}"

    try:
        response = httpx.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        participant = data.get("participant", {})
        chip_state = participant.get("chipState", "unknown")
        total_chips = participant.get("totalChips", 0)

        print(f"[Status Check] Competition: {competition_id}")
        print(f" Chip State  : {chip_state}")
        print(f" Total Chips : {total_chips}")
        print(f" Bankroll    : {participant.get('bankrollChips', 0)}")
        print(f" Table Chips : {participant.get('tableChips', 0)}")

    except Exception as e:
        print(f"Failed to fetch participant status: {e}", file=sys.stderr)

def rebuy(competition_id: str = "cms7hrnjg20czv7oi85cho570") -> None:
    key, _ = load()
    headers = {"x-arena-api-key": key, "Content-Type": "application/json"}
    status_url = f"{BASE_URL}/texas/rebuy-status?competitionId={competition_id}"
    try:
        status_resp = httpx.get(status_url, headers=headers)
        status_resp.raise_for_status()
        status_data = status_resp.json()

        can_rebuy = status_data.get("canRebuyNow", False)
        reason = status_data.get("cannotRebuyReason")

        if not can_rebuy:
            print(f"Rebuy Unavailable: {reason}")
            return False

        rebuy_url = f"{BASE_URL}/texas/rebuy"
        rebuy_resp = httpx.post(
            rebuy_url, headers=headers, json={"competitionId": competition_id}
        )
        rebuy_resp.raise_for_status()
        rebuy_result = rebuy_resp.json()

        participant = rebuy_result.get("participant", {})
        new_state = participant.get("chipState")
        new_total = participant.get("totalChips")

        print(f"[Rebought chips] New State: {new_state} | Total Chips: {new_total}")

    except Exception as e:
        print(f"Rebuy execution failed: {e}", file=sys.stderr)

def force_leave(competition_id: str = "cms7hrnjg20czv7oi85cho570", max_wait_seconds: int = 45) -> bool:
    key, _ = load()
    headers = {"x-arena-api-key": key, "Content-Type": "application/json"}
    
    pending_url = f"{BASE_URL}/texas/pending-actions?competitionId={competition_id}"
    leave_url = f"{BASE_URL}/texas/leave"
    action_url = f"{BASE_URL}/texas/action"

    start_time = time.time()
    print(f"[Force Leave] Initiating leave sequence for competition: {competition_id}")

    while time.time() - start_time < max_wait_seconds:
        try:
            leave_resp = httpx.post(
                leave_url,
                headers=headers,
                json={"competitionId": competition_id},
                timeout=10.0,
            )
            if leave_resp.status_code == 200:
                leave_data = leave_resp.json()
                if leave_data.get("left"):
                    print(f"[Force Leave] Successfully left table.")
                    return True
                else:
                    print(f"[Force Leave] Leave rejected by server: {leave_data}")
        except Exception as e:
            print(f"[Force Leave] Leave request error: {e}", file=sys.stderr)

        try:
            resp = httpx.get(pending_url, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                participant = data.get("participant", {})
                chip_state = participant.get("chipState")
                tables = data.get("tables", [])

                if not tables and chip_state not in ("locked_in_play", "in_play"):
                    print(f"[Force Leave] No active tables found. Chip state: {chip_state}")
                    return True

                for t in tables:
                    tid = t.get("tableId")
                    allowed = t.get("allowedActions", [])
                
                    if "fold" in allowed or allowed:
                        action = "fold" if "fold" in allowed else allowed[0]
                        action_resp = httpx.post(
                            action_url,
                            headers=headers,
                            json={"tableId": tid, "action": action},
                            timeout=10.0,
                        )
                        print(f"[Force Leave] Performed '{action}' on table: {tid} (Status: {action_resp.status_code})")
        except Exception as e:
            print(f"[Force Leave] Pending actions check error: {e}", file=sys.stderr)

        time.sleep(2.0)

    print(f"[Force Leave] Timeout after {max_wait_seconds}s. Player might still be in hand.", file=sys.stderr)
    return False

if __name__ == "__main__":
    #list_competitions()
    #force_leave(competition_id="cmt78jcn6c9a1ddft3z2to1y5")
    check_status(competition_id="cmt78jcn6c9a1ddft3z2to1y5")
    