"""Feishu channel configuration from environment variables.

Follows the same convention as ``GITHUB_TOKEN``: credentials are never
stored in ``config.json``, only passed in via the environment at run
time. Missing configuration is *not* an error — ``load_notify_config``
returns ``None`` so callers can treat notifications as optional.
"""

from __future__ import annotations

import os
from typing import Mapping, Optional


class ConfigError(Exception):
    """Raised when notify configuration or CLI usage is invalid."""


def load_notify_config(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[dict]:
    """Return ``{"feishu": {"webhook_url", "secret"}}`` read from the environment.

    ``FEISHU_WEBHOOK_URL`` enables the channel; ``FEISHU_SECRET`` is the
    optional signature secret. Returns ``None`` when no webhook URL is
    configured, which callers should treat as "notifications disabled".
    """
    env = os.environ if env is None else env
    url = (env.get("FEISHU_WEBHOOK_URL") or "").strip()
    if not url:
        return None
    secret = (env.get("FEISHU_SECRET") or "").strip()
    return {"feishu": {"webhook_url": url, "secret": secret}}
