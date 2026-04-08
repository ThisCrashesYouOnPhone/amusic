"""
Play detection.

Apple's recently-played list is ordered most-recent-first. By diffing the
current list against the previous poll's list, we can identify:

  1. NEW plays — track IDs that weren't in the previous list at all
  2. REPEAT plays — tracks that were in the previous list but moved up
     more than the count of new tracks above them would explain. The only
     thing that moves a track up that list is being played again.

Limitation: a back-to-back replay of the same song (no other song between)
looks identical to a single play. Apple gives us no way to disambiguate.
Repeat detection here only catches the case where at least one different
song was played between repeats. This is documented in the README.
"""
from __future__ import annotations

from typing import List, Dict, Any


def detect_plays(
    current: List[Dict[str, Any]],
    previous: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return new plays in chronological order (oldest first).

    Each entry: {"track": <track dict>, "kind": "new" | "repeat"}

    On a first run (empty previous), returns the entire current list.
    Caller is responsible for deciding whether to actually scrobble those.
    """
    if not previous:
        return [{"track": t, "kind": "new"} for t in reversed(current)]

    prev_index = {t["id"]: i for i, t in enumerate(previous)}
    detected: List[Dict[str, Any]] = []

    for new_idx, track in enumerate(current):
        tid = track["id"]
        if tid not in prev_index:
            detected.append({"track": track, "kind": "new"})
            continue

        old_idx = prev_index[tid]
        # How many genuinely new tracks appear above this one in the current list?
        new_above = sum(1 for t in current[:new_idx] if t["id"] not in prev_index)

        # If no replay happened, this track's expected new index is its
        # old index plus however many new tracks pushed it down.
        expected_idx = old_idx + new_above

        if new_idx < expected_idx:
            # It moved up beyond what new tracks alone would explain → replayed
            detected.append({"track": track, "kind": "repeat"})
        else:
            # We've reached the unchanged tail; everything below is also stable.
            break

    # Reverse so the oldest play is first — this is the order we want for
    # walking timestamps backwards from "now".
    return list(reversed(detected))
