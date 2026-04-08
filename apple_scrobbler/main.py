"""
Orchestrator: poll Apple → detect new plays → assign timestamps → submit → persist.

Run via:  python -m apple_scrobbler.main

Required env vars:
  APPLE_DEV_TOKEN
  APPLE_MUSIC_USER_TOKEN
  LASTFM_API_KEY
  LASTFM_SHARED_SECRET
  LASTFM_SESSION_KEY

Optional env vars:
  DRY_RUN=1           — fetch and detect, but don't submit or update ledger
  BOOTSTRAP_SCROBBLE=1 — on first run (empty ledger), scrobble the existing
                       50-track recent list instead of just snapshotting it
  LEDGER_PATH=...     — defaults to ./ledger.json
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .apple import AppleMusicClient, TokenExpired
from .lastfm import LastfmClient
from .ledger import Ledger
from .detect import detect_plays
from .timestamps import assign_timestamps

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("scrobbler")


def env(name: str, required: bool = True) -> str:
    value = os.environ.get(name, "").strip()
    if required and not value:
        log.error("Missing required environment variable: %s", name)
        sys.exit(2)
    return value


def truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    apple_dev = env("APPLE_DEV_TOKEN")
    apple_mut = env("APPLE_MUSIC_USER_TOKEN")
    lfm_key = env("LASTFM_API_KEY")
    lfm_secret = env("LASTFM_SHARED_SECRET")
    lfm_session = env("LASTFM_SESSION_KEY")

    dry_run = truthy("DRY_RUN")
    bootstrap = truthy("BOOTSTRAP_SCROBBLE")
    ledger_path = Path(os.environ.get("LEDGER_PATH", "ledger.json"))

    run_time = datetime.now(timezone.utc)
    log.info("=" * 60)
    log.info("Run start: %s (dry_run=%s, bootstrap=%s)",
             run_time.isoformat(), dry_run, bootstrap)

    ledger = Ledger(ledger_path)
    log.info(
        "Ledger: previous_run=%s, total_runs=%s, total_scrobbled=%s",
        ledger.last_run_time,
        ledger.data["stats"]["total_runs"],
        ledger.data["stats"]["total_scrobbled"],
    )

    apple = AppleMusicClient(apple_dev, apple_mut)
    try:
        current = apple.get_recently_played_tracks()
    except TokenExpired as e:
        log.error(str(e))
        return 3

    log.info("Apple returned %s tracks in recently-played.", len(current))
    if not current:
        log.info("Nothing to do. Exiting cleanly.")
        return 0

    # Bootstrap protection: on the very first run we don't want to flood
    # Last.fm with up to 50 backdated guesses unless the user explicitly opts in.
    if not ledger.previous_recent and not bootstrap:
        log.info(
            "First run — snapshotting %s tracks WITHOUT scrobbling. "
            "Set BOOTSTRAP_SCROBBLE=1 to scrobble the initial window.",
            len(current),
        )
        if not dry_run:
            ledger.update(current, run_time, 0)
            ledger.save()
        return 0

    plays = detect_plays(current, ledger.previous_recent)
    log.info("Detected %s plays to scrobble.", len(plays))

    if not plays:
        if not dry_run:
            ledger.update(current, run_time, 0)
            ledger.save()
        log.info("No new plays. Done.")
        return 0

    timestamped = assign_timestamps(plays, run_time, ledger.last_run_time)

    log.info("Plays (chronological):")
    for p in timestamped:
        t = p["track"]
        log.info(
            "  [%-6s] %s — %s — %s @ %s",
            p["kind"],
            t["artist"][:30],
            t["name"][:40],
            t["album"][:30],
            p["timestamp"].isoformat(timespec="seconds"),
        )

    if dry_run:
        log.info("DRY_RUN — skipping Last.fm submission and ledger update.")
        return 0

    lastfm = LastfmClient(lfm_key, lfm_secret, lfm_session)
    payload = [
        {
            "artist": p["track"]["artist"],
            "track": p["track"]["name"],
            "album": p["track"]["album"],
            "timestamp": p["timestamp"],
            "duration_ms": p["track"]["duration_ms"],
        }
        for p in timestamped
    ]
    result = lastfm.scrobble_batch(payload)
    log.info(
        "Last.fm: %s accepted, %s ignored, %s errors",
        result["accepted"], result["ignored"], result["errors"],
    )

    ledger.update(current, run_time, result["accepted"])
    ledger.save()
    log.info("Ledger saved. Run complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
