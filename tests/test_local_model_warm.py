from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.local_stt import (
    DEFAULT_LOCAL_MODEL_ID,
    model_to_prefetch,
    model_to_warm,
    selected_local_model,
)

APP = Path(__file__).resolve().parents[1] / "knight_flow" / "app.py"


def config(provider="local", model=DEFAULT_LOCAL_MODEL_ID, auto_download=True):
    return {
        "stt": {
            "provider": provider,
            "auto_download_local_model": auto_download,
            "providers": {"local": {"model": model}},
        }
    }


class TheFirstDictationOfASessionIsNoLongerTheSlowOneTests(unittest.TestCase):
    """Downloading the weights and loading them are separate costs, and only the
    first was ever paid ahead of time.

    `model_to_prefetch` returns None once the model is on disk, so from the
    second launch onwards startup prepared nothing at all and building the ONNX
    session happened inside the first dictation. Measured on this machine with
    one 5-second clip, in fresh processes:

        cold      first dictation  6444 ms
        warmed    first dictation   597 ms, after 5969 ms in the background

    Same model, same clip, same machine. The whole difference is where the
    session gets built, and it was being built on the first thing somebody does
    after opening the app -- which is why it reads as "this product is slow"
    rather than "this model is loading".
    """

    def test_a_downloaded_model_is_warmed_which_is_exactly_what_prefetch_skips(self) -> None:
        """The two are complements, and the gap between them was the bug."""
        with patch("knight_flow.local_stt.is_downloaded", return_value=True):
            self.assertIsNone(model_to_prefetch(config()), "nothing left to download")
            warm = model_to_warm(config())
            self.assertIsNotNone(warm, "and therefore nothing was being prepared at all")
            self.assertEqual(warm.id, DEFAULT_LOCAL_MODEL_ID)

    def test_a_model_that_is_not_downloaded_is_not_warmed(self) -> None:
        """There is nothing to load yet; downloading owns that case."""
        with patch("knight_flow.local_stt.is_downloaded", return_value=False):
            self.assertIsNone(model_to_warm(config()))
            self.assertIsNotNone(model_to_prefetch(config()))

    def test_a_small_cloud_machine_warms_nothing(self) -> None:
        """Several hundred megabytes of RAM to save nothing at all: a CPU-only
        laptop on a cloud route keeps its memory, exactly as before X-413."""
        with patch("knight_flow.local_stt.is_downloaded", return_value=True), \
             patch("knight_flow.local_stt.gpu_available", return_value=False), \
             patch("knight_flow.local_stt.machine_ram_gb", return_value=8.0):
            for provider in ("deepgram", "openrouter", "elevenlabs", ""):
                with self.subTest(provider=provider):
                    self.assertIsNone(model_to_warm(config(provider=provider)))

    def test_a_cloud_machine_that_can_carry_the_rescue_model_warms_it(self) -> None:
        """X-413: the cloud route falls back to local the moment the cloud is
        unreachable, so the rescue engine is built at launch where a GPU or
        enough memory makes that cheap, not inside the first rescued take."""
        with patch("knight_flow.local_stt.is_downloaded", return_value=True), patch("knight_flow.local_fallback.is_downloaded", return_value=True), \
             patch("knight_flow.local_stt.gpu_available", return_value=True), \
             patch("knight_flow.local_stt.machine_ram_gb", return_value=8.0):
            warm = model_to_warm(config(provider="deepgram"))
            self.assertIsNotNone(warm)
            self.assertEqual(warm.id, DEFAULT_LOCAL_MODEL_ID)
        with patch("knight_flow.local_stt.is_downloaded", return_value=True), patch("knight_flow.local_fallback.is_downloaded", return_value=True), \
             patch("knight_flow.local_stt.gpu_available", return_value=False), \
             patch("knight_flow.local_stt.machine_ram_gb", return_value=32.0):
            self.assertIsNotNone(model_to_warm(config(provider="deepgram")))
        disabled = config(provider="deepgram")
        disabled["stt"]["local_fallback"] = False
        with patch("knight_flow.local_stt.is_downloaded", return_value=True), patch("knight_flow.local_fallback.is_downloaded", return_value=True), \
             patch("knight_flow.local_stt.gpu_available", return_value=True):
            self.assertIsNone(model_to_warm(disabled), "no rescue wanted, nothing warmed")

    def test_warming_ignores_the_auto_download_preference(self) -> None:
        """Turning off automatic downloads says nothing about a model already
        on disk, and refusing to warm it would leave that person permanently on
        the slow first dictation for a setting about network use."""
        with patch("knight_flow.local_stt.is_downloaded", return_value=True):
            self.assertIsNotNone(model_to_warm(config(auto_download=False)))
            self.assertIsNone(model_to_prefetch(config(auto_download=False)))

    def test_the_selected_model_is_honoured_rather_than_the_default(self) -> None:
        chosen = selected_local_model(config(model="whisper-large-v3-turbo"))
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.id, "whisper-large-v3-turbo")

    def test_an_unknown_model_id_falls_back_instead_of_raising(self) -> None:
        """A config naming a model a later release dropped must not crash the
        app on the way to the microphone."""
        chosen = selected_local_model(config(model="a-model-that-was-removed"))
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.id, DEFAULT_LOCAL_MODEL_ID)

    def test_a_malformed_config_does_not_raise(self) -> None:
        for broken in ({}, {"stt": None}, {"stt": {"providers": "nope"}},
                       {"stt": {"provider": "local", "providers": None}}):
            with self.subTest(config=broken):
                try:
                    model_to_warm(broken)
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"startup warming raised on {broken!r}: {exc}")

    def test_startup_actually_calls_it(self) -> None:
        """A warm-up nobody schedules is worse than none: it reads as done."""
        source = APP.read_text(encoding="utf-8")
        self.assertIn("self.warm_selected_local_model", source)
        self.assertIn("def warm_selected_local_model", source)

    def test_it_runs_off_the_ui_thread(self) -> None:
        """Six seconds of model loading on the Tk thread would freeze the pill
        and every window with it -- a worse symptom than the one being fixed."""
        source = APP.read_text(encoding="utf-8")
        body = source[source.index("def warm_selected_local_model"):]
        body = body[:body.index("def prefetch_selected_local_model")]
        self.assertIn("threading.Thread", body)
        self.assertIn("daemon=True", body)

    def test_a_failed_warm_up_is_not_fatal(self) -> None:
        """It is an optimisation. If it cannot run, the model loads on demand
        exactly as it did before, and the person sees a slow first dictation
        rather than a broken app."""
        from knight_flow.local_stt import warm_engine

        with patch("knight_flow.local_stt.ensure_loaded", side_effect=RuntimeError("no runtime")):
            self.assertFalse(warm_engine(selected_local_model(config())))


if __name__ == "__main__":
    unittest.main()
