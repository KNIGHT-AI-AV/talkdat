"""X-613: the tray's Status opens the web Help page, which shows the status.

The Status window was a square Tk window with a text dump. The Help page now
leads with what Talk DAT! is doing and what holds the microphone, with Refresh
and Panic stop; the Tk window is the fallback when the renderer is unavailable.
"""
import copy
import multiprocessing
import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from knight_flow.config import DEFAULT_CONFIG

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "knight_flow/web_shell/shell_assets"


class TheReportTests(unittest.TestCase):
    def test_the_report_is_the_status_worded_for_a_person(self):
        from knight_flow.web_shell.shell_app import AppShell

        shell = SimpleNamespace(app=SimpleNamespace(status_snapshot=lambda: {
            "session_active": False, "version": "0.4.166-beta", "provider": "local", "last_error": ""}),
            _permissions=AppShell._permissions)
        report = AppShell._status_report(shell)["status_report"]
        self.assertEqual(report["rows"], [["Last error", "None"], ["Provider", "local"],
                                          ["Session active", "No"], ["Version", "0.4.166-beta"]])
        self.assertTrue(report["microphone"][0].startswith("Registered auxiliary microphone tests:"))
        self.assertIn("Panic stop", report["microphone"][-1])

    def test_the_macos_permissions_come_along_on_a_mac_only(self):
        import knight_flow
        from unittest.mock import patch

        from knight_flow.web_shell.shell_app import AppShell

        self.assertIsNone(AppShell._permissions(), "no checklist on Windows or on a build without the Mac helpers")
        page = lambda key, label: SimpleNamespace(key=key, label=label, settings_path=f"Privacy > {label}",
                                                  breaks=f"{label.lower()} stops")
        mac = SimpleNamespace(IS_MAC=True, permission_report=lambda: {"mic": "granted", "ax": "denied"})
        onboarding = SimpleNamespace(permission_is_satisfied=lambda state: state == "granted",
                                     permission_pages=lambda: (page("mic", "Microphone"), page("ax", "Accessibility")),
                                     permissions_outstanding=lambda report: tuple(k for k, v in report.items() if v != "granted"))
        with patch.object(knight_flow, "mac_support", mac, create=True), \
             patch.dict("sys.modules", {"knight_flow.mac_support": mac, "knight_flow.onboarding": onboarding}):
            checklist = AppShell._permissions()
        self.assertEqual(checklist["missing"], 1)
        self.assertEqual([(r["label"], r["granted"], r["breaks"]) for r in checklist["rows"]],
                         [("Microphone", True, ""), ("Accessibility", False, "accessibility stops")])

    def test_open_system_settings_needs_a_mac(self):
        from knight_flow.web_shell.shell_app import AppShell

        with self.assertRaises(ValueError):
            AppShell._open_permissions(SimpleNamespace(overlay=SimpleNamespace()))
        opener = Mock()
        answer = AppShell._open_permissions(SimpleNamespace(overlay=SimpleNamespace(_open_permission_settings_for_first_gap=opener)))
        opener.assert_called_once()
        self.assertIn("System Settings", answer["message"])
        script = (ASSETS / "shell.js").read_text(encoding="utf-8")
        self.assertIn('action("open_permissions"', script)
        self.assertIn('"macOS permissions"', script)

    def test_the_tray_opens_the_help_page_first(self):
        from knight_flow.overlay import Overlay

        overlay = SimpleNamespace(callbacks={"web_settings": Mock(return_value=True)})
        Overlay.open_status.__wrapped__(overlay)
        overlay.callbacks["web_settings"].assert_called_once_with("help")

    def test_the_help_page_draws_it_first(self):
        script = (ASSETS / "shell.js").read_text(encoding="utf-8")
        panel = script.index('if (page.id === "help" && state.data.actions?.includes("status_report")) main.append(renderStatusPanel());')
        self.assertLess(panel, script.index('for (const [label, name] of [["Getting started"'))
        self.assertIn('rpc("action", {name:"status_report"})', script)


def native_status_probe(connection, evidence, html):
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        user = ctypes.windll.user32
        user.GetThreadDesktop.restype = wintypes.HANDLE
        desktop = user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        name = ctypes.create_unicode_buffer(256)
        required = wintypes.DWORD()
        if (not user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(required))
                or not name.value.startswith("talkdat-tests-")):
            evidence.send({"error": "The status proof requires the isolated desktop"})
            return
        surface = name.value
    else:
        surface = "hidden WKWebView"
    import webview
    from knight_flow.web_shell.shell_host import _run_window

    if sys.platform == "darwin":
        from webview.platforms.cocoa import BrowserView
        BrowserView.app.setActivationPolicy_(2)
    create = webview.create_window
    once = threading.Event()

    def create_probe(*args, **kwargs):
        kwargs["focus"] = False
        window = create(*args, **kwargs)

        def probe():
            if once.is_set():
                return
            once.set()

            def until(script):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if window.evaluate_js(script):
                        return
                    time.sleep(.04)
                raise AssertionError("The status panel did not settle: " + script)

            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('help');true")
                until("document.querySelectorAll('#status-panel .status-facts div').length===2")
                window.evaluate_js("[...document.querySelectorAll('#status-panel button')].find(b=>b.textContent==='Panic stop').click();true")
                until("document.querySelector('#status-panel .status-facts dd')?.textContent==='No'")
                evidence.send({"desktop": surface, "text": window.evaluate_js("document.getElementById('status-panel').innerText"),
                               "overflow": window.evaluate_js("document.documentElement.scrollWidth>document.documentElement.clientWidth")})
            except Exception as error:
                evidence.send({"error": str(error), "ui": window.evaluate_js("document.body.innerText.slice(-1500)")})
            finally:
                window.destroy()

        window.events.loaded += probe
        return window

    webview.create_window = create_probe
    _run_window(connection, html, "help", hidden=sys.platform == "darwin")


@unittest.skipUnless(sys.platform in {"win32", "darwin"}, "Native desktop status acceptance")
class NativeStatusTests(unittest.TestCase):
    def test_help_shows_the_status_and_panic_stop_works(self):
        from knight_flow.overlay import Overlay
        from knight_flow.web_shell.shell_backend import ShellBackend
        from knight_flow.web_shell.shell_host import ShellController, bundled_html

        tasks = queue.Queue()
        config = copy.deepcopy(DEFAULT_CONFIG)
        live = {"recording": True}
        panics = []

        def report():
            return {"status_report": {"rows": [["Recording", "Yes" if live["recording"] else "No"], ["Version", "0.4.166-beta"]],
                                      "microphone": ["Registered auxiliary microphone tests: none active."]}}

        def panic():
            panics.append(True)
            live["recording"] = False
            return {"message": "Stopped everything."}

        backend = ShellBackend(config, ASSETS, lambda candidate: None, lambda: None,
                               object.__new__(Overlay)._settings_palette,
                               actions={"status_report": report, "panic": panic})
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=native_status_probe, args=(child, sender, bundled_html(ASSETS)))
        process.start()
        child.close()
        sender.close()
        controller = ShellController(ASSETS, tasks.put, backend.handle, on_failure=lambda: None)
        controller.connection = parent
        listener = threading.Thread(target=controller._listen, args=(parent,), daemon=True)
        listener.start()
        try:
            deadline = time.monotonic() + 65
            while time.monotonic() < deadline and not receiver.poll():
                while not tasks.empty():
                    tasks.get_nowait()()
                time.sleep(.005)
            self.assertTrue(receiver.poll(), "No native status receipt")
            result = receiver.recv()
            self.assertNotIn("error", result, result)
            self.assertEqual(panics, [True])
            self.assertIn("Version", result["text"])
            self.assertIn("none active", result["text"])
            self.assertFalse(result["overflow"])
            print("Native status on Help passed on", result["desktop"])
        finally:
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)
            listener.join(2)
            parent.close()
            receiver.close()


if __name__ == "__main__":
    unittest.main()
