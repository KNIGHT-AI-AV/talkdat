from __future__ import annotations

import unittest
from unittest.mock import patch

from knight_flow.mac_support import IS_MAC
from tests.tk_support import probe_error as _ROOT_ERROR


@unittest.skipUnless(IS_MAC, "the fullscreen guard on macOS")
@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class ThePillMustHideOverFullscreenAppsTests(unittest.TestCase):
    """The guard exists so push-to-talk never draws a bar across a game or film.

    Its implementation was entirely win32 and returned False off Windows, so on
    macOS the Pill sat on top of fullscreen content and "hide over fullscreen
    media" -- on by default -- was another setting that did nothing.
    """

    def _window(self, pid: int, *, layer: int = 0, x=0, y=0, w=1920, h=1080) -> dict:
        return {
            "kCGWindowOwnerPID": pid,
            "kCGWindowLayer": layer,
            "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h},
        }

    def _screens(self) -> list[dict]:
        return [{"index": 0, "primary": True, "x": 0, "y": 0, "width": 1920, "height": 1080,
                 "work_x": 0, "work_y": 30, "work_width": 1920, "work_height": 974}]

    def _run(self, windows, *, front_pid=4242, self_pid=999):
        from knight_flow import mac_support as ms

        app = unittest.mock.MagicMock()
        app.processIdentifier.return_value = front_pid
        workspace = unittest.mock.MagicMock()
        workspace.sharedWorkspace.return_value.frontmostApplication.return_value = app
        quartz = unittest.mock.MagicMock()
        quartz.CGWindowListCopyWindowInfo.return_value = windows
        with patch.dict("sys.modules", {"Quartz": quartz, "AppKit": unittest.mock.MagicMock(NSWorkspace=workspace)}), \
             patch.object(ms, "list_screens", return_value=self._screens()), \
             patch("os.getpid", return_value=self_pid):
            return ms.frontmost_window_is_fullscreen()

    def test_a_window_covering_the_whole_screen_counts(self) -> None:
        """Fullscreen on macOS covers the menu bar and Dock too, which is what
        separates it from a merely maximised window."""
        self.assertTrue(self._run([self._window(4242)]))

    def test_a_maximised_window_does_not_count(self) -> None:
        """Filling the work area leaves the menu bar and Dock visible; the Pill
        should stay, because nothing is being watched fullscreen."""
        self.assertFalse(self._run([self._window(4242, y=30, h=974)]))

    def test_our_own_pill_never_hides_itself(self) -> None:
        """The Pill is always frontmost-adjacent and full-width on some setups;
        counting it would make the app hide itself and look crashed."""
        self.assertFalse(self._run([self._window(999)], front_pid=999, self_pid=999))

    def test_overlay_layers_are_ignored(self) -> None:
        """Panels and HUDs sit above layer 0 and are never the content."""
        self.assertFalse(self._run([self._window(4242, layer=25)]))

    def test_no_windows_means_no_hiding(self) -> None:
        self.assertFalse(self._run([]))

    def test_the_overlay_consults_it(self) -> None:
        from tests.tk_support import acquire_root, release_root

        from knight_flow import mac_support as ms
        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(lambda: release_root(overlay.root))
        with patch.object(ms, "frontmost_window_is_fullscreen", return_value=True):
            self.assertTrue(overlay._foreground_is_fullscreen())
        with patch.object(ms, "frontmost_window_is_fullscreen", return_value=False):
            self.assertFalse(overlay._foreground_is_fullscreen())


if __name__ == "__main__":
    unittest.main()
