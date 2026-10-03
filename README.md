# star-pulse-ai

English | [简体中文](README.zh-CN.md)

Generate a Markdown leaderboard of the fastest star-growing AI projects on GitHub, designed to run unattended on a schedule.

## Overview

Each run fetches hot projects under a set of AI topic tags, compares them against the previous run, and ranks a TOP board by **star growth** (delta), producing a Markdown report.

- The first run only records a baseline (no board); boards appear from the second run onward.
- Comparison is only against the previous run — no long-term trend analysis.
- An optional `GITHUB_TOKEN` raises the API rate limit.
- **Lightweight**: the only third-party dependency is `requests`, with no database or background service; each run exits when done and all state fits in under 1 MB — ideal for scheduled runs on low-end devices like NAS boxes and Raspberry Pis.

## Output

Each run writes a date-named file such as `output/20261002.md` (same-day reruns overwrite it), containing:

1. **Ranking table** — rank, project, star delta, total stars, rank change (↑/↓/—/🆕)
2. **Project details** — full project descriptions in the same order as the ranking
3. **Dropped-off appendix** — projects on the previous board but not this one (collapsed)

## Quick Start

**1. Install dependencies**

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**2. Run**

```bash
.venv/bin/python -m starpulse
```

**3. Check the results**

- Leaderboard: `output/YYYYMMDD.md`
- Run state: `state/` directory (maintained automatically, no manual handling needed)

Common settings (tags, board size, star threshold) live in [config.json](config.json).

**(Optional) Environment variables**

```bash
export GITHUB_TOKEN=ghp_xxx                               # raises the API rate limit; runs fine without it
export FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx   # posts a TOP 10 card to a Feishu group after each board
export FEISHU_SECRET=xxx                                  # only needed when the bot has signature verification enabled
```

Without `FEISHU_WEBHOOK_URL` notifications are skipped, and a delivery failure never affects the run.

## License

See [LICENSE](LICENSE).
