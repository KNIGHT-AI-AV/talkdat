"""X-610: the third-dictation finish choice is drawn by the web shell.

X-137 asks once, at the third real dictation, with the person's own words
finished both ways. It was the one full window a new user met that still drew
in square Tk panes. It is now a block at the top of the web Writing page, and
the Tk window is the fallback. And an upgrade no longer opens the Tk What's New
on top of Home, which already leads with this version's notes.
"""
import copy
import json
import multiprocessing
import os
import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.web_shell.finish_choice import FinishChoice

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "knight_flow/web_shell/shell_assets"


class TheChoiceTests(unittest.TestCase):
    def test_an_offer_is_shown_once_and_saved_through_the_one_save(self):
        choose = Mock(return_value="Executive is your default finish.")
        choice = FinishChoice(choose)
        self.assertIsNone(choice.snapshot())
        choice.offer("Hi Sam, the build passed.", "Hi Sam, the build has passed.")
        self.assertEqual(choice.snapshot(), {"chill": "Hi Sam, the build passed.",
                                             "executive": "Hi Sam, the build has passed."})
        self.assertEqual(choice.act("executive"), "Executive is your default finish.")
        choose.assert_called_once_with("executive")
        self.assertIsNone(choice.snapshot())
        with self.assertRaises(ValueError):
            choice.act("standard")

    def test_later_keeps_the_current_finish_and_unknown_answers_are_refused(self):
        choose = Mock()
        choice = FinishChoice(choose)
        choice.offer("a", "b")
        with self.assertRaises(ValueError):
            choice.act("chill")  # the saved value for Chill is "standard"
        self.assertIn("Kept your current finish", choice.act("later"))
        choose.assert_not_called()

    def test_the_app_saves_the_choice_once_for_both_places(self):
        from knight_flow.app import TalkDatApp

        app = SimpleNamespace(config={"cleanup": {"format_intensity": "standard"}}, save_settings=Mock(),
                              overlay=SimpleNamespace(set_state=Mock()))
        message = TalkDatApp.choose_finish(app, "executive")
        self.assertEqual(app.config["cleanup"], {"format_intensity": "executive", "intensity_default_migrated": True})
        app.save_settings.assert_called_once_with()
        self.assertIn("Executive is your default finish", message)
        TalkDatApp.choose_finish(app, "anything else")
        self.assertEqual(app.config["cleanup"]["format_intensity"], "standard")

    def test_the_tk_window_is_only_the_fallback(self):
        from knight_flow.overlay import Overlay

        overlay = SimpleNamespace(callbacks={"web_finish_choice": Mock(return_value=True)}, force_visible=Mock())
        # The builder under its Tk transaction wrapper (functools.wraps).
        Overlay.open_finish_chooser.__wrapped__(overlay, "chill words", "executive words")
        overlay.callbacks["web_finish_choice"].assert_called_once_with("chill words", "executive words")
        overlay.force_visible.assert_not_called()

    def test_the_page_draws_it_and_answers_with_the_saved_values(self):
        script = (ASSETS / "shell.js").read_text(encoding="utf-8")
        self.assertIn('page.id === "formatting" && state.data?.finish_choice', script)
        self.assertIn('"finish_choice:" + key', script)
        self.assertIn('choice.chill, "standard"', script)
        self.assertIn('choice.executive, "executive"', script)
        self.assertIn(".finish-card{", (ASSETS / "workspaces.css").read_text(encoding="utf-8"))


class TheUpgradeOpensOneWindowTests(unittest.TestCase):
    def app(self, *, legacy=False, show_home=True, onboarding=False):
        from knight_flow.app import TalkDatApp
        from knight_flow.version import APP_VERSION

        app = SimpleNamespace(_previous_version="0.4.1-beta", web_shell=SimpleNamespace(_legacy=legacy),
                              config={"ui": {"show_home_on_start": show_home}},
                              needs_onboarding=lambda: onboarding,
                              overlay=SimpleNamespace(root=SimpleNamespace(after=Mock())))
        app._home_opened_at_launch = lambda: TalkDatApp._home_opened_at_launch(app)
        self.assertNotEqual(APP_VERSION, app._previous_version)
        return app

    def test_home_carries_the_notes_so_no_tk_window_follows(self):
        from knight_flow.app import TalkDatApp

        started = []
        original = threading.Thread.start
        threading.Thread.start = lambda thread: started.append(thread.name)
        try:
            TalkDatApp.maybe_show_whats_new(self.app())
            self.assertEqual(started, [])
            TalkDatApp.maybe_show_whats_new(self.app(legacy=True))
            TalkDatApp.maybe_show_whats_new(self.app(show_home=False))
            self.assertEqual(started, ["TalkDatWhatsNew", "TalkDatWhatsNew"])
        finally:
            threading.Thread.start = original


def native_finish_choice_probe(connection, evidence, html, snapshot_dir):
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
            evidence.send({"error": "The finish choice proof requires the isolated desktop"})
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
                raise AssertionError("The finish choice did not settle: " + script)

            try:
                until("document.body.classList.contains('connected')")
                window.evaluate_js("window.TalkDat.navigate('formatting');true")
                until("!!document.querySelector('#finish-choice .finish-card')")
                layout = window.evaluate_js(
                    "(()=>{const c=[...document.querySelectorAll('.finish-card')].map(e=>e.getBoundingClientRect());"
                    "return {cards:c.length,side_by_side:c.length===2&&Math.abs(c[0].top-c[1].top)<2,"
                    "overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,"
                    "first:document.querySelector('#page').children[1]?.id}})()")
                snapshot = ""
                if snapshot_dir:
                    # A developer's look at the page (TALK_DAT_SNAPSHOT_DIR);
                    # never part of the verdict.
                    try:
                        from PIL import ImageGrab
                        time.sleep(.3)
                        ImageGrab.grab().save(os.path.join(snapshot_dir, "finish-choice.png"))
                        snapshot = "saved"
                    except Exception as error:
                        snapshot = f"not saved: {error}"
                text = window.evaluate_js("document.getElementById('finish-choice').innerText")
                window.evaluate_js("Array.from(document.querySelectorAll('#finish-choice button'))"
                                   ".find(b=>b.textContent==='Use Executive').click();true")
                until("!document.getElementById('finish-choice')")
                evidence.send({"desktop": surface, "layout": layout, "text": text, "snapshot": snapshot})
            except Exception as error:
                evidence.send({"error": str(error), "ui": window.evaluate_js("document.body.innerText.slice(-1500)")})
            finally:
                window.destroy()

        window.events.loaded += probe
        return window

    webview.create_window = create_probe
    _run_window(connection, html, "formatting", hidden=sys.platform == "darwin")


@unittest.skipUnless(sys.platform in {"win32", "darwin"}, "Native desktop finish-choice acceptance")
class NativeFinishChoiceTests(unittest.TestCase):
    def test_the_writing_page_shows_both_finishes_and_saves_the_pick(self):
        from knight_flow.overlay import Overlay
        from knight_flow.web_shell.shell_backend import ShellBackend
        from knight_flow.web_shell.shell_host import ShellController, bundled_html

        tasks = queue.Queue()
        config = copy.deepcopy(DEFAULT_CONFIG)
        chosen = []

        def choose(key):
            chosen.append(key)
            config.setdefault("cleanup", {})["format_intensity"] = key
            return "Executive is your default finish."

        choice = FinishChoice(choose)
        choice.offer("Hey Sam, the build passed. I'll deploy after lunch, gonna check the logs first.",
                     "Hey Sam, the build passed. I'll deploy after lunch; I will check the logs first.")
        backend = ShellBackend(config, ASSETS, lambda candidate: None, lambda: None,
                               object.__new__(Overlay)._settings_palette, finish_choice=choice)
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        receiver, sender = context.Pipe(duplex=False)
        snapshot_dir = os.environ.get("TALK_DAT_SNAPSHOT_DIR", "")
        process = context.Process(target=native_finish_choice_probe,
                                  args=(child, sender, bundled_html(ASSETS), snapshot_dir))
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
            self.assertTrue(receiver.poll(), "No native finish-choice receipt")
            result = receiver.recv()
            self.assertNotIn("error", result, result)
            self.assertEqual(result["layout"]["cards"], 2)
            self.assertFalse(result["layout"]["overflow"], result["layout"])
            self.assertEqual(result["layout"]["first"], "finish-choice", "the choice leads the page")
            self.assertIn("gonna check the logs", result["text"])
            self.assertIn("I will check the logs", result["text"])
            self.assertEqual(chosen, ["executive"])
            self.assertIsNone(choice.snapshot())
            print("Native finish choice on the Writing page passed on", result["desktop"], json.dumps(result["layout"]), result.get("snapshot") or "")
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
