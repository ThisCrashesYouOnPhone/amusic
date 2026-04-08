"""
Heuristic timestamp reconstruction.

Apple's recently-played endpoint does not provide play timestamps. We
reconstruct plausible per-track timestamps by walking BACKWARD from the
current poll time, subtracting each track's duration in turn.

Constraints:
  * timestamps must not predate the previous poll (we'd be claiming
    plays that happened in a window we already covered)
  * if total track duration would exceed the polling window, we
    compress proportionally — this happens when the user skipped
    several songs partway through

This is not perfect, but the error bound is at most one polling
interval, and the resulting Last.fm timeline LOOKS right (tracks
spaced naturally by their lengths) instead of clustering all plays
at the cron-tick second.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional


DEFAULT_DURATION_MS = 180_000  # 3 min fallback


def assign_timestamps(
    plays: List[Dict[str, Any]],
    run_time: datetime,
    last_run_time: Optional[datetime],
    head_offset_seconds: float = 10.0,
) -> List[Dict[str, Any]]:
    """Annotate plays with a 'timestamp' field (UTC datetime, when each play started).

    plays: chronological order, OLDEST first
    run_time: now (UTC)
    last_run_time: previous poll time (UTC) or None on first run
    head_offset_seconds: gap between the most recent play and 'now', so we
                        don't claim a track started exactly at the cron tick
    """
    if not plays:
        return plays

    # Floor the window. On the very first run, fall back to a 6-hour reach.
    floor = last_run_time if last_run_time else (run_time - timedelta(hours=6))

    window_seconds = max(1.0, (run_time - floor).total_seconds() - head_offset_seconds)
    total_duration = sum(
        (p["track"].get("duration_ms") or DEFAULT_DURATION_MS) / 1000
        for p in plays
    )

    # If duration sum exceeds the window (heavy listening / skipped tracks),
    # compress proportionally so timestamps still fit inside the window.
    scale = (window_seconds / total_duration) if total_duration > window_seconds else 1.0

    # Walk newest -> oldest, accumulating offset from run_time.
    cumulative = float(head_offset_seconds)
    annotated: List[Dict[str, Any]] = []
    for play in reversed(plays):
        duration_s = ((play["track"].get("duration_ms") or DEFAULT_DURATION_MS) / 1000) * scale
        ts = run_time - timedelta(seconds=(cumulative + duration_s))
        cumulative += duration_s
        annotated.append({**play, "timestamp": ts})

    # Restore chronological order (oldest first)
    return list(reversed(annotated))
