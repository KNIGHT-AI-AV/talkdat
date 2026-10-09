"""Pure mocked one-shot speech and request-boundary privacy regressions."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from knight_flow import net_fence
from knight_flow.stt_sessions import BatchSTTSession, http_request, transcribe_pcm


class SpeechBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.previous_fence = net_fence.local_only()
        net_fence.set_local_only(False)

    def tearDown(self):
        net_fence.set_local_only(self.previous_fence)

    def provider_config(self):
        return {
            "privacy": {"local_only": False},
            "stt": {"route_mode": "byok", "provider": "deepgram", "providers": {
                "deepgram": {"api_key": "fixture", "model": "nova-3"},
                "local": {"model": "whisper-small"},
            }},
        }

    def assert_local_transcription(self, config, provider=""):
        providers = []

        def decode(session, _wav):
            providers.append(session.provider_id)
            return "local words"

        with patch.object(BatchSTTSession, "_transcribe", autospec=True, side_effect=decode):
            self.assertEqual(transcribe_pcm(config, b"\x01\x00" * 100, 16000, 1, provider_id=provider), "local words")
        self.assertEqual(providers, ["local"])

    def test_local_only_outranks_an_explicit_remote_retry(self):
        config = self.provider_config()
        config["privacy"]["local_only"] = True
        self.assert_local_transcription(config, "deepgram")

    def test_local_route_outranks_a_stale_remote_provider(self):
        config = self.provider_config()
        config["stt"]["route_mode"] = "local"
        self.assert_local_transcription(config)

    def test_missing_privacy_or_route_flags_default_to_local(self):
        config = self.provider_config()
        del config["privacy"]
        del config["stt"]["route_mode"]
        self.assert_local_transcription(config)

    def test_explicitly_opted_in_provider_still_works(self):
        config = self.provider_config()
        providers = []

        def decode(session, _wav):
            providers.append(session.provider_id)
            return "provider words"

        with patch.object(BatchSTTSession, "_transcribe", autospec=True, side_effect=decode):
            self.assertEqual(transcribe_pcm(config, b"\x01\x00" * 100, 16000, 1), "provider words")
        self.assertEqual(providers, ["deepgram"])

    def test_global_local_fence_refuses_batch_network_before_open(self):
        net_fence.set_local_only(True)
        with patch("knight_flow.stt_sessions.urlopen") as open_request:
            with self.assertRaises(net_fence.LocalOnlyBlocked):
                http_request("https://api.deepgram.com/v1/listen", method="POST", body=b"fixture audio")
        open_request.assert_not_called()

    def test_fence_is_rechecked_before_each_retry(self):
        attempts = []

        def interrupted(*_args, **_kwargs):
            attempts.append(True)
            net_fence.set_local_only(True)
            raise URLError("fixture interruption")

        with patch("knight_flow.stt_sessions.urlopen", side_effect=interrupted), patch("knight_flow.stt_sessions.time.sleep"):
            outcome = None
            try:
                http_request("https://api.deepgram.com/v1/listen", retries=2)
            except RuntimeError as exc:
                outcome = exc
        self.assertIsInstance(outcome, net_fence.LocalOnlyBlocked)
        self.assertEqual(attempts, [True])

    def test_fence_allows_existing_loopback_routes(self):
        net_fence.set_local_only(True)
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"loopback result"
        with patch("knight_flow.stt_sessions.urlopen", return_value=response):
            self.assertEqual(http_request("http://127.0.0.1:9000/transcribe"), b"loopback result")


if __name__ == "__main__":
    unittest.main()
