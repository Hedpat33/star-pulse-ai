"""Best-effort Feishu notification for the daily board.

Weak dependency contract: every failure — notify package missing,
``FEISHU_WEBHOOK_URL`` unset, oversized payload, network error — is
swallowed into a single log line and ``False``. This module must never
raise, so a notification problem can never fail a starpulse run.
"""

from __future__ import annotations

import logging
from typing import Optional

from starpulse.card import build_board_card
from starpulse.snapshot import Snapshot

logger = logging.getLogger("starpulse")


def notify_board(prev: Optional[Snapshot], current: Snapshot) -> bool:
    """Send the board card to Feishu; True only on confirmed delivery."""
    if prev is None or not current.top:
        return False
    try:
        card = build_board_card(prev, current)
        from notify.channels import FeishuChannel
        from notify.config import load_notify_config
        from notify.messages import RawCardMessage

        config = load_notify_config()
        if config is None:
            logger.info(
                "FEISHU_WEBHOOK_URL not set; board card not sent"
            )
            return False
        FeishuChannel.from_config(config["feishu"]).send(
            RawCardMessage(card=card)
        )
    except Exception as exc:  # noqa: BLE001 - notifications are best-effort
        logger.warning("board card not delivered: %s", exc)
        return False
    logger.info("board card sent to feishu")
    return True
