"""Interactive card message: colored header, markdown body, buttons."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from notify.messages.base import Message

CARD_COLORS = frozenset({
    "blue", "wathet", "turquoise", "green", "yellow", "orange",
    "red", "carmine", "violet", "purple", "indigo", "grey",
})


@dataclass(frozen=True)
class RawCardMessage(Message):
    """A fully assembled interactive-card payload, sent verbatim.

    Escape hatch for callers that build the card JSON themselves
    (columns, backgrounds, ...) instead of the flat ``CardMessage``.
    """

    card: dict

    def __post_init__(self) -> None:
        if not isinstance(self.card, dict) or not self.card:
            raise ValueError("card must be a non-empty dict")


@dataclass(frozen=True)
class CardMessage(Message):
    """An interactive card.

    ``buttons`` is a list of ``(label, url)`` pairs rendered as
    open-URL buttons.
    """

    title: str
    body: str
    color: str = "blue"
    buttons: List[Tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be a non-empty string")
        if not isinstance(self.body, str) or not self.body.strip():
            raise ValueError("body must be a non-empty string")
        if self.color not in CARD_COLORS:
            raise ValueError(
                f"color must be one of {sorted(CARD_COLORS)}, got {self.color!r}"
            )
        if not isinstance(self.buttons, list):
            raise ValueError("buttons must be a list of (label, url) tuples")
        for button in self.buttons:
            if (
                not isinstance(button, tuple)
                or len(button) != 2
                or not all(isinstance(part, str) and part.strip() for part in button)
            ):
                raise ValueError(
                    f"invalid button {button!r}; expected (label, url) strings"
                )
