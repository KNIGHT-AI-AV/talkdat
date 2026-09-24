"""A Settings save must not shrink the Pill (owner's audit, 2026-09-23).

Every web Settings save calls Overlay.apply_runtime_config(). __init__ scaled
the Pill's sizes through ui_scale.px, but apply_runtime_config rebuilt them
from the raw 96-DPI numbers in config. On the owner's 3840x2160 panel at 150%
the listening Pill dropped from 288x52 to 192x39 after ANY save (192x35
instead of 240x44 at 125%) and stayed that way until a restart: shots
tk-pill__10a/10b in the UI inventory.

Two smaller faults rode along and are pinned here too:

* the same function re-read `bottom_margin` raw, so the gap under the Pill
  changed after a save;
* it chose the Pill's shape with `self.state == "idle"`, which EXPANDED a Pill
  that was showing a result or an error (both compact states) on save, and a
  changed size preset only reached the screen at the next dictation.

Real Overlay, real Tk; run through scripts/run_tests_offscreen.py so nothing
appears on anyone's screen.
"""
from __future__ import annotations

import copy
import time
import unittest

from knight_flow import ui_scale
from knight_flow.config import DEFAULT_CONFIG, PILL_SCALE_PRESETS
from tests import gui_offscreen  # noqa: F401  (X-164: never on a human's screen)
from tests.tk_support import probe_error as _ROOT_ERROR


def forget_default_root() -> None:
    """Tk binds every image made without a master to tkinter's default root.
    A root left behind by an earlier module would own this module's images
    ("image pyimageNN doesn't exist"), so each test starts and ends without
    one, as test_usage_counts_tk does."""
    import tkinter

    existing = getattr(tkinter, "_default_root", None)
    try:
        alive = existing is not None and bool(existing.winfo_exists())
    except Exception:
        alive = False
    if not alive:
        tkinter._default_root = None  # type: ignore[attr-defined]

GEOMETRY = (
    "active_pill_width",
    "active_pill_height",
    "active_width",
    "active_height",
    "compact_width",
    "compact_height",
    "bottom_margin",
)


def pump(root, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        root.update()
        time.sleep(0.01)


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class ThePillKeepsItsSizeAfterASaveTests(unittest.TestCase):
    def overlay(self, scale: float):
        """One live Overlay at a time: a second Tk interpreter cannot see the
        first one's images, so a loop must retire each Pill before the next."""
        from knight_flow.overlay import Overlay
        from tests.tk_support import acquire_root

        self.release(getattr(self, "_overlay", None))
        forget_default_root()
        config = copy.deepcopy(DEFAULT_CONFIG)
        config.setdefault("ui", {})["scale"] = scale
        # Geometry is under test, not animation: settle sizes immediately.
        config["ui"]["reduce_motion"] = True
        # macOS: one Tk root per process, ever (tests/tk_support). The Pill is a
        # Toplevel there, so destroying overlay.root left each test's hidden
        # Tk alive as the default root, and the next Overlay's images landed
        # in that dead interpreter ("image pyimageNN does not exist").
        overlay = Overlay(config, callbacks={}, root=acquire_root())
        self._overlay = overlay
        pump(overlay.root, 0.3)
        return overlay

    @staticmethod
    def release(overlay) -> None:
        from tests.tk_support import release_root

        if overlay is not None:
            try:
                release_root(overlay._tk_root)
            except Exception:
                pass

    def tearDown(self) -> None:
        overlay = getattr(self, "_overlay", None)
        self._overlay = None
        self.release(overlay)
        forget_default_root()

    @staticmethod
    def geometry(overlay) -> dict[str, int]:
        return {name: int(getattr(overlay, name)) for name in GEOMETRY}

    def test_a_save_changes_no_dimension_at_150_and_125_percent(self) -> None:
        for scale in (1.5, 1.25):
            with self.subTest(scale=scale):
                overlay = self.overlay(scale)
                before = self.geometry(overlay)
                # Sanity: the starting point really is scaled, or the
                # comparison below would pass on two equally wrong numbers.
                self.assertEqual(before["active_pill_width"], ui_scale.px(192, overlay.config))
                self.assertEqual(before["compact_width"], ui_scale.px(92, overlay.config))
                overlay.apply_runtime_config()
                pump(overlay.root, 0.2)
                self.assertEqual(self.geometry(overlay), before)

    def test_listening_after_a_save_is_the_full_scaled_size(self) -> None:
        """The exact numbers from the inventory: 288x52 at 150%, 240x44 at 125%."""
        for scale, expected in ((1.5, (288, 52)), (1.25, (240, 44))):
            with self.subTest(scale=scale):
                overlay = self.overlay(scale)
                overlay.apply_runtime_config()
                pump(overlay.root, 0.2)
                overlay.set_state("listening", "Listening.", "")
                pump(overlay.root, 0.5)
                self.assertEqual((overlay.current_width, overlay.current_height), expected)
                self.assertEqual((overlay.root.winfo_width(), overlay.root.winfo_height()), expected)

    def test_a_save_while_a_result_shows_keeps_the_pill_compact(self) -> None:
        overlay = self.overlay(1.5)
        overlay.set_state("captured", "Pasted.", "")
        pump(overlay.root, 0.1)
        overlay.apply_runtime_config()
        pump(overlay.root, 0.3)
        self.assertTrue(overlay.compact, "a save expanded a Pill that was showing a result")
        self.assertEqual(
            (overlay.current_width, overlay.current_height),
            (overlay.compact_width, overlay.compact_height),
        )

    def test_a_new_size_preset_reaches_the_screen_at_once(self) -> None:
        overlay = self.overlay(1.5)
        overlay.config["overlay"].update(PILL_SCALE_PRESETS["large"])
        overlay.apply_runtime_config()
        pump(overlay.root, 0.3)
        expected = (ui_scale.px(111, overlay.config), ui_scale.px(31, overlay.config))
        self.assertEqual((overlay.current_width, overlay.current_height), expected)
        self.assertEqual((overlay.root.winfo_width(), overlay.root.winfo_height()), expected)


if __name__ == "__main__":
    unittest.main()
