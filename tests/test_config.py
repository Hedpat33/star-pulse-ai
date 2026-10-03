"""Tests for starpulse.config."""

import json
import tempfile
import unittest
from pathlib import Path

from starpulse.config import ConfigError, load_config


def write_config(path: Path, **overrides) -> dict:
    data = {
        "tags": ["ai", "llm"],
        "top_n": 10,
        "min_stars": 5000,
        "output_dir": str(path.parent / "out"),
        "state_dir": str(path.parent / "state"),
        "history_retention_days": 90,
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


class LoadConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.cfg_path = self.tmp / "config.json"

    def test_loads_valid_config(self):
        write_config(self.cfg_path)
        cfg = load_config(self.cfg_path, env={})
        self.assertEqual(cfg.tags, ["ai", "llm"])
        self.assertEqual(cfg.top_n, 10)
        self.assertEqual(cfg.min_stars, 5000)
        self.assertEqual(cfg.output_dir, self.tmp / "out")
        self.assertEqual(cfg.history_retention_days, 90)
        self.assertIsNone(cfg.token)
        self.assertFalse(cfg.verbose)

    def test_missing_file_raises_with_path(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.tmp / "nope.json", env={})
        self.assertIn("nope.json", str(ctx.exception))

    def test_invalid_json_raises(self):
        self.cfg_path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.cfg_path, env={})
        self.assertIn("invalid JSON", str(ctx.exception))

    def test_too_many_tags_rejected(self):
        write_config(self.cfg_path, tags=[f"tag{i}" for i in range(31)])
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.cfg_path, env={})
        self.assertIn("tags", str(ctx.exception))
        self.assertIn("30", str(ctx.exception))

    def test_empty_tags_rejected(self):
        write_config(self.cfg_path, tags=[])
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.cfg_path, env={})
        self.assertIn("tags", str(ctx.exception))

    def test_token_in_file_rejected(self):
        write_config(self.cfg_path, token="ghp_secret")
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.cfg_path, env={})
        self.assertIn("token", str(ctx.exception))

    def test_notify_section_in_file_rejected(self):
        write_config(
            self.cfg_path,
            notify={"feishu": {"webhook_url": "https://example.com/hook"}},
        )
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.cfg_path, env={})
        self.assertIn("FEISHU_WEBHOOK_URL", str(ctx.exception))

    def test_invalid_top_n_rejected(self):
        write_config(self.cfg_path, top_n=0)
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.cfg_path, env={})
        self.assertIn("top_n", str(ctx.exception))

    def test_non_integer_field_rejected(self):
        write_config(self.cfg_path, min_stars="5000")
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.cfg_path, env={})
        self.assertIn("min_stars", str(ctx.exception))

    def test_token_from_env(self):
        write_config(self.cfg_path)
        cfg = load_config(self.cfg_path, env={"GITHUB_TOKEN": "ghp_env"})
        self.assertEqual(cfg.token, "ghp_env")

    def test_cli_token_beats_env(self):
        write_config(self.cfg_path)
        cfg = load_config(
            self.cfg_path, cli_token="ghp_cli", env={"GITHUB_TOKEN": "ghp_env"}
        )
        self.assertEqual(cfg.token, "ghp_cli")

    def test_cli_overrides_top_and_dirs(self):
        write_config(self.cfg_path)
        cfg = load_config(
            self.cfg_path,
            cli_top=5,
            cli_output_dir=str(self.tmp / "other_out"),
            cli_state_dir=str(self.tmp / "other_state"),
            env={},
        )
        self.assertEqual(cfg.top_n, 5)
        self.assertEqual(cfg.output_dir, self.tmp / "other_out")
        self.assertEqual(cfg.state_dir, self.tmp / "other_state")

    def test_cli_verbose_flag(self):
        write_config(self.cfg_path)
        cfg = load_config(self.cfg_path, cli_verbose=True, env={})
        self.assertTrue(cfg.verbose)


if __name__ == "__main__":
    unittest.main()
