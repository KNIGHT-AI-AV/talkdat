"""The Tk fallbacks for the usage-counts switch (owner decision 2026-09-23).

When the web shell cannot open, Settings and first-run setup fall back to Tk.
Those carry the same words, only in an official build: Settings has one
checkbox, saving privacy.share_usage_counts. 0.4.176 (TEAM KNIGHT, consent
before capture): the checkbox reads off until the person says yes, and setup
asks with two answers, Share and Don't share, neither chosen until the person
picks one; either is saved as their answer (privacy.usage_counts_asked). Real
windows, on the isolated test desktop
(scripts/run_tests_offscreen.py tests.test_usage_counts_tk).
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

if sys.platform == "win32":
    from tests import gui_offscreen  # noqa: F401  (never on a human's screen)

try:
    import tkinter as tk
except Exception:  # pragma: no cover - headless CI without Tk
    tk = None  # type: ignore[assignment]

from knight_flow import official_build
from tests.tk_support import probe_error as _ROOT_ERROR


@contextlib.contextmanager
def build(official: bool):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("TALKDAT_")}
    clean["TALK_DAT_HOME"] = os.environ["TALK_DAT_HOME"]
    with mock.patch.object(official_build, "OFFICIAL", official), mock.patch.dict(os.environ, clean, clear=True):
        yield


def pump(root, seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def usage_radios(window) -> list:
    found = []
    for widget in descendants(window):
        if widget.winfo_class() in {"TRadiobutton", "Radiobutton"}:
            with contextlib.suppress(tk.TclError):
                if str(widget.cget("text")) in {official_build.USAGE_COUNTS_SHARE, official_build.USAGE_COUNTS_DECLINE}:
                    found.append(widget)
    return found


def usage_checks(window) -> list:
    found = []
    for widget in descendants(window):
        if widget.winfo_class() in {"TCheckbutton", "Checkbutton"}:
            with contextlib.suppress(tk.TclError):
                if str(widget.cget("text")) == official_build.USAGE_COUNTS_LINE:
                    found.append(widget)
    return found


@unittest.skipIf(tk is None, "tkinter unavailable")
@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class TkFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        with contextlib.suppress(Exception):
            existing = getattr(tk, "_default_root", None)
            if existing is not None and not existing.winfo_exists():
                tk._default_root = None  # type: ignore[attr-defined]
        self._previous_home = os.environ.get("TALK_DAT_HOME")
        self._home = tempfile.mkdtemp(prefix="talkdat-usage-")
        os.environ["TALK_DAT_HOME"] = self._home

    def tearDown(self) -> None:
        # Only a dead root is forgotten: on macOS the live one is the shared
        # root every later window test is handed (tests/tk_support).
        with contextlib.suppress(Exception):
            existing = getattr(tk, "_default_root", None)
            if existing is not None and not existing.winfo_exists():
                tk._default_root = None  # type: ignore[attr-defined]
        if self._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._previous_home

    def settings_window(self, metrics=None):
        from knight_flow.config import load_config, save_config
        from knight_flow.overlay import Overlay
        from tests.tk_support import acquire_root, release_root

        config = load_config()
        if metrics is not None:
            config["metrics"] = metrics
        # macOS: one Tk root per process, ever (tests/tk_support). A fresh Tk
        # here is not the default root while the shared one lives, so the
        # Pill's images landed in the wrong interpreter.
        overlay = Overlay(
            config, callbacks={"save_settings": lambda: save_config(overlay.config)}, root=acquire_root()
        )
        self.addCleanup(release_root, overlay._tk_root)
        pump(overlay.root, 0.4)
        overlay.open_settings()
        pump(overlay.root, 1.2)
        window = overlay.utility_windows.get("settings")
        self.assertIsNotNone(window, "the Tk Settings window did not open")
        return overlay, window

    def test_tk_settings_shows_one_switch_in_an_official_build_and_saves_it(self) -> None:
        with build(True):
            overlay, window = self.settings_window()
            checks = usage_checks(window)
            self.assertEqual(len(checks), 1)
            variable = str(checks[0].cget("variable"))
            self.assertFalse(overlay.root.getboolean(overlay.root.getvar(variable)), "off until a yes")
            checks[0].invoke()
            save = next(w for w in descendants(window) if w.winfo_class() == "TButton" and str(w.cget("text")) == "Save")
            save.invoke()
            pump(overlay.root, 0.3)
            self.assertIs(overlay.config["privacy"]["share_usage_counts"], True)
            self.assertIs(overlay.config["privacy"]["usage_counts_asked"], True, "turning it on is the answer")
            self.assertIs(overlay.config["privacy"]["local_only"], True)

    def test_tk_settings_saving_something_else_is_not_an_answer(self) -> None:
        with build(True):
            overlay, window = self.settings_window()
            save = next(w for w in descendants(window) if w.winfo_class() == "TButton" and str(w.cget("text")) == "Save")
            save.invoke()
            pump(overlay.root, 0.3)
            self.assertIs(overlay.config["privacy"]["usage_counts_asked"], False)
            self.assertIs(overlay.config["privacy"]["share_usage_counts"], False)

    INSTALL_ID = "ab" * 16  # obviously fake: an ID-shaped literal reads as a key to the export's secrets gate

    def install_id_widgets(self, window) -> tuple[list, list]:
        shown = [w for w in descendants(window) if w.winfo_class() in {"TEntry", "Entry"}
                 and self.INSTALL_ID in str(w.get())]
        lines = [w for w in descendants(window) if w.winfo_class() in {"TLabel", "Label"}
                 and str(w.cget("text")) == official_build.USAGE_COUNTS_ID_DETAIL]
        return shown, lines

    def test_tk_settings_shows_the_install_id_read_only_in_an_official_build(self) -> None:
        # 0.4.176 item 7: the ID a person sends to have its records deleted.
        with build(True):
            _overlay, window = self.settings_window({"install_id": self.INSTALL_ID})
            shown, lines = self.install_id_widgets(window)
            self.assertEqual(len(shown), 1)
            self.assertEqual(str(shown[0].cget("state")), "readonly")
            self.assertEqual(len(lines), 1)

    def test_tk_settings_shows_no_install_id_in_a_source_build(self) -> None:
        with build(False):
            _overlay, window = self.settings_window({"install_id": self.INSTALL_ID})
            self.assertEqual(self.install_id_widgets(window), ([], []))

    def test_tk_settings_shows_no_switch_in_a_source_build(self) -> None:
        with build(False):
            _overlay, window = self.settings_window()
            self.assertEqual(usage_checks(window), [])

    @unittest.skipUnless(sys.platform == "win32", "the setup wizard fallback is exercised on Windows")
    def test_the_tk_setup_wizard_asks_with_two_answers_and_saves_the_one_picked(self) -> None:
        from knight_flow import main_thread
        from knight_flow.app import TalkDatApp
        from knight_flow.config import config_path
        from knight_flow.onboarding import ONBOARDING_STEPS
        from knight_flow.ui import onboarding as ui
        from scripts.capture_onboarding_gallery import CaptureHost

        for official, pick in ((False, None), (True, official_build.USAGE_COUNTS_DECLINE), (True, None)):
            config_path().unlink(missing_ok=True)
            with self.subTest(official=official, pick=pick), build(official), \
                    mock.patch.object(ui, "list_input_devices", return_value=["Synthetic microphone"]), \
                    mock.patch("knight_flow.net_fence.set_local_only"):
                root = tk.Tk()
                root.withdraw()
                main_thread.bind(root)
                try:
                    host = CaptureHost(root, "Flow Dark")
                    app = object.__new__(TalkDatApp)
                    app.config = host.config
                    app.overlay = host
                    app.save_settings = mock.Mock()
                    host.refresh_route_paint = mock.Mock()
                    host.callbacks["onboarding_save"] = app.save_onboarding_settings
                    wizard = ui.OnboardingWizard(host)
                    wizard.render_step(next(i for i, step in enumerate(ONBOARDING_STEPS) if step.id == "test"))
                    pump(root, 0.3)
                    radios = usage_radios(wizard.window)
                    self.assertEqual(usage_checks(wizard.window), [], "setup asks; it has no switch")
                    if not official:
                        self.assertEqual(radios, [])
                        continue
                    self.assertEqual([str(r.cget("text")) for r in radios],
                                     [official_build.USAGE_COUNTS_SHARE, official_build.USAGE_COUNTS_DECLINE])
                    self.assertNotIn(wizard.usage_choice_var.get(), {"yes", "no"}, "neither answer is chosen")
                    if pick:
                        next(r for r in radios if str(r.cget("text")) == pick).invoke()
                    wizard.next_button.invoke()
                    pump(root, 0.5)
                    saved = json.loads(config_path().read_text(encoding="utf-8"))
                    self.assertIs(saved["onboarding"]["completed"], True)
                    self.assertIs(saved["privacy"]["share_usage_counts"], False)
                    self.assertIs(saved["privacy"]["usage_counts_asked"], pick is not None)
                finally:
                    with contextlib.suppress(Exception):
                        root.destroy()
                    with contextlib.suppress(Exception):
                        tk._default_root = None  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
