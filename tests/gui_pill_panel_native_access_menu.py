"""Real-Tk proof for the Pill Panel's native accessibility-equivalent menu."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest import mock

from tests import gui_offscreen  # noqa: F401

try:
    import tkinter as tk
except Exception:  # pragma: no cover - tkinter missing entirely
    tk = None  # type: ignore[assignment]


def pump(root: tk.Misc, seconds: float = 0.16) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


@unittest.skipIf(tk is None, "tkinter unavailable")
class RealPillPanelNativeAccessMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        cls._home = tempfile.TemporaryDirectory(prefix="talkdat-pill-native-access-")
        os.environ["TALK_DAT_HOME"] = cls._home.name

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        cls.overlay = Overlay(load_config(), callbacks={})
        pump(cls.overlay.root)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.overlay.root.destroy()
        except Exception:
            pass
        try:
            tk._default_root = None  # type: ignore[attr-defined]
        except Exception:
            pass
        if cls._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = cls._previous_home
        cls._home.cleanup()

    def setUp(self) -> None:
        self.overlay._close_context_menu()
        self.calls: list[tuple[str, object]] = []
        # X-525: the engine answers "local" or "byok"; there is no lock left.
        self.route = {"mode": "local"}

        def set_route(value: str) -> None:
            self.calls.append(("route", value))
            self.route["mode"] = value

        self.overlay.callbacks = {
            "route_state": lambda: dict(self.route),
            "set_route": set_route,
            "save_settings": lambda: self.calls.append(("save", None)),
            "push_menu_order": lambda order: self.calls.append(("push", tuple(order))),
            "ramble": lambda: self.calls.append(("ramble", None)),
        }
        self.overlay.config.setdefault("cleanup", {})["format_intensity"] = "executive"
        self.overlay._menu_show_more = False
        self.overlay._menu_reset_armed = False
        self.overlay._foreground_target_window = lambda: 4321
        self.overlay._open_context_menu(240, 240)
        pump(self.overlay.root)

    def tearDown(self) -> None:
        self.overlay._close_context_menu()
        pump(self.overlay.root, 0.04)

    def test_roles_focus_footer_geometry_and_canvas_tab_contract(self) -> None:
        panel = self.overlay.context_menu_window
        canvas = self.overlay.context_menu_canvas
        footer = self.overlay.context_menu_access_footer
        button = self.overlay.context_menu_access_button
        menu = self.overlay.context_menu_access_menu

        self.assertIsNotNone(panel)
        self.assertIsInstance(canvas, tk.Canvas)
        self.assertIsInstance(footer, tk.Frame)
        self.assertIsInstance(button, tk.Menubutton)
        self.assertIsInstance(menu, tk.Menu)
        assert panel is not None and canvas is not None and footer is not None and button is not None
        self.assertEqual(button.winfo_class(), "Menubutton")
        self.assertEqual(menu.winfo_class(), "Menu")
        self.assertEqual(str(canvas.cget("takefocus")), "0")
        self.assertNotEqual(str(button.cget("takefocus")), "0")
        self.assertIs(button.focus_get(), button)
        self.assertTrue(footer.winfo_ismapped())
        self.assertTrue(button.winfo_ismapped())
        self.assertEqual(
            footer.winfo_y(),
            panel.winfo_height() - self.overlay._context_menu_access_footer_height(),
        )
        self.assertLessEqual(button.winfo_y() + button.winfo_height(), footer.winfo_height())
        self.assertEqual(self.overlay.context_menu_target_hwnd, 4321)

    def test_every_destination_and_both_exclusive_radio_groups_exist(self) -> None:
        menu = self.overlay.context_menu_access_menu
        assert menu is not None
        self.assertEqual(set(self.overlay.context_menu_access_route_entries), {"local", "byok"})
        self.assertEqual(set(self.overlay.context_menu_access_finish_entries), {"standard", "executive"})
        for index in self.overlay.context_menu_access_route_entries.values():
            self.assertEqual(menu.type(index), "radiobutton")
        for index in self.overlay.context_menu_access_finish_entries.values():
            self.assertEqual(menu.type(index), "radiobutton")

        expected_actions = {row[0] for row in self.overlay._context_menu_access_rows()}
        self.assertEqual(set(self.overlay.context_menu_access_action_entries), expected_actions)
        ordered_actions = [
            action
            for action, _index in sorted(
                self.overlay.context_menu_access_action_entries.items(),
                key=lambda item: item[1],
            )
        ]
        self.assertEqual(ordered_actions[-3:], list(self.overlay.MENU_SAFETY_ZONE_ACTIONS))
        for index in self.overlay.context_menu_access_action_entries.values():
            self.assertEqual(menu.type(index), "command")
        self.assertEqual(menu.type(self.overlay.context_menu_access_reset_entry), "command")

    def test_radio_sync_and_single_invocation(self) -> None:
        """X-525: was test_radio_sync_disabled_cloud_and_single_invocation.

        The disabled-Cloud half went with the lock it tested: `cloud_locked`
        asked whether the leg was "talk_dat_cloud", and `cloud_leg_provider`
        has answered `byok_provider() or "local"` since X-480, so it could
        never be true again.

        What survives is the part that has actually broken before: a radio
        must mirror live state IN, and firing it must call the handler exactly
        ONCE. A Tk radiobutton that both traces its variable and carries a
        command will happily do it twice.
        """
        menu = self.overlay.context_menu_access_menu
        route_var = self.overlay.context_menu_access_route_var
        finish_var = self.overlay.context_menu_access_finish_var
        assert menu is not None and route_var is not None and finish_var is not None

        self.route.update(mode="local")
        self.overlay.config["cleanup"]["format_intensity"] = "standard"
        self.overlay._sync_context_menu_access_menu()
        self.assertEqual(route_var.get(), "local")
        self.assertEqual(finish_var.get(), "standard")

        byok_index = self.overlay.context_menu_access_route_entries["byok"]
        self.assertEqual(menu.entrycget(byok_index, "state"), tk.NORMAL)
        menu.invoke(byok_index)
        self.assertEqual(self.calls, [("route", "byok")])
        self.assertEqual(route_var.get(), "byok")

        executive_index = self.overlay.context_menu_access_finish_entries["executive"]
        menu.invoke(executive_index)
        self.assertEqual(self.calls, [("route", "byok"), ("save", None)])
        self.assertEqual(finish_var.get(), "executive")
        self.assertEqual(self.overlay.config["cleanup"]["format_intensity"], "executive")

    def test_action_and_reset_use_existing_handlers_without_duplication(self) -> None:
        menu = self.overlay.context_menu_access_menu
        assert menu is not None
        reset_index = self.overlay.context_menu_access_reset_entry
        assert reset_index is not None
        menu.invoke(reset_index)
        self.assertTrue(self.overlay._menu_reset_armed)
        self.assertEqual(menu.entrycget(reset_index, "label"), "Confirm reset layout")
        menu.invoke(reset_index)
        self.assertFalse(self.overlay._menu_reset_armed)
        self.assertEqual([kind for kind, _value in self.calls], ["save", "push"])

        ramble_index = self.overlay.context_menu_access_action_entries["ramble"]
        menu.invoke(ramble_index)
        self.assertEqual([kind for kind, _value in self.calls].count("ramble"), 1)
        self.assertIsNone(self.overlay.context_menu_window)

    def test_keyboard_posts_the_native_menu(self) -> None:
        menu = self.overlay.context_menu_access_menu
        button = self.overlay.context_menu_access_button
        assert menu is not None
        assert button is not None
        # A real Windows Menu enters an OS-modal loop while posted. Spy on the
        # real widget's posting boundary so the test process never requires a
        # synthetic pointer event to dismiss that loop.
        with mock.patch.object(menu, "post") as post:
            self.assertEqual(self.overlay._post_context_menu_access_menu(), "break")
        post.assert_called_once_with(
            button.winfo_rootx(),
            button.winfo_rooty() + button.winfo_height(),
        )


if __name__ == "__main__":
    unittest.main()
