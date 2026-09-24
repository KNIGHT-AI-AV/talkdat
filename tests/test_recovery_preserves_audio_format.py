"""Captured audio must survive recovery without changing its time or samples.

The reference behavior is retained desktop audio available for retry after a
crash, as described in Wispr Flow's Retry and recover a failed transcription
(checked 2026-09-19). These are synthetic PCM fixtures, not a microphone trial.
"""
from __future__ import annotations

import io
import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from knight_flow.audio_spool import read_safety_audio, recover_interrupted_sessions, repair_wav


def recording(pcm: bytes, sample_rate: int = 48000, channels: int = 2) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(pcm)
    return output.getvalue()


class RecoveryPreservesAudioFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch("knight_flow.audio_spool.app_dir", return_value=self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.spool = self.root / "audio-spool"
        self.spool.mkdir()
        self.pcm = struct.pack("<hh", 1200, -800) * 4800

    def test_orphan_recording_keeps_its_actual_sample_rate_and_channels(self) -> None:
        (self.spool / "orphan.wav").write_bytes(recording(self.pcm))
        pcm, rate, channels = read_safety_audio("orphan")
        self.assertEqual((rate, channels), (48000, 2))
        self.assertEqual(pcm, self.pcm)

    def test_stale_checkpoint_does_not_overwrite_the_audio_format(self) -> None:
        (self.spool / "interrupted.wav").write_bytes(recording(self.pcm))
        metadata = {
            "session_id": "interrupted", "audio_file": "interrupted.wav",
            "status": "recording", "sample_rate": 16000, "channels": 1,
        }
        (self.spool / "interrupted.json").write_text(json.dumps(metadata), encoding="utf-8")
        self.assertEqual(recover_interrupted_sessions(), 1)
        actual = json.loads((self.spool / "interrupted.json").read_text(encoding="utf-8"))
        self.assertEqual((actual["sample_rate"], actual["channels"]), (48000, 2))
        self.assertEqual(actual["duration_ms"], 100)
        self.assertEqual(read_safety_audio("interrupted"), (self.pcm, 48000, 2))

    def test_repair_of_stale_lengths_preserves_format_and_all_complete_frames(self) -> None:
        body = bytearray(recording(self.pcm))
        struct.pack_into("<I", body, 4, 36)
        struct.pack_into("<I", body, 40, 0)
        path = self.spool / "lengths.wav"
        path.write_bytes(body)
        self.assertEqual(repair_wav(path, 16000, 1), len(self.pcm))
        with wave.open(str(path), "rb") as stream:
            self.assertEqual((stream.getframerate(), stream.getnchannels()), (48000, 2))
            self.assertEqual(stream.readframes(stream.getnframes()), self.pcm)

    def test_valid_legacy_wav_chunks_are_not_rewritten_as_pcm(self) -> None:
        original = recording(self.pcm)
        extra = b"JUNK" + struct.pack("<I", 8) + b"metadata"
        body = bytearray(original[:36] + extra + original[36:])
        struct.pack_into("<I", body, 4, len(body) - 8)
        path = self.spool / "legacy.wav"
        path.write_bytes(body)
        self.assertEqual(read_safety_audio("legacy"), (self.pcm, 48000, 2))
        self.assertEqual(path.read_bytes(), bytes(body))

    def test_valid_trailing_chunks_remain_outside_the_samples(self) -> None:
        original = recording(self.pcm)
        extra = b"JUNK" + struct.pack("<I", 8) + b"metadata"
        body = bytearray(original + extra)
        struct.pack_into("<I", body, 4, len(body) - 8)
        path = self.spool / "trailing.wav"
        path.write_bytes(body)
        self.assertEqual(read_safety_audio("trailing"), (self.pcm, 48000, 2))
        self.assertEqual(path.read_bytes(), bytes(body))

    def test_unknown_or_incomplete_headers_are_not_replaced_with_guessed_audio(self) -> None:
        for body in (b"short", b"not a valid wave file" * 4):
            with self.subTest(bytes=len(body)):
                path = self.spool / "unknown.wav"
                path.write_bytes(body)
                self.assertEqual(repair_wav(path), 0)
                self.assertEqual(path.read_bytes(), body)

    def test_partial_final_frame_is_not_declared_complete(self) -> None:
        body = bytearray(recording(self.pcm))
        struct.pack_into("<I", body, 4, 36)
        struct.pack_into("<I", body, 40, 0)
        path = self.spool / "partial.wav"
        path.write_bytes(body + b"\x01")
        self.assertEqual(repair_wav(path), len(self.pcm))
        self.assertEqual(read_safety_audio("partial"), (self.pcm, 48000, 2))
        self.assertEqual(path.stat().st_size, len(body) + 1)

    def test_invalid_metadata_cannot_block_recovery_of_a_valid_recording(self) -> None:
        (self.spool / "invalid-metadata.wav").write_bytes(recording(self.pcm))
        metadata = {
            "session_id": "invalid-metadata", "audio_file": "invalid-metadata.wav",
            "status": "processing", "sample_rate": "not-a-number", "channels": {},
        }
        path = self.spool / "invalid-metadata.json"
        path.write_text(json.dumps(metadata), encoding="utf-8")
        self.assertEqual(read_safety_audio("invalid-metadata"), (self.pcm, 48000, 2))
        self.assertEqual(recover_interrupted_sessions(), 1)
        actual = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((actual["sample_rate"], actual["channels"]), (48000, 2))


if __name__ == "__main__":
    unittest.main()
