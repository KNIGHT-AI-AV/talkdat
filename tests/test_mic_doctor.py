from __future__ import annotations

import math
import unittest

from knight_flow.mic_doctor import analyze_sample, health_warning


def tone_with_pauses(amplitude: int, *, seconds: float = 2.0, rate: int = 16000, noise: int = 0) -> bytes:
    """Half-second bursts of 'speech' separated by pauses of room noise."""
    out = bytearray()
    for index in range(int(seconds * rate)):
        in_burst = (index // (rate // 2)) % 2 == 0
        value = int(amplitude * math.sin(2 * math.pi * index / 160)) if in_burst else 0
        value += int(noise * math.sin(2 * math.pi * index / 37))
        value = max(-32768, min(32767, value))
        out += int(value).to_bytes(2, "little", signed=True)
    return bytes(out)


class TwentySecondsPreventsRefundsTests(unittest.TestCase):
    """X-27. One sample, one verdict a person can act on. The thresholds are
    the shipped staging; each case below is a support ticket this replaces."""

    def test_a_healthy_mic_says_so(self) -> None:
        report = analyze_sample(tone_with_pauses(6000, noise=30))
        self.assertEqual(report.verdict, "ok")
        self.assertTrue(report.healthy)
        self.assertEqual(health_warning(report), "")

    def test_silence_reads_as_dead_not_quiet(self) -> None:
        report = analyze_sample(b"\x00\x00" * 16000)
        self.assertEqual(report.verdict, "dead")
        self.assertIn("microphone", report.advice.lower())

    def test_a_whisper_level_mic_reads_too_quiet(self) -> None:
        report = analyze_sample(tone_with_pauses(200))
        self.assertEqual(report.verdict, "too_quiet")

    def test_a_clipping_mic_reads_too_hot(self) -> None:
        report = analyze_sample(tone_with_pauses(32760))
        self.assertEqual(report.verdict, "too_hot")
        self.assertGreater(report.clipping_ratio, 0.02)

    def test_a_loud_room_reads_noisy(self) -> None:
        report = analyze_sample(tone_with_pauses(3000, noise=1400))
        self.assertEqual(report.verdict, "noisy")

    def test_empty_audio_is_survivable(self) -> None:
        report = analyze_sample(b"")
        self.assertEqual(report.verdict, "dead")

    def test_every_unhealthy_verdict_has_a_warning_line(self) -> None:
        for verdict_audio in (b"\x00\x00" * 16000, tone_with_pauses(200), tone_with_pauses(32760)):
            report = analyze_sample(verdict_audio)
            with self.subTest(verdict=report.verdict):
                self.assertTrue(health_warning(report))


if __name__ == "__main__":
    unittest.main()
