"""Real-window checks for semantic utility-window themes.

This module intentionally does not begin with ``test_``. Tk owns process-global
image state, so the ordinary test below launches this file in a clean Python
interpreter for each run.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from tests import gui_offscreen  # noqa: F401  (never map on a human display)

import tkinter as tk
from tkinter import ttk

from knight_flow.config import load_config
from knight_flow.history import create_history_store
from knight_flow.overlay import Overlay


def pump(root: tk.Misc, seconds: float = 0.3) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.005)


def descendants(widget: tk.Misc) -> list[tk.Misc]:
    result: list[tk.Misc] = []
    for child in widget.winfo_children():
        result.append(child)
        result.extend(descendants(child))
    return result


def widget_text(widget: tk.Misc) -> str:
    try:
        return str(widget.cget("text"))
    except (AttributeError, tk.TclError):
        return ""


class UtilityThemeRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = tempfile.mkdtemp(prefix="talkdat-utility-theme-")
        self.overlays: list[Overlay] = []

    def tearDown(self) -> None:
        for overlay in reversed(self.overlays):
            try:
                overlay.root.destroy()
            except Exception:
                pass
        tk._default_root = None  # type: ignore[attr-defined]
        if self.previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self.previous_home

    def overlay_for(self, theme: str) -> tuple[Overlay, dict[str, str]]:
        config = load_config()
        config.setdefault("ui", {})["settings_theme"] = theme
        overlay = Overlay(config=config, callbacks={})
        self.overlays.append(overlay)
        return overlay, overlay._settings_palette(theme)

    def retire_overlay(self, overlay: Overlay) -> None:
        with self.subTest(cleanup=True):
            try:
                overlay.root.destroy()
            finally:
                if overlay in self.overlays:
                    self.overlays.remove(overlay)
                tk._default_root = None  # type: ignore[attr-defined]

    def assert_title_uses_theme(self, window: tk.Toplevel, title: str, palette: dict[str, str]) -> None:
        labels = [widget for widget in descendants(window) if widget_text(widget) == title]
        self.assertTrue(labels, f"{title!r} has no visible custom title label")
        title_label = labels[0]
        self.assertEqual(str(title_label.cget("background")), palette["bg"])
        self.assertEqual(str(title_label.cget("foreground")), palette["text"])

    def test_status_stats_and_release_notes_follow_dark_and_light_palettes(self) -> None:
        for theme in ("Flow Dark", "Flow Light"):
            with self.subTest(theme=theme):
                overlay, palette = self.overlay_for(theme)

                overlay.open_status()
                overlay.root.update_idletasks()
                status = overlay.utility_windows["status"]
                self.assertEqual(str(status.cget("background")), palette["bg"])
                self.assert_title_uses_theme(status, "Status", palette)
                status_text = next(widget for widget in descendants(status) if isinstance(widget, tk.Text))
                self.assertEqual(str(status_text.cget("background")), palette["field"])
                self.assertEqual(str(status_text.cget("foreground")), palette["text"])
                panic = next(widget for widget in descendants(status) if widget_text(widget) == "Panic stop")
                self.assertIsInstance(panic, ttk.Button)
                self.assertEqual(str(panic.cget("style")), "Flow.Danger.TButton")
                status.destroy()

                create_history_store(overlay.config).append(
                    {
                        "created_at": time.time(),
                        "type": "dictation",
                        "text": "Production review at ten, gym at noon, photo shoot at four.",
                    }
                )
                overlay.open_history()
                pump(overlay.root, 0.4)
                history = overlay.utility_windows["history"]
                self.assertEqual(str(history.cget("background")), palette["bg"])
                self.assert_title_uses_theme(history, "History", palette)
                history_widgets = descendants(history)
                search = next(widget for widget in history_widgets if isinstance(widget, ttk.Entry))
                self.assertEqual(str(search.cget("style")), "Flow.TEntry")
                timeline = next(
                    widget for widget in history_widgets
                    if isinstance(widget, tk.Canvas) and str(widget.cget("yscrollcommand"))
                )
                self.assertEqual(str(timeline.cget("background")), palette["bg"])
                history_row = next(
                    widget for widget in history_widgets
                    if widget_text(widget) == "Production review at ten, gym at noon, photo shoot at four."
                )
                self.assertEqual(str(history_row.cget("background")), palette["bg"])
                self.assertEqual(str(history_row.cget("foreground")), palette["text"])
                self.assertEqual(str(history_row.cget("activebackground")), palette["surface"])
                self.assertEqual(str(history_row.cget("highlightcolor")), palette["warning"])
                time_chips = [
                    widget for widget in history_widgets
                    if isinstance(widget, tk.Label)
                    and str(widget.cget("background")) == palette["panel"]
                    and str(widget.cget("foreground")) == palette["accent"]
                ]
                self.assertTrue(time_chips, "History time chips are not using panel/accent roles")
                protected_title = next(
                    widget for widget in history_widgets if widget_text(widget) == "Protected voice sessions"
                )
                protected = protected_title.master
                self.assertEqual(str(protected.cget("background")), palette["panel"])
                self.assertEqual(str(protected.cget("highlightbackground")), palette["stroke"])

                more = next(widget for widget in history_widgets if widget_text(widget) == "Export and clear...")
                before = set(descendants(overlay.root))
                more.invoke()
                overlay.root.update_idletasks()
                popups = [
                    widget for widget in descendants(overlay.root)
                    if widget not in before and isinstance(widget, tk.Toplevel)
                ]
                self.assertEqual(len(popups), 1, "History More did not open one transient menu")
                more_popup = popups[0]
                clear_history = next(
                    widget for widget in descendants(more_popup) if widget_text(widget) == "Clear text history"
                )
                self.assertEqual(str(clear_history.cget("background")), palette["panel"])
                self.assertEqual(str(clear_history.cget("foreground")), palette["danger"])
                self.assertEqual(str(clear_history.cget("activebackground")), palette["surface"])
                self.assertEqual(str(clear_history.cget("highlightcolor")), palette["warning"])
                more_popup.destroy()
                history.destroy()

                overlay.open_stats()
                overlay.root.update_idletasks()
                stats = overlay.utility_windows["stats"]
                self.assertEqual(str(stats.cget("background")), palette["bg"])
                self.assert_title_uses_theme(stats, "Stats", palette)
                headline = next(
                    widget for widget in descendants(stats)
                    if widget_text(widget) == "Your dictation, by the numbers"
                )
                self.assertEqual(str(headline.cget("foreground")), palette["text"])
                value_labels = [
                    widget for widget in descendants(stats)
                    if isinstance(widget, tk.Label)
                    and str(widget.cget("foreground")) == palette["accent"]
                    and str(widget.cget("background")) == palette["panel"]
                ]
                self.assertTrue(value_labels, "Stats values are not using the theme's semantic accent chip")
                stats.destroy()

                overlay.open_whats_new(
                    "0.4.103-beta",
                    "0.4.104-beta",
                    "## Utility polish\n\n- Theme-safe release notes",
                    "https://example.invalid/release",
                )
                overlay.root.update_idletasks()
                whats_new = overlay.utility_windows["whats_new"]
                self.assertEqual(str(whats_new.cget("background")), palette["bg"])
                self.assert_title_uses_theme(whats_new, "What's New", palette)
                notes = next(widget for widget in descendants(whats_new) if isinstance(widget, tk.Text))
                self.assertEqual(str(notes.cget("background")), palette["field"])
                self.assertEqual(str(notes.cget("foreground")), palette["text"])
                whats_new.destroy()
                self.retire_overlay(overlay)

    def test_update_window_uses_theme_notes_progress_and_status_roles(self) -> None:
        for theme in ("Flow Dark", "Flow Light"):
            with self.subTest(theme=theme):
                overlay, palette = self.overlay_for(theme)
                overlay.open_update_window(
                    {
                        "current_version": "0.4.103-beta",
                        "latest_version": "0.4.104-beta",
                        "published_at": "2026-08-21",
                        "release_notes": "## Better utilities\n\n- Theme coherence",
                        "has_installer": True,
                        "has_checksum": True,
                        "release_url": "https://example.invalid/release",
                    },
                    lambda *_args: None,
                    lambda: None,
                )
                overlay.root.update_idletasks()
                window = overlay.utility_windows["update"]
                self.assertEqual(str(window.cget("background")), palette["bg"])
                self.assert_title_uses_theme(window, "Update", palette)
                notes = next(widget for widget in descendants(window) if isinstance(widget, tk.Text))
                self.assertEqual(str(notes.cget("background")), palette["field"])
                self.assertEqual(str(notes.cget("foreground")), palette["text"])
                progress = next(widget for widget in descendants(window) if isinstance(widget, ttk.Progressbar))
                self.assertEqual(str(progress.cget("style")), "Flow.Horizontal.TProgressbar")
                self.retire_overlay(overlay)


if __name__ == "__main__":
    unittest.main()
