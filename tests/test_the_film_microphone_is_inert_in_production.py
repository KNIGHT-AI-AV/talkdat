"""X-398: the file-fed microphone exists only for the product film.

Without TALK_DAT_MIC_WAV the app must never touch it; with it, the app hears
the WAV at real-time pace and then silence, through the same callback shape
sounddevice uses, so the film never needs audio hardware.
"""
from __future__ import annotations

import os
import struct
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

from knight_flow import audio_input


class TheFilmMicrophoneTests(unittest.TestCase):
    def _wav(self, seconds: float = 0.25, rate: int = 16000) -> str:
        path = Path(tempfile.mkdtemp()) / "take.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(b"".join(struct.pack("<h", 3000 if i % 2 else -3000) for i in range(int(rate * seconds))))
        return str(path)

    def test_production_never_reaches_the_hook(self) -> None:
        source = Path(audio_input.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count('os.environ.get("TALK_DAT_MIC_WAV"'), 1)
        with mock.patch.dict(os.environ, {"TALK_DAT_MIC_WAV": ""}):
            with mock.patch.object(audio_input, "_WavInputStream", side_effect=AssertionError("hook reached")):
                try:
                    stream, _rate, _channels, _device = audio_input.open_raw_input_stream(
                        samplerate=16000, channels=1, callback=lambda *a: None, device=None
                    )
                except AssertionError:
                    raise
                except Exception:
                    return  # no microphone on this machine; the hook was still never touched
                try:
                    stream.close()
                except Exception:
                    pass

    def test_the_wav_arrives_through_the_callback_and_silence_follows(self) -> None:
        heard: list[bytes] = []
        with mock.patch.dict(os.environ, {"TALK_DAT_MIC_WAV": self._wav()}):
            stream, rate, channels, device = audio_input.open_raw_input_stream(
                samplerate=16000, channels=1, blocksize=800, callback=lambda data, frames, _t, _s: heard.append(bytes(data))
            )
        self.assertEqual((rate, channels, device), (16000, 1, None))
        stream.start()
        time.sleep(0.6)
        stream.stop()
        self.assertTrue(audio_input.input_stream_active(stream) is False)
        self.assertGreaterEqual(len(heard), 5)
        self.assertTrue(any(b != bytes(len(b)) for b in heard[:5]), "the WAV never arrived")
        self.assertEqual(heard[-1], bytes(len(heard[-1])), "silence did not follow the WAV")


if __name__ == "__main__":
    unittest.main()
