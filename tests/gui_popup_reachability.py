"""Real-Tk proofs for monitor-safe tooltips and Scratchpad reachability.

Runs in the clean interpreter managed by test_gui_regressions.py. The windows
remain transparent so the suite never interrupts the person using the machine.
"""

from __future__ import annotations

from knight_flow import mac_support

from knight_flow.flat_button import FlatButton  # tk.Button off macOS; a styled Label on Aqua

import os
import re
import tempfile
import time
import unittest
from unittest import mock

from tests import gui_offscreen  # noqa: F401


def run_key_binding(widget, sequence: str) -> None:
    """Run a widget's bound script for `sequence` as Tk would on a real key.

    Aqua drops synthesized key events, so the keyboard contract is exercised
    by evaluating the binding itself: %W becomes the widget path and every
    other substitution the placeholder Tk uses for a missing field.
    """
    script = widget.bind(sequence) or widget.bind_class(widget.winfo_class(), sequence)
    assert script, f"{widget} has no {sequence} binding"
    keysym = sequence.strip("<>").split("-")[-1]
    # tkinter parses the numeric fields, so they must be integers; %T is 2 (KeyPress).
    # %A (the typed character) must stay a WORD: an empty bare word vanishes
    # from the Tcl argument list and tkinter then skips its Event substitution.
    fields = {"W": str(widget), "K": keysym, "A": "{}", "E": "0", "T": "2"}
    body = re.sub(r"%(.)", lambda m: fields.get(m.group(1), "0"), script)
    # A handler returning "break" makes the wrapper run Tcl `break`, which
    # needs an enclosing loop.
    widget.tk.eval("foreach _talkdat_once 1 { " + body + " }")

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - tkinter missing entirely
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]


def pump(root: tk.Misc, seconds: float = 0.2) -> None:
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


@unittest.skipIf(tk is None, "tkinter unavailable")
class RealPopupReachabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        cls._home = tempfile.TemporaryDirectory(prefix="talkdat-popup-reachability-")
        os.environ["TALK_DAT_HOME"] = cls._home.name

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        cls.overlay = Overlay(load_config(), callbacks={})
        pump(cls.overlay.root, 0.15)

    @classmethod
    def tearDownClass(cls) -> None:
        with mock.patch.object(cls.overlay, "_save_scratchpad_tabs", return_value=None):
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
        cls._home.cleanup()

    def test_settings_tooltip_opens_from_focus_and_stays_inside_a_negative_monitor(self) -> None:
        self.overlay.open_settings()
        pump(self.overlay.root, 0.45)
        window = self.overlay.utility_windows["settings"]
        language_label = next(
            widget
            for widget in descendants(window)
            if widget.winfo_class() in {"Label", "TLabel"}
            and str(widget.cget("text")) == "Language"
        )
        label_grid = language_label.grid_info()
        language_field = language_label.master.grid_slaves(
            row=int(label_grid["row"]),
            column=1,
        )[0]
        self.assertTrue(language_field.bind("<FocusIn>"))

        negative_monitor = (-1920, -1080, 0, 0)
        with mock.patch.object(
            self.overlay,
            "_window_monitor_work_area",
            return_value=negative_monitor,
        ):
            language_field.event_generate("<FocusIn>")
            pump(self.overlay.root, 0.08)
            language_field.event_generate("<Enter>")
            pump(self.overlay.root, 0.08)
            language_field.event_generate("<Leave>")
            pump(self.overlay.root, 0.08)

        left, top, right, bottom = negative_monitor
        tooltips = [
            widget
            for widget in descendants(window)
            if isinstance(widget, tk.Toplevel) and bool(widget.overrideredirect())
            and widget.winfo_rootx() >= left + 8
            and widget.winfo_rooty() >= top + 8
            and widget.winfo_rootx() + widget.winfo_width() <= right - 8
            and widget.winfo_rooty() + widget.winfo_height() <= bottom - 8
        ]
        self.assertEqual(len(tooltips), 1)
        tip = tooltips[0]
        self.assertGreaterEqual(tip.winfo_rootx(), left + 8)
        self.assertGreaterEqual(tip.winfo_rooty(), top + 8)
        self.assertLessEqual(tip.winfo_rootx() + tip.winfo_width(), right - 8)
        self.assertLessEqual(tip.winfo_rooty() + tip.winfo_height(), bottom - 8)

        language_field.event_generate("<FocusOut>")
        # Help waits briefly so moving from the owner into a scrollable tip is
        # possible, then runs the same short guarded fade as other popovers.
        pump(self.overlay.root, 0.24)
        self.assertFalse(bool(tip.winfo_exists()))

    def test_settings_tooltip_uses_logical_bounds_when_monitor_lookup_is_unavailable(self) -> None:
        self.overlay.open_settings()
        pump(self.overlay.root, 0.2)
        window = self.overlay.utility_windows["settings"]
        language_label = next(
            widget
            for widget in descendants(window)
            if widget.winfo_class() in {"Label", "TLabel"}
            and str(widget.cget("text")) == "Language"
        )
        label_grid = language_label.grid_info()
        language_field = language_label.master.grid_slaves(
            row=int(label_grid["row"]),
            column=1,
        )[0]
        fallback = (40, 30, 520, 190)
        ui = self.overlay.config.setdefault("ui", {})
        original_scale = ui.get("scale")
        ui["scale"] = 2.0
        try:
            with (
                mock.patch.object(
                    self.overlay,
                    "_window_monitor_work_area",
                    return_value=None,
                ) as monitor_lookup,
                mock.patch.object(
                    self.overlay,
                    "_logical_work_area",
                    return_value=fallback,
                ) as logical_lookup,
            ):
                language_field.event_generate("<Enter>")
                pump(self.overlay.root, 0.1)

            monitor_lookup.assert_called()
            logical_lookup.assert_called()
            tips = [
                widget
                for widget in descendants(window)
                if isinstance(widget, tk.Toplevel)
                and hasattr(widget, "_talkdat_tooltip_copy")
                and bool(widget.winfo_exists())
            ]
            self.assertEqual(len(tips), 1)
            tip = tips[0]
            gutter = 16
            left, top, right, bottom = fallback
            self.assertGreaterEqual(tip.winfo_rootx(), left + gutter)
            self.assertGreaterEqual(tip.winfo_rooty(), top + gutter)
            self.assertLessEqual(
                tip.winfo_rootx() + tip.winfo_width(),
                right - gutter,
            )
            self.assertLessEqual(
                tip.winfo_rooty() + tip.winfo_height(),
                bottom - gutter,
            )
            self.assertLessEqual(
                int(tip._talkdat_tooltip_content_width),  # type: ignore[attr-defined]
                tip.winfo_width() - 88,
            )
            self.assertTrue(tip._talkdat_tooltip_scroll_mode)  # type: ignore[attr-defined]
            scrollbar = tip._talkdat_tooltip_scrollbar  # type: ignore[attr-defined]
            body = tip._talkdat_tooltip_body  # type: ignore[attr-defined]
            self.assertIsNotNone(scrollbar)
            self.assertTrue(scrollbar.winfo_ismapped())
            self.assertLess(body.yview()[1], 1.0)
            self.assertTrue(body.bind("<End>"))
            # Offscreen GUI tests intentionally cannot claim keyboard focus;
            # drive the same viewport operation directly and leave the binding
            # contract to the source-level keyboard parity test.
            body.yview_moveto(1.0)
            pump(self.overlay.root, 0.06)
            self.assertAlmostEqual(body.yview()[1], 1.0, places=6)

            language_field.event_generate("<Leave>")
            pump(self.overlay.root, 0.4)
            self.assertFalse(bool(tip.winfo_exists()))
        finally:
            if original_scale is None:
                ui.pop("scale", None)
            else:
                ui["scale"] = original_scale

    def test_scratchpad_minimum_and_long_font_list_remain_reachable(self) -> None:
        with mock.patch.object(self.overlay, "_save_scratchpad_tabs", return_value=None):
            self.overlay.open_scratchpad()
            pump(self.overlay.root, 0.35)
        window = self.overlay.utility_windows["scratchpad"]
        if not mac_support.IS_MAC:
            # Aqua reports a borderless (overrideredirect) window as not WM-resizable;
            # there the utility resizes through the app's own edge bindings.
            self.assertEqual(tuple(bool(value) for value in window.resizable()), (True, True))
        min_width, min_height = window.minsize()
        self.assertGreaterEqual(min_width, 760)
        self.assertGreaterEqual(min_height, 500)

        window.geometry(f"{min_width}x{min_height}+20+20")
        pump(self.overlay.root, 0.2)
        footer_actions = [
            widget
            for widget in descendants(window)
            if isinstance(widget, ttk.Button) and str(widget.cget("text")) in {"Save", "Close"}
        ]
        self.assertEqual({str(button.cget("text")) for button in footer_actions}, {"Save", "Close"})
        for button in footer_actions:
            self.assertTrue(button.winfo_ismapped())
            self.assertGreaterEqual(button.winfo_rootx(), window.winfo_rootx())
            self.assertLessEqual(
                button.winfo_rootx() + button.winfo_width(),
                window.winfo_rootx() + window.winfo_width(),
            )
            self.assertLessEqual(
                button.winfo_rooty() + button.winfo_height(),
                window.winfo_rooty() + window.winfo_height(),
            )

        font_action = next(
            widget
            for widget in descendants(window)
            if isinstance(widget, ttk.Button) and str(widget.cget("text")) == "Font"
        )
        fake_families = tuple(f"Reachable Font {index:03d}" for index in range(300))
        negative_monitor = (-1920, -1080, 0, 0)
        with (
            mock.patch("knight_flow.overlay.tkfont.families", return_value=fake_families),
            mock.patch.object(
                self.overlay,
                "_window_monitor_work_area",
                return_value=negative_monitor,
            ),
        ):
            started = time.perf_counter()
            font_action.invoke()
            invoke_elapsed = time.perf_counter() - started
            pump(self.overlay.root, 0.25)

        self.assertLess(
            invoke_elapsed,
            0.35,
            "opening the font picker rebuilt hundreds of font widgets on Tk's UI thread",
        )

        popups = [
            widget
            for widget in descendants(window)
            if isinstance(widget, tk.Toplevel)
            and any(
                isinstance(child, tk.Listbox)
                and int(child.size()) >= len(fake_families)
                for child in descendants(widget)
            )
        ]
        self.assertEqual(len(popups), 1)
        popup = popups[0]
        listboxes = [widget for widget in descendants(popup) if isinstance(widget, tk.Listbox)]
        scrollbars = [widget for widget in descendants(popup) if isinstance(widget, ttk.Scrollbar)]
        font_buttons = [
            widget
            for widget in descendants(popup)
            if isinstance(widget, (tk.Button, FlatButton)) and str(widget.cget("text")).startswith("Reachable Font")
        ]
        self.assertEqual(len(listboxes), 1)
        self.assertEqual(len(scrollbars), 1)
        self.assertEqual(font_buttons, [], "font names must not become hundreds of eager widgets")
        self.assertGreaterEqual(int(listboxes[0].size()), len(fake_families))
        shown = {
            str(listboxes[0].get(index))
            for index in range(int(listboxes[0].size()))
        }
        self.assertTrue(set(fake_families).issubset(shown))
        self.assertTrue(scrollbars[0].winfo_ismapped())
        self.assertLess(listboxes[0].yview()[1], 0.99)
        self.assertGreaterEqual(popup.winfo_rootx(), negative_monitor[0] + 8)
        self.assertGreaterEqual(popup.winfo_rooty(), negative_monitor[1] + 8)
        self.assertLessEqual(popup.winfo_rootx() + popup.winfo_width(), negative_monitor[2] - 8)
        self.assertLessEqual(popup.winfo_rooty() + popup.winfo_height(), negative_monitor[3] - 8)

        listboxes[0].focus_set()
        if mac_support.IS_MAC:
            # Aqua drops synthesized key events outright; run the list's own
            # <End> binding script the way Tk would on a real press.
            run_key_binding(listboxes[0], "<End>")
        else:
            listboxes[0].event_generate("<End>")
        pump(self.overlay.root, 0.1)
        self.assertGreater(listboxes[0].yview()[0], 0.5)
        listboxes[0].yview_moveto(0.0)
        listboxes[0].event_generate("<MouseWheel>", delta=-120)
        pump(self.overlay.root, 0.08)
        self.assertGreater(listboxes[0].yview()[0], 0.0)
        popup.destroy()
        pump(self.overlay.root, 0.05)


if __name__ == "__main__":
    unittest.main()
