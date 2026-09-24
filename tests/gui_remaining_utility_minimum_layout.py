"""Real Tk proof for the remaining utility pages at their declared floors.

The companion ``test_remaining_utility_minimum_layout`` launches this module
in a clean interpreter.  These assertions measure mapped Windows widgets, not
source strings: fixed commands must be fully inside the client rectangle and
the intentionally overflowing middle regions must still reach their end.
"""

from __future__ import annotations

from knight_flow.flat_button import FlatButton  # tk.Button off macOS; a styled Label on Aqua

import os
import tempfile
import time
import unittest

from tests import gui_offscreen  # noqa: F401  (never map on a human display)

import tkinter as tk
from tkinter import ttk

from knight_flow.config import load_config
from knight_flow.overlay import Overlay
from knight_flow.reset import CATEGORIES


def pump(root: tk.Misc, seconds: float = 0.25) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


def descendants(widget: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    for child in widget.winfo_children():
        found.append(child)
        found.extend(descendants(child))
    return found


def widget_text(widget: tk.Misc) -> str:
    try:
        text = str(widget.cget("text"))
        if text:
            return text
        variable = str(widget.cget("textvariable"))
        return str(widget.getvar(variable)) if variable else ""
    except (AttributeError, tk.TclError):
        return ""


def find_button(window: tk.Misc, label: str) -> tk.Misc:
    matches = [
        widget for widget in descendants(window)
        if isinstance(widget, (tk.Button, FlatButton, ttk.Button)) and widget_text(widget) == label
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {label!r} button, found {len(matches)}")
    return matches[0]


def scrolling_canvas(window: tk.Misc) -> tk.Canvas:
    matches = [
        widget for widget in descendants(window)
        if isinstance(widget, tk.Canvas)
        and str(widget.cget("yscrollcommand"))
        and str(widget.bind("<End>"))
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one keyboard-scrolling canvas, found {len(matches)}")
    return matches[0]


def set_exact_size(root: tk.Misc, window: tk.Toplevel, width: int, height: int) -> None:
    window.geometry(f"{width}x{height}")
    pump(root, 0.25)
    window.update_idletasks()
    if (window.winfo_width(), window.winfo_height()) != (width, height):
        raise AssertionError(
            f"window did not accept its declared floor: "
            f"{window.winfo_width()}x{window.winfo_height()} != {width}x{height}"
        )


def scroll_until_in_view(root: tk.Misc, canvas: tk.Canvas, widget: tk.Misc) -> bool:
    """Walk the scroller from top to bottom in small steps until the widget's
    midpoint is inside the viewport. False means no scroll position shows it,
    which is the only way a control in a scroller is truly unreachable."""
    steps = 40
    for step in range(steps + 1):
        canvas.yview_moveto(step / steps)
        pump(root, 0.03)
        if midpoint_is_in_view(widget, canvas):
            return True
    return False


def midpoint_is_in_view(widget: tk.Misc, viewport: tk.Misc) -> bool:
    midpoint = widget.winfo_rooty() + widget.winfo_height() / 2
    top = viewport.winfo_rooty()
    return top <= midpoint <= top + viewport.winfo_height()


class RemainingUtilityMinimumRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.previous_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = tempfile.mkdtemp(prefix="talkdat-remaining-minimum-")
        config = load_config()
        config.setdefault("ui", {})["settings_theme"] = "Flow Light"
        config["ui"]["scale"] = 1.0
        cls.overlay = Overlay(
            config=config,
            callbacks={
                "license_status": lambda: {},
                "license_activation_status": lambda: {},
                "save_settings": lambda: None,
            },
        )
        pump(cls.overlay.root, 0.35)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.overlay.root.destroy()
        except Exception:
            pass
        tk._default_root = None  # type: ignore[attr-defined]
        if cls.previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = cls.previous_home

    def setUp(self) -> None:
        self._close_utilities()

    def tearDown(self) -> None:
        self._close_utilities()

    def _close_utilities(self) -> None:
        windows: list[tk.Toplevel] = []
        for window in list(self.overlay.utility_windows.values()):
            if window not in windows:
                windows.append(window)
        for window in windows:
            try:
                window.destroy()
            except Exception:
                pass
        self.overlay.utility_windows.clear()
        self.overlay._shell_window = None
        pump(self.overlay.root, 0.1)

    def assert_fully_in_window(self, window: tk.Toplevel, widget: tk.Misc) -> None:
        self.assertTrue(widget.winfo_ismapped(), f"{widget_text(widget)!r} is not mapped")
        left = widget.winfo_rootx()
        top = widget.winfo_rooty()
        right = left + widget.winfo_width()
        bottom = top + widget.winfo_height()
        window_left = window.winfo_rootx()
        window_top = window.winfo_rooty()
        window_right = window_left + window.winfo_width()
        window_bottom = window_top + window.winfo_height()
        self.assertGreaterEqual(left, window_left)
        self.assertGreaterEqual(top, window_top)
        self.assertLessEqual(right, window_right)
        self.assertLessEqual(bottom, window_bottom)
        self.assertGreater(widget.winfo_width(), 1)
        self.assertGreater(widget.winfo_height(), 1)

    def assert_buttons_inside(self, window: tk.Toplevel, *labels: str) -> None:
        for label in labels:
            with self.subTest(control=label):
                self.assert_fully_in_window(window, find_button(window, label))

    def assert_canvas_reaches_end(self, canvas: tk.Canvas) -> None:
        before = canvas.yview()
        self.assertLess(before[1], 1.0, "content does not overflow, so reachability is unproven")
        canvas.focus_force()
        canvas.event_generate("<End>")
        pump(self.overlay.root, 0.12)
        after = canvas.yview()
        self.assertGreater(after[0], before[0])
        self.assertAlmostEqual(after[1], 1.0, places=2)

    def test_model_guide_pins_its_footer_above_the_scrollable_catalog(self) -> None:
        self.overlay.open_model_guide()
        window = self.overlay.utility_windows["model_guide"]
        set_exact_size(self.overlay.root, window, 760, 560)
        self.assert_buttons_inside(window, "Open official docs", "Close")

        table = next(widget for widget in descendants(window) if isinstance(widget, ttk.Treeview))
        self.assertLess(table.yview()[1], 1.0)
        last = table.get_children()[-1]
        table.see(last)
        pump(self.overlay.root, 0.1)
        self.assertTrue(table.bbox(last), "the final model row is not reachable")

    def test_account_pins_actions_and_has_a_real_top_right_close(self) -> None:
        self.overlay.open_account()
        window = self.overlay.utility_windows["account"]
        set_exact_size(self.overlay.root, window, 620, 440)
        # X-432: sign-in lives in the card now (Email me a code), and the
        # action row's button is the website door by name. Both must be
        # inside the window at its floor, or the floor is a lie.
        self.assert_buttons_inside(window, "Sign in on the website", "Website", "Close", "Close window")
        email_button = find_button(window, "Email me a code")
        self.assertTrue(
            scroll_until_in_view(self.overlay.root, scrolling_canvas(window), email_button),
            "the in-app sign-in cannot be scrolled into view at the floor",
        )

        close = find_button(window, "Close window")
        self.assertGreaterEqual(close.winfo_width(), 44)
        self.assertGreaterEqual(close.winfo_height(), 32)
        canvas = scrolling_canvas(window)
        self.assert_canvas_reaches_end(canvas)
        canvas.yview_moveto(1.0)
        pump(self.overlay.root, 0.1)
        # 2026-09-22: the forever-code row is gone with the prices. The last
        # thing on the page is the line that says Talk DAT! is free.
        free_line = next(
            widget for widget in descendants(window)
            if widget_text(widget).startswith("Talk DAT! is free.")
        )
        self.assertTrue(midpoint_is_in_view(free_line, canvas), "the last Account line is unreachable at End")

    def test_translation_keeps_cloud_and_local_option_lanes_above_actions(self) -> None:
        for engine, extra_buttons in (
            ("managed", ()),
            ("local", ("Install engine", "Download model", "Refresh")),
        ):
            with self.subTest(engine=engine):
                self._close_utilities()
                translation = self.overlay.config.setdefault("translation", {})
                translation["engine"] = engine
                translation["engine_user_chosen"] = True
                self.overlay.open_translation()
                window = self.overlay.utility_windows["translation"]
                set_exact_size(self.overlay.root, window, 900, 650)
                self.assert_buttons_inside(
                    window,
                    "Translate",
                    "Copy result",
                    "Request language",
                    "Close",
                    *extra_buttons,
                )
                for combo in [widget for widget in descendants(window) if isinstance(widget, ttk.Combobox)]:
                    if combo.winfo_ismapped():
                        self.assert_fully_in_window(window, combo)

    def test_reset_keeps_the_summary_and_safety_actions_visible(self) -> None:
        self.overlay.open_reset()
        window = self.overlay.utility_windows["reset"]
        set_exact_size(self.overlay.root, window, 560, 560)
        self.assert_buttons_inside(window, "Preview and erase...", "Cancel")
        summary = next(
            widget for widget in descendants(window)
            if widget_text(widget) == "Nothing selected." or widget_text(widget).startswith("Selected:")
        )
        self.assert_fully_in_window(window, summary)

        canvas = scrolling_canvas(window)
        self.assert_canvas_reaches_end(canvas)
        final_category = next(
            widget for widget in descendants(window)
            if isinstance(widget, ttk.Checkbutton) and widget_text(widget).startswith(CATEGORIES[-1].label)
        )
        self.assertTrue(midpoint_is_in_view(final_category, canvas), "the last reset category is unreachable")

    def test_words_and_phrases_pins_actions_and_scrolls_the_form(self) -> None:
        self.overlay.open_add_words()
        window = self.overlay.utility_windows["add_words"]
        set_exact_size(self.overlay.root, window, 480, 320)
        self.assert_buttons_inside(window, "Add", "Remove selected", "Close")

        canvas = scrolling_canvas(window)
        self.assert_canvas_reaches_end(canvas)
        listbox = next(widget for widget in descendants(window) if isinstance(widget, tk.Listbox))
        self.assertTrue(midpoint_is_in_view(listbox, canvas), "the learned-word list is unreachable at End")


if __name__ == "__main__":
    unittest.main()
