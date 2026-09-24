from __future__ import annotations

import unittest

from knight_flow.captions import LINES, MAX_LINE_CHARS, CaptionBuffer


class TheStripNeverJumpsBackwardsTests(unittest.TestCase):
    """X-32. Partials replace each other; finals commit; the window shows a
    steady two-line tail a viewer can actually read."""

    def test_partials_replace_never_stack(self) -> None:
        buffer = CaptionBuffer()
        buffer.update("hello", False)
        buffer.update("hello there", False)
        buffer.update("hello there friend", False)
        self.assertEqual(buffer.lines(), ["hello there friend"])

    def test_a_final_commits_and_the_next_partial_rides_below(self) -> None:
        buffer = CaptionBuffer()
        buffer.update("first sentence lands", True)
        buffer.update("second one coming", False)
        self.assertEqual(buffer.lines(), ["first sentence lands", "second one coming"])

    def test_only_the_last_lines_show(self) -> None:
        buffer = CaptionBuffer()
        for index in range(6):
            buffer.update(f"sentence number {index} has landed here", True)
        self.assertEqual(len(buffer.lines()), LINES)
        self.assertIn("number 5", buffer.lines()[-1])

    def test_long_speech_wraps_at_the_readable_width(self) -> None:
        buffer = CaptionBuffer()
        buffer.update("word " * 40, False)
        for line in buffer.lines():
            self.assertLessEqual(len(line), MAX_LINE_CHARS)

    def test_empty_updates_change_nothing(self) -> None:
        buffer = CaptionBuffer()
        buffer.update("", False)
        buffer.update("   ", True)
        self.assertEqual(buffer.lines(), [])


if __name__ == "__main__":
    unittest.main()
