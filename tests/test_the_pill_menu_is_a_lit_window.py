"""X-684: the Pill menu is a lit window that grows out of the Pill.

Polish audit P0-4, 2026-09-24: the menu is a frameless WinForms window, so it had no
DWM shadow and, on Windows 10, no rounded corners: a flat rectangle with four hard
edges that appeared in one frame. Now:

- Windows 11 rounds its corners in the compositor (DWM, anti-aliased); Windows 10
  cannot (a window region is a one-bit clip), so there it stays square;
- both carry the system drop shadow a menu window class has (CS_DROPSHADOW);
- both are applied before the window is first shown, so the first frame is already
  the final shape (no square flash, no layered window, which WebView2 renders blank);
- the page grows from the side facing the Pill (the pointer is on the Pill when it
  is right-clicked) on the sheet spring: scale .96 and an 8 px rise away from it.
"""
from __future__ import annotations

import json
import re
import unittest
from unittest import mock

from tests import shell_css
from tests.shell_cascade import Element, resolve
from tests.shell_css import ROOT

HOST = ROOT / "knight_flow" / "web_shell" / "shell_host.py"


class FakeChromeApi:
    def __init__(self):
        self.dwm = {}

    def root_handle(self, client):
        return client

    def set_dwm_int(self, hwnd, attribute, value):
        self.dwm[(hwnd, attribute)] = value
        return True

    def get_dwm_int(self, hwnd, attribute):
        return self.dwm.get((hwnd, attribute))


class FakeClassStyle:
    def __init__(self, style=0x0008):
        self.style, self.writes = style, []

    def get(self, hwnd):
        return self.style

    def set(self, hwnd, style):
        self.writes.append((hwnd, style))
        self.style = style
        return True


class TheWindowTests(unittest.TestCase):
    def test_windows_11_rounds_the_corners_and_both_cast_the_menu_shadow(self):
        from knight_flow.web_shell.shell_host import CS_DROPSHADOW, _apply_menu_chrome

        chrome, style = FakeChromeApi(), FakeClassStyle()
        corners, shadow = _apply_menu_chrome(4242, chrome_api=chrome, windows_build=22631, class_style=style)
        self.assertEqual((corners, shadow), ("dwm_hint", True))
        self.assertEqual(chrome.dwm[(4242, 33)], 2, "DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND")
        self.assertEqual(style.writes, [(4242, 0x0008 | CS_DROPSHADOW)], "the class keeps its other styles")

    def test_windows_10_stays_square_and_still_casts_the_shadow(self):
        from knight_flow.web_shell.shell_host import CS_DROPSHADOW, _apply_menu_chrome

        chrome, style = FakeChromeApi(), FakeClassStyle()
        corners, shadow = _apply_menu_chrome(4242, chrome_api=chrome, windows_build=19045, class_style=style)
        self.assertEqual((corners, shadow), ("square", True))
        self.assertEqual(chrome.dwm, {}, "no aliased region, no DWM call on Windows 10")
        self.assertTrue(style.style & CS_DROPSHADOW)

    def test_it_is_applied_before_the_first_show_and_never_layers_the_window(self):
        source = HOST.read_text(encoding="utf-8")
        before_show = source[source.index("def protect_navigation"):source.index("window.events.before_show += protect_navigation")]
        self.assertIn("_apply_menu_chrome", before_show)
        self.assertIn("mode == 'menu'", before_show)
        self.assertNotRegex(source, r"\.Opacity\s*=|AnimateWindow|WS_EX_LAYERED")


class TheEntranceTests(unittest.TestCase):
    def test_the_origin_is_the_pill_side(self):
        from knight_flow.web_shell.shell_host import menu_origin

        menu = [100, 200, 304, 552]
        self.assertEqual(menu_origin(menu, (252, 770)), ("50% 100%", "8px"), "Pill below: grow up from it")
        self.assertEqual(menu_origin(menu, (252, 180)), ("50% 0%", "-8px"), "Pill above: grow down from it")
        self.assertEqual(menu_origin(menu, (60, 900)), ("0% 100%", "8px"), "clamped to the menu's edge")
        with self.assertRaises(ValueError):
            menu_origin([0, 0, 0, 10], (1, 1))

    def test_the_host_sets_the_origin_before_the_page_renders_the_menu(self):
        import sys
        from types import SimpleNamespace

        from knight_flow.web_shell import shell_host

        api = shell_host._RendererApi(mock.Mock(), mode="menu")
        api._window = mock.Mock()
        api._ready.set()
        api._place_menu = lambda bounds: None
        messages = [{"command": "navigate", "page": "menu", "bounds": [100, 200, 304, 552]}]

        def receive(_connection):
            if messages:
                return messages.pop(0)
            raise EOFError

        # On the Mac, _show() defers activation and window.show() to the Cocoa
        # run loop via PyObjCTools.AppHelper.callAfter (test_hidden_mac_menu.py
        # pins the same mechanism); run() never turns here, so the queued call
        # is fired by hand, exactly as that file already does.
        queued = []
        cocoa_modules = {
            "PyObjCTools": SimpleNamespace(AppHelper=SimpleNamespace(callAfter=queued.append)),
            "webview.platforms.cocoa": SimpleNamespace(BrowserView=SimpleNamespace(app=mock.Mock())),
        }
        with mock.patch.object(shell_host, "_receive", receive), \
             mock.patch.object(shell_host, "_cursor_position", lambda: (252, 770)), \
             mock.patch.dict(sys.modules, cocoa_modules):
            api._read()
            for callback in queued:
                callback()
        script = api._window.evaluate_js.call_args_list[0].args[0]
        self.assertLess(script.index("--menu-origin"), script.index("window.TalkDat.navigate"))
        self.assertIn(json.dumps("50% 100%"), script)
        api._window.show.assert_called()

    def test_the_page_grows_from_that_origin_on_the_sheet_spring(self):
        opening = Element("div", ("workspace",), parent=Element("body", ("menu-view", "menu-opening")))
        animation = resolve(opening, "animation") or ""
        self.assertTrue(animation.startswith("menu-grow var(--t-sheet) var(--spring-sheet)"), animation)
        self.assertEqual(resolve(opening, "transform-origin"), "var(--menu-origin)")
        frames = [body for _sheet, stack, selector, body in shell_css.all_rules() if stack == ("@keyframes menu-grow",)]
        self.assertTrue(frames)
        self.assertIn("scale:.96", frames[0].replace(" ", ""))
        self.assertIn("translate:0var(--menu-rise)", frames[0].replace(" ", ""))
        defaults = dict(shell_css.declarations(shell_css.tokens_block()))
        self.assertEqual((defaults.get("--menu-origin"), defaults.get("--menu-rise")), ("50% 100%", "8px"))

    def test_each_open_replays_the_entrance(self):
        script = (ROOT / "knight_flow" / "web_shell" / "shell_assets" / "shell.js").read_text(encoding="utf-8")
        self.assertRegex(script, r'classList\.remove\("menu-opening"\);\s*void document\.body\.offsetWidth;\s*document\.body\.classList\.add\("menu-opening"\)')


if __name__ == "__main__":
    unittest.main()
