"""Channel abstraction: render hook, fallback chain, serialization."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from notify.messages import CardMessage, Message, PostMessage, TextMessage
from notify.messages.base import MessageTooLarge

MAX_PAYLOAD_BYTES = 20 * 1024


class ChannelError(Exception):
    """Raised when a channel fails to deliver a message."""

    def __init__(self, code: Optional[int], message: str, hint: Optional[str] = None):
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(message)

    def __str__(self) -> str:
        base = f"channel error (code={self.code}): {self.message}"
        if self.hint:
            return f"{base} [{self.hint}]"
        return base


class UnsupportedMessage(Exception):
    """Raised when a channel cannot render a message even after fallback."""

    def __init__(self, type_name: str):
        self.type_name = type_name
        super().__init__(f"no channel fallback available for {type_name}")


def downgrade(message: Message) -> Message:
    """Convert a message to the next level down the fallback chain.

    Chain: CardMessage -> PostMessage -> TextMessage.
    """
    if isinstance(message, CardMessage):
        lines = [line for line in message.body.splitlines() if line.strip()]
        return PostMessage(title=message.title, lines=lines or [message.body.strip()])
    if isinstance(message, PostMessage):
        parts = ([message.title] if message.title else []) + list(message.lines)
        return TextMessage(text="\n".join(parts))
    raise UnsupportedMessage(type(message).__name__)


class Channel(ABC):
    """Base channel: ``send`` orchestrates render -> fallback -> post."""

    def render(self, message: Message) -> Optional[dict]:
        """Return the platform payload, or None when unsupported."""
        return None

    @abstractmethod
    def _post(self, body: bytes) -> dict:
        """Deliver an already-serialized JSON body; return the raw response."""

    def _prepare(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Hook for platform extras (e.g. signature fields); identity by default."""
        return payload

    def send(self, message: Message) -> dict:
        current = message
        payload = self.render(current)
        while payload is None:
            current = downgrade(current)
            payload = self.render(current)
        payload = self._prepare(payload)
        return self._post(self._serialize(payload))

    def _serialize(self, payload: Dict[str, Any]) -> bytes:
        data = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(data) > MAX_PAYLOAD_BYTES:
            raise MessageTooLarge(
                f"payload is {len(data)} bytes (limit {MAX_PAYLOAD_BYTES})"
            )
        return data
