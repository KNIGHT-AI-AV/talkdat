"""Pill Panel lifecycle actions stay in a stable safety zone.

Legacy releases allowed update, restart, and close to be mixed among routine
destinations.  Migration must preserve every valid daily row and its relative
order while restoring lifecycle actions to a predictable tail above the fixed
Reset layout footer.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from knight_flow.overlay import Overlay


def bare_overlay(*, expanded: bool = False) -> Overlay:
    overlay = Overlay.__new__(Overlay)
    overlay._menu_show_more = bool(expanded)
    overlay._menu_reset_armed = False
    overlay.context_menu_hover = ""
    overlay.context_menu_press_state = None
    overlay.context_menu_window = None
    overlay.context_menu_canvas = None
    overlay.MENU_ROW_TOP = 12
    overlay.MENU_ROW_PITCH = 44
    overlay.MENU_ROW_HEIGHT = 40
    overlay.MENU_WIDTH = 320
    overlay.config = {"overlay": {}, "cleanup": {"format_intensity": "executive"}}
    overlay.callbacks = {}
    overlay._draw_context_menu = lambda: None
    return overlay


class SavedOrderMigrationTests(unittest.TestCase):
    def test_legacy_interleaving_keeps_daily_order_and_pins_the_safety_tail(self) -> None:
        overlay = bare_overlay()
        legacy = [
            "history",
            "quit_app",
            "paste_last",
            "restart_app",
            "settings",
            "check_updates",
            "stats",
            "more_features",
        ]
        overlay.config["overlay"]["menu_order"] = legacy

        migrated = [row[0] for row in overlay._context_menu_rows()]

        self.assertEqual(
            migrated[:-3],
            ["history", "paste_last", "settings", "stats", "more_features"],
        )
        self.assertEqual(migrated[-3:], list(Overlay.MENU_SAFETY_ZONE_ACTIONS))
        self.assertEqual(sorted(migrated), sorted(legacy))

    def test_missing_new_daily_destination_is_added_without_losing_old_ones(self) -> None:
        overlay = bare_overlay()
        overlay.config["overlay"]["menu_order"] = [
            "history", "settings", "paste_last", "check_updates", "restart_app", "quit_app"
        ]

        migrated = [row[0] for row in overlay._context_menu_rows()]

        self.assertIn("stats", migrated)
        self.assertIn("more_features", migrated)
        self.assertEqual(len(migrated), len(set(migrated)))
        self.assertEqual(migrated[-3:], list(Overlay.MENU_SAFETY_ZONE_ACTIONS))

    def test_reset_footer_remains_outside_every_saved_order(self) -> None:
        overlay = bare_overlay(expanded=True)
        rows = [row[0] for row in overlay._context_menu_rows()]
        self.assertNotIn(Overlay.MENU_RESET_FOCUS, rows)
        self.assertEqual(overlay._context_menu_focus_order()[-1], Overlay.MENU_RESET_FOCUS)


class DragSafetyTests(unittest.TestCase):
    def test_lifecycle_rows_never_start_a_drag_timer_or_reorder(self) -> None:
        overlay = bare_overlay()
        rows = [row[0] for row in overlay._context_menu_rows()]
        action = "quit_app"
        row_index = rows.index(action)
        y = overlay.MENU_ROWS_Y0 + row_index * overlay.MENU_ROW_PITCH + 4
        overlay._context_menu_press(SimpleNamespace(x=20, y=y))

        self.assertIsNotNone(overlay.context_menu_press_state)
        assert overlay.context_menu_press_state is not None
        self.assertEqual(overlay.context_menu_press_state["action"], action)
        self.assertIsNone(overlay.context_menu_press_state["timer"])
        self.assertFalse(overlay.context_menu_press_state["dragging"])

        overlay._context_menu_begin_drag()
        self.assertFalse(overlay.context_menu_press_state["dragging"])

    def test_daily_drag_cannot_cross_into_the_lifecycle_tail(self) -> None:
        overlay = bare_overlay()
        order = [row[0] for row in overlay._context_menu_rows()]
        action = "settings"
        overlay.context_menu_press_state = {
            "action": action,
            "y": overlay.MENU_ROWS_Y0,
            "timer": None,
            "dragging": True,
            "order": list(order),
        }
        overlay._context_menu_box = (0, 0, 320, 1000)
        # A pointer well below the menu requests the last possible target.
        overlay._context_menu_drag_motion(SimpleNamespace(x=20, y=999))
        reordered = overlay.context_menu_press_state["order"]

        self.assertEqual(reordered[-3:], list(Overlay.MENU_SAFETY_ZONE_ACTIONS))
        self.assertEqual(reordered[-4], action)

    def test_commit_normalizes_untrusted_order_before_persisting(self) -> None:
        overlay = bare_overlay()
        saved: list[list[str]] = []
        overlay.callbacks = {"save_settings": lambda: None, "push_menu_order": saved.append}
        overlay._commit_menu_order(
            ["quit_app", "history", "restart_app", "settings", "check_updates", "paste_last"]
        )

        committed = saved[-1]
        self.assertEqual(committed[-3:], list(Overlay.MENU_SAFETY_ZONE_ACTIONS))
        self.assertEqual(len(committed), len(set(committed)))
        self.assertTrue({"settings", "paste_last", "history", "stats", "more_features"} <= set(committed))


if __name__ == "__main__":
    unittest.main()
