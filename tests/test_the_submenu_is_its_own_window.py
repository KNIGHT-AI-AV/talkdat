"""The Pill menu's submenu is a window of its own, as WinUI opens each submenu in its own popup (2026-11-05).

The menu is one WebView2 window, and WebView2 cannot be transparent on Windows, so a submenu drawn inside a
widened menu would leave an opaque block beside the shorter list. The renderer keeps a second frameless window
for the submenu. The menu page keeps every decision (timers, keys, actions); the renderer only places the
submenu where menu_geometry.submenu_bounds says, from the menu window's own rectangle and the row's rectangle in
the page, shows it without taking the focus unless the keyboard opened it, relays the submenu page's pointer and
click events to the menu page, and dismisses the two as one: a deactivate hides both unless the focus went to
the partner window. Nothing here is forwarded to the app.
"""
from __future__ import annotations

import json
import time
import unittest
from unittest import mock

from knight_flow.web_shell import shell_host

PARENT, CHILD = 0x1001, 0x2002


class FakeWindow:
    def __init__(self, hwnd):
        self.native = mock.Mock()
        self.native.Handle.ToInt64.return_value = hwnd
        self.native.Visible = True
        self.scripts: list[str] = []
        self.shown = 0
        self.hidden = 0

    def evaluate_js(self, script):
        self.scripts.append(script)
        return True

    def show(self):
        self.shown += 1

    def hide(self):
        self.hidden += 1

    def get_current_url(self):
        return "about:blank"


ROWS = [{"label": "Local speech", "icon": "dictation", "kind": "radio", "checked": True},
        {"label": "Your key", "icon": "account", "kind": "radio", "checked": False}]
OPEN = {"op": "open", "rows": ROWS, "anchor": {"x": 4, "y": 100, "width": 288, "height": 32},
        "size": {"width": 240, "height": 76}, "scale": 1.5, "keyboard": False}


class Harness(unittest.TestCase):
    def setUp(self):
        self.api = shell_host._RendererApi(connection=None, mode="menu")
        self.api._window = FakeWindow(PARENT)
        self.submenu = FakeWindow(CHILD)
        self.api._submenu_window = self.submenu
        self.placed, self.quiet_shown, self.quiet_hidden = [], [], []
        self.foreground = [0]
        patches = [
            mock.patch.object(self.api, "_trusted", return_value=True),
            mock.patch.object(shell_host._SubmenuApi, "_trusted", return_value=True),
            mock.patch.object(shell_host, "_window_rect", return_value=(100, 200, 532, 900)),
            mock.patch.object(shell_host, "_work_area_of", return_value=(0, 0, 1920, 1040)),
            mock.patch.object(shell_host, "_position_menu_window", side_effect=lambda hwnd, bounds: self.placed.append((hwnd, bounds))),
            mock.patch.object(shell_host, "_show_without_activating", side_effect=self.quiet_shown.append),
            mock.patch.object(shell_host, "_hide_window", side_effect=self.quiet_hidden.append),
            mock.patch.object(shell_host, "_foreground_window", side_effect=lambda: self.foreground[0]),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)


class TheRendererPlacesTheSubmenu(Harness):
    def test_open_places_it_beside_its_row_in_physical_pixels(self):
        answer = self.api.request("submenu", OPEN)
        self.assertTrue(answer["ok"], answer)
        # Row (4, 100, 288 x 32) at 150% from the window's (100, 200): (106, 350, 432 x 48); 240 x 76 is 360 x 114;
        # WinUI's 4 px overlap is 6 px here.
        self.assertEqual(self.placed, [(CHILD, [106 + 432 - 6, 350, 360, 114])])

    def test_open_draws_the_rows_in_the_submenu_page(self):
        self.api.request("submenu", OPEN)
        script = self.submenu.scripts[-1]
        self.assertTrue(script.startswith("window.TalkDat.showSubmenu("), script)
        payload = json.loads(script[len("window.TalkDat.showSubmenu("):script.rindex(")")])
        self.assertEqual(payload["rows"], ROWS)
        self.assertIs(payload["keyboard"], False)

    def test_a_hover_open_leaves_the_focus_in_the_menu(self):
        self.api.request("submenu", OPEN)
        self.assertEqual(self.quiet_shown, [CHILD])
        self.assertEqual(self.submenu.shown, 0)

    def test_a_keyboard_open_moves_the_focus_into_the_submenu(self):
        self.api.request("submenu", {**OPEN, "keyboard": True})
        self.assertEqual(self.submenu.shown, 1)
        self.assertEqual(self.quiet_shown, [])

    def test_close_hides_it_and_can_give_the_focus_back(self):
        self.api.request("submenu", OPEN)
        self.assertTrue(self.api.request("submenu", {"op": "close"})["ok"])
        self.assertEqual(self.quiet_hidden, [CHILD])
        self.api.request("submenu", {"op": "close", "refocus": True})
        self.assertEqual(self.api._window.shown, 1)

    def test_a_malformed_request_shows_nothing(self):
        for bad in ({**OPEN, "rows": "Local"}, {**OPEN, "rows": ROWS * 9}, {**OPEN, "anchor": {"x": 4}},
                    {**OPEN, "scale": "big"}, {**OPEN, "size": {"width": -1, "height": 76}}, {"op": "explode"}):
            with self.subTest(bad=bad):
                self.assertFalse(self.api.request("submenu", bad)["ok"])
        self.assertEqual((self.placed, self.quiet_shown, self.submenu.scripts), ([], [], []))

    def test_the_submenu_request_never_reaches_the_app(self):
        self.assertNotIn("submenu", shell_host.FORWARDED_METHODS)


class TheSubmenuPageReportsToTheMenu(Harness):
    def test_pointer_and_click_events_reach_the_menu_page(self):
        events = shell_host._SubmenuApi(self.api)
        for kind, index in (("enter", 1), ("leave", -1), ("invoke", 0), ("close", -1)):
            events.event(kind, index)
        time.sleep(0.2)
        relayed = [script for script in self.api._window.scripts if script.startswith("window.TalkDat.submenuEvent(")]
        self.assertEqual([json.loads(script[len("window.TalkDat.submenuEvent("):script.rindex(")")]) for script in relayed],
                         [{"kind": "enter", "index": 1}, {"kind": "leave", "index": -1},
                          {"kind": "invoke", "index": 0}, {"kind": "close", "index": -1}])

    def test_anything_else_is_dropped(self):
        events = shell_host._SubmenuApi(self.api)
        events.event("navigate", 0)
        events.event("enter", "1")
        events.event("enter", 99)
        time.sleep(0.2)
        self.assertEqual([s for s in self.api._window.scripts if "submenuEvent" in s], [])

    def test_a_page_that_is_not_ours_reports_nothing(self):
        events = shell_host._SubmenuApi(self.api)
        with mock.patch.object(shell_host._SubmenuApi, "_trusted", return_value=False):
            events.event("invoke", 0)
            time.sleep(0.2)
        self.assertEqual([s for s in self.api._window.scripts if "submenuEvent" in s], [])


class TheTwoDismissAsOne(Harness):
    def test_focus_moving_to_the_submenu_keeps_both(self):
        self.foreground[0] = CHILD
        with mock.patch.object(self.api, "_hide_menu_after_exit") as hide:
            self.api._native_menu_deactivated()
            time.sleep(0.2)
        hide.assert_not_called()

    def test_focus_moving_to_the_menu_from_the_submenu_keeps_both(self):
        self.foreground[0] = PARENT
        with mock.patch.object(self.api, "_hide_menu_after_exit") as hide:
            self.api._submenu_deactivated()
            time.sleep(0.2)
        hide.assert_not_called()

    def test_focus_going_anywhere_else_hides_both(self):
        self.foreground[0] = 0x9999
        self.api._native_menu_deactivated()
        time.sleep(shell_host.MENU_EXIT_SECONDS + 0.3)
        self.assertEqual(self.api._window.hidden, 1)
        self.assertIn(CHILD, self.quiet_hidden)

    def test_hiding_the_menu_hides_the_submenu(self):
        self.api._hide_menu_after_exit()
        time.sleep(shell_host.MENU_EXIT_SECONDS + 0.3)
        self.assertEqual(self.api._window.hidden, 1)
        self.assertIn(CHILD, self.quiet_hidden)


if __name__ == "__main__":
    unittest.main()
