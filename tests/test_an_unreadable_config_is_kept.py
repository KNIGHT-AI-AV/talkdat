"""P0-7 (find-more sweep): an unreadable config.json is never replaced by the defaults.

Every custom word, snippet, profile and setting lives in config.json.
`load_config` used to carry on with the defaults when the file would not read
or parse, and the first save of the launch (`stamp_first_run`, the startup
save, any Settings change) then wrote those defaults over it. The same save
minted a new install id and dropped the internal-machine mark.

Now a file that reads but will not parse is moved aside and kept, a file that
cannot be opened at all stays in place and no save touches it this session,
and a sharing violation is retried before either. Each case says so once
(launch_notices, shown on Home and the Pill).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow import config as config_module
from knight_flow import launch_notices
from knight_flow.activation_metrics import stamp_first_run
from knight_flow.config import load_config, save_config

DAMAGED = b'{"dictionary": {"words": ["Mayowa", "Knight"],}, "metrics": {"internal": true},}'


def _sharing_violation() -> OSError:
    error = PermissionError(13, "The process cannot access the file because it is being used by another process")
    return error


class AnUnreadableConfigIsKept(unittest.TestCase):
    def setUp(self) -> None:
        self._old_home = os.environ.get("TALK_DAT_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["TALK_DAT_HOME"] = self._tmp.name
        self.home = Path(self._tmp.name)
        self.path = self.home / "config.json"
        launch_notices.clear()

    def tearDown(self) -> None:
        config_module._UNREADABLE_CONFIG_ROOTS.discard(self.home.resolve())
        launch_notices.clear()
        if self._old_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old_home
        self._tmp.cleanup()

    def _kept(self) -> list[Path]:
        return sorted(self.home.glob("config.json.unreadable-*"))

    def test_a_file_that_will_not_parse_survives_the_first_launch_save(self) -> None:
        self.path.write_bytes(DAMAGED)
        config = load_config(self.home)
        stamp_first_run(config, save_config)
        save_config(config)

        kept = self._kept()
        self.assertEqual(len(kept), 1, "the unreadable file must be kept aside")
        self.assertEqual(kept[0].read_bytes(), DAMAGED, "its bytes must be exactly as they were")
        # This session runs on the defaults, which may now be saved: the
        # original is safe beside them.
        self.assertNotIn("Mayowa", config.get("dictionary", {}).get("words", []))
        self.assertTrue(self.path.is_file())
        notices = launch_notices.pending()
        self.assertEqual([item["key"] for item in notices], ["config"])
        self.assertIn(kept[0].name, notices[0]["text"])

    def test_bad_utf8_does_not_stop_the_launch(self) -> None:
        # The old read let UnicodeDecodeError escape load_config entirely.
        raw = b'{"dictionary": {"words": ["caf\xe9"]}}'
        self.path.write_bytes(raw)
        config = load_config(self.home)
        self.assertIsInstance(config, dict)
        self.assertEqual([p.read_bytes() for p in self._kept()], [raw])

    def test_a_file_that_is_not_an_object_is_kept(self) -> None:
        self.path.write_bytes(b'["Mayowa"]')
        load_config(self.home)
        self.assertEqual([p.read_bytes() for p in self._kept()], [b'["Mayowa"]'])

    def test_a_file_that_cannot_be_opened_is_never_written(self) -> None:
        self.path.write_text(json.dumps({"dictionary": {"words": ["Mayowa"]}}), encoding="utf-8")
        before = self.path.read_bytes()
        real_read_bytes = Path.read_bytes

        def locked(self_path):  # type: ignore[no-untyped-def]
            if Path(self_path).name == "config.json":
                raise _sharing_violation()
            return real_read_bytes(self_path)

        with patch.object(Path, "read_bytes", locked), patch.object(config_module.time, "sleep"):
            config = load_config(self.home)
        stamp_first_run(config, save_config)
        self.assertIs(save_config(config), False)

        self.assertEqual(self.path.read_bytes(), before, "a save must not replace a file it could not read")
        self.assertEqual(self._kept(), [], "a file that could not be opened is not moved")
        self.assertIn("restart", launch_notices.pending()[0]["text"].lower())

    def test_a_passing_sharing_violation_is_retried(self) -> None:
        self.path.write_text(json.dumps({"dictionary": {"words": ["Mayowa"]}}), encoding="utf-8")
        real_read_bytes = Path.read_bytes
        failures = {"left": 2}

        def briefly_locked(self_path):  # type: ignore[no-untyped-def]
            if Path(self_path).name == "config.json" and failures["left"]:
                failures["left"] -= 1
                raise _sharing_violation()
            return real_read_bytes(self_path)

        with patch.object(Path, "read_bytes", briefly_locked), patch.object(config_module.time, "sleep"):
            config = load_config(self.home)
        self.assertEqual(failures["left"], 0, "positive control: the read really failed twice")
        self.assertIn("Mayowa", config["dictionary"]["words"])
        self.assertEqual(launch_notices.pending(), [])
        self.assertIs(save_config(config), True)

    def test_a_good_file_says_nothing_and_keeps_nothing_aside(self) -> None:
        self.path.write_text(json.dumps({"dictionary": {"words": ["Mayowa"]}}), encoding="utf-8")
        config = load_config(self.home)
        self.assertIn("Mayowa", config["dictionary"]["words"])
        self.assertEqual(self._kept(), [])
        self.assertEqual(launch_notices.pending(), [])


class TheSettingsPageSaysASaveWasRefused(unittest.TestCase):
    def test_a_refused_save_is_an_error_on_the_settings_page(self) -> None:
        from knight_flow.web_shell import shell_persistence

        with patch.object(shell_persistence, "save_config", return_value=False):
            with self.assertRaises(ValueError) as caught:
                shell_persistence.save_settings_config({"dictionary": {"words": []}})
        self.assertIn("not saved", str(caught.exception))


class HomeSaysWhatTheLaunchFound(unittest.TestCase):
    def tearDown(self) -> None:
        launch_notices.clear()

    def test_the_greeting_carries_the_notices(self) -> None:
        from knight_flow.config import DEFAULT_CONFIG
        from knight_flow.web_shell.home_workspace import home_greeting

        launch_notices.clear()
        self.assertEqual(home_greeting(json.loads(json.dumps(DEFAULT_CONFIG)))["alerts"], [])
        launch_notices.notice("config", "Your settings could not be read.")
        alerts = home_greeting(json.loads(json.dumps(DEFAULT_CONFIG)))["alerts"]
        self.assertEqual([item["text"] for item in alerts], ["Your settings could not be read."])

    def test_home_js_shows_each_alert_and_opens_recovery(self) -> None:
        # The real home.js in Node, through the harness the Home tests use.
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH")
        harness = Path(__file__).resolve().parent / "js" / "drive_home.mjs"
        if not harness.exists():
            # X-725: the open-source export leaves tests/js out.
            self.skipTest("the Home harness is not in this checkout")
        finished = subprocess.run([node, str(harness)], capture_output=True, timeout=60)
        self.assertEqual(finished.returncode, 0, finished.stderr.decode("utf-8", "replace"))
        report = json.loads(finished.stdout.decode("utf-8"))
        self.assertEqual(report["alerts"], [{"text": "A dictation was interrupted. Your recording is in Recovery.",
                                             "role": "alert"}])
        self.assertEqual(report["alertNavigations"], ["recovery"])


if __name__ == "__main__":
    unittest.main()
