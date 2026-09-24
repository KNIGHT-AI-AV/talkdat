"""Source and pure-logic contracts for the Pill Panel's native access path."""

from __future__ import annotations

import inspect
import unittest

from knight_flow.overlay import Overlay


def bare_overlay() -> Overlay:
    overlay = Overlay.__new__(Overlay)
    overlay._menu_show_more = False
    overlay._menu_reset_armed = False
    overlay.config = {"overlay": {}, "cleanup": {"format_intensity": "executive"}}
    overlay.callbacks = {}
    return overlay


class NativeAccessMenuSourceContracts(unittest.TestCase):
    def test_panel_builds_native_roles_and_removes_canvas_from_tab_order(self) -> None:
        source = inspect.getsource(Overlay._open_context_menu)
        builder = inspect.getsource(Overlay._build_context_menu_access_footer)

        self.assertIn("takefocus=False", source)
        self.assertIn("button = tk.Menubutton(", builder)
        self.assertIn("menu = tk.Menu(", builder)
        self.assertIn("takefocus=True", builder)
        self.assertIn("menu.add_radiobutton(", builder)
        self.assertIn("self._activate_context_menu_action(selected)", builder)
        self.assertIn("self._activate_context_menu_access_reset", builder)

    def test_fixed_access_footer_preserves_the_canvas_outer_keyline(self) -> None:
        source = inspect.getsource(Overlay._place_context_menu_access_footer)

        self.assertIn("outline_inset = 1", source)
        self.assertIn("x=outline_inset", source)
        self.assertIn("int(width) - 2 * outline_inset", source)
        self.assertIn("footer_height - outline_inset", source)

    def test_native_destination_list_contains_every_real_folded_feature(self) -> None:
        overlay = bare_overlay()
        actions = [row[0] for row in overlay._context_menu_access_rows()]

        self.assertEqual(
            set(actions),
            {
                "settings",
                "paste_last",
                "history",
                "ramble",
                "captions",
                "translation",
                "scratchpad",
                "scribe",
                "local_models",
                "stats",
                "check_updates",
                "restart_app",
                "quit_app",
            },
        )
        self.assertNotIn("more_features", actions)
        self.assertEqual(actions[-3:], list(Overlay.MENU_SAFETY_ZONE_ACTIONS))

    def test_native_radio_wrappers_delegate_once_to_existing_handlers(self) -> None:
        overlay = bare_overlay()
        called: list[tuple[str, str]] = []
        overlay._handle_route_tap = lambda value: called.append(("route", value))
        overlay._handle_finish_tap = lambda value: called.append(("finish", value))
        overlay._sync_context_menu_access_menu = lambda: called.append(("sync", ""))

        overlay._activate_context_menu_access_route("local")
        overlay._activate_context_menu_access_finish("standard")

        self.assertEqual(
            called,
            [
                ("route", "local"),
                ("sync", ""),
                ("finish", "standard"),
                ("sync", ""),
            ],
        )


if __name__ == "__main__":
    unittest.main()
