"""A GPU machine can run the 4B without the 1.7B, and a Mac finds its Ollama.

Smart formatting setup pulls only qwen3:4b-instruct-2507 on a capable GPU
(2.5 GB instead of 3.9 GB). That only works if the formatter no longer needs
the 1.7B's warm-up to decide it is on a GPU, so the 4B is measured the same
way (same warm-up, same /api/ps check) and that measurement is enough. A 4B
that spills off the card still falls back to the 1.7B.

No engine and no process: every engine call and subprocess is patched.
"""
from __future__ import annotations

import copy
import os
import unittest
from unittest import mock

from knight_flow import llm, translation
from knight_flow.config import DEFAULT_CONFIG, LOCAL_FORMATTER_MODEL
from knight_flow.local_finish import LOCAL_GPU_MODEL, MachineSpeed

BASE = "http://127.0.0.1:11987"


def config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["transforms"]["llm"].update(provider="ollama", api_base=BASE, model=LOCAL_FORMATTER_MODEL, auto_install=True)
    return cfg


def speed(on_gpu):
    return MachineSpeed(prefill_tps=4000.0, generation_tps=150.0, on_gpu=on_gpu)


def no_process(*_a, **_k):
    raise AssertionError("a test started a real process")


class Clean(unittest.TestCase):
    def setUp(self):
        # This suite tests the cross-platform upgrade path, not the Mac's own
        # memory gate (that's tests/test_mac_smart_formatting_setup.py); a
        # Mac under 16 GB running this suite for real would otherwise never
        # see the 4B upgrade these tests exercise.
        patcher = mock.patch("knight_flow.mac_support.gpu_model_fits", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.reset)
        self.reset()

    @staticmethod
    def reset():
        for model in (LOCAL_FORMATTER_MODEL, LOCAL_GPU_MODEL):
            key = llm.local_finish_key(BASE, model)
            llm._LOCAL_SPEED.pop(key, None)
            llm._OLLAMA_PREPARE_IN_FLIGHT.discard(key)
            llm._OLLAMA_PREPARED.discard(key)
        llm._OLLAMA_READY_CACHE.clear()


class TheTargetTrustsTheFourBsOwnMeasurementTests(Clean):
    def target(self, installed):
        with mock.patch("knight_flow.llm._ollama_models", return_value=set(installed)):
            return llm.local_finish_target(config(), executive=False)[1]

    def test_a_4b_measured_on_the_gpu_answers_with_no_17b_present(self):
        llm._LOCAL_SPEED[llm.local_finish_key(BASE, LOCAL_GPU_MODEL)] = speed(True)
        self.assertEqual(self.target({LOCAL_GPU_MODEL.lower()}), LOCAL_GPU_MODEL)

    def test_a_4b_that_spilled_to_the_cpu_is_not_chosen(self):
        llm._LOCAL_SPEED[llm.local_finish_key(BASE, LOCAL_GPU_MODEL)] = speed(False)
        self.assertEqual(self.target({LOCAL_GPU_MODEL.lower(), LOCAL_FORMATTER_MODEL}), LOCAL_FORMATTER_MODEL)

    def test_nothing_measured_is_not_a_gpu(self):
        self.assertEqual(self.target({LOCAL_GPU_MODEL.lower()}), LOCAL_FORMATTER_MODEL)

    def test_the_old_path_is_unchanged(self):
        llm._LOCAL_SPEED[llm.local_finish_key(BASE, LOCAL_FORMATTER_MODEL)] = speed(True)
        self.assertEqual(self.target({LOCAL_GPU_MODEL.lower(), LOCAL_FORMATTER_MODEL}), LOCAL_GPU_MODEL)

    def test_a_chosen_model_is_never_overridden(self):
        cfg = config()
        cfg["transforms"]["llm"]["model"] = "llama3.2:3b"
        llm._LOCAL_SPEED[llm.local_finish_key(BASE, LOCAL_GPU_MODEL)] = speed(True)
        with mock.patch("knight_flow.llm._ollama_models", return_value={LOCAL_GPU_MODEL.lower()}):
            self.assertEqual(llm.local_finish_target(cfg, executive=False)[1], "llama3.2:3b")


class PrepareWarmsTheFourBAloneTests(Clean):
    def prepare(self, models, warm_result, *, executable="C:/ollama.exe"):
        state = {"models": set(models)}
        warmed, pulled = [], []

        def warm(api_base, model, **_k):
            warmed.append(model)
            result = warm_result(model)
            if result is not None:
                llm._LOCAL_SPEED[llm.local_finish_key(api_base, model)] = result
            return result

        def run(argv, **_k):
            pulled.append(argv[-1])
            state["models"].add(argv[-1].lower())
            return mock.Mock(returncode=0)

        class Now:
            def __init__(self, target, **_k): self.target = target
            def start(self): self.target()

        with mock.patch("knight_flow.llm._ollama_models", side_effect=lambda *a, **k: set(state["models"])), \
             mock.patch("knight_flow.llm.warm_local_finish", side_effect=warm), \
             mock.patch("knight_flow.llm._local_ollama_executable", return_value=executable), \
             mock.patch("knight_flow.llm.subprocess.run", side_effect=run), \
             mock.patch("knight_flow.llm.subprocess.Popen", side_effect=no_process), \
             mock.patch("knight_flow.llm.threading.Thread", Now):
            llm.prepare_local_formatter(config())
        return warmed, pulled

    def test_only_the_4b_on_the_gpu_is_warmed_and_nothing_is_pulled(self):
        warmed, pulled = self.prepare({LOCAL_GPU_MODEL.lower()}, lambda m: speed(True))
        self.assertEqual(warmed, [LOCAL_GPU_MODEL])
        self.assertEqual(pulled, [])
        self.assertIn(llm.local_finish_key(BASE, LOCAL_FORMATTER_MODEL), llm._OLLAMA_PREPARED)
        self.assertFalse(llm.local_formatter_preparing(config()))
        with mock.patch("knight_flow.llm._ollama_models", return_value={LOCAL_GPU_MODEL.lower()}):
            self.assertEqual(llm.local_finish_target(config(), executive=True)[1], LOCAL_GPU_MODEL)

    def test_a_4b_that_does_not_fit_falls_back_to_the_17b(self):
        warmed, pulled = self.prepare({LOCAL_GPU_MODEL.lower()},
                                      lambda m: speed(False) if m == LOCAL_GPU_MODEL else speed(False))
        self.assertEqual(pulled, [LOCAL_FORMATTER_MODEL])
        self.assertEqual(warmed[:2], [LOCAL_GPU_MODEL, LOCAL_FORMATTER_MODEL])
        with mock.patch("knight_flow.llm._ollama_models", return_value={LOCAL_GPU_MODEL.lower(), LOCAL_FORMATTER_MODEL}):
            self.assertEqual(llm.local_finish_target(config(), executive=False)[1], LOCAL_FORMATTER_MODEL)

    def test_an_engine_that_never_answers_the_warm_up_is_not_prepared(self):
        warmed, _pulled = self.prepare({LOCAL_GPU_MODEL.lower()}, lambda m: None, executable="")
        self.assertEqual(warmed, [LOCAL_GPU_MODEL])
        self.assertNotIn(llm.local_finish_key(BASE, LOCAL_FORMATTER_MODEL), llm._OLLAMA_PREPARED)

    def test_without_the_4b_the_old_order_stands(self):
        warmed, pulled = self.prepare(set(), lambda m: speed(False))
        self.assertEqual(pulled, [LOCAL_FORMATTER_MODEL])
        self.assertEqual(warmed, [LOCAL_FORMATTER_MODEL])


class TheMacFindsItsOllamaTests(unittest.TestCase):
    def find(self, platform, present, which=None, home="/Users/pat"):
        with mock.patch.object(llm.shutil, "which", return_value=which), \
             mock.patch("sys.platform", platform), \
             mock.patch.object(llm.os.path, "expanduser", side_effect=lambda p: p.replace("~", home, 1)), \
             mock.patch.object(llm.os.path, "isfile", side_effect=lambda p: p in present), \
             mock.patch("knight_flow.llm.subprocess.Popen", side_effect=no_process):
            return llm._local_ollama_executable(), translation._ollama_executable()

    def test_each_mac_location_is_found(self):
        for path in ("/Applications/Ollama.app/Contents/Resources/ollama",
                     "/Users/pat/Applications/Ollama.app/Contents/Resources/ollama",
                     "/opt/homebrew/bin/ollama",
                     "/usr/local/bin/ollama"):
            with self.subTest(path=path):
                self.assertEqual(self.find("darwin", {path}), (path, path))

    def test_the_app_bundle_wins_over_homebrew(self):
        found, _ = self.find("darwin", {"/Applications/Ollama.app/Contents/Resources/ollama", "/opt/homebrew/bin/ollama"})
        self.assertEqual(found, "/Applications/Ollama.app/Contents/Resources/ollama")

    def test_path_wins_everywhere(self):
        self.assertEqual(self.find("darwin", set(), which="/somewhere/ollama")[0], "/somewhere/ollama")

    def test_nothing_installed_is_empty(self):
        self.assertEqual(self.find("darwin", set()), ("", ""))

    def test_windows_still_finds_the_per_user_install(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/pat/AppData/Local"}):
            expected = os.path.join("C:/Users/pat/AppData/Local", "Programs", "Ollama", "ollama.exe")
            self.assertEqual(self.find("win32", {expected})[0], expected)

    def test_a_mac_never_looks_for_the_windows_exe(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/x"}):
            with mock.patch("sys.platform", "darwin"):
                self.assertFalse(any(p.endswith(".exe") for p in llm._ollama_executable_candidates()))


if __name__ == "__main__":
    unittest.main()
