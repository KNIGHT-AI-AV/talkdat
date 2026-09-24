"""One icon per meaning, in the real renderer (owner's audit, 2026-09-23).

The inventory found, in the web Pill menu and the Settings rail:

* Settings and "App controls" both wore the sliders icon;
* Stats wore History's clock;
* Tools wore the Words speech bubble;
* Live captions and Translate fell back to the generic sliders, because the
  Tools page's rows carry only an action and the icon was looked up by id;
* Scratchpad and Scribe shared one icon.

This drives the REAL shell (pywebview + WebView2, the bundled document) on a
hidden desktop and compares what each row's icon actually paints: its mask
image and mask position, as computed by the browser. Two rows on one page with
the same pair show the same glyph.

Run through scripts/run_tests_offscreen.py.
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

# The bundled document inlines the atlas as a data URI, so a computed
# mask-image runs to hundreds of kilobytes. The report carries a hash of it,
# plus the cell position: all that "same glyph or not" needs, and small enough
# for the shell's one-megabyte message limit (the raw strings exceeded it and
# the report was silently refused).
GLYPH_JS = """const glyph=icon=>{const style=getComputedStyle(icon),image=String(style.maskImage||style.webkitMaskImage);
  let hash=5381;for(let i=0;i<image.length;i++)hash=((hash<<5)+hash+image.charCodeAt(i))|0;
  return (hash>>>0).toString(16)+'|'+(style.maskPosition||style.webkitMaskPosition);};"""

ROWS_JS = "(()=>{" + GLYPH_JS + """return JSON.stringify([...document.querySelectorAll('.menu-row')].map(row=>
  ({label:row.getAttribute('aria-label'),glyph:glyph(row.querySelector('.nav-icon'))})));})()"""

RAIL_JS = "(()=>{" + GLYPH_JS + """return JSON.stringify([...document.querySelectorAll('#navigation button')].map(button=>
  ({label:button.textContent.trim(),glyph:glyph(button.querySelector('.nav-icon'))})));})()"""


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

            def page_rows(title):
                until("document.querySelector('.pill-menu-heading h1')?.textContent===" + json.dumps(title))
                return json.loads(window.evaluate_js(ROWS_JS))

            try:
                until("document.body.classList.contains('connected')")
                if mode == "menu":
                    report = {"home": page_rows("Talk DAT!")}
                    for title in ("Tools", "App controls"):
                        window.evaluate_js(
                            "document.querySelector('.menu-row[aria-label=" + json.dumps(title) + "]').click();true"
                        )
                        report[title] = page_rows(title)
                        window.evaluate_js("document.querySelector('.menu-back').click();true")
                        page_rows("Talk DAT!")
                    api.request("state", {"probe": "menu", "report": report})
                else:
                    until("document.querySelectorAll('#navigation button').length>=7")
                    api.request("state", {"probe": "rail", "report": json.loads(window.evaluate_js(RAIL_JS))})
            except Exception as error:  # noqa: BLE001
                api.request("state", {"probe": mode if mode == "menu" else "rail", "report": {"error": str(error)}})

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


def distinct(rows) -> list[str]:
    """Labels of rows whose glyph another row on the same page also wears."""
    seen: dict[str, list[str]] = {}
    for row in rows:
        seen.setdefault(row["glyph"], []).append(row["label"])
    return sorted(label for labels in seen.values() if len(labels) > 1 for label in labels)


@unittest.skipUnless(sys.platform == "win32", "WebView2 renderer")
class EveryRowHasItsOwnIconTests(unittest.TestCase):
    def test_menu_pages_and_rail_use_one_glyph_per_meaning(self) -> None:
        from knight_flow.ui_scale import enable_dpi_awareness

        enable_dpi_awareness()
        root = tk.Tk()
        root.overrideredirect(True)
        root.geometry("200x48+500+850")
        root.update()
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
        overlay._logical_work_area.return_value = (0, 0, 1920, 1080)
        overlay._foreground_target_window.return_value = 0
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

        shell.menu_controller.handler = handle
        shell.settings_controller.handler = handle
        try:
            self.assertTrue(shell.open_menu(17, 19))
            self.assertTrue(shell.open_settings("home"))
            deadline = time.monotonic() + 80
            while time.monotonic() < deadline and len(reports) < 2:
                root.update()
                try:
                    app._cross_thread_calls.get(timeout=0.02)()
                except queue.Empty:
                    pass
            self.assertEqual(set(reports), {"menu", "rail"}, reports)
            for report in reports.values():
                self.assertNotIn("error", report if isinstance(report, dict) else {}, report)

            menu = reports["menu"]
            for page, page_rows in menu.items():
                with self.subTest(page=page):
                    self.assertTrue(page_rows, f"{page} drew no rows")
                    self.assertEqual(distinct(page_rows), [], f"{page} shows one glyph for two meanings")
            glyph = {row["label"]: row["glyph"] for row in menu["home"]}
            self.assertNotEqual(glyph["App controls"], glyph["Settings"])
            self.assertNotEqual(glyph["Stats"], glyph["History"])
            tools = {row["label"]: row["glyph"] for row in menu["Tools"]}
            for label in ("Live captions", "Translate"):
                self.assertNotEqual(tools[label], glyph["Settings"], f"{label} fell back to the generic sliders")
            self.assertNotEqual(tools["Scratchpad"], tools["Scribe"])

            rail = reports["rail"]
            self.assertGreaterEqual(len(rail), 7)
            self.assertEqual(distinct(rail), [], "the Settings rail shows one glyph for two sections")
            print("icons:", json.dumps({"menu": {page: [row["label"] for row in rows] for page, rows in menu.items()},
                                         "rail": [row["label"] for row in rail]}))
        finally:
            shell.close()
            root.destroy()
            for controller in (shell.menu_controller, shell.settings_controller):
                if controller.process:
                    controller.process.join(4)
                    if controller.process.is_alive():
                        controller.process.terminate()
                        controller.process.join(3)


if __name__ == "__main__":
    unittest.main()
