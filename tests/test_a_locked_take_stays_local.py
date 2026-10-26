"""T7, the criterion the report left open: a take locked to this computer, with
a cloud key saved and no local model on disk, still starts on the local route;
and when its local transcription then fails, it is retried on the local route
only and ends with no text, its audio left for Recovery -- never moved to the
cloud. Fakes only: no microphone, model, network or window.
"""
from __future__ import annotations

import types
import unittest
from unittest import mock

import knight_flow.app as app_module
from knight_flow import net_fence
from tests.test_signed_out_still_dictates import _FakeApp, _run_start_session


class ALockedTakeWithoutALocalModel(unittest.TestCase):
    def tearDown(self) -> None:
        net_fence.set_local_only(False)

    def start(self, app):
        # A key the registry treats as saved (a placeholder: no credential is read).
        with (
            mock.patch("knight_flow.stt_registry.provider_key_is_set", return_value=True),
            mock.patch("knight_flow.app.selected_stt_api_key", return_value="placeholder-not-a-key"),
        ):
            return _run_start_session(app, model_on_disk=False)

    def app(self):
        # Local-only is ON by default (stt_registry.local_only); a cloud route
        # exists only once the person turned it off, so both cases start there.
        app = _FakeApp(account_active=False)
        app.config["stt"] = {"provider": "deepgram", "route_mode": "byok", "providers": {}}
        app.config["privacy"] = {"local_only": False}
        return app

    def test_it_starts_on_the_local_route_whatever_key_is_saved(self) -> None:
        app = self.app()
        app.config["privacy"]["lock_next_take"] = True
        captured = self.start(app)
        self.assertIsNotNone(captured, "the take starts; it is not refused")
        config = captured["config"]
        self.assertEqual(config["stt"]["provider"], "local")
        self.assertIs(config["privacy"]["local_only"], True)
        self.assertIs(app.config["privacy"]["lock_next_take"], False, "the one-shot request is used up")
        self.assertIs(app.config["privacy"]["local_only"], False, "the stored config is not locked")
        self.assertFalse(net_fence.take_locked(), "no fence view outlives the take")

    def test_without_the_lock_the_same_config_goes_to_its_cloud_key(self) -> None:
        # The control: the lock, not the fakes, is what keeps the take local.
        captured = self.start(self.app())
        self.assertIsNotNone(captured)
        self.assertEqual(captured["config"]["stt"]["provider"], "deepgram")

    def test_a_failed_local_transcription_is_retried_locally_only(self) -> None:
        from tests.test_a_sustained_outage_reaches_the_local_rescue import CHANNELS, PCM, SAMPLE_RATE
        from tests.test_a_sustained_outage_reaches_the_local_rescue import _FakeApp as OutageApp

        app = OutageApp()
        locked = {"stt": {"provider": "local", "providers": {}}, "privacy": {"local_only": True}, "dictation": {}}
        session = types.SimpleNamespace(_talkdat_config=locked, _talkdat_provider_id="local", transport_degraded=False,
                                        captured_audio=lambda: (PCM, SAMPLE_RATE, CHANNELS, True))
        used = []

        def transcribe(config, pcm, rate, channels, *, provider_id=""):
            used.append((provider_id, config.get("privacy", {}).get("local_only")))
            raise RuntimeError("no local model on this computer")

        with mock.patch.object(app_module, "transcribe_pcm", transcribe):
            result = app_module.TalkDatApp.recover_transcript_if_needed(app, session, "ptt", "")
        self.assertEqual(result, "", "no text is made up")
        self.assertEqual(used, [("local", True)], "one retry, on this computer, still locked")
        self.assertEqual(app.cloud_fallback_notes, 0)


if __name__ == "__main__":
    unittest.main()
