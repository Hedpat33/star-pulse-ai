"""Pure Markdown rendering: baseline snapshot + current snapshot -> string.

No network, no disk IO: ranking selection and rendering are pure functions
so tests can construct snapshots directly.
"""

from __future__ import annotations

from datetime import datetime
from string import Template
from typing import Dict, List, Optional, Sequence, Tuple

from starpulse.github_client import Repo
from starpulse.snapshot import Snapshot

BOARD_TEMPLATE = Template(
    "# 🚀 GitHub AI 项目 Star 榜 TOP $top_n\n"
    "\n"
    "> 数据时间：$generated_at · 对比上次运行间隔：**$interval**\n"
    "> 筛选条件：$tag_count 个 AI 主题标签 · Stars > $min_stars · 按日增 Star 排序\n"
    "\n"
    "$body"
)

STATUS_NEW = "🆕"
STATUS_FLAT = "—"

TABLE_HEADER = (
    "| # | 项目 | 📈 增量 | ⭐ Star | 变化 |\n"
    "|------|------|---------|--------|------|"
)

EMPTY_ROW = "| — | （本次无符合条件的项目） | | | |"

DETAILS_HEADING = "\n\n## 📋 项目详情\n"

DEPARTED_HEADER = (
    "\n<details>\n"
    "<summary>📉 上次在榜、本次已离榜（$count 个）</summary>\n"
    "\n"
    "| 项目 | 上次排名 | 离榜原因 |\n"
    "|------|---------|---------|"
)

NEWCOMERS_NOTE = "\n\n> ⚠ {count} 个新进候选下次参与排序"

FOOTER = "\n\n---\n\n*由 star-pulse-ai 生成*"


def select_board(
    prev: Optional[Snapshot],
    pool: Sequence[Repo],
    *,
    top_n: int,
) -> Tuple[List[Repo], int]:
    """Rank the current pool by star delta against the baseline.

    Returns (board rows, newcomer count). Candidates without a baseline star
    count are excluded from ranking this run and reported as newcomers; ties
    break by stars desc then full_name.
    """
    if prev is None:
        return [], 0
    baseline = {r.full_name: r.stars for r in prev.repos}
    scored: List[Tuple[int, Repo]] = []
    newcomers = 0
    for repo in pool:
        base = baseline.get(repo.full_name)
        if base is None:
            newcomers += 1
            continue
        scored.append((repo.stars - base, repo))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].stars, pair[1].full_name))
    return [repo for _, repo in scored[:top_n]], newcomers


def render(
    prev: Snapshot,
    current: Snapshot,
    newcomers: int,
    failed_tags: Sequence[str],
    *,
    top_n: int,
    min_stars: int,
    tag_count: int,
) -> str:
    """Render the delta-ranked leaderboard Markdown for one run.

    `prev` is the baseline snapshot (pool + previous board rows); `current`
    carries the full pool and the board rows chosen by `select_board`.
    """
    prev_pool: Dict[str, int] = {r.full_name: r.stars for r in prev.repos}
    prev_index: Dict[str, int] = {
        r.full_name: rank for rank, r in enumerate(prev.top, start=1)
    }
    current_pool = {r.full_name for r in current.repos}

    body = _table(current.top, prev_pool, prev_index)
    if current.top:
        body += _details_section(current.top)
    departed = _departed_section(prev, current, current_pool, prev_index, top_n)
    if departed:
        body += "\n" + departed
    if newcomers:
        body += NEWCOMERS_NOTE.format(count=newcomers)
    if failed_tags:
        body += (
            f"\n\n> ⚠ {len(failed_tags)} 个标签抓取失败："
            + ", ".join(failed_tags)
        )
    body += FOOTER

    interval = _format_interval(
        (current.generated_at - prev.generated_at).total_seconds()
    )

    return BOARD_TEMPLATE.substitute(
        top_n=top_n,
        generated_at=current.generated_at.strftime("%Y-%m-%d %H:%M"),
        interval=interval,
        tag_count=tag_count,
        min_stars=f"{min_stars:,}",
        body=body,
    )


def format_interval(seconds: float) -> str:
    """Human readable elapsed time: days, hours, minutes."""
    return _format_interval(seconds)


def _format_interval(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    if seconds >= 86400:
        return f"{_trim(seconds / 86400)} 天"
    if seconds >= 3600:
        return f"{_trim(seconds / 3600)} 小时"
    if seconds >= 60:
        return f"{_trim(seconds / 60)} 分钟"
    return "不到 1 分钟"


def _trim(value: float) -> str:
    text = f"{value:.1f}"
    if text.endswith(".0"):
        return text[:-2]
    return text


def _table(
    repos: Sequence[Repo],
    prev_pool: Dict[str, int],
    prev_index: Dict[str, int],
) -> str:
    lines = [TABLE_HEADER]
    if not repos:
        lines.append(EMPTY_ROW)
        return "\n".join(lines)
    for rank, repo in enumerate(repos, start=1):
        status = _status(repo.full_name, rank, prev_index)
        delta = _delta(repo, prev_pool)
        lines.append(
            f"| {rank} "
            f"| [{repo.full_name}]({repo.html_url}) "
            f"| {delta} "
            f"| {repo.stars:,} "
            f"| {status} |"
        )
    return "\n".join(lines)


def _status(full_name: str, rank: int, prev_index: Dict[str, int]) -> str:
    previous = prev_index.get(full_name)
    if previous is None:
        # No previous board to compare against (first delta board), or the
        # repo is making its board debut -> both read as "no prior rank".
        return STATUS_NEW if prev_index else STATUS_FLAT
    moved = previous - rank
    if moved > 0:
        return f"↑ {moved}"
    if moved < 0:
        return f"↓ {-moved}"
    return STATUS_FLAT


def _delta(repo: Repo, prev_pool: Dict[str, int]) -> str:
    base = prev_pool.get(repo.full_name)
    if base is None:
        return STATUS_FLAT
    return f"{repo.stars - base:+,}"


def _details_section(repos: Sequence[Repo]) -> str:
    """Full-length descriptions in ranking order, as a numbered list."""
    lines = [DETAILS_HEADING]
    for rank, repo in enumerate(repos, start=1):
        lines.append(
            f"{rank}. **[{repo.full_name}]({repo.html_url})** — "
            f"{_description(repo)}"
        )
    return "\n".join(lines)


def _description(repo: Repo) -> str:
    text = repo.description.strip() or (repo.topics[0] if repo.topics else "")
    text = text.replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    return text or "—"


def _departed_section(
    prev: Snapshot,
    current: Snapshot,
    current_pool: set,
    prev_index: Dict[str, int],
    top_n: int,
) -> str:
    current_names = {repo.full_name for repo in current.top}
    departed = [repo for repo in prev.top if repo.full_name not in current_names]
    if not departed:
        return ""

    lines = [Template(DEPARTED_HEADER).substitute(count=len(departed))]
    for repo in departed:
        if repo.full_name in current_pool:
            reason = f"增量跌出 TOP {top_n}"
        else:
            reason = "不再匹配筛选条件"
        rank = prev_index[repo.full_name]
        lines.append(
            f"| [{repo.full_name}]({repo.html_url}) | #{rank} | {reason} |"
        )
    lines.append("")
    lines.append("</details>")
    return "\n".join(lines)
