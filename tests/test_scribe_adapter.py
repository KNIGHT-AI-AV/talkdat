import queue,threading,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from knight_flow.web_shell.scribe_adapter import ScribeActions


class ScribeActionsTests(unittest.TestCase):
    def setUp(self):
        self.engine=SimpleNamespace(body='Current notes',saved_path='notes.md',finish=Mock(),cancel=Mock(),retry=Mock())
        self.app=SimpleNamespace(config={'scribe':{'source':'both'},'privacy':{'local_only':True}},_scribe_engine=self.engine,
            toggle_scribe=Mock(),_cross_thread_calls=queue.Queue(),_on_scribe_state=Mock())
        self.copy=Mock();self.open=Mock();self.busy=Mock(return_value=False);self.library=Mock()
        self.actions=ScribeActions(self.app,self.copy,self.open,self.busy,self.library)
    def test_start_refusal_is_reported_when_app_did_not_create_engine(self):
        with self.assertRaisesRegex(ValueError,'could not start'):self.actions('start',None)
    def test_unsaved_note_is_not_replaced(self):
        self.engine.saved_path=None
        with self.assertRaisesRegex(ValueError,'Save a copy'):self.actions('start',None)
        self.app.toggle_scribe.assert_not_called()
    def test_busy_audio_refuses_start_and_retry(self):
        self.busy.return_value=True
        for operation,value in [('start',None),('retry',self.engine)]:
            with self.subTest(operation=operation),self.assertRaises(ValueError):self.actions(operation,value)
        self.engine.retry.assert_not_called()
    def test_stop_finishes_only_the_current_owner(self):
        self.actions('finish',self.engine);self.engine.finish.assert_called_once()
        self.actions('stop',self.engine);self.engine.cancel.assert_called_once()
        for operation in ('finish','stop','retry'):
            with self.assertRaises(ValueError):self.actions(operation,object())
    def test_retry_receives_independent_current_config(self):
        self.actions('retry',self.engine);config=self.engine.retry.call_args.kwargs['config']
        self.app.config['privacy']['local_only']=False;self.assertTrue(config['privacy']['local_only'])
    def test_late_restore_cannot_adopt_over_another_engine(self):
        with self.assertRaises(ValueError):self.actions('adopt',{'previous':object(),'engine':object()})
        self.assertIs(self.app._scribe_engine,self.engine)
    def test_adopt_preserves_identity_and_checks_current_activity(self):
        value=object();self.actions('adopt',{'previous':self.engine,'engine':value});self.assertIs(self.app._scribe_engine,value)
    def test_permission_url_is_fixed_and_requires_explicit_action(self):
        with patch('knight_flow.web_shell.scribe_adapter.sys.platform','darwin'),patch('subprocess.Popen') as run:
            self.actions('current',None);run.assert_not_called();self.actions('permission',None)
            self.assertEqual(run.call_args.args[0],['open','x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'])
    def test_current_and_platform_do_not_activate_audio(self):
        self.assertIs(self.actions('current',None),self.engine);self.actions('platform',None);self.app.toggle_scribe.assert_not_called()
    def test_copy_passes_complete_literal_text(self):
        self.actions('copy','Literal <tag> 日本語 👩🏽‍💻');self.copy.assert_called_once_with('Literal <tag> 日本語 👩🏽‍💻')
