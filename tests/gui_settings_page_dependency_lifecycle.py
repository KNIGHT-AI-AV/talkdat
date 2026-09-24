"""Real Settings lifecycle checks for page-owned dependency probes.

Opening the default General page must not enumerate audio hardware or contact
the local formatter runtime.  Each dependency belongs to the page that can use
its result, starts on that page's first selection, and remains initialized when
the person navigates away and back.

This module is launched in a clean interpreter by ``test_gui_regressions`` so
the assertions observe a real Tk Settings window without inheriting another
test's default root.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

if sys.platform == "win32":
    from tests import gui_offscreen  # noqa: F401

try:
    import tkinter as tk
except Exception:  # pragma: no cover
    tk = None  # type: ignore[assignment]


def pump(root, seconds: float = 0.25) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


def wait_for_count(root, snapshot, key: str, expected: int, *, timeout: float = 3.0) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        root.update()
        if snapshot()[key] >= expected:
            return
        time.sleep(0.01)
    raise AssertionError(f"{key} dependency did not start {expected} time(s)")


@unittest.skipIf(tk is None, "tkinter unavailable")
class SettingsPageDependencyLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = tempfile.mkdtemp(prefix="talkdat-settings-deps-")

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        config = load_config()
        config.setdefault("ui", {})["reduce_motion"] = True
        config.setdefault("transforms", {})["llm"] = {
            "provider": "ollama",
            "model": "qwen2.5:1.5b-instruct-q4_K_M",
            "api_base": "http://localhost:11434",
        }
        cls.overlay = Overlay(config, callbacks={})
        pump(cls.overlay.root, 0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.overlay.root.destroy()
        except Exception:
            pass
        try:
            tk._default_root = None  # type: ignore[attr-defined]
        except Exception:
            pass
        if cls._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = cls._previous_home

    def tearDown(self) -> None:
        shell = getattr(self.overlay, "_shell_window", None)
        if shell is not None:
            try:
                shell.destroy()
            except Exception:
                pass
        for child in tuple(self.overlay.root.winfo_children()):
            if isinstance(child, tk.Toplevel):
                try:
                    child.destroy()
                except Exception:
                    pass
        self.overlay._shell_window = None
        self.overlay.utility_windows.clear()
        pump(self.overlay.root, 0.1)

    def test_dependencies_start_once_when_their_owning_page_is_first_selected(self) -> None:
        calls = {"microphones": 0, "formatter": 0}
        calls_lock = threading.Lock()

        def count_microphones() -> list[str]:
            with calls_lock:
                calls["microphones"] += 1
            return ["1: Studio microphone"]

        def count_formatter(_config) -> dict[str, object]:
            with calls_lock:
                calls["formatter"] += 1
            return {
                "local": True,
                "ready": False,
                "engine_installed": True,
                "engine_running": True,
                "model_installed": False,
                "model": "qwen2.5:1.5b-instruct-q4_K_M",
            }

        def snapshot() -> dict[str, int]:
            with calls_lock:
                return dict(calls)

        with (
            mock.patch("knight_flow.overlay.list_input_devices", side_effect=count_microphones),
            mock.patch("knight_flow.llm.local_formatter_status", side_effect=count_formatter),
        ):
            self.overlay.open_settings()
            window = self.overlay.utility_windows["settings"]
            pump(self.overlay.root, 0.5)

            self.assertEqual(
                snapshot(),
                {"microphones": 0, "formatter": 0},
                "the default General page initialized dependencies owned by hidden pages",
            )

            select = window._select_settings_page  # type: ignore[attr-defined]
            select("Dictation", None, "Mic + paste")
            wait_for_count(self.overlay.root, snapshot, "microphones", 1)
            pump(self.overlay.root, 0.2)
            self.assertEqual(snapshot(), {"microphones": 1, "formatter": 0})

            select("General", None, "At a glance")
            select("Dictation", None, "Mic + paste")
            pump(self.overlay.root, 0.3)
            self.assertEqual(
                snapshot(),
                {"microphones": 1, "formatter": 0},
                "revisiting Dictation restarted audio-device enumeration",
            )

            select("Formatting", None, "Formatting")
            wait_for_count(self.overlay.root, snapshot, "formatter", 1)
            pump(self.overlay.root, 0.2)
            self.assertEqual(snapshot(), {"microphones": 1, "formatter": 1})

            select("General", None, "At a glance")
            select("Formatting", None, "Formatting")
            pump(self.overlay.root, 0.3)
            self.assertEqual(
                snapshot(),
                {"microphones": 1, "formatter": 1},
                "revisiting Formatting restarted local formatter readiness probing",
            )


if __name__ == "__main__":
    unittest.main()
