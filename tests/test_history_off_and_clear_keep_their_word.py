"""P0-6 (find-more sweep): "History off" and "Clear text history" do what they say.

Settings says History off "keeps no record", but every protected recording
kept the raw and final text of its take in its metadata whatever the switch
said, and the formatting journal kept both too. "Clear text history" (web
shell and Tk) cleared History, the full transcript file and the drafts, but
not the journal and not the words kept with each recording; the Tk path also
swallowed a failed clear and said "History cleared."; and neither emptied
`last_transcript`, so Paste Last pasted the cleared words until a restart.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow import field_context as fc
from knight_flow.app import TalkDatApp
from knight_flow.audio_spool import list_safety_sessions, start_safety_capture
from knight_flow.config import full_history_path, history_db_path, history_path, live_draft_path, recovered_draft_path
from knight_flow.format_journal import journal_path, record_formatting
from knight_flow.history import clear_saved_text, pinned_path
from tests.test_app_session_lifecycle import _app

WORDS = "meet me by the quiet orchard"


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

    def files_holding(self, needle: str, *, skip: tuple[str, ...] = ()) -> list[str]:
        found = []
        for path in self.home.rglob("*"):
            if path.is_file() and path.name not in skip:
                with open(path, "rb") as handle:
                    if needle.encode("utf-8") in handle.read().lower():
                        found.append(path.name)
        return found


class HistoryOffKeepsNoWords(_Scratch):
    def take(self, save_history: bool):
        token = object()
        app = _app(token)
        app.config = {"privacy": {"save_history": save_history}}
        probe = fc.FieldProbe(kind=fc.MULTI_LINE)
        app._session_field = (token, probe)
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        capture.field_probe = probe
        capture.append(b"\x10\x27" * 16000, 16000, 1, heard_voice=True)
        app.safety_capture = capture
        app.safety_capture_token = token
        app.recover_transcript_if_needed = lambda _session, _mode, text: text
        app.handle_dictation = lambda text, **_kw: {"text": text, "delivery": {"success": True, "method": "paste"}}
        with patch("knight_flow.app.save_config"):
            app.on_session_done(token, "dictation", WORDS)
        return capture

    def test_a_take_with_history_off_keeps_audio_only(self) -> None:
        capture = self.take(save_history=False)
        self.assertTrue(capture.audio_path.exists(), "Recover needs the audio")
        sessions = list_safety_sessions(1000)
        self.assertEqual(len(sessions), 1)
        self.assertEqual((sessions[0]["raw_transcript"], sessions[0]["final_text"]), ("", ""))
        self.assertEqual(self.files_holding("orchard"), [])

    def test_a_take_with_history_on_keeps_its_words(self) -> None:
        # Positive control: the fixture really writes words when allowed to.
        self.take(save_history=True)
        self.assertEqual(list_safety_sessions(1000)[0]["final_text"], WORDS)

    def test_the_journal_writes_nothing_with_history_off(self) -> None:
        config = {"privacy": {"save_history": False}, "diagnostics": {"formatting_journal": True}}
        record_formatting(config, raw=WORDS, final=WORDS, stage="paste")
        self.assertFalse(journal_path().exists())
        config["privacy"]["save_history"] = True
        record_formatting(config, raw=WORDS, final=WORDS, stage="paste")
        self.assertTrue(journal_path().exists(), "positive control: the journal is on")


class ClearTextHistoryClearsEveryStore(_Scratch):
    def seed(self) -> object:
        history_path().write_text(json.dumps({"text": WORDS}) + "\n", encoding="utf-8")
        for path in (full_history_path(), live_draft_path(), recovered_draft_path()):
            path.write_text(WORDS, encoding="utf-8")
        journal_path().write_text(json.dumps({"raw": WORDS}) + "\n", encoding="utf-8")
        journal_path().with_suffix(".jsonl.1").write_text(json.dumps({"raw": WORDS}) + "\n", encoding="utf-8")
        pinned_path().write_text(json.dumps([{"text": "pinned on purpose"}]), encoding="utf-8")
        capture = start_safety_capture(mode="dictation", control="hold", provider="local", model="")
        capture.append(b"\x10\x27" * 16000, 16000, 1, heard_voice=True)
        capture.finalize(status="delivered", raw_transcript=WORDS, final_text=WORDS)
        return capture

    def test_every_store_is_cleared_and_pins_and_audio_stay(self) -> None:
        capture = self.seed()
        self.assertTrue(self.files_holding("orchard"), "positive control: the words were seeded")
        self.assertEqual(clear_saved_text(), [])
        self.assertEqual(self.files_holding("orchard"), [])
        self.assertTrue(capture.audio_path.exists(), "the dialog says recordings stay")
        self.assertIn("pinned on purpose", pinned_path().read_text(encoding="utf-8"))

    def test_a_store_that_cannot_be_cleared_is_named(self) -> None:
        self.seed()
        history_db_path().write_bytes(b"")
        with patch("knight_flow.history.SqliteHistoryStore.clear", side_effect=sqlite3.OperationalError("locked")):
            self.assertEqual(clear_saved_text(), ["the searchable history"])

    def web_clear(self, app):
        from knight_flow.web_shell.workspace_adapter import Workspaces

        workspaces = Workspaces.__new__(Workspaces)
        workspaces.app, workspaces.config, workspaces.busy = app, {}, lambda: False
        return workspaces.history_utility("clear_text", True)

    def test_the_web_shell_clears_paste_lasts_source(self) -> None:
        self.seed()
        app = _app(object())
        app.config = {"privacy": {"save_history": True}}
        app.last_transcript, app.last_original, app.last_raw_transcript = WORDS, WORDS, WORDS
        result = self.web_clear(app)
        self.assertIn("formatting journal", result["message"])
        self.assertEqual((app.last_transcript, app.last_original, app.last_raw_transcript), ("", "", ""))
        TalkDatApp.paste_last(app)
        self.assertEqual(app.overlay.states[-1], ("error", "No previous transcript to paste."))

    def test_the_web_shell_says_when_something_was_not_cleared(self) -> None:
        self.seed()
        history_db_path().write_bytes(b"")
        with patch("knight_flow.history.SqliteHistoryStore.clear", side_effect=sqlite3.OperationalError("locked")):
            with self.assertRaises(ValueError) as caught:
                self.web_clear(_app(object()))
        self.assertIn("searchable history", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
