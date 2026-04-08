"""
Apple Music API client.

Minimal client for the only endpoint we care about: GET /v1/me/recent/played/tracks.

Apple's recently-played endpoint has hard limits we have to live with:
  * max 10 tracks per request (limit param above 10 returns an error)
  * max ~50 most-recent tracks total via offset pagination
  * no play timestamps in the response (we reconstruct them ourselves)
  * the order is most-recent-first

We use the "web-scraped" developer token from music.apple.com — same approach
Cider uses. It works without an Apple Developer Program membership but the
tokens expire roughly every 6 months and need to be re-scraped.
"""
from __future__ import annotations

import logging
from typing import List, Dict, Any

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://api.music.apple.com/v1"
PAGE_SIZE = 10
MAX_OFFSET = 40  # offsets 0, 10, 20, 30, 40 -> 50 tracks total


class TokenExpired(RuntimeError):
    """Raised when Apple returns 401, signalling a token re-scrape is required."""


class AppleMusicClient:
    def __init__(self, dev_token: str, music_user_token: str):
        self.dev_token = dev_token
        self.music_user_token = music_user_token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.dev_token}",
            "Music-User-Token": self.music_user_token,
            # The web-scraped token is bound to apple.com origins. Setting Origin
            # makes the request indistinguishable from the real web player.
            "Origin": "https://music.apple.com",
            "Referer": "https://music.apple.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
            ),
        }

    def get_recently_played_tracks(self) -> List[Dict[str, Any]]:
        """Return up to 50 recently-played tracks, most recent first.

        Raises TokenExpired if Apple returns 401 — caller should surface this
        loudly so the user knows to re-scrape.
        """
        all_tracks: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()  # defensive de-dup across pages

        with httpx.Client(timeout=15.0) as client:
            for offset in range(0, MAX_OFFSET + 1, PAGE_SIZE):
                url = f"{API_BASE}/me/recent/played/tracks"
                params = {"limit": PAGE_SIZE, "offset": offset}

                try:
                    r = client.get(url, params=params, headers=self._headers())
                except httpx.HTTPError as e:
                    log.warning("Apple API request failed at offset %s: %s", offset, e)
                    break

                if r.status_code == 401:
                    raise TokenExpired(
                        "Apple Music API returned 401. Your developer token or "
                        "Music-User-Token has expired. Re-scrape both from the "
                        "music.apple.com console and update GitHub secrets:\n"
                        "  MusicKit.getInstance().developerToken\n"
                        "  MusicKit.getInstance().musicUserToken"
                    )

                if r.status_code != 200:
                    log.warning(
                        "Apple API returned %s at offset %s: %s",
                        r.status_code, offset, r.text[:200],
                    )
                    break

                data = r.json().get("data", [])
                if not data:
                    break

                for item in data:
                    tid = item.get("id", "")
                    if tid and tid not in seen_ids:
                        seen_ids.add(tid)
                        all_tracks.append(self._normalize(item))

                if len(data) < PAGE_SIZE:
                    break  # last page

        return all_tracks

    @staticmethod
    def _normalize(item: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten Apple's response into the dict shape the rest of the app uses."""
        attrs = item.get("attributes", {}) or {}
        return {
            "id": item.get("id", ""),
            "name": attrs.get("name", ""),
            "artist": attrs.get("artistName", ""),
            "album": attrs.get("albumName", ""),
            "duration_ms": int(attrs.get("durationInMillis", 180_000) or 180_000),
            "isrc": attrs.get("isrc"),
        }
