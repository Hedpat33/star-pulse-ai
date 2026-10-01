"""Load and validate configuration from config.json, CLI flags and env vars."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional

MAX_TAGS = 30
DEFAULT_TAGS = [
    "ai", "llm", "genai", "machine-learning", "deep-learning",
    "generative-ai", "rag", "large-language-model", "gpt",
    "diffusion-model", "reinforcement-learning", "nlp",
    "computer-vision", "pytorch", "tensorflow", "agent",
    "ai-agents", "mcp", "transformers", "chatgpt",
]


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    tags: List[str]
    top_n: int
    min_stars: int
    output_dir: Path
    state_dir: Path
    history_retention_days: int
    token: Optional[str]
    verbose: bool = False


def load_config(
    path: Path,
    *,
    cli_top: Optional[int] = None,
    cli_output_dir: Optional[str] = None,
    cli_state_dir: Optional[str] = None,
    cli_token: Optional[str] = None,
    cli_verbose: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> Config:
    """Read ``path`` and merge CLI overrides. Secrets never come from the file."""
    env = os.environ if env is None else env

    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a JSON object: {path}")
    if "token" in raw:
        raise ConfigError(
            "'token' must not be stored in config file; "
            "use GITHUB_TOKEN env var or --token flag"
        )

    tags = _require_str_list(raw, "tags")
    if not tags:
        raise ConfigError("'tags' must not be empty")
    if len(tags) > MAX_TAGS:
        raise ConfigError(
            f"'tags' must contain at most {MAX_TAGS} items, got {len(tags)}"
        )

    top_n = cli_top if cli_top is not None else _require_int(raw, "top_n", minimum=1)
    if top_n < 1:
        raise ConfigError(f"'top_n' must be >= 1, got {top_n}")
    min_stars = _require_int(raw, "min_stars", minimum=0)
    retention = _require_int(raw, "history_retention_days", minimum=1)

    output_dir = Path(cli_output_dir) if cli_output_dir else Path(
        _require_str(raw, "output_dir")
    )
    state_dir = Path(cli_state_dir) if cli_state_dir else Path(
        _require_str(raw, "state_dir")
    )

    token = cli_token or env.get("GITHUB_TOKEN") or None

    return Config(
        tags=tags,
        top_n=top_n,
        min_stars=min_stars,
        output_dir=output_dir,
        state_dir=state_dir,
        history_retention_days=retention,
        token=token,
        verbose=cli_verbose,
    )


def _require_str(raw: dict, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'{key}' must be a non-empty string")
    return value


def _require_str_list(raw: dict, key: str) -> List[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"'{key}' must be a list of non-empty strings")
    return [v.strip() for v in value]


def _require_int(raw: dict, key: str, minimum: int) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"'{key}' must be an integer")
    if value < minimum:
        raise ConfigError(f"'{key}' must be >= {minimum}, got {value}")
    return value
