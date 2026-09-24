"""X-611: a release ready to install is offered on Home, not in a Tk window.

The Update window was a square Tk window every existing user met on every
release. Home now carries the whole offer: the version, the readable notes,
the verified install with its progress, Later, Skip this version and View on
GitHub. The install is the app's own verified path; the Tk window is the
fallback when the renderer is unavailable.
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
from knight_flow.web_shell.update_offer import INSTALLING_MESSAGE, UpdateOffer

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "knight_flow/web_shell/shell_assets"

RELEASE = {"current_version": "0.4.164-beta", "latest_version": "0.4.165-beta", "published_at": "2026-09-25T10:00:00Z",
           "release_notes": "## 0.4.165-beta\n\nNames come out right.\n\n- One.\n- Two.", "release_url": "https://example.test/r",
           "has_installer": True, "installer_size": 576 * 1024 * 1024, "has_checksum": True,
           "provenance_verified": True, "source_commit": "abcdef1234567890", "publisher_signature_required": True,
           "predownloaded": False}


def offer_with(**changes):
    notify, opened, counted = Mock(), Mock(), Mock()
    offer = UpdateOffer(notify=notify, open_url=opened, count_dismissal=counted)
    install, skip = Mock(), Mock()
    offer.offer({**RELEASE, **changes}, install, skip)
    return offer, SimpleNamespace(notify=notify, opened=opened, counted=counted, install=install, skip=skip)


class TheOfferTests(unittest.TestCase):
    def test_it_promises_exactly_the_checks_the_window_promised(self):
        offer, _ = offer_with()
        shown = offer.snapshot()
        self.assertEqual((shown["current"], shown["latest"], shown["phase"]), ("0.4.164-beta", "0.4.165-beta", "ready"))
        self.assertIn("receipt, SHA256, and Windows publisher signature", shown["status"])
        self.assertEqual(shown["details"], ["Published 2026-09-25", "576 MB", "Source abcdef123456"])
        self.assertIn("Names come out right.", shown["notes"])

    def test_no_checksum_or_no_installer_blocks_install(self):
        offer, calls = offer_with(has_checksum=False)
        self.assertEqual(offer.snapshot()["phase"], "blocked")
        self.assertIn("blocked for safety", offer.snapshot()["status"])
        with self.assertRaises(ValueError):
            offer.act("install")
        calls.install.assert_not_called()
        offer, _ = offer_with(has_installer=False)
        self.assertIn("View on GitHub", offer.snapshot()["status"])

    def test_install_runs_the_apps_path_and_reports_its_progress(self):
        offer, calls = offer_with()
        self.assertEqual(offer.act("install"), "")
        set_progress, set_status, on_done = calls.install.call_args.args
        self.assertTrue(offer.installing)
        set_progress(288 * 1024 * 1024, 576 * 1024 * 1024)
        self.assertEqual(offer.snapshot()["percent"], 50.0)
        self.assertIn("Downloading update... 50%", offer.snapshot()["status"])
        for action in ("later", "skip", "install"):
            with self.assertRaises(ValueError, msg=action):
                offer.act(action)
        self.assertEqual(offer.act("github"), "")
        calls.opened.assert_called_once_with("https://example.test/r")
        set_status("Rechecking installer integrity before launch...")
        on_done(True, "Update installer started.")
        self.assertEqual(offer.snapshot()["phase"], "started")
        calls.notify.assert_called_with("captured", "Update installer started.")

    def test_a_failed_install_can_be_tried_again(self):
        offer, calls = offer_with()
        offer.act("install")
        calls.install.call_args.args[2](False, "The download was cut off.")
        self.assertEqual(offer.snapshot()["phase"], "failed")
        calls.notify.assert_called_with("error", "The download was cut off.")
        offer.act("install")
        self.assertEqual(calls.install.call_count, 2)

    def test_an_install_that_cannot_start_says_why(self):
        offer, calls = offer_with()
        calls.install.side_effect = OSError("disk full")
        offer.act("install")
        self.assertEqual(offer.snapshot()["phase"], "failed")
        self.assertIn("disk full", offer.snapshot()["status"])

    def test_later_spends_a_strike_skip_records_the_version(self):
        offer, calls = offer_with()
        self.assertIn("remind you later", offer.act("later"))
        calls.counted.assert_called_once_with()
        self.assertIsNone(offer.snapshot())
        offer, calls = offer_with()
        self.assertIn("Skipping v0.4.165-beta", offer.act("skip"))
        calls.skip.assert_called_once_with()
        calls.counted.assert_not_called()
        self.assertIsNone(offer.snapshot())

    def test_a_second_offer_never_replaces_a_running_install(self):
        offer, _ = offer_with()
        offer.act("install")
        self.assertFalse(offer.offer({**RELEASE, "latest_version": "0.4.166-beta"}, Mock(), Mock()))
        offer.withdraw()
        self.assertEqual(offer.snapshot()["latest"], "0.4.165-beta")

    def test_withdraw_never_counts_a_dismissal(self):
        offer, calls = offer_with()
        offer.withdraw()
        self.assertIsNone(offer.snapshot())
        calls.counted.assert_not_called()
        self.assertIn(INSTALLING_MESSAGE[:20], INSTALLING_MESSAGE)


class HomeCarriesItTests(unittest.TestCase):
    def test_home_reports_the_offer_and_routes_its_buttons(self):
        from knight_flow.web_shell.home_workspace import HomeWorkspace

        offer, calls = offer_with()
        updates = SimpleNamespace(offer=offer, check=Mock(), install=Mock())
        home = HomeWorkspace(copy.deepcopy(DEFAULT_CONFIG), lambda job: job(), loader=lambda config: {},
                             greeter=lambda config: {}, updates=updates)
        self.assertEqual(home.handle({"operation": "status"})["offer"]["latest"], "0.4.165-beta")
        answer = home.handle({"operation": "update_later"})
        self.assertIsNone(answer["offer"])
        self.assertIn("remind you later", answer["notice"])
        with self.assertRaises(ValueError):
            home.handle({"operation": "update_skip"})

    def test_the_app_offers_it_on_home_first(self):
        from knight_flow.app import TalkDatApp

        info = SimpleNamespace(latest_version="0.4.165-beta", published_at="", release_notes="", release_url="",
                               installer_url="https://example.test/setup.exe", installer_size=1, installer_sha256="x",
                               receipt_verified=False, receipt_commit="", artifact_signing_enabled=False)
        for web_answer, tk_calls in ((True, 0), (False, 1)):
            app = SimpleNamespace(web_shell=SimpleNamespace(offer_update=Mock(return_value=web_answer)),
                                  overlay=SimpleNamespace(open_update_window=Mock()),
                                  install_update=Mock(), skip_update_version=Mock())
            TalkDatApp.show_update_window(app, info)
            self.assertEqual(app.overlay.open_update_window.call_count, tk_calls)
            data, install, skip = app.web_shell.offer_update.call_args.args
            self.assertEqual(data["latest_version"], "0.4.165-beta")
            install("progress", "status", "done")
            app.install_update.assert_called_once_with(info, None, "progress", "status", "done")
            skip()
            app.skip_update_version.assert_called_once_with("0.4.165-beta")

    def test_the_page_draws_it_polls_it_and_will_not_be_left_mid_install(self):
        script = (ASSETS / "home.js").read_text(encoding="utf-8")
        for needle in ("function renderOffer(o)", '"Try again":"Install now","update_install",true)',
                       '"update_later"', '"update_skip"', '"update_github"',
                       'installing?250', 'lastOffer?.phase!=="installing"'):
            self.assertIn(needle, script)
        self.assertIn(".home-offer{", (ASSETS / "workspaces.css").read_text(encoding="utf-8"))


def native_home_offer_probe(connection, evidence, html):
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
            evidence.send({"error": "The update offer proof requires the isolated desktop"})
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

            def until(script, seconds=15):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if window.evaluate_js(script):
                        return
                    time.sleep(.04)
                raise AssertionError("The update offer did not settle: " + script)

            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('home');true")
                until("!!document.querySelector('.home-offer:not([hidden]) h2')")
                layout = window.evaluate_js(
                    "({overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,"
                    "first:document.querySelector('.home-workspace').children[1]?.className,"
                    "buttons:[...document.querySelectorAll('.home-offer button')].map(b=>b.textContent)})")
                window.evaluate_js("[...document.querySelectorAll('.home-offer button')]"
                                   ".find(b=>b.textContent==='Install now').click();true")
                until("document.querySelector('.home-offer-status')?.textContent.includes('Downloading update')")
                locked = window.evaluate_js("[...document.querySelectorAll('.home-offer button')]"
                                            ".filter(b=>b.textContent!=='View on GitHub').every(b=>b.disabled)")
                until("document.querySelector('.home-offer-status')?.textContent.includes('installer started')")
                evidence.send({"desktop": surface, "layout": layout, "locked_while_installing": locked,
                               "text": window.evaluate_js("document.querySelector('.home-offer').innerText")})
            except Exception as error:
                evidence.send({"error": str(error), "ui": window.evaluate_js("document.body.innerText.slice(-1500)")})
            finally:
                window.destroy()

        window.events.loaded += probe
        return window

    webview.create_window = create_probe
    _run_window(connection, html, "home", hidden=sys.platform == "darwin")


@unittest.skipUnless(sys.platform in {"win32", "darwin"}, "Native desktop update-offer acceptance")
class NativeHomeOfferTests(unittest.TestCase):
    def test_home_shows_the_release_and_runs_the_install_to_its_end(self):
        from knight_flow.overlay import Overlay
        from knight_flow.web_shell.shell_backend import ShellBackend
        from knight_flow.web_shell.shell_host import ShellController, bundled_html
        from knight_flow.web_shell.workspace_adapter import Workspaces

        tasks = queue.Queue()
        config = copy.deepcopy(DEFAULT_CONFIG)
        notified = []
        offer = UpdateOffer(notify=lambda kind, message: notified.append(kind), open_url=lambda url: None,
                            count_dismissal=lambda: None)

        def install(set_progress, set_status, on_done):
            def worker():
                for part in (1, 2, 3):
                    time.sleep(.35)
                    set_progress(part * 100, 300)
                time.sleep(.35)
                set_status("Rechecking installer integrity before launch...")
                time.sleep(.35)
                on_done(True, "Update installer started. Talk DAT! will close and relaunch when install finishes.")
            threading.Thread(target=worker, daemon=True).start()

        offer.offer(RELEASE, install, lambda: None)
        app = SimpleNamespace(config=config, _cross_thread_calls=SimpleNamespace(put=tasks.put),
                              web_shell=SimpleNamespace(update_offer=offer),
                              check_updates=lambda **kwargs: None, install_or_check_update=lambda: None)
        workspaces = Workspaces(app, lambda candidate: None, lambda: False)
        backend = ShellBackend(config, ASSETS, lambda candidate: None, lambda: None,
                               object.__new__(Overlay)._settings_palette, workspaces=workspaces)
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=native_home_offer_probe, args=(child, sender, bundled_html(ASSETS)))
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
            self.assertTrue(receiver.poll(), "No native update-offer receipt")
            result = receiver.recv()
            self.assertNotIn("error", result, result)
            self.assertFalse(result["layout"]["overflow"], result["layout"])
            self.assertEqual(result["layout"]["first"], "home-offer", "the offer comes right after the greeting")
            self.assertEqual(result["layout"]["buttons"], ["Install now", "View on GitHub", "Skip this version", "Later"])
            self.assertTrue(result["locked_while_installing"])
            self.assertIn("0.4.164-beta → 0.4.165-beta", result["text"])
            self.assertEqual(offer.snapshot()["phase"], "started")
            self.assertEqual(notified, ["captured"])
            print("Native update offer on Home passed on", result["desktop"])
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
