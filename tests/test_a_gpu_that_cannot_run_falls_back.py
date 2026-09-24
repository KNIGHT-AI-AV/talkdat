"""X-473: the GPU fallback guarded the wrong call, so it never fired.

Found by measuring, not by reading. A benchmark of the local engines on his own
3090 died with:

    RuntimeError: Library cublas64_12.dll is not found or cannot be loaded

and the fallback written for exactly that case did not run.

WHY. CTranslate2 loads lazily. `ctranslate2.get_cuda_device_count()` returns 1
on any machine with an NVIDIA card, and `WhisperModel(device="cuda")`
CONSTRUCTS successfully there whether or not the CUDA runtime libraries exist.
The failure arrives later, on the first inference. `_load_faster_whisper`
wraps construction in try/except and falls back to CPU, which is the right
idea guarding the wrong call: construction never raises, so the guard never
fires and the exception escapes to the person as a failed dictation.

A CUDA DEVICE IS NOT A CUDA RUNTIME. That is the whole bug in one line, and it
is not exotic: it is every user who owns an NVIDIA card and has never
installed the CUDA toolkit, which is nearly all of them. They turn GPU on in
Settings expecting it to be faster, and every Whisper dictation fails instead.
Parakeet is unaffected -- it runs on onnx-asr through DirectML, which is why
this went unnoticed while the default engine was Parakeet.

What this pins:

  * an inference failure on GPU retries on the CPU rather than reaching the
    person, because a slower transcript beats no transcript;
  * it is remembered, so the cost is paid once per run and not on every
    dictation for the rest of the session. A fallback that re-fails the same
    way forever is only half a fix;
  * a CPU failure still raises. Swallowing that would turn a real fault into
    silence, which is the failure mode X-465 was opened to remove.

WHAT THIS CANNOT PROVE: that CPU transcription is fast enough to be pleasant on
any given machine. It is not, for the large Whisper models, and that is a
separate finding recorded with the two-tier work.
"""

from __future__ import annotations

import unittest
from unittest import mock

from knight_flow import local_stt


class ACudaDeviceIsNotACudaRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        local_stt.forget_broken_cuda()
        self.addCleanup(local_stt.forget_broken_cuda)

    def _model(self, engine: str = "faster_whisper"):
        return mock.Mock(id="whisper-large-v3-turbo", engine=engine, engine_id="large-v3-turbo")

    def test_a_gpu_inference_failure_retries_on_the_cpu(self) -> None:
        """The person gets their words. Slower is not a failure; nothing is."""
        loaded: list[bool] = []

        def ensure(model, status_cb=None, *, gpu=False):
            loaded.append(gpu)
            return mock.Mock(name="gpu" if gpu else "cpu")

        def recognise(engine, audio, language, task=""):
            if loaded[-1]:
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            return "the words came back"

        with mock.patch.object(local_stt, "local_model_for_id", return_value=self._model()), \
             mock.patch.object(local_stt, "ensure_loaded", side_effect=ensure), \
             mock.patch.object(local_stt, "_recognize_faster_whisper", side_effect=recognise):
            text = local_stt.transcribe(
                model_id="whisper-large-v3-turbo", pcm16=b"\0\0" * 16000,
                sample_rate=16000, channels=1, language="en", gpu=True,
            )

        self.assertEqual(text, "the words came back")
        self.assertEqual(loaded, [True, False], "it did not retry on the CPU")

    def test_the_failure_is_remembered_so_it_costs_once(self) -> None:
        """A fallback that re-attempts the impossible on every dictation pays
        the GPU load and the failure every single time. The second call must go
        straight to the CPU."""
        loaded: list[bool] = []

        def ensure(model, status_cb=None, *, gpu=False):
            loaded.append(gpu)
            return mock.Mock()

        def recognise(engine, audio, language, task=""):
            if loaded[-1]:
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            return "words"

        with mock.patch.object(local_stt, "local_model_for_id", return_value=self._model()), \
             mock.patch.object(local_stt, "ensure_loaded", side_effect=ensure), \
             mock.patch.object(local_stt, "_recognize_faster_whisper", side_effect=recognise):
            for _ in range(3):
                local_stt.transcribe(
                    model_id="whisper-large-v3-turbo", pcm16=b"\0\0" * 16000,
                    sample_rate=16000, channels=1, language="en", gpu=True,
                )

        self.assertEqual(
            loaded, [True, False, False, False],
            "the GPU was attempted more than once after it had already proved unusable",
        )

    def test_a_cpu_failure_still_raises(self) -> None:
        """Only the GPU attempt is forgiven. A CPU failure is a real fault and
        must reach the caller, which is what turns it into a message the person
        can act on rather than an empty transcript."""
        with mock.patch.object(local_stt, "local_model_for_id", return_value=self._model()), \
             mock.patch.object(local_stt, "ensure_loaded", return_value=mock.Mock()), \
             mock.patch.object(local_stt, "_recognize_faster_whisper",
                               side_effect=RuntimeError("the model is broken")):
            with self.assertRaises(RuntimeError):
                local_stt.transcribe(
                    model_id="whisper-large-v3-turbo", pcm16=b"\0\0" * 16000,
                    sample_rate=16000, channels=1, language="en", gpu=False,
                )

    def test_parakeet_is_left_alone(self) -> None:
        """onnx-asr runs on DirectML, which is why this bug never touched the
        default engine. Its failures must not be routed through a CPU retry
        that means nothing for it."""
        with mock.patch.object(local_stt, "local_model_for_id",
                               return_value=self._model("onnx_asr")), \
             mock.patch.object(local_stt, "ensure_loaded", return_value=mock.Mock()), \
             mock.patch.object(local_stt, "_recognize_onnx",
                               side_effect=RuntimeError("onnx blew up")):
            with self.assertRaises(RuntimeError):
                local_stt.transcribe(
                    model_id="parakeet-tdt-0.6b-v3", pcm16=b"\0\0" * 16000,
                    sample_rate=16000, channels=1, language="en", gpu=True,
                )


if __name__ == "__main__":
    unittest.main()
