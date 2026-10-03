"""Feishu (Lark) custom-bot webhook channel."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from typing import Any, Dict, Optional

import requests

from notify.channels.base import Channel, ChannelError
from notify.messages import CardMessage, PostMessage, RawCardMessage, TextMessage

_ERROR_HINTS = {
    19021: "sign mismatch or timestamp older than one hour; check server clock",
    19024: "message missed a configured custom keyword",
    19022: "caller IP not in the bot's allowlist",
    11232: "rate limited (100/min, 5/s); retry later",
    9499: "bad request: malformed JSON or payload over 20 KB",
}


def compute_sign(timestamp: str, secret: str) -> str:
    """Official Feishu signature: HMAC-SHA256 with key = timestamp + secret."""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"), b"", hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("ascii")


_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


class FeishuChannel(Channel):
    """Sends messages to a Feishu custom-bot webhook."""

    def __init__(
        self, webhook_url: str, secret: Optional[str] = None, timeout: int = 10
    ):
        if not isinstance(webhook_url, str) or not webhook_url.strip():
            raise ValueError("webhook_url must be a non-empty string")
        self.webhook_url = webhook_url.strip()
        self.secret = secret or None
        self.timeout = timeout

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "FeishuChannel":
        url = cfg.get("webhook_url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("feishu config requires a non-empty 'webhook_url'")
        secret = cfg.get("secret")
        if secret is not None and not isinstance(secret, str):
            raise ValueError("'secret' must be a string")
        return cls(url, secret=secret)

    def _prepare(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.secret:
            return payload
        payload = dict(payload)
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = compute_sign(timestamp, self.secret)
        return payload

    def render(self, message) -> Optional[dict]:
        if isinstance(message, TextMessage):
            return {"msg_type": "text", "content": {"text": self._render_text(message)}}
        if isinstance(message, PostMessage):
            return {
                "msg_type": "post",
                "content": {"post": {"zh_cn": {
                    "title": message.title,
                    "content": [self._parse_line(line) for line in message.lines],
                }}},
            }
        if isinstance(message, CardMessage):
            return {"msg_type": "interactive", "card": self._render_card(message)}
        if isinstance(message, RawCardMessage):
            return {"msg_type": "interactive", "card": message.card}
        return None

    @staticmethod
    def _render_text(message: TextMessage) -> str:
        parts = [message.text]
        parts += [f'<at user_id="{m}">{m}</at>' for m in message.mentions]
        if message.mention_all:
            parts.append('<at user_id="all">所有人</at>')
        return " ".join(parts)

    @staticmethod
    def _parse_line(line: str) -> list:
        nodes = []
        pos = 0
        for match in _LINK_RE.finditer(line):
            if match.start() > pos:
                nodes.append({"tag": "text", "text": line[pos:match.start()]})
            nodes.append({"tag": "a", "text": match.group(1), "href": match.group(2)})
            pos = match.end()
        if pos < len(line):
            nodes.append({"tag": "text", "text": line[pos:]})
        if not nodes:
            nodes.append({"tag": "text", "text": line})
        return nodes

    @staticmethod
    def _render_card(message: CardMessage) -> dict:
        elements = [{"tag": "markdown", "content": message.body}]
        for label, url in message.buttons:
            elements.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": label},
                "type": "default",
                "behaviors": [{"type": "open_url", "default_url": url}],
            })
        return {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": message.title},
                "template": message.color,
            },
            "body": {"elements": elements},
        }

    def _post(self, body: bytes) -> dict:
        try:
            response = requests.post(
                self.webhook_url,
                data=body,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise ChannelError(None, f"request failed: {exc}") from exc
        except ValueError as exc:
            raise ChannelError(None, f"invalid JSON response: {exc}") from exc
        code = data.get("code", 0)
        if code != 0:
            raise ChannelError(
                code, str(data.get("msg", "unknown error")), hint=_ERROR_HINTS.get(code)
            )
        return data
