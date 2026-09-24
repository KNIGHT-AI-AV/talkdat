"""Long local dictations must not silently lose their tail.

`_recognize_onnx` chains a VAD for recordings past the model's ~25s
utterance cap. The failure path of that chain used to be
`contextlib.suppress(Exception)` plus one bare `engine.recognize` over the
whole recording -- which the model truncates at its cap, so everything past
~25s vanished with no log line and no signal to the user.

These tests pin the repaired failure path:
  * the VAD failure is logged (a warning, with the traceback), and
  * the fallback feeds EVERY sample of the recording to the engine in
    cap-sized chunks, so the tail is transcribed.

They also pin that the happy paths are untouched: a successful VAD pass
never calls the bare engine, and short audio takes exactly one bare call.

Restoring the old suppress-and-bare-recognize body makes
`test_vad_failure_is_logged` and `test_vad_failure_fallback_covers_the_tail`
fail (verified while building this guard).
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from knight_flow import local_stt

SAMPLE_RATE = 10  # samples/second, tiny on purpose; only ratios matter here
CAP_SAMPLES = SAMPLE_RATE * local_stt._ONNX_UTTERANCE_CAP_S
# X-409 raised the cap to minutes; "long" is always past it, whatever it is.
LONG_SECONDS = local_stt._ONNX_UTTERANCE_CAP_S * 2 + 10


class _RecordingEngine:
    """Stands in for an onnx-asr model with a hard utterance cap.

    Like the real models, it answers every recognize() call -- but only
    "hears" the first `cap` samples it is given. Text encodes which slice of
    the recording was heard, so a joined transcript shows exactly what
    survived.
    """

    def __init__(self, audio: list[int], vad_error: Exception | None = None) -> None:
        self._audio = audio
        self._vad_error = vad_error
        self.recognize_slices: list[tuple[int, int]] = []
        self.with_vad_calls = 0

    def with_vad(self, vad: object, **options: object) -> "_RecordingEngine":
        self.with_vad_calls += 1
        if self._vad_error is not None:
            raise self._vad_error
        return self

    def recognize(self, audio: object, sample_rate: int) -> object:
        chunk = list(audio)
        heard = chunk[:CAP_SAMPLES]
        start = self._audio.index(chunk[0])
        self.recognize_slices.append((start, start + len(heard)))
        if self._vad_error is None and self.with_vad_calls:
            # VAD path: yields per-segment results.
            return [types.SimpleNamespace(text=f"seg-{start}-{start + len(heard)}")]
        return f"heard-{start}-{start + len(heard)}"


def _fake_onnx_asr_module() -> types.ModuleType:
    module = types.ModuleType("onnx_asr")
    module.load_vad = lambda name: object()  # type: ignore[attr-defined]
    return module


def _long_audio(seconds: int) -> list[int]:
    # Distinct sample values so the engine can report which slice it saw.
    return list(range(SAMPLE_RATE * seconds))


def _expected_chunks(total: int) -> str:
    # Cap-sized windows, tail included, whatever the cap is set to.
    return " ".join(f"heard-{start}-{min(start + CAP_SAMPLES, total)}" for start in range(0, total, CAP_SAMPLES))


class VadTailFallbackTests(unittest.TestCase):
    def _recognize(self, engine: _RecordingEngine, audio: list[int]) -> str:
        with patch.dict(sys.modules, {"onnx_asr": _fake_onnx_asr_module()}):
            return local_stt._recognize_onnx(engine, audio, SAMPLE_RATE)

    def test_vad_failure_is_logged(self) -> None:
        audio = _long_audio(LONG_SECONDS)
        engine = _RecordingEngine(audio, vad_error=RuntimeError("vad model corrupt"))
        with self.assertLogs(local_stt.log, level="WARNING") as captured:
            self._recognize(engine, audio)
        joined = "\n".join(captured.output)
        self.assertIn("VAD chain failed", joined)
        # The traceback travels with the warning so the failure is diagnosable.
        self.assertIn("vad model corrupt", joined)

    def test_vad_failure_fallback_covers_the_tail(self) -> None:
        audio = _long_audio(LONG_SECONDS)  # past the cap, so the VAD chain runs
        engine = _RecordingEngine(audio, vad_error=RuntimeError("boom"))
        with self.assertLogs(local_stt.log, level="WARNING"):
            text = self._recognize(engine, audio)
        # Every sample of the recording was fed to the engine...
        covered = sorted(engine.recognize_slices)
        self.assertEqual(covered[0][0], 0)
        self.assertEqual(covered[-1][1], len(audio))
        for (_, prev_end), (next_start, _) in zip(covered, covered[1:]):
            self.assertEqual(prev_end, next_start, "gap between fallback chunks")
        # ...and every chunk's text made it into the transcript, tail included.
        self.assertEqual(text, _expected_chunks(len(audio)))

    def test_vad_failure_mid_iteration_still_covers_the_tail(self) -> None:
        # The chain can also die while its lazy results are being consumed;
        # the partial segments must be discarded, not returned as the answer.
        audio = _long_audio(LONG_SECONDS)
        engine = _RecordingEngine(audio)

        def exploding_results() -> object:
            yield types.SimpleNamespace(text="only the head")
            raise RuntimeError("segment 2 failed")

        engine.with_vad = lambda vad, **options: types.SimpleNamespace(  # type: ignore[method-assign]
            recognize=lambda a, sample_rate: exploding_results()
        )
        with self.assertLogs(local_stt.log, level="WARNING"):
            text = self._recognize(engine, audio)
        self.assertEqual(text, _expected_chunks(len(audio)))

    def test_successful_vad_pass_never_calls_the_bare_engine(self) -> None:
        # The happy path must not pay for the guard: no extra recognize calls,
        # no logging, same joined-segments answer as before.
        audio = _long_audio(LONG_SECONDS)
        engine = _RecordingEngine(audio)
        vad_engine = types.SimpleNamespace(
            recognize=lambda a, sample_rate: [
                types.SimpleNamespace(text="hello "),
                types.SimpleNamespace(text=" world"),
            ]
        )
        engine.with_vad = lambda vad, **options: vad_engine  # type: ignore[method-assign]
        text = self._recognize(engine, audio)
        self.assertEqual(text, "hello world")
        self.assertEqual(engine.recognize_slices, [])

    def test_short_audio_takes_one_bare_call(self) -> None:
        audio = _long_audio(10)  # under the cap; VAD never enters the picture
        engine = _RecordingEngine(audio)
        text = self._recognize(engine, audio)
        self.assertEqual(engine.with_vad_calls, 0)
        self.assertEqual(engine.recognize_slices, [(0, len(audio))])
        self.assertEqual(text, f"heard-0-{len(audio)}")


if __name__ == "__main__":
    unittest.main()
