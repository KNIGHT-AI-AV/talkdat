"""The Tk fallbacks for the usage-counts switch (owner decision 2026-09-23).

When the web shell cannot open, Settings and first-run setup fall back to Tk.
Those carry the same switch in the same words: one checkbox, only in an
official build, saving privacy.share_usage_counts. Real windows, on the
isolated test desktop (scripts/run_tests_offscreen.py tests.test_usage_counts_tk).
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


def usage_checks(window) -> list:
    found = []
    for widget in descendants(window):
        if widget.winfo_class() in {"TCheckbutton", "Checkbutton"}:
            with contextlib.suppress(tk.TclError):
                if str(widget.cget("text")) == official_build.USAGE_COUNTS_LINE:
                    found.append(widget)
    return found


@unittest.skipIf(tk is None, "tkinter unavailable")
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
        with contextlib.suppress(Exception):
            tk._default_root = None  # type: ignore[attr-defined]
        if self._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._previous_home

    def settings_window(self):
        from knight_flow.config import load_config, save_config
        from knight_flow.overlay import Overlay

        config = load_config()
        overlay = Overlay(config, callbacks={"save_settings": lambda: save_config(overlay.config)})
        self.addCleanup(lambda: overlay.root.destroy())
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
            self.assertTrue(overlay.root.getboolean(overlay.root.getvar(variable)), "on by default")
            checks[0].invoke()
            save = next(w for w in descendants(window) if w.winfo_class() == "TButton" and str(w.cget("text")) == "Save")
            save.invoke()
            pump(overlay.root, 0.3)
            self.assertIs(overlay.config["privacy"]["share_usage_counts"], False)
            self.assertIs(overlay.config["privacy"]["local_only"], True)

    def test_tk_settings_shows_no_switch_in_a_source_build(self) -> None:
        with build(False):
            _overlay, window = self.settings_window()
            self.assertEqual(usage_checks(window), [])

    @unittest.skipUnless(sys.platform == "win32", "the setup wizard fallback is exercised on Windows")
    def test_the_tk_setup_wizard_mentions_it_once_and_saves_it(self) -> None:
        from knight_flow import main_thread
        from knight_flow.app import TalkDatApp
        from knight_flow.config import config_path
        from knight_flow.onboarding import ONBOARDING_STEPS
        from knight_flow.ui import onboarding as ui
        from scripts.capture_onboarding_gallery import CaptureHost

        for official in (False, True):
            with self.subTest(official=official), build(official), \
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
                    checks = usage_checks(wizard.window)
                    if not official:
                        self.assertEqual(checks, [])
                        continue
                    self.assertEqual(len(checks), 1)
                    self.assertTrue(wizard.share_counts_var.get())
                    checks[0].invoke()
                    self.assertFalse(wizard.share_counts_var.get())
                    wizard.next_button.invoke()
                    pump(root, 0.5)
                    saved = json.loads(config_path().read_text(encoding="utf-8"))
                    self.assertIs(saved["onboarding"]["completed"], True)
                    self.assertIs(saved["privacy"]["share_usage_counts"], False)
                finally:
                    with contextlib.suppress(Exception):
                        root.destroy()
                    with contextlib.suppress(Exception):
                        tk._default_root = None  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
