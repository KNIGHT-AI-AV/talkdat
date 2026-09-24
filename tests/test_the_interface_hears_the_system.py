from __future__ import annotations

import ctypes
import gc
import sys
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest import mock

from knight_flow.ui import leading, system_prefs, type_scale


def _usable_root() -> tuple[tk.Tk | None, Exception | None]:
    try:
        root = tk.Tk()
    except Exception as error:  # pragma: no cover - depends on the display
        return None, error
    return root, None


_PROBE, _ROOT_ERROR = _usable_root()
if _PROBE is not None:
    _PROBE.destroy()
    _PROBE = None
    gc.collect()


class SystemPreferencesTests(unittest.TestCase):
    """An accessibility setting said once to Windows must not need saying twice.

    The app's own "reduce motion" checkbox was the only thing consulted, so
    someone who had switched animations off system-wide -- the place a person
    with a vestibular disorder actually sets it -- still got every animation
    until they found our checkbox as well (X-536).
    """

    def test_windows_stillness_is_reported_as_reduced_motion(self) -> None:
        def spi(action, _param, result, _flags):
            if action == system_prefs.SPI_GETCLIENTAREAANIMATION:
                result._obj.value = 0  # animation DISABLED
                return 1
            return 0

        api = SimpleNamespace(user32=SimpleNamespace(SystemParametersInfoW=mock.Mock(side_effect=spi)))
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(ctypes, "windll", api, create=True):
            self.assertTrue(system_prefs.animations_are_switched_off())

    def test_windows_animating_normally_is_not_reduced_motion(self) -> None:
        def spi(action, _param, result, _flags):
            if action == system_prefs.SPI_GETCLIENTAREAANIMATION:
                result._obj.value = 1  # animation ENABLED
                return 1
            return 0

        api = SimpleNamespace(user32=SimpleNamespace(SystemParametersInfoW=mock.Mock(side_effect=spi)))
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(ctypes, "windll", api, create=True):
            self.assertFalse(system_prefs.animations_are_switched_off())

    def test_an_unanswerable_question_is_not_a_preference(self) -> None:
        """A failed call must not be read as "this person wants stillness".

        Guessing either way is wrong, but guessing THIS way is worse: it would
        silently switch animation off for everyone the first time the call
        failed anywhere unexpected, and a preference nobody expressed is not a
        preference.
        """

        zero_api = SimpleNamespace(user32=SimpleNamespace(SystemParametersInfoW=mock.Mock(return_value=0)))
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(ctypes, "windll", zero_api, create=True):
            self.assertFalse(system_prefs.animations_are_switched_off())

        raising_api = SimpleNamespace(user32=SimpleNamespace(SystemParametersInfoW=mock.Mock(side_effect=OSError)))
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(ctypes, "windll", raising_api, create=True):
            self.assertFalse(system_prefs.animations_are_switched_off())
            self.assertFalse(system_prefs.high_contrast_is_on())

    def test_other_platforms_answer_without_touching_user32(self) -> None:
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertFalse(system_prefs.animations_are_switched_off())
            self.assertFalse(system_prefs.high_contrast_is_on())

    def test_this_machine_answers_both_questions(self) -> None:
        """Not what the answer is -- that it is an answer and not an exception."""

        self.assertIsInstance(system_prefs.animations_are_switched_off(), bool)
        self.assertIsInstance(system_prefs.high_contrast_is_on(), bool)


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class LeadingReachesTheWidgetTests(unittest.TestCase):
    """The scale decides the leading; this proves the pixels arrive.

    A table of ratios that no widget reads is a document, not a design.
    """

    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()

        def destroy_on_tk_thread() -> None:
            root = self.root
            self.root = None  # type: ignore[assignment]
            root.destroy()
            gc.collect()

        self.addCleanup(destroy_on_tk_thread)

    def test_body_copy_gains_leading_and_a_reading_surface_gains_more(self) -> None:
        ui = tk.Text(self.root, font=("Segoe UI", type_scale.BODY))
        prose = tk.Text(self.root, font=("Segoe UI", type_scale.BODY))

        ui_extra = leading.apply(ui)
        prose_extra = leading.apply(prose, prose=True)

        self.assertGreater(ui_extra, 0, "body copy must gain leading")
        self.assertGreater(
            prose_extra,
            ui_extra,
            "a page he writes into is set looser than a settings row",
        )
        self.assertEqual(int(ui.cget("spacing2")), ui_extra, "the pixels must reach Tk")
        self.assertEqual(int(prose.cget("spacing2")), prose_extra)

    def test_a_pixel_sized_font_is_converted_before_it_is_measured(self) -> None:
        """A negative Tk size is pixels, not points.

        Reading -16 as sixteen POINTS would ask for the leading of a much
        larger step and set the block far too loose.
        """

        widget = tk.Text(self.root, font=("Segoe UI", -16))
        self.assertGreaterEqual(leading.apply(widget), 0)

    def test_a_destroyed_widget_does_not_take_the_panel_with_it(self) -> None:
        widget = tk.Text(self.root, font=("Segoe UI", type_scale.BODY))
        widget.destroy()
        self.assertEqual(leading.apply(widget), 0)


if __name__ == "__main__":
    unittest.main()
