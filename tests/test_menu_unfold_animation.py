"""X-168: the Features accordion animates instead of rebuilding the menu.

Reported as: "Features in Pill menu for example needs fluid animation for
expanding open and closed options .. no lag!"

The lag was not a missing animation. It was a REBUILD. Toggling the row
destroyed the menu's Toplevel and built a new one a few pitches taller, so a
single click paid for a Win32 window teardown, a fresh window, a region carve,
a focus_force -- and, because the plate cache held exactly one entry keyed on
height, a full re-render of the blurred menu plate. Two heights and one slot
guarantees a miss in both directions, forever.

Three things are pinned here, and none of them can be checked by looking at the
menu:

1. The toggle does not close and reopen the window.
2. Both accordion heights stay cached, so the second toggle is free.
3. The frame plan eases out and lands EXACTLY on the target height.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from knight_flow.ui import menu_unfold_frames

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


def _method(name: str) -> ast.FunctionDef:
    tree = ast.parse(OVERLAY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in overlay.py")


def _calls(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            found.add(child.func.attr)
    return found


class TheToggleDoesNotRebuildTheWindowTests(unittest.TestCase):
    def test_the_accordion_branch_neither_closes_nor_opens_the_menu(self) -> None:
        source = ast.get_source_segment(OVERLAY.read_text(encoding="utf-8"), _method("_activate_context_menu_action")) or ""
        branch = source[: source.index('target_hwnd = self.context_menu_target_hwnd')]
        self.assertIn("more_features", branch, "the accordion branch moved; retarget this test")
        self.assertNotIn(
            "_close_context_menu", branch,
            "the accordion destroys the menu window again; that teardown IS the lag",
        )
        self.assertNotIn(
            "_open_context_menu", branch,
            "the accordion builds a second Toplevel again instead of resizing the first",
        )
        # History: X-168's vertical unfold; X-339 slides a SIDE PANEL out
        # instead -- same no-rebuild guarantee, horizontal.
        self.assertIn("_toggle_features_panel", branch)

    def test_a_frame_costs_no_pil_and_no_tk_image(self) -> None:
        """The per-frame step may only move a window, never draw one.

        If `_draw_context_menu` creeps into the frame step, every frame pays for
        a canvas rebuild and, on a cache miss, a blurred plate. X-339's width
        slide inherits the exact same economics as the old height unfold.
        """
        calls = _calls(_method("_step_context_menu_unfold"))
        self.assertIn("_resize_context_menu", calls)
        for forbidden in ("_draw_context_menu", "PhotoImage", "_context_menu_background"):
            self.assertNotIn(forbidden, calls, f"{forbidden} runs once per animation frame")
        slide_calls = _calls(_method("_step_features_slide"))
        self.assertIn("_set_context_menu_width", slide_calls)
        for forbidden in ("_draw_context_menu", "PhotoImage", "_context_menu_background"):
            self.assertNotIn(forbidden, slide_calls, f"{forbidden} runs once per slide frame")

    def test_the_content_is_drawn_once_per_toggle(self) -> None:
        calls = _calls(_method("_toggle_features_panel"))
        self.assertIn("_draw_context_menu", calls, "the panel rows are never drawn")
        self.assertIn("_cancel_context_menu_unfold", calls, "a second toggle mid-animation would run two timers")

    def test_the_panel_slide_is_snappy(self) -> None:
        """His order: "it must animate, and it must be smooth, and it must be
        snappy... super quick." Seven 16ms frames is ~112ms."""
        source = ast.get_source_segment(OVERLAY.read_text(encoding="utf-8"), _method("_toggle_features_panel")) or ""
        self.assertIn("steps=7", source)
        self.assertIn("menu_unfold_frames", source)

    def test_the_wide_plate_is_prewarmed(self) -> None:
        """The first slide's PIL render was the reported heaviness; the wide
        plate must exist before anyone clicks Features."""
        overlay = OVERLAY.read_text(encoding="utf-8")
        self.assertIn("_prewarm_context_menu_plates", overlay)
        prewarm = ast.get_source_segment(overlay, _method("_prewarm_context_menu_plates")) or ""
        self.assertIn("_context_menu_background", prewarm)

    def test_closing_cancels_a_pending_frame(self) -> None:
        """A queued frame resizes a window that close() is about to destroy."""
        self.assertIn("_cancel_context_menu_unfold", _calls(_method("_close_context_menu")))


class TheCachesSurviveAToggleTests(unittest.TestCase):
    def test_the_plate_cache_is_not_a_single_slot(self) -> None:
        source = ast.get_source_segment(OVERLAY.read_text(encoding="utf-8"), _method("_context_menu_background")) or ""
        self.assertIn("cache.get(cache_key)", source, "the plate cache is back to one entry")
        self.assertNotIn(
            "self._context_menu_plate_cache = (cache_key", source,
            "one slot keyed on height guarantees a miss on every accordion toggle",
        )

    def test_the_tk_conversion_is_cached_too(self) -> None:
        source = ast.get_source_segment(OVERLAY.read_text(encoding="utf-8"), _method("_draw_context_menu")) or ""
        self.assertIn("_context_menu_photo_cache", source)
        self.assertIn("photos.get(plate_key)", source)

    def test_both_caches_are_bounded(self) -> None:
        """Unbounded, a per-height cache would hold a plate per display scale."""
        source = OVERLAY.read_text(encoding="utf-8")
        menu_cache_source = "\n".join(
            ast.get_source_segment(source, _method(name)) or ""
            for name in ("_draw_context_menu", "_context_menu_background")
        )
        self.assertEqual(
            menu_cache_source.count("pop(next(iter("), 3,
            "one of the three menu caches has no eviction and will grow without limit",
        )


class TheUnfoldFramePlanTests(unittest.TestCase):
    def test_it_lands_exactly_on_the_target(self) -> None:
        for start, target in ((300, 520), (520, 300), (128, 129), (1000, 140)):
            with self.subTest(start=start, target=target):
                self.assertEqual(menu_unfold_frames(start, target)[-1], target)

    def test_it_eases_out(self) -> None:
        """Big early steps, small late ones: a container settling, not sliding."""
        frames = menu_unfold_frames(300, 520)
        steps = [b - a for a, b in zip((300, *frames), frames)]
        self.assertGreater(steps[0], steps[-1])
        self.assertTrue(all(step > 0 for step in steps), f"non-monotonic unfold: {frames}")

    def test_it_is_monotonic_downward_when_shrinking(self) -> None:
        frames = menu_unfold_frames(520, 300)
        self.assertEqual(list(frames), sorted(frames, reverse=True))

    def test_no_frame_is_wasted_on_an_identical_height(self) -> None:
        self.assertEqual(len(set(menu_unfold_frames(300, 302))), len(menu_unfold_frames(300, 302)))
        self.assertEqual(menu_unfold_frames(400, 400), (400,))

    def test_the_unfold_is_over_fast(self) -> None:
        """A menu nobody waits for. 8 frames at 60fps is about 110ms."""
        from knight_flow.overlay import Overlay

        frames = menu_unfold_frames(300, 520)
        self.assertLessEqual(len(frames) * Overlay.MENU_UNFOLD_FRAME_MS, 160)


class TheMenuHeightHasOneSiteTests(unittest.TestCase):
    def test_open_and_unfold_agree_by_construction(self) -> None:
        """Two independent height formulas would land the accordion off by a few
        pixels, and the plate would show a seam against the window edge."""
        text = OVERLAY.read_text(encoding="utf-8")
        self.assertGreaterEqual(
            text.count("_context_menu_window_height("), 3,
            "the open path or the unfold grew its own height formula",
        )

    def test_the_two_pinned_switches_are_stated_once(self) -> None:
        """`2 * MENU_ROW_PITCH` is the pinned-switch band, and MENU_ROWS_Y0 owns it.

        Writing it a second time inside the height formula is the same defect
        MENU_ROWS_Y0's own docstring was written about: one fact, two
        expressions, which drift the day a third switch gets pinned.
        """
        text = OVERLAY.read_text(encoding="utf-8")
        self.assertEqual(
            text.count("2 * self.MENU_ROW_PITCH"), 1,
            "the pinned-switch band is computed in more than one place again",
        )

    def test_the_height_is_measured_from_the_rows_origin(self) -> None:
        source = ast.get_source_segment(OVERLAY.read_text(encoding="utf-8"), _method("_context_menu_window_height")) or ""
        self.assertIn("top=self.MENU_ROWS_Y0", source)


if __name__ == "__main__":
    unittest.main()
