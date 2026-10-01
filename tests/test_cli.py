"""Integration tests for starpulse.cli with a faked GitHub client (no network)."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from starpulse import cli
from starpulse.github_client import FetchResult, Repo
from starpulse.snapshot import Snapshot, save_snapshot

TZ = timezone(timedelta(hours=8))


def repo(name: str, stars: int) -> Repo:
    return Repo(
        full_name=name,
        stars=stars,
        description=f"about {name}",
        html_url=f"https://github.com/{name}",
        topics=["ai"],
    )


class FakeClient:
    """Stand-in for GitHubClient configured per test."""

    result = FetchResult()

    def __init__(self, token=None, **kwargs):
        self.token = token

    def fetch_candidates(self, tags, min_stars):
        return FakeClient.result


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.output_dir = self.root / "out"
        self.state_dir = self.root / "state"
        self.config_path = self.root / "config.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "tags": ["ai", "llm"],
                    "top_n": 10,
                    "min_stars": 5000,
                    "output_dir": str(self.output_dir),
                    "state_dir": str(self.state_dir),
                    "history_retention_days": 90,
                }
            ),
            encoding="utf-8",
        )
        FakeClient.result = FetchResult()

    def run_cli(self):
        with mock.patch.object(cli, "GitHubClient", FakeClient):
            return cli.main(["--config", str(self.config_path)])

    def seed_previous(self, pool=None, top=None):
        prev = Snapshot(
            generated_at=datetime(2026, 9, 30, 8, 0, tzinfo=TZ),
            repos=pool or [repo("a/one", 9000), repo("z/old", 6000)],
            top=top if top is not None else (
                [repo("a/one", 9000), repo("z/old", 6000)]
            ),
        )
        save_snapshot(self.state_dir, prev)

    def board_path(self):
        files = sorted(self.output_dir.glob("*.md"))
        self.assertEqual(len(files), 1, files)
        return files[0]

    def read_board(self):
        path = self.board_path()
        self.assertRegex(path.name, r"^\d{8}\.md$")
        return path.read_text(encoding="utf-8")

    def read_latest_snapshot(self):
        files = sorted(self.state_dir.glob("snapshot-*.json"))
        self.assertTrue(files, "no timestamped snapshot written")
        return json.loads(files[-1].read_text(encoding="utf-8"))

    def test_first_run_records_baseline_without_board(self):
        FakeClient.result = FetchResult(
            pool=[repo("a/one", 9500), repo("b/new", 7000)]
        )
        code = self.run_cli()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertFalse(list(self.output_dir.glob("*.md")))

        latest = self.read_latest_snapshot()
        self.assertEqual(
            [r["full_name"] for r in latest["repos"]], ["a/one", "b/new"]
        )
        self.assertEqual(latest["top"], [])
        history = (self.state_dir / "history.jsonl").read_text(encoding="utf-8")
        self.assertEqual(len(history.splitlines()), 1)

    def test_second_run_writes_delta_board(self):
        self.seed_previous()
        FakeClient.result = FetchResult(
            pool=[repo("a/one", 9600), repo("b/new", 7000)]
        )
        code = self.run_cli()
        self.assertEqual(code, cli.EXIT_OK)

        board = self.read_board()
        self.assertIn("[a/one](https://github.com/a/one)", board)
        self.assertIn("+600", board)
        self.assertNotIn("抓取失败", board)
        # b/new has no baseline -> excluded from ranking, reported instead.
        self.assertNotIn("b/new](https://github.com/b/new)", board)
        self.assertIn("1 个新进候选下次参与排序", board)

        latest = self.read_latest_snapshot()
        self.assertEqual(
            [r["full_name"] for r in latest["repos"]], ["a/one", "b/new"]
        )
        self.assertEqual(
            [r["full_name"] for r in latest["top"]], ["a/one"]
        )
        history = (self.state_dir / "history.jsonl").read_text(encoding="utf-8")
        # seed_previous only writes a snapshot; this run adds the first line.
        self.assertEqual(len(history.splitlines()), 1)

    def test_departed_rows_and_delta_board(self):
        self.seed_previous()
        FakeClient.result = FetchResult(pool=[repo("a/one", 9600)])
        self.assertEqual(self.run_cli(), cli.EXIT_OK)
        board = self.read_board()
        self.assertIn("+600", board)
        self.assertIn("已离榜", board)
        self.assertIn("z/old", board)

    def test_pool_snapshot_keeps_full_name_and_stars_only(self):
        self.seed_previous()
        FakeClient.result = FetchResult(pool=[repo("a/one", 9600)])
        self.assertEqual(self.run_cli(), cli.EXIT_OK)
        latest = self.read_latest_snapshot()
        self.assertEqual(
            latest["repos"], [{"full_name": "a/one", "stars": 9600}]
        )
        self.assertEqual(len(latest["top"]), 1)
        self.assertIn("description", latest["top"][0])

    def test_partial_failure_exits_2_with_footer_warning(self):
        self.seed_previous()
        FakeClient.result = FetchResult(
            pool=[repo("a/one", 9100)], failed_tags=["llm"]
        )
        code = self.run_cli()
        self.assertEqual(code, cli.EXIT_PARTIAL)
        board = self.read_board()
        self.assertIn("⚠ 1 个标签抓取失败：llm", board)
        # State must still be written on partial success.
        self.assertTrue(list(self.state_dir.glob("snapshot-*.json")))

    def test_total_failure_leaves_state_untouched(self):
        self.seed_previous()
        seeded = sorted(self.state_dir.glob("snapshot-*.json"))
        self.assertTrue(seeded)
        before = seeded[0].read_text(encoding="utf-8")
        FakeClient.result = FetchResult(failed_tags=["ai", "llm"])
        code = self.run_cli()
        self.assertEqual(code, cli.EXIT_FATAL)
        after = sorted(self.state_dir.glob("snapshot-*.json"))
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0].read_text(encoding="utf-8"), before)
        self.assertFalse(list(self.output_dir.glob("*.md")))
        self.assertFalse((self.state_dir / "history.jsonl").exists())

    def test_legacy_latest_json_still_provides_baseline(self):
        # Pre-upgrade state: only latest.json exists, no snapshot-*.json.
        prev = Snapshot(
            generated_at=datetime(2026, 9, 30, 8, 0, tzinfo=TZ),
            repos=[repo("a/one", 9000)],
            top=[repo("a/one", 9000)],
        )
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "latest.json").write_text(
            json.dumps(prev.to_dict()), encoding="utf-8"
        )
        FakeClient.result = FetchResult(pool=[repo("a/one", 9600)])
        code = self.run_cli()
        self.assertEqual(code, cli.EXIT_OK)
        board = self.read_board()
        # Delta board proves the legacy baseline was used, not a fresh reset.
        self.assertIn("+600", board)

    def test_missing_config_exits_1(self):
        missing = self.root / "absent.json"
        with mock.patch.object(cli, "GitHubClient", FakeClient):
            code = cli.main(["--config", str(missing)])
        self.assertEqual(code, cli.EXIT_FATAL)

    def test_token_passed_to_client_from_env(self):
        seen = {}

        class TokenClient(FakeClient):
            def __init__(self, token=None, **kwargs):
                seen["token"] = token

        FakeClient.result = FetchResult(pool=[repo("a/one", 9000)])
        with mock.patch.object(cli, "GitHubClient", TokenClient):
            code = cli.main(
                ["--config", str(self.config_path), "--token", "ghp_x"]
            )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(seen["token"], "ghp_x")

    def test_cli_top_override_limits_board(self):
        self.seed_previous(
            pool=[repo("a/one", 9000), repo("b/two", 8000), repo("c/three", 7000)],
            top=[],
        )
        FakeClient.result = FetchResult(
            pool=[repo("a/one", 9100), repo("b/two", 8900), repo("c/three", 7800)]
        )
        with mock.patch.object(cli, "GitHubClient", FakeClient):
            code = cli.main(["--config", str(self.config_path), "--top", "2"])
        self.assertEqual(code, cli.EXIT_OK)
        board = self.read_board()
        ranked = [line for line in board.splitlines()
                  if line.startswith("| 1 ") or line.startswith("| 2 ")
                  or line.startswith("| 3 ")]
        self.assertEqual(len(ranked), 2)
        self.assertIn("TOP 2", board)


if __name__ == "__main__":
    unittest.main()
