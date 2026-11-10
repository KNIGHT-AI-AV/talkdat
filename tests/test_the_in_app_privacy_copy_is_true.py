"""0.4.176 item 8: the in-app copy the privacy audit found false or missing.

IN-APP-COPY-CHANGES.md C2 to C5 in the privacy audit of 2026-10-26 (AUDIT.md section 3.5,
A3, A4, A8, A9), minus what items 4 to 7 already cover:

  C2 (A3): command mode's shortcut said nothing about the web search a command
  with no text selected opens. It says so now, with the Local-only exception
  that is true since the fence of 8e57037.
  C3 (A4): "off keeps no record" was false; recovery recordings are kept with
  History off (config.py forces them on; audio_spool keeps the last five). The
  same sentence sat in the settings tips, so both say the true thing.
  C4 (A8): the Tk setup fallback said the account keeps "only your email and
  which computers are signed in" and that "we never count" what you dictate.
  C5 (A9): the Tk settings fallback said "Nothing is sent to us either way."
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "knight_flow" / "web_shell" / "shell_assets"
HISTORY = ("Keeps a private copy of your dictations on this computer. Off keeps no transcript history; "
           "recent recordings are still kept for recovery, and you can clear them in History.")
SEARCH = ("With no text selected, a command opens a Perplexity web search for what you said, unless "
          "Local-only privacy is on.")


class TheInAppPrivacyCopyIsTrueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fields = json.loads((ASSETS / "settings-fields.json").read_text(encoding="utf-8"))

    def field(self, identifier: str) -> dict:
        return next(field for field in self.fields if field["id"] == identifier)

    def test_command_mode_says_a_command_can_open_a_web_search(self) -> None:
        description = self.field("hotkeys.command_mode")["description"]
        self.assertTrue(description.startswith("Click Record, press the keys together, then release."), description)
        self.assertTrue(description.endswith(" " + SEARCH), description)
        for field in self.fields:
            if field.get("type") == "hotkey" and field["id"] != "hotkeys.command_mode":
                with self.subTest(field=field["id"]):
                    self.assertNotIn("Perplexity", field.get("description", ""))

    def test_history_off_says_recordings_are_still_kept(self) -> None:
        self.assertEqual(self.field("privacy.save_history")["description"], HISTORY)
        tips = json.loads((ROOT / "knight_flow" / "assets" / "settings_tips.json").read_text(encoding="utf-8"))
        tip = next(entry for entry in tips if entry["label"] == "Save local transcript history")
        self.assertEqual(tip["tip"], HISTORY)
        for text in (json.dumps(self.fields), json.dumps(tips)):
            self.assertNotIn("off keeps no record", text)

    def test_the_tk_setup_fallback_says_what_the_account_keeps(self) -> None:
        source = (ROOT / "knight_flow" / "ui" / "onboarding.py").read_text(encoding="utf-8")
        self.assertNotIn("keep only your email", source)
        self.assertNotIn("We never count or keep", source)
        self.assertIn('"keep your email address, the computers you sign in on, and your theme and menu order. "', source)
        self.assertIn('"We never keep what you dictate."', source)

    def test_the_tk_settings_fallback_says_your_dictation_is_not_sent_to_us(self) -> None:
        source = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        self.assertNotIn("Nothing is sent to us either way.", source)
        self.assertIn("a provider you have a key for. Your dictation is not sent to us either way.", source)


if __name__ == "__main__":
    unittest.main()
