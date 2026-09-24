"""X-408: on-device speech takes the GPU through DirectML when Windows has one.

Measured on the founder's PC with the real 66.7-second take from 2026-09-03:
CPU int8 on 6 threads 18.5 s (32 s inside the app under load); DirectML with
the full-precision graph 3.7 s, and a warm 8-second clip 0.20 s against 3.0 s
on the CPU. DirectML compiles kernels per input shape, so clips are padded to
a few fixed lengths and those lengths are warmed once at startup.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow import local_stt

ROOT = Path(__file__).resolve().parents[1]


class GpuChoiceTests(unittest.TestCase):
    def test_the_machine_decides_unless_the_setting_is_explicit(self) -> None:
        with patch.object(local_stt, "_gpu_providers", return_value=["DmlExecutionProvider", "CPUExecutionProvider"]):
            local_stt._GPU_STATE["slow"] = False
            self.assertTrue(local_stt.gpu_default({}))
            self.assertTrue(local_stt.gpu_default(None))
            self.assertFalse(local_stt.gpu_default({"gpu": False}))
            local_stt._GPU_STATE["slow"] = True
            try:
                self.assertFalse(local_stt.gpu_default({}))
                self.assertTrue(local_stt.gpu_default({"gpu": True}))
            finally:
                local_stt._GPU_STATE["slow"] = False
        with patch.object(local_stt, "_gpu_providers", return_value=[]):
            self.assertFalse(local_stt.gpu_default({}))

    def test_directml_and_cuda_are_preferred_and_the_cpu_always_follows(self) -> None:
        source = (ROOT / "knight_flow" / "local_stt.py").read_text(encoding="utf-8")
        self.assertIn('("CUDAExecutionProvider", "DmlExecutionProvider", "CoreMLExecutionProvider")', source)
        self.assertIn('preferred + ["CPUExecutionProvider"]', source)

    def test_the_session_asks_the_machine(self) -> None:
        source = (ROOT / "knight_flow" / "stt_sessions.py").read_text(encoding="utf-8")
        self.assertIn("gpu=local_stt.gpu_default(self.extra),", source)
        self.assertNotIn('gpu=bool(self.extra.get("gpu", False))', source)


class ShapeBucketTests(unittest.TestCase):
    def test_short_clips_pad_up_to_the_next_bucket_and_long_ones_are_left_alone(self) -> None:
        self.assertEqual(local_stt.padded_seconds(1.2), 5.0)
        self.assertEqual(local_stt.padded_seconds(5.0), 5.0)
        self.assertEqual(local_stt.padded_seconds(7.4), 10.0)
        self.assertEqual(local_stt.padded_seconds(24.9), 25.0)
        self.assertEqual(local_stt.padded_seconds(66.7), 66.7)

    def test_only_a_gpu_engine_is_padded(self) -> None:
        import numpy as np

        class Engine:
            def __init__(self) -> None:
                self.seen: list[int] = []

            def recognize(self, audio, sample_rate):
                self.seen.append(len(audio))
                return "ok"

        cpu, gpu = Engine(), Engine()
        local_stt._GPU_ENGINE_IDS.add(id(gpu))
        try:
            clip = np.zeros(16000 * 3, dtype=np.float32)
            local_stt._recognize_onnx(cpu, clip, 16000)
            local_stt._recognize_onnx(gpu, clip, 16000)
        finally:
            local_stt._GPU_ENGINE_IDS.discard(id(gpu))
        self.assertEqual(cpu.seen, [16000 * 3])
        self.assertEqual(gpu.seen, [16000 * 5])


class GpuRuntimeTests(unittest.TestCase):
    def test_the_gpu_uses_the_int8_graph_already_on_disk(self) -> None:
        source = (ROOT / "knight_flow" / "local_stt.py").read_text(encoding="utf-8")
        self.assertNotIn("accelerated", source, "no second payload: the graph on disk is the one that runs on the GPU")
        self.assertIn("quantization=quantization," + chr(10) + "                providers=providers,", source)

    def test_gpu_runs_are_serialised_behind_one_lock(self) -> None:
        import threading

        seen: list[str] = []

        class Engine:
            def recognize(self, audio, sample_rate):
                seen.append("locked" if local_stt._GPU_RUN_LOCK.locked() else "free")
                return "ok"

        cpu, gpu = Engine(), Engine()
        local_stt._GPU_ENGINE_IDS.add(id(gpu))
        try:
            import numpy as np

            clip = np.zeros(16000, dtype=np.float32)
            local_stt._recognize_onnx(cpu, clip, 16000)
            local_stt._recognize_onnx(gpu, clip, 16000)
        finally:
            local_stt._GPU_ENGINE_IDS.discard(id(gpu))
        self.assertEqual(seen, ["free", "locked"])
        self.assertIsInstance(local_stt._GPU_RUN_LOCK, type(threading.Lock()))

    def test_a_minute_of_speech_is_one_call_and_the_vad_asks_for_long_segments(self) -> None:
        self.assertGreaterEqual(local_stt._ONNX_UTTERANCE_CAP_S, 120)
        self.assertEqual(local_stt._VAD_OPTIONS["max_speech_duration_s"], 60)

    def test_the_windows_build_ships_directml_and_never_two_runtimes(self) -> None:
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertRegex(requirements, re.compile(r'^onnxruntime-directml[^\n]*sys_platform == "win32"', re.M))
        self.assertRegex(requirements, re.compile(r'^onnxruntime>=[^\n]*sys_platform != "win32"', re.M))
        self.assertNotIn("onnx-asr[cpu", requirements)
        self.assertIn("onnx-asr[hub]", requirements)

class TheBuildShipsTheDirectMlRuntimeTests(unittest.TestCase):
    def test_both_build_scripts_reinstall_directml_last_and_check_it(self) -> None:
        for name in ("build-custom-installer.ps1", "build-exe.ps1"):
            script = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("--force-reinstall --no-deps $DirectMlPin", script, name)
            self.assertIn("DmlExecutionProvider", script, name)
            self.assertLess(script.index("requirements.lock"), script.index("$DirectMlPin"), name)


if __name__ == "__main__":
    unittest.main()
