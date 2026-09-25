"""X-629 (interaction grid D11, d10): messages never take focus; hover holds one; an info never replaces an unread error.

Toasts, the learned-word pop-over and the small update pop-over were not
no-activate (only the Pill was), so a click to put one away made it the
foreground window and the next paste went there instead of into the
person's app. X-629 gave them the Pill's WS_EX_NOACTIVATE style.

X-742 moved every one of them INTO the Pill (the owner's rule: a message is
the Pill itself changing shape, never a separate piece), so there is no other
window left to style: a message, a word notice and the update offer are all
drawn by the Pill's own no-activate window, and no new window appears. (A real
mouse click cannot be sent from a test without touching the person's own
desktop, so what is checked is the window style Windows reads on that click.)

Hover still holds a message, and an info still waits for an unread error.

Runs through scripts/run_tests_offscreen.py.
"""
from __future__ import annotations

import ctypes
import sys
import unittest
from unittest import mock

from tests.pill_harness import build_overlay, destroy_overlay, pump

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
GA_ROOT = 2


def no_activate(window) -> bool:
    user32 = ctypes.windll.user32
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    getter = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    getter.restype = ctypes.c_ssize_t
    getter.argtypes = [ctypes.c_void_p, ctypes.c_int]
    hwnd = user32.GetAncestor(ctypes.c_void_p(int(window.winfo_id())), GA_ROOT)
    return bool(int(getter(ctypes.c_void_p(hwnd), GWL_EXSTYLE)) & WS_EX_NOACTIVATE)


def settled(overlay, seconds: float = 3.0) -> bool:
    import time

    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        view = overlay._flag_view
        if view is not None and view.phase == "hold":
            return True
        pump(overlay.root, 0.02)
    return False


@unittest.skipUnless(sys.platform == "win32", "the no-activate style is a Windows window style")
class PopOversNeverTakeFocusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.overlay = build_overlay({})
        self.addCleanup(destroy_overlay, self.overlay)
        quiet = mock.patch("knight_flow.meeting_quiet.meeting_in_progress", return_value=False)
        quiet.start()
        self.addCleanup(quiet.stop)

    def assert_on_the_pill(self) -> None:
        overlay = self.overlay
        self.assertTrue(settled(overlay), "the message never showed")
        windows = [child for child in overlay.root.winfo_children() if child.winfo_class() == "Toplevel"]
        self.assertEqual(windows, [], "a message opened a window of its own")
        self.assertTrue(no_activate(overlay.root), "a click on the message would take the focus")

    def test_a_toast_is_the_no_activate_pill(self) -> None:
        self.overlay.show_toast("Talk DAT! is up to date")
        self.assert_on_the_pill()

    def test_the_learned_word_is_the_no_activate_pill(self) -> None:
        self.overlay.offer_learned_word("Kubernetes", lambda _word: None)
        self.assert_on_the_pill()
        self.assertEqual(self.overlay._flag_view.layout.mode, "segment")

    def test_the_update_offer_is_the_no_activate_pill(self) -> None:
        self.overlay.show_update_popover("9.9.9", lambda: None)
        self.assert_on_the_pill()
        self.assertEqual(self.overlay._flag_view.layout.mode, "segment")


class ToastsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.overlay = build_overlay({})
        self.addCleanup(destroy_overlay, self.overlay)
        quiet = mock.patch("knight_flow.meeting_quiet.meeting_in_progress", return_value=False)
        quiet.start()
        self.addCleanup(quiet.stop)

    def test_an_info_never_replaces_an_unread_error(self) -> None:
        overlay = self.overlay
        overlay.show_toast("No sound is reaching the microphone.", detail="Check the input device.", kind="error")
        self.assertTrue(settled(overlay))
        overlay.show_toast("Talk DAT! is up to date")
        pump(overlay.root, 0.3)
        self.assertEqual(overlay._flag_view.message.title, "No sound is reaching the microphone.",
                         "the info erased the error")
        # Read and clicked away: the info that waited comes next.
        overlay._flag_contract()
        pump(overlay.root, 1.2)
        self.assertIsNotNone(overlay._flag_view)
        self.assertEqual(overlay._flag_view.message.title, "Talk DAT! is up to date")

    def test_hover_holds_a_toast(self) -> None:
        overlay = self.overlay
        overlay.flag("Talk DAT! is up to date", hold_ms=200)
        self.assertTrue(settled(overlay))
        view = overlay._flag_view
        x, y, w, h = view.capsule_now
        centre = (view.envelope.x + x + w // 2, view.envelope.y + y + h // 2)
        with mock.patch.object(overlay.root, "winfo_pointerxy", return_value=centre):
            pump(overlay.root, 1.2)
            self.assertIs(overlay._flag_view, view, "the message left under the pointer")
        # Somewhere no window is, rather than wherever the real pointer is.
        with mock.patch.object(overlay.root, "winfo_pointerxy", return_value=(-30000, -30000)):
            pump(overlay.root, 2.2)
        self.assertIsNone(overlay._flag_view, "the message never left once the pointer did")


if __name__ == "__main__":
    unittest.main()
