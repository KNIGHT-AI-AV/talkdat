"""Real-Tk lifecycle checks for the bounded utility popover singletons."""

from __future__ import annotations

from knight_flow.flat_button import FlatButton  # tk.Button off macOS; a styled Label on Aqua

import contextlib
import os
import tempfile
import time
import unittest
from unittest import mock

from tests import gui_offscreen  # noqa: F401

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
        time.sleep(0.005)


def descendants(widget: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    stack = list(widget.winfo_children())
    while stack:
        child = stack.pop()
        found.append(child)
        with contextlib.suppress(tk.TclError):
            stack.extend(child.winfo_children())
    return found


def live_toplevel_paths(widget: tk.Misc) -> set[str]:
    """Return the stable Tcl paths of every live child Toplevel."""

    return {
        str(child)
        for child in descendants(widget)
        if isinstance(child, tk.Toplevel) and bool(child.winfo_exists())
    }


@unittest.skipIf(tk is None, "tkinter unavailable")
class PopupLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = tempfile.mkdtemp(prefix="talkdat-popup-life-")
        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        cls.overlay = Overlay(load_config(), callbacks={})
        pump(cls.overlay.root, 0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        with contextlib.suppress(Exception):
            cls.overlay.root.destroy()
        with contextlib.suppress(Exception):
            tk._default_root = None  # type: ignore[attr-defined]
        if cls._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = cls._previous_home

    def setUp(self) -> None:
        for child in tuple(self.overlay.root.winfo_children()):
            if isinstance(child, tk.Toplevel):
                with contextlib.suppress(Exception):
                    child.destroy()
        self.overlay.utility_windows.clear()
        self.overlay._shell_window = None
        self.overlay._theme_picker = None
        self.overlay.config.setdefault("ui", {})["reduce_motion"] = False
        # Keep every real-Tk surface transparent. The product presentation
        # helpers intentionally raise alpha after gui_offscreen's constructor
        # patch, which is correct in production but would flash test windows.
        popup_present = mock.patch.object(
            self.overlay, "_schedule_popup_present", return_value=None
        )
        utility_present = mock.patch.object(
            self.overlay, "_schedule_utility_present", return_value=None
        )
        popup_present.start()
        utility_present.start()
        self.addCleanup(popup_present.stop)
        self.addCleanup(utility_present.stop)
        pump(self.overlay.root, 0.08)

    def _host(self) -> tk.Toplevel:
        host = tk.Toplevel(self.overlay.root)
        host.geometry("700x500+-30000+-30000")
        tk.Frame(host, width=700, height=500).pack(fill="both", expand=True)
        host.update_idletasks()
        return host

    def test_theme_choice_applies_only_after_its_picker_retires(self) -> None:
        host = self._host()
        anchor = tk.Button(host, text="Theme")
        anchor.place(x=20, y=20, width=100, height=36)
        variable = tk.StringVar(master=host, value="Flow Dark")
        writes: list[str] = []
        variable.trace_add("write", lambda *_args: writes.append(variable.get()))

        self.overlay._open_theme_picker(anchor, variable)
        popup = self.overlay._theme_picker
        self.assertIsNotNone(popup)
        choice = next(
            button
            for button in descendants(popup)
            if isinstance(button, (tk.Button, FlatButton))
            and str(button.cget("text")) not in {"", "Flow Dark"}
        )
        chosen = str(choice.cget("text"))
        choice.invoke()

        self.assertEqual(variable.get(), "Flow Dark")
        self.assertTrue(popup.winfo_exists())
        pump(self.overlay.root, 0.22)
        self.assertEqual(variable.get(), chosen)
        self.assertEqual(writes, [chosen])
        self.assertIsNone(self.overlay._theme_picker)
        self.assertFalse(popup.winfo_exists())

        # A non-helper destruction still clears only the pointer it owns.
        self.overlay._open_theme_picker(anchor, variable)
        replacement = self.overlay._theme_picker
        replacement.destroy()
        pump(self.overlay.root, 0.03)
        self.assertIsNone(self.overlay._theme_picker)

    def test_theme_choice_is_exact_and_immediate_with_reduced_motion(self) -> None:
        self.overlay.config.setdefault("ui", {})["reduce_motion"] = True
        host = self._host()
        anchor = tk.Button(host, text="Theme")
        anchor.pack()
        variable = tk.StringVar(master=host, value="Flow Dark")
        writes: list[str] = []
        variable.trace_add("write", lambda *_args: writes.append(variable.get()))

        self.overlay._open_theme_picker(anchor, variable)
        popup = self.overlay._theme_picker
        choice = next(
            button
            for button in descendants(popup)
            if isinstance(button, (tk.Button, FlatButton))
            and str(button.cget("text")) not in {"", "Flow Dark"}
        )
        chosen = str(choice.cget("text"))
        choice.invoke()

        self.assertEqual(variable.get(), chosen)
        self.assertEqual(writes, [chosen])
        self.assertIsNone(self.overlay._theme_picker)
        self.assertFalse(popup.winfo_exists())

    def test_theme_picker_construction_failure_leaves_no_owned_popup(self) -> None:
        host = self._host()
        anchor = tk.Button(host, text="Theme")
        anchor.pack()
        variable = tk.StringVar(master=host, value="Flow Dark")
        before = live_toplevel_paths(self.overlay.root)

        with (
            mock.patch(
                "knight_flow.overlay.tk.Canvas",
                side_effect=tk.TclError("forced canvas failure"),
            ),
            mock.patch("knight_flow.overlay.log.warning"),
        ):
            self.overlay._open_theme_picker(anchor, variable)

        pump(self.overlay.root, 0.03)
        self.assertIsNone(self.overlay._theme_picker)
        self.assertEqual(live_toplevel_paths(self.overlay.root), before)
        self.assertEqual(variable.get(), "Flow Dark")

    def test_theme_choice_stays_exact_if_its_fade_is_interrupted(self) -> None:
        host = self._host()
        anchor = tk.Button(host, text="Theme")
        anchor.pack()
        variable = tk.StringVar(master=host, value="Flow Dark")
        writes: list[str] = []
        variable.trace_add("write", lambda *_args: writes.append(variable.get()))

        self.overlay._open_theme_picker(anchor, variable)
        popup = self.overlay._theme_picker
        choice = next(
            button
            for button in descendants(popup)
            if isinstance(button, (tk.Button, FlatButton))
            and str(button.cget("text")) not in {"", "Flow Dark"}
        )
        chosen = str(choice.cget("text"))
        choice.invoke()
        choice.invoke()
        self.assertEqual(writes, [])

        # A host teardown can destroy the popup before its alpha tween ends.
        # The shared completion must still apply once, never zero or twice.
        popup.destroy()
        pump(self.overlay.root, 0.04)
        self.assertEqual(variable.get(), chosen)
        self.assertEqual(writes, [chosen])
        self.assertIsNone(self.overlay._theme_picker)

    def test_history_more_is_one_popup_per_history_window(self) -> None:
        self.overlay.open_history()
        pump(self.overlay.root, 0.65)
        window = self.overlay.utility_windows["history"]
        more = next(
            button
            for button in descendants(window)
            if isinstance(button, ttk.Button)
            and str(button.cget("text")) == "Export and clear..."
        )

        more.invoke()
        first = window._history_more_popup  # type: ignore[attr-defined]
        more.invoke()
        self.assertIs(window._history_more_popup, first)  # type: ignore[attr-defined]
        with mock.patch.object(
            first,
            "focus_force",
            side_effect=tk.TclError("forced focus refusal"),
        ):
            more.invoke()
        self.assertIs(window._history_more_popup, first)  # type: ignore[attr-defined]
        owned = [
            child
            for child in descendants(window)
            if isinstance(child, tk.Toplevel)
            and child.winfo_exists()
            and any(
                isinstance(control, (tk.Button, FlatButton))
                and str(control.cget("text")) == "Export Markdown"
                for control in descendants(child)
            )
        ]
        self.assertEqual(owned, [first])

        self.overlay._request_popup_close(first)
        pump(self.overlay.root, 0.18)
        self.assertIsNone(window._history_more_popup)  # type: ignore[attr-defined]

    def test_history_more_construction_failure_leaves_no_owned_popup(self) -> None:
        self.overlay.open_history()
        pump(self.overlay.root, 0.65)
        window = self.overlay.utility_windows["history"]
        more = next(
            button
            for button in descendants(window)
            if isinstance(button, ttk.Button)
            and str(button.cget("text")) == "Export and clear..."
        )
        before = live_toplevel_paths(self.overlay.root)

        with (
            mock.patch(
                "knight_flow.overlay.tk.Frame",
                side_effect=tk.TclError("forced frame failure"),
            ),
            mock.patch("knight_flow.overlay.log.debug"),
        ):
            more.invoke()

        pump(self.overlay.root, 0.03)
        self.assertIsNone(window._history_more_popup)  # type: ignore[attr-defined]
        self.assertEqual(live_toplevel_paths(self.overlay.root), before)

    def test_help_note_is_one_popup_per_host(self) -> None:
        host = self._host()
        self.overlay._open_help_note(host, "settings")
        first = host._talkdat_help_note_popup  # type: ignore[attr-defined]
        with mock.patch.object(
            first,
            "focus_force",
            side_effect=tk.TclError("forced focus refusal"),
        ):
            self.overlay._open_help_note(host, "different context")

        self.assertIs(host._talkdat_help_note_popup, first)  # type: ignore[attr-defined]
        self.assertEqual(
            first._talkdat_help_note_state["context"],  # type: ignore[attr-defined]
            "different context",
        )
        owned = [
            child
            for child in descendants(host)
            if isinstance(child, tk.Toplevel) and child.winfo_exists()
        ]
        self.assertEqual(owned, [first])
        self.overlay._request_popup_close(first)
        pump(self.overlay.root, 0.18)
        self.assertIsNone(host._talkdat_help_note_popup)  # type: ignore[attr-defined]

    def test_help_note_construction_failure_leaves_no_owned_popup(self) -> None:
        host = self._host()
        before = live_toplevel_paths(self.overlay.root)

        with (
            mock.patch.object(
                self.overlay,
                "_settings_palette",
                side_effect=RuntimeError("forced palette failure"),
            ),
            mock.patch("knight_flow.overlay.log.debug"),
        ):
            self.overlay._open_help_note(host, "settings")

        pump(self.overlay.root, 0.03)
        self.assertIsNone(host._talkdat_help_note_popup)  # type: ignore[attr-defined]
        self.assertEqual(live_toplevel_paths(self.overlay.root), before)

    def test_retiring_owned_popups_cannot_clear_replacement_pointers(self) -> None:
        self.overlay.open_history()
        pump(self.overlay.root, 0.65)
        history = self.overlay.utility_windows["history"]
        more = next(
            button
            for button in descendants(history)
            if isinstance(button, ttk.Button)
            and str(button.cget("text")) == "Export and clear..."
        )
        more.invoke()
        old_more = history._history_more_popup  # type: ignore[attr-defined]
        replacement_more = tk.Toplevel(history)
        history._history_more_popup = replacement_more  # type: ignore[attr-defined]
        old_more.destroy()
        pump(self.overlay.root, 0.03)
        self.assertIs(  # type: ignore[attr-defined]
            history._history_more_popup,
            replacement_more,
        )

        host = self._host()
        self.overlay._open_help_note(host, "settings")
        old_note = host._talkdat_help_note_popup  # type: ignore[attr-defined]
        replacement_note = tk.Toplevel(host)
        host._talkdat_help_note_popup = replacement_note  # type: ignore[attr-defined]
        old_note.destroy()
        pump(self.overlay.root, 0.03)
        self.assertIs(  # type: ignore[attr-defined]
            host._talkdat_help_note_popup,
            replacement_note,
        )

        replacement_more.destroy()
        replacement_note.destroy()

    def test_settings_save_receipt_is_latest_wins_during_show_and_close(self) -> None:
        host = self._host()
        palette = self.overlay._settings_palette("Flow Dark")
        self.overlay._show_settings_saved_overlay(host, palette, "First save")
        state = host._talkdat_settings_saved_overlay  # type: ignore[attr-defined]
        first = state["window"]

        self.overlay._show_settings_saved_overlay(host, palette, "Second save")
        self.assertIs(state["window"], first)
        self.assertEqual(
            first._talkdat_saved_message_label.cget("text"),  # type: ignore[attr-defined]
            "Second save",
        )

        light_palette = self.overlay._settings_palette("Flow Light")
        self.overlay._show_settings_saved_overlay(host, light_palette, "Light save")
        self.assertIs(state["window"], first)
        pump(self.overlay.root, 0.24)
        themed = state["window"]
        self.assertIsNotNone(themed)
        self.assertIsNot(themed, first)
        self.assertFalse(first.winfo_exists())
        self.assertEqual(
            themed._talkdat_saved_message_label.cget("text"),  # type: ignore[attr-defined]
            "Light save",
        )
        self.assertEqual(
            themed._talkdat_saved_message_label.cget("fg"),  # type: ignore[attr-defined]
            light_palette["text"],
        )

        self.overlay._request_popup_close(themed)
        self.overlay._show_settings_saved_overlay(host, light_palette, "Third save")
        self.assertIs(state["window"], themed)
        pump(self.overlay.root, 0.24)
        latest = state["window"]
        self.assertIsNotNone(latest)
        self.assertIsNot(latest, themed)
        self.assertEqual(
            latest._talkdat_saved_message_label.cget("text"),  # type: ignore[attr-defined]
            "Third save",
        )
        owned = [
            child
            for child in descendants(host)
            if isinstance(child, tk.Toplevel) and child.winfo_exists()
        ]
        self.assertEqual(owned, [latest])

    def test_settings_receipt_is_latest_wins_during_reduced_motion_destroy(self) -> None:
        self.overlay.config.setdefault("ui", {})["reduce_motion"] = True
        host = self._host()
        dark = self.overlay._settings_palette("Flow Dark")
        light = self.overlay._settings_palette("Flow Light")
        self.overlay._show_settings_saved_overlay(host, dark, "Old save")
        state = host._talkdat_settings_saved_overlay  # type: ignore[attr-defined]
        retiring = state["window"]

        def request_newest(event: tk.Event) -> None:
            if event.widget is retiring:
                self.overlay._show_settings_saved_overlay(
                    host,
                    light,
                    "Newest from destroy",
                )

        retiring.bind("<Destroy>", request_newest, add="+")
        self.overlay._request_popup_close(retiring)
        pump(self.overlay.root, 0.06)

        latest = state["window"]
        self.assertIsNotNone(latest)
        self.assertIsNot(latest, retiring)
        self.assertEqual(
            latest._talkdat_saved_message_label.cget("text"),  # type: ignore[attr-defined]
            "Newest from destroy",
        )
        self.assertEqual(
            latest._talkdat_saved_message_label.cget("fg"),  # type: ignore[attr-defined]
            light["text"],
        )
        owned = [
            child
            for child in descendants(host)
            if isinstance(child, tk.Toplevel) and child.winfo_exists()
        ]
        self.assertEqual(owned, [latest])

    def test_settings_receipt_remeasures_long_warning_copy_inside_its_card(self) -> None:
        host = self._host()
        palette = self.overlay._settings_palette("Flow Dark")
        self.overlay._show_settings_saved_overlay(host, palette, "Saved.")
        state = host._talkdat_settings_saved_overlay  # type: ignore[attr-defined]
        receipt = state["window"]
        pump(self.overlay.root, 0.04)
        short_height = receipt.winfo_height()

        warning = (
            "Saved, but Rewrite and Translate share Ctrl+Win+R, so only one action "
            "will fire. Give one of them different keys before relying on either "
            "shortcut during a live dictation."
        )
        self.overlay._show_settings_saved_overlay(host, palette, warning)
        pump(self.overlay.root, 0.04)

        self.assertIs(state["window"], receipt)
        label = receipt._talkdat_saved_message_label  # type: ignore[attr-defined]
        self.assertEqual(label.cget("text"), warning)
        self.assertEqual(receipt._talkdat_saved_full_message, warning)  # type: ignore[attr-defined]
        self.assertGreater(int(label.cget("wraplength")), 0)
        self.assertGreaterEqual(receipt.winfo_height(), short_height)
        self.assertGreaterEqual(label.winfo_rootx(), receipt.winfo_rootx())
        self.assertLessEqual(
            label.winfo_rootx() + label.winfo_width(),
            receipt.winfo_rootx() + receipt.winfo_width(),
        )
        self.assertGreaterEqual(label.winfo_rooty(), receipt.winfo_rooty())
        self.assertLessEqual(
            label.winfo_rooty() + label.winfo_height(),
            receipt.winfo_rooty() + receipt.winfo_height(),
        )

    def test_settings_receipt_uses_logical_bounds_without_a_monitor_api(self) -> None:
        host = self._host()
        palette = self.overlay._settings_palette("Flow Dark")
        fallback = (40, 30, 520, 350)
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
                self.overlay._show_settings_saved_overlay(
                    host,
                    palette,
                    "Settings saved near the edge.",
                )
                state = host._talkdat_settings_saved_overlay  # type: ignore[attr-defined]
                receipt = state["window"]
                pump(self.overlay.root, 0.05)

                gutter = 16
                left, top, right, bottom = fallback
                self.assertGreaterEqual(receipt.winfo_rootx(), left + gutter)
                self.assertGreaterEqual(receipt.winfo_rooty(), top + gutter)
                self.assertLessEqual(
                    receipt.winfo_rootx() + receipt.winfo_width(),
                    right - gutter,
                )
                self.assertLessEqual(
                    receipt.winfo_rooty() + receipt.winfo_height(),
                    bottom - gutter,
                )

                self.overlay._show_settings_saved_overlay(
                    host,
                    palette,
                    "Newest save stays owned.",
                )
                self.assertIs(state["window"], receipt)
                self.assertEqual(
                    receipt._talkdat_saved_message_label.cget("text"),  # type: ignore[attr-defined]
                    "Newest save stays owned.",
                )

            monitor_lookup.assert_called()
            logical_lookup.assert_called()
        finally:
            if original_scale is None:
                ui.pop("scale", None)
            else:
                ui["scale"] = original_scale

    def test_settings_receipt_construction_failure_leaves_no_owned_popup(self) -> None:
        host = self._host()
        palette = self.overlay._settings_palette("Flow Dark")
        before = live_toplevel_paths(self.overlay.root)

        with (
            mock.patch(
                "knight_flow.overlay.tk.Canvas",
                side_effect=tk.TclError("forced receipt canvas failure"),
            ),
            mock.patch("knight_flow.overlay.log.debug"),
        ):
            self.overlay._show_settings_saved_overlay(host, palette, "Save")

        pump(self.overlay.root, 0.03)
        state = host._talkdat_settings_saved_overlay  # type: ignore[attr-defined]
        self.assertIsNone(state["window"])
        self.assertIsNone(state["pending"])
        self.assertEqual(live_toplevel_paths(self.overlay.root), before)

    def test_pill_caption_toggle_uses_the_normal_utility_close(self) -> None:
        self.overlay.toggle_captions()
        window = self.overlay.utility_windows["captions"]
        with mock.patch.object(self.overlay, "_request_utility_close") as close:
            self.overlay.toggle_captions()
        close.assert_called_once_with(window)

    def test_ramble_indicator_is_latest_wins_and_retires_normally(self) -> None:
        self.overlay.show_ramble_indicator()
        first = self.overlay._ramble_indicator
        self.assertIsNotNone(first)

        self.overlay.show_ramble_indicator()
        latest = self.overlay._ramble_indicator
        self.assertIsNotNone(latest)
        self.assertIsNot(latest, first)
        self.assertFalse(first.winfo_exists())
        self.assertTrue(latest.winfo_exists())

        self.overlay.hide_ramble_indicator()
        pump(self.overlay.root, 0.18)
        self.assertFalse(latest.winfo_exists())
        self.assertIsNone(self.overlay._ramble_indicator)

    def test_settings_deep_link_during_close_builds_a_fresh_owner(self) -> None:
        self.overlay.open_settings()
        pump(self.overlay.root, 0.65)
        old = self.overlay.utility_windows["settings"]

        self.overlay._request_utility_close(old)
        self.overlay._settings_initial_page = ("Speech", "Local models")
        self.overlay.open_settings()
        pump(self.overlay.root, 0.8)

        fresh = self.overlay.utility_windows.get("settings")
        self.assertIsNotNone(fresh)
        self.assertIsNot(fresh, old)
        self.assertTrue(fresh.winfo_exists())
        self.assertFalse(getattr(fresh, "_talkdat_close_requested", False))
        self.assertIsNone(getattr(self.overlay, "_settings_initial_page", None))

    def test_pill_caption_toggle_really_stops_and_retires_once(self) -> None:
        toggles: list[str] = []
        self.overlay.callbacks["captions_stream"] = lambda: toggles.append("toggle")
        self.addCleanup(self.overlay.callbacks.pop, "captions_stream", None)

        self.overlay.toggle_captions()
        window = self.overlay.utility_windows["captions"]
        start = next(
            button
            for button in descendants(window)
            if isinstance(button, (tk.Button, FlatButton)) and str(button.cget("text")) == "START"
        )
        start.invoke()
        self.assertEqual(toggles, ["toggle"])
        self.assertEqual(str(start.cget("text")), "STOP")

        self.overlay.toggle_captions()
        self.assertEqual(toggles, ["toggle", "toggle"])
        pump(self.overlay.root, 0.25)
        self.assertNotIn("captions", self.overlay.utility_windows)
        self.assertFalse(window.winfo_exists())

        self.overlay._request_utility_close(window)
        pump(self.overlay.root, 0.03)
        self.assertEqual(toggles, ["toggle", "toggle"])


if __name__ == "__main__":
    unittest.main()
