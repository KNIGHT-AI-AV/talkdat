"""X-619 (interaction grid D3, d9): the update dot owns its press.

The dot on the Pill's corner opened the update window through a canvas
tag_bind that returned "break". "break" only stops the canvas ITEM bindings;
the Pill's own press and release bindings still ran, so one click on the dot
opened the update AND started a hands-free take. The dot is 10 px at the
Pill's edge, so a near miss started a take outright.

Pinned here, on a real Pill (run through scripts/run_tests_offscreen.py):
a click on the dot opens the update once and toggles nothing; a click on the
Pill body still toggles once; a press on the dot released off it does
nothing; and hovering the dot says what it is. X-742 made the dot the pip,
a 6 px light set into the Pill's rim 5 px inside its right cap; the press
rules are the same, aimed at its new centre, and the hover's words are said
by the Pill itself.
"""
from __future__ import annotations

import unittest
from unittest import mock

from tests.pill_harness import Counter, body_point, build_overlay, click, destroy_overlay, press, pump, release


class TheUpdateDotOwnsItsPressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hands_free = Counter()
        self.install_update = Counter()
        self.overlay = build_overlay({"hands_free": self.hands_free, "install_update": self.install_update})
        self.overlay.set_update_flag("green")
        pump(self.overlay.root, 0.1)

    def tearDown(self) -> None:
        destroy_overlay(self.overlay)

    def dot(self) -> tuple[int, int]:
        from knight_flow import pill_message

        x, y = pill_message.pip_centre(self.overlay.current_width, self.overlay.current_height,
                                       self.overlay._flag_scale())
        return int(x), int(y)

    def test_a_click_on_the_dot_opens_the_update_and_starts_nothing(self) -> None:
        click(self.overlay, *self.dot())
        pump(self.overlay.root, 0.05)
        self.assertEqual(self.install_update.calls, 1)
        self.assertEqual(self.hands_free.calls, 0, "the dot's click also started a hands-free take")

    def test_a_near_miss_is_still_the_dot(self) -> None:
        x, y = self.dot()
        click(self.overlay, x - 6, y + 6)
        pump(self.overlay.root, 0.05)
        self.assertEqual((self.install_update.calls, self.hands_free.calls), (1, 0))

    def test_the_pill_body_still_toggles_once(self) -> None:
        click(self.overlay, *body_point(self.overlay))
        pump(self.overlay.root, 0.05)
        self.assertEqual((self.install_update.calls, self.hands_free.calls), (0, 1))

    def test_a_press_on_the_dot_released_elsewhere_is_never_mind(self) -> None:
        press(self.overlay, *self.dot())
        release(self.overlay, *body_point(self.overlay))
        pump(self.overlay.root, 0.05)
        self.assertEqual((self.install_update.calls, self.hands_free.calls), (0, 0))
        # And the next ordinary click is not swallowed by the abandoned press.
        click(self.overlay, *body_point(self.overlay))
        self.assertEqual(self.hands_free.calls, 1)

    def test_without_a_dot_the_corner_is_ordinary_pill(self) -> None:
        self.overlay.set_update_flag("")
        click(self.overlay, *self.dot())
        self.assertEqual((self.install_update.calls, self.hands_free.calls), (0, 1))

    def test_hovering_the_dot_says_what_it_is(self) -> None:
        x, y = self.dot()
        canvas = self.overlay.canvas
        root_x, root_y = int(canvas.winfo_rootx()) + x, int(canvas.winfo_rooty()) + y
        with mock.patch.object(self.overlay.root, "winfo_pointerxy", return_value=(root_x, root_y)):
            canvas.event_generate("<Motion>", x=x, y=y, rootx=root_x, rooty=root_y)
            pump(self.overlay.root, 0.8)
        view = self.overlay._flag_view
        self.assertIsNotNone(view, "a hover on the dot said nothing")
        self.assertEqual(view.message.title, "Update ready. Click to see it.")


if __name__ == "__main__":
    unittest.main()
