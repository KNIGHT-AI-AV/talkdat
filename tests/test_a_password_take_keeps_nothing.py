"""P0-2 (find-more sweep): a take typed into a password field keeps nothing.

X-604 kept a password out of History and the formatting journal, and the Pill
says "Nothing was kept". But `on_session_done` wrote before `handle_dictation`
decided anything: the raw words went into the protected recording's metadata,
the live crash draft got them, the recording was finalized with the final
text, and its audio stayed in the spool, where Recovery listed it with a text
preview and a Copy button. The only password test drove `handle_dictation`
alone, so it could not see any of this.

These tests drive `on_session_done` with a real spool in a scratch data folder.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow import field_context as fc
from knight_flow.app import TalkDatApp
from knight_flow.audio_spool import audio_spool_dir, list_safety_sessions, recover_interrupted_sessions, start_safety_capture
from tests.test_app_session_lifecycle import _app

SECRET = "blue harbor seven"


class _Scratch(unittest.TestCase):
    def setUp(self) -> None:
        self._old_home = os.environ.get("TALK_DAT_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["TALK_DAT_HOME"] = self._tmp.name
        self.home = Path(self._tmp.name)

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old_home
        self._tmp.cleanup()

    def files_holding(self, needle: str) -> list[str]:
        found = []
        for path in self.home.rglob("*"):
            if path.is_file():
                with open(path, "rb") as handle:
                    if needle.encode("utf-8") in handle.read().lower():
                        found.append(path.name)
        return found

    def take(self, field: str):
        token = object()
        app = _app(token)
        app.config = {"privacy": {"save_history": True}}
        probe = fc.FieldProbe(kind=field)
        app._session_field = (token, probe)
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        capture.field_probe = probe
        capture.append(b"\x10\x27" * 16000, 16000, 1, heard_voice=True)
        app.safety_capture = capture
        app.safety_capture_token = token
        app.recover_transcript_if_needed = lambda _session, _mode, text: text
        app.write_live_draft = TalkDatApp.write_live_draft.__get__(app)
        app.handle_dictation = lambda text, **_kw: {"text": text, "delivery": {"success": True, "method": "type"}}
        draft = self.home / "live-transcript-draft.txt"
        with patch("knight_flow.app.live_draft_path", return_value=draft), \
             patch("knight_flow.app.save_config"):
            app.on_session_done(token, "dictation", SECRET)
        return app, capture, draft


class APasswordTakeKeepsNothing(_Scratch):
    def test_no_audio_no_words_no_recovery_entry(self) -> None:
        _app_, capture, draft = self.take(fc.PASSWORD)
        self.assertFalse(capture.audio_path.exists(), "the spoken password stayed on disk as audio")
        self.assertFalse(capture.metadata_path.exists(), "the password take stayed in the spool")
        self.assertEqual(list_safety_sessions(1000), [], "Recovery would list the password take")
        self.assertFalse(draft.exists(), "the crash draft holds the password")
        self.assertEqual(self.files_holding("harbor"), [], "the password is written somewhere")

    def test_a_later_update_cannot_bring_the_metadata_back(self) -> None:
        _app_, capture, _draft = self.take(fc.PASSWORD)
        capture.update(status="delivered", raw_transcript=SECRET)
        self.assertFalse(capture.metadata_path.exists())

    def test_an_ordinary_field_still_keeps_its_recording(self) -> None:
        # Positive control: the same take into a normal field is protected as
        # before, so the assertions above are about the field, not the fixture.
        _app_, capture, draft = self.take(fc.MULTI_LINE)
        self.assertTrue(capture.audio_path.exists())
        sessions = list_safety_sessions(1000)
        self.assertEqual([item["status"] for item in sessions], ["delivered"])
        self.assertEqual(sessions[0]["final_text"], SECRET)
        self.assertTrue(draft.exists())


class ACrashDuringAPasswordTakeKeepsNothing(_Scratch):
    def test_the_take_is_marked_as_soon_as_the_field_is_known(self) -> None:
        token = object()
        app = _app(token)
        app.config = {"privacy": {"save_history": True}}
        app._session_field = (token, fc.FieldProbe(kind=fc.PASSWORD))
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        app.safety_capture = capture
        app.safety_capture_token = token
        app.on_session_update(token, "dictation", SECRET, False)
        metadata = json.loads(capture.metadata_path.read_text(encoding="utf-8"))
        self.assertIs(metadata.get("password_field"), True)
        self.assertNotIn("harbor", json.dumps(metadata))
        capture.discard()

    def test_the_next_launch_deletes_it_instead_of_offering_it(self) -> None:
        root = audio_spool_dir()
        (root / "crashed.wav").write_bytes(b"RIFF" + b"\x00" * 60)
        (root / "crashed.json").write_text(json.dumps({
            "session_id": "crashed", "status": "recording", "audio_file": "crashed.wav",
            "created_at": time.time(), "password_field": True}), encoding="utf-8")
        (root / "ordinary.wav").write_bytes(b"RIFF" + b"\x00" * 60)
        (root / "ordinary.json").write_text(json.dumps({
            "session_id": "ordinary", "status": "recording", "audio_file": "ordinary.wav",
            "created_at": time.time()}), encoding="utf-8")
        self.assertEqual(recover_interrupted_sessions(), 1)
        self.assertEqual([item["session_id"] for item in list_safety_sessions(1000)], ["ordinary"])
        self.assertFalse((root / "crashed.wav").exists())


class TheSessionStartHandsTheFieldToTheCapture(unittest.TestCase):
    def test_the_capture_carries_the_takes_field_read(self) -> None:
        from tests.test_signed_out_still_dictates import _FakeApp, _run_start_session

        app = _FakeApp(account_active=False)
        self.assertIsNotNone(_run_start_session(app, model_on_disk=True))
        self.assertIs(app.safety_capture.field_probe, app._session_field[1])


if __name__ == "__main__":
    unittest.main()
