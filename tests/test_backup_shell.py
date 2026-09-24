"""Restore selection and confirmation are separate, one-use operations."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from tests import test_web_shell_app
from knight_flow import config


class BackupShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        home = patch.dict(os.environ, TALK_DAT_HOME=str(self.root)); home.start(); self.addCleanup(home.stop)
        self.file = self.root / 'restore.zip'
        with zipfile.ZipFile(self.file, 'w') as archive: archive.writestr('config.json', '{"theme":"restored"}')
        self.app, self.shell = test_web_shell_app.AppShellTests().make_shell()
        self.shell._capture_busy = Mock(return_value=False)
        picker = patch('tkinter.filedialog.askopenfilename', return_value=str(self.file))
        self.picker = picker.start(); self.addCleanup(picker.stop)

    def call(self, name): return self.shell.backend.handle('action', {'name': name})

    def test_preview_does_not_restore_or_quit(self):
        result = self.call('restore_backup')
        self.assertEqual(result['backup_preview']['files'], ['config.json'])
        self.assertNotIn('digest', result['backup_preview'])
        self.assertFalse(config.config_path().exists())
        self.app._cross_thread_calls.put.assert_not_called()

    def test_cancel_consumes_selection(self):
        self.call('restore_backup'); self.call('restore_backup_cancel')
        with self.assertRaises(ValueError): self.call('restore_backup_confirm')
        self.assertFalse(config.config_path().exists())

    def test_confirm_restores_once_then_schedules_normal_quit(self):
        self.call('restore_backup'); self.call('restore_backup_confirm')
        self.assertIn('restored', config.config_path().read_text())
        self.app._cross_thread_calls.put.call_args.args[0]()
        self.app.quit.assert_called_once_with(settings_confirmed=True)
        with self.assertRaises(ValueError): self.call('restore_backup_confirm')

    def test_active_capture_prevents_selection_and_later_confirmation(self):
        self.shell._capture_busy.return_value = True
        with self.assertRaises(ValueError): self.call('restore_backup')
        self.picker.assert_not_called()
        self.shell._capture_busy.return_value = False; self.call('restore_backup')
        self.shell._capture_busy.return_value = True
        with self.assertRaises(ValueError): self.call('restore_backup_confirm')
        self.assertFalse(config.config_path().exists())

    def test_changed_archive_is_rejected_without_quitting(self):
        self.call('restore_backup')
        with zipfile.ZipFile(self.file, 'w') as archive: archive.writestr('config.json', '{}')
        with self.assertRaisesRegex(ValueError, 'changed'): self.call('restore_backup_confirm')
        self.app._cross_thread_calls.put.assert_not_called()
        self.assertFalse(config.config_path().exists())

    def test_expired_selection_cannot_restore(self):
        self.call('restore_backup')
        source, digest, moment = self.shell._pending_backup
        self.shell._pending_backup = (source, digest, moment - 301)
        with self.assertRaises(ValueError): self.call('restore_backup_confirm')
        self.assertFalse(config.config_path().exists())

    def test_restore_request_cannot_supply_a_renderer_path(self):
        with self.assertRaises(ValueError):
            self.shell.backend.handle('action', {'name': 'restore_backup_confirm', 'path': str(self.file)})
        self.assertFalse(config.config_path().exists())

if __name__ == '__main__': unittest.main()
