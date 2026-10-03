"""Feishu leaderboard card: snapshots -> interactive card JSON (pure).

Confirmed design: blue header, grey notation line with the compared
time window, grey weighted header row, then one column_set per ranked
repo (project link / delta / stars / rank change). While the payload
stays under the Feishu 20 KB limit all ``MAX_ROWS`` are kept; beyond
that rows are dropped from the tail until the card fits.
"""

from __future__ import annotations

import json
from typing import Dict, List, Sequence

from starpulse.github_client import Repo
from starpulse.snapshot import Snapshot

TITLE = "AI 项目 Star 日飙升榜"
HEADER_TEMPLATE = "blue"
MAX_ROWS = 10

# Feishu rejects interactive payloads over 20 KB. Reserve headroom for
# the timestamp/sign fields appended at send time.
MAX_PAYLOAD_BYTES = 20 * 1024
RESERVED_BYTES = 512

COLUMN_WEIGHTS = (4, 1, 1, 1)
HEADER_LABELS = ("项目", "📈 增量", "⭐ Star", "变化")

STATUS_NEW = "🆕"
STATUS_FLAT = "—"


def build_board_card(prev: Snapshot, current: Snapshot) -> dict:
    """Build the board card for one run; shrink rows until it fits 20 KB."""
    rows: List[Repo] = list(current.top[:MAX_ROWS])
    card = _build(prev, current, rows)
    while (
        len(_card_bytes(card)) > MAX_PAYLOAD_BYTES - RESERVED_BYTES
        and len(rows) > 1
    ):
        rows.pop()
        card = _build(prev, current, rows)
    return card


def _build(prev: Snapshot, current: Snapshot, rows: Sequence[Repo]) -> dict:
    elements: list = [
        {
            "tag": "markdown",
            "content": (
                f"{prev.generated_at:%Y-%m-%d %H:%M}"
                f" / {current.generated_at:%Y-%m-%d %H:%M}"
            ),
            "text_size": "notation",
            "text_color": "grey",
        },
        _column_set(
            [f"**{label}**" for label in HEADER_LABELS],
            background="grey",
        ),
    ]

    prev_pool: Dict[str, int] = {r.full_name: r.stars for r in prev.repos}
    prev_index: Dict[str, int] = {
        r.full_name: rank for rank, r in enumerate(prev.top, start=1)
    }
    for rank, repo in enumerate(rows, start=1):
        elements.append(
            _column_set(
                [
                    f"[{repo.full_name}]({repo.html_url})",
                    _delta(repo, prev_pool),
                    f"{repo.stars:,}",
                    _status(repo.full_name, rank, prev_index),
                ]
            )
        )

    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": TITLE},
            "template": HEADER_TEMPLATE,
        },
        "body": {"elements": elements},
    }


def _column_set(cells: Sequence[str], background: str = "default") -> dict:
    columns = [
        {
            "tag": "column",
            "width": "weighted",
            "weight": weight,
            "vertical_align": "center",
            "elements": [{"tag": "markdown", "content": cell}],
        }
        for cell, weight in zip(cells, COLUMN_WEIGHTS)
    ]
    column_set = {
        "tag": "column_set",
        "flex_mode": "none",
        "horizontal_spacing": "small",
        "columns": columns,
    }
    if background != "default":
        column_set["background_style"] = background
    return column_set


def _delta(repo: Repo, prev_pool: Dict[str, int]) -> str:
    base = prev_pool.get(repo.full_name)
    if base is None:
        return STATUS_FLAT
    return f"{repo.stars - base:+,}"


def _status(full_name: str, rank: int, prev_index: Dict[str, int]) -> str:
    previous = prev_index.get(full_name)
    if previous is None:
        return STATUS_NEW if prev_index else STATUS_FLAT
    moved = previous - rank
    if moved > 0:
        return f"↑ {moved}"
    if moved < 0:
        return f"↓ {-moved}"
    return STATUS_FLAT


def _card_bytes(card: dict) -> bytes:
    # Same serialization as Channel._serialize, so the pre-check matches
    # the hard limit enforced at send time.
    return json.dumps(
        card, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
