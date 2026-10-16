"""0.4.173: build-mac.sh's 20-second probe launch proves the app starts, and touches no engine and no model.

Two findings, 2026-10-15 and -16, on knight-mac. The Store build's probe opened Ollama.app and Ollama's first run raised
an administrator dialog (fixed on the Store line as TALK_DAT_NO_ENGINE_START, 32dfb64f and f8111a95). And the probe
linked the owner's real ~/Library/Application Support/TalkDat/models into its temp home and launched the app, whose
Parakeet load writes a ready marker into the model folder and removes one it finds incomplete: every Mac build could
rewrite, or delete, the owner's speech model. A model-less probe home is not the answer by itself: the launch then
prefetches the 640 MB model in the background (model_to_prefetch fetches regardless of the route). So under the switch
the launch starts no formatter engine, does no formatter work, and neither prefetches nor warms a speech model; and
build-mac.sh sets the switch and no longer links the models.
"""

from __future__ import annotations

import os
from pathlib import Path
import threading
import types
import unittest
from unittest import mock

from knight_flow import app as app_module
from knight_flow import llm

ROOT = Path(__file__).resolve().parents[1]
BUILD_MAC = (ROOT / "build-mac.sh").read_text(encoding="utf-8")


def switch(on: bool):
    environ = {k: v for k, v in os.environ.items() if k != "TALK_DAT_NO_ENGINE_START"}
    if on:
        environ["TALK_DAT_NO_ENGINE_START"] = "1"
    return mock.patch.dict(os.environ, environ, clear=True)


def fake_app() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        _reset_in_progress=False, lock=threading.Lock(), session=None, config={"stt": {}},
        local_model_prefetch_lock=threading.Lock(), local_model_prefetch_in_progress=False,
        overlay=mock.Mock(), _local_download_message=lambda model: "downloading")


class TheFormatterUnderTheSwitchTests(unittest.TestCase):
    def test_the_switch_has_the_store_lines_name(self) -> None:
        self.assertEqual(llm.NO_ENGINE_START_ENV, "TALK_DAT_NO_ENGINE_START")

    def launch_with_no_engine_running(self, on: bool):
        class Now:  # threading.Thread that runs its target at start(), so the worker is observable
            def __init__(self, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()
        cfg = {"transforms": {"llm": {"provider": "ollama", "api_base": "http://127.0.0.1:11434"}}}
        with switch(on), mock.patch.object(llm, "_ollama_models", return_value=None), \
                mock.patch.object(llm, "_local_ollama_executable", return_value="/usr/local/bin/ollama"), \
                mock.patch.object(llm, "_OLLAMA_PREPARED", set()), mock.patch.object(llm, "_OLLAMA_PREPARE_IN_FLIGHT", set()), \
                mock.patch.object(llm.subprocess, "Popen") as popen, mock.patch.object(llm.time, "sleep"), \
                mock.patch.object(llm.threading, "Thread", Now):
            llm.prepare_local_formatter(cfg)
        return popen

    def test_under_the_switch_no_engine_is_started(self) -> None:
        self.launch_with_no_engine_running(True).assert_not_called()

    def test_without_the_switch_the_launch_does_start_it(self) -> None:
        popen = self.launch_with_no_engine_running(False)
        popen.assert_called_once()
        self.assertEqual(popen.call_args[0][0], ["/usr/local/bin/ollama", "serve"])

    def test_under_the_switch_the_formatter_does_no_engine_work(self) -> None:
        with switch(True), mock.patch.object(llm, "_ollama_models", return_value=set()) as models, \
                mock.patch.object(llm, "_OLLAMA_PREPARED", set()), mock.patch.object(llm, "_OLLAMA_PREPARE_IN_FLIGHT", set()), \
                mock.patch.object(llm.threading, "Thread") as thread:
            llm.prepare_local_formatter({"transforms": {"llm": {"provider": "ollama"}}})
        models.assert_not_called()
        thread.assert_not_called()


class TheSpeechModelUnderTheSwitchTests(unittest.TestCase):
    def test_under_the_switch_the_launch_neither_prefetches_nor_warms(self) -> None:
        with switch(True), mock.patch.object(app_module, "model_to_prefetch", return_value=None) as prefetch, \
                mock.patch.object(app_module, "model_to_warm", return_value=None) as warm:
            app_module.TalkDatApp.prefetch_selected_local_model(fake_app())
            app_module.TalkDatApp.warm_selected_local_model(fake_app())
        prefetch.assert_not_called()
        warm.assert_not_called()

    def test_without_the_switch_both_still_run(self) -> None:
        with switch(False), mock.patch.object(app_module, "model_to_prefetch", return_value=None) as prefetch, \
                mock.patch.object(app_module, "model_to_warm", return_value=None) as warm:
            app_module.TalkDatApp.prefetch_selected_local_model(fake_app())
            app_module.TalkDatApp.warm_selected_local_model(fake_app())
        prefetch.assert_called_once()
        warm.assert_called_once()


class TheBuildScriptTests(unittest.TestCase):
    def test_the_probe_launch_sets_the_switch(self) -> None:
        self.assertIn('TALK_DAT_HOME="$PROBE_HOME" TALK_DAT_NO_ENGINE_START=1 "$BUNDLE/Contents/MacOS/$APP_NAME"',
                      BUILD_MAC)

    def test_the_probe_home_never_reaches_the_real_models(self) -> None:
        self.assertNotIn('ln -s "$REAL_HOME/models"', BUILD_MAC)
        self.assertNotIn("Application Support/TalkDat", BUILD_MAC)


if __name__ == "__main__":
    unittest.main()
