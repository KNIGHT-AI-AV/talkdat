"""X-188: a control that is drawn must be possible to activate.

"Reset layout" sits in the pill menu's footer. It painted correctly, it changed
its own label to "Reset layout, sure? Tap again" when armed, and its two-tap
logic was fully implemented -- inside `_context_menu_click`, a method NOTHING
EVER BOUND. The canvas binds `_context_menu_press` and `_context_menu_release`,
and release only ever looked up a ROW, so a click on the footer fell through and
did nothing.

A visible control that cannot be activated is worse than an absent one. An absent
feature sends you looking for another way; this one reads as the application
ignoring you, and there is nothing to find because nothing failed.

It was also unreachable by keyboard, so it appeared in no interaction sequence at
all. Both are fixed: the footer is part of the real click path, and it is the
last stop in the menu's focus order.

The footer is deliberately NOT a row. It has no action id and is painted below
the rows, so putting it in the row list would make it appear in the menu twice.
A sentinel keeps it in one logical focus sequence while staying out of every list
that means "menu actions" -- including the frozen capability manifest.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from knight_flow.overlay import Overlay

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


def method_source(name: str) -> str:
    text = OVERLAY.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{name} not found")


def bare_overlay() -> Overlay:
    overlay = Overlay.__new__(Overlay)
    overlay._menu_show_more = False
    return overlay


class ThePointerCanActivateResetTests(unittest.TestCase):
    def test_the_release_path_handles_the_footer(self) -> None:
        """The bug: the reset logic lived in a method nothing bound."""
        source = method_source("_context_menu_release")
        self.assertIn("_context_menu_footer_hit", source)
        self.assertIn("_activate_menu_reset", source)

    def test_the_footer_hit_test_is_computed_in_one_place(self) -> None:
        """The painter and the hit test disagreeing is the hover-plate bug."""
        text = OVERLAY.read_text(encoding="utf-8")
        self.assertEqual(
            text.count("rows_bottom = self.MENU_ROWS_Y0 + len(self._context_menu_rows())"), 1,
            "the footer boundary is computed in more than one place again",
        )

    def test_two_taps_are_required(self) -> None:
        """X-70's design: an 'are you sure' without a dialog."""
        source = method_source("_activate_menu_reset")
        self.assertIn("_menu_reset_armed", source)
        self.assertIn("_commit_menu_order", source)
        armed_first = source.index("if getattr(self, \"_menu_reset_armed\", False):")
        commit = source.index("_commit_menu_order")
        self.assertLess(armed_first, commit, "reset commits without being armed first")


class TheKeyboardCanReachResetTests(unittest.TestCase):
    def test_the_footer_is_the_last_focus_stop(self) -> None:
        overlay = bare_overlay()
        order = overlay._context_menu_focus_order()
        self.assertEqual(order[-1], Overlay.MENU_RESET_FOCUS)

    def test_every_row_is_still_in_the_focus_order(self) -> None:
        overlay = bare_overlay()
        rows = [action for action, _t, _s, _i in overlay._context_menu_rows()]
        order = overlay._context_menu_focus_order()
        pinned = [focus for focus, _segment in Overlay.MENU_PINNED_FOCUS_STOPS]
        self.assertEqual(order[len(pinned):-1], rows, "the focus order no longer matches the rows")

    def test_enter_on_the_footer_resets_rather_than_dispatching(self) -> None:
        source = method_source("_context_menu_key")
        self.assertIn("MENU_RESET_FOCUS", source)
        self.assertIn("_activate_menu_reset()", source)

    def test_moving_off_the_footer_disarms_it(self) -> None:
        """Arming is deliberate; arrowing away must not leave a primed reset."""
        source = method_source("_context_menu_key")
        self.assertIn("_menu_reset_armed = False", source)


class TheFooterIsNotARowTests(unittest.TestCase):
    """It must not leak into anything that means 'a menu action'."""

    def test_the_sentinel_is_not_in_the_row_list(self) -> None:
        overlay = bare_overlay()
        rows = [action for action, _t, _s, _i in overlay._context_menu_rows()]
        self.assertNotIn(Overlay.MENU_RESET_FOCUS, rows)

    def test_the_sentinel_is_not_in_the_capability_manifest(self) -> None:
        """The frozen list is the contract that nothing was lost; a focus
        sentinel is not a capability and must not inflate it."""
        import json

        manifest = json.loads((ROOT / "tests" / "capability_manifest.json").read_text(encoding="utf-8"))
        for group, entries in manifest["capabilities"].items():
            with self.subTest(group=group):
                self.assertNotIn(Overlay.MENU_RESET_FOCUS, entries)

    def test_the_sentinel_is_obviously_not_a_real_action_id(self) -> None:
        """Dunder-ish on purpose, so a stray one is recognisable on sight."""
        self.assertTrue(Overlay.MENU_RESET_FOCUS.startswith("__"))
        self.assertTrue(Overlay.MENU_RESET_FOCUS.endswith("__"))


if __name__ == "__main__":
    unittest.main()
