"""The Pill Panel's pinned switches are complete keyboard controls.

Cloud / Auto / Local and Chill / Executive are drawn above the reorderable
rows. Pointer hit testing has always worked, but keyboard navigation used to
start at Settings and skip all five controls. These tests pin the focus-only
sentinels, their visual focus treatment and dispatch through the same handlers
the pointer already uses.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

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
    overlay._menu_reset_armed = False
    overlay.context_menu_hover = ""
    overlay.config = {"cleanup": {"format_intensity": "executive"}}
    overlay.callbacks = {}
    overlay._draw_context_menu = lambda: None
    return overlay


class ThePinnedSwitchesAreInTheFocusLoopTests(unittest.TestCase):
    def test_the_visual_stack_is_the_keyboard_order(self) -> None:
        overlay = bare_overlay()
        rows = [action for action, _title, _subtitle, _icon in overlay._context_menu_rows()]
        pinned = [focus for focus, _segment in Overlay.MENU_PINNED_FOCUS_STOPS]

        # X-525: two route positions, not three. Cloud and Auto were inert
        # (set_route_mode rejects anything outside ROUTE_MODES) and Auto was
        # also what a person on their own key was shown instead of BYOK.
        self.assertEqual(len(pinned), 4)
        self.assertEqual(
            overlay._context_menu_focus_order(),
            pinned + rows + [Overlay.MENU_RESET_FOCUS],
        )

    def test_down_visits_every_stop_and_wraps(self) -> None:
        overlay = bare_overlay()
        expected = overlay._context_menu_focus_order()
        visited: list[str] = []

        for _stop in expected:
            self.assertEqual(overlay._context_menu_key(SimpleNamespace(keysym="Down")), "break")
            visited.append(overlay.context_menu_hover)

        self.assertEqual(visited, expected)
        overlay._context_menu_key(SimpleNamespace(keysym="Down"))
        self.assertEqual(overlay.context_menu_hover, expected[0])

    def test_up_home_and_end_include_switches_rows_and_footer(self) -> None:
        overlay = bare_overlay()
        order = overlay._context_menu_focus_order()

        overlay.context_menu_hover = order[3]
        overlay._context_menu_key(SimpleNamespace(keysym="Home"))
        self.assertEqual(overlay.context_menu_hover, order[0])
        overlay._context_menu_key(SimpleNamespace(keysym="End"))
        self.assertEqual(overlay.context_menu_hover, Overlay.MENU_RESET_FOCUS)
        overlay._context_menu_key(SimpleNamespace(keysym="Up"))
        self.assertEqual(overlay.context_menu_hover, order[-2])

    def test_focus_tokens_never_become_row_action_ids(self) -> None:
        overlay = bare_overlay()
        rows = {action for action, _title, _subtitle, _icon in overlay._context_menu_rows()}
        for token, _segment in Overlay.MENU_PINNED_FOCUS_STOPS:
            with self.subTest(token=token):
                self.assertTrue(token.startswith("__") and token.endswith("__"))
                self.assertNotIn(token, rows)


class KeyboardActivationUsesThePointerHandlersTests(unittest.TestCase):
    def test_enter_activates_each_route_segment_through_the_existing_handler(self) -> None:
        overlay = bare_overlay()
        called: list[str] = []
        overlay._handle_route_tap = called.append

        for focus, segment in Overlay.MENU_ROUTE_FOCUS_STOPS:
            with self.subTest(segment=segment):
                overlay.context_menu_hover = focus
                self.assertEqual(overlay._context_menu_key(SimpleNamespace(keysym="Return")), "break")

        self.assertEqual(called, ["local", "byok"])

    def test_space_activates_each_finish_segment_through_the_existing_handler(self) -> None:
        overlay = bare_overlay()
        called: list[str] = []
        overlay._handle_finish_tap = called.append

        for focus, segment in Overlay.MENU_FINISH_FOCUS_STOPS:
            with self.subTest(segment=segment):
                overlay.context_menu_hover = focus
                self.assertEqual(overlay._context_menu_key(SimpleNamespace(keysym="space")), "break")

        self.assertEqual(called, ["standard", "executive"])

    def test_a_route_tap_always_sets_the_route_and_never_upsells(self) -> None:
        """X-525 replaces the locked-cloud test, which guarded a branch that
        can no longer be reached.

        It asserted that tapping a LOCKED Cloud opened the premium notice
        instead of setting the route. `cloud_locked` was
        `leg == "talk_dat_cloud"`, and X-480 changed `cloud_leg_provider` to
        answer `byok_provider(config) or "local"`, so the leg can never be that
        again. The branch, the notice and the "Cloud (account required)" label
        were all unreachable.

        The invariant worth keeping is the other half of that sentence: a tap
        on the route switch must do exactly what it says and nothing else."""
        overlay = bare_overlay()
        called: list[object] = []
        overlay.callbacks = {
            "route_state": lambda: {"mode": "local"},
            "set_route": lambda route: called.append(("set", route)),
        }
        overlay._close_context_menu = lambda: called.append("close")

        overlay._handle_route_tap("byok")

        self.assertIn(("set", "byok"), called)
        # 2026-09-22: the premium notice itself is gone, so there is nothing
        # left for a tap to be diverted into.
        self.assertFalse(hasattr(overlay, "show_premium_notice"))


class KeyboardFocusIsNotSelectionTests(unittest.TestCase):
    def test_focus_ring_is_a_dashed_accent_outline(self) -> None:
        overlay = bare_overlay()
        overlay.MENU_ROW_HEIGHT = 40
        rectangles: list[tuple[tuple[object, ...], dict[str, object]]] = []

        class Canvas:
            def create_rectangle(self, *args: object, **kwargs: object) -> None:
                rectangles.append((args, kwargs))

        overlay._draw_context_menu_focus_ring(
            Canvas(), 12, 16, 100, 48, {"accent": "#45e0ca"}
        )

        self.assertEqual(len(rectangles), 1)
        _args, kwargs = rectangles[0]
        self.assertEqual(kwargs["fill"], "")
        self.assertEqual(kwargs["outline"], "#45e0ca")
        self.assertGreaterEqual(int(kwargs["width"]), 2)
        self.assertTrue(kwargs["dash"], "focus must not reuse the solid selection outline")

    def test_both_switches_draw_focus_and_expose_selected_state_in_text(self) -> None:
        source = method_source("_draw_context_menu")
        self.assertEqual(
            source.count("_draw_context_menu_focus_ring("),
            2,
            "both pinned switches need the independent keyboard focus ring",
        )
        self.assertIn('"Locked"', source)
        self.assertGreaterEqual(source.count("Selected"), 2)

    def test_the_existing_reset_footer_also_exposes_keyboard_focus(self) -> None:
        source = method_source("_draw_context_menu")
        self.assertIn("footer_focused", source)
        self.assertIn(
            'fill=palette["text"] if armed or footer_focused else palette["muted"]',
            source,
        )

    def test_focus_drawing_does_not_enter_the_unfold_animation_frame(self) -> None:
        source = method_source("_step_context_menu_unfold")
        self.assertNotIn("_draw_context_menu", source)
        self.assertNotIn("_draw_context_menu_focus_ring", source)
        self.assertNotIn("PhotoImage", source)


if __name__ == "__main__":
    unittest.main()
