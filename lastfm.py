"""
Last.fm scrobble client.

Implements track.scrobble with the proper auth signing scheme:

  1. Take all params except 'format' and 'callback'
  2. Sort by key
  3. Concatenate as key1value1key2value2...
  4. Append shared secret
  5. MD5 the resulting UTF-8 string
  6. Add the hex digest as 'api_sig'

Last.fm accepts up to 50 scrobbles per batch and applies its own dedup
based on (artist, track, timestamp) — so resubmissions of the same play
will be silently ignored rather than creating duplicates, which makes
the scrobbler safe to retry on failure.
"""
from __future__ import annotations

import hashlib
import logging
from typing import List, Dict, Any

import httpx

log = logging.getLogger(__name__)

API_URL = "https://ws.audioscrobbler.com/2.0/"
BATCH_SIZE = 50


class LastfmClient:
    def __init__(self, api_key: str, shared_secret: str, session_key: str):
        self.api_key = api_key
        self.shared_secret = shared_secret
        self.session_key = session_key

    def _sign(self, params: Dict[str, str]) -> str:
        items = sorted(
            (k, v) for k, v in params.items() if k not in ("format", "callback")
        )
        sig_string = "".join(f"{k}{v}" for k, v in items) + self.shared_secret
        return hashlib.md5(sig_string.encode("utf-8")).hexdigest()

    def scrobble_batch(self, plays: List[Dict[str, Any]]) -> Dict[str, int]:
        """Submit a batch of plays.

        plays: list of dicts with keys
            artist (str, required)
            track (str, required)
            timestamp (datetime, required, UTC)
            album (str, optional)
            duration_ms (int, optional)

        Returns {"accepted": int, "ignored": int, "errors": int}
        """
        result = {"accepted": 0, "ignored": 0, "errors": 0}
        if not plays:
            return result

        with httpx.Client(timeout=20.0) as client:
            for chunk_start in range(0, len(plays), BATCH_SIZE):
                chunk = plays[chunk_start:chunk_start + BATCH_SIZE]
                params: Dict[str, str] = {
                    "method": "track.scrobble",
                    "api_key": self.api_key,
                    "sk": self.session_key,
                }
                for i, play in enumerate(chunk):
                    if not play.get("artist") or not play.get("track"):
                        continue
                    params[f"artist[{i}]"] = play["artist"]
                    params[f"track[{i}]"] = play["track"]
                    params[f"timestamp[{i}]"] = str(int(play["timestamp"].timestamp()))
                    if play.get("album"):
                        params[f"album[{i}]"] = play["album"]
                    if play.get("duration_ms"):
                        params[f"duration[{i}]"] = str(int(play["duration_ms"] / 1000))

                params["api_sig"] = self._sign(params)
                params["format"] = "json"

                try:
                    r = client.post(API_URL, data=params)
                except httpx.HTTPError as e:
                    log.error("Last.fm scrobble HTTP error: %s", e)
                    result["errors"] += len(chunk)
                    continue

                if r.status_code != 200:
                    log.error(
                        "Last.fm scrobble returned %s: %s",
                        r.status_code, r.text[:300],
                    )
                    result["errors"] += len(chunk)
                    continue

                try:
                    body = r.json()
                except ValueError:
                    log.error("Last.fm returned non-JSON: %s", r.text[:200])
                    result["errors"] += len(chunk)
                    continue

                attrs = body.get("scrobbles", {}).get("@attr", {})
                result["accepted"] += int(attrs.get("accepted", 0))
                result["ignored"] += int(attrs.get("ignored", 0))

                if int(attrs.get("ignored", 0)):
                    # Log per-track ignore reasons (Last.fm returns codes 1-7)
                    scrobble_list = body.get("scrobbles", {}).get("scrobble", [])
                    if isinstance(scrobble_list, dict):
                        scrobble_list = [scrobble_list]
                    for s in scrobble_list:
                        msg = s.get("ignoredMessage", {})
                        code = msg.get("code", "0")
                        if code != "0":
                            log.warning(
                                "  ignored: %s — %s (code %s)",
                                s.get("track", {}).get("#text", "?"),
                                msg.get("#text", "?"),
                                code,
                            )

        return result
