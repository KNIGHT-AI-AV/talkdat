from __future__ import annotations

import unittest

from knight_flow.capture_timing import pcm_duration_ms, should_extend_min_capture


class CaptureTimingTests(unittest.TestCase):
    def test_pcm_duration_uses_pcm16_bytes(self) -> None:
        self.assertAlmostEqual(pcm_duration_ms(16000, 16000, 1), 500.0)

    def test_voice_shorter_than_minimum_extends(self) -> None:
        self.assertTrue(
            should_extend_min_capture(
                16000,
                16000,
                1,
                heard_voice=True,
                min_capture_ms=900,
            )
        )

    def test_no_voice_does_not_extend(self) -> None:
        self.assertFalse(
            should_extend_min_capture(
                16000,
                16000,
                1,
                heard_voice=False,
                min_capture_ms=900,
            )
        )

    def test_enough_audio_does_not_extend(self) -> None:
        self.assertFalse(
            should_extend_min_capture(
                32000,
                16000,
                1,
                heard_voice=True,
                min_capture_ms=900,
            )
        )


if __name__ == "__main__":
    unittest.main()
