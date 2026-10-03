"""Plain text message with optional mentions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from notify.messages.base import Message


@dataclass(frozen=True)
class TextMessage(Message):
    """A plain-text message.

    ``mentions`` holds open_id / user_id values to @ after the body;
    ``mention_all`` @s everyone in the chat.
    """

    text: str
    mentions: List[str] = field(default_factory=list)
    mention_all: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must be a non-empty string")
        if not isinstance(self.mentions, list) or not all(
            isinstance(m, str) and m.strip() for m in self.mentions
        ):
            raise ValueError("mentions must be a list of non-empty strings")
