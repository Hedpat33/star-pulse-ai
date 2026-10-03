"""Tests for the weak-dependency notification bridge (never raises)."""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from starpulse.github_client import Repo
from starpulse.notify_bridge import notify_board
from starpulse.snapshot import Snapshot

TZ = timezone(timedelta(hours=8))
URL = "https://open.feishu.cn/open-apis/bot/v2/hook/test"


def repo(name: str, stars: int) -> Repo:
    return Repo(
        full_name=name,
        stars=stars,
        description="about",
        html_url=f"https://github.com/{name}",
        topics=["ai"],
    )


def snapshots():
    prev = Snapshot(
        generated_at=datetime(2026, 10, 2, 8, 0, tzinfo=TZ),
        repos=[repo("a/one", 9000)],
        top=[repo("a/one", 9000)],
    )
    current = Snapshot(
        generated_at=datetime(2026, 10, 3, 8, 0, tzinfo=TZ),
        repos=[repo("a/one", 9600)],
        top=[repo("a/one", 9600)],
    )
    return prev, current


class NotifyBoardTest(unittest.TestCase):
    def test_unconfigured_webhook_skips_quietly(self):
        # The core contract: no FEISHU_WEBHOOK_URL -> no send, no error.
        prev, current = snapshots()
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(notify_board(prev, current))

    def test_baseline_run_skips(self):
        _, current = snapshots()
        with mock.patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": URL}):
            self.assertFalse(notify_board(None, current))

    def test_empty_board_skips(self):
        prev, _ = snapshots()
        empty = Snapshot(
            generated_at=datetime(2026, 10, 3, 8, 0, tzinfo=TZ), repos=[], top=[]
        )
        with mock.patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": URL}):
            self.assertFalse(notify_board(prev, empty))

    def test_successful_send_returns_true(self):
        prev, current = snapshots()
        with mock.patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": URL}), \
                mock.patch(
                    "notify.channels.feishu.FeishuChannel.send"
                ) as send:
            self.assertTrue(notify_board(prev, current))
        self.assertEqual(send.call_count, 1)
        message = send.call_args.args[0]
        self.assertEqual(message.card["header"]["template"], "blue")

    def test_channel_error_returns_false(self):
        from notify.channels import ChannelError

        prev, current = snapshots()
        with mock.patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": URL}), \
                mock.patch(
                    "notify.channels.feishu.FeishuChannel.send",
                    side_effect=ChannelError(19021, "sign fail"),
                ):
            self.assertFalse(notify_board(prev, current))

    def test_missing_notify_package_returns_false(self):
        prev, current = snapshots()
        # None-ing only the top package is not enough: cached submodules
        # would still import, so block every entry the bridge touches.
        with mock.patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": URL}), \
                mock.patch.dict(sys.modules, {
                    "notify": None,
                    "notify.channels": None,
                    "notify.config": None,
                    "notify.messages": None,
                }):
            self.assertFalse(notify_board(prev, current))

    def test_build_failure_returns_false(self):
        prev, current = snapshots()
        with mock.patch(
            "starpulse.notify_bridge.build_board_card",
            side_effect=RuntimeError("bad data"),
        ):
            self.assertFalse(notify_board(prev, current))


if __name__ == "__main__":
    unittest.main()
