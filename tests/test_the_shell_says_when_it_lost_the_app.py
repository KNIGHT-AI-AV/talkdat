"""The sidebar footer speaks only when the window has lost the app.

Owner's audit, 2026-09-23: the Settings rail ended in "● Connected", always,
explaining nothing -- it was painted on the first answer and never changed
again, so it could not even report the one thing a connection line is for.
Now it is hidden while the window can reach the app, and when the link fails
(no bridge, no reply, a closed pipe) it says so in words and says what to do.

Two halves: the host marks a lost link on the answer (unit), and the real page
shows and hides the message from that mark (WebView2 on a hidden desktop, run
through scripts/run_tests_offscreen.py).
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
from unittest import mock
from unittest.mock import Mock

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell import shell_host
from knight_flow.web_shell.shell_app import AppShell
from knight_flow.web_shell.shell_host import ShellController, _run_window, bundled_html


def trusted_api(connection):
    api = shell_host._RendererApi(connection)
    api._guard_ready = True
    api._window = Mock()
    api._window.get_current_url.return_value = "bundled"
    api._bundled_uri = "bundled"
    return api


class TheHostMarksALostLinkTests(unittest.TestCase):
    def test_a_send_that_cannot_go_out_is_a_lost_link(self) -> None:
        connection = Mock()
        connection.send_bytes.side_effect = OSError("the pipe is being closed")
        with mock.patch.object(shell_host, "trusted_document", return_value=True):
            answer = trusted_api(connection).request("state", {})
        self.assertFalse(answer["ok"])
        self.assertEqual(answer.get("error_code"), shell_host.DISCONNECTED)

    def test_no_reply_is_a_lost_link(self) -> None:
        connection = Mock()
        with mock.patch.object(shell_host, "trusted_document", return_value=True), \
                mock.patch.object(threading.Event, "wait", return_value=False):
            answer = trusted_api(connection).request("state", {})
        self.assertEqual(answer.get("error_code"), shell_host.DISCONNECTED)

    def test_an_oversized_request_is_not_called_a_lost_link(self) -> None:
        """The page's own mistake must not light the lost-link message."""
        connection = Mock()
        with mock.patch.object(shell_host, "trusted_document", return_value=True), \
                mock.patch.object(shell_host, "MAX_MESSAGE", 16):
            answer = trusted_api(connection).request("state", {"note": "x" * 64})
        self.assertFalse(answer["ok"])
        self.assertNotIn("error_code", answer)
        connection.send_bytes.assert_not_called()


FOOTER_JS = """JSON.stringify({hidden:document.getElementById('connection-status').hidden,
  text:document.getElementById('connection-status').innerText,
  connected:document.body.classList.contains('connected')})"""


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
                until("document.body.classList.contains('connected')")
                linked = json.loads(window.evaluate_js(FOOTER_JS))
                # The app stops answering: the host's own lost-link answer.
                window.evaluate_js(
                    "window.__realRequest=window.pywebview.api.request;"
                    "window.pywebview.api.request=async()=>({ok:false,error_code:'disconnected',"
                    "error:'Talk DAT did not respond. Your draft is still here.'});"
                    "window.TalkDat.refresh();true"
                )
                until("!document.getElementById('connection-status').hidden")
                lost = json.loads(window.evaluate_js(FOOTER_JS))
                # An ordinary refusal from a live app is not a lost link.
                window.evaluate_js(
                    "window.pywebview.api.request=async()=>({ok:false,error:'That setting is invalid.'});"
                    "window.TalkDat.refresh();true"
                )
                until("document.getElementById('connection-status').hidden")
                refused = json.loads(window.evaluate_js(FOOTER_JS))
                window.evaluate_js("window.pywebview.api.request=window.__realRequest;window.TalkDat.refresh();true")
                until("document.body.classList.contains('connected')")
                back = json.loads(window.evaluate_js(FOOTER_JS))
                api.request("state", {"probe": "footer", "report": {"linked": linked, "lost": lost,
                                                                      "refused": refused, "back": back}})
            except Exception as error:  # noqa: BLE001
                api.request("state", {"probe": "footer", "report": {"error": str(error)}})

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
class ThePageShowsTheLostLinkTests(unittest.TestCase):
    def test_the_footer_is_silent_while_linked_and_plain_when_the_link_is_lost(self) -> None:
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
            self.assertTrue(shell.open_settings("general"))
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and "footer" not in reports:
                root.update()
                try:
                    app._cross_thread_calls.get(timeout=0.02)()
                except queue.Empty:
                    pass
            report = reports.get("footer")
            self.assertIsNotNone(report, "the page never reported")
            self.assertNotIn("error", report, report)
            self.assertTrue(report["linked"]["hidden"], "the footer still speaks while everything is fine")
            self.assertFalse(report["lost"]["hidden"], "a lost link was not shown")
            lost_text = " ".join(report["lost"]["text"].replace(" ", " ").split())
            self.assertIn("Not connected to Talk DAT!", lost_text)
            self.assertIn("open it again from the Pill", lost_text, "it must say what to do")
            self.assertFalse(report["lost"]["connected"])
            self.assertTrue(report["refused"]["hidden"], "an ordinary refusal was shown as a lost link")
            self.assertTrue(report["back"]["hidden"], "the message outlived the link coming back")
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
