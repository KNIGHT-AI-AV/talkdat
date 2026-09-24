import copy,queue,threading,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from knight_flow.app import TalkDatApp
from knight_flow.mic_registry import MicrophoneRegistry


class MicrophoneAppOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.app=TalkDatApp.__new__(TalkDatApp)
        self.app.config={'audio':{'input_device':'7: Studio'},'dictionary':{'words':['retain']}}
        self.app.lock=threading.RLock();self.app.session=None;self.app.session_token=None
        self.app._cross_thread_calls=queue.Queue();self.registry=MicrophoneRegistry()
        self.item=patch('knight_flow.app.microphone_registry',return_value=self.registry);self.item.start();self.addCleanup(self.item.stop)
    def test_pending_dictation_token_blocks_a_microphone_test(self):
        self.app.session_token=1
        with self.assertRaisesRegex(ValueError,'current recording'):self.app.start_microphone_check('mic')
    def test_another_registered_input_blocks_a_microphone_test(self):
        self.registry.acquire('other',stop=lambda:None)
        with self.assertRaises(ValueError):self.app.start_microphone_check('mic')
    def test_retiring_check_worker_blocks_the_next_check(self):
        self.app._microphone_check=SimpleNamespace(finished=threading.Event())
        with self.assertRaises(ValueError):self.app.start_microphone_check('speech')
    def test_preparing_caption_model_blocks_a_diagnostic_check(self):
        self.app._captions_engine=SimpleNamespace(finished=threading.Event())
        with patch('knight_flow.microphone_check.MicrophoneCheck'):
            with self.assertRaises(ValueError):self.app.start_microphone_check('speech')
    def test_pronunciation_processing_blocks_a_diagnostic_check(self):
        self.app._pronunciation_practice=SimpleNamespace(active=True)
        with patch('knight_flow.microphone_check.MicrophoneCheck'):
            with self.assertRaises(ValueError):self.app.start_microphone_check('speech')
    def test_panic_cancels_a_check_after_its_microphone_has_closed(self):
        self.app.cancel=Mock()
        self.app.overlay=SimpleNamespace(_ui_thread_id=threading.get_ident(),set_state=Mock())
        check=SimpleNamespace(stop=Mock(),finished=threading.Event())
        self.app._microphone_check=check
        self.app.panic_stop()
        check.stop.assert_called_once()
    def test_captions_cannot_start_while_a_diagnostic_worker_retires(self):
        self.app.overlay=SimpleNamespace(captions_stream_state=Mock())
        self.app._microphone_check=SimpleNamespace(finished=threading.Event())
        self.assertIs(self.app.start_captions_stream(),False)
        self.app.overlay.captions_stream_state.assert_called_once()
    def test_late_result_from_a_replaced_check_cannot_deliver(self):
        made=[];delivered=[]
        def factory(config,**kw):
            check=SimpleNamespace(start=lambda:None,finished=threading.Event());check.finished.set()
            made.append((check,kw['on_done']));return check
        with patch('knight_flow.microphone_check.MicrophoneCheck',side_effect=factory):
            self.app.start_microphone_check('mic',delivered.append)
            self.app.start_microphone_check('mic',delivered.append)
        made[0][1]({'phase':'ready'});self.assertEqual(delivered,[])
        made[1][1]({'phase':'ready'});self.assertEqual(delivered,[{'phase':'ready'}])
    def test_failed_input_save_preserves_the_entire_config(self):
        before=copy.deepcopy(self.app.config)
        with patch('knight_flow.config.save_config',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.app.set_microphone_input('9: New')
        self.assertEqual(self.app.config,before)
    def test_input_save_keeps_the_config_object_and_unrelated_fields(self):
        original=self.app.config
        with patch('knight_flow.config.save_config') as saved:self.app.set_microphone_input('9: New')
        self.assertIs(self.app.config,original);self.assertEqual(self.app.config['dictionary']['words'],['retain'])
        self.assertEqual(saved.call_args.args[0]['audio']['input_device'],'9: New')
    def test_input_cannot_change_before_the_previous_driver_closes(self):
        self.app._microphone_check=SimpleNamespace(finished=threading.Event())
        with patch('knight_flow.config.save_config') as saved:
            with self.assertRaises(ValueError):self.app.set_microphone_input('9: New')
        saved.assert_not_called()


if __name__=='__main__':unittest.main()
