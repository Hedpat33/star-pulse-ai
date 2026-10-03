"""Tests for starpulse.card (pure card construction, no network)."""

import json
import unittest
from datetime import datetime, timedelta, timezone

from starpulse.card import (
    MAX_PAYLOAD_BYTES,
    MAX_ROWS,
    RESERVED_BYTES,
    build_board_card,
)
from starpulse.github_client import Repo
from starpulse.snapshot import Snapshot

TZ = timezone(timedelta(hours=8))
PREV_AT = datetime(2026, 10, 3, 0, 18, tzinfo=TZ)
NOW_AT = datetime(2026, 10, 3, 7, 0, tzinfo=TZ)


def repo(name: str, stars: int) -> Repo:
    return Repo(
        full_name=name,
        stars=stars,
        description=f"about {name}",
        html_url=f"https://github.com/{name}",
        topics=["ai"],
    )


def card_bytes(card: dict) -> bytes:
    return json.dumps(
        card, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


class BuildBoardCardTest(unittest.TestCase):
    def build(self, prev_repos, prev_top, current_repos, current_top):
        prev = Snapshot(generated_at=PREV_AT, repos=prev_repos, top=prev_top)
        current = Snapshot(generated_at=NOW_AT, repos=current_repos, top=current_top)
        return build_board_card(prev, current)

    def test_header_blue_with_title(self):
        card = self.build(
            [repo("a/one", 9000)], [repo("a/one", 9000)],
            [repo("a/one", 9600)], [repo("a/one", 9600)],
        )
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["template"], "blue")
        self.assertEqual(
            card["header"]["title"],
            {"tag": "plain_text", "content": "AI 项目 Star 日飙升榜"},
        )

    def test_time_window_line_first(self):
        card = self.build(
            [repo("a/one", 9000)], [repo("a/one", 9000)],
            [repo("a/one", 9600)], [repo("a/one", 9600)],
        )
        line = card["body"]["elements"][0]
        self.assertEqual(line["tag"], "markdown")
        self.assertEqual(line["content"], "2026-10-03 00:18 / 2026-10-03 07:00")
        self.assertEqual(line["text_size"], "notation")

    def test_header_row_grey_with_four_weighted_columns(self):
        card = self.build(
            [repo("a/one", 9000)], [repo("a/one", 9000)],
            [repo("a/one", 9600)], [repo("a/one", 9600)],
        )
        header = card["body"]["elements"][1]
        self.assertEqual(header["tag"], "column_set")
        self.assertEqual(header["background_style"], "grey")
        self.assertEqual([c["weight"] for c in header["columns"]], [4, 1, 1, 1])
        labels = [c["elements"][0]["content"] for c in header["columns"]]
        self.assertEqual(labels[0], "**项目**")
        self.assertIn("增量", labels[1])
        self.assertIn("Star", labels[2])
        self.assertEqual(labels[3], "**变化**")

    def test_data_row_content(self):
        card = self.build(
            [repo("a/one", 9000), repo("b/two", 8000)],
            [repo("b/two", 8000), repo("a/one", 9000)],
            [repo("a/one", 9600), repo("b/two", 8800)],
            [repo("a/one", 9600), repo("b/two", 8800)],
        )
        cells = [
            c["elements"][0]["content"]
            for c in card["body"]["elements"][2]["columns"]
        ]
        # a/one was #2, now #1 -> up one; delta +600; stars grouped.
        self.assertEqual(cells[0], "[a/one](https://github.com/a/one)")
        self.assertEqual(cells[1], "+600")
        self.assertEqual(cells[2], "9,600")
        self.assertEqual(cells[3], "↑ 1")

    def test_data_row_without_background(self):
        card = self.build(
            [repo("a/one", 9000)], [repo("a/one", 9000)],
            [repo("a/one", 9600)], [repo("a/one", 9600)],
        )
        row = card["body"]["elements"][2]
        self.assertNotIn("background_style", row)

    def test_status_new_for_repo_absent_from_previous_board(self):
        card = self.build(
            [repo("a/one", 9000)], [repo("a/one", 9000)],
            [repo("a/one", 9600), repo("b/two", 8800)],
            [repo("a/one", 9600), repo("b/two", 8800)],
        )
        cells = [
            c["elements"][0]["content"]
            for c in card["body"]["elements"][3]["columns"]
        ]
        self.assertEqual(cells[3], "🆕")

    def test_status_flat_when_previous_board_empty(self):
        card = self.build(
            [repo("a/one", 9000)], [],
            [repo("a/one", 9600)], [repo("a/one", 9600)],
        )
        cells = [
            c["elements"][0]["content"]
            for c in card["body"]["elements"][2]["columns"]
        ]
        self.assertEqual(cells[3], "—")

    def test_rows_capped_at_max_rows(self):
        prev_repos = [repo(f"o/r{i}", 1000) for i in range(15)]
        current = [repo(f"o/r{i}", 1100 + i) for i in range(15)]
        card = self.build(prev_repos, prev_repos, current, current)
        # time line + header row + MAX_ROWS data rows
        self.assertEqual(len(card["body"]["elements"]), 2 + MAX_ROWS)
        self.assertEqual(MAX_ROWS, 10)

    def test_empty_board_still_renders_header_only(self):
        card = self.build([], [], [], [])
        self.assertEqual(len(card["body"]["elements"]), 2)

    def test_oversized_card_shrinks_until_it_fits(self):
        long_name = "o/" + "x" * 3000
        prev_repos = [repo(long_name, 1000)]
        current = [repo(f"{long_name}{i}", 1100 + i) for i in range(MAX_ROWS)]
        card = self.build(prev_repos, [], current, current)
        data_rows = len(card["body"]["elements"]) - 2
        self.assertLess(data_rows, MAX_ROWS)
        self.assertGreaterEqual(data_rows, 1)
        self.assertLessEqual(
            len(card_bytes(card)), MAX_PAYLOAD_BYTES - RESERVED_BYTES
        )


if __name__ == "__main__":
    unittest.main()
