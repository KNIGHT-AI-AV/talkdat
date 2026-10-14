"""X-189: every animation must ask whether motion was switched off.

Reduced motion is an accessibility setting, not a preference about taste. For
people with vestibular disorders, movement they did not ask for is a symptom
trigger, so "most animations respect it" is not a meaningful state to be in.

The setting was read as a raw
`self.config.get("ui", {}).get("reduce_motion", False)` chain at each site, which
means an animation whose author did not write that chain silently ignored it. The
menu unfold added in X-168 did exactly that: someone who had switched motion off
still got a 110ms easing accordion every time they opened Features. Nothing
reported it, because an animation that plays when it should not is invisible to
everyone except the person it affects.

`_motion_is_reduced()` is now the single accessor, and this file asserts that
every animation entry point consults it.

WHAT THIS CANNOT PROVE, stated plainly: it checks that each animator ASKS. It
cannot prove the resulting frames are still. That needs a packaged build and a
person watching, and it is listed as a manual acceptance gate rather than
claimed here.
"""

from __future__ import annotations

import ast
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from knight_flow import pill_message

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"

# Every method that starts or continues a visible animation. Adding an animator
# without adding it here is the failure this file exists to prevent, so the
# coverage test below fails on any *new* method whose name looks like one.
ANIMATORS = (
    "_set_compact",               # the pill's open/close frame playback
    "_unfold_context_menu",       # the Features accordion
    "_draw_compact_reference_visual",  # the pill's live voice visual
    "_pip_look",                  # the update light rising out of the Pill (2026-10-09)
    "_pip_moving",                # and how long the Pill's loop stays awake for it
)

# Plays frames but is never the entry point: `_set_compact` gates it and is
# itself in ANIMATORS, so the check belongs at the caller. Listed so the
# coverage test does not have to guess.
GATED_BY_CALLER = frozenset({"_play_open_frames"})


def method_source(name: str) -> str:
    text = OVERLAY.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    return ""


class ThereIsOneAnswerAboutMotionTests(unittest.TestCase):
    def test_the_accessor_exists(self) -> None:
        self.assertNotEqual(method_source("_motion_is_reduced"), "", "_motion_is_reduced is gone")

    def test_the_setting_is_not_read_raw_anywhere(self) -> None:
        """A raw read is how an animator forgets to ask.

        Everything must go through the accessor, so there is exactly one place
        that can be wrong and one place to change if the storage moves.
        """
        text = OVERLAY.read_text(encoding="utf-8")
        tree = ast.parse(text)
        # Two reads are legitimate and are named rather than counted: the
        # accessor itself, and the Settings checkbox, which shows the stored
        # state rather than deciding whether to animate.
        allowed = {"_motion_is_reduced", "open_settings"}
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name in allowed:
                continue
            body = ast.get_source_segment(text, node) or ""
            code = " ".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
            if 'get("reduce_motion"' in code:
                offenders.append(node.name)
        self.assertEqual(
            offenders, [],
            "these read reduce_motion directly instead of calling the accessor, "
            f"which is exactly how an animator forgets to ask: {offenders}",
        )

    def test_the_settings_control_still_writes_it(self) -> None:
        """The accessor is worthless if the checkbox stopped saving."""
        text = OVERLAY.read_text(encoding="utf-8")
        self.assertIn('ui["reduce_motion"] = bool(reduce_motion_var.get())', text)
        self.assertIn("reduce_motion_var,", text, "the control is not dirty-tracked")


class EveryAnimatorAsksTests(unittest.TestCase):
    def test_each_known_animator_consults_the_setting(self) -> None:
        for name in ANIMATORS:
            with self.subTest(animator=name):
                source = method_source(name)
                self.assertNotEqual(source, "", f"{name} not found; retarget this test")
                self.assertIn(
                    "_motion_is_reduced", source,
                    f"{name} animates without asking whether motion was switched off",
                )

    def test_the_menu_unfold_skips_the_frames_rather_than_shortening_them(self) -> None:
        """Reduced motion means no movement, not faster movement."""
        source = method_source("_unfold_context_menu")
        guard = source.index("_motion_is_reduced")
        frames = source.index("menu_unfold_frames")
        self.assertLess(
            guard, frames,
            "the unfold computes a frame plan before checking the setting, so "
            "motion still plays for someone who asked for none",
        )

    def test_no_new_animator_escapes_this_list(self) -> None:
        """A method that plays frames but is not listed is the next silent gap."""
        text = OVERLAY.read_text(encoding="utf-8")
        tree = ast.parse(text)
        suspects = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            body = ast.get_source_segment(text, node) or ""
            plays_frames = "menu_unfold_frames" in body or "_play_open_frames" in body
            if (
                plays_frames
                and node.name not in ANIMATORS
                and node.name not in GATED_BY_CALLER
                and not node.name.startswith("_step")
            ):
                if "_motion_is_reduced" not in body:
                    suspects.append(node.name)
        self.assertEqual(
            suspects, [],
            "these play animation frames without consulting the setting; add the "
            f"check, then add them to ANIMATORS: {suspects}",
        )


class TheUpdateLightTimesItselfTests(unittest.TestCase):
    """The Overlay's own timing of the update light, on a bare Overlay with no window.

    Review R2 (2026-10-10): M14 (the Overlay passing reduced=False) and M16 (a light
    that never stops moving, so the Pill's loop never rests while one is lit) passed
    every module that runs without a window. These do not need one.
    """

    def overlay(self, *, reduced, flag="green", since=None, leaving=None):
        from knight_flow.overlay import Overlay

        overlay = object.__new__(Overlay)
        overlay._update_flag, overlay._pip_since, overlay._pip_leaving = flag, since, leaving
        overlay._motion_is_reduced = lambda: reduced
        return overlay

    @staticmethod
    def now():
        return time.perf_counter() * 1000.0

    def test_the_light_follows_the_motion_setting(self):
        start = pill_message.pip_look(200.0)
        for reduced in (True, False):
            with self.subTest(reduced=reduced):
                now = self.now()
                rising = self.overlay(reduced=reduced, since=now - 60.0)
                self.assertEqual(rising._pip_look(now), ("green", pill_message.pip_look(60.0, reduced=reduced)))
                leaving = self.overlay(reduced=reduced, flag="", leaving=("red", now - 50.0, start))
                self.assertEqual(leaving._pip_look(now),
                                 ("red", pill_message.pip_look(50.0, leaving=True, reduced=reduced, start=start)))
        # The two differ at those moments, so a light that ignored the setting fails above.
        self.assertNotEqual(pill_message.pip_look(60.0, reduced=True), pill_message.pip_look(60.0, reduced=False))
        self.assertNotEqual(pill_message.pip_look(50.0, leaving=True, reduced=True, start=start),
                            pill_message.pip_look(50.0, leaving=True, reduced=False, start=start))

    def test_the_loop_rests_once_the_light_has_settled(self):
        now = self.now()
        self.assertTrue(self.overlay(reduced=False, since=now - 10.0)._pip_moving())
        self.assertFalse(self.overlay(reduced=False, since=now - 5000.0)._pip_moving())
        self.assertTrue(self.overlay(reduced=False, flag="", leaving=("green", now - 10.0, pill_message.PIP_REST))._pip_moving())
        self.assertFalse(self.overlay(reduced=False, flag="", leaving=("green", now - 5000.0, pill_message.PIP_REST))._pip_moving())
        self.assertFalse(self.overlay(reduced=False, flag="")._pip_moving())
        self.assertFalse(self.overlay(reduced=False, since=None)._pip_moving())

    def test_the_light_moves_for_its_whole_rise_and_fall(self):
        # Review T-5 (N32, N35, 2026-10-10): the settled shortcut waits for the longest
        # timing: 200 ms into the 320 ms rise and 150 ms into the 180 ms fall, full motion.
        now = self.now()
        rising = self.overlay(reduced=False, since=now - 200.0)
        self.assertEqual(rising._pip_look(now), ("green", pill_message.pip_look(200.0)))
        self.assertNotEqual(pill_message.pip_look(200.0), pill_message.PIP_REST)
        start = pill_message.pip_look(400.0)
        leaving = self.overlay(reduced=False, flag="", leaving=("red", now - 150.0, start))
        self.assertEqual(leaving._pip_look(now), ("red", pill_message.pip_look(150.0, leaving=True, start=start)))

    def test_reduced_motion_settles_sooner(self):
        # 180 ms in: the 320 ms rise is still moving, the 120 ms fade has finished.
        now = self.now()
        self.assertTrue(self.overlay(reduced=False, since=now - 180.0)._pip_moving())
        self.assertFalse(self.overlay(reduced=True, since=now - 180.0)._pip_moving())

    def test_a_settled_light_does_not_ask_about_motion(self):
        # Review UI-9: the loop's rest check runs on every tick. Once the light has
        # settled the answer cannot depend on the setting, so the setting (and Windows,
        # behind it) is not asked.
        asked = AssertionError("the motion setting was read for a light at rest")
        lit = self.overlay(reduced=False, since=self.now() - 5000.0)
        lit._motion_is_reduced = Mock(side_effect=asked)
        self.assertFalse(lit._pip_moving())
        self.assertEqual(lit._pip_look(), ("green", pill_message.PIP_REST))
        gone = self.overlay(reduced=False, flag="", leaving=("red", self.now() - 5000.0, pill_message.PIP_REST))
        gone._motion_is_reduced = Mock(side_effect=asked)
        self.assertFalse(gone._pip_moving())
        self.assertIsNone(gone._pip_look())


if __name__ == "__main__":
    unittest.main()
