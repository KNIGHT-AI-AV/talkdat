import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.web_shell.workspace_adapter import Workspaces


class WorkspaceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.patcher=patch('knight_flow.config.app_dir',return_value=self.root)
        self.patcher.start();self.addCleanup(self.patcher.stop)
        for target in ('knight_flow.history.app_dir','knight_flow.audio_spool.app_dir'):
            patcher=patch(target,return_value=self.root);patcher.start();self.addCleanup(patcher.stop)
        self.app=SimpleNamespace(config=copy.deepcopy(DEFAULT_CONFIG),overlay=Mock(),recover_audio_session=Mock())
        self.persist=Mock();self.busy=Mock(return_value=False)
        self.service=Workspaces(self.app,self.persist,self.busy)
    def test_clear_text_keeps_notes_pins_and_audio(self):
        from knight_flow.config import history_path,full_history_path,live_draft_path,recovered_draft_path,scratchpad_tabs_path
        from knight_flow.history import pin_text,pinned_entries
        from knight_flow.audio_spool import audio_spool_dir
        for path in (history_path(),full_history_path(),live_draft_path(),recovered_draft_path()):path.write_text('private words',encoding='utf-8')
        scratchpad_tabs_path().write_text('keep notes',encoding='utf-8')
        pin_text('keep this pin')
        audio_spool_dir().mkdir(exist_ok=True);audio=audio_spool_dir()/'take.wav';audio.write_bytes(b'keep recording')
        self.service.history_utility('clear_text',True)
        self.assertTrue(all(path.read_text(encoding='utf-8')=='' for path in (history_path(),full_history_path(),live_draft_path(),recovered_draft_path())))
        self.assertEqual(scratchpad_tabs_path().read_text(),'keep notes')
        self.assertEqual(pinned_entries()[0]['text'],'keep this pin')
        self.assertEqual(audio.read_bytes(),b'keep recording')
    def test_clear_requires_confirmation_and_idle_capture(self):
        for confirmed in (False,'true',None):
            with self.assertRaises(ValueError):self.service.history_utility('clear_audio',confirmed)
        self.busy.return_value=True
        with self.assertRaises(ValueError):self.service.history_utility('clear_text',True)
        with self.assertRaises(ValueError):self.service.recover('session')
        self.app.recover_audio_session.assert_not_called()
    def test_failed_preference_write_keeps_current_settings(self):
        before=copy.deepcopy(self.app.config)
        self.persist.side_effect=OSError('disk full')
        with self.assertRaises(OSError):self.service.set_font('Georgia')
        self.assertEqual(self.app.config,before)
    def test_copy_does_not_report_success_when_clipboard_is_busy(self):
        with patch('knight_flow.paste.copy_text',return_value=False):
            with self.assertRaisesRegex(ValueError,'clipboard'):self.service.copy('my words')
    def test_recovery_shows_configured_retention_and_rejects_foreign_audio(self):
        self.app.config['dictation']['safety_recording_limit']=10
        with patch('knight_flow.audio_spool.list_safety_sessions',return_value=[]) as sessions:self.service.sessions()
        sessions.assert_called_once_with(10)
        with patch.object(self.service,'open_path') as opened:
            with self.assertRaises(ValueError):self.service.play_recording({'audio_path':str(self.root/'elsewhere.wav')})
            opened.assert_not_called()
    def test_history_uses_the_current_backend_after_settings_change(self):
        stores=[Mock(),Mock()]
        for store in stores:store.recent.return_value=[]
        with patch('knight_flow.history.create_history_store',side_effect=stores) as factory:
            payload={'area':'history','operation':'list','query':'','offset':0,'pinned':False}
            self.service.handle(payload)
            self.app.config['privacy']['history_backend']='sqlite'
            self.service.handle(payload)
        self.assertEqual(factory.call_count,2)
        for store in stores:store.recent.assert_called_once_with(300)

if __name__=='__main__':unittest.main()
