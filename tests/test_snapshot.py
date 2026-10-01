"""Tests for starpulse.snapshot."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from starpulse.github_client import Repo
from starpulse.snapshot import (
    SNAPSHOT_KEEP,
    Snapshot,
    append_history,
    cleanup_history,
    load_baseline,
    save_snapshot,
)

TZ = timezone(timedelta(hours=8))


def make_repo(name: str, stars: int) -> Repo:
    return Repo(
        full_name=name,
        stars=stars,
        description="desc",
        html_url=f"https://github.com/{name}",
        topics=["ai"],
    )


def make_snapshot(stamp: datetime, *repos: Repo) -> Snapshot:
    return Snapshot(generated_at=stamp, repos=list(repos))


def make_full_snapshot(stamp: datetime, pool: list, top: list) -> Snapshot:
    return Snapshot(generated_at=stamp, repos=pool, top=top)


def snap_path(state: Path, stamp: datetime) -> Path:
    return state / f"snapshot-{stamp:%Y%m%d-%H%M%S}.json"


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_roundtrip(self):
        stamp = datetime(2026, 10, 1, 8, 0, tzinfo=TZ)
        snap = make_full_snapshot(
            stamp,
            pool=[make_repo("a/one", 9000), make_repo("b/two", 8000)],
            top=[make_repo("a/one", 9000)],
        )
        save_snapshot(self.state, snap)
        loaded = load_baseline(self.state)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.generated_at, snap.generated_at)
        self.assertEqual(
            [(r.full_name, r.stars) for r in loaded.repos],
            [(r.full_name, r.stars) for r in snap.repos],
        )
        self.assertEqual(loaded.top, snap.top)

    def test_file_named_from_generated_at(self):
        stamp = datetime(2026, 10, 2, 9, 46, 13, tzinfo=TZ)
        save_snapshot(self.state, make_snapshot(stamp, make_repo("a/one", 1)))
        self.assertTrue(snap_path(self.state, stamp).exists())

    def test_pool_rows_persist_only_name_and_stars(self):
        stamp = datetime(2026, 10, 1, 8, 0, tzinfo=TZ)
        snap = make_full_snapshot(
            stamp,
            pool=[make_repo("a/one", 9000)],
            top=[],
        )
        save_snapshot(self.state, snap)
        data = json.loads(snap_path(self.state, stamp).read_text(encoding="utf-8"))
        self.assertEqual(data["repos"], [{"full_name": "a/one", "stars": 9000}])
        self.assertEqual(len(data["top"]), 0)

    def test_top_rows_keep_full_metadata(self):
        stamp = datetime(2026, 10, 1, 8, 0, tzinfo=TZ)
        snap = make_full_snapshot(
            stamp,
            pool=[make_repo("a/one", 9000)],
            top=[make_repo("a/one", 9000)],
        )
        save_snapshot(self.state, snap)
        data = json.loads(snap_path(self.state, stamp).read_text(encoding="utf-8"))
        self.assertEqual(data["top"][0]["description"], "desc")
        self.assertEqual(data["top"][0]["html_url"], "https://github.com/a/one")
        self.assertEqual(data["top"][0]["topics"], ["ai"])

    def test_load_prefers_newest_snapshot(self):
        save_snapshot(self.state, make_snapshot(
            datetime(2026, 9, 30, 8, 0, tzinfo=TZ), make_repo("old/x", 1)))
        save_snapshot(self.state, make_snapshot(
            datetime(2026, 10, 1, 8, 0, tzinfo=TZ), make_repo("new/y", 2)))
        loaded = load_baseline(self.state)
        self.assertEqual(loaded.repos[0].full_name, "new/y")

    def test_corrupt_newest_falls_back_to_older(self):
        save_snapshot(self.state, make_snapshot(
            datetime(2026, 9, 30, 8, 0, tzinfo=TZ), make_repo("old/x", 1)))
        newer = datetime(2026, 10, 1, 8, 0, tzinfo=TZ)
        snap_path(self.state, newer).write_text("{broken", encoding="utf-8")
        loaded = load_baseline(self.state)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.repos[0].full_name, "old/x")

    def test_legacy_latest_json_used_as_fallback(self):
        legacy = {
            "generated_at": "2026-10-01T08:00:00+08:00",
            "repos": [{"full_name": "a/one", "stars": 9000}],
            "top": [],
        }
        (self.state / "latest.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )
        loaded = load_baseline(self.state)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.repos[0].full_name, "a/one")

    def test_snapshot_preferred_over_legacy(self):
        save_snapshot(self.state, make_snapshot(
            datetime(2026, 10, 2, 8, 0, tzinfo=TZ), make_repo("new/y", 2)))
        legacy = {
            "generated_at": "2026-10-01T08:00:00+08:00",
            "repos": [{"full_name": "old/x", "stars": 1}],
            "top": [],
        }
        (self.state / "latest.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )
        loaded = load_baseline(self.state)
        self.assertEqual(loaded.repos[0].full_name, "new/y")

    def test_old_schema_without_top_returns_none(self):
        old = {
            "generated_at": "2026-10-01T08:00:00+08:00",
            "repos": [{"full_name": "a/one", "stars": 9000}],
        }
        (self.state / "latest.json").write_text(
            json.dumps(old), encoding="utf-8"
        )
        self.assertIsNone(load_baseline(self.state))

    def test_missing_file_returns_none(self):
        self.assertIsNone(load_baseline(self.state))

    def test_corrupted_json_returns_none(self):
        (self.state / "latest.json").write_text("{broken", encoding="utf-8")
        self.assertIsNone(load_baseline(self.state))

    def test_missing_key_returns_none(self):
        (self.state / "latest.json").write_text("{}", encoding="utf-8")
        self.assertIsNone(load_baseline(self.state))

    def test_no_tmp_file_left_behind(self):
        save_snapshot(self.state, make_snapshot(
            datetime(2026, 10, 1, 8, 0, tzinfo=TZ), make_repo("a/one", 1)))
        self.assertEqual(list(self.state.glob("*.tmp")), [])

    def test_creates_state_dir(self):
        nested = self.state / "deep" / "state"
        save_snapshot(nested, make_snapshot(
            datetime(2026, 10, 1, 8, 0, tzinfo=TZ)))
        self.assertTrue(snap_path(
            nested, datetime(2026, 10, 1, 8, 0, tzinfo=TZ)).exists())


class RotationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def save_many(self, count: int) -> list:
        """Save `count` snapshots one day apart; return their paths (oldest first)."""
        paths = []
        start = datetime(2026, 9, 1, 8, 0, tzinfo=TZ)
        for day in range(count):
            stamp = start + timedelta(days=day)
            save_snapshot(self.state, make_snapshot(stamp, make_repo("a/one", day)))
            paths.append(snap_path(self.state, stamp))
        return paths

    def test_keeps_newest_seven(self):
        paths = self.save_many(SNAPSHOT_KEEP + 2)
        remaining = sorted(self.state.glob("snapshot-*.json"))
        self.assertEqual(len(remaining), SNAPSHOT_KEEP)
        # The oldest two are gone, the newest seven survive.
        self.assertFalse(paths[0].exists())
        self.assertFalse(paths[1].exists())
        for path in paths[2:]:
            self.assertTrue(path.exists())

    def test_spares_legacy_latest_and_history(self):
        (self.state / "latest.json").write_text("{}", encoding="utf-8")
        (self.state / "history.jsonl").write_text("{}\n", encoding="utf-8")
        self.save_many(SNAPSHOT_KEEP + 3)
        self.assertTrue((self.state / "latest.json").exists())
        self.assertTrue((self.state / "history.jsonl").exists())

    def test_noop_below_keep_limit(self):
        paths = self.save_many(3)
        for path in paths:
            self.assertTrue(path.exists())


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def read_lines(self):
        return (self.state / "history.jsonl").read_text(
            encoding="utf-8").splitlines()

    def test_append_adds_valid_json_lines(self):
        append_history(self.state, make_snapshot(
            datetime(2026, 9, 30, 8, 0, tzinfo=TZ), make_repo("a/one", 1)))
        append_history(self.state, make_snapshot(
            datetime(2026, 10, 1, 8, 0, tzinfo=TZ), make_repo("a/one", 2)))
        lines = self.read_lines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["generated_at"],
                         "2026-09-30T08:00:00+08:00")

    def test_cleanup_drops_expired_lines(self):
        now = datetime(2026, 10, 1, 8, 0, tzinfo=TZ)
        append_history(self.state, make_snapshot(now - timedelta(days=100),
                                                 make_repo("old/x", 1)))
        append_history(self.state, make_snapshot(now - timedelta(days=10),
                                                 make_repo("mid/x", 1)))
        append_history(self.state, make_snapshot(now, make_repo("new/x", 1)))
        removed = cleanup_history(self.state, retention_days=90, now=now)
        self.assertEqual(removed, 1)
        lines = self.read_lines()
        self.assertEqual(len(lines), 2)
        names = [json.loads(l)["repos"][0]["full_name"] for l in lines]
        self.assertNotIn("old/x", names)

    def test_cleanup_keeps_everything_when_nothing_expired(self):
        now = datetime(2026, 10, 1, 8, 0, tzinfo=TZ)
        append_history(self.state, make_snapshot(now, make_repo("a/one", 1)))
        removed = cleanup_history(self.state, retention_days=90, now=now)
        self.assertEqual(removed, 0)
        self.assertEqual(len(self.read_lines()), 1)

    def test_cleanup_skips_corrupted_lines(self):
        now = datetime(2026, 10, 1, 8, 0, tzinfo=TZ)
        append_history(self.state, make_snapshot(now, make_repo("a/one", 1)))
        with (self.state / "history.jsonl").open("a", encoding="utf-8") as fh:
            fh.write("not-json\n")
        removed = cleanup_history(self.state, retention_days=90, now=now)
        self.assertEqual(removed, 1)
        self.assertEqual(len(self.read_lines()), 1)

    def test_cleanup_missing_file_is_noop(self):
        self.assertEqual(cleanup_history(self.state, retention_days=90), 0)


if __name__ == "__main__":
    unittest.main()
