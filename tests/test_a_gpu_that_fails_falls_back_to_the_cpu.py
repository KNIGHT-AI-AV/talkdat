"""0.4.173: a GPU that fails at run time falls back to the CPU (Windows and every platform), X-473's pattern for Parakeet.

Whisper already retried on the CPU when its GPU run failed (X-473); Parakeet did not: a DirectML or CUDA run that raises
(a lost device, a driver reset, an operator the provider cannot run) failed the dictation. Now a GPU run or warm-up that
raises gives up on the GPU for the rest of the session and redoes the work on the CPU, because a slower transcript beats
no transcript; a CPU failure still raises. The same change is on the Mac line (codex/mac-0.4.173-cpu 1e0c02e), where it
also covers CoreML's opt-in; this module is its platform-neutral half for the release line.
"""

from __future__ import annotations

import unittest
from unittest import mock

from knight_flow import local_stt

WINDOWS_PROVIDERS = ["DmlExecutionProvider", "CPUExecutionProvider"]


def pcm(seconds: float) -> bytes:
    return b"\0\0" * int(16000 * seconds)


class AGpuThatFailsAtRunTimeFallsBackTests(unittest.TestCase):
    """The GPU engines are told apart by local_stt's own registry; their runs raise, the CPU's do not."""

    def setUp(self) -> None:
        for patcher in (mock.patch.dict(local_stt._GPU_STATE, {"slow": False, "warm_seconds": None}),
                        mock.patch.object(local_stt, "_GPU_ENGINE_IDS", set()),
                        mock.patch.object(local_stt, "_gpu_providers", return_value=WINDOWS_PROVIDERS),
                        mock.patch("knight_flow.recognition_bias.with_transducer_bias",
                                   side_effect=lambda engine, _v: engine)):
            patcher.start()
            self.addCleanup(patcher.stop)
        local_stt._GPU_STATE.pop("failed", None)
        self.model = mock.Mock(id="parakeet-tdt-0.6b-v3", engine="onnx_asr", engine_id="nemo-parakeet-tdt-0.6b-v3",
                               label="Parakeet")
        self.loaded: list[bool] = []

    def ensure(self, model, status_cb=None, *, gpu=False):
        self.loaded.append(gpu)
        engine = mock.Mock(name="gpu engine" if gpu else "cpu engine")
        if gpu:
            local_stt._GPU_ENGINE_IDS.add(id(engine))
        return engine

    @staticmethod
    def recognise(engine, audio, sample_rate, confidence=None):
        if local_stt.is_gpu_engine(engine):
            raise RuntimeError("Non-zero status code returned while running a DmlExecutionProvider node: "
                               "the GPU device instance has been suspended (887A0005)")
        return "the words came back"

    def test_a_gpu_run_that_raises_retries_on_the_cpu_and_gives_up_on_the_gpu(self) -> None:
        with mock.patch.object(local_stt, "local_model_for_id", return_value=self.model), \
                mock.patch.object(local_stt, "ensure_loaded", side_effect=self.ensure), \
                mock.patch.object(local_stt, "_recognize_onnx", side_effect=self.recognise):
            try:
                text = local_stt.transcribe(model_id=self.model.id, pcm16=pcm(1), sample_rate=16000, channels=1,
                                            language="en", gpu=True)
            except RuntimeError as error:
                self.fail(f"the GPU failure reached the person: {error}")
        self.assertEqual(text, "the words came back")
        self.assertEqual(self.loaded, [True, False], "it did not retry on the CPU")
        self.assertFalse(local_stt.gpu_available(), "the session keeps paying for a GPU that fails")

    def test_a_cpu_failure_still_raises(self) -> None:
        def broken(engine, audio, sample_rate, confidence=None):
            raise RuntimeError("the CPU failed too")
        with mock.patch.object(local_stt, "local_model_for_id", return_value=self.model), \
                mock.patch.object(local_stt, "ensure_loaded", side_effect=self.ensure), \
                mock.patch.object(local_stt, "_recognize_onnx", side_effect=broken):
            with self.assertRaises(RuntimeError):
                local_stt.transcribe(model_id=self.model.id, pcm16=pcm(1), sample_rate=16000, channels=1,
                                     language="en", gpu=False)
        self.assertEqual(self.loaded, [False])

    def test_a_gpu_warm_up_that_raises_warms_the_cpu_instead(self) -> None:
        with mock.patch.object(local_stt, "ensure_loaded", side_effect=self.ensure), \
                mock.patch.object(local_stt, "_recognize_onnx", side_effect=self.recognise):
            try:
                warmed = local_stt.warm_engine(self.model)
            except RuntimeError as error:
                self.fail(f"the GPU warm-up failure escaped: {error}")
        self.assertTrue(warmed, "the CPU warm-up should stand in for the failed GPU one")
        self.assertEqual(self.loaded, [True, False])
        self.assertFalse(local_stt.gpu_available())

    def test_a_gpu_that_works_is_left_alone(self) -> None:
        def fine(engine, audio, sample_rate, confidence=None):
            return "gpu words"
        with mock.patch.object(local_stt, "local_model_for_id", return_value=self.model), \
                mock.patch.object(local_stt, "ensure_loaded", side_effect=self.ensure), \
                mock.patch.object(local_stt, "_recognize_onnx", side_effect=fine):
            text = local_stt.transcribe(model_id=self.model.id, pcm16=pcm(1), sample_rate=16000, channels=1,
                                        language="en", gpu=True)
        self.assertEqual((text, self.loaded), ("gpu words", [True]))
        self.assertTrue(local_stt.gpu_available())


if __name__ == "__main__":
    unittest.main()
