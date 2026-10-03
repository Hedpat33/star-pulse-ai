"""Command line entry point: one invocation = one leaderboard run."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from starpulse.config import Config, ConfigError, load_config
from starpulse.github_client import GitHubClient, dedupe
from starpulse.notify_bridge import notify_board
from starpulse.render import render, select_board
from starpulse.snapshot import (
    Snapshot,
    append_history,
    cleanup_history,
    load_baseline,
    save_snapshot,
)

logger = logging.getLogger("starpulse")

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_PARTIAL = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="starpulse",
        description="Generate a GitHub AI star-growth leaderboard (run once).",
    )
    parser.add_argument("--config", default="config.json",
                        help="path to config.json (default: ./config.json)")
    parser.add_argument("--top", type=int, default=None,
                        help="override top_n from config")
    parser.add_argument("--output-dir", default=None,
                        help="override output_dir from config")
    parser.add_argument("--state-dir", default=None,
                        help="override state_dir from config")
    parser.add_argument("--token", default=None,
                        help="GitHub token (else GITHUB_TOKEN env var); never stored")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="enable DEBUG logging")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )

    try:
        config = load_config(
            Path(args.config),
            cli_top=args.top,
            cli_output_dir=args.output_dir,
            cli_state_dir=args.state_dir,
            cli_token=args.token,
            cli_verbose=args.verbose,
        )
    except ConfigError as exc:
        logger.error("configuration error: %s", exc)
        return EXIT_FATAL

    started = datetime.now().astimezone()
    client = GitHubClient(token=config.token)
    result = client.fetch_candidates(config.tags, config.min_stars)

    if config.tags and len(result.failed_tags) == len(config.tags):
        logger.error(
            "all %d tag queries failed (%s); state left untouched",
            len(config.tags),
            ", ".join(result.failed_tags),
        )
        return EXIT_FATAL

    pool = dedupe(result.pool)
    prev = load_baseline(config.state_dir)
    ranking_path = config.output_dir / f"{started:%Y%m%d}.md"

    if prev is None:
        # Baseline run: record the pool so the next run can compute deltas,
        # but emit no ranking (nothing has been compared yet).
        logger.info(
            "first run: baseline recorded (%d candidate(s)); no ranking written",
            len(pool),
        )
        current = Snapshot(generated_at=started, repos=pool)
    else:
        board_rows, newcomers = select_board(prev, pool, top_n=config.top_n)
        current = Snapshot(generated_at=started, repos=pool, top=board_rows)
        board = render(
            prev,
            current,
            newcomers,
            result.failed_tags,
            top_n=config.top_n,
            min_stars=config.min_stars,
            tag_count=len(config.tags),
        )
        # Write order: board first, then the snapshot (atomic), then history.
        try:
            _write_atomic(ranking_path, board)
        except OSError as exc:
            logger.error("failed to write ranking file: %s", exc)
            return EXIT_FATAL
        notify_board(prev, current)

    try:
        save_snapshot(config.state_dir, current)
    except Exception as exc:  # noqa: BLE001 - degrade, board is already out
        logger.warning("failed to save snapshot: %s", exc)

    try:
        append_history(config.state_dir, current)
        cleanup_history(config.state_dir, config.history_retention_days)
    except OSError as exc:
        logger.warning("history append/cleanup failed: %s", exc)

    logger.info(
        "run complete: %d candidate(s), board=%s",
        len(pool),
        ranking_path if prev is not None else "n/a (baseline)",
    )
    if result.failed_tags:
        logger.warning("%d tag(s) failed: %s",
                       len(result.failed_tags), ", ".join(result.failed_tags))
        return EXIT_PARTIAL
    return EXIT_OK


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


if __name__ == "__main__":
    sys.exit(main())
