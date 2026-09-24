import copy,threading,time,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.web_shell.setup_adapter import SetupActions


class SetupActionTests(unittest.TestCase):
    def setUp(self):
        self.app=SimpleNamespace(lock=threading.RLock(),config=copy.deepcopy(DEFAULT_CONFIG),session_token=None,
            overlay=SimpleNamespace(onboarding_test_sink=None,state='listening'),
            hotkeys=SimpleNamespace(lock=threading.RLock(),_shortcut_recording_until=0,pressed=set()))
        def record(active):self.app.hotkeys._shortcut_recording_until=time.monotonic()+15 if active else 0
        self.app.hotkeys.record_shortcut=Mock(side_effect=record)
        self.app.start_session=Mock(side_effect=lambda *a,**k:setattr(self.app,'session_token',object()))
        self.app.cancel=Mock();self.app.stop_session=Mock();self.busy=Mock(return_value=False);self.copy=Mock()
        self.action=SetupActions(self.app,self.copy,self.busy)
        self.registry=patch('knight_flow.mic_registry.microphone_registry',return_value=SimpleNamespace(is_active=lambda:False));self.registry.start();self.addCleanup(self.registry.stop)
    def test_practice_owns_exact_session_and_sink(self):
        receive=Mock();self.action('speech_start',receive);sink=self.app.overlay.onboarding_test_sink
        sink('Received');receive.assert_called_once_with('Received');self.assertIsNone(self.app.overlay.onboarding_test_sink)
    def test_new_recording_cannot_receive_old_setup_result(self):
        receive=Mock();self.action('speech_start',receive);sink=self.app.overlay.onboarding_test_sink
        self.app.session_token=object();sink('Late');receive.assert_not_called()
    def test_cancel_precedes_releasing_sink(self):
        self.action('speech_start',Mock());sink=self.app.overlay.onboarding_test_sink
        self.app.cancel.side_effect=lambda:self.assertIs(self.app.overlay.onboarding_test_sink,sink)
        self.action('speech_cancel',None);self.app.cancel.assert_called_once();self.assertIsNone(self.app.overlay.onboarding_test_sink)
    def test_cancel_does_not_cancel_foreign_session_or_erase_foreign_sink(self):
        self.action('speech_start',Mock());self.app.session_token=object();foreign=Mock();self.app.overlay.onboarding_test_sink=foreign
        self.action('speech_cancel',None);self.app.cancel.assert_not_called();self.assertIs(self.app.overlay.onboarding_test_sink,foreign)
    def test_start_refuses_busy_or_other_guided_surface(self):
        self.busy.return_value=True
        with self.assertRaises(ValueError):self.action('speech_start',Mock())
        self.busy.return_value=False;self.app.overlay.onboarding_test_sink=Mock()
        with self.assertRaises(ValueError):self.action('speech_start',Mock())
        self.app.start_session.assert_not_called()
    def test_failed_start_releases_its_sink(self):
        self.app.start_session.side_effect=OSError()
        with self.assertRaises(OSError):self.action('speech_start',Mock())
        self.assertIsNone(self.app.overlay.onboarding_test_sink)
    def test_rehearsal_does_not_open_microphone(self):
        self.action('rehearsal_start',None);self.app.start_session.assert_not_called()
        self.assertGreater(self.app.hotkeys._shortcut_recording_until,time.monotonic())
    def test_rehearsal_needs_actual_trigger_state(self):
        self.action('rehearsal_start',None)
        with patch('knight_flow.web_shell.setup_adapter.physical_key_down',return_value=False):
            self.assertFalse(self.action('rehearsal_status',None)['matched'])
        with patch('knight_flow.web_shell.setup_adapter.physical_key_down',return_value=True):
            result=self.action('rehearsal_status',None);self.assertTrue(result['matched']);self.assertTrue(result['active'])
        self.assertGreater(self.app.hotkeys._shortcut_recording_until,0)
        with patch('knight_flow.web_shell.setup_adapter.physical_key_down',return_value=False):
            result=self.action('rehearsal_status',None);self.assertTrue(result['matched']);self.assertFalse(result['active'])
        self.assertEqual(self.app.hotkeys._shortcut_recording_until,0)
    def test_rehearsal_expires_without_permanent_shortcut_disable(self):
        self.action('rehearsal_start',None);self.action.rehearsal_until=time.monotonic()-1
        self.assertFalse(self.action('rehearsal_status',None)['active']);self.assertEqual(self.app.hotkeys._shortcut_recording_until,0)
    def test_rehearsal_cannot_end_replacement_lease(self):
        self.action('rehearsal_start',None);self.app.hotkeys._shortcut_recording_until+=10;foreign=self.app.hotkeys._shortcut_recording_until
        self.action('rehearsal_stop',None);self.assertEqual(self.app.hotkeys._shortcut_recording_until,foreign)
    def test_permission_unknown_is_never_granted(self):
        fake=SimpleNamespace(PERMISSION_ORDER=('microphone','accessibility'),permission_report=lambda:{'microphone':'granted'})
        with patch('knight_flow.web_shell.setup_adapter.sys.platform','darwin'),patch('knight_flow.mac_support',fake,create=True):
            result=self.action('permissions',None)
        self.assertEqual([r['state'] for r in result],['granted','unknown'])
    def test_document_boundary_only_opens_known_terms_pages(self):
        with patch('webbrowser.open',return_value=True) as opened:
            with self.assertRaises(ValueError):self.action('document','file:///private')
            opened.assert_not_called();self.action('document','terms');self.assertIn('talkdat.app/terms',opened.call_args.args[0])
    def test_permission_probe_error_is_unknown_without_blocking_setup(self):
        fake=SimpleNamespace(PERMISSION_ORDER=('microphone',),permission_report=Mock(side_effect=OSError()))
        with patch('knight_flow.web_shell.setup_adapter.sys.platform','darwin'),patch('knight_flow.mac_support',fake,create=True):
            self.assertEqual(self.action('permissions',None)[0]['state'],'unknown')


if __name__=='__main__':unittest.main()
