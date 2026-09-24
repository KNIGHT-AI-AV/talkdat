"""Real-window checks for utility content at its smallest supported size.

This module is launched in a clean interpreter by
``tests.test_utility_minimum_layout``.  Tk keeps process-global image state, so
isolating these assertions avoids stale-image failures while still measuring
real mapped widgets and real canvas viewports.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests import gui_offscreen  # noqa: F401  (never map on a human display)

import tkinter as tk
from tkinter import ttk

from knight_flow import ui_scale
from knight_flow.config import config_path, load_config
from knight_flow.overlay import Overlay


def pump(root: tk.Misc, seconds: float = 0.25) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


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


def button(window: tk.Misc, label: str) -> ttk.Button:
    matches = [
        widget for widget in descendants(window)
        if isinstance(widget, ttk.Button) and widget_text(widget) == label
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {label!r} button, found {len(matches)}")
    return matches[0]


def scroll_canvas(window: tk.Misc) -> tk.Canvas:
    matches = [
        widget for widget in descendants(window)
        if isinstance(widget, tk.Canvas)
        and str(widget.cget("yscrollcommand"))
        and str(widget.bind("<End>"))
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one scrolling canvas, found {len(matches)}")
    return matches[0]


def set_exact_size(root: tk.Misc, window: tk.Toplevel, width: int, height: int) -> None:
    window.geometry(f"{width}x{height}")
    pump(root, 0.25)
    window.update_idletasks()


def midpoint_is_in_view(widget: tk.Misc, viewport: tk.Misc) -> bool:
    widget_midpoint = widget.winfo_rooty() + (widget.winfo_height() / 2)
    viewport_top = viewport.winfo_rooty()
    viewport_bottom = viewport_top + viewport.winfo_height()
    return viewport_top <= widget_midpoint <= viewport_bottom


def fits_horizontally(widget: tk.Misc, viewport: tk.Misc) -> bool:
    widget_left = widget.winfo_rootx()
    widget_right = widget_left + widget.winfo_width()
    viewport_left = viewport.winfo_rootx()
    viewport_right = viewport_left + viewport.winfo_width()
    return viewport_left <= widget_left and widget_right <= viewport_right


class _FakeInputStream:
    def __init__(self) -> None:
        self.entered = False
        self.closed = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_args) -> None:
        self.closed = True


class UtilityMinimumLayoutRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.previous_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = tempfile.mkdtemp(prefix="talkdat-utility-minimum-")
        config = load_config()
        config.setdefault("ui", {})["settings_theme"] = "Flow Light"
        cls.events: list[str] = []
        cls.overlay = Overlay(
            config=config,
            callbacks={
                "status_provider": lambda: {
                    f"diagnostic_{index:02d}": "A deliberately long value " * 4
                    for index in range(36)
                },
                "check_updates": lambda: cls.events.append("updates"),
                "panic": lambda: cls.events.append("panic"),
                "save_settings": lambda: cls.events.append("saved"),
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
        self.events.clear()

    def tearDown(self) -> None:
        self._close_utilities()

    def _close_utilities(self) -> None:
        windows = []
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

    def assert_mapped(self, window: tk.Misc, *labels: str) -> None:
        for label in labels:
            with self.subTest(control=label):
                control = button(window, label)
                self.assertTrue(control.winfo_ismapped(), f"{label!r} exists but has no visible pixels")
                self.assertGreater(control.winfo_width(), 1)
                self.assertGreater(control.winfo_height(), 1)

    def assert_keyboard_scrolls_to_end(self, canvas: tk.Canvas) -> None:
        canvas.update_idletasks()
        scrollbars = [
            widget for widget in canvas.master.winfo_children()
            if isinstance(widget, ttk.Scrollbar)
        ]
        self.assertEqual(len(scrollbars), 1)
        self.assertEqual(str(scrollbars[0].cget("style")), "Flow.Vertical.TScrollbar")
        before = canvas.yview()
        self.assertLess(before[1], 1.0, "test content does not overflow, so reachability is unproven")
        canvas.focus_force()
        canvas.event_generate("<End>")
        pump(self.overlay.root, 0.15)
        after = canvas.yview()
        self.assertGreater(after[0], before[0], "End did not move the focused scroll region")
        self.assertAlmostEqual(after[1], 1.0, places=2)
        canvas.event_generate("<Home>")
        pump(self.overlay.root, 0.1)
        self.assertAlmostEqual(canvas.yview()[0], 0.0, places=2)

    def test_status_keeps_every_action_mapped_at_620_by_460(self) -> None:
        self.overlay.open_status()
        window = self.overlay.utility_windows["status"]
        set_exact_size(self.overlay.root, window, 620, 460)
        self.assert_mapped(window, "Refresh", "Check updates", "Panic stop", "Close")

        diagnostic = next(widget for widget in descendants(window) if isinstance(widget, tk.Text))
        scrollbar = next(widget for widget in descendants(window) if isinstance(widget, ttk.Scrollbar))
        self.assertTrue(diagnostic.winfo_ismapped())
        self.assertTrue(scrollbar.winfo_ismapped())
        before = diagnostic.yview()
        self.assertLess(before[1], 1.0)
        diagnostic.focus_force()
        diagnostic.event_generate("<End>")
        pump(self.overlay.root, 0.12)
        self.assertGreater(diagnostic.yview()[0], before[0])

        button(window, "Check updates").invoke()
        button(window, "Panic stop").invoke()
        self.assertEqual(self.events, ["updates", "panic"])

    def test_resized_window_receipt_reaches_disk_before_close(self) -> None:
        self.overlay.open_stats()
        window = self.overlay.utility_windows["stats"]
        target_width, target_height = 744, 516
        set_exact_size(self.overlay.root, window, target_width, target_height)
        window.event_generate("<<TalkDATGeometrySettled>>", when="tail")
        pump(self.overlay.root, 0.12)

        window.destroy()
        pump(self.overlay.root, 0.12)

        import json

        persisted = json.loads(Path(config_path()).read_text(encoding="utf-8-sig"))
        receipt = persisted["ui"]["window_sizes"]["stats"]
        self.assertEqual(receipt.get("units"), "logical-px-v1")
        current_scale = ui_scale.scale(self.overlay.config)
        self.assertAlmostEqual(receipt["width"], target_width / current_scale, delta=2)
        self.assertAlmostEqual(receipt["height"], target_height / current_scale, delta=2)
        self.assertEqual(
            ui_scale.restore_window_size(receipt, {"ui": {"scale": 2.0}}),
            (ui_scale.px(receipt["width"], {"ui": {"scale": 2.0}}),
             ui_scale.px(receipt["height"], {"ui": {"scale": 2.0}})),
        )

    def test_no_automatic_input_and_reachable_device_controls(self):
        with patch('knight_flow.audio_input.list_input_devices',return_value=['7: Studio microphone']),patch('knight_flow.audio_input.open_raw_input_stream') as opened:
            self.overlay.open_mic_doctor();window=self.overlay.utility_windows['mic_doctor']
            set_exact_size(self.overlay.root,window,460,380);pump(self.overlay.root,.4)
            self.assert_mapped(window,'Check my mic','Stop','Close')
            canvas=scroll_canvas(window);self.assert_keyboard_scrolls_to_end(canvas)
            canvas.yview_moveto(1);pump(self.overlay.root,.1)
            self.assertTrue(midpoint_is_in_view(button(window,'Refresh list'),canvas))
            opened.assert_not_called();window.destroy();pump(self.overlay.root,.1)
            opened.assert_not_called()
    def test_closing_cancels_owned_capture_and_ignores_late_report(self):
        reports=[];state={'active':True,'phase':'listening','level':.2,'message':'Listening'}
        stopper=Mock(side_effect=lambda:state.update(active=False,phase='cancelled',level=0,message='Stopped'))
        capture=SimpleNamespace(snapshot=lambda:state,stop=stopper)
        def begin(callback):reports.append(callback);return capture
        self.overlay.callbacks['mic_doctor_run']=begin
        try:
            with patch('knight_flow.audio_input.list_input_devices',return_value=['7: Studio microphone']),patch('knight_flow.audio_input.open_raw_input_stream') as opened:
                self.overlay.open_mic_doctor();window=self.overlay.utility_windows['mic_doctor'];pump(self.overlay.root,.1)
                button(window,'Check my mic').invoke();pump(self.overlay.root,.15)
                self.assertEqual(str(button(window,'Check my mic').cget('state')),'disabled')
                self.assertEqual(len(reports),1);window.destroy();pump(self.overlay.root,.15)
                self.assertTrue(stopper.called)
                reports[0](SimpleNamespace(verdict='ok',advice='Late',speech_rms=.1,noise_floor=.01,snr_db=20,clipping_ratio=0))
                pump(self.overlay.root,.1);opened.assert_not_called()
        finally:self.overlay.callbacks.pop('mic_doctor_run',None)
    def test_explicit_stop_keeps_controls_busy_until_driver_is_closed(self):
        inputs=patch('knight_flow.audio_input.list_input_devices',return_value=['7: Studio microphone'])
        inputs.start();self.addCleanup(inputs.stop)
        state={'active':True,'phase':'listening','level':.2,'message':'Listening'}
        stopper=Mock(side_effect=lambda:state.update(phase='closing',message='Closing'))
        capture=SimpleNamespace(snapshot=lambda:state,stop=stopper)
        self.overlay.callbacks['mic_doctor_run']=lambda callback:capture
        try:
            self.overlay.open_mic_doctor();window=self.overlay.utility_windows['mic_doctor'];pump(self.overlay.root,.1)
            button(window,'Check my mic').invoke();pump(self.overlay.root,.1);button(window,'Stop').invoke();pump(self.overlay.root,.1)
            stopper.assert_called_once();self.assertEqual(str(button(window,'Check my mic').cget('state')),'disabled')
            state.update(active=False,phase='cancelled',message='Stopped');pump(self.overlay.root,.15)
            self.assertEqual(str(button(window,'Check my mic').cget('state')),'normal')
            window.destroy();pump(self.overlay.root,.1)
        finally:self.overlay.callbacks.pop('mic_doctor_run',None)

    def test_removing_the_meter_page_cancels_capture_without_a_stale_timer(self):
        stopper=Mock();errors=[]
        capture=SimpleNamespace(snapshot=lambda:{'active':True,'phase':'listening','level':.2,'message':'Listening'},stop=stopper)
        self.overlay.callbacks['mic_doctor_run']=lambda callback:capture
        old_report=self.overlay.root.report_callback_exception
        self.overlay.root.report_callback_exception=lambda *error:errors.append(error)
        try:
            with patch('knight_flow.audio_input.list_input_devices',return_value=[]):
                self.overlay.open_mic_doctor();window=self.overlay.utility_windows['mic_doctor'];pump(self.overlay.root,.1)
                button(window,'Check my mic').invoke();pump(self.overlay.root,.1)
                scroll_canvas(window).destroy();pump(self.overlay.root,.2)
                self.assertTrue(stopper.called,'Removing the page leaves its microphone running')
                self.assertEqual(errors,[])
                window.destroy();pump(self.overlay.root,.1)
        finally:
            self.overlay.callbacks.pop('mic_doctor_run',None)
            self.overlay.root.report_callback_exception=old_report

    def test_feedback_pins_actions_and_keeps_every_field_keyboard_reachable(self) -> None:
        self.overlay.open_feedback_form("feature")
        window = self.overlay.utility_windows["feedback_feature"]
        set_exact_size(self.overlay.root, window, 480, 320)
        self.assert_mapped(window, "Send to the team", "Close")
        canvas = scroll_canvas(window)
        # At this exact height the improved compact form can fit without a
        # scroll journey.  Prove keyboard reachability in both valid states:
        # End must land at the bottom when content overflows, while a fitting
        # form must already expose its final field.
        if canvas.yview()[1] < 0.999:
            self.assert_keyboard_scrolls_to_end(canvas)
        else:
            self.assertTrue(str(canvas.bind("<End>")))
            scrollbar = next(
                widget for widget in canvas.master.winfo_children()
                if isinstance(widget, ttk.Scrollbar)
            )
            self.assertEqual(str(scrollbar.cget("style")), "Flow.Vertical.TScrollbar")
        canvas.yview_moveto(1.0)
        pump(self.overlay.root, 0.1)

        reply_label = next(widget for widget in descendants(window) if widget_text(widget) == "Reply email (optional)")
        self.assertTrue(reply_label.winfo_ismapped())
        self.assertTrue(midpoint_is_in_view(reply_label, canvas), "reply field cannot be reached at the scroll end")
        entries = [widget for widget in descendants(window) if isinstance(widget, ttk.Entry)]
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(widget.winfo_ismapped() for widget in entries))

    def test_finish_chooser_stacks_narrow_and_restores_two_columns_when_wide(self) -> None:
        paragraph = " ".join(["Production review, gym, photo shoot, edit notes, and tomorrow's call."] * 9)
        self.overlay.open_finish_chooser(paragraph, paragraph.upper())
        window = self.overlay.utility_windows["finish_chooser"]
        set_exact_size(self.overlay.root, window, 480, 320)
        pump(self.overlay.root, 0.2)

        chill = button(window, "Use Chill")
        executive = button(window, "Use Executive")
        chill_card = chill.master
        executive_card = executive.master
        self.assertEqual(chill_card.grid_info()["column"], 0)
        self.assertEqual(executive_card.grid_info()["column"], 0)
        self.assertGreater(int(executive_card.grid_info()["row"]), int(chill_card.grid_info()["row"]))

        preview_boxes = [
            widget for widget in descendants(window)
            if isinstance(widget, tk.Text) and str(widget.cget("state")) == "disabled"
        ]
        self.assertEqual(len(preview_boxes), 2)
        for preview in preview_boxes:
            with self.subTest(preview=str(preview)):
                preview.update_idletasks()
                self.assertLess(preview.yview()[1], 1.0)
                preview_scrollbar = next(
                    widget for widget in preview.master.winfo_children()
                    if isinstance(widget, ttk.Scrollbar)
                )
                self.assertTrue(preview_scrollbar.winfo_ismapped())
                preview.yview_moveto(1.0)
                pump(self.overlay.root, 0.08)
                self.assertAlmostEqual(preview.yview()[1], 1.0, places=2)

        canvas = scroll_canvas(window)
        self.assert_keyboard_scrolls_to_end(canvas)
        canvas.yview_moveto(1.0)
        pump(self.overlay.root, 0.1)
        self.assertTrue(midpoint_is_in_view(executive, canvas), "Executive choice is not reachable at narrow width")

        set_exact_size(self.overlay.root, window, 760, 460)
        pump(self.overlay.root, 0.2)
        self.assertEqual(chill_card.grid_info()["row"], executive_card.grid_info()["row"])
        self.assertNotEqual(chill_card.grid_info()["column"], executive_card.grid_info()["column"])

    def test_stats_pins_actions_and_scrolls_to_the_last_metric(self) -> None:
        unknown_rate = {
            "is_cloud": True,
            "provider": "Preview speech provider",
            "model": "model-without-a-published-rate",
            "total_minutes": 12.5,
            "minutes_per_active_day": 3.25,
            "estimated_monthly_cost": None,
            "rate_per_minute": None,
        }
        with patch("knight_flow.overlay.usage_summary", return_value=unknown_rate):
            self.overlay.open_stats()
            window = self.overlay.utility_windows["stats"]
            set_exact_size(self.overlay.root, window, 460, 360)
            self.assert_mapped(window, "Refresh", "Close")
            canvas = scroll_canvas(window)
            self.assert_keyboard_scrolls_to_end(canvas)

            last_metric = next(
                widget for widget in descendants(window)
                if widget_text(widget) == "Projection excludes"
            )
            long_value = next(
                widget for widget in descendants(window)
                if widget_text(widget) == "Writing-model costs"
            )
            canvas.yview_moveto(1.0)
            pump(self.overlay.root, 0.15)
            self.assertTrue(midpoint_is_in_view(last_metric, canvas), "last Stats metric is not reachable at End")
            self.assertTrue(midpoint_is_in_view(long_value, canvas), "last Stats value is not reachable at End")
            self.assertTrue(fits_horizontally(long_value, canvas), "long Stats value is still horizontally clipped")
            self.assertGreater(int(long_value.cget("wraplength")), 0)
            self.assertEqual(str(long_value.cget("anchor")), "w")

            button(window, "Refresh").invoke()
            pump(self.overlay.root, 0.1)
            self.assertTrue(any(widget_text(widget) == "Saved words" for widget in descendants(window)))
            self.assertTrue(any(widget_text(widget) == "- (no published rate for this model)" for widget in descendants(window)))

    def test_history_gives_a_long_storage_path_its_own_wrapped_line(self) -> None:
        long_path = Path(
            "C:/Users/Example/Documents/An exceptionally long redirected Talk DAT profile/"
            "Protected workspace/History archive/Full dictation history/history.jsonl"
        )
        with patch("knight_flow.overlay.full_history_path", return_value=long_path):
            self.overlay.open_history()
            window = self.overlay.utility_windows["history"]
            set_exact_size(self.overlay.root, window, 900, 640)
            title = next(widget for widget in descendants(window) if widget_text(widget) == "Full dictation history")
            path_label = next(widget for widget in descendants(window) if widget_text(widget) == str(long_path))
            header = title.master

            self.assertGreaterEqual(
                path_label.winfo_rooty(),
                title.winfo_rooty() + title.winfo_height() + 2,
                "History path still collides with its heading",
            )
            self.assertTrue(fits_horizontally(path_label, header), "History path line escapes its header width")
            self.assertGreater(int(path_label.cget("wraplength")), 0)
            self.assertLessEqual(path_label.winfo_reqwidth(), header.winfo_width() + 1)
            self.assert_mapped(window, "Copy all", "Pin last", "Refresh", "Close", "Export and clear...")
            more = button(window, "Export and clear...")
            clock = next(
                widget for widget in descendants(window)
                if isinstance(widget, ttk.Checkbutton) and widget_text(widget) == "24-hour time"
            )
            window_bottom = window.winfo_rooty() + window.winfo_height()
            for control in (more, clock):
                self.assertGreaterEqual(control.winfo_height(), 24, f"{widget_text(control)} collapsed vertically")
                self.assertLessEqual(
                    control.winfo_rooty() + control.winfo_height(),
                    window_bottom,
                    f"{widget_text(control)} escaped below the History window",
                )


if __name__ == "__main__":
    unittest.main()
