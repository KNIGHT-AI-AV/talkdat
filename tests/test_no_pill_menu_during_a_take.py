"""X-622 (interaction grid D7): no Pill menu while the mic is open or a result is landing.

Right-clicking the Pill during a take opened the menu, and the menu window
activates and takes keyboard focus. When the take ended it pasted into the
menu window, not into the app the person was writing in, and nothing guards
a paste into our own windows. Anything that moves focus mid-take is a lost
dictation.

Now the press is refused while the Pill is live or processing, and its
release gets the ACK. When the Pill is idle the menu opens as before. The
launch's "Preparing microphone" is painted as processing too, so when the app
says no take is in flight, the menu opens.

Runs through scripts/run_tests_offscreen.py.
"""
from __future__ import annotations

import unittest

from tests.pill_harness import body_point, build_overlay, canvas_point, destroy_overlay, pump


class NoMenuDuringATakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.menus: list[tuple[int, int]] = []
        self.in_flight = True

        def web_menu(x: int, y: int) -> bool:
            self.menus.append((x, y))
            return True

        self.overlay = build_overlay({"web_menu": web_menu, "take_in_flight": lambda: self.in_flight})

    def tearDown(self) -> None:
        destroy_overlay(self.overlay)

    def right_click(self) -> None:
        cx, cy, rx, ry = canvas_point(self.overlay, *body_point(self.overlay))
        self.overlay.canvas.event_generate("<ButtonPress-3>", x=cx, y=cy, rootx=rx, rooty=ry)
        self.acks_after_press = self.overlay._ack_counts.get("pill", 0)
        self.overlay.canvas.event_generate("<ButtonRelease-3>", x=cx, y=cy, rootx=rx, rooty=ry)

    def test_no_menu_while_listening_and_the_release_acks(self) -> None:
        self.overlay.set_state("listening", "Hands-free: toggle to stop.")
        pump(self.overlay.root, 0.3)
        self.right_click()
        self.assertEqual(self.menus, [], "the menu opened mid-take and would take the focus")
        self.assertEqual(self.acks_after_press, 0, "the ACK played on the press")
        self.assertEqual(self.overlay._ack_counts.get("pill"), 1)

    def test_no_menu_while_a_result_is_landing(self) -> None:
        self.overlay.set_state("processing", "Formatting transcript.")
        pump(self.overlay.root, 0.2)
        self.right_click()
        self.assertEqual(self.menus, [])
        self.assertEqual(self.overlay._ack_counts.get("pill"), 1)

    def test_the_idle_pill_opens_its_menu(self) -> None:
        self.right_click()
        self.assertEqual(len(self.menus), 1)
        self.assertIsNone(self.overlay._ack_counts.get("pill"))

    def test_preparing_the_microphone_at_launch_is_not_a_take(self) -> None:
        self.in_flight = False
        self.overlay.set_state("processing", "Preparing microphone.")
        pump(self.overlay.root, 0.2)
        self.right_click()
        self.assertEqual(len(self.menus), 1)


if __name__ == "__main__":
    unittest.main()
