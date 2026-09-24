"""Real Tk smoke tests for keyboard-first micro-controls.

Static guards pin the source contracts, but they cannot catch a Tk option that
is accepted by Python and rejected only when the real widget is constructed.
Run this module in the clean interpreter managed by test_gui_regressions.py.

This is not Narrator/UI Automation certification.  It proves real widget
construction, focus participation, command wiring, and single activation only.
"""

from __future__ import annotations

from knight_flow import mac_support

import contextlib
import os
import tempfile
import time
import unittest
from unittest import mock

from tests import gui_offscreen  # noqa: F401  (never show windows on the user's desktop)
from knight_flow.flat_button import FlatButton  # tk.Button off macOS, a styled Label on it

try:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import ttk
except Exception:  # pragma: no cover - tkinter missing entirely
    tk = None  # type: ignore[assignment]
    tkfont = None  # type: ignore[assignment]
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
class RealMicroControlAccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        cls._home = tempfile.mkdtemp(prefix="talkdat-micro-controls-")
        os.environ["TALK_DAT_HOME"] = cls._home
        cls.calls = {
            "captions": 0,
            "translation_toggle": 0,
            "push_to_talk": 0,
            "push_to_talk_stop": 0,
            "cancel": 0,
            "update": 0,
            "reject": 0,
        }

        def count(name: str):
            def callback(*_args, **_kwargs):
                cls.calls[name] += 1

            return callback

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        cls.overlay = Overlay(
            load_config(),
            callbacks={
                "captions_stream": count("captions"),
                "translate_toggle": count("translation_toggle"),
                "push_to_talk": count("push_to_talk"),
                "push_to_talk_stop": count("push_to_talk_stop"),
                "cancel": count("cancel"),
            },
        )
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

    def _buttons(self, widget: tk.Misc) -> list[tk.Button]:
        return [child for child in descendants(widget) if isinstance(child, (tk.Button, FlatButton))]

    def _button(self, widget: tk.Misc, text: str) -> tk.Button:
        matches = [button for button in self._buttons(widget) if str(button.cget("text")) == text]
        self.assertTrue(matches, f"real Tk button {text!r} was not constructed")
        return matches[0]

    def test_shared_close_and_settings_custom_controls_construct_focusably(self) -> None:
        self.overlay.open_settings()
        pump(self.overlay.root, 0.5)
        window = self.overlay.utility_windows["settings"]

        close_probe = tk.Toplevel(self.overlay.root)
        close_host = tk.Frame(close_probe, bg="#071113")
        close_host.pack()
        self.overlay._close_control(close_probe, close_host, "#071113").pack()
        pump(self.overlay.root, 0.05)
        close = self._button(close_probe, "Close window")
        self.assertNotEqual(str(close.cget("takefocus")), "0")
        self.assertTrue(close.bind("<Return>"))
        close_probe.destroy()

        # X-529: six, not seven. Tools carried no settings -- only buttons
        # that opened other windows, each of which already had a home.
        settings_destinations = {
            "General",
            "Colors",
            "Dictation",
            "Formatting",
            "Speech",
            "Advanced",
        }
        rail_buttons = [
            button
            for button in self._buttons(window)
            if str(button.cget("text")).splitlines()[0] in settings_destinations
        ]
        self.assertEqual(
            {str(button.cget("text")).splitlines()[0] for button in rail_buttons},
            settings_destinations,
            "Settings rail destinations are not all native buttons",
        )
        self.assertTrue(all(str(button.cget("takefocus")) != "0" for button in rail_buttons))
        self.assertTrue(all(button.bind("<Return>") and button.bind("<space>") for button in rail_buttons))

        settings_close = [button for button in self._buttons(window) if str(button.cget("text")) == "Close window"]
        self.assertEqual(len(settings_close), 1, "Settings masthead must expose exactly one native Close button")
        self.assertNotEqual(str(settings_close[0].cget("takefocus")), "0")

        window._select_settings_page("Colors", None, "Theme")
        pump(self.overlay.root, 1.4)
        # History: fifty theme tk.Buttons until X-337. The material gallery
        # is ONE focusable canvas with the full keyboard grammar. Identify
        # it BY that grammar -- other focusable hand2 canvases exist (the
        # gain dial, the emoji grid), so the whole keyboard contract is the
        # discriminator, not cursor + takefocus alone.
        grammar = ("<Up>", "<Down>", "<Return>", "<space>", "<FocusIn>")
        galleries = [
            widget
            for widget in descendants(window)
            if isinstance(widget, tk.Canvas)
            and str(widget.cget("takefocus")) == "1"
            and all(widget.bind(sequence) for sequence in grammar)
        ]
        self.assertEqual(len(galleries), 1, "the material theme gallery must be one focusable canvas")

        gain_scales = [
            widget
            for widget in descendants(window)
            if isinstance(widget, ttk.Scale)
            and str(widget.cget("style")) == "Flow.Horizontal.TScale"
        ]
        self.assertEqual(len(gain_scales), 1, "software gain does not expose exactly one native slider")
        self.assertNotEqual(str(gain_scales[0].cget("takefocus")), "0")
        self.assertTrue(gain_scales[0].bind("<Left>"))
        decorative_gain_dials = [
            widget
            for widget in descendants(window)
            if isinstance(widget, tk.Canvas)
            and str(widget.cget("width")) == "132"
            and str(widget.cget("height")) == "112"
        ]
        self.assertEqual(len(decorative_gain_dials), 1)
        self.assertEqual(str(decorative_gain_dials[0].cget("takefocus")), "0")

        radios = [widget for widget in descendants(window) if isinstance(widget, tk.Radiobutton)]
        provider_radios = {
            str(widget.cget("text")): widget
            for widget in radios
            if str(widget.cget("text")) in {"Local / on-device", "Bring your own"}
        }
        self.assertEqual(set(provider_radios), {"Local / on-device", "Bring your own"})
        self.assertEqual(len({str(widget.cget("variable")) for widget in provider_radios.values()}), 1)
        self.assertTrue(all(str(widget.cget("takefocus")) != "0" for widget in provider_radios.values()))
        finish_radios = [widget for widget in radios if "Chill" in str(widget.cget("text")) or "Executive" in str(widget.cget("text"))]
        self.assertEqual(len(finish_radios), 2)
        self.assertEqual(len({str(widget.cget("variable")) for widget in finish_radios}), 1)

        results = next(widget for widget in descendants(window) if isinstance(widget, tk.Listbox))
        # The entry used to be a direct grandchild of the navigation host; it
        # gained a row wrapper when Clear moved inline with the field, and a
        # fixed two-level walk stopped finding it. Search the navigation host's
        # whole subtree instead -- it holds exactly one Entry, and that stays
        # true however the search control is arranged inside it.
        search_entry = next(
            widget
            for widget in descendants(results.master)
            if isinstance(widget, ttk.Entry)
        )
        search_entry.setvar(search_entry.cget("textvariable"), "microphone")
        pump(self.overlay.root, 0.1)
        self.assertTrue(results.winfo_ismapped())
        results.focus_force()
        results.event_generate("<Escape>")
        pump(self.overlay.root, 0.1)
        self.assertEqual(str(search_entry.get()), "")
        self.assertFalse(results.winfo_ismapped())
        window.destroy()
        pump(self.overlay.root, 0.1)

    def test_ramble_pdf_templates_are_native_buttons_and_start_immediately(self) -> None:
        chosen: list[str] = []
        self.overlay.open_ramble_chooser(chosen.append)
        pump(self.overlay.root, 0.3)
        window = self.overlay.utility_windows["ramble_pick"]
        pdf = next(
            widget for widget in descendants(window)
            if isinstance(widget, ttk.Button) and str(widget.cget("text")) == "PDF"
        )
        pdf.invoke()
        pump(self.overlay.root, 0.2)

        template_buttons = [
            widget for widget in self._buttons(window)
            if str(widget.cget("image")) and str(widget.cget("compound")) == "top"
        ]
        self.assertGreaterEqual(len(template_buttons), 8)
        self.assertTrue(all(str(button.cget("takefocus")) != "0" for button in template_buttons))
        self.assertTrue(all(button.bind("<Left>") and button.bind("<Right>") for button in template_buttons))
        for label in ("Previous", "Next"):
            arrow = next(
                widget for widget in descendants(window)
                if isinstance(widget, ttk.Button) and str(widget.cget("text")) == label
            )
            self.assertTrue(arrow.winfo_ismapped())

        template_buttons[0].invoke()
        pump(self.overlay.root, 0.4)
        self.assertEqual(len(chosen), 1)
        self.assertTrue(chosen[0].startswith("pdf:"))
        self.assertFalse(window.winfo_exists())

    def test_history_more_menu_builds_real_focusable_actions(self) -> None:
        self.overlay.open_history()
        pump(self.overlay.root, 0.4)
        window = self.overlay.utility_windows["history"]
        more = next(
            button
            for button in descendants(window)
            if isinstance(button, ttk.Button) and str(button.cget("text")) == "Export and clear..."
        )
        more.invoke()
        pump(self.overlay.root, 0.2)

        exports = [button for button in self._buttons(window) if str(button.cget("text")) == "Export Markdown"]
        self.assertEqual(len(exports), 1)
        self.assertTrue(exports[0].bind("<Down>"))
        self.assertNotEqual(str(exports[0].cget("takefocus")), "0")
        exports[0].winfo_toplevel().destroy()

    def test_live_captions_buttons_call_the_engine_once_per_activation(self) -> None:
        before = self.calls["captions"]
        self.overlay.toggle_captions()
        pump(self.overlay.root, 0.3)
        window = self.overlay.utility_windows["captions"]
        self.assertIsNone(getattr(window, "_glass_titlebar", None))
        self.assertIsNone(getattr(window, "_theme_brush", None))
        self.assertIsNone(getattr(window, "_help_chip", None))
        close_buttons = [
            button for button in self._buttons(window)
            if str(button.cget("text")) == "Close captions"
        ]
        self.assertEqual(len(close_buttons), 1)
        start = self._button(window, "START")
        for control in (
            start,
            self._button(window, "Clear"),
            self._button(window, "Pager"),
            close_buttons[0],
        ):
            self.assertTrue(control.winfo_ismapped(), f"{control.cget('text')} is not visible")
        self.assertEqual(str(start.cget("state")), "normal")

        start.invoke()
        pump(self.overlay.root, 0.05)
        self.assertEqual(self.calls["captions"], before + 1)
        self.assertEqual(str(start.cget("text")), "STOP")

        start.invoke()
        pump(self.overlay.root, 0.05)
        self.assertEqual(self.calls["captions"], before + 2)
        self.assertEqual(str(start.cget("text")), "START")
        clear = self._button(window, "Clear")
        clear.invoke()
        pump(self.overlay.root, 0.05)
        self.assertEqual(str(clear.cget("text")), "Glass")
        self.assertEqual(str(close_buttons[0].cget("background")), self.overlay.CAPTIONS_CLEAR_KEY)
        self.assertEqual(str(close_buttons[0].master.cget("background")), self.overlay.CAPTIONS_CLEAR_KEY)
        window.destroy()
        pump(self.overlay.root, 0.1)

    def test_caption_transport_tracks_real_engine_states_and_close_is_not_toggle(self) -> None:
        closed = []
        self.overlay.callbacks["captions_stop"] = lambda: closed.append(True)
        try:
            before = self.calls["captions"]
            self.overlay.toggle_captions()
            window = self.overlay.utility_windows["captions"]
            pump(self.overlay.root, .1)
            start = self._button(window, "START")
            start.invoke()
            self.assertEqual(self.calls["captions"], before + 1)
            self.overlay.captions_stream_state("starting", "Opening the microphone.")
            self.assertEqual(str(start.cget("text")), "STARTING")
            self.assertEqual(str(start.cget("state")), "disabled")
            self.overlay.captions_stream_state("listening")
            self.assertEqual(str(start.cget("text")), "STOP")
            self.assertEqual(str(start.cget("state")), "normal")
            self.overlay.captions_stream_state("stopping")
            self.assertEqual(str(start.cget("text")), "STOPPING")
            self.assertEqual(str(start.cget("state")), "disabled")
            self.overlay.captions_stream_state("stopped")
            self.assertEqual(str(start.cget("text")), "START")
            self.overlay._request_utility_close(window)
            pump(self.overlay.root, .4)
            self.assertEqual(closed, [True])
            self.assertEqual(self.calls["captions"], before + 1)
            self.assertIsNone(self.overlay._caption_state_sink)
        finally:
            self.overlay.callbacks.pop("captions_stop", None)

    def test_caption_error_survives_the_ticker_until_retry(self) -> None:
        self.overlay.toggle_captions()
        window = self.overlay.utility_windows["captions"]
        pump(self.overlay.root, .1)
        message = "The microphone could not open. Check your input in Settings."
        self.overlay.captions_stream_state("error", message)
        pump(self.overlay.root, .5)
        self.assertEqual(self.overlay._caption_label.cget("text"), message)
        self.assertEqual(str(self._button(window, "START").cget("state")), "normal")
        self.overlay.captions_stream_state("listening")
        self.overlay.captions_update("A fresh caption.", True)
        pump(self.overlay.root, .25)
        self.assertEqual(self.overlay._caption_label.cget("text"), "A fresh caption.")
        self.overlay._request_utility_close(window)
        pump(self.overlay.root, .4)

    def test_translation_scratchpad_and_toasts_construct_semantic_actions(self) -> None:
        self.overlay.open_translation()
        pump(self.overlay.root, 0.4)
        translation = self.overlay.utility_windows["translation"]
        auto = next(button for button in self._buttons(translation) if str(button.cget("text")).startswith("Auto-translate"))
        speak = next(button for button in self._buttons(translation) if "Translate now" in str(button.cget("text")))
        self.assertEqual(str(auto.cget("state")), "normal")
        self.assertEqual(str(speak.cget("state")), "normal")
        before_toggle = self.calls["translation_toggle"]
        auto.invoke()
        self.assertEqual(self.calls["translation_toggle"], before_toggle + 1)

        self.overlay.config.setdefault("ui", {})["scratchpad_font"] = mac_support.FONT_MONO
        self.overlay.open_scratchpad()
        pump(self.overlay.root, 0.4)
        scratchpad = self.overlay.utility_windows["scratchpad"]
        editor = next(widget for widget in descendants(scratchpad) if isinstance(widget, tk.Text))
        actual_family = str(tkfont.Font(root=scratchpad, font=editor.cget("font")).actual("family"))
        self.assertEqual(actual_family.casefold(), mac_support.FONT_MONO.casefold())
        font = next(
            button
            for button in descendants(scratchpad)
            if isinstance(button, ttk.Button) and str(button.cget("text")) == "Font"
        )
        font.invoke()
        pump(self.overlay.root, 0.2)
        font_popup = getattr(scratchpad, "_talkdat_font_chooser", None)
        self.assertIsNotNone(font_popup)
        font_lists = [
            widget
            for widget in descendants(font_popup)
            if isinstance(widget, tk.Listbox)
        ]
        self.assertEqual(len(font_lists), 1)
        shown_fonts = {
            str(font_lists[0].get(index))
            for index in range(int(font_lists[0].size()))
        }
        self.assertTrue({"Calibri", mac_support.FONT_MONO, "Verdana", "Georgia"}.issubset(shown_fonts))
        self.assertTrue(font_lists[0].bind("<Return>"))
        use_font = self._button(font_popup, "Use selected font")
        self.assertEqual(str(use_font.cget("state")), "normal")
        font_lists[0].winfo_toplevel().destroy()

        before_reject = self.calls["reject"]
        with mock.patch("knight_flow.meeting_quiet.meeting_in_progress", return_value=False):
            self.overlay.show_learned_word(
                "Accessibility",
                lambda: self.calls.__setitem__("reject", self.calls["reject"] + 1),
            )
        pump(self.overlay.root, 0.2)
        reject = self._button(self.overlay.root, "Don't save")
        reject.invoke()
        self.assertEqual(self.calls["reject"], before_reject + 1)
        reject.winfo_toplevel().destroy()

        before_update = self.calls["update"]
        self.overlay.show_update_popover(
            "test",
            lambda: self.calls.__setitem__("update", self.calls["update"] + 1),
        )
        pump(self.overlay.root, 0.2)
        update = self._button(self.overlay.root, "Update")
        update.invoke()
        pump(self.overlay.root, 0.2)
        self.assertEqual(self.calls["update"], before_update + 1)

    def test_outcome_toast_reduced_motion_snaps_after_the_same_hold(self) -> None:
        ui = self.overlay.config.setdefault("ui", {})
        marker = object()
        previous_reduce_motion = ui.get("reduce_motion", marker)
        try:
            with (
                mock.patch.object(self.overlay, "TOAST_HOLD_MS", 30),
                mock.patch.object(self.overlay, "TOAST_FADE_MS", 500),
            ):
                ui["reduce_motion"] = True
                self.overlay._show_toast_now("Reduced motion outcome")
                reduced_toast = self.overlay._toast_window
                self.assertIsNotNone(reduced_toast)
                pump(self.overlay.root, 0.12)
                self.assertFalse(reduced_toast.winfo_exists())
                self.assertIsNone(self.overlay._toast_window)

                ui["reduce_motion"] = False
                self.overlay._show_toast_now("Animated outcome")
                animated_toast = self.overlay._toast_window
                self.assertIsNotNone(animated_toast)
                pump(self.overlay.root, 0.12)
                self.assertTrue(animated_toast.winfo_exists())
                self.assertGreater(float(animated_toast.attributes("-alpha")), 0.0)
                pump(self.overlay.root, 0.5)
                self.assertFalse(animated_toast.winfo_exists())
                self.assertIsNone(self.overlay._toast_window)
        finally:
            toast = getattr(self.overlay, "_toast_window", None)
            if toast is not None:
                with contextlib.suppress(Exception):
                    toast.destroy()
            self.overlay._toast_window = None
            if previous_reduce_motion is marker:
                ui.pop("reduce_motion", None)
            else:
                ui["reduce_motion"] = previous_reduce_motion

    def test_learned_receipt_is_singleton_and_alt_d_targets_latest_word(self) -> None:
        ui = self.overlay.config.setdefault("ui", {})
        marker = object()
        previous_reduce_motion = ui.get("reduce_motion", marker)
        rejected: list[str] = []
        latest = None
        try:
            ui["reduce_motion"] = True
            with mock.patch(
                "knight_flow.meeting_quiet.meeting_in_progress",
                return_value=False,
            ):
                self.overlay.show_learned_word(
                    "Alpha",
                    lambda: rejected.append("Alpha"),
                )
                pump(self.overlay.root, 0.03)
                first = self.overlay._learned_word_receipt
                self.assertIsNotNone(first)

                self.overlay.show_learned_word(
                    "Beta",
                    lambda: rejected.append("Beta"),
                )
                pump(self.overlay.root, 0.03)

            latest = self.overlay._learned_word_receipt
            self.assertIsNotNone(latest)
            self.assertIsNot(first, latest)
            self.assertFalse(first.winfo_exists())
            active_receipts = [
                child
                for child in self.overlay.root.winfo_children()
                if isinstance(child, tk.Toplevel)
                and any(
                    isinstance(widget, (tk.Button, FlatButton))
                    and str(widget.cget("text")) == "Don't save"
                    for widget in descendants(child)
                )
            ]
            self.assertEqual(active_receipts, [latest])
            self.assertAlmostEqual(float(latest.attributes("-alpha")), 0.96, places=2)

            # Tk routes synthetic key events only to the focused toplevel.
            # Give the root the same focus ownership its accelerator expects
            # so this remains deterministic when earlier GUI tests left a
            # utility window focused.
            self.overlay.root.focus_force()
            pump(self.overlay.root, 0.02)
            self.overlay.root.event_generate("<Alt-d>", when="tail")
            pump(self.overlay.root, 0.04)
            self.assertEqual(rejected, ["Beta"])

            receipt_canvas = next(
                widget
                for widget in descendants(latest)
                if isinstance(widget, tk.Canvas)
            )
            text_item = next(
                item
                for item in receipt_canvas.find_all()
                if receipt_canvas.type(item) == "text"
            )
            strike_item = next(
                item
                for item in receipt_canvas.find_all()
                if receipt_canvas.type(item) == "line"
            )
            text_bounds = receipt_canvas.bbox(text_item)
            strike_coords = receipt_canvas.coords(strike_item)
            self.assertIsNotNone(text_bounds)
            self.assertAlmostEqual(strike_coords[2], text_bounds[2], places=2)

            # Repeated accelerators during the visible strike cannot reject
            # the same learned word twice.
            self.overlay.root.event_generate("<Alt-d>", when="tail")
            pump(self.overlay.root, 0.04)
            self.assertEqual(rejected, ["Beta"])

            pump(self.overlay.root, 0.5)
            self.assertFalse(latest.winfo_exists())
            self.assertIsNone(self.overlay._learned_word_receipt)
            self.assertIsNone(self.overlay._learned_word_reject_binding)
        finally:
            if latest is not None:
                with contextlib.suppress(Exception):
                    latest.destroy()
            receipt = getattr(self.overlay, "_learned_word_receipt", None)
            if receipt is not None:
                with contextlib.suppress(Exception):
                    receipt.destroy()
            if previous_reduce_motion is marker:
                ui.pop("reduce_motion", None)
            else:
                ui["reduce_motion"] = previous_reduce_motion


if __name__ == "__main__":
    unittest.main()
