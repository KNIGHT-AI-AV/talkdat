from __future__ import annotations

import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from knight_flow.audio_spool import (
    list_safety_sessions,
    recover_interrupted_sessions,
    save_safety_recording,
    start_safety_capture,
)


class AudioSpoolTests(unittest.TestCase):
    def test_safety_recordings_rotate_to_limit(self) -> None:
        pcm = b"\x01\x00" * 1600
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("knight_flow.audio_spool.app_dir", return_value=root):
                for index in range(7):
                    saved = save_safety_recording(
                        pcm,
                        sample_rate=16000,
                        channels=1,
                        reason=f"retry-{index}",
                        limit=5,
                    )
                    self.assertIsNotNone(saved)

                recordings = sorted((root / "audio-spool").glob("*.wav"))
                self.assertEqual(len(recordings), 5)
                self.assertTrue(all(path.stat().st_size > len(pcm) for path in recordings))
                self.assertEqual(len({path.name for path in recordings}), 5)
                self.assertEqual(len(list_safety_sessions(5)), 5)

    def test_capture_is_playable_while_session_is_still_recording(self) -> None:
        pcm = b"\x01\x08" * 3200
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("knight_flow.audio_spool.app_dir", return_value=root):
                capture = start_safety_capture(
                    mode="dictation",
                    control="hold",
                    provider="local",
                    model="test-model",
                )
                capture.append(pcm, 16000, 1, heard_voice=True)
                self.assertTrue(capture.flush())

                with wave.open(str(capture.audio_path), "rb") as wav:
                    self.assertEqual(wav.getframerate(), 16000)
                    self.assertEqual(wav.getnchannels(), 1)
                    self.assertEqual(wav.readframes(wav.getnframes()), pcm)

                item = list_safety_sessions(5)[0]
                self.assertEqual(item["status"], "recording")
                self.assertGreaterEqual(item["duration_ms"], 190)
                capture.finalize(status="delivered", raw_transcript="testing", final_text="Testing.")

    def test_startup_marks_interrupted_capture_recoverable(self) -> None:
        pcm = b"\x01\x08" * 1600
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("knight_flow.audio_spool.app_dir", return_value=root):
                capture = start_safety_capture(
                    mode="dictation",
                    control="hold",
                    provider="deepgram",
                    model="nova-3",
                )
                capture.append(pcm, 16000, 1, heard_voice=True)
                self.assertTrue(capture.flush())
                closed = threading.Event()
                capture._queue.put(("close", closed))
                self.assertTrue(closed.wait(2))
                capture._thread.join(2)

                self.assertEqual(recover_interrupted_sessions(), 1)
                item = list_safety_sessions(5)[0]
                self.assertEqual(item["status"], "interrupted")
                self.assertTrue(item["has_audio"])
                self.assertGreater(item["audio_bytes"], 0)


if __name__ == "__main__":
    unittest.main()


class DigitalSilenceIsNotTheSameAsNotSpeakingTests(unittest.TestCase):
    """macOS answers a refused microphone with silence, not an error.

    The capture succeeds, every sample is zero, the transcript comes back empty
    and the default message tells the person they did not speak -- which is
    wrong and gives them nothing to act on. Measured during the macOS port: ten
    seconds of capture with speech playing aloud the whole time returned a peak
    amplitude of exactly 0.
    """

    def test_all_zero_samples_are_recognised(self) -> None:
        from knight_flow.audio_input import is_digitally_silent

        self.assertTrue(is_digitally_silent(b"\x00" * 3200))

    def test_a_noise_floor_is_not_silence(self) -> None:
        """A working microphone in a quiet room still delivers something. Only
        exact zeros mean nothing arrived, so a faint room must not be blamed on
        permissions."""
        from knight_flow.audio_input import is_digitally_silent

        quiet = b"".join((1).to_bytes(2, "little", signed=True) for _ in range(1600))
        self.assertFalse(is_digitally_silent(quiet))

    def test_no_audio_at_all_is_left_to_its_existing_handling(self) -> None:
        from knight_flow.audio_input import is_digitally_silent

        self.assertFalse(is_digitally_silent(b""))


class TheMicrophonePermissionAnswerIsHonestTests(unittest.TestCase):
    """The first version of this always said yes.

    It imported AVFoundation, which pyobjc ships separately and which is not a
    dependency, so every call fell into its own except clause and reported the
    microphone as usable. A check that cannot fail is worse than no check,
    because it reads as evidence that something was verified.
    """

    def test_the_answer_is_one_of_four_known_states(self) -> None:
        from knight_flow.mac_support import microphone_permission

        self.assertIn(microphone_permission(), {"granted", "denied", "not asked", "unknown"})

    def test_only_a_definite_refusal_counts_as_unusable(self) -> None:
        from unittest.mock import patch

        from knight_flow import mac_support

        for state, usable in (
            ("granted", True), ("not asked", True), ("unknown", True), ("denied", False),
        ):
            with self.subTest(state=state), patch.object(
                mac_support, "microphone_permission", return_value=state
            ):
                self.assertEqual(mac_support.has_microphone_permission(), usable)
