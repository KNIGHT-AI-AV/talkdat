"""LIST-0476: the Tk Settings fallback's save sets the network fence too.

The launch, the Pill's route switch, the web Settings save (AppShell._applied)
and setup apply one rule (X-338): the fence is up while Local-only privacy is on
or the route reads Local through route_mode(). The Tk Settings fallback's save
never touched it, so a change made there waited for the next route switch, web
save or launch. Real windows, on the isolated test desktop
(scripts/run_tests_offscreen.py tests.test_the_tk_settings_save_sets_the_fence).
"""
from __future__ import annotations

import contextlib
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


def pump(root, seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@unittest.skipIf(tk is None, "tkinter unavailable")
class TheTkSettingsSaveSetsTheFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        with contextlib.suppress(Exception):
            existing = getattr(tk, "_default_root", None)
            if existing is not None and not existing.winfo_exists():
                tk._default_root = None  # type: ignore[attr-defined]
        self._previous_home = os.environ.get("TALK_DAT_HOME")
        self._home = tempfile.mkdtemp(prefix="talkdat-fence-")
        os.environ["TALK_DAT_HOME"] = self._home

    def tearDown(self) -> None:
        with contextlib.suppress(Exception):
            tk._default_root = None  # type: ignore[attr-defined]
        if self._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._previous_home

    def save(self, local_only: bool, route: str):
        from knight_flow.config import load_config, save_config
        from knight_flow.overlay import Overlay

        config = load_config()
        config["privacy"]["local_only"] = local_only
        config["stt"]["route_mode"] = route
        overlay = Overlay(config, callbacks={"save_settings": lambda: save_config(overlay.config)})
        self.addCleanup(lambda: overlay.root.destroy())
        pump(overlay.root, 0.4)
        overlay.open_settings()
        pump(overlay.root, 1.2)
        window = overlay.utility_windows.get("settings")
        self.assertIsNotNone(window, "the Tk Settings window did not open")
        button = next(w for w in descendants(window) if w.winfo_class() == "TButton" and str(w.cget("text")) == "Save")
        with mock.patch("knight_flow.net_fence.set_local_only") as fence:
            button.invoke()
            pump(overlay.root, 0.3)
        return overlay, fence

    def test_local_only_on_keeps_it_up(self) -> None:
        overlay, fence = self.save(True, "byok")
        self.assertIs(overlay.config["privacy"]["local_only"], True)
        fence.assert_called_with(True)

    def test_a_route_that_reads_local_keeps_it_up(self) -> None:
        overlay, fence = self.save(False, "local")
        self.assertIs(overlay.config["privacy"]["local_only"], False)
        fence.assert_called_with(True)

    def test_your_key_with_local_only_off_lowers_it(self) -> None:
        from knight_flow.stt_registry import local_only, route_mode

        overlay, fence = self.save(False, "byok")
        self.assertFalse(local_only(overlay.config) or route_mode(overlay.config) == "local")
        fence.assert_called_with(False)


if __name__ == "__main__":
    unittest.main()
