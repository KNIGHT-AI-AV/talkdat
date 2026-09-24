"""X-183: Scratchpad saves through EVERY close, including the shared X.

X-177 added a disposer so the pending autosave is flushed however the window
ends. It did not work through the one path that needed it most, and the reason is
a Tk ordering fact worth stating plainly:

    destroying a Toplevel destroys its CHILDREN BEFORE the Toplevel's own
    <Destroy> binding fires

Measured directly in raw Tk:

    ('binding-fired', '.!toplevel.!text', top_exists=True,  text_exists=False)

So a disposer hung on <Destroy> sees dead widgets. Scratchpad's flush is guarded
by `text.winfo_exists()` -- correctly, since it must never raise during teardown
-- so it returned silently and the last edits were lost.

The footer Close, Escape and WM_DELETE_WINDOW all route through `close_window`,
which saves first, so they were fine. The shared X control calls
`window.destroy()` directly and cannot be intercepted, which is exactly the path
this test drives.

Disposal now happens at the top of the destroy wrapper, before any child dies.

Run in its own interpreter by tests/test_gui_regressions.py.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

if sys.platform == "win32":
    from tests import gui_offscreen  # noqa: F401

try:
    import tkinter as tk
except Exception:  # pragma: no cover
    tk = None  # type: ignore[assignment]


def pump(root, seconds: float = 0.8) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


@unittest.skipIf(tk is None, "tkinter unavailable")
class ScratchpadSurvivesEveryCloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        cls._home = tempfile.mkdtemp(prefix="talkdat-scratch-")
        os.environ["TALK_DAT_HOME"] = cls._home
        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        cls.overlay = Overlay(load_config(), callbacks={})
        pump(cls.overlay.root, 0.4)

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

    def _scratchpad_file(self) -> Path:
        # Ask the app where it keeps them rather than guessing a filename; the
        # first version of this test guessed "scratchpad.json" and failed on a
        # missing file instead of on the defect it was written for.
        from knight_flow.config import scratchpad_tabs_path

        # scratchpad_path() is the legacy single .md file; the tabbed editor
        # writes scratchpad-tabs.json, which is what save_now persists.
        return Path(scratchpad_tabs_path())

    def test_typing_then_closing_by_the_shared_x_keeps_the_text(self) -> None:
        """The path that was silently losing edits.

        The footer Close, Escape and the window manager button all route through
        close_window, which saves first. Only the shared X control calls
        destroy() directly, and it cannot be intercepted, so it is the one that
        needed disposal to run while the widgets were alive.
        """
        self.overlay.open_scratchpad()
        pump(self.overlay.root, 1.4)
        window = self.overlay.utility_windows.get("scratchpad")
        self.assertIsNotNone(window, "Scratchpad did not open")

        editors = []

        def collect(widget) -> None:
            for child in widget.winfo_children():
                if isinstance(child, tk.Text):
                    editors.append(child)
                collect(child)

        collect(window)
        self.assertTrue(editors, "no text editor found in Scratchpad")
        editor = max(editors, key=lambda w: w.winfo_width() * w.winfo_height())

        marker = "x183-shared-x-close-marker"
        editor.insert("end", marker)
        editor.edit_modified(True)
        # Deliberately LESS than the 520ms autosave delay: the whole defect is
        # about what happens to an edit that has not been written yet.
        pump(self.overlay.root, 0.2)

        window.destroy()          # exactly what the shared X control does
        pump(self.overlay.root, 0.8)

        path = self._scratchpad_file()
        self.assertTrue(path.exists(), f"nothing was written to {path}")
        self.assertIn(
            marker, path.read_text(encoding="utf-8", errors="replace"),
            "text typed just before closing was lost; the flush ran after the "
            "editor was already destroyed and skipped itself",
        )


if __name__ == "__main__":
    unittest.main()
