from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from knight_flow.stt_sessions import BatchSTTSession, extract_text


def session(provider_id: str, *, model: str, variant: str = "default") -> BatchSTTSession:
    noop = lambda *_args, **_kwargs: None  # noqa: E731
    return BatchSTTSession(
        provider_id=provider_id,
        api_key="test-key",
        api_base="",
        model=model,
        variant=variant,
        language="en-US",
        sample_rate=16000,
        channels=1,
        max_seconds=30,
        no_speech_timeout_seconds=10,
        silence_timeout_seconds=10,
        tail_capture_ms=0,
        min_capture_ms=0,
        extra={},
        on_update=noop,
        on_status=noop,
        on_level=noop,
        on_done=noop,
        on_error=noop,
    )


class CloudSTTAdapterTests(unittest.TestCase):
    def test_xai_uses_dedicated_formatted_stt_endpoint(self) -> None:
        current = session("xai", model="grok-transcribe")
        response = json.dumps({"text": "Formatted transcript."}).encode()
        with patch("knight_flow.stt_sessions.http_request", return_value=response) as request:
            result = current._transcribe_xai(b"RIFF-test")

        self.assertEqual(result, "Formatted transcript.")
        url = request.call_args.args[0]
        kwargs = request.call_args.kwargs
        self.assertEqual(url, "https://api.x.ai/v1/stt")
        self.assertIn(b'name="format"', kwargs["body"])
        self.assertIn(b'name="file"', kwargs["body"])
        self.assertLess(kwargs["body"].index(b'name="format"'), kwargs["body"].index(b'name="file"'))

    def test_smallest_sends_audio_bytes_to_pulse_pro(self) -> None:
        current = session("smallest", model="pulse-pro")
        response = json.dumps({"transcription": "Smallest transcript."}).encode()
        with patch("knight_flow.stt_sessions.http_request", return_value=response) as request:
            result = current._transcribe_smallest(b"RIFF-test")

        self.assertEqual(result, "Smallest transcript.")
        url = request.call_args.args[0]
        kwargs = request.call_args.kwargs
        self.assertIn("/waves/v1/stt/?", url)
        self.assertIn("model=pulse-pro", url)
        self.assertIn("language=en", url)
        self.assertEqual(kwargs["body"], b"RIFF-test")

    def test_soniox_uploads_polls_reads_and_cleans_up(self) -> None:
        current = session("soniox", model="stt-async-v5")
        responses = [
            json.dumps({"id": "file-1"}).encode(),
            json.dumps({"id": "transcription-1"}).encode(),
            json.dumps({"status": "completed"}).encode(),
            json.dumps({"text": "Soniox transcript."}).encode(),
            b"",
            b"",
        ]
        with patch("knight_flow.stt_sessions.time.sleep"), patch(
            "knight_flow.stt_sessions.http_request",
            side_effect=responses,
        ) as request:
            result = current._transcribe_soniox(b"RIFF-test")

        self.assertEqual(result, "Soniox transcript.")
        calls = request.call_args_list
        self.assertEqual(calls[0].args[0], "https://api.soniox.com/v1/files")
        self.assertEqual(calls[1].args[0], "https://api.soniox.com/v1/transcriptions")
        self.assertEqual(calls[2].args[0], "https://api.soniox.com/v1/transcriptions/transcription-1")
        self.assertTrue(calls[3].args[0].endswith("/transcription-1/transcript"))
        self.assertEqual(calls[4].kwargs["method"], "DELETE")
        self.assertEqual(calls[5].kwargs["method"], "DELETE")

    def test_assemblyai_uses_current_speech_models_array(self) -> None:
        current = session("assemblyai", model="universal-3-pro", variant="speaker-labels")
        responses = [
            json.dumps({"upload_url": "https://cdn.example/audio.wav"}).encode(),
            json.dumps({"id": "transcript-1"}).encode(),
            json.dumps({"status": "completed", "text": "Assembly transcript."}).encode(),
        ]
        with patch("knight_flow.stt_sessions.time.sleep"), patch(
            "knight_flow.stt_sessions.http_request",
            side_effect=responses,
        ) as request:
            result = current._transcribe_assemblyai(b"RIFF-test")

        self.assertEqual(result, "Assembly transcript.")
        submit = request.call_args_list[1]
        body = json.loads(submit.kwargs["body"].decode("utf-8"))
        self.assertEqual(body["speech_models"], ["universal-3-pro"])
        self.assertNotIn("speech_model", body)
        self.assertTrue(body["speaker_labels"])

    def test_transcription_alias_is_extracted(self) -> None:
        self.assertEqual(extract_text({"transcription": "hello"}), "hello")


if __name__ == "__main__":
    unittest.main()
