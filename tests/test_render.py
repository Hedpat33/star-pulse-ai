"""Tests for starpulse.render (pure functions, no IO)."""

import unittest
from datetime import datetime, timedelta, timezone

from starpulse.github_client import Repo
from starpulse.render import format_interval, render, select_board
from starpulse.snapshot import Snapshot

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 1, 8, 0, tzinfo=TZ)


def repo(name: str, stars: int, description: str = "", topics=None) -> Repo:
    return Repo(
        full_name=name,
        stars=stars,
        description=description,
        html_url=f"https://github.com/{name}",
        topics=topics or [],
    )


def snapshot(*repos: Repo, top=None, stamp: datetime = NOW) -> Snapshot:
    return Snapshot(
        generated_at=stamp,
        repos=list(repos),
        top=list(top) if top is not None else list(repos),
    )


def baseline(*repos: Repo, stamp: datetime = None) -> Snapshot:
    """Baseline snapshot: full pool, board rows optional (default none)."""
    return Snapshot(
        generated_at=stamp or (NOW - timedelta(days=1)),
        repos=list(repos),
        top=[],
    )


def render_board(prev, current, newcomers=0, failed=None, **meta):
    defaults = {"top_n": 10, "min_stars": 5000, "tag_count": 20}
    defaults.update(meta)
    return render(
        prev,
        current,
        newcomers,
        failed or [],
        **defaults,
    )


class SelectBoardTest(unittest.TestCase):
    def test_orders_by_delta_desc(self):
        prev = baseline(
            repo("a/one", 9000),
            repo("b/two", 8000),
            repo("c/three", 8500),
        )
        pool = [
            repo("a/one", 9100),   # +100
            repo("b/two", 8600),   # +600
            repo("c/three", 8700),  # +200
        ]
        rows, newcomers = select_board(prev, pool, top_n=10)
        self.assertEqual(
            [r.full_name for r in rows], ["b/two", "c/three", "a/one"]
        )
        self.assertEqual(newcomers, 0)

    def test_newcomers_excluded_and_counted(self):
        prev = baseline(repo("a/one", 9000))
        pool = [repo("a/one", 9100), repo("new/x", 9999), repo("new/y", 7000)]
        rows, newcomers = select_board(prev, pool, top_n=10)
        self.assertEqual([r.full_name for r in rows], ["a/one"])
        self.assertEqual(newcomers, 2)

    def test_no_baseline_returns_empty(self):
        rows, newcomers = select_board(None, [repo("a/one", 9000)], top_n=10)
        self.assertEqual(rows, [])
        self.assertEqual(newcomers, 0)

    def test_tie_breaks_by_stars_desc_then_name(self):
        prev = baseline(repo("a/one", 9000), repo("b/two", 8000), repo("c/three", 7000))
        pool = [
            repo("c/three", 7100),  # +100
            repo("b/two", 8100),    # +100, more stars
            repo("a/one", 9100),    # +100, most stars
        ]
        rows, _ = select_board(prev, pool, top_n=10)
        self.assertEqual(
            [r.full_name for r in rows], ["a/one", "b/two", "c/three"]
        )

    def test_cuts_to_top_n(self):
        prev = baseline(
            repo("a/one", 9000), repo("b/two", 8000), repo("c/three", 7000)
        )
        pool = [
            repo("a/one", 9010), repo("b/two", 9900), repo("c/three", 9500)
        ]
        rows, _ = select_board(prev, pool, top_n=2)
        self.assertEqual([r.full_name for r in rows], ["c/three", "b/two"])


class HeaderTest(unittest.TestCase):
    def setUp(self):
        prev = baseline(repo("a/one", 9000, "First project"))
        rows, _ = select_board(prev, [repo("a/one", 9100)], top_n=10)
        current = snapshot(
            repo("a/one", 9100, "First project"), top=rows
        )
        self.board = render_board(prev, current)

    def test_header_contains_top_n_and_filters(self):
        self.assertIn("# 🚀 GitHub AI 项目 Star 榜 TOP 10", self.board)
        self.assertIn("Stars > 5,000", self.board)
        self.assertIn("20 个 AI 主题标签", self.board)
        self.assertIn("2026-10-01 08:00", self.board)

    def test_header_sorts_by_delta(self):
        self.assertIn("按日增 Star 排序", self.board)

    def test_table_columns_present(self):
        self.assertIn(
            "| # | 项目 | 📈 增量 | ⭐ Star | 变化 |", self.board
        )

    def test_project_rows_are_links(self):
        self.assertIn("| [a/one](https://github.com/a/one) |", self.board)
        self.assertIn("| 9,100 |", self.board)


class DiffTest(unittest.TestCase):
    def run_board(self, prev_pool, current_pool, prev_top=None, current_top=None,
                  **meta):
        prev = Snapshot(
            generated_at=NOW - timedelta(days=1),
            repos=prev_pool,
            top=prev_top if prev_top is not None else prev_pool,
        )
        rows, newcomers = select_board(prev, current_pool, top_n=meta.get("top_n", 10))
        current = snapshot(*current_pool, top=current_top if current_top is not None else rows)
        return render_board(prev, current, newcomers, **meta)

    def test_rank_up_down_and_flat(self):
        prev_pool = [
            repo("a/one", 9000),
            repo("b/two", 8500),
            repo("c/three", 8000),
        ]
        current_pool = [
            repo("a/one", 9050),    # +50
            repo("b/two", 8500),    # +0
            repo("c/three", 8700),  # +700 -> rank 1 (was #3)
        ]
        board = self.run_board(prev_pool, current_pool)
        # prev ranks: a=1 b=2 c=3; delta ranks: c=1 a=2 b=3
        self.assertIn(
            "| [c/three](https://github.com/c/three) | +700 | 8,700 | ↑ 2 |",
            board,
        )
        self.assertIn(
            "| [a/one](https://github.com/a/one) | +50 | 9,050 | ↓ 1 |",
            board,
        )
        self.assertIn(
            "| [b/two](https://github.com/b/two) | +0 | 8,500 | ↓ 1 |",
            board,
        )

    def test_first_delta_board_shows_flat_status(self):
        # Baseline has no previous board rows -> nothing to compare.
        prev = baseline(repo("a/one", 9000), repo("b/two", 8000))
        pool = [repo("a/one", 9100), repo("b/two", 8600)]
        rows, newcomers = select_board(prev, pool, top_n=10)
        current = snapshot(*pool, top=rows)
        board = render_board(prev, current, newcomers)
        self.assertEqual(board.count("| — |"), 2)
        self.assertNotIn("↑", board)
        self.assertNotIn("↓", board)

    def test_delta_shows_difference(self):
        prev = baseline(repo("a/one", 9000))
        pool = [repo("a/one", 10023)]
        rows, newcomers = select_board(prev, pool, top_n=10)
        board = render_board(prev, snapshot(*pool, top=rows), newcomers)
        self.assertIn("| +1,023 | 10,023 |", board)

    def test_negative_delta_ranked_last(self):
        prev = baseline(repo("a/one", 9000), repo("b/two", 8000))
        pool = [repo("a/one", 8988), repo("b/two", 8050)]  # -12, +50
        rows, newcomers = select_board(prev, pool, top_n=10)
        self.assertEqual([r.full_name for r in rows], ["b/two", "a/one"])
        board = render_board(prev, snapshot(*pool, top=rows), newcomers)
        self.assertIn("| -12 | 8,988 |", board)

    def test_newcomer_note_in_footer(self):
        prev = baseline(repo("a/one", 9000))
        pool = [repo("a/one", 9100), repo("new/x", 9999)]
        rows, newcomers = select_board(prev, pool, top_n=10)
        board = render_board(prev, snapshot(*pool, top=rows), newcomers)
        self.assertIn("> ⚠ 1 个新进候选下次参与排序", board)
        self.assertNotIn("new/x", board)

    def test_interval_one_and_half_days(self):
        prev = baseline(repo("a/one", 9000), stamp=NOW - timedelta(days=1, hours=12))
        pool = [repo("a/one", 9000)]
        rows, newcomers = select_board(prev, pool, top_n=10)
        board = render_board(prev, snapshot(*pool, top=rows), newcomers)
        self.assertIn("对比上次运行间隔：**1.5 天**", board)

    def test_interval_exact_one_day(self):
        prev = baseline(repo("a/one", 9000), stamp=NOW - timedelta(days=1))
        pool = [repo("a/one", 9000)]
        rows, newcomers = select_board(prev, pool, top_n=10)
        board = render_board(prev, snapshot(*pool, top=rows), newcomers)
        self.assertIn("**1 天**", board)


class DepartedTest(unittest.TestCase):
    def run_board(self, prev_top, pool, top_n=10):
        prev = Snapshot(
            generated_at=NOW - timedelta(days=1),
            repos=pool,
            top=prev_top,
        )
        rows, newcomers = select_board(prev, pool, top_n=top_n)
        current = snapshot(*pool, top=rows)
        return render_board(prev, current, newcomers, top_n=top_n)

    def test_dropped_out_of_delta_ranking(self):
        # z/last was #2 on the board but has the lowest delta now.
        prev_top = [repo("a/one", 9000), repo("z/last", 6000)]
        pool = [repo("a/one", 9100), repo("z/last", 6001)]
        board = self.run_board(prev_top, pool, top_n=1)
        self.assertIn("<details>", board)
        self.assertIn("已离榜（1 个）", board)
        self.assertIn(
            "| [z/last](https://github.com/z/last) | #2 | 增量跌出 TOP 1 |",
            board,
        )

    def test_no_longer_matching_filter(self):
        # gone/x is not in the current pool at all.
        prev_top = [repo("a/one", 9000), repo("gone/x", 6000)]
        pool = [repo("a/one", 9100)]
        prev = Snapshot(
            generated_at=NOW - timedelta(days=1), repos=prev_top, top=prev_top
        )
        rows, newcomers = select_board(prev, pool, top_n=10)
        board = render_board(prev, snapshot(*pool, top=rows), newcomers)
        self.assertIn(
            "| [gone/x](https://github.com/gone/x) | #2 | 不再匹配筛选条件 |",
            board,
        )

    def test_departed_table_rows_follow_separator_without_blank_line(self):
        prev_top = [repo("a/one", 9000), repo("z/last", 6000)]
        pool = [repo("a/one", 9100), repo("z/last", 6001)]
        board = self.run_board(prev_top, pool, top_n=1)
        lines = board.splitlines()
        sep_index = lines.index("|------|---------|---------|")
        # No blank line right after the separator, otherwise the table breaks.
        self.assertTrue(lines[sep_index + 1].startswith("| [z/last]"))

    def test_no_departed_section_when_none(self):
        prev_top = [repo("a/one", 9000)]
        pool = [repo("a/one", 9100)]
        board = self.run_board(prev_top, pool)
        self.assertNotIn("<details>", board)

    def test_baseline_without_board_rows_has_no_departed_section(self):
        prev = baseline(repo("a/one", 9000))
        pool = [repo("a/one", 9100)]
        rows, newcomers = select_board(prev, pool, top_n=10)
        board = render_board(prev, snapshot(*pool, top=rows), newcomers)
        self.assertNotIn("<details>", board)


class FormattingTest(unittest.TestCase):
    def run_board(self, current_repo, **meta):
        prev = baseline(repo("a/one", 9000))
        pool = [current_repo]
        rows, newcomers = select_board(prev, pool, top_n=10)
        return render_board(prev, snapshot(*pool, top=rows), newcomers, **meta)

    def test_pipe_in_description_is_escaped(self):
        board = self.run_board(
            repo("a/one", 9000, "fast | easy | simple tool")
        )
        self.assertIn("fast \\| easy \\| simple tool", board)

    def test_newline_in_description_collapsed(self):
        board = self.run_board(repo("a/one", 9000, "line one\nline two"))
        self.assertIn("** — line one line two", board)

    def test_long_description_not_truncated_in_details(self):
        long_desc = "x" * 120
        board = self.run_board(repo("a/one", 9000, long_desc))
        self.assertIn(long_desc, board)
        self.assertNotIn("x" * 59 + "…", board)

    def test_empty_description_falls_back_to_topic(self):
        board = self.run_board(
            repo("a/one", 9000, "", topics=["machine-learning"])
        )
        self.assertIn("** — machine-learning", board)

    def test_empty_board_message(self):
        prev = baseline(repo("a/one", 9000))
        board = render_board(prev, snapshot(repo("a/one", 9100), top=[]))
        self.assertIn("本次无符合条件的项目", board)

    def test_failure_note_lists_tags(self):
        board = self.run_board(repo("a/one", 9000), failed=["ai", "llm"])
        self.assertIn("⚠ 2 个标签抓取失败：ai, llm", board)

    def test_no_failure_note_when_all_ok(self):
        board = self.run_board(repo("a/one", 9000))
        self.assertNotIn("抓取失败", board)

    def test_footer_present(self):
        board = self.run_board(repo("a/one", 9000))
        self.assertTrue(board.rstrip().endswith("*由 star-pulse-ai 生成*"))


class DetailsTest(unittest.TestCase):
    def run_board(self, pool, prev_top=None, **meta):
        prev = Snapshot(
            generated_at=NOW - timedelta(days=1),
            repos=pool,
            top=prev_top if prev_top is not None else pool,
        )
        rows, newcomers = select_board(prev, pool, top_n=meta.get("top_n", 10))
        current = snapshot(*pool, top=rows)
        return render_board(prev, current, newcomers, **meta)

    def test_heading_present(self):
        board = self.run_board([repo("a/one", 9000, "Does things")])
        self.assertIn("## 📋 项目详情", board)

    def test_details_follow_ranking_order(self):
        prev = baseline(
            repo("a/one", 9000), repo("b/two", 8500), repo("c/three", 8000)
        )
        pool = [
            repo("a/one", 9050, "first desc"),    # +50
            repo("b/two", 8500, "second desc"),   # +0
            repo("c/three", 8700, "third desc"),  # +700 -> rank 1
        ]
        rows, newcomers = select_board(prev, pool, top_n=10)
        board = render_board(prev, snapshot(*pool, top=rows), newcomers)
        ranking = [name for name in ("c/three", "a/one", "b/two")]
        details_start = board.index("## 📋 项目详情")
        section = board[details_start:]
        positions = [section.index(name) for name in ranking]
        self.assertEqual(positions, sorted(positions))

    def test_details_count_matches_table_rows(self):
        prev = baseline(repo("a/one", 9000), repo("b/two", 8500))
        pool = [repo("a/one", 9050, "d1"), repo("b/two", 8600, "d2")]
        rows, newcomers = select_board(prev, pool, top_n=10)
        board = render_board(prev, snapshot(*pool, top=rows), newcomers)
        section = board[board.index("## 📋 项目详情"):]
        detail_lines = [l for l in section.splitlines() if l[:2] in ("1.", "2.")]
        self.assertEqual(len(detail_lines), len(rows))

    def test_empty_board_renders_no_details(self):
        prev = baseline(repo("a/one", 9000))
        board = render_board(prev, snapshot(repo("a/one", 9100), top=[]))
        self.assertNotIn("## 📋 项目详情", board)

    def test_table_and_details_are_adjacent(self):
        board = self.run_board([repo("a/one", 9000, "Does things")])
        lines = board.splitlines()
        heading_index = lines.index("## 📋 项目详情")
        # The table separator must be the line right before the heading's
        # blank line, i.e. no other section sneaks between table and details.
        self.assertEqual(lines[heading_index - 1], "")
        self.assertTrue(lines[heading_index - 2].startswith("| 1 |"))


class IntervalFormatTest(unittest.TestCase):
    def test_days(self):
        self.assertEqual(format_interval(86400), "1 天")
        self.assertEqual(format_interval(86400 * 2.5), "2.5 天")

    def test_hours(self):
        self.assertEqual(format_interval(3600 * 3), "3 小时")
        self.assertEqual(format_interval(3600 * 1.5), "1.5 小时")

    def test_minutes(self):
        self.assertEqual(format_interval(120), "2 分钟")

    def test_sub_minute(self):
        self.assertEqual(format_interval(30), "不到 1 分钟")

    def test_negative_clamped(self):
        self.assertEqual(format_interval(-5), "不到 1 分钟")


if __name__ == "__main__":
    unittest.main()
