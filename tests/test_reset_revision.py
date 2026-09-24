"""Synthetic reset regression fixtures; never point these at the owner's profile."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from knight_flow import reset

class ResetRevisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="talkdat-reset-proof-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = {"dictionary": {"words": ["Keep"]}, "licensing": {"device_id": "keep"},
                       "ui": {"settings_theme": "Moss"}, "plugins": {"enabled": True},
                       "wake_word": {"enabled": True}, "privacy": {"local_only": True}}
        self.written = []
        vault = patch.object(reset, "delete_all_credentials", return_value=True)
        self.vault = vault.start(); self.addCleanup(vault.stop)

    def file(self, name, body=b"private fixture"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def erase(self, keys, **kwargs):
        return reset.perform(keys, self.root, read_config=lambda: self.config,
                             write_config=lambda value, forgotten: self.written.append((value, forgotten)), **kwargs)

    def test_history_clears_rotated_journal(self):
        path = self.file("formatting-journal.jsonl.1")
        self.erase(["history"])
        self.assertFalse(path.exists())

    def test_history_clears_sqlite_sidecars(self):
        paths = [self.file(name) for name in ["history.db-wal", "history.db-shm", "history.db-journal"]]
        self.erase(["history"])
        self.assertTrue(all(not path.exists() for path in paths))

    def test_dictionary_clears_pronunciation_recordings_only(self):
        clip = self.file("pronunciation/name/take-0.wav")
        other = self.file("scribe-recordings/conversation/microphone.wav")
        self.erase(["dictionary"])
        self.assertFalse(clip.exists())
        self.assertTrue(other.exists())
        self.vault.assert_not_called()

    def test_scribe_has_separate_opt_in_category(self):
        self.assertIn("scribe", reset.CATEGORY_BY_KEY)
        self.assertFalse(reset.CATEGORY_BY_KEY["scribe"].default_checked)
        clip = self.file("scribe-recordings/conversation/microphone.wav")
        self.erase(["scribe"])
        self.assertFalse(clip.exists())

    def test_scribe_reset_covers_older_meeting_notes(self):
        note = self.file("meetings/old-conversation.md")
        self.erase(["scribe"])
        self.assertFalse(note.exists())

    def test_app_settings_reset_covers_current_preferences(self):
        self.erase(["settings"])
        saved = self.written[0][0]
        for name in ("ui", "plugins", "wake_word", "privacy"):
            self.assertNotIn(name, saved)
        self.assertEqual(saved["dictionary"], self.config["dictionary"])
        self.assertEqual(saved["licensing"], self.config["licensing"])

    def test_app_preferences_have_separate_opt_in_category(self):
        self.assertIn("profiles", reset.CATEGORY_BY_KEY)
        self.assertFalse(reset.CATEGORY_BY_KEY["profiles"].default_checked)
        self.config.update(profiles=[{"id": "personal"}], style_profile={"votes": 20})
        self.erase(["profiles"])
        self.assertNotIn("profiles", self.written[0][0])
        self.assertNotIn("style_profile", self.written[0][0])

    def test_duplicate_selection_does_not_double_count_or_fail(self):
        path = self.file("history.jsonl", b"12345")
        intended = reset.plan(["history", "history"], self.root)
        self.assertEqual(intended.bytes_freed, 5)
        self.assertEqual(len(intended.categories), 1)
        self.assertEqual(self.erase(["history", "history"])["failed"], [])

    def test_failed_delete_does_not_claim_freed_bytes(self):
        self.file("history.jsonl", b"12345")
        with patch.object(Path, "unlink", side_effect=PermissionError):
            result = self.erase(["history"])
        self.assertEqual(result["bytes_freed"], 0)
        self.assertIn("history.jsonl", result["failed"])

    def test_vault_false_result_is_reported(self):
        self.vault.return_value = False
        self.assertIn("saved keys", self.erase(["settings"])["failed"])

    def test_missing_signout_handler_is_reported(self):
        self.assertIn("sign-in", self.erase(["account"])["failed"])

    def test_preview_rejects_new_file_without_erasing_existing(self):
        original = self.file("history.jsonl")
        preview = reset.plan(["history"], self.root)
        self.file("pinned.json", b"[]")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.erase(["history"], expected=preview)
        self.assertTrue(original.exists())

if __name__ == "__main__":
    unittest.main()

