"""
Persistent state.

The ledger holds:
  * the previous poll's recent-played list (for diffing)
  * the previous poll's wall time (for the timestamp window floor)
  * cumulative stats (total scrobbled, total runs)

We persist this as a single JSON file checked into the repo. The GitHub
Actions workflow commits any changes back after each run, so the file's
git history doubles as a complete audit log of every poll.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

log = logging.getLogger(__name__)

LEDGER_VERSION = 1


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.data: Dict[str, Any] = self._default()
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(
                    "Could not read ledger at %s (%s); starting fresh.",
                    path, e,
                )

    @staticmethod
    def _default() -> Dict[str, Any]:
        return {
            "version": LEDGER_VERSION,
            "last_run_iso": None,
            "previous_recent": [],
            "stats": {"total_scrobbled": 0, "total_runs": 0},
        }

    @property
    def last_run_time(self) -> Optional[datetime]:
        iso = self.data.get("last_run_iso")
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso)
        except ValueError:
            return None

    @property
    def previous_recent(self) -> List[Dict[str, Any]]:
        return self.data.get("previous_recent", [])

    def update(
        self,
        current_recent: List[Dict[str, Any]],
        run_time: datetime,
        scrobbled_count: int,
    ) -> None:
        self.data["last_run_iso"] = run_time.isoformat()
        self.data["previous_recent"] = current_recent
        self.data["stats"]["total_scrobbled"] = (
            self.data["stats"].get("total_scrobbled", 0) + scrobbled_count
        )
        self.data["stats"]["total_runs"] = (
            self.data["stats"].get("total_runs", 0) + 1
        )

    def save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
