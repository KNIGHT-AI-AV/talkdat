"""T9: twenty synthetic takes with clipped, silent, noisy and clean stretches.
Each injected fault is found within 200 ms of where it was put; clean takes
report nothing. Synthetic PCM only.
"""
from __future__ import annotations

import math
import random
import struct
import unittest

from knight_flow.audio_spans import analyze_spans, as_metadata, span_audio, Span

RATE = 16000
TOLERANCE_MS = 200


def speech(seconds: float, seed: int, level: float = 0.22) -> list[int]:
    """Speech-shaped: a moving voiced tone gated into syllables with pauses."""
    rng = random.Random(seed)
    out = []
    for index in range(int(seconds * RATE)):
        t = index / RATE
        gate = 1.0 if (t * 4.0) % 1.0 < 0.6 else 0.04
        pitch = 120 + 30 * math.sin(t * 2.3)
        value = level * gate * (0.6 * math.sin(2 * math.pi * pitch * t) + 0.4 * math.sin(2 * math.pi * 3 * pitch * t))
        out.append(int(max(-1.0, min(1.0, value + rng.uniform(-0.002, 0.002))) * 32767))
    return out


def clipped(seconds: float) -> list[int]:
    return [32767 if (index // 20) % 2 else -32768 for index in range(int(seconds * RATE))]


def silence(seconds: float) -> list[int]:
    return [0] * int(seconds * RATE)


def noise(seconds: float, seed: int, level: float = 0.12) -> list[int]:
    rng = random.Random(seed)
    return [int(rng.gauss(0, level) * 32767 * 0.9) for _ in range(int(seconds * RATE))]


def pcm(parts: list[list[int]]) -> bytes:
    samples = [max(-32768, min(32767, value)) for part in parts for value in part]
    return struct.pack(f"<{len(samples)}h", *samples)


def build(case: int):
    """(audio, [(kind, start_ms, end_ms)]) for take number ``case``."""
    rng = random.Random(case)
    parts, faults, at = [], [], 0.0
    plan = [("speech", rng.uniform(2.0, 4.0))]
    for _ in range(case % 3 + 1):
        kind = ["clipped", "silent", "noisy"][rng.randrange(3)] if case % 5 else None
        if kind:
            plan.append((kind, {"clipped": rng.uniform(0.4, 1.2), "silent": rng.uniform(2.0, 3.5),
                                "noisy": rng.uniform(1.5, 3.0)}[kind]))
        plan.append(("speech", rng.uniform(2.0, 4.0)))
    for kind, seconds in plan:
        if kind == "speech":
            parts.append(speech(seconds, rng.randrange(10_000)))
        elif kind == "clipped":
            parts.append(clipped(seconds))
        elif kind == "silent":
            parts.append(silence(seconds))
        else:
            parts.append(noise(seconds, rng.randrange(10_000)))
        if kind != "speech":
            faults.append((kind, int(at * 1000), int((at + seconds) * 1000)))
        at += seconds
    return pcm(parts), faults


class EveryFaultIsFound(unittest.TestCase):
    def test_twenty_takes(self):
        missed, extra = [], []
        for case in range(20):
            audio, faults = build(case)
            spans = analyze_spans(audio, sample_rate=RATE)
            for kind, start, end in faults:
                if not any(span.kind == kind and abs(span.start_ms - start) <= TOLERANCE_MS
                           and abs(span.end_ms - end) <= TOLERANCE_MS for span in spans):
                    missed.append((case, kind, start, end, [(s.kind, s.start_ms, s.end_ms) for s in spans]))
            for span in spans:
                if not any(span.kind == kind and span.start_ms < end + TOLERANCE_MS and span.end_ms > start - TOLERANCE_MS
                           for kind, start, end in faults):
                    extra.append((case, span))
        self.assertEqual(missed, [])
        self.assertEqual(extra, [], "a clean stretch was reported")

    def test_clean_takes_report_nothing(self):
        for seed in range(5):
            audio = pcm([speech(8.0, seed)])
            self.assertEqual(analyze_spans(audio, sample_rate=RATE), [], f"seed {seed}")

    def test_a_pause_between_sentences_is_not_silence(self):
        for pause in (0.5, 1.2):
            audio = pcm([speech(2.0, 7), silence(pause), speech(2.0, 8)])
            self.assertEqual(analyze_spans(audio, sample_rate=RATE), [], f"{pause} s pause")


class ReviewOnlyThePartThatFailed(unittest.TestCase):
    def test_span_audio_is_the_span_with_context(self):
        audio = pcm([speech(2.0, 1), clipped(1.0), speech(2.0, 2)])
        (span,) = analyze_spans(audio, sample_rate=RATE)
        part = span_audio(audio, span, sample_rate=RATE, context_ms=300)
        self.assertEqual(len(part) % 2, 0)
        expected_ms = span.duration_ms + 600
        self.assertAlmostEqual(len(part) / (RATE * 2) * 1000, expected_ms, delta=5)

    def test_listening_to_spans_beats_the_whole_take(self):
        listened_spans = listened_whole = 0.0
        for case in range(20):
            audio, faults = build(case)
            if not faults:
                continue
            spans = analyze_spans(audio, sample_rate=RATE)
            listened_spans += sum(len(span_audio(audio, span, sample_rate=RATE)) for span in spans) / (RATE * 2)
            listened_whole += len(audio) / (RATE * 2)
        saving = 1 - listened_spans / listened_whole
        print(f"\nT9 review audio: spans {listened_spans:.1f} s against whole takes {listened_whole:.1f} s "
              f"({saving:.0%} less to hear; a proxy for review time, not a timed person)")
        self.assertGreaterEqual(saving, 0.25)

    def test_the_recording_is_not_changed(self):
        audio = pcm([speech(2.0, 3), silence(2.0), speech(2.0, 4)])
        before = bytes(audio)
        for span in analyze_spans(audio, sample_rate=RATE):
            span_audio(audio, span, sample_rate=RATE)
        self.assertEqual(audio, before)

    def test_metadata_shape(self):
        self.assertEqual(as_metadata([Span("silent", 100, 2000)]), [{"kind": "silent", "start_ms": 100, "end_ms": 2000}])
        self.assertEqual(analyze_spans(b"", sample_rate=RATE), [])


if __name__ == "__main__":
    unittest.main()
