from __future__ import annotations

import copy
import unittest

from knight_flow.profiles import active_profile, apply_profile


BASE_CONFIG = {
    "cleanup": {"level": "medium", "tone": ""},
    "deepgram": {"language": "en"},
    "dictation": {"press_enter_command": False},
    "profiles": [
        {"match": "slack", "cleanup_level": "light", "tone": "friendly", "auto_enter": True},
        {"match": "code", "cleanup_level": "none", "language": "de"},
        {"match": "notepad", "cleanup_level": "high", "enabled": False},
    ],
}


class ActiveProfileTests(unittest.TestCase):
    def config(self) -> dict:
        return copy.deepcopy(BASE_CONFIG)

    def test_first_enabled_substring_match_wins(self) -> None:
        self.assertEqual(active_profile(self.config(), "slack.exe")["match"], "slack")
        self.assertEqual(active_profile(self.config(), "Code.exe")["match"], "code")

    def test_matching_ignores_case_on_both_sides(self) -> None:
        self.assertEqual(active_profile(self.config(), "SLACK.EXE")["match"], "slack")

    def test_disabled_profiles_are_skipped(self) -> None:
        self.assertEqual(active_profile(self.config(), "notepad.exe"), {})

    def test_unknown_app_and_empty_inputs_select_nothing(self) -> None:
        self.assertEqual(active_profile(self.config(), "firefox.exe"), {})
        self.assertEqual(active_profile(self.config(), ""), {})
        self.assertEqual(active_profile({}, "slack.exe"), {})
        self.assertEqual(active_profile({"profiles": []}, "slack.exe"), {})

    def test_malformed_profile_entries_do_not_raise(self) -> None:
        config = {"profiles": ["not-a-dict", None, {"match": "slack", "tone": "formal"}]}
        self.assertEqual(active_profile(config, "slack.exe")["tone"], "formal")

    def test_profiles_that_are_not_a_list_are_ignored(self) -> None:
        self.assertEqual(active_profile({"profiles": {"match": "slack"}}, "slack.exe"), {})

    def test_a_blank_match_never_captures_every_app(self) -> None:
        config = {"profiles": [{"match": "   ", "tone": "formal"}]}
        self.assertEqual(active_profile(config, "slack.exe"), {})


class ApplyProfileTests(unittest.TestCase):
    def config(self) -> dict:
        return copy.deepcopy(BASE_CONFIG)

    def test_no_profile_returns_the_config_untouched(self) -> None:
        config = self.config()
        self.assertIs(apply_profile(config, {}), config)

    def test_overrides_land_on_the_expected_sections(self) -> None:
        merged = apply_profile(self.config(), BASE_CONFIG["profiles"][0])
        self.assertEqual(merged["cleanup"]["level"], "light")
        self.assertEqual(merged["cleanup"]["tone"], "friendly")
        self.assertTrue(merged["dictation"]["press_enter_command"])

    def test_language_override_reaches_the_speech_section(self) -> None:
        merged = apply_profile(self.config(), BASE_CONFIG["profiles"][1])
        self.assertEqual(merged["deepgram"]["language"], "de")
        self.assertEqual(merged["cleanup"]["level"], "none")

    def test_the_original_config_is_never_mutated(self) -> None:
        config = self.config()
        apply_profile(config, BASE_CONFIG["profiles"][0])
        self.assertEqual(config["cleanup"]["level"], "medium")
        self.assertEqual(config["cleanup"]["tone"], "")
        self.assertFalse(config["dictation"]["press_enter_command"])

    def test_an_unrecognised_cleanup_level_is_dropped_not_applied(self) -> None:
        merged = apply_profile(self.config(), {"match": "x", "cleanup_level": "extreme"})
        self.assertEqual(merged["cleanup"]["level"], "medium")

    def test_blank_overrides_leave_the_current_value_alone(self) -> None:
        merged = apply_profile(self.config(), {"match": "x", "tone": "  ", "language": ""})
        self.assertEqual(merged["cleanup"]["tone"], "")
        self.assertEqual(merged["deepgram"]["language"], "en")

    def test_auto_enter_false_is_honoured_as_an_explicit_choice(self) -> None:
        config = self.config()
        config["dictation"]["press_enter_command"] = True
        merged = apply_profile(config, {"match": "x", "auto_enter": False})
        self.assertFalse(merged["dictation"]["press_enter_command"])

    def test_missing_sections_are_created_rather_than_crashing(self) -> None:
        merged = apply_profile({}, {"match": "x", "cleanup_level": "high", "language": "fr", "auto_enter": True})
        self.assertEqual(merged["cleanup"]["level"], "high")
        self.assertEqual(merged["deepgram"]["language"], "fr")
        self.assertTrue(merged["dictation"]["press_enter_command"])


if __name__ == "__main__":
    unittest.main()
