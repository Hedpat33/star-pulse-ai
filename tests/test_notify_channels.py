"""Tests for notify.channels.base."""

import json
import unittest
from typing import Optional

from notify.channels import (
    Channel,
    ChannelError,
    UnsupportedMessage,
    downgrade,
)
from notify.messages import CardMessage, PostMessage, TextMessage


class EchoChannel(Channel):
    """Test double: renders every message type."""

    def __init__(self):
        self.posted = []

    def render(self, message) -> Optional[dict]:
        return {"msg_type": type(message).__name__, "payload": "ok"}

    def _post(self, body: bytes) -> dict:
        self.posted.append(body)
        return {"code": 0}


class PostOnlyChannel(Channel):
    """Test double: renders only PostMessage, forcing the card->post fallback."""

    def __init__(self):
        self.posted = []

    def render(self, message) -> Optional[dict]:
        if isinstance(message, PostMessage):
            return {"msg_type": "PostMessage"}
        return None

    def _post(self, body: bytes) -> dict:
        self.posted.append(body)
        return {"code": 0}


class NoRenderChannel(Channel):
    def render(self, message) -> Optional[dict]:
        return None

    def _post(self, body: bytes) -> dict:  # pragma: no cover - never reached
        raise AssertionError("must not post")


class DowngradeTest(unittest.TestCase):
    def test_card_downgrades_to_post(self):
        msg = downgrade(CardMessage(title="T", body="line1\nline2"))
        self.assertIsInstance(msg, PostMessage)
        self.assertEqual(msg.title, "T")
        self.assertEqual(msg.lines, ["line1", "line2"])

    def test_post_downgrades_to_text(self):
        msg = downgrade(PostMessage(title="T", lines=["a", "b"]))
        self.assertIsInstance(msg, TextMessage)
        self.assertEqual(msg.text, "T\na\nb")

    def test_post_without_title_downgrades_to_text(self):
        msg = downgrade(PostMessage(lines=["only"]))
        self.assertEqual(msg.text, "only")

    def test_text_cannot_downgrade(self):
        with self.assertRaises(UnsupportedMessage):
            downgrade(TextMessage(text="hi"))


class SendFlowTest(unittest.TestCase):
    def test_send_posts_rendered_payload(self):
        channel = EchoChannel()
        result = channel.send(TextMessage(text="hello"))
        self.assertEqual(result, {"code": 0})
        self.assertEqual(len(channel.posted), 1)
        body = json.loads(channel.posted[0].decode("utf-8"))
        self.assertEqual(body["msg_type"], "TextMessage")

    def test_send_falls_back_when_render_returns_none(self):
        channel = PostOnlyChannel()
        channel.send(CardMessage(title="T", body="B"))
        body = json.loads(channel.posted[0].decode("utf-8"))
        self.assertEqual(body["msg_type"], "PostMessage")

    def test_send_raises_when_fallback_exhausted(self):
        with self.assertRaises(UnsupportedMessage):
            NoRenderChannel().send(TextMessage(text="hi"))

    def test_prepare_hook_runs_before_post(self):
        class Prepared(EchoChannel):
            def _prepare(self, payload):
                payload = dict(payload)
                payload["signed"] = True
                return payload

        channel = Prepared()
        channel.send(TextMessage(text="x"))
        body = json.loads(channel.posted[0].decode("utf-8"))
        self.assertTrue(body["signed"])

    def test_serialize_rejects_payload_over_20kb(self):
        channel = EchoChannel()
        big = "x" * (21 * 1024)
        with self.assertRaises(Exception) as ctx:
            channel._serialize({"blob": big})
        self.assertEqual(type(ctx.exception).__name__, "MessageTooLarge")

    def test_serialize_accepts_payload_under_limit(self):
        channel = EchoChannel()
        blob = "x" * (18 * 1024)
        data = channel._serialize({"blob": blob})
        self.assertLessEqual(len(data), 20 * 1024)


class ChannelErrorTest(unittest.TestCase):
    def test_attributes_and_str(self):
        err = ChannelError(19021, "sign match fail", hint="check clock")
        self.assertEqual(err.code, 19021)
        self.assertEqual(err.message, "sign match fail")
        self.assertEqual(err.hint, "check clock")
        self.assertIn("19021", str(err))
        self.assertIn("check clock", str(err))

    def test_str_without_hint(self):
        err = ChannelError(None, "boom")
        self.assertNotIn("None [", str(err))


if __name__ == "__main__":
    unittest.main()
