"""Tests for the python -m notify CLI."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from notify.__main__ import build_message, build_parser, main


def make_response(payload: dict) -> mock.Mock:
    resp = mock.Mock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class BuildMessageTest(unittest.TestCase):
    def parse(self, argv):
        return build_parser().parse_args(argv)

    def test_text_message(self):
        args = self.parse(["--type", "text", "--text", "hello"])
        msg = build_message(args)
        self.assertEqual(msg.text, "hello")

    def test_text_requires_text(self):
        args = self.parse(["--type", "text"])
        with self.assertRaises(Exception):
            build_message(args)

    def test_post_from_body(self):
        args = self.parse(
            ["--type", "post", "--title", "T", "--body", "line1\nline2"]
        )
        msg = build_message(args)
        self.assertEqual(msg.title, "T")
        self.assertEqual(msg.lines, ["line1", "line2"])

    def test_card_with_buttons(self):
        args = self.parse([
            "--type", "card",
            "--title", "T",
            "--body", "B",
            "--color", "green",
            "--button", "Open=https://example.com",
            "--button", "Docs=https://docs.example.com",
        ])
        msg = build_message(args)
        self.assertEqual(msg.color, "green")
        self.assertEqual(
            msg.buttons,
            [("Open", "https://example.com"), ("Docs", "https://docs.example.com")],
        )

    def test_invalid_button_spec_rejected(self):
        args = self.parse(
            ["--type", "card", "--title", "T", "--body", "B", "--button", "nourl"]
        )
        with self.assertRaises(Exception):
            build_message(args)

    def test_card_requires_title(self):
        args = self.parse(["--type", "card", "--body", "B"])
        with self.assertRaises(Exception):
            build_message(args)

    def test_body_file_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            body_path = Path(tmp) / "body.md"
            body_path.write_text("# from file", encoding="utf-8")
            args = self.parse(
                ["--type", "card", "--title", "T", "--body-file", str(body_path)]
            )
            msg = build_message(args)
        self.assertEqual(msg.body, "# from file")

    def test_body_and_body_file_conflict(self):
        args = self.parse(
            ["--type", "card", "--title", "T", "--body", "a", "--body-file", "b.md"]
        )
        with self.assertRaises(Exception):
            build_message(args)


class MainTest(unittest.TestCase):
    URL = "https://open.feishu.cn/open-apis/bot/v2/hook/x"

    def invoke(self, env, argv=None):
        with mock.patch.dict(os.environ, env, clear=True):
            return main(argv or ["--type", "text", "--text", "hi"])

    def test_happy_path_text(self):
        with mock.patch(
            "notify.__main__.FeishuChannel._post", return_value={"code": 0}
        ) as post:
            code = self.invoke({"FEISHU_WEBHOOK_URL": self.URL,
                                "FEISHU_SECRET": "s"})
        self.assertEqual(code, 0)
        self.assertEqual(post.call_count, 1)

    def test_channel_error_returns_one(self):
        from notify.channels import ChannelError

        with mock.patch(
            "notify.__main__.FeishuChannel._post",
            side_effect=ChannelError(19021, "sign fail", hint="check clock"),
        ):
            code = self.invoke({"FEISHU_WEBHOOK_URL": self.URL})
        self.assertEqual(code, 1)

    def test_missing_webhook_env_returns_one(self):
        code = self.invoke({})
        self.assertEqual(code, 1)

    def test_blank_webhook_env_returns_one(self):
        code = self.invoke({"FEISHU_WEBHOOK_URL": "   "})
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
