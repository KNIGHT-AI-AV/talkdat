"""X-405: the progressive pipeline must actually close segments during a hold.

On 2026-09-03 a 67-second dictation on the founder's PC transcribed nothing
until release and then took 32 seconds. The segment planner compared the
post-front-end level against a fixed 0.025 floor; the adaptive gain lifts
every pause toward the speech target, so the level never dropped under it
once in 67 seconds and no segment closed. The gate below judges each chunk
against the recording's own floor and speech level instead, and the session
feeds it the raw microphone level.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from knight_flow.progressive import MIN_SEGMENT_SECONDS, SILENCE_CLOSE_SECONDS, SegmentPlanner, VoiceGate

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = (ROOT / "knight_flow" / "stt_sessions.py").read_text(encoding="utf-8")
CHUNK = 0.02


def levels(pattern: list[tuple[float, float]]) -> list[float]:
    out: list[float] = []
    for seconds, level in pattern:
        out.extend([level] * int(round(seconds / CHUNK)))
    return out


def closed_segments(sequence: list[float], sample_rate: int = 16000) -> list[float]:
    planner = SegmentPlanner(sample_rate, 1)
    gate = VoiceGate()
    chunk_bytes = int(sample_rate * CHUNK) * 2
    closed = []
    for level in sequence:
        span = planner.observe(chunk_bytes, level, voiced=gate.voiced(level))
        if span:
            closed.append((span[1] - span[0]) / (2 * sample_rate))
    return closed


class VoiceGateTests(unittest.TestCase):
    def test_a_quiet_room_with_normal_speech_closes_at_every_pause(self) -> None:
        sequence = levels([(0.5, 0.01), (6.0, 0.4), (0.8, 0.012), (6.0, 0.5), (0.8, 0.01), (2.0, 0.45)])
        closed = closed_segments(sequence)
        self.assertEqual(len(closed), 2, closed)
        self.assertGreaterEqual(min(closed), MIN_SEGMENT_SECONDS)

    def test_a_noisy_room_still_finds_the_pauses(self) -> None:
        # A fan at 0.09 would never drop under the old fixed floor of 0.025.
        sequence = levels([(0.5, 0.09), (6.0, 0.6), (0.9, 0.1), (6.0, 0.55), (0.9, 0.09), (1.0, 0.6)])
        self.assertEqual(len(closed_segments(sequence)), 2)

    def test_a_breath_between_words_does_not_close_a_segment(self) -> None:
        sequence = levels([(0.3, 0.01), (6.0, 0.5), (0.3, 0.01), (6.0, 0.5)])
        self.assertEqual(closed_segments(sequence), [])

    def test_the_floor_follows_the_room_but_never_jumps_to_speech(self) -> None:
        gate = VoiceGate()
        for _ in range(50):
            gate.voiced(0.02)
        for _ in range(100):
            gate.voiced(0.6)
        self.assertLess(gate.floor, 0.1)
        self.assertGreater(gate.speech, 0.4)
        self.assertFalse(gate.voiced(0.05))
        self.assertTrue(gate.voiced(0.3))

    def test_the_planner_without_a_gate_keeps_the_legacy_threshold(self) -> None:
        planner = SegmentPlanner(16000, 1)
        chunk_bytes = int(16000 * CHUNK) * 2
        for _ in range(int((MIN_SEGMENT_SECONDS + 1) / CHUNK)):
            planner.observe(chunk_bytes, 0.5)
        span = None
        for _ in range(int((SILENCE_CLOSE_SECONDS + 0.1) / CHUNK)):
            span = planner.observe(chunk_bytes, 0.01) or span
        self.assertIsNotNone(span)


class TheSessionFeedsTheGateTests(unittest.TestCase):
    def test_the_gate_reads_the_raw_microphone_level(self) -> None:
        self.assertIn('"gate": VoiceGate()', SESSIONS)
        self.assertRegex(SESSIONS, re.compile(r'voiced=progressive\["gate"\]\.voiced\(rms_level\(raw_data\)\)'))

    def test_release_logs_how_much_was_left_to_transcribe(self) -> None:
        self.assertIn("progressive: %d segments closed during the hold", SESSIONS)


if __name__ == "__main__":
    unittest.main()


class LocalTranscriptionHonoursItsInputTests(unittest.TestCase):
    """The local path transcribed the WHOLE buffer whatever WAV it was handed,
    so each progressive segment carried the entire take so far and the
    release joined the same sentences several times over."""

    def test_pcm_is_taken_from_the_wav_it_was_given(self) -> None:
        import io
        import wave

        from knight_flow.stt_sessions import pcm16_from_wav

        frames = bytes(range(0, 200, 2)) * 4
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(frames)
        self.assertEqual(pcm16_from_wav(buffer.getvalue()), frames)
        self.assertEqual(pcm16_from_wav(b"not a wav"), b"")

    def test_the_session_no_longer_reads_the_whole_buffer_for_a_segment(self) -> None:
        body = SESSIONS.split("def _transcribe_local", 1)[1].split("def ", 1)[0]
        self.assertIn("pcm16_from_wav(wav_bytes)", body)
        self.assertNotIn("pcm16=bytes(self._audio)", body)
