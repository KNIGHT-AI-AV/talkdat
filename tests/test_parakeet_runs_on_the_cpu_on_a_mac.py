"""0.4.173: Parakeet runs on the CPU on a Mac, and a GPU that fails at run time falls back to the CPU.

RULING 2026-10-16T02:24:15Z, after measuring on knight-mac (an 8 GB Mac): onnxruntime's CoreML provider takes only
1,528 of the Parakeet encoder's 3,249 nodes, in 319 partitions; compiling them pushed swap from 2.7 to 3.95 GiB before
a word was transcribed, and the build probe's CoreML warm-up hit "GetElementType is not implemented". The CPU warmed in
1.49 s and transcribed a 6.3 s sentence in 0.19 s with no swap growth. So Parakeet int8 defaults to the CPU on macOS;
CoreML is opt-in (TALK_DAT_COREML=1) until it has its own proof.

"The CPU" has to be said out loud. With no providers, onnx_asr 0.12 hands onnxruntime every available provider
(`providers or rt.get_available_providers()`), which on a Mac is CoreML first: gpu=False alone still ran CoreML, in
every public direct Mac build since at least 0.4.133. So every Parakeet load on a Mac, and the VAD it chains for long
takes, names ["CPUExecutionProvider"] explicitly. Windows is unchanged.

The runtime fallback is X-473's pattern for Parakeet: a GPU run or warm-up that raises gives up on the GPU for the rest
of the session and retries on the CPU, because a slower transcript beats no transcript; a CPU failure still raises.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from knight_flow import local_stt

MAC_PROVIDERS = ["CoreMLExecutionProvider", "AzureExecutionProvider", "CPUExecutionProvider"]
WINDOWS_PROVIDERS = ["DmlExecutionProvider", "CPUExecutionProvider"]
CPU = ["CPUExecutionProvider"]


class FakeOnnxAsr(types.ModuleType):
    """Records the providers every model and VAD load is given; engines chain a VAD and recognize."""

    def __init__(self) -> None:
        super().__init__("onnx_asr")
        self.loads: list[tuple[str, object]] = []

    def load_model(self, engine_id, path=None, **kwargs):
        self.loads.append(("model", kwargs.get("providers", "NOT GIVEN")))
        engine = mock.Mock(name="engine")
        chain = mock.Mock(name="chain")
        chain.recognize.return_value = [mock.Mock(text="words")]
        del chain.with_timestamps
        engine.with_vad.return_value = chain
        return engine

    def load_vad(self, model="silero", path=None, **kwargs):
        self.loads.append(("vad", kwargs.get("providers", "NOT GIVEN")))
        return mock.Mock(name="vad")


class Machine:
    """sys.platform, onnxruntime's provider list and the CoreML opt-in, for one test."""

    def __init__(self, test: unittest.TestCase, platform: str, providers: list, coreml: bool = False) -> None:
        import onnxruntime

        self.onnx_asr = FakeOnnxAsr()
        environ = {k: v for k, v in os.environ.items() if k != "TALK_DAT_COREML"}
        if coreml:
            environ["TALK_DAT_COREML"] = "1"
        target = Path(tempfile.mkdtemp())
        test.addCleanup(lambda: __import__("shutil").rmtree(target, ignore_errors=True))
        (target / local_stt.READY_MARKER).write_text("ok", encoding="utf-8")
        for patcher in (
            mock.patch.object(local_stt.sys, "platform", platform),
            mock.patch.object(onnxruntime, "get_available_providers", return_value=list(providers)),
            mock.patch.dict(sys.modules, {"onnx_asr": self.onnx_asr}),
            mock.patch.dict(os.environ, environ, clear=True),
            mock.patch.dict(local_stt._GPU_STATE, {"slow": False, "warm_seconds": None}),
            mock.patch.dict(local_stt._ENGINES, {}, clear=True),
            mock.patch.object(local_stt, "_GPU_ENGINE_IDS", set()),
            mock.patch.object(local_stt, "model_dir", return_value=target),
            mock.patch.object(local_stt, "resolved_model_dir", return_value=target),
            mock.patch.object(local_stt, "_payload_looks_complete", return_value=True),
            mock.patch.object(local_stt, "is_downloaded", return_value=True),
            mock.patch.object(local_stt, "_write_ready_manifest"),
            mock.patch.object(local_stt, "_recognize_once", return_value="words"),
            mock.patch("knight_flow.recognition_bias.with_transducer_bias", side_effect=lambda engine, _v: engine),
        ):
            patcher.start()
            test.addCleanup(patcher.stop)
        local_stt._GPU_STATE.pop("failed", None)
        self.model = local_stt.local_model_for_id(local_stt.DEFAULT_LOCAL_MODEL_ID)


def pcm(seconds: float) -> bytes:
    return b"\0\0" * int(16000 * seconds)


class ParakeetStaysOnTheCpuOnAMacTests(unittest.TestCase):
    def test_a_mac_offers_no_gpu_for_parakeet_without_the_opt_in(self) -> None:
        Machine(self, "darwin", MAC_PROVIDERS)
        self.assertEqual(local_stt._gpu_providers(), [])
        self.assertFalse(local_stt.gpu_available())
        self.assertFalse(local_stt.gpu_default({}))

    def test_every_parakeet_load_on_a_mac_names_only_the_cpu(self) -> None:
        machine = Machine(self, "darwin", MAC_PROVIDERS)
        local_stt._load_onnx_asr(machine.model, gpu=True)
        local_stt._load_onnx_asr(machine.model, gpu=False)
        self.assertEqual(machine.onnx_asr.loads, [("model", CPU), ("model", CPU)])

    def test_no_mac_parakeet_path_can_reach_coreml_without_the_opt_in(self) -> None:
        # The coordinator's guard: transcribe (GPU asked and not), the launch warm-up, ensure_loaded, and the VAD a long
        # take chains. Every load must name exactly the CPU: no provider list at all means CoreML first on a Mac.
        machine = Machine(self, "darwin", MAC_PROVIDERS)
        for gpu in (True, False):
            local_stt.transcribe(model_id=machine.model.id, pcm16=pcm(2), sample_rate=16000, channels=1,
                                 language="en", gpu=gpu)
            local_stt._ENGINES.clear()
        local_stt.warm_engine(machine.model)
        local_stt._ENGINES.clear()
        for gpu in (True, False):
            local_stt.ensure_loaded(machine.model, gpu=gpu)
            local_stt._ENGINES.clear()
        local_stt.transcribe(model_id=machine.model.id, pcm16=pcm(local_stt._ONNX_UTTERANCE_CAP_S + 5),
                             sample_rate=16000, channels=1, language="en", gpu=False)
        kinds = {kind for kind, _ in machine.onnx_asr.loads}
        self.assertEqual(kinds, {"model", "vad"}, machine.onnx_asr.loads)
        for kind, providers in machine.onnx_asr.loads:
            self.assertEqual(providers, CPU, f"a {kind} load on a Mac was given {providers!r}")

    def test_the_opt_in_offers_coreml_so_the_gate_is_real(self) -> None:
        machine = Machine(self, "darwin", MAC_PROVIDERS, coreml=True)
        self.assertEqual(local_stt._gpu_providers(), ["CoreMLExecutionProvider", "CPUExecutionProvider"])
        local_stt._load_onnx_asr(machine.model, gpu=True)
        self.assertEqual(machine.onnx_asr.loads, [("model", ["CoreMLExecutionProvider", "CPUExecutionProvider"])])

    def test_windows_loads_exactly_as_before(self) -> None:
        machine = Machine(self, "win32", WINDOWS_PROVIDERS)
        local_stt._load_onnx_asr(machine.model, gpu=False)
        local_stt._load_onnx_asr(machine.model, gpu=True)
        self.assertEqual(machine.onnx_asr.loads, [("model", "NOT GIVEN"), ("model", WINDOWS_PROVIDERS)])


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
            raise RuntimeError("Non-zero status code returned while running a CoreML node: GetElementType")
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
            warmed = local_stt.warm_engine(self.model)
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
