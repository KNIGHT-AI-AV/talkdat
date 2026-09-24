"""Real-Tk proof that an update install cannot lose its owning window."""

from __future__ import annotations

from knight_flow.flat_button import FlatButton  # tk.Button off macOS; a styled Label on Aqua

import os
import tempfile
import time
import unittest

from tests import gui_offscreen  # noqa: F401  (keep native windows off screen)

import tkinter as tk
from tkinter import ttk


def pump(root: tk.Misc, seconds: float = 0.15) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


def descendants(widget: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    stack = list(widget.winfo_children())
    while stack:
        child = stack.pop()
        found.append(child)
        stack.extend(child.winfo_children())
    return found


class UpdateTransactionSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_home = os.environ.get("TALK_DAT_HOME")
        self.home = tempfile.TemporaryDirectory(prefix="talkdat-update-transaction-")
        os.environ["TALK_DAT_HOME"] = self.home.name
        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        self.overlay = Overlay(load_config(), callbacks={})
        pump(self.overlay.root, 0.2)

    def tearDown(self) -> None:
        try:
            self.overlay.root.destroy()
        except Exception:
            pass
        tk._default_root = None  # type: ignore[attr-defined]
        self.home.cleanup()
        if self.previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self.previous_home

    def _button(self, window: tk.Misc, text: str) -> ttk.Button | tk.Button:
        matches = [
            widget
            for widget in descendants(window)
            if isinstance(widget, (ttk.Button, tk.Button, FlatButton)) and str(widget.cget("text")) == text
        ]
        self.assertTrue(matches, f"missing real button {text!r}")
        return matches[0]

    def _open(self, on_install):
        self.overlay.open_update_window(
            {
                "current_version": "0.4.120-beta",
                "latest_version": "0.4.121-beta",
                "published_at": "2026-08-21",
                "release_notes": "## Safer update\n\n- Signed installer\n- Preserved settings",
                "has_installer": True,
                "has_checksum": True,
                "provenance_verified": True,
                "source_commit": "0123456789abcdef0123456789abcdef",
                "installer_size": 80 * 1024 * 1024,
                "release_url": "https://example.invalid/release",
            },
            on_install,
            lambda: None,
        )
        pump(self.overlay.root, 0.35)
        return self.overlay.utility_windows["update"]

    def test_busy_install_blocks_escape_close_and_sidebar_until_done(self) -> None:
        callbacks: dict[str, object] = {}

        def hold_install(set_progress, set_status, on_done) -> None:
            callbacks.update(progress=set_progress, status=set_status, done=on_done)

        window = self._open(hold_install)
        install = self._button(window, "Install now")
        install.invoke()
        pump(self.overlay.root, 0.1)

        self.assertTrue(getattr(window, "_close_locked", False))
        self.assertTrue(getattr(window, "_navigation_locked", False))
        self.assertEqual(str(install.cget("state")), "disabled")

        replacement_calls: list[str] = []
        reentered = self._open(lambda *_args: replacement_calls.append("replacement"))
        self.assertIs(reentered, window, "reentrant update open replaced the live transaction owner")
        self.assertTrue(window.winfo_exists())
        self.assertEqual(replacement_calls, [])

        window.event_generate("<Escape>")
        pump(self.overlay.root, 0.05)
        self.assertTrue(window.winfo_exists(), "Escape destroyed a live install transaction")

        self._button(window, "Close window").invoke()
        pump(self.overlay.root, 0.05)
        self.assertTrue(window.winfo_exists(), "title-bar close destroyed a live install transaction")

        settings_controls = [
            widget
            for widget in descendants(window)
            if hasattr(widget, "keys")
            and "text" in widget.keys()
            and "takefocus" in widget.keys()
            and str(widget.cget("text")) == "Settings"
            and str(widget.cget("takefocus")) != "0"
        ]
        self.assertTrue(settings_controls, "sidebar Settings destination is missing")
        destination = settings_controls[0]
        if isinstance(destination, (tk.Button, FlatButton, ttk.Button)):
            destination.invoke()
        else:
            destination.event_generate("<Return>")
        pump(self.overlay.root, 0.1)
        self.assertTrue(window.winfo_exists(), "sidebar navigation replaced the live update transaction")
        self.assertIs(self.overlay.utility_windows.get("update"), window)

        callbacks["done"](False, "Installer verification failed safely")  # type: ignore[operator]
        pump(self.overlay.root, 0.15)
        self.assertFalse(getattr(window, "_close_locked", True))
        self.assertFalse(getattr(window, "_navigation_locked", True))
        self.assertEqual(str(install.cget("state")), "normal")

        self._button(window, "Close window").invoke()
        pump(self.overlay.root, 0.2)
        self.assertFalse(window.winfo_exists())

    def test_synchronous_installer_failure_unlocks_the_window(self) -> None:
        def fail_immediately(*_args) -> None:
            raise RuntimeError("test launch failure")

        window = self._open(fail_immediately)
        install = self._button(window, "Install now")
        install.invoke()
        pump(self.overlay.root, 0.1)
        self.assertFalse(getattr(window, "_close_locked", True))
        self.assertFalse(getattr(window, "_navigation_locked", True))
        self.assertEqual(str(install.cget("state")), "normal")
        status_text = " ".join(
            str(widget.cget("textvariable") and widget.getvar(widget.cget("textvariable")))
            for widget in descendants(window)
            if isinstance(widget, tk.Label) and str(widget.cget("textvariable"))
        )
        self.assertIn("test launch failure", status_text)

    def test_three_rapid_notifications_present_only_the_latest_payload(self) -> None:
        first = self._open(lambda *_args: None)

        def payload(latest: str) -> dict[str, object]:
            return {
                "current_version": "0.4.120-beta",
                "latest_version": latest,
                "published_at": "2026-08-21",
                "release_notes": f"## {latest}\n\nLatest notification wins.",
                "has_installer": True,
                "has_checksum": True,
                "provenance_verified": True,
                "source_commit": "fedcba9876543210fedcba9876543210",
                "installer_size": 80 * 1024 * 1024,
                "release_url": "https://example.invalid/release",
            }

        # U1 starts the close; U2 arrives inside the fade/retirement window.
        # The close completion must be replaceable, not first-writer-wins.
        self.overlay.open_update_window(
            payload("0.4.122-beta"),
            lambda *_args: None,
            lambda: None,
        )
        self.overlay.open_update_window(
            payload("0.4.123-beta"),
            lambda *_args: None,
            lambda: None,
        )
        pump(self.overlay.root, 0.9)

        latest = self.overlay.utility_windows["update"]
        self.assertIsNot(latest, first)
        visible_text = "\n".join(
            str(widget.cget("text"))
            for widget in descendants(latest)
            if hasattr(widget, "keys") and "text" in widget.keys()
        )
        self.assertIn("0.4.123-beta", visible_text)
        self.assertNotIn("0.4.122-beta", visible_text)


if __name__ == "__main__":
    unittest.main()
