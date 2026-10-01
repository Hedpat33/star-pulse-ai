"""Persist run snapshots (timestamped, rotated) and history (history.jsonl)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from starpulse.github_client import Repo

logger = logging.getLogger(__name__)

LATEST_FILE = "latest.json"
HISTORY_FILE = "history.jsonl"
SNAPSHOT_PREFIX = "snapshot-"
SNAPSHOT_SUFFIX = ".json"
SNAPSHOT_KEEP = 7


class SnapshotError(Exception):
    """Raised when a snapshot cannot be written."""


@dataclass(frozen=True)
class Snapshot:
    """One run: full candidate pool (name + stars) plus the rows that made the board.

    `repos` is the whole deduplicated pool used for the next run's delta
    ranking; only full_name/stars are persisted. `top` keeps the rendered
    board rows with full metadata for change columns and the departed
    appendix.
    """

    generated_at: datetime
    repos: List[Repo] = field(default_factory=list)
    top: List[Repo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at.isoformat(),
            "repos": [
                {"full_name": r.full_name, "stars": r.stars}
                for r in self.repos
            ],
            "top": [
                {
                    "full_name": r.full_name,
                    "stars": r.stars,
                    "description": r.description,
                    "html_url": r.html_url,
                    "topics": list(r.topics),
                }
                for r in self.top
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Snapshot":
        """Parse a snapshot; requires the `top` key (v2 schema).

        Files written by the old top-N-only schema lack `top` and raise
        KeyError, which load_baseline reports as "no baseline".
        """
        generated_at = datetime.fromisoformat(data["generated_at"])
        pool = [
            Repo(
                full_name=item["full_name"],
                stars=int(item["stars"]),
                description=item.get("description", ""),
                html_url=item.get("html_url", ""),
                topics=list(item.get("topics", [])),
            )
            for item in data.get("repos", [])
        ]
        top = [
            Repo(
                full_name=item["full_name"],
                stars=int(item["stars"]),
                description=item.get("description", ""),
                html_url=item.get("html_url", ""),
                topics=list(item.get("topics", [])),
            )
            for item in data["top"]
        ]
        return cls(generated_at=generated_at, repos=pool, top=top)


def load_baseline(state_dir: Path) -> Optional[Snapshot]:
    """Return the previous run's snapshot as the comparison baseline.

    Prefers the newest `snapshot-*.json` (lexicographic order equals
    chronological order for the timestamp format), falls back to the legacy
    `latest.json` written before timestamped snapshots existed, and returns
    None when nothing usable is found (treated as a first run).
    """
    candidates = sorted(
        state_dir.glob(SNAPSHOT_PREFIX + "*" + SNAPSHOT_SUFFIX), reverse=True
    )
    for path in candidates:
        snapshot = _read_snapshot(path)
        if snapshot is not None:
            return snapshot
    legacy = state_dir / LATEST_FILE
    if legacy.exists():
        return _read_snapshot(legacy)
    return None


def _read_snapshot(path: Path) -> Optional[Snapshot]:
    try:
        return Snapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError) as exc:
        logger.warning(
            "snapshot %s unusable (missing, corrupt, or old schema): %s",
            path, exc,
        )
        return None


def save_snapshot(state_dir: Path, snapshot: Snapshot) -> None:
    """Write one timestamped snapshot atomically, then rotate old ones."""
    state_dir.mkdir(parents=True, exist_ok=True)
    name = (
        f"{SNAPSHOT_PREFIX}{snapshot.generated_at:%Y%m%d-%H%M%S}"
        f"{SNAPSHOT_SUFFIX}"
    )
    path = state_dir / name
    tmp = state_dir / (name + ".tmp")
    try:
        tmp.write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError as exc:
        raise SnapshotError(f"failed to write {path}: {exc}") from exc
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    _rotate(state_dir)


def _rotate(state_dir: Path) -> None:
    """Keep the newest SNAPSHOT_KEEP timestamped snapshots, delete the rest.

    Only files matching the snapshot pattern are candidates, so the legacy
    latest.json and history.jsonl are never touched. Deletion failures are
    warnings only — the board is already written by then.
    """
    snapshots = sorted(
        state_dir.glob(SNAPSHOT_PREFIX + "*" + SNAPSHOT_SUFFIX), reverse=True
    )
    for stale in snapshots[SNAPSHOT_KEEP:]:
        try:
            stale.unlink()
        except OSError as exc:
            logger.warning("failed to delete old snapshot %s: %s", stale, exc)


def append_history(state_dir: Path, snapshot: Snapshot) -> None:
    """Append one JSON line to history.jsonl."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / HISTORY_FILE
    line = json.dumps(snapshot.to_dict(), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def cleanup_history(state_dir: Path, retention_days: int, now: Optional[datetime] = None) -> int:
    """Drop history lines older than retention_days. Returns rows removed.

    Streams line by line through a temp file so memory stays constant.
    Corrupted lines are dropped silently. Returns 0 when nothing to do.
    """
    path = state_dir / HISTORY_FILE
    if not path.exists():
        return 0
    now = now or datetime.now().astimezone()
    cutoff = now - timedelta(days=retention_days)

    kept: List[str] = []
    removed = 0
    has_old = False
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                stamp = datetime.fromisoformat(
                    json.loads(stripped)["generated_at"]
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                removed += 1
                continue
            if stamp < cutoff:
                has_old = True
                removed += 1
            else:
                kept.append(stripped)

    if not has_old and removed == 0:
        return 0

    tmp = state_dir / (HISTORY_FILE + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for line in kept:
            fh.write(line + "\n")
    os.replace(tmp, path)
    logger.info("history cleanup removed %d line(s)", removed)
    return removed
