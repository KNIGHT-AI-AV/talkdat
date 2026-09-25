"""P0-3 (find-more sweep): a take that fails is not lost quietly.

Three parts that compounded:
  1. A take whose voice was heard, retried, and still produced no words said
     "No speech captured. Ready again." (17 such takes in his log since 09-15).
  2. A crash mid-take was recovered at the next launch and only logged.
  3. Rotation kept the newest five recordings and deleted older ones whatever
     their status, so the only copy of a failed take went after five more
     dictations, recovered or not.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow import launch_notices, mac_support
from knight_flow.app import TalkDatApp
from knight_flow.audio_spool import (
    audio_spool_dir,
    list_safety_sessions,
    mark_session_handled,
    recover_interrupted_sessions,
    recovery_sessions,
    rotate_safety_recordings,
    start_safety_capture,
)
from tests.test_app_session_lifecycle import _app

DAY = 24 * 3600


class _Scratch(unittest.TestCase):
    def setUp(self) -> None:
        self._old_home = os.environ.get("TALK_DAT_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["TALK_DAT_HOME"] = self._tmp.name
        self.root = audio_spool_dir()
        launch_notices.clear()

    def tearDown(self) -> None:
        launch_notices.clear()
        if self._old_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old_home
        self._tmp.cleanup()

    def session(self, name: str, status: str, *, age: float, **extra) -> None:
        (self.root / f"{name}.wav").write_bytes(b"RIFF" + b"\x00" * 200)
        created = time.time() - age
        metadata = {"session_id": name, "status": status, "audio_file": f"{name}.wav",
                    "created_at": created, "updated_at": created, **extra}
        (self.root / f"{name}.json").write_text(json.dumps(metadata), encoding="utf-8")

    def names(self) -> set[str]:
        return {item["session_id"] for item in list_safety_sessions(1000)}


class RotationKeepsAFailedTakeUntilItIsHandled(_Scratch):
    def seed(self, status: str = "transcription_failed", **extra) -> None:
        self.session("failed", status, age=3600, **extra)
        for index in range(6):
            self.session(f"ok{index}", "delivered", age=60 - index)

    def test_a_failed_take_outlives_five_more_dictations(self) -> None:
        self.seed()
        rotate_safety_recordings(limit=5)
        self.assertIn("failed", self.names())
        self.assertEqual(len(self.names()), 6, "the oldest delivered take still rotates")

    def test_recovery_lists_it_beyond_the_newest_five(self) -> None:
        self.seed()
        rotate_safety_recordings(limit=5)
        self.assertEqual([item["session_id"] for item in recovery_sessions(5)][-1], "failed")

    def test_once_copied_it_rotates_like_any_other(self) -> None:
        self.seed()
        mark_session_handled("failed")
        rotate_safety_recordings(limit=5)
        self.assertNotIn("failed", self.names())

    def test_an_interrupted_take_is_kept_too(self) -> None:
        self.seed("interrupted")
        rotate_safety_recordings(limit=5)
        self.assertIn("failed", self.names())

    def test_a_silent_take_is_not_kept(self) -> None:
        self.seed("no_transcript", heard_voice=False)
        rotate_safety_recordings(limit=5)
        self.assertNotIn("failed", self.names())

    def test_a_heard_take_with_no_words_is_kept(self) -> None:
        self.seed("no_transcript", heard_voice=True)
        rotate_safety_recordings(limit=5)
        self.assertIn("failed", self.names())

    def test_the_age_cap_still_applies(self) -> None:
        self.session("old", "transcription_failed", age=15 * DAY)
        for index in range(6):
            self.session(f"ok{index}", "delivered", age=60 - index)
        rotate_safety_recordings(limit=5)
        self.assertNotIn("old", self.names())


class AHeardVoiceIsNotNoSpeech(_Scratch):
    class _Session:
        def __init__(self, pcm: bytes, heard: bool) -> None:
            self.transport_degraded = False
            self._pcm, self._heard = pcm, heard

        def captured_audio(self):
            return self._pcm, 16000, 1, self._heard

    def take(self, pcm: bytes, heard: bool):
        token = object()
        app = _app(token)
        app.config = {"privacy": {"save_history": True}, "dictation": {}}
        app.session = self._Session(pcm, heard)
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        capture.append(pcm, 16000, 1, heard_voice=heard)
        app.safety_capture = capture
        app.safety_capture_token = token
        with patch("knight_flow.app.transcribe_pcm", return_value=""), \
             patch("knight_flow.app.local_fallback.rescue_model", return_value=None), \
             patch("knight_flow.app.save_config"):
            app.on_session_done(token, "dictation", "")
        return app, capture

    def test_a_heard_voice_with_no_words_says_so_and_keeps_the_audio(self) -> None:
        app, capture = self.take(b"\x10\x27" * 16000, heard=True)
        messages = [message for _state, message in app.overlay.states]
        self.assertNotIn("No speech captured. Ready again.", messages)
        self.assertIn(("error", "Heard you, but got no words."), app.overlay.states)
        for index in range(6):
            self.session(f"ok{index}", "delivered", age=-1 - index)
        rotate_safety_recordings(limit=5)
        self.assertIn(capture.session_id, self.names(), "the heard take must outlive rotation")

    def test_silence_still_says_no_speech(self) -> None:
        app, _capture = self.take(b"\x00\x00" * 16000, heard=False)
        if mac_support.IS_MAC:
            # All-zero samples are exactly what a refused microphone hands
            # back on macOS (X-721: measured with speech playing aloud, peak
            # amplitude 0), so the app names that instead of telling someone
            # who never got a working mic that they simply didn't speak.
            self.assertEqual(
                app.overlay.states[-1],
                ("error", "The microphone sent no signal at all."),
            )
        else:
            self.assertEqual(app.overlay.states[-1], ("idle", "No speech captured. Ready again."))


class ACrashIsAnnouncedOnce(_Scratch):
    def test_an_interrupted_take_with_audio_is_announced(self) -> None:
        pcm = b"\x10\x27" * 3200
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        capture.append(pcm, 16000, 1, heard_voice=True)
        self.assertTrue(capture.flush())
        started = time.time()
        self.assertEqual(recover_interrupted_sessions(), 1)
        TalkDatApp._announce_interrupted_takes(started)
        notices = launch_notices.pending()
        self.assertEqual([(item["key"], item["page"]) for item in notices], [("recovery", "recovery")])
        self.assertIn("Recovery", notices[0]["message"])
        capture.discard()

    def test_an_interrupted_take_without_audio_is_not(self) -> None:
        self.session("empty", "recording", age=10)
        (self.root / "empty.wav").write_bytes(b"")
        started = time.time()
        recover_interrupted_sessions()
        TalkDatApp._announce_interrupted_takes(started)
        self.assertEqual(launch_notices.pending(), [])


if __name__ == "__main__":
    unittest.main()
