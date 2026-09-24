from __future__ import annotations

import datetime as dt
import unittest

from knight_flow.scribe import Chunk, heuristic_summary, merge_turns, render_notes

WHEN = dt.datetime(2026, 8, 9, 16, 0)


class TwoTracksOneTruthTests(unittest.TestCase):
    """X-33. The merge is the product: what the mic heard and what the
    speakers played, interleaved by time into turns a person would have
    typed."""

    def test_turns_interleave_by_time(self) -> None:
        chunks = [
            Chunk("You", 0.0, "So about the deadline"),
            Chunk("Them", 4.0, "We can do Friday"),
            Chunk("You", 9.0, "Friday works, send the contract"),
        ]
        turns = merge_turns(chunks)
        self.assertEqual([speaker for speaker, _ in turns], ["You", "Them", "You"])

    def test_consecutive_same_speaker_chunks_fuse(self) -> None:
        chunks = [
            Chunk("You", 0.0, "First thirty seconds of me talking"),
            Chunk("You", 30.0, "and the next thirty carries straight on"),
            Chunk("Them", 45.0, "then they answer"),
        ]
        turns = merge_turns(chunks)
        self.assertEqual(len(turns), 2)
        self.assertIn("carries straight on", turns[0][1])

    def test_silent_chunks_vanish(self) -> None:
        chunks = [Chunk("Them", 0.0, "   "), Chunk("You", 2.0, "hello")]
        self.assertEqual(merge_turns(chunks), [("You", "hello")])

    def test_decision_sentences_lead_the_summary(self) -> None:
        turns = [
            ("You", "The weather is nice today. We agreed the deadline is Friday."),
            ("Them", "I will send the contract tomorrow. My cat is orange."),
        ]
        summary = heuristic_summary(turns)
        self.assertTrue(summary[0].startswith(("We agreed", "I will")))
        joined = " ".join(summary[:2])
        self.assertIn("deadline", joined.lower())
        self.assertIn("contract", joined.lower())

    def test_the_document_reads_summary_first_then_both_sides(self) -> None:
        turns = [("You", "Question about pricing."), ("Them", "It is twenty nine dollars.")]
        body = render_notes(turns, ["It is twenty nine dollars."], WHEN)
        self.assertLess(body.index("## Summary"), body.index("## Transcript"))
        self.assertIn("**You:** Question about pricing.", body)
        self.assertIn("**Them:** It is twenty nine dollars.", body)
        self.assertIn("Talk DAT! Scribe", body)


if __name__ == "__main__":
    unittest.main()
