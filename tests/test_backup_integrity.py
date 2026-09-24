"""Real file/database roundtrips; every fixture lives in a disposable home."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from knight_flow import config, packs
from knight_flow import backups
from knight_flow.history import SqliteHistoryStore


class BackupIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = patch.dict(os.environ, TALK_DAT_HOME=str(self.root))
        self.home.start(); self.addCleanup(self.home.stop)
        self.zip = self.root / 'backup.zip'

    def archive(self, files):
        with zipfile.ZipFile(self.zip, 'w') as archive:
            for name, body in files:
                archive.writestr(name, body)
        return self.zip

    def test_sqlite_backup_includes_committed_wal_and_restores_live_database(self):
        store = SqliteHistoryStore()
        store.append({'text': 'first café line'})
        connection = sqlite3.connect(config.history_db_path())
        self.addCleanup(connection.close)
        connection.execute('PRAGMA wal_autocheckpoint=0')
        connection.execute('SELECT COUNT(*) FROM history').fetchone()
        store.append({'text': 'second 中文 line'})
        self.assertTrue(config.history_db_path().with_suffix('.db-wal').exists())
        packs.export_backup(self.zip)
        with zipfile.ZipFile(self.zip) as archive:
            self.assertIn('history.db', archive.namelist())
            self.assertNotIn('history.db-wal', archive.namelist())
        store.append({'text': 'later entry'})
        restored = packs.restore_backup(self.zip)
        self.assertIn('history.db', restored)
        self.assertEqual([row['text'] for row in store.recent(10)], ['first café line', 'second 中文 line'])
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM history').fetchone()[0], 2)

    def test_legacy_note_and_full_transcript_survive(self):
        config.scratchpad_path().write_text('Unmigrated note ✓', encoding='utf-8')
        config.full_history_path().write_text('Full archive', encoding='utf-8')
        packs.export_backup(self.zip)
        config.scratchpad_path().unlink(); config.full_history_path().unlink()
        packs.restore_backup(self.zip)
        self.assertEqual(config.scratchpad_path().read_text(encoding='utf-8'), 'Unmigrated note ✓')
        self.assertEqual(config.full_history_path().read_text(), 'Full archive')

    def test_failed_export_preserves_the_previous_archive(self):
        self.zip.write_bytes(b'previous good backup')
        config.history_db_path().write_bytes(b'corrupted database')
        with self.assertRaises((ValueError, sqlite3.Error)):
            packs.export_backup(self.zip)
        self.assertEqual(self.zip.read_bytes(), b'previous good backup')

    def test_invalid_later_member_changes_nothing(self):
        config.config_path().write_text('{"theme":"old"}')
        (self.root / 'pinned.json').write_text('[]')
        self.archive([('config.json', '{"theme":"new"}'), ('pinned.json', '{bad json')])
        with self.assertRaises(ValueError): packs.restore_backup(self.zip)
        self.assertEqual(json.loads(config.config_path().read_text()), {'theme': 'old'})
        self.assertEqual((self.root / 'pinned.json').read_text(), '[]')

    def test_duplicate_members_are_rejected_before_any_write(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            self.archive([('config.json', '{}'), ('config.json', '{"later":true}')])
        with self.assertRaises(ValueError): packs.restore_backup(self.zip)
        self.assertFalse(config.config_path().exists())

    def test_archive_without_supported_content_is_not_success(self):
        self.archive([('../config.json', '{}'), ('other.txt', 'ignore')])
        with self.assertRaises(ValueError): packs.restore_backup(self.zip)
        self.assertFalse(config.config_path().exists())

    def test_malformed_sqlite_never_replaces_current_files(self):
        config.config_path().write_text('{"theme":"old"}')
        self.archive([('config.json', '{}'), ('history.db', 'not a database')])
        with self.assertRaises((ValueError, sqlite3.Error)): packs.restore_backup(self.zip)
        self.assertEqual(json.loads(config.config_path().read_text()), {'theme': 'old'})

    def test_failed_second_replace_rolls_back_first_file(self):
        config.config_path().write_text('{"theme":"old"}')
        (self.root / 'pinned.json').write_text('[{"text":"old pin"}]')
        self.archive([('config.json', '{"theme":"new"}'), ('pinned.json', '[]')])
        original = os.replace
        def fail_once(source, target):
            if Path(target).resolve() == (self.root / 'pinned.json').resolve() and not getattr(fail_once, 'failed', False):
                fail_once.failed = True
                raise OSError('injected disk error')
            return original(source, target)
        with patch('os.replace', side_effect=fail_once):
            with self.assertRaises(OSError): packs.restore_backup(self.zip)
        self.assertEqual(json.loads(config.config_path().read_text()), {'theme': 'old'})
        self.assertEqual(json.loads((self.root / 'pinned.json').read_text())[0]['text'], 'old pin')

    def test_restore_protects_settings_from_stale_quit_save_until_restart(self):
        self.archive([('config.json', '{"theme":"restored"}')])
        packs.restore_backup(self.zip)
        with self.assertRaisesRegex(ValueError, '[Rr]estart'):
            config.save_config({'theme': 'old process'})
        self.assertEqual(json.loads(config.config_path().read_text()), {'theme': 'restored'})

    def test_restore_size_limit_is_checked_before_writes(self):
        self.archive([('config.json', '{}'), ('scratchpad.md', 'x' * 110)])
        with patch.object(backups, 'MAX_BACKUP_MEMBER_BYTES', 100):
            with self.assertRaises(ValueError): packs.restore_backup(self.zip)
        self.assertFalse(config.config_path().exists())

    def test_changed_preview_is_rejected(self):
        self.archive([('config.json', '{"theme":"shown"}')])
        preview = backups.inspect_backup(self.zip)
        self.archive([('config.json', '{"theme":"different"}')])
        with self.assertRaisesRegex(ValueError, 'changed'):
            packs.restore_backup(self.zip, expected_digest=preview['digest'])
        self.assertFalse(config.config_path().exists())

    def test_symlink_member_is_not_restored(self):
        entry = zipfile.ZipInfo('config.json')
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        with zipfile.ZipFile(self.zip, 'w') as archive: archive.writestr(entry, '{}')
        with self.assertRaises(ValueError): packs.restore_backup(self.zip)
        self.assertFalse(config.config_path().exists())

    def test_failed_rollback_keeps_previous_copy_for_recovery(self):
        config.config_path().write_text('{"theme":"old"}')
        (self.root / 'pinned.json').write_text('[{"text":"old pin"}]')
        self.archive([('config.json', '{"theme":"new"}'), ('pinned.json', '[]')])
        original = os.replace
        def unavailable(source, target):
            if Path(target).name == 'pinned.json' or (Path(source).parent.name == 'previous' and Path(target).name == 'config.json'):
                raise OSError('injected disk unavailable')
            return original(source, target)
        with patch('os.replace', side_effect=unavailable):
            with self.assertRaisesRegex(OSError, 'need recovery'): packs.restore_backup(self.zip)
        copies = list(self.root.glob('.restore-*/previous/config.json'))
        self.assertEqual(len(copies), 1)
        self.assertEqual(json.loads(copies[0].read_text()), {'theme': 'old'})

    def test_backup_cannot_overwrite_a_live_source_file(self):
        config.config_path().write_text('{"theme":"old"}')
        with self.assertRaises(ValueError): packs.export_backup(config.config_path())
        self.assertEqual(json.loads(config.config_path().read_text()), {'theme': 'old'})

    def test_invalid_settings_section_is_rejected_before_restore(self):
        self.archive([('config.json', '{"privacy":[]}')])
        with self.assertRaises(ValueError): packs.restore_backup(self.zip)
        self.assertFalse(config.config_path().exists())

    def test_total_archive_size_is_bounded(self):
        self.archive([('scratchpad.md', 'a' * 60), ('full-transcript-history.txt', 'b' * 60)])
        with patch.object(backups, 'MAX_BACKUP_TOTAL_BYTES', 100):
            with self.assertRaises(ValueError): packs.restore_backup(self.zip)
        self.assertFalse(config.scratchpad_path().exists())

    def test_valid_backup_can_recover_a_damaged_current_database(self):
        store = SqliteHistoryStore()
        store.append({'text': 'Recover these words'})
        packs.export_backup(self.zip)
        config.history_db_path().write_bytes(b'broken current database')
        packs.restore_backup(self.zip)
        self.assertEqual(store.last_text(), 'Recover these words')

if __name__ == '__main__': unittest.main()
