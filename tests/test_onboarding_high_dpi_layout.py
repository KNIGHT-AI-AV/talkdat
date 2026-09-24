from __future__ import annotations

from knight_flow.mac_support import IS_MAC
from knight_flow.ui.onboarding import WINDOWS_DEFAULT_MIC

import json
import subprocess
import sys
import textwrap
import time
import unittest
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

from knight_flow.onboarding import ONBOARDING_STEPS
from knight_flow.ui.onboarding import OnboardingWizard
from scripts.capture_onboarding_gallery import CaptureHost
from tests.tk_support import probe_error as _ROOT_ERROR

# A bare tk.Tk() succeeds even with no Aqua session (it just never gets laid
# out by a real window server), so a "can I construct a root" probe reads
# this environment as usable and then hangs every layout wait at 1px. Reuse
# tk_support's probe -- it already asks launchctl whether a WindowServer is
# reachable before trusting Tk() at all.


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class OnboardingHighDpiLayoutTests(unittest.TestCase):
    def _wizard(self, scale: float) -> tuple[tk.Tk, OnboardingWizard]:
        root = tk.Tk()
        root.tk.call("tk", "scaling", 96.0 * scale / 72.0)
        root.withdraw()
        self.addCleanup(root.destroy)
        host = CaptureHost(root, "Flow Dark", scale=scale)
        wizard = OnboardingWizard(host)
        self.addCleanup(lambda: wizard.window.destroy() if wizard.window and wizard.window.winfo_exists() else None)
        self.assertIsNotNone(wizard.window)
        wizard.window.geometry("1040x720+0+0")
        return root, wizard

    @staticmethod
    def _walk(widget: tk.Misc) -> list[tk.Misc]:
        found: list[tk.Misc] = []
        for child in widget.winfo_children():
            found.append(child)
            found.extend(OnboardingHighDpiLayoutTests._walk(child))
        return found

    def _render(self, root: tk.Tk, wizard: OnboardingWizard, step_id: str) -> None:
        index = next(index for index, step in enumerate(ONBOARDING_STEPS) if step.id == step_id)
        wizard.render_step(index)
        # Settle until the layout has actually happened, rather than assuming
        # three passes is always enough.
        #
        # Three was enough when this test ran on its own and not always enough
        # after its siblings had each built and destroyed their own Tk root in
        # the same process: the window came back unlaid-out, every widget
        # reported width 1, and the assertions below read that as "the
        # description is wider than its container". A width of 1 is Tk's answer
        # for a widget it has not placed yet, not a measurement, so waiting for
        # a real number is the difference between measuring the layout and
        # measuring whether the layout had finished.
        #
        # And settle on the CLOCK, not on a pass count (2026-09-24). While a
        # label still wraps at 1 px the wizard re-measures after 60 ms
        # (_queue_content_extent_sync), so on an idle machine forty passes
        # finished inside that window, the re-measure never ran, and five of
        # these tests failed on code that had passed the day before under load.
        deadline = time.monotonic() + 2.0
        passes = 0
        while True:
            wizard.window.geometry("1040x720+0+0")
            root.update_idletasks()
            root.update()
            passes += 1
            if passes > 2 and wizard.content.winfo_width() > 1:
                return
            if time.monotonic() > deadline:
                break
            time.sleep(0.01)
        self.fail(
            f"the {step_id} page never laid out: "
            f"content is {wizard.content.winfo_width()}px wide after {passes} passes over 2 s"
        )
        # X-460c's own retry lives on a 60ms `after`, which needs real
        # wall-clock time to fire -- a back-to-back-window run (e.g. right
        # after test_every_page_remains_reachable's ~20-step render) can
        # leave a label wrapped at 1px past these three synchronous passes.
        # Give the real timer a chance instead of asserting on a lie.
        deadline = time.monotonic() + 2.0
        while wizard._labels_still_wrapping() and time.monotonic() < deadline:
            root.update_idletasks()
            root.update()
            time.sleep(0.02)

    def test_every_page_remains_reachable_in_a_200_percent_1080p_height(self) -> None:
        root = tk.Tk()
        root.tk.call("tk", "scaling", 192.0 / 72.0)
        root.withdraw()
        self.addCleanup(root.destroy)
        host = CaptureHost(root, "Flow Dark", scale=2.0)
        wizard = OnboardingWizard(host)
        self.addCleanup(lambda: wizard.window.destroy() if wizard.window and wizard.window.winfo_exists() else None)
        self.assertIsNotNone(wizard.window)
        wizard.window.geometry("1920x1040+0+0")

        overflow_pages: list[str] = []
        for index, step in enumerate(ONBOARDING_STEPS):
            wizard.render_step(index)
            root.update_idletasks()
            root.update()
            first, last = wizard.content_canvas.yview()
            if last - first < 0.99:
                overflow_pages.append(step.id)
                self.assertTrue(wizard.content_scrollbar.winfo_ismapped(), step.id)
                for _pass in range(2):
                    wizard.content_canvas.yview_moveto(1.0)
                    root.update_idletasks()
                    root.update()
                self.assertAlmostEqual(wizard.content_canvas.yview()[1], 1.0, places=3)
            window_bottom = wizard.window.winfo_rooty() + wizard.window.winfo_height()
            for button in (wizard.back_button, wizard.next_button):
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), window_bottom)

        self.assertTrue(overflow_pages)

    def test_page_three_description_wraps_inside_the_200_percent_viewport(self) -> None:
        root, wizard = self._wizard(2.0)
        self._render(root, wizard, "welcome")
        # Found by the step's own description rather than a copy of its words,
        # so a copy edit (2026-09-23: plain-language rewrite) cannot turn this
        # layout check into a lookup failure.
        welcome = next(step.description for step in ONBOARDING_STEPS if step.id == "welcome")
        description = next(
            widget
            for widget in self._walk(wizard.content)
            if isinstance(widget, tk.Label)
            and widget.cget("text") == welcome
        )
        self.assertLessEqual(int(description.cget("wraplength")), description.master.winfo_width())
        self.assertLessEqual(description.winfo_reqwidth(), description.master.winfo_width())

    def test_microphone_selector_keeps_the_default_value_readable_at_200_percent(self) -> None:
        root, wizard = self._wizard(2.0)
        self._render(root, wizard, "microphone")
        value_font = tkfont.nametofont("TkDefaultFont")
        required = value_font.measure(wizard.audio_device_var.get()) + wizard.px(44)
        self.assertGreaterEqual(wizard.mic_box.winfo_width(), required)
        self.assertEqual(wizard.audio_device_var.get(), WINDOWS_DEFAULT_MIC)
        self.assertEqual(int(wizard.mic_box.master.grid_slaves(row=1)[0].grid_info()["row"]), 1)

    def test_writing_page_stays_horizontally_contained_at_standard_and_200_percent(self) -> None:
        for scale in (1.0, 2.0):
            with self.subTest(scale=scale):
                root, wizard = self._wizard(scale)
                self._render(root, wizard, "writing")
                left = wizard.content_canvas.winfo_rootx()
                right = left + wizard.content_canvas.winfo_width()
                for widget in self._walk(wizard.content):
                    if not widget.winfo_ismapped() or widget.winfo_width() <= 1:
                        continue
                    self.assertGreaterEqual(widget.winfo_rootx(), left, str(widget))
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), right + 1, str(widget))

    def test_route_and_writing_choices_are_native_radio_groups(self) -> None:
        root, wizard = self._wizard(1.0)
        wizard.host.callbacks["license_status"] = lambda: {
            "active": False,
            "plan": "free",
            "cloud_enabled": False,
            "permanent_core": False,
        }
        wizard.route_var.set("local")
        self._render(root, wizard, "voice")

        # X-516: two routes. The managed card went with its engine.
        self.assertEqual(set(wizard.route_buttons), {"local", "byok"})
        for route, button in wizard.route_buttons.items():
            with self.subTest(route=route):
                self.assertIsInstance(button, tk.Radiobutton)
                self.assertEqual(button.winfo_class(), "Radiobutton")
                self.assertEqual(str(button.cget("variable")), str(wizard.route_var))
                self.assertEqual(str(button.cget("value")), route)
                self.assertEqual(str(button.cget("takefocus")), "1")
        # X-516: no route is disabled any more. The managed card was the only
        # one that could be greyed out, because it needed an account behind it.
        for route, button in wizard.route_buttons.items():
            with self.subTest(route=route):
                self.assertEqual(str(button.cget("state")), tk.NORMAL)
        self.assertEqual(wizard.route_var.get(), "local")

        self._render(root, wizard, "writing")
        self.assertEqual(set(wizard.writing_buttons), {"smart", "fast", "verbatim"})
        for preset, button in wizard.writing_buttons.items():
            with self.subTest(preset=preset):
                self.assertIsInstance(button, tk.Radiobutton)
                self.assertEqual(button.winfo_class(), "Radiobutton")
                self.assertEqual(str(button.cget("variable")), str(wizard.writing_var))
                self.assertEqual(str(button.cget("value")), preset)
        wizard.writing_buttons["fast"].invoke()
        self.assertEqual(wizard.writing_var.get(), "fast")

    def test_trigger_status_names_the_configured_chord_in_initial_and_later_states(self) -> None:
        root, wizard = self._wizard(1.0)
        wizard.config.setdefault("hotkeys", {})["push_to_talk"] = [["shift", "alt", "z"]]
        self._render(root, wizard, "controls")

        expected = wizard._chord_text()  # "Shift + Alt + Z" here, "Shift + Option + Z" on a Mac
        self.assertIn(expected, wizard.control_status_var.get())
        wizard.hotkey_rehearsed = True
        if wizard.key_after:
            wizard.window.after_cancel(wizard.key_after)
            wizard.key_after = None
        wizard._start_key_poll()
        self.assertIn(expected, wizard.control_status_var.get())
        wizard._receive_test_result("Rehearsal words")
        root.update_idletasks()
        root.update()
        self.assertIn(expected, wizard.control_status_var.get())

    def test_150_percent_layout_reaches_idle_without_configure_redraw_loop(self) -> None:
        """A real child process bounds the failure if Tk ever churns again."""

        script = textwrap.dedent(
            """
            import json
            import time
            import tkinter as tk
            from collections import Counter

            from knight_flow.ui.atelier_controls import AtelierButton
            from knight_flow.ui.onboarding import OnboardingWizard
            from scripts.capture_onboarding_gallery import CaptureHost

            counts = Counter()
            original_button = AtelierButton._redraw
            original_art = OnboardingWizard._draw_art_panel
            original_sync = OnboardingWizard._sync_content_extent

            def count_button(self):
                counts["button"] += 1
                return original_button(self)

            def count_art(self, *args, **kwargs):
                counts["art"] += 1
                return original_art(self, *args, **kwargs)

            def count_sync(self, *args, **kwargs):
                counts["sync"] += 1
                return original_sync(self, *args, **kwargs)

            AtelierButton._redraw = count_button
            OnboardingWizard._draw_art_panel = count_art
            OnboardingWizard._sync_content_extent = count_sync

            root = tk.Tk()
            root.tk.call("tk", "scaling", 144.0 / 72.0)
            root.withdraw()
            host = CaptureHost(root, "Flow Dark", scale=1.5, viewport="1560x1040")
            wizard = OnboardingWizard(host)
            wizard.window.geometry("1560x1040+0+0")
            wizard.window.deiconify()
            wizard.window.lift()
            started = time.perf_counter()
            for _pass in range(8):
                root.update_idletasks()
                root.update()
            result = {
                "elapsed": time.perf_counter() - started,
                "button": counts["button"],
                "art": counts["art"],
                "sync": counts["sync"],
                "back_class": wizard.back_button.winfo_class(),
                "next_class": wizard.next_button.winfo_class(),
                "back_size": [wizard.back_button.winfo_width(), wizard.back_button.winfo_height()],
                "next_size": [wizard.next_button.winfo_width(), wizard.next_button.winfo_height()],
            }
            wizard.window.destroy()
            root.update()
            root.destroy()
            print(json.dumps(result))
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
            timeout=25,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertLess(result["elapsed"], 12.0)
        self.assertLessEqual(result["button"], 30)
        self.assertLessEqual(result["art"], 15)
        self.assertLessEqual(result["sync"], 80)
        self.assertEqual(result["back_class"], "Button")
        self.assertEqual(result["next_class"], "Button")
        # Exact on the Segoe metrics the buttons were tuned against; the system
        # face on a Mac lands within a couple of pixels of them.
        tolerance = 4 if IS_MAC else 0
        for key, expected_size in (("back_size", [156, 60]), ("next_size", [198, 66])):
            with self.subTest(key=key):
                for actual, wanted in zip(result[key], expected_size, strict=True):
                    self.assertLessEqual(abs(actual - wanted), tolerance, f"{key}: {result[key]} vs {expected_size}")


if __name__ == "__main__":
    unittest.main()
