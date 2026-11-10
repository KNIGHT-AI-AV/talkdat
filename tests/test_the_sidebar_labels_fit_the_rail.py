"""Every sidebar label reads in full in the sidebar.

X-720 r4 at 0.4.176 (2026-11-06): WinUI's 320 px open NavigationView pane, applied from 1008 px, left
Home 669 px of the default 1120x760 window, so its four tiles fell to two by two
(test_home_tiles_fill_their_rows). The pane is the rail's own 200 px column again. This is the check
that nothing in the rail clips or wraps at that width: each destination's label, the wordmark and the
connection line, measured in the real renderer (WebView2 on a hidden desktop, through
scripts/run_tests_offscreen.py) at the default window.
0.4.177 (merging 0.4.176 H4): the sidebar is the owner's reference sidebar, 256 px open; the same check reads its eight
group rows, every visible page row, the wordmark and the account card.
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
from tests.shell_css import ASSETS

RAIL_JS = """(()=>{const box=node=>{const r=node.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom}};
  const lines=node=>{const range=document.createRange();range.selectNodeContents(node);
    return new Set([...range.getClientRects()].filter(r=>r.width>0).map(r=>Math.round(r.top))).size};
  const fit=node=>({text:node.textContent.trim(),scroll:node.scrollWidth,client:node.clientWidth,lines:lines(node),
    box:box(node),parent:box(node.parentElement)});
  const rail=document.querySelector('.rail');
  return JSON.stringify({rail:Math.round(rail.getBoundingClientRect().width),
    labels:[...document.querySelectorAll('#navigation .nav-label')].filter(node=>node.offsetParent).map(fit),
    groups:[...document.querySelectorAll('#navigation .nav-parent .nav-label')].map(node=>node.textContent.trim()),
    others:[...document.querySelectorAll('.rail .wordmark, .rail .connection, #account-card .account-name')]
      .filter(node=>node.offsetParent).map(fit)});})()"""


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

            try:
                until("document.querySelectorAll('#navigation .nav-parent').length>=8")
                time.sleep(0.5)
                api.request("state", {"probe": "rail", "report": json.loads(window.evaluate_js(RAIL_JS))})
            except Exception as error:  # noqa: BLE001
                api.request("state", {"probe": "rail", "report": {"error": str(error)}})

        window.events.loaded += lambda: threading.Thread(target=probe, daemon=True).start()
        return window

    webview.create_window = instrument
    _run_window(connection, html, page, hidden, mode, bounds)


class ProbeController(ShellController):
    def open(self, page="general", *, hidden=False, bounds=None, side=None):
        if self.process and self.process.is_alive():
            return super().open(page, hidden=hidden, bounds=bounds)
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        self.connection = parent
        self.process = context.Process(
            target=probe_window,
            args=(child, bundled_html(ASSETS), page, hidden, self.mode, bounds),
            daemon=True,
        )
        self.process.start()
        child.close()
        threading.Thread(target=self._listen, args=(parent,), daemon=True).start()


@unittest.skipUnless(sys.platform == "win32", "WebView2 renderer")
class TheSidebarLabelsFitTheRailTests(unittest.TestCase):
    def test_every_label_reads_in_full_on_one_line(self) -> None:
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
            while time.monotonic() < deadline and "rail" not in reports:
                root.update()
                try:
                    app._cross_thread_calls.get(timeout=0.02)()
                except queue.Empty:
                    pass
            report = reports.get("rail")
            self.assertIsNotNone(report, "the page never reported")
            self.assertNotIn("error", report, report)
            self.assertEqual(report["groups"], ["Home", "Dictation", "Shortcuts", "Writing", "Tools", "Appearance", "Help",
                                                "General"], report)
            self.assertGreaterEqual(len(report["labels"]), 8, report)
            for item in report["labels"] + report["others"]:
                with self.subTest(item["text"]):
                    self.assertTrue(item["text"], item)
                    self.assertGreater(item["client"], 0, f"not laid out as a box: {item}")
                    self.assertLessEqual(item["scroll"], item["client"], f"clipped: {item}")
                    self.assertEqual(item["lines"], 1, f"wraps: {item}")
                    self.assertGreaterEqual(item["box"]["left"], item["parent"]["left"] - 0.5, item)
                    self.assertLessEqual(item["box"]["right"], item["parent"]["right"] + 0.5, f"past its row: {item}")
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
