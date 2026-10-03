"""Channel-agnostic message base types."""

from __future__ import annotations

from abc import ABC


class MessageTooLarge(Exception):
    """Raised when a serialized payload exceeds the channel size limit."""


class Message(ABC):
    """Marker base class for all outgoing messages.

    Messages carry data only; rendering into a platform payload belongs
    to Channel implementations.
    """
