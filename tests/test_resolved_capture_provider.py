"""The app's announced route and the capture constructor use the same config."""
from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_signed_out_still_dictates import _FakeApp, _run_start_session


class ResolvedCaptureProviderTests(unittest.TestCase):
    def capture(self, config):
        app = _FakeApp(account_active=False)
        app.config = copy.deepcopy(config)
        before = copy.deepcopy(app.config)
        with (
            patch("knight_flow.field_context.FieldProbe.start", return_value=SimpleNamespace()),
            patch("knight_flow.app.foreground_window_id", return_value=111),
            patch("knight_flow.screen_context.foreground_title", return_value=""),
        ):
            captured = _run_start_session(app, model_on_disk=True)
        self.assertIsNotNone(captured)
        self.assertEqual(app.config, before, "session resolution mutated global settings")
        return app, captured["config"]

    def mixed_config(self):
        return {
            "privacy": {"local_only": False},
            "stt": {"route_mode": "byok", "provider": "local", "cloud_provider": "deepgram", "providers": {
                "deepgram": {"api_key": "fixture", "model": "nova-3"},
                "local": {"model": "whisper-small"},
            }},
            "dictation": {},
        }

    def test_explicit_byok_cloud_provider_reaches_the_constructor(self):
        app, captured = self.capture(self.mixed_config())
        self.assertEqual(captured["stt"]["provider"], "deepgram")
        self.assertEqual(app.session._talkdat_provider_id, "deepgram")
        self.assertEqual(captured["stt"]["providers"]["deepgram"]["model"], "nova-3")

    def test_local_only_preserves_the_selected_local_model(self):
        config = self.mixed_config()
        config["privacy"]["local_only"] = True
        app, captured = self.capture(config)
        self.assertEqual(captured["stt"]["provider"], "local")
        self.assertEqual(captured["stt"]["providers"]["local"]["model"], "whisper-small")
        self.assertEqual(app.session._talkdat_provider_id, "local")

    def test_local_route_preserves_global_provider_settings_for_a_later_switch(self):
        config = self.mixed_config()
        config["stt"]["route_mode"] = "local"
        app, captured = self.capture(config)
        app.config["stt"]["providers"]["local"]["model"] = "parakeet-tdt-0.6b-v3"
        self.assertEqual(captured["stt"]["providers"]["local"]["model"], "whisper-small")
        self.assertEqual(app.session._talkdat_config["stt"]["providers"]["local"]["model"], "whisper-small")


if __name__ == "__main__":
    unittest.main()
