"""T6 runner: the passage is rendered to a FILE by a (fake) text-to-speech
command and every installed engine hears the same audio. No speech engine is
loaded, no audio is played, nothing is downloaded.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from knight_flow.model_bench import PASSAGE, bench_installed, peak_memory_mb, recommend, render_passage


def fake_tts(command, **_kwargs):
    """Writes the WAV the real command would, to the path the command names."""
    target = next(part for part in command if str(part).endswith(".wav")) if "-o" in command else None
    if target is None:
        script = command[-1]
        target = script.split("SetOutputToWaveFile('", 1)[1].split("'", 1)[0]
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(struct.pack("<h", 1000) * 16000)


class TheRunner(unittest.TestCase):
    def test_the_passage_is_rendered_to_a_file(self):
        with tempfile.TemporaryDirectory() as folder:
            for platform in ("win32", "darwin"):
                pcm, rate, channels = render_passage(platform, folder, run=fake_tts)
                self.assertEqual((len(pcm), rate, channels), (32000, 16000, 1))
                self.assertEqual(Path(folder, "passage.txt").read_text(encoding="utf-8"), PASSAGE)

    def test_no_text_to_speech_is_an_honest_stop(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(RuntimeError):
            render_passage("linux", folder, run=fake_tts)

    def test_every_engine_hears_the_same_audio(self):
        heard = []

        def transcribe(*, model_id, pcm16, sample_rate, channels, language):
            heard.append((model_id, len(pcm16), sample_rate, channels, language))
            return PASSAGE if model_id == "good" else "please send the report"

        results = bench_installed(["good", "rough"], b"\x00\x01" * 8000, 16000, 1, transcribe=transcribe,
                                  warm_runs=2, memory=lambda: 512.0)
        self.assertEqual({entry[0] for entry in heard}, {"good", "rough"})
        self.assertEqual({entry[1:] for entry in heard}, {(16000, 16000, 1, "en")})
        self.assertEqual(len(heard), 6)  # one cold and two warm each
        self.assertEqual(recommend(results).model_id, "good")
        self.assertEqual(results[0].peak_memory_mb, 512.0)

    def test_this_process_reports_its_peak_memory(self):
        self.assertGreater(peak_memory_mb(), 1.0)


if __name__ == "__main__":
    unittest.main()
