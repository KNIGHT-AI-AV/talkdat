from __future__ import annotations

import math
import unittest

from knight_flow.audio_front_end import (
    LIMIT_PEAK,
    AdaptiveFrontEnd,
    SILENCE_RMS,
    TARGET_RMS,
    front_end_for,
)
from knight_flow.audio_input import pcm_rms_level


def tone(amplitude: int, samples: int = 1600) -> bytes:
    """A 100Hz-ish sine chunk at 16kHz -- one tenth of a second of 'voice'."""
    out = bytearray()
    for index in range(samples):
        value = int(amplitude * math.sin(2 * math.pi * index / 160))
        out += int(value).to_bytes(2, "little", signed=True)
    return bytes(out)


class WhisperingJustWorksTests(unittest.TestCase):
    """X-36. No mode, no switch: a whisper reaches the recognizer at
    conversational level, a shout never clips, and silence is never inflated
    into the model. The numbers here are the shipped default staging."""

    def test_a_whisper_is_lifted_toward_conversational_level(self) -> None:
        front = AdaptiveFrontEnd()
        chunk = tone(400)  # quiet but real -- a whisper through a decent mic
        self.assertGreater(pcm_rms_level(chunk), SILENCE_RMS)
        out = b""
        for _ in range(20):  # two seconds of speaking
            out = front.process(chunk)
        lifted = pcm_rms_level(out)
        self.assertGreater(lifted, pcm_rms_level(chunk) * 4, "the whisper barely moved")
        self.assertGreater(lifted, TARGET_RMS * 0.5, "never reached working level")

    def test_a_shout_is_never_clipped(self) -> None:
        front = AdaptiveFrontEnd()
        for _ in range(10):
            front.process(tone(400))  # gain climbs on quiet speech first
        loud = front.process(tone(30000))  # then a sudden shout
        peak = max(
            abs(int.from_bytes(loud[i : i + 2], "little", signed=True))
            for i in range(0, len(loud), 2)
        )
        self.assertLessEqual(peak, LIMIT_PEAK, "the limiter must catch what the gain pushed")

    def test_silence_is_held_not_amplified(self) -> None:
        """Gain must HOLD through silence: lifting the noise floor between
        sentences feeds the recognizer room tone shaped like speech."""
        front = AdaptiveFrontEnd()
        for _ in range(10):
            front.process(tone(400))
        climbed = front.gain
        for _ in range(20):
            front.process(tone(6))  # effectively silence
        self.assertAlmostEqual(front.gain, climbed, delta=0.01)

    def test_speech_already_at_level_is_left_alone(self) -> None:
        front = AdaptiveFrontEnd()
        healthy = tone(int(TARGET_RMS * 32768 * 1.4142))  # sine RMS = peak/sqrt2
        for _ in range(20):
            front.process(healthy)
        self.assertLess(front.gain, 1.35, "healthy speech should not be pushed")

    def test_manual_settings_survive_as_pre_gain(self) -> None:
        front = front_end_for({"audio": {"gain_boost": 2.0, "adaptive_gain": True}}, 2.0)
        self.assertEqual(front.pre_gain, 2.0)
        disabled = front_end_for({"audio": {"adaptive_gain": False}}, 1.0)
        out = disabled.process(tone(400))
        self.assertEqual(disabled.gain, 1.0)
        self.assertEqual(pcm_rms_level(out), pcm_rms_level(tone(400)))


class PillMeterSeesWhatTheEngineHearsTests(unittest.TestCase):
    """The field regression: the voice wave vanished for quiet mics because
    the Pill metered the RAW microphone, which sits below the visual noise
    floor for exactly the setups the auto-gain exists for. visual_level is
    raw dynamics scaled by the live gain, with the limiter kept out of the
    meter so a hot mic's syllables are never flattened to full scale."""

    def test_a_quiet_mic_still_moves_the_wave(self) -> None:
        front = AdaptiveFrontEnd()
        chunk = tone(400)
        raw = pcm_rms_level(chunk)
        for _ in range(20):
            front.process(chunk)
        self.assertGreater(front.visual_level(raw), raw * 4,
                           "the wave must rise with the same lift the engine got")
        self.assertGreater(front.visual_level(raw), 0.03,
                           "quiet speech must clear the visual noise floor")

    def test_a_hot_mic_is_not_pinned_at_full_scale(self) -> None:
        front = AdaptiveFrontEnd()
        loud = pcm_rms_level(tone(26000))
        softer = pcm_rms_level(tone(13000))
        # Gain stays ~1 for hot input; the meter must preserve the 2:1 shape
        # the limiter would have flattened.
        ratio = front.visual_level(loud) / max(front.visual_level(softer), 1e-9)
        self.assertGreater(ratio, 1.5, "syllable dynamics flattened")
        self.assertLessEqual(front.visual_level(loud), 1.0)

    def test_both_capture_paths_meter_through_visual_level(self) -> None:
        """Source pin: neither session may feed the Pill raw_rms_level
        directly again -- that is the exact line that killed the wave."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "knight_flow"
        for name in ("stt_sessions.py", "deepgram_live.py"):
            source = (root / name).read_text(encoding="utf-8")
            self.assertIn("self.front_end.visual_level(raw_rms_level(raw_data))", source,
                          f"{name}: the meter must run through visual_level")
            self.assertNotIn("_safe_level(raw_rms_level(raw_data))", source,
                             f"{name}: raw metering regressed")


if __name__ == "__main__":
    unittest.main()
