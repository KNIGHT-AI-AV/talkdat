"""Home's four quick actions never leave one tile alone on a row.

Owner's audit, 2026-09-23 (web-home__normal-day__*): four tiles in an
auto-fit grid of 190px columns came out three across with the fourth alone on
a second row at the default window size. They now sit four across where Home
is wide, two by two where it is narrower, and in one column on the narrowest
window -- always full rows.

Measured in the real renderer (WebView2 on a hidden desktop, through
scripts/run_tests_offscreen.py): the tiles' own boxes, grouped into rows.
"""
from __future__ import annotations

import copy
import ctypes
import json
import multiprocessing
import queue
import sys
import threading
import time
import tkinter as tk
import unittest
from ctypes import wintypes
from unittest.mock import Mock

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.shell_app import AppShell
from knight_flow.web_shell.shell_host import ShellController, _run_window, bundled_html

ROWS_JS = """(()=>{const tops=[...document.querySelectorAll('.home-action')].map(tile=>Math.round(tile.getBoundingClientRect().top));
  const rows={};for(const top of tops)rows[top]=(rows[top]||0)+1;
  return JSON.stringify({width:Math.round(document.querySelector('.home-workspace').getBoundingClientRect().width),
    rows:Object.keys(rows).sort((a,b)=>a-b).map(top=>rows[top])});})()"""


def probe_window(connection, html, page, hidden, mode, bounds):
    user32 = ctypes.windll.user32
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    name = ctypes.create_unicode_buffer(256)
    needed = wintypes.DWORD()
    desktop = user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
    assert user32.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed))
    assert name.value.startswith("talkdat-tests-"), "run through scripts/run_tests_offscreen.py"
    import webview

    create = webview.create_window

    def instrument(*args, **kwargs):
        window = create(*args, **kwargs)

        def probe():
            api = kwargs["js_api"]

            def until(expression, timeout=20):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    value = window.evaluate_js(expression)
                    if value:
                        return value
                    time.sleep(0.05)
                raise AssertionError(expression)

            def measure(width):
                style = "" if width is None else f"{width}px"
                window.evaluate_js(f"document.querySelector('.home-workspace').style.width={json.dumps(style)};true")
                time.sleep(0.3)
                return json.loads(window.evaluate_js(ROWS_JS))

            try:
                until("document.querySelectorAll('.home-action').length===4")
                report = {"default": measure(None), "narrow": measure(560), "narrowest": measure(340)}
                api.request("state", {"probe": "home", "report": report})
            except Exception as error:  # noqa: BLE001
                api.request("state", {"probe": "home", "report": {"error": str(error)}})

        window.events.loaded += lambda: threading.Thread(target=probe, daemon=True).start()
        return window

    webview.create_window = instrument
    _run_window(connection, html, page, hidden, mode, bounds)


class ProbeController(ShellController):
    def open(self, page="general", *, hidden=False, bounds=None):
        if self.process and self.process.is_alive():
            return super().open(page, hidden=hidden, bounds=bounds)
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        self.connection = parent
        self.process = context.Process(
            target=probe_window,
            args=(child, bundled_html(self.assets), page, hidden, self.mode, bounds),
            daemon=True,
        )
        self.process.start()
        child.close()
        threading.Thread(target=self._listen, args=(parent,), daemon=True).start()


@unittest.skipUnless(sys.platform == "win32", "WebView2 renderer")
class HomeTilesFillTheirRowsTests(unittest.TestCase):
    def test_four_across_two_by_two_or_one_column(self) -> None:
        from knight_flow.ui_scale import enable_dpi_awareness

        enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        overlay = Mock()
        overlay.root = root
        overlay._settings_palette = object.__new__(Overlay)._settings_palette
        source = object.__new__(Overlay)
        rows = source._context_menu_default_rows()
        overlay._context_menu_rows.return_value = rows
        overlay._context_menu_default_rows.return_value = rows
        overlay._context_menu_access_rows.return_value = source._context_menu_default_rows(include_feature_actions=True)
        overlay._context_menu_feature_rows.return_value = source._context_menu_feature_rows()
        overlay.MENU_SAFETY_ZONE_ACTIONS = Overlay.MENU_SAFETY_ZONE_ACTIONS
        app = Mock()
        app.config = copy.deepcopy(DEFAULT_CONFIG)
        app.overlay = overlay
        app._cross_thread_calls = queue.Queue()
        shell = AppShell(app, controller_factory=ProbeController)
        reports: dict = {}
        original = shell.backend.handle

        def handle(method, payload):
            if payload.get("probe"):
                reports[payload["probe"]] = payload["report"]
            return original(method, payload)

        shell.settings_controller.handler = handle
        try:
            self.assertTrue(shell.open_settings("home"))
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and "home" not in reports:
                root.update()
                try:
                    app._cross_thread_calls.get(timeout=0.02)()
                except queue.Empty:
                    pass
            report = reports.get("home")
            self.assertIsNotNone(report, "the page never reported")
            self.assertNotIn("error", report, report)
            # The default window (1120x760) gives Home about 780 CSS px.
            self.assertGreaterEqual(report["default"]["width"], 720, report)
            self.assertEqual(report["default"]["rows"], [4], f"not four across: {report['default']}")
            self.assertEqual(report["narrow"]["rows"], [2, 2], f"not two by two: {report['narrow']}")
            self.assertEqual(report["narrowest"]["rows"], [1, 1, 1, 1], f"not one column: {report['narrowest']}")
        finally:
            shell.close()
            root.destroy()
            controller = shell.settings_controller
            if controller.process:
                controller.process.join(4)
                if controller.process.is_alive():
                    controller.process.terminate()
                    controller.process.join(3)


if __name__ == "__main__":
    unittest.main()
