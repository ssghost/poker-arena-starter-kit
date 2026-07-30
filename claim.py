import json
import sys
from pathlib import Path
import httpx

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
            "{BASE_URL}/auth/claim/status",
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
            print("No claimUrl field found: {data}")

    except httpx.HTTPStatusError as e:
        print(f"HTTP Error {e.response.status_code}: {e.response.text}", file=sys.stderr)
    except Exception as e:
        print(f"Failed to fetch status: {e}", file=sys.stderr)

def rename() -> None:
    new_name = str(input("new name: "))
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
        data = response.json()

        print(f"Agent profile updated with new name {new_name}, new quote {new_quote}.")
    except httpx.HTTPStatusError as e:
        print(f"HTTP Error {e.response.status_code}: {e.response.text}", file=sys.stderr)
    except Exception as e:
        print(f"Failed to fetch status: {e}", file=sys.stderr)

if __name__ == "__main__":
    rename()