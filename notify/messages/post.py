"""Rich-text (post) message: title plus plain lines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from notify.messages.base import Message


@dataclass(frozen=True)
class PostMessage(Message):
    """A rich-text message.

    Each entry in ``lines`` is one paragraph; inline links use the
    ``[label](https://url)`` syntax and are parsed by the channel.
    """

    title: str = ""
    lines: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.title, str):
            raise ValueError("title must be a string")
        if not isinstance(self.lines, list) or not self.lines:
            raise ValueError("lines must be a non-empty list")
        if not all(isinstance(line, str) and line.strip() for line in self.lines):
            raise ValueError("every line must be a non-empty string")
