from __future__ import annotations

import unittest

from knight_flow.mac_support import IS_MAC
from knight_flow.onboarding import (
    ONBOARDING_STEPS,
    ONBOARDING_VERSION,
    apply_writing_preset,
    hotkey_labels,
    mark_onboarding_complete,
    microphone_quality,
    onboarding_is_complete,
    primary_hotkey,
    selected_writing_preset,
    selected_access_choice,
)


class OnboardingTests(unittest.TestCase):
    def test_current_version_is_required_even_for_an_old_completed_setup(self) -> None:
        config = {"onboarding": {"completed": True, "version": ONBOARDING_VERSION - 1}}
        self.assertFalse(onboarding_is_complete(config))
        config["onboarding"]["version"] = ONBOARDING_VERSION
        self.assertTrue(onboarding_is_complete(config))

    def test_completion_receipt_keeps_only_setup_metadata(self) -> None:
        config = {"onboarding": {"writing_preset": "smart"}}
        mark_onboarding_complete(
            config,
            route="local",
            microphone_tested=True,
            hotkey_rehearsed=True,
            dictation_tested=True,
            access_choice="account",
        )
        receipt = config["onboarding"]
        self.assertTrue(receipt["completed"])
        self.assertEqual(receipt["version"], ONBOARDING_VERSION)
        self.assertEqual(receipt["route"], "local")
        self.assertEqual(receipt["access_choice"], "account")
        self.assertNotIn("api_key", receipt)

    def test_primary_hotkey_uses_config_and_windows_friendly_labels(self) -> None:
        config = {"hotkeys": {"push_to_talk": [["ctrl", "cmd"]]}}
        chord = primary_hotkey(config)
        self.assertEqual(chord, ("ctrl", "cmd"))
        # "cmd" is the Windows key on Windows and Command on a Mac, and these
        # are drawn as keycaps the person is told to hold. Telling a Mac user to
        # press "Win" names a key their keyboard does not have.
        expected = ("Control", "Command") if IS_MAC else ("Ctrl", "Win")
        self.assertEqual(hotkey_labels(chord), expected)

    def test_writing_presets_are_distinct_and_meaning_safe(self) -> None:
        config: dict[str, object] = {}
        self.assertEqual(apply_writing_preset(config, "smart"), "smart")
        self.assertTrue(config["cleanup"]["smart_format"])  # type: ignore[index]
        self.assertTrue(config["cleanup"]["preserve_meaning"])  # type: ignore[index]
        self.assertEqual(selected_writing_preset(config), "smart")

        apply_writing_preset(config, "verbatim")
        self.assertFalse(config["cleanup"]["smart_format"])  # type: ignore[index]
        self.assertFalse(config["cleanup"]["remove_fillers"])  # type: ignore[index]
        self.assertEqual(selected_writing_preset(config), "verbatim")

    def test_microphone_quality_has_clear_nontechnical_bands(self) -> None:
        self.assertEqual(microphone_quality(0.0)[1], "quiet")
        self.assertEqual(microphone_quality(0.05)[1], "good")
        self.assertEqual(microphone_quality(0.7)[1], "hot")

    def test_setup_journey_covers_the_critical_first_run(self) -> None:
        # "menu" sits after the trigger rehearsal on purpose: the Pill has no
        # chrome, so the right-click is the only door to everything beyond
        # dictating, and someone who is never shown it never finds History,
        # Translate, or the off switch.
        # X-23 inserts one macOS-only step. The Windows journey is unchanged,
        # which is the thing worth asserting here -- a [mac] item that shifts
        # the Windows step list is a bug in the port, not a feature.
        # X-149: the intro page leads on both platforms; permissions still
        # sits right after "voice", before anything that trips a gate.
        # X-484: "access" is gone. It asked for a trial, a plan or an
        # account before the first dictation, and the trial was for a
        # managed cloud that no longer exists.
        expected = ("intro", "welcome", "voice", "microphone", "controls", "menu", "superpowers", "writing", "test")
        if IS_MAC:
            # X-496: index 3, not 4. Removing "access" shifted every step
            # left by one, and permissions has to stay immediately after
            # "voice" or it lands after a page that already needed it.
            expected = expected[:3] + ("permissions",) + expected[3:]
        self.assertEqual(tuple(step.id for step in ONBOARDING_STEPS), expected)

    def test_the_permission_step_comes_before_anything_that_needs_one(self) -> None:
        """Placement is the whole point of the item.

        Every page after it trips a gate: the mic meter opens the microphone,
        the trigger rehearsal needs Input Monitoring, and the closing dictation
        test needs Accessibility to deliver a character. Asked afterwards, each
        one looks like a broken feature rather than a permission that is
        missing, and macOS shows its prompt only once.
        """
        ids = [step.id for step in ONBOARDING_STEPS]
        if not IS_MAC:
            self.assertNotIn("permissions", ids)
            return
        position = ids.index("permissions")
        for gated in ("microphone", "controls", "test"):
            self.assertLess(position, ids.index(gated), f"{gated} runs before its permission is asked for")

    def test_access_choice_is_bounded_to_supported_routes(self) -> None:
        self.assertEqual(selected_access_choice({"onboarding": {"access_choice": "restore"}}), "restore")
        self.assertEqual(selected_access_choice({"onboarding": {"access_choice": "invented"}}), "private")


if __name__ == "__main__":
    unittest.main()
