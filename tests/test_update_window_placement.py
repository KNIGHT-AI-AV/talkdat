from __future__ import annotations

import re
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py").read_text(encoding="utf-8")


class UpdateWindowAppearsAtThePillTests(unittest.TestCase):
    """The reply has to arrive where the question was asked.

    Pop-ups default to a second screen so they do not land on top of whatever
    is being dictated into, which is right for a window someone opened from a
    menu. It is wrong for the answer to an action taken on the Pill itself:
    right-click, Check for updates, and the window appearing on another display
    reads as nothing having happened.
    """

    def test_the_update_window_anchors_to_the_pill(self) -> None:
        # Match the update window constructor itself.  The re-entry safety path
        # calls ``_focus_utility_window("update")`` first; the shorter helper
        # name is a substring of that call and previously made this assertion
        # inspect the refocus callback instead of the window being created.
        match = re.search(
            r'window\s*=\s*self\._utility_window\(\s*"update".*?\)',
            SOURCE,
            re.S,
        )
        assert match is not None
        self.assertIn("anchor_to_pill=True", match.group(0))

    def test_anchoring_uses_the_pill_position_not_a_monitor_centre(self) -> None:
        block = SOURCE[SOURCE.index("def _pill_anchored_geometry"):][:2200]
        self.assertIn("winfo_rootx", block)
        self.assertIn("winfo_rooty", block)

    def test_it_sits_above_the_pill(self) -> None:
        block = SOURCE[SOURCE.index("def _pill_anchored_geometry"):][:2200]
        self.assertIn("pill_y - height", block, "the window belongs above the Pill")

    def test_it_flips_below_when_there_is_no_room_above(self) -> None:
        """The Pill is often near the top of the screen, where a window placed
        above it would be off-display entirely."""
        block = SOURCE[SOURCE.index("def _pill_anchored_geometry"):][:2200]
        self.assertIn("work_top", block)
        self.assertIn("winfo_height()", block)

    def test_it_stays_on_the_display_the_pill_is_on(self) -> None:
        block = SOURCE[SOURCE.index("def _pill_anchored_geometry"):][:2200]
        self.assertIn("m.left <= pill_x < m.right", block)

    def test_failure_falls_back_rather_than_breaking_the_window(self) -> None:
        block = SOURCE[SOURCE.index("def _pill_anchored_geometry"):][:2200]
        self.assertIn("return None", block)
        self.assertIn("if anchored:", SOURCE)


if __name__ == "__main__":
    unittest.main()
