"""X-460: Setup fits its step instead of scrolling.

"WHY DO I MUST SCROLL IN MENUS!!!!! FIX SCALING!!!!" with Setup on the
speech-route step: a scrollbar, the account button cut off, the card titles
clipped to "Talk DA1" and "Private on-d". A step, once laid out, measures
what it needs and the window grows by the overflow as far as the monitor's
work area allows. Grow only, once per render. The route cards put the badge
above the title.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIZARD = (ROOT / "knight_flow" / "ui" / "onboarding.py").read_text(encoding="utf-8")


def block(pattern: str) -> str:
    found = re.search(pattern, WIZARD, re.S)
    assert found, "anchor moved: " + pattern
    return found.group(0)


class TheWindowGrowsToTheStepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fit = block(r"def _fit_window_to_step\(self\) -> None:.*?\n    def _cancel_content_extent_sync")

    def test_every_step_render_schedules_one_fit(self) -> None:
        render = block(r"def render_step\(self, index: int\) -> None:.*?self\._store_resume_receipt\(\)")
        self.assertIn("self._queue_content_extent_sync()\n", render)
        self.assertIn("self._queue_fit_to_step()", render)
        self.assertLess(render.index("_queue_content_extent_sync"), render.index("_queue_fit_to_step"),
                        "measure after the extent sync, or the number is stale")

    def test_the_fit_measures_the_real_overflow(self) -> None:
        self.assertIn("viewport_height = int(self.content_canvas.winfo_height())", self.fit)
        self.assertIn("required_height = int(self.content.winfo_reqheight())", self.fit)
        self.assertIn("if viewport_height <= 1 or required_height <= viewport_height:", self.fit)

    def test_it_grows_only_within_the_work_area(self) -> None:
        self.assertIn("bottom = self._work_area_bottom()", self.fit)
        self.assertIn("room = bottom - (y + height) - self.px(8)", self.fit)
        self.assertIn("grow = min(overflow, max(0, room))", self.fit)
        self.assertIn('self.window.geometry(f"{width}x{height + grow}+{x}+{y}")', self.fit)
        self.assertNotIn("height - grow", self.fit, "grow only; never shrink a size the person chose")
        work = block(r"def _work_area_bottom\(self\) -> int:.*?\n    def _fit_window_to_step")
        self.assertIn('getattr(self.host, "_active_monitor_work_area", None)', work)
        self.assertIn("winfo_screenheight()", work, "a Mac or a test has no monitor API")

    def test_a_low_window_is_lifted_to_make_room(self) -> None:
        self.assertIn("if grow < overflow and y > self.px(24):", self.fit)
        self.assertIn("lift = min(overflow - grow, y - self.px(24))", self.fit)

    def test_once_per_step_render(self) -> None:
        self.assertIn("if self._fit_served_step == self.step_index:", self.fit)
        self.assertIn("self._fit_served_step = self.step_index", self.fit)
        teardown = block(r"def _cancel_content_extent_sync\(self\) -> None:.*?self\._content_extent_after = None")
        self.assertIn("fit = self._fit_after", teardown)


class TheRouteCardsKeepTheirTitlesTests(unittest.TestCase):
    def test_the_badge_is_an_eyebrow_above_the_title(self) -> None:
        voice = block(r"def _render_voice\(self\) -> None:.*?\n    def _activate_route_control")
        self.assertIn('badge_label.grid(row=0, column=0, sticky="w"', voice)
        self.assertIn('radio.grid(row=1, column=0, sticky="ew")', voice)
        self.assertNotIn('badge_label.grid(row=0, column=1, sticky="e"', voice)


if __name__ == "__main__":
    unittest.main()
