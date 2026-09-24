"""X-460c: Setup's scroll range settles, and the fit waits for the wrap.

The audit found three steps (welcome, controls, superpowers) carrying a
scroll range of thousands of pixels while their content measured ~530.
Labels start life wrapped at 1 px because their master is unmapped when the
first wrap runs; the extent sync measured that skyscraper, and the signature
dedup then refused every later correction. The sync now measures again, as
the one pending callback, until no label is still wrapped at 1-2 px; and the
per-step fit waits for the same before it measures.
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


class TheScrollRangeSettlesTests(unittest.TestCase):
    def test_the_sync_measures_again_while_labels_are_still_wrapping(self) -> None:
        queue = block(r"def _queue_content_extent_sync\(self, _event: tk\.Event \| None = None\) -> None:.*?\n    def _verify_content_extent")
        self.assertIn("if self._labels_still_wrapping() and retries < 20:", queue)
        self.assertIn("self._content_extent_signature = None", queue, "the dedup must not block the correction")
        self.assertIn("self._content_extent_after = self.window.after(60, apply)", queue,
                      "the retry IS the one pending callback, so the Configure-pair collapse still holds")
        self.assertIn('retries = int(getattr(self, "_extent_retries", 0))', queue, "a half-built wizard has no counter yet")

    def test_the_fit_waits_for_the_wrap(self) -> None:
        fit = block(r"def _fit_window_to_step\(self\) -> None:.*?\n    def _fold_art_band")
        self.assertIn("if self._labels_still_wrapping() and self._fit_tries < 12:", fit)
        self.assertIn("self._fit_after = self.window.after(60, self._fit_window_to_step)", fit)
        self.assertIn("self._verify_content_extent()", fit, "measure a fresh extent, never the cached one")
        wrapping = block(r"def _labels_still_wrapping\(self\) -> bool:.*?\n    def _cancel_content_extent_sync")
        self.assertIn('0 < int(widget.cget("wraplength")) <= 2', wrapping)
        self.assertIn('content = getattr(self, "content", None)', wrapping, "a half-built wizard has no content yet")
        self.assertIn("self._fit_tries = 0", block(r"def _queue_fit_to_step\(self\) -> None:.*?\n    def _work_area_bottom"))


if __name__ == "__main__":
    unittest.main()
