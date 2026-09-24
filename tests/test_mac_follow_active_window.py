from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from knight_flow.mac_support import IS_MAC
from tests.tk_support import probe_error as _ROOT_ERROR


@unittest.skipUnless(IS_MAC, "X-02 / X-16 on macOS")
@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class ThePillFollowsTheActiveWindowTests(unittest.TestCase):
    """X-02: "it doesn't jump to the next one without me first clicking it".

    Placement only re-evaluated when something else prompted a redraw, so the
    Pill lagged behind the window someone had just clicked into. Windows
    registers SetWinEventHook(EVENT_SYSTEM_FOREGROUND); the macOS counterpart is
    NSWorkspace's didActivateApplicationNotification, delivered on the same run
    loop Tk pumps.
    """

    TWO_SCREENS = [
        {"index": 0, "primary": True, "x": 0, "y": 0, "width": 1920, "height": 1080,
         "work_x": 0, "work_y": 30, "work_width": 1920, "work_height": 975},
        {"index": 1, "primary": False, "x": 1920, "y": 0, "width": 1440, "height": 900,
         "work_x": 1920, "work_y": 0, "work_width": 1440, "work_height": 900},
    ]

    def test_a_point_maps_to_the_screen_that_contains_it(self) -> None:
        from knight_flow import mac_support as ms

        with patch.object(ms, "list_screens", return_value=self.TWO_SCREENS):
            self.assertEqual(ms.screen_containing(100, 100)["index"], 0)
            self.assertEqual(ms.screen_containing(2000, 400)["index"], 1)

    def test_a_point_off_every_screen_falls_back_to_primary(self) -> None:
        """Guessing is worse than the primary display: a Pill placed on a
        screen that is not there is a Pill nobody can see."""
        from knight_flow import mac_support as ms

        with patch.object(ms, "list_screens", return_value=self.TWO_SCREENS):
            self.assertEqual(ms.screen_containing(9999, 9999)["index"], 0)

    def test_the_frontmost_apps_screen_is_found_from_its_window(self) -> None:
        from knight_flow import mac_support as ms

        app = MagicMock()
        app.processIdentifier.return_value = 321
        workspace = MagicMock()
        workspace.sharedWorkspace.return_value.frontmostApplication.return_value = app
        quartz = MagicMock()
        quartz.CGWindowListCopyWindowInfo.return_value = [
            {"kCGWindowOwnerPID": 999, "kCGWindowLayer": 0,
             "kCGWindowBounds": {"X": 10, "Y": 10, "Width": 100, "Height": 100}},
            {"kCGWindowOwnerPID": 321, "kCGWindowLayer": 0,
             "kCGWindowBounds": {"X": 2000, "Y": 100, "Width": 400, "Height": 300}},
        ]
        with patch.dict("sys.modules", {"Quartz": quartz, "AppKit": MagicMock(NSWorkspace=workspace)}), \
             patch.object(ms, "list_screens", return_value=self.TWO_SCREENS):
            screen = ms.screen_for_frontmost_app()
        self.assertIsNotNone(screen)
        self.assertEqual(screen["index"], 1, "must follow the app onto the second display")

    def test_the_overlay_no_longer_hard_returns_none(self) -> None:
        """The macOS branch was a bare `return None`, which pinned the Pill to
        the primary display while the checkbox that promises otherwise stayed
        checked and on by default."""
        from tests.tk_support import acquire_root, release_root

        from knight_flow import mac_support as ms
        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(lambda: release_root(overlay.root))
        with patch.object(ms, "screen_for_frontmost_app", return_value=self.TWO_SCREENS[1]):
            self.assertEqual(overlay._active_monitor_work_area(), (1920, 0, 3360, 900))

    def test_repositioning_is_debounced_and_respects_the_session_lock(self) -> None:
        """Jumping screens mid-dictation is worse than lagging, so a locked
        session suppresses the move."""
        from tests.tk_support import acquire_root, release_root

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(lambda: release_root(overlay.root))
        moved = []
        overlay._position = lambda: moved.append(1)

        overlay._session_work_area = (0, 0, 100, 100)
        overlay._reposition_for_foreground()
        self.assertEqual(moved, [], "a locked session must not be moved")

        overlay._session_work_area = None
        overlay._reposition_for_foreground()
        self.assertEqual(len(moved), 1)

    def test_utility_windows_open_on_the_pills_screen(self) -> None:
        """X-16: a window opened from the Pill's menu must appear where the
        Pill is, not wherever "secondary" happened to mean."""
        from tests.tk_support import acquire_root, release_root

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(lambda: release_root(overlay.root))
        overlay.root.update()
        rect = overlay._pill_monitor_work_area()
        self.assertIsNotNone(rect, "the Pill is on a screen; that screen must be findable")


if __name__ == "__main__":
    unittest.main()
