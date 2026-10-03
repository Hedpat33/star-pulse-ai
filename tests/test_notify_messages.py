"""Tests for notify.messages."""

import unittest

from notify.messages import (
    CardMessage,
    Message,
    MessageTooLarge,
    PostMessage,
    RawCardMessage,
    TextMessage,
)
from notify.messages.card import CARD_COLORS


class MessageBaseTest(unittest.TestCase):
    def test_message_is_abstract_mark(self):
        self.assertTrue(issubclass(TextMessage, Message))
        self.assertTrue(issubclass(Message, object))

    def test_message_too_large_is_exception(self):
        self.assertTrue(issubclass(MessageTooLarge, Exception))


class TextMessageTest(unittest.TestCase):
    def test_minimal_construction(self):
        msg = TextMessage(text="hello")
        self.assertEqual(msg.text, "hello")
        self.assertEqual(msg.mentions, [])
        self.assertFalse(msg.mention_all)

    def test_rejects_blank_text(self):
        with self.assertRaises(ValueError):
            TextMessage(text="   ")

    def test_rejects_non_string_text(self):
        with self.assertRaises(ValueError):
            TextMessage(text=123)  # type: ignore[arg-type]

    def test_rejects_blank_mention_id(self):
        with self.assertRaises(ValueError):
            TextMessage(text="hi", mentions=[""])

    def test_rejects_non_list_mentions(self):
        with self.assertRaises(ValueError):
            TextMessage(text="hi", mentions="ou_x")  # type: ignore[arg-type]

    def test_is_frozen_dataclass(self):
        msg = TextMessage(text="hi")
        with self.assertRaises(Exception):
            msg.text = "changed"  # type: ignore[misc]


class PostMessageTest(unittest.TestCase):
    def test_construction(self):
        msg = PostMessage(title="Daily", lines=["line one", "line two"])
        self.assertEqual(msg.title, "Daily")
        self.assertEqual(msg.lines, ["line one", "line two"])

    def test_defaults(self):
        msg = PostMessage(lines=["only"])
        self.assertEqual(msg.title, "")
        self.assertEqual(msg.lines, ["only"])

    def test_rejects_empty_lines(self):
        with self.assertRaises(ValueError):
            PostMessage(lines=[])

    def test_rejects_blank_line(self):
        with self.assertRaises(ValueError):
            PostMessage(lines=["ok", "  "])


class CardMessageTest(unittest.TestCase):
    def test_construction(self):
        msg = CardMessage(title="Board", body="**bold**")
        self.assertEqual(msg.title, "Board")
        self.assertEqual(msg.color, "blue")
        self.assertEqual(msg.buttons, [])

    def test_accepts_all_documented_colors(self):
        for color in CARD_COLORS:
            msg = CardMessage(title="t", body="b", color=color)
            self.assertEqual(msg.color, color)

    def test_rejects_unknown_color(self):
        with self.assertRaises(ValueError):
            CardMessage(title="t", body="b", color="crimson")

    def test_rejects_blank_title(self):
        with self.assertRaises(ValueError):
            CardMessage(title=" ", body="b")

    def test_rejects_blank_body(self):
        with self.assertRaises(ValueError):
            CardMessage(title="t", body="")

    def test_rejects_malformed_buttons(self):
        with self.assertRaises(ValueError):
            CardMessage(title="t", body="b", buttons=[("only-label",)])
        with self.assertRaises(ValueError):
            CardMessage(title="t", body="b", buttons=[("", "https://x.io")])
        with self.assertRaises(ValueError):
            CardMessage(title="t", body="b", buttons=[("label", "")])


class RawCardMessageTest(unittest.TestCase):
    def test_construction(self):
        card = {"schema": "2.0", "header": {}, "body": {"elements": []}}
        msg = RawCardMessage(card=card)
        self.assertEqual(msg.card, card)

    def test_rejects_non_dict(self):
        with self.assertRaises(ValueError):
            RawCardMessage(card="not a card")  # type: ignore[arg-type]

    def test_rejects_empty_dict(self):
        with self.assertRaises(ValueError):
            RawCardMessage(card={})


if __name__ == "__main__":
    unittest.main()
