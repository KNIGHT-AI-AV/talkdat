import queue,tempfile,threading,time,unittest,wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from knight_flow.scribe_engine import ScribeEngine


class ScribeEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)
        self.ui=queue.Queue();self.states=[];self.preparing=threading.Event();self.release_prepare=threading.Event();self.release_prepare.set()
        self.recording=threading.Event();self.closed=threading.Event();self.summary_started=threading.Event();self.release_summary=threading.Event();self.release_summary.set()
        self.path=self.folder/'you.wav'
        with wave.open(str(self.path),'wb') as file:
            file.setnchannels(1);file.setsampwidth(2);file.setframerate(16000);file.writeframes(b'\0\x01'*16000)
        test=self
        class Recorder:
            def __init__(self,config):self.folder=test.folder;self.closed=test.closed;self.errors=[];self.offsets={}
            def start(self):test.recording.set()
            def request_stop(self):test.closed.set()
            def stop(self):test.closed.set();return self.tracks()
            def tracks(self):return {'you':test.path}
        def prepare(config):self.preparing.set();self.release_prepare.wait(3)
        def summarize(config,text):self.summary_started.set();self.release_summary.wait(3);return 'We will ship on Friday.'
        self.prepare=Mock(side_effect=prepare);self.recognize=Mock(return_value='We agreed to ship on Friday.');self.summarize=Mock(side_effect=summarize)
        for target,value in [('ScribeRecorder',Recorder),('prepare',self.prepare),('recognize',self.recognize),('summarize',self.summarize),('notes_folder',lambda:self.folder),('ScribeEngine._identity',lambda self:'fixture:en')]:
            item=patch('knight_flow.scribe_engine.'+target,value);item.start();self.addCleanup(item.stop)
        self.engine=ScribeEngine({'scribe':{'source':'microphone'}},dispatch=self.ui.put,on_state=lambda *args:self.states.append(args))
        self.addCleanup(self.finish)
    def finish(self):
        self.release_prepare.set();self.release_summary.set();self.engine.cancel()
        if self.engine._thread:self.engine._thread.join(2)
    def complete(self):
        self.engine.start();self.assertTrue(self.recording.wait(1));self.engine.finish();self.assertTrue(self.engine.finished.wait(2))
    def test_finish_saves_real_words_and_exposes_both_receipts(self):
        self.complete();state=self.engine.snapshot();self.assertEqual(state['phase'],'ready');self.assertTrue(state['audio_closed'])
        self.assertIn('ship on Friday',Path(state['saved_path']).read_text(encoding='utf-8'));self.assertEqual(state['recording_folder'],str(self.folder))
    def test_cancel_during_preparation_never_opens_audio(self):
        self.release_prepare.clear();self.engine.start();self.assertTrue(self.preparing.wait(1));self.engine.cancel();self.release_prepare.set()
        self.assertTrue(self.engine.finished.wait(1));self.assertFalse(self.recording.is_set());self.assertEqual(self.engine.phase,'paused')
    def test_cancel_recording_keeps_originals_without_transcription_or_summary(self):
        self.engine.start();self.assertTrue(self.recording.wait(1));self.engine.cancel();self.assertTrue(self.engine.finished.wait(1))
        self.recognize.assert_not_called();self.summarize.assert_not_called();self.assertTrue(self.path.exists());self.assertEqual(self.engine.phase,'paused')
    def test_empty_recognition_is_not_saved_as_success(self):
        self.recognize.return_value='';self.complete();self.assertEqual(self.engine.phase,'empty');self.assertIsNone(self.engine.saved_path)
    def test_save_failure_keeps_full_draft_and_retry_does_not_retranscribe(self):
        with patch('knight_flow.scribe_engine.save_new_export',side_effect=OSError('disk full')):self.complete()
        self.assertEqual(self.engine.phase,'save-failed');self.assertIn('ship on Friday',self.engine.body)
        calls=self.recognize.call_count;self.engine.retry();self.assertTrue(self.engine.finished.wait(1));self.assertEqual(self.engine.phase,'ready');self.assertEqual(self.recognize.call_count,calls)
    def test_failed_recognition_saves_visible_gap(self):
        self.recognize.side_effect=OSError('engine failed');self.complete();self.assertEqual(self.engine.phase,'review')
        self.assertIn('Transcription unavailable',self.engine.body);self.summarize.assert_not_called()
    def test_late_ui_receipts_do_not_replay_old_recording_status(self):
        self.complete()
        while not self.ui.empty():self.ui.get_nowait()()
        self.assertEqual([phase for _,phase,_ in self.states],['ready'])
    def test_preparation_failure_never_opens_audio(self):
        self.prepare.side_effect=OSError('model missing');self.engine.start();self.assertTrue(self.engine.finished.wait(1));self.assertFalse(self.recording.is_set());self.assertEqual(self.engine.phase,'error')
    def test_state_reads_do_not_wait_for_writing_model(self):
        self.release_summary.clear();self.engine.start();self.assertTrue(self.recording.wait(1));self.engine.finish();self.assertTrue(self.summary_started.wait(1))
        read=threading.Event();threading.Thread(target=lambda:(self.engine.snapshot(),read.set()),daemon=True).start()
        self.assertTrue(read.wait(.2),'The UI state read blocked on the writing model')
    def test_original_config_changes_do_not_redirect_processing(self):
        config={'scribe':{'source':'microphone'}};engine=ScribeEngine(config,dispatch=self.ui.put,on_state=Mock());config['scribe']['source']='system'
        self.assertEqual(engine.config['scribe']['source'],'microphone')
    def test_retry_is_refused_while_recording(self):
        self.engine.start();self.assertTrue(self.recording.wait(1))
        with self.assertRaises(ValueError):self.engine.retry()
