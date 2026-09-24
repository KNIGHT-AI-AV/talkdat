from __future__ import annotations

import unittest

from knight_flow.mac_support import IS_MAC
from tests.tk_support import probe_error as _ROOT_ERROR


@unittest.skipUnless(IS_MAC, "describes Dock-aware placement")
@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class ThePillMustNotSitBehindTheDockTests(unittest.TestCase):
    """Reported from the machine: "the actual pill needs to be higher right now
    it's underneath the dock".

    _primary_work_area asked Windows for the work area and, off Windows, fell
    back to the whole screen. On a 1080pt display whose Dock starts at 1004 the
    Pill was placed at y=1030 -- entirely inside the Dock. NSScreen.visibleFrame
    is the equivalent answer and excludes both the menu bar and the Dock.
    """

    def test_the_work_area_excludes_the_menu_bar_and_dock(self) -> None:
        from tests.tk_support import acquire_root, release_root

        from knight_flow.config import load_config
        from knight_flow.mac_support import list_screens
        from knight_flow.overlay import Overlay

        screen = list_screens()[0]
        overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(lambda: release_root(overlay.root))
        left, top, right, bottom = overlay._logical_work_area()

        self.assertGreater(top, 0, "the menu bar band is missing from the work area")
        self.assertLess(bottom, screen["height"], "the Dock band is missing from the work area")

    def test_the_pill_clears_the_dock(self) -> None:
        from tests.tk_support import acquire_root, release_root

        from knight_flow.config import load_config
        from knight_flow.mac_support import list_screens
        from knight_flow.overlay import Overlay

        screen = list_screens()[0]
        dock_top = screen["work_y"] + screen["work_height"]
        overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(lambda: release_root(overlay.root))

        _left, _top, _right, bottom = overlay._logical_work_area()
        for label, height in (("compact", overlay.compact_height),
                              ("active", overlay.active_pill_height)):
            with self.subTest(state=label):
                y = bottom - height - overlay._bottom_clearance()
                self.assertLessEqual(
                    y + height, dock_top,
                    f"the {label} pill overlaps the Dock band",
                )

    def test_a_magnifying_dock_gets_extra_room(self) -> None:
        """visibleFrame reports the Dock at its resting size. Magnified icons
        grow upward past that edge, so a Pill flush against it is covered by the
        thing it was placed to avoid."""
        from unittest.mock import patch

        from tests.tk_support import acquire_root, release_root

        from knight_flow import mac_support as ms
        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(lambda: release_root(overlay.root))

        with patch.object(ms, "dock_is_on_the_bottom", return_value=True), \
             patch.object(ms, "dock_magnification_headroom", return_value=40):
            self.assertEqual(overlay._bottom_clearance(), overlay.bottom_margin + 40)
        with patch.object(ms, "dock_is_on_the_bottom", return_value=False), \
             patch.object(ms, "dock_magnification_headroom", return_value=40):
            self.assertEqual(overlay._bottom_clearance(), overlay.bottom_margin)

    def test_headroom_is_never_negative(self) -> None:
        """A Dock set to shrink on magnification (largesize below tilesize) must
        not pull the Pill down into it."""
        from knight_flow.mac_support import dock_magnification_headroom

        self.assertGreaterEqual(dock_magnification_headroom(), 0)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(IS_MAC, "Aqua coordinate spaces")
@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class TkAndTheScreenDoNotAgreeOnZeroTests(unittest.TestCase):
    """The bug that survived the first fix.

    Correcting the work area alone still left the Pill 8 points inside the
    Dock, because Tk places windows relative to an origin below the menu bar
    while NSScreen reports the work area in true screen coordinates. Feeding Tk
    a screen-space y therefore moves the window down by the menu bar height.

    winfo_rooty() cannot detect this: it answers in Tk's own space and agrees
    with whatever was requested, so it reports no offset. That is why the first
    attempt measured zero and changed nothing.
    """

    def _overlay(self):
        from tests.tk_support import acquire_root, release_root

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(lambda: release_root(overlay.root))
        return overlay

    def test_the_offset_is_the_menu_bar_height(self) -> None:
        from knight_flow.mac_support import list_screens

        overlay = self._overlay()
        expected = list_screens()[0]["work_y"]
        self.assertEqual(overlay._tk_y_offset(), expected)
        self.assertGreater(expected, 0, "a Mac always has a menu bar band")

    def test_the_requested_geometry_is_shifted_into_tk_space(self) -> None:
        """What Tk is asked for must be the screen position minus the offset,
        or the window lands that far lower than intended."""
        overlay = self._overlay()
        _left, _top, _right, bottom = overlay._logical_work_area()
        overlay._apply_geometry(overlay.compact_width, overlay.compact_height)

        screen_y = bottom - overlay.compact_height - overlay._bottom_clearance()
        self.assertEqual(overlay._last_requested_y, screen_y - overlay._tk_y_offset())

    def test_windows_is_unaffected(self) -> None:
        from unittest.mock import patch

        from knight_flow import mac_support as ms

        overlay = self._overlay()
        with patch.object(ms, "IS_MAC", False):
            self.assertEqual(overlay._tk_y_offset(), 0)
