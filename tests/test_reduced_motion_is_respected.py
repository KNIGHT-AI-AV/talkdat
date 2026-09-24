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
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"

# Every method that starts or continues a visible animation. Adding an animator
# without adding it here is the failure this file exists to prevent, so the
# coverage test below fails on any *new* method whose name looks like one.
ANIMATORS = (
    "_set_compact",               # the pill's open/close frame playback
    "_unfold_context_menu",       # the Features accordion
    "_draw_compact_reference_visual",  # the pill's live voice visual
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


if __name__ == "__main__":
    unittest.main()
