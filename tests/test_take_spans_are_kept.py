"""T9 wiring: a take's clipped, silent and noisy spans are found from its kept
audio, cached beside it, and one span can be cut out for a replay or a retry.
Synthetic audio in a scratch data folder; no device.
"""
from __future__ import annotations

import math
import os
import struct
import tempfile
import unittest
from unittest.mock import patch

from knight_flow.audio_spool import safety_session, session_spans, span_audio_of, start_safety_capture

RATE = 16000


def take() -> bytes:
    speech = [int(0.22 * (1.0 if (i / RATE * 4.0) % 1.0 < 0.6 else 0.04) * 32767
                  * math.sin(2 * math.pi * 140 * i / RATE)) for i in range(RATE * 2)]
    clipped = [32767 if (i // 20) % 2 else -32768 for i in range(RATE)]
    samples = speech + clipped + speech
    return struct.pack(f"<{len(samples)}h", *samples)


class SpansAreKeptWithTheTake(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.environ.get("TALK_DAT_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["TALK_DAT_HOME"] = self._tmp.name
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        capture.append(take(), RATE, 1, heard_voice=True)
        capture.finalize(status="complete")
        self.session_id = capture.session_id

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old
        self._tmp.cleanup()

    def test_the_clipped_span_is_found_and_cached(self) -> None:
        spans = session_spans(self.session_id)
        self.assertEqual([span["kind"] for span in spans], ["clipped"])
        self.assertAlmostEqual(spans[0]["start_ms"], 2000, delta=200)
        self.assertAlmostEqual(spans[0]["end_ms"], 3000, delta=200)
        self.assertEqual(safety_session(self.session_id)["audio_spans"]["spans"], spans)
        with patch("knight_flow.audio_spans.analyze_spans", side_effect=AssertionError("recomputed")):
            self.assertEqual(session_spans(self.session_id), spans)

    def test_one_span_is_cut_out_with_context(self) -> None:
        (span,) = session_spans(self.session_id)
        part, rate, channels = span_audio_of(self.session_id, span, context_ms=300)
        self.assertEqual((rate, channels), (RATE, 1))
        self.assertAlmostEqual(len(part) / (RATE * 2) * 1000, span["end_ms"] - span["start_ms"] + 600, delta=5)

    def test_an_unknown_take_has_no_spans(self) -> None:
        self.assertEqual(session_spans("no-such-take"), [])


if __name__ == "__main__":
    unittest.main()
