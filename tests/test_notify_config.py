"""Tests for notify.config (environment-based, GITHUB_TOKEN style)."""

import os
import unittest
from unittest import mock

from notify.config import load_notify_config

URL = "https://open.feishu.cn/open-apis/bot/v2/hook/from-env"


class LoadNotifyConfigTest(unittest.TestCase):
    def test_reads_webhook_and_secret_from_env(self):
        cfg = load_notify_config(
            env={"FEISHU_WEBHOOK_URL": URL, "FEISHU_SECRET": "s1"}
        )
        self.assertEqual(cfg, {"feishu": {"webhook_url": URL, "secret": "s1"}})

    def test_returns_none_when_unset(self):
        # Missing configuration is not an error: notifications are optional.
        self.assertIsNone(load_notify_config(env={}))

    def test_blank_url_treated_as_unset(self):
        self.assertIsNone(load_notify_config(env={"FEISHU_WEBHOOK_URL": "   "}))

    def test_url_is_stripped(self):
        cfg = load_notify_config(env={"FEISHU_WEBHOOK_URL": f"  {URL}  "})
        self.assertEqual(cfg["feishu"]["webhook_url"], URL)

    def test_secret_defaults_to_empty_string(self):
        cfg = load_notify_config(env={"FEISHU_WEBHOOK_URL": URL})
        self.assertEqual(cfg["feishu"]["secret"], "")

    def test_secret_is_stripped(self):
        cfg = load_notify_config(
            env={"FEISHU_WEBHOOK_URL": URL, "FEISHU_SECRET": "  sec  "}
        )
        self.assertEqual(cfg["feishu"]["secret"], "sec")

    def test_reads_process_env_by_default(self):
        with mock.patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": URL}, clear=True):
            cfg = load_notify_config()
        self.assertEqual(cfg["feishu"]["webhook_url"], URL)


if __name__ == "__main__":
    unittest.main()
