from __future__ import annotations

import unittest

from knight_flow.progressive import (
    MIN_SEGMENT_SECONDS,
    SILENCE_CLOSE_SECONDS,
    VOICE_LEVEL,
    SegmentPlanner,
)


def feed_seconds(planner: SegmentPlanner, seconds: float, level: float, *, rate: int = 16000):
    """Feed audio in 100ms chunks at the given level; return closed spans."""
    spans = []
    chunk = int(rate * 0.1) * 2  # 100ms of mono PCM16
    for _ in range(int(seconds * 10)):
        span = planner.observe(chunk, level)
        if span:
            spans.append(span)
    return spans


class SegmentsCloseAtClauseBoundariesTests(unittest.TestCase):
    """X-31. The planner's rules ARE the latency win: enough voiced speech
    plus a real pause closes a segment for early transcription; anything
    less stays whole for the single-shot path."""

    def test_short_speech_never_closes(self) -> None:
        planner = SegmentPlanner(16000)
        spans = feed_seconds(planner, 3.0, VOICE_LEVEL + 0.01)
        spans += feed_seconds(planner, 2.0, 0.0)
        self.assertEqual(spans, [], "three seconds of speech must stay whole")

    def test_a_long_clause_plus_a_pause_closes(self) -> None:
        planner = SegmentPlanner(16000)
        spans = feed_seconds(planner, MIN_SEGMENT_SECONDS + 1.0, VOICE_LEVEL + 0.01)
        self.assertEqual(spans, [])
        spans = feed_seconds(planner, SILENCE_CLOSE_SECONDS + 0.2, 0.0)
        self.assertEqual(len(spans), 1)
        start, end = spans[0]
        self.assertEqual(start, 0)
        self.assertGreater(end, 0)

    def test_segments_chain_without_gaps_or_overlap(self) -> None:
        planner = SegmentPlanner(16000)
        all_spans = []
        for _ in range(3):
            all_spans += feed_seconds(planner, MIN_SEGMENT_SECONDS + 1.0, VOICE_LEVEL + 0.01)
            all_spans += feed_seconds(planner, SILENCE_CLOSE_SECONDS + 0.2, 0.0)
        self.assertEqual(len(all_spans), 3)
        for (first_start, first_end), (second_start, _s) in zip(all_spans, all_spans[1:]):
            self.assertEqual(first_end, second_start, "spans must tile exactly")
        tail_start, tail_end = planner.tail_span()
        self.assertEqual(tail_start, all_spans[-1][1])
        self.assertGreaterEqual(tail_end, tail_start)

    def test_breaths_do_not_close_segments(self) -> None:
        planner = SegmentPlanner(16000)
        spans = feed_seconds(planner, MIN_SEGMENT_SECONDS + 1.0, VOICE_LEVEL + 0.01)
        spans += feed_seconds(planner, 0.3, 0.0)  # a breath, not a pause
        self.assertEqual(spans, [])
        spans += feed_seconds(planner, 2.0, VOICE_LEVEL + 0.01)
        self.assertEqual(spans, [], "speech resumed; still one segment")


if __name__ == "__main__":
    unittest.main()
