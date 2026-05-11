"""
Generate a daily FYERS access token.

Usage:
    python3 scripts/fyers_auth.py \\
        --app-id WLBEIQQR4O-100 \\
        --secret OL1WCVJQOA \\
        --redirect-uri http://127.0.0.1:5000/callback

Flow:
    1. Script prints an auth URL. Open it in a browser and log in.
    2. FYERS redirects to your redirect_uri with ?auth_code=... in the URL.
    3. Paste that auth_code back into the script.
    4. Script exchanges it for an access_token and writes FYERS_APP_ID /
       FYERS_ACCESS_TOKEN into backend/.env (replacing any existing values).

Access tokens expire daily (~08:00 IST), so re-run this each morning.
"""

import argparse
import hashlib
import re
import sys
import urllib.parse
from pathlib import Path

import httpx

AUTH_URL = "https://api-t1.fyers.in/api/v3/generate-authcode"
VALIDATE_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"


def build_auth_url(app_id: str, redirect_uri: str, state: str = "timemachine") -> str:
    qs = urllib.parse.urlencode({
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    })
    return f"{AUTH_URL}?{qs}"


def exchange_authcode(app_id: str, secret: str, auth_code: str) -> str:
    app_hash = hashlib.sha256(f"{app_id}:{secret}".encode()).hexdigest()
    resp = httpx.post(
        VALIDATE_URL,
        json={
            "grant_type": "authorization_code",
            "appIdHash": app_hash,
            "code": auth_code,
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("s") != "ok" or "access_token" not in payload:
        raise RuntimeError(f"FYERS validate-authcode failed: {payload}")
    return payload["access_token"]


def upsert_env(env_path: Path, app_id: str, access_token: str) -> None:
    content = env_path.read_text() if env_path.exists() else ""

    updates = {
        "FYERS_APP_ID": app_id,
        "FYERS_ACCESS_TOKEN": access_token,
    }

    for key, value in updates.items():
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        if pattern.search(content):
            content = pattern.sub(f"{key}={value}", content)
        else:
            if content and not content.endswith("\n"):
                content += "\n"
            content += f"{key}={value}\n"

    env_path.write_text(content)


def main():
    parser = argparse.ArgumentParser(description="Generate FYERS access token.")
    parser.add_argument("--app-id", required=True, help="FYERS app id (e.g. WLBEIQQR4O-100)")
    parser.add_argument("--secret", required=True, help="FYERS app secret")
    parser.add_argument(
        "--redirect-uri",
        required=True,
        help="Redirect URI registered on the FYERS app (e.g. http://127.0.0.1:5000/callback)",
    )
    parser.add_argument(
        "--env-file",
        default=str(Path(__file__).resolve().parent.parent / ".env"),
        help="Path to .env file to update",
    )
    args = parser.parse_args()

    auth_url = build_auth_url(args.app_id, args.redirect_uri)
    print("\n1. Open this URL and log in:\n")
    print(f"   {auth_url}\n")
    print("2. After login, FYERS redirects to your redirect URI with ?auth_code=XXX")
    print("   Copy the auth_code value from the redirected URL.\n")

    auth_code = input("Paste auth_code here: ").strip()
    if not auth_code:
        print("No auth_code provided.", file=sys.stderr)
        sys.exit(1)

    access_token = exchange_authcode(args.app_id, args.secret, auth_code)
    upsert_env(Path(args.env_file), args.app_id, access_token)

    print(f"\n[ok] Access token written to {args.env_file}")
    print("     Restart the backend to pick up the new token.")


if __name__ == "__main__":
    main()
