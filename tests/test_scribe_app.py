import queue,threading,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from knight_flow.app import TalkDatApp
from knight_flow.mic_registry import MicrophoneRegistry


class ScribeAppTests(unittest.TestCase):
    def setUp(self):
        self.app=TalkDatApp.__new__(TalkDatApp);self.app.config={'scribe':{'source':'microphone'}}
        self.app.lock=threading.RLock();self.app.session=None;self.app.session_token=None
        self.app._cross_thread_calls=queue.Queue();self.app._has_a_writing_model=lambda:True
        self.app.overlay=SimpleNamespace(set_state=Mock(),_ui_thread_id=threading.get_ident(),root=SimpleNamespace(after=Mock(side_effect=AssertionError('Do not call Tk from a worker'))))
        self.engine=SimpleNamespace(finished=threading.Event(),recorder=None,phase='recording',start=Mock(),finish=Mock(),cancel=Mock(),body='',saved_path=None)
        item=patch('knight_flow.scribe_engine.ScribeEngine',return_value=self.engine);self.factory=item.start();self.addCleanup(item.stop)
        item=patch('knight_flow.app.microphone_registry',return_value=MicrophoneRegistry());item.start();self.addCleanup(item.stop)
    def test_start_carries_snapshot_source_and_ui_dispatch_to_engine(self):
        self.app.toggle_scribe();self.engine.start.assert_called_once();self.assertIs(self.app._scribe_engine,self.engine)
        self.assertIs(self.factory.call_args.args[0],self.app.config)
    def test_second_click_finishes_current_capture_without_replacing_owner(self):
        self.app._scribe_engine=self.engine;self.app.toggle_scribe();self.engine.finish.assert_called_once();self.factory.assert_not_called()
    def test_click_during_transcription_pauses_processing(self):
        self.app._scribe_engine=self.engine;self.engine.phase='transcribing';self.app.toggle_scribe();self.engine.cancel.assert_called_once()
    def test_unsaved_draft_is_not_replaced_by_new_recording(self):
        self.app._scribe_engine=self.engine;self.engine.finished.set();self.engine.body='Keep my unsaved words'
        self.app.toggle_scribe();self.factory.assert_not_called();self.assertEqual(self.engine.body,'Keep my unsaved words')
    def test_dictation_overlap_is_refused(self):
        self.app.session_token=object();self.app.toggle_scribe();self.factory.assert_not_called()
    def test_cold_caption_preparation_overlap_is_refused(self):
        self.app._captions_engine=object();self.app.toggle_scribe();self.factory.assert_not_called()
    def test_previous_owner_cannot_repaint_new_recording(self):
        self.app._scribe_engine=object();self.app._on_scribe_state(self.engine,'ready','Old notes');self.app.overlay.set_state.assert_not_called()
    def test_completion_cannot_repaint_active_dictation(self):
        self.app._scribe_engine=self.engine;self.app.session_token=object();self.app._on_scribe_state(self.engine,'ready','Old notes');self.app.overlay.set_state.assert_not_called()
    def test_quitting_ignores_late_worker_state(self):
        self.app._scribe_engine=self.engine;self.app._quitting=True;self.app._on_scribe_state(self.engine,'ready','Old notes');self.app.overlay.set_state.assert_not_called()
    def test_stop_cancels_preparing_or_recording_engine(self):
        self.app._scribe_engine=self.engine;self.app.stop_scribe();self.engine.cancel.assert_called_once()
    def test_background_menu_call_enters_python_ui_queue_before_starting(self):
        worker=threading.Thread(target=self.app.toggle_scribe);worker.start();worker.join(1);self.factory.assert_not_called()
        self.app._cross_thread_calls.get_nowait()();self.engine.start.assert_called_once();self.app.overlay.root.after.assert_not_called()
    def test_quit_waits_for_owned_audio_close_before_destroying_ui(self):
        self.app._scribe_engine=self.engine;self.engine.recorder=SimpleNamespace(closed=threading.Event())
        self.app.overlay.root.after=Mock();self.app.quit()
        self.engine.cancel.assert_called_once();self.app.overlay.root.after.assert_called_once()
        self.assertEqual(self.app.overlay.root.after.call_args.args[0],100);self.assertTrue(self.app._quitting)
    def test_quit_timeout_keeps_app_available_for_a_close_retry(self):
        self.app._scribe_engine=self.engine;self.engine.recorder=SimpleNamespace(closed=threading.Event());self.app._meeting_quit_deadline=0
        self.app.overlay.root.after=Mock();self.app.quit();self.app.overlay.root.after.assert_not_called()
        self.assertFalse(self.app._quitting);self.assertIn('still closing',self.app.overlay.set_state.call_args.args[1])
    def test_panic_cancels_scribe_even_during_model_preparation(self):
        from knight_flow.mic_registry import MicrophoneRegistry
        self.app._scribe_engine=self.engine;self.engine.phase='preparing';self.app.cancel=Mock()
        self.app.stop_captions_stream=Mock();self.app.stop_microphone_check=Mock()
        with patch('knight_flow.app.microphone_registry',return_value=MicrophoneRegistry()):self.app.panic_stop()
        self.engine.cancel.assert_called_once()
    def test_microphone_check_refuses_unregistered_cold_scribe_preparation(self):
        self.app._scribe_engine=self.engine;self.engine.phase='preparing'
        with self.assertRaises(ValueError):self.app.start_microphone_check('mic')
