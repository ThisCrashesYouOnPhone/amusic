"""
One-time helper: exchange a Last.fm API key + secret for a permanent session key.

Usage:
    pip install httpx
    python scripts/get_lastfm_session_key.py

The session key never expires unless you revoke the application at
https://www.last.fm/settings/applications. Add the printed key to your
GitHub secrets as LASTFM_SESSION_KEY.
"""
from __future__ import annotations

import hashlib
import sys
import webbrowser

import httpx

API_URL = "https://ws.audioscrobbler.com/2.0/"


def main() -> int:
    print("Last.fm session key helper")
    print("--------------------------")
    api_key = input("API key: ").strip()
    secret = input("Shared secret: ").strip()

    if not api_key or not secret:
        print("Both values required.")
        return 1

    with httpx.Client(timeout=15.0) as client:
        # 1. Get a request token
        r = client.get(API_URL, params={
            "method": "auth.getToken",
            "api_key": api_key,
            "format": "json",
        })
        r.raise_for_status()
        body = r.json()
        if "token" not in body:
            print(f"auth.getToken failed: {body}")
            return 1
        token = body["token"]

        # 2. Send the user to authorize
        auth_url = f"https://www.last.fm/api/auth/?api_key={api_key}&token={token}"
        print()
        print(f"Opening browser to: {auth_url}")
        print("Click 'Yes, allow access', then come back here and press Enter.")
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass
        input()

        # 3. Exchange the authorized token for a permanent session key
        sig_string = (
            f"api_key{api_key}"
            f"methodauth.getSession"
            f"token{token}"
            f"{secret}"
        )
        sig = hashlib.md5(sig_string.encode("utf-8")).hexdigest()
        r = client.get(API_URL, params={
            "method": "auth.getSession",
            "api_key": api_key,
            "token": token,
            "api_sig": sig,
            "format": "json",
        })
        r.raise_for_status()
        body = r.json()

    if "session" not in body:
        print(f"auth.getSession failed: {body}")
        print("Make sure you clicked 'Yes, allow access' on the auth page.")
        return 1

    session = body["session"]
    print()
    print(f"Authorized as: {session['name']}")
    print()
    print("Add this to GitHub secrets as LASTFM_SESSION_KEY:")
    print()
    print(f"    {session['key']}")
    print()
    print(
        "This key never expires unless you revoke the application at\n"
        "https://www.last.fm/settings/applications"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
