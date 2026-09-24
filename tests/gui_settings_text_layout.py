"""Real-Tk Settings text-layout proofs for one isolated UI scale.

This module is launched by ``tests.test_settings_text_layout`` in fresh
interpreters because Tk's scaling and named-style tables are process global.
The windows remain fully transparent and parked away from the user's desktop.
"""

from __future__ import annotations

from knight_flow import mac_support

from knight_flow import ui_scale

import os
import tempfile
import time
import tkinter as tk
import tkinter.font as tkfont
import unittest
from tkinter import ttk
from unittest import mock

from tests import gui_offscreen  # noqa: F401


WARNING_COPY = (
    "Saved, but Rewrite and Translate share Ctrl+Win+R, so only one action will "
    "fire. Give one of them different keys before relying on either shortcut "
    "during a live dictation. The rest of your Settings were saved and remain "
    "available; this warning stays here until you resolve the shortcut conflict."
)

LONG_HELP_LABEL = "Keep a local formatting log (what you said vs what was typed)"
FOOTER_LABEL_STYLES = {
    "Flow.Footer.TLabel",
    "Flow.FooterSaving.TLabel",
    "Flow.FooterSuccess.TLabel",
    "Flow.FooterWarning.TLabel",
    "Flow.FooterError.TLabel",
}


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


def assert_widget_inside(
    case: unittest.TestCase,
    child: tk.Misc,
    parent: tk.Misc,
    message: str,
) -> None:
    child_left = int(child.winfo_rootx())
    child_top = int(child.winfo_rooty())
    child_right = child_left + int(child.winfo_width())
    child_bottom = child_top + int(child.winfo_height())
    parent_left = int(parent.winfo_rootx())
    parent_top = int(parent.winfo_rooty())
    parent_right = parent_left + int(parent.winfo_width())
    parent_bottom = parent_top + int(parent.winfo_height())
    case.assertGreaterEqual(child_left, parent_left, message)
    case.assertGreaterEqual(child_top, parent_top, message)
    case.assertLessEqual(child_right, parent_right, message)
    case.assertLessEqual(child_bottom, parent_bottom, message)


class SettingsTextLayoutRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scale = float(os.environ["TALKDAT_TEST_UI_SCALE"])
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        cls._home = tempfile.TemporaryDirectory(prefix="talkdat-settings-layout-")
        os.environ["TALK_DAT_HOME"] = cls._home.name

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        config = load_config()
        ui = config.setdefault("ui", {})
        ui["scale"] = cls.scale
        ui["reduce_motion"] = True
        ui["settings_theme"] = "Flow Dark"
        ui["theme"] = "dark"
        cls.overlay = Overlay(config, callbacks={})
        pump(cls.overlay.root, 0.2)
        constrained = (0, 0, 1366, 768) if cls.scale == 2.0 else None
        if constrained is None:
            cls.overlay.open_settings()
            pump(cls.overlay.root, 0.85)
        else:
            # A high-DPI layout that only passes on the founder's ultrawide is
            # not responsive. Build the real Settings window against the common
            # 1366x768/200% work area that exposed the single-row footer clip.
            with mock.patch.object(
                cls.overlay,
                "_pill_monitor_work_area",
                return_value=constrained,
            ):
                cls.overlay.open_settings()
                pump(cls.overlay.root, 0.85)
        cls.window = cls.overlay.utility_windows["settings"]

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
        cls._home.cleanup()

    def tearDown(self) -> None:
        active = getattr(self.window, "_talkdat_active_tooltip", {})
        tip = active.get("window") if isinstance(active, dict) else None
        if tip is not None:
            try:
                tip.destroy()
            except Exception:
                pass
            active["window"] = None
            active["owner"] = None
            active["interaction"] = None
        pump(self.overlay.root, 0.04)

    def _footer_parts(self):
        footer_labels = [
            widget
            for widget in descendants(self.window)
            if isinstance(widget, ttk.Label)
            and str(widget.cget("style")) in FOOTER_LABEL_STYLES
        ]
        self.assertEqual(
            len(footer_labels),
            2,
            "Settings must expose one status icon and one status message",
        )
        status_label = next(widget for widget in footer_labels if str(widget.cget("textvariable")))
        status_icon = next(widget for widget in footer_labels if widget is not status_label)
        status_row = status_label.master
        button_row = status_row.master
        footer_actions = next(
            child
            for child in button_row.winfo_children()
            if child is not status_row and isinstance(child, tk.Frame)
        )
        actions = [
            child
            for child in descendants(footer_actions)
            if isinstance(child, ttk.Button)
        ]
        return status_label, status_icon, status_row, button_row, footer_actions, actions

    def test_long_save_warning_wraps_above_contained_footer_actions(self) -> None:
        (
            status_label,
            status_icon,
            status_row,
            button_row,
            footer_actions,
            actions,
        ) = self._footer_parts()

        button_row._talkdat_set_save_status(WARNING_COPY, "warning")  # type: ignore[attr-defined]
        pump(self.overlay.root, 0.18)

        self.assertEqual(self.window.getvar(str(status_label.cget("textvariable"))), WARNING_COPY)
        self.assertEqual(str(status_label.cget("style")), "Flow.FooterWarning.TLabel")
        self.assertEqual(str(status_icon.cget("text")), "")
        self.assertTrue(str(status_icon.cget("image")))
        self.assertEqual(status_icon._talkdat_icon_name, "warning")  # type: ignore[attr-defined]
        self.assertEqual(int(status_row.grid_info()["row"]), 0)
        self.assertEqual(int(footer_actions.grid_info()["row"]), 1)
        self.assertTrue(status_row.winfo_ismapped())
        self.assertTrue(footer_actions.winfo_ismapped())
        self.assertGreater(int(status_label.cget("wraplength")), 0)
        self.assertLessEqual(int(status_label.cget("wraplength")), int(status_row.winfo_width()))

        style_font = ttk.Style(self.window).lookup("Flow.FooterWarning.TLabel", "font")
        line_height = tkfont.Font(root=self.window, font=style_font).metrics("linespace")
        self.assertGreater(
            int(status_label.winfo_height()),
            int(line_height),
            "the representative warning stayed on one overflowing line instead of wrapping",
        )
        assert_widget_inside(self, status_label, status_row, "wrapped warning escaped its status row")
        assert_widget_inside(self, status_icon, status_row, "warning icon escaped its status row")
        assert_widget_inside(self, status_row, button_row, "status row escaped the Settings footer")
        assert_widget_inside(self, footer_actions, button_row, "action row escaped the Settings footer")
        self.assertLessEqual(
            int(status_row.winfo_rooty()) + int(status_row.winfo_height()),
            int(footer_actions.winfo_rooty()),
            "status copy and footer buttons occupy the same visual row",
        )

        self.assertEqual(
            {str(button.cget("text")) for button in actions},
            {"Save", "Status", "History", "Scratchpad", "Close", "Start over..."},
        )
        for button in actions:
            with self.subTest(button=str(button.cget("text"))):
                self.assertTrue(button.winfo_ismapped())
                assert_widget_inside(self, button, footer_actions, "footer action escaped its action row")
                assert_widget_inside(self, button, self.window, "footer action escaped Settings")

    def test_status_semantics_never_call_dirty_or_invalid_input_ok(self) -> None:
        (
            status_label,
            status_icon,
            _status_row,
            button_row,
            _footer_actions,
            actions,
        ) = self._footer_parts()
        setter = button_row._talkdat_set_save_status  # type: ignore[attr-defined]
        cases = (
            ("neutral", "Flow.Footer.TLabel", None),
            ("saving", "Flow.FooterSaving.TLabel", "restart"),
            ("success", "Flow.FooterSuccess.TLabel", "success"),
            ("warning", "Flow.FooterWarning.TLabel", "warning"),
            ("error", "Flow.FooterError.TLabel", "warning"),
        )
        for kind, expected_style, expected_icon_name in cases:
            with self.subTest(kind=kind):
                setter(f"Representative {kind} status", kind)
                pump(self.overlay.root, 0.03)
                self.assertEqual(str(status_label.cget("style")), expected_style)
                self.assertEqual(str(status_icon.cget("text")), "")
                self.assertEqual(
                    status_icon._talkdat_icon_name,  # type: ignore[attr-defined]
                    expected_icon_name,
                )
                self.assertEqual(bool(str(status_icon.cget("image"))), expected_icon_name is not None)

        replacement_label = next(
            widget
            for widget in descendants(self.window)
            if isinstance(widget, ttk.Label)
            and str(widget.cget("text")) == "Replacements JSON"
        )
        replacements = next(
            widget
            for widget in replacement_label.master.winfo_children()
            if isinstance(widget, tk.Text)
            and int(widget.grid_info().get("row", -1)) == 0
            and int(widget.grid_info().get("column", -1)) == 1
        )
        original = replacements.get("1.0", "end-1c")
        replacements.delete("1.0", "end")
        replacements.insert("1.0", "{")
        pump(self.overlay.root, 0.12)
        self.assertEqual(
            button_row._talkdat_save_status_kind.get(),  # type: ignore[attr-defined]
            "saving",
        )
        self.assertEqual(status_icon._talkdat_icon_name, "restart")  # type: ignore[attr-defined]

        save_button = next(button for button in actions if str(button.cget("text")) == "Save")
        save_button.invoke()
        pump(self.overlay.root, 0.08)
        self.assertEqual(
            button_row._talkdat_save_status_kind.get(),  # type: ignore[attr-defined]
            "error",
        )
        self.assertEqual(str(status_label.cget("style")), "Flow.FooterError.TLabel")
        self.assertEqual(status_icon._talkdat_icon_name, "warning")  # type: ignore[attr-defined]

        replacements.delete("1.0", "end")
        replacements.insert("1.0", original)
        pump(self.overlay.root, 0.08)
        save_button.invoke()
        pump(self.overlay.root, 0.08)
        self.assertIn(
            button_row._talkdat_save_status_kind.get(),  # type: ignore[attr-defined]
            {"success", "warning"},
        )

    def test_constrained_two_x_footer_uses_two_rows_without_clipping(self) -> None:
        if self.scale != 2.0:
            self.skipTest("the 1366x768 constrained footer proof is specific to 2x DPI")
        (
            _status_label,
            _status_icon,
            status_row,
            button_row,
            footer_actions,
            actions,
        ) = self._footer_parts()
        pump(self.overlay.root, 0.12)

        self.assertLessEqual(self.window.winfo_width(), 1334)
        workflow = footer_actions._talkdat_workflow_actions  # type: ignore[attr-defined]
        window_actions = footer_actions._talkdat_window_actions  # type: ignore[attr-defined]
        # The fold is a function of the font, not the platform: the two groups
        # share a row only while both fit (Aqua's narrower system face can).
        required = (
            workflow.winfo_reqwidth()
            + window_actions.winfo_reqwidth()
            + ui_scale.px(24, self.overlay.config)
        )
        expected_mode = "two-row" if footer_actions.winfo_width() < required else "one-row"
        self.assertEqual(
            footer_actions._talkdat_layout_mode,  # type: ignore[attr-defined]
            expected_mode,
        )
        self.assertEqual(int(workflow.grid_info()["row"]), 0)
        if expected_mode == "two-row":
            self.assertEqual(int(window_actions.grid_info()["row"]), 1)
            self.assertLessEqual(
                workflow.winfo_rooty() + workflow.winfo_height(),
                window_actions.winfo_rooty(),
            )
        else:
            self.assertEqual(int(window_actions.grid_info()["row"]), 0)
        assert_widget_inside(self, status_row, button_row, "status row escaped constrained footer")
        assert_widget_inside(self, footer_actions, button_row, "action rows escaped constrained footer")
        self.assertEqual(len(actions), 6)
        for button in actions:
            with self.subTest(button=str(button.cget("text"))):
                self.assertTrue(button.winfo_ismapped())
                self.assertEqual(str(button.cget("takefocus")), "1")
                assert_widget_inside(self, button, footer_actions, "constrained action clipped")
                assert_widget_inside(self, button, self.window, "constrained action escaped Settings")

    def test_tiny_two_x_tooltip_scrolls_and_escape_only_dismisses_help(self) -> None:
        if self.scale != 2.0:
            self.skipTest("the constrained tooltip contract is specifically a 2x-DPI proof")
        if mac_support.IS_MAC:
            # Point-size fonts follow Tk's own DPI scaling, which a config scale of
            # 2.0 does not touch on macOS, so the 480x320 overflow this proves never
            # occurs there; the metrics are Windows DPI-awareness metrics.
            self.skipTest("the 480x320 2x overflow proof is calibrated to Windows DPI font scaling")

        owner = next(
            widget
            for widget in descendants(self.window)
            if isinstance(widget, ttk.Checkbutton)
            and str(widget.cget("text")) == LONG_HELP_LABEL
        )
        self.assertTrue(owner.bind("<Enter>"), "the long-help control has no help binding")

        work_area = (0, 0, 480, 320)
        callbacks: dict[tuple[int, str], object] = {}
        original_bind = tk.Misc.bind

        def capture_bind(widget, sequence=None, func=None, add=None):
            if sequence and callable(func):
                callbacks[(id(widget), str(sequence))] = func
            return original_bind(widget, sequence, func, add)

        with (
            mock.patch.object(
                self.overlay,
                "_window_monitor_work_area",
                return_value=work_area,
            ),
            mock.patch.object(tk.Misc, "bind", new=capture_bind),
        ):
            owner.event_generate("<Enter>")
            pump(self.overlay.root, 0.18)

        active = self.window._talkdat_active_tooltip  # type: ignore[attr-defined]
        tip = active.get("window")
        self.assertIsNotNone(tip, "the Settings help binding did not create its surface")
        self.assertTrue(tip.winfo_exists())
        self.assertTrue(bool(tip._talkdat_tooltip_scroll_mode))  # type: ignore[attr-defined]
        body_canvas = tip._talkdat_tooltip_body  # type: ignore[attr-defined]
        scrollbar = tip._talkdat_tooltip_scrollbar  # type: ignore[attr-defined]
        self.assertIsNotNone(scrollbar)
        self.assertIs(active.get("scroll_canvas"), body_canvas)
        self.assertTrue(scrollbar.winfo_ismapped())
        self.assertTrue(body_canvas.winfo_ismapped())

        left, top, right, bottom = work_area
        self.assertGreaterEqual(tip.winfo_rootx(), left + 16)
        self.assertGreaterEqual(tip.winfo_rooty(), top + 16)
        self.assertLessEqual(tip.winfo_rootx() + tip.winfo_width(), right - 16)
        self.assertLessEqual(tip.winfo_rooty() + tip.winfo_height(), bottom - 16)

        assert_widget_inside(self, body_canvas, tip, "scroll viewport escaped the tooltip")
        assert_widget_inside(self, scrollbar, tip, "scrollbar escaped the tooltip")
        surface = next(
            child for child in tip.winfo_children()
            if isinstance(child, tk.Canvas)
        )
        for item in surface.find_all():
            bbox = surface.bbox(item)
            if bbox is None:
                continue
            with self.subTest(canvas_item=item):
                self.assertGreaterEqual(bbox[0], 0)
                self.assertGreaterEqual(bbox[1], 0)
                self.assertLessEqual(bbox[2], surface.winfo_width())
                self.assertLessEqual(bbox[3], surface.winfo_height())

        initial_view = tuple(float(value) for value in body_canvas.yview())
        self.assertLess(initial_view[1], 0.99, "the help copy did not actually overflow the viewport")
        end = callbacks[(id(body_canvas), "<End>")]
        self.assertEqual(end(None), "break")
        pump(self.overlay.root, 0.08)
        final_view = tuple(float(value) for value in body_canvas.yview())
        self.assertGreater(final_view[0], initial_view[0])
        self.assertGreaterEqual(final_view[1], 0.99, "End did not reach the last line of help")

        escape = callbacks[(id(tip), "<Escape>")]
        self.assertEqual(escape(None), "break")
        pump(self.overlay.root, 0.08)
        self.assertFalse(bool(tip.winfo_exists()), "Escape left the pinned tooltip alive")
        self.assertTrue(bool(self.window.winfo_exists()), "Escape dismissed Settings with its tooltip")
        self.assertIs(self.overlay.utility_windows.get("settings"), self.window)


if __name__ == "__main__":
    unittest.main()
