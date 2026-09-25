"""P1-1 (find-more sweep): the paste delay and two animation settings survive a relaunch.

`_migrate_paste_latency_default` and `_migrate_overlay_animation` ran on every
`load_config` with no done-stamp. A paste delay of 30 or 80 ms, the one fix
Settings offers for apps that miss the paste, went back to 10 at every launch,
and `resize_frame_ms` / `resize_steps` did the same. They now run once.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from knight_flow.config import load_config, save_config


class AChosenPasteDelaySurvivesARelaunch(unittest.TestCase):
    def setUp(self) -> None:
        self._old_home = os.environ.get("TALK_DAT_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["TALK_DAT_HOME"] = self._tmp.name
        self.home = Path(self._tmp.name)

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old_home
        self._tmp.cleanup()

    def choose(self, config: dict) -> dict:
        config["dictation"]["clipboard_paste_delay_ms"] = 80
        config["overlay"]["resize_frame_ms"] = 12
        config["overlay"]["resize_steps"] = 60
        save_config(config)
        return config

    def assert_kept(self, config: dict) -> None:
        self.assertEqual(config["dictation"]["clipboard_paste_delay_ms"], 80)
        self.assertEqual((config["overlay"]["resize_frame_ms"], config["overlay"]["resize_steps"]), (12, 60))

    def test_a_value_chosen_in_settings_survives_two_launches(self) -> None:
        self.choose(load_config(self.home))
        self.assert_kept(load_config(self.home))
        self.assert_kept(load_config(self.home))

    def test_a_config_run_since_the_migration_shipped_keeps_its_value(self) -> None:
        # Every launch since 2026-07-09 saved the migrated value, so 80 on
        # disk now is the person's choice even without the new stamp.
        (self.home / "config.json").write_text(json.dumps({
            "dictation": {"clipboard_paste_delay_ms": 80},
            "overlay": {"resize_frame_ms": 12, "resize_steps": 60},
            "updates": {"last_run_at": int(time.time()) - 3600},
        }), encoding="utf-8")
        self.assert_kept(load_config(self.home))

    def test_a_config_from_before_the_migration_moves_once_then_keeps_the_choice(self) -> None:
        (self.home / "config.json").write_text(json.dumps({
            "dictation": {"clipboard_paste_delay_ms": 80},
            "overlay": {"resize_frame_ms": 12, "resize_steps": 60},
        }), encoding="utf-8")
        config = load_config(self.home)
        self.assertEqual(config["dictation"]["clipboard_paste_delay_ms"], 10, "the old default still migrates")
        self.assertEqual((config["overlay"]["resize_frame_ms"], config["overlay"]["resize_steps"]), (8, 22))
        self.choose(config)
        self.assert_kept(load_config(self.home))


if __name__ == "__main__":
    unittest.main()
