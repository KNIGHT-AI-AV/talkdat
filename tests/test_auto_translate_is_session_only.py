"""X-169: auto-translate can never survive a restart.

He reported it twice. The second report arrived translated into Spanish by the
very feature he was reporting:

    "why does it translate by default? This is a critical problem. It cannot
     translate for users at the moment of initial account creation... It should
     require manual activation for each use, remain easily accessible to turn on
     and off, and be disabled by default."

It was never a wrong default -- DEFAULT_CONFIG ships both translation flags
False, and a fresh install does not translate. What happened is that the
Translate workspace opens with a full-width hero bar reading
"Auto-translate  English -> Spanish  ·  OFF, tap to turn on", and one click on
it wrote `auto_translate_dictation: true` into config.json. Permanently. Nothing
in the dictation flow ever says which language is about to come out, so every
dictation after that click arrived in Spanish, across restarts, indefinitely.

His live config was read to confirm it: `auto_translate_dictation: true`,
`enabled: true`, both persisted.

So the switch stops being a setting and becomes session state. It is enforced at
BOTH disk boundaries, because there are two ways in: the hotkey toggle and the
workspace's own save path, and neither should need to know about this rule.

A sweep of the other five mode toggles -- pause, meeting, scribe, captions,
hands-free -- confirmed they were all already session-only. This was the single
outlier, and the registry is what stops a sixth from appearing.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from knight_flow.config import (
    DEFAULT_CONFIG,
    SESSION_ONLY_SETTINGS,
    load_config,
    save_config,
)


class TheShippedDefaultIsOffTests(unittest.TestCase):
    def test_a_fresh_install_never_translates(self) -> None:
        translation = DEFAULT_CONFIG["translation"]
        self.assertFalse(translation["auto_translate_dictation"])
        self.assertFalse(translation["enabled"])

    def test_auto_translate_is_registered_as_session_only(self) -> None:
        self.assertIn(("translation", "auto_translate_dictation"), SESSION_ONLY_SETTINGS)


class TheFlagCannotSurviveDiskTests(unittest.TestCase):
    def setUp(self) -> None:
        self._home = tempfile.mkdtemp(prefix="talkdat-session-only-")
        self._previous = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = self._home

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._previous

    def _config_file(self) -> Path:
        return Path(self._home) / "config.json"

    def test_an_existing_install_with_it_on_loads_with_it_off(self) -> None:
        """This is the fix for the machine it was reported from."""
        self._config_file().write_text(
            json.dumps({"translation": {"enabled": True, "auto_translate_dictation": True}}),
            encoding="utf-8",
        )
        config = load_config()
        self.assertFalse(
            config["translation"]["auto_translate_dictation"],
            "a stored auto-translate flag still turns dictation translation on at launch",
        )

    def test_manual_translation_stays_available(self) -> None:
        """`enabled` is the manual workspace and Translate-last; only the
        automatic dictation switch is session state. Clearing both would have
        broken the feature instead of the bug."""
        self._config_file().write_text(
            json.dumps({"translation": {"enabled": True, "auto_translate_dictation": True}}),
            encoding="utf-8",
        )
        self.assertTrue(load_config()["translation"]["enabled"])

    def test_saving_never_writes_it(self) -> None:
        config = load_config()
        config["translation"]["auto_translate_dictation"] = True
        save_config(config)
        on_disk = json.loads(self._config_file().read_text(encoding="utf-8"))
        self.assertFalse(
            on_disk["translation"]["auto_translate_dictation"],
            "the workspace save path persists auto-translate again",
        )

    def test_saving_leaves_the_live_session_alone(self) -> None:
        """Turning it on must still work for the rest of THIS session.

        If save_config mutated the caller's dict, saving any unrelated setting
        while auto-translate was on would silently switch it off mid-session.
        """
        config = load_config()
        config["translation"]["auto_translate_dictation"] = True
        save_config(config)
        self.assertTrue(
            config["translation"]["auto_translate_dictation"],
            "saving turned the live session's auto-translate off",
        )

    def test_a_restart_returns_to_off(self) -> None:
        config = load_config()
        config["translation"]["auto_translate_dictation"] = True
        save_config(config)
        self.assertFalse(load_config()["translation"]["auto_translate_dictation"])


class TheDictationGateNeedsBothFlagsTests(unittest.TestCase):
    def test_enabled_alone_does_not_translate_dictation(self) -> None:
        """Both flags are required, so `enabled` on its own is harmless.

        That is what makes it safe to keep `enabled` persistent while the
        automatic switch becomes session state: the manual workspace keeps its
        setting and dictation still arrives as spoken.
        """
        from knight_flow.translation import auto_translation_enabled

        self.assertFalse(auto_translation_enabled({"translation": {"enabled": True}}))
        self.assertFalse(
            auto_translation_enabled({"translation": {"auto_translate_dictation": True}})
        )
        self.assertTrue(
            auto_translation_enabled(
                {"translation": {"enabled": True, "auto_translate_dictation": True}}
            )
        )


if __name__ == "__main__":
    unittest.main()
