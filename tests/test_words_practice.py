import copy
import queue
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from knight_flow.pronunciation_practice import PronunciationPractice,capture_take,CaptureCloseFailure
from knight_flow.mic_registry import MicrophoneRegistry


class WordsPracticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.registry=MicrophoneRegistry()
        self.app=SimpleNamespace(config={'dictionary':{'words':['Mayowa'],'terms':[]},'audio':{'input_device':'Studio mic'}},
            lock=threading.RLock(),session=None,session_token=None,_cross_thread_calls=queue.Queue(),
            _local_clip_transcriber=Mock(return_value=lambda path:'my yo wa'))
        for name,value in [('knight_flow.pronunciation_practice.microphone_registry',self.registry),('knight_flow.pronunciation.clips_root',self.root)]:
            patcher=patch(name,return_value=value);patcher.start();self.addCleanup(patcher.stop)
        self.persist=Mock();self.status=Mock();self.workers=[]
        self.practice=PronunciationPractice(self.app,capture=Mock(return_value=b'RIFFtest'),persist=self.persist,launch=self.workers.append)
        self.practice.cancelled.wait=Mock(return_value=False)
    def drain(self):
        while not self.app._cross_thread_calls.empty():self.app._cross_thread_calls.get_nowait()()
    def run_worker(self):self.workers.pop(0)()
    def test_registers_before_worker_and_commits_only_on_ui_queue(self):
        self.practice.start('Mayowa',self.status)
        self.assertTrue(self.registry.is_active());self.assertTrue(self.practice.active)
        self.run_worker();self.persist.assert_not_called();self.assertFalse(self.registry.is_active())
        self.assertTrue(self.practice.active);self.drain()
        self.persist.assert_called_once();self.assertFalse(self.practice.active)
        self.assertEqual(self.app.config['dictionary']['words'],[])
        self.assertEqual(self.app.config['dictionary']['terms'][0]['sounds_like'],['my yo wa'])
        self.assertEqual(len(list(self.root.rglob('take-*.wav'))),3)
    def test_busy_app_and_other_microphone_are_refused(self):
        self.app.session_token=object()
        with self.assertRaises(ValueError):self.practice.start('Name',self.status)
        self.app.session_token=None;self.registry.acquire('mic-doctor')
        with self.assertRaises(ValueError):self.practice.start('Name',self.status)
        self.assertEqual(self.workers,[])
    def test_duplicate_start_cannot_reset_a_live_cancellation(self):
        self.practice.start('Mayowa',self.status);self.practice.cancel()
        with self.assertRaises(ValueError):self.practice.start('Other',self.status)
        self.assertTrue(self.practice.cancelled.is_set())
    def test_panic_cancels_and_keeps_owner_until_worker_finishes(self):
        self.practice.start('Mayowa',self.status);self.registry.stop_all()
        self.assertTrue(self.registry.is_active());self.assertTrue(self.practice.cancelled.is_set())
        self.run_worker();self.drain()
        self.assertFalse(self.registry.is_active());self.persist.assert_not_called()
        self.assertFalse(list(self.root.iterdir()));self.assertIn('cancelled',self.status.call_args.args[0])
    def test_cancel_after_capture_before_ui_commit_saves_nothing(self):
        self.practice.start('Mayowa',self.status);self.run_worker();self.practice.cancel();self.drain()
        self.persist.assert_not_called();self.assertEqual(self.app.config['dictionary']['words'],['Mayowa'])
    def test_external_vocabulary_change_during_training_is_kept(self):
        self.practice.start('Mayowa',self.status);self.run_worker();self.app.config['dictionary']['words'].append('External');self.drain()
        self.persist.assert_not_called();self.assertIn('External',self.app.config['dictionary']['words'])
        self.assertIn('changed',self.status.call_args.args[0])
    def test_disk_failure_keeps_original_word_and_no_training_files(self):
        before=copy.deepcopy(self.app.config);self.persist.side_effect=OSError('disk full')
        self.practice.start('Mayowa',self.status);self.run_worker();self.drain()
        self.assertEqual(self.app.config,before);self.assertFalse(list(self.root.iterdir()))
        self.assertIn('could not be saved',self.status.call_args.args[0])
    def test_capture_failure_is_reported_and_owner_released(self):
        self.practice.capture.side_effect=OSError('mic missing')
        self.practice.start('Mayowa',self.status);self.run_worker();self.drain()
        self.assertFalse(self.registry.is_active());self.assertFalse(self.practice.active);self.persist.assert_not_called()
        self.assertIn('could not finish',self.status.call_args.args[0])
    def test_manual_alias_is_retained_when_trained_alias_changes(self):
        self.app.config['dictionary']['terms']=[{'text':'Mayowa','sounds_like':['my other','old hearing'],'trained_aliases':['old hearing']}]
        self.practice.start('Mayowa',self.status);self.run_worker();self.drain()
        self.assertEqual(self.app.config['dictionary']['terms'][0]['sounds_like'],['my other','my yo wa'])
    def test_non_latin_training_keeps_the_heard_word(self):
        self.app._local_clip_transcriber.return_value=lambda _: '明和。'
        self.practice.start('美和',self.status);self.run_worker();self.drain()
        self.assertEqual(self.app.config['dictionary']['terms'][0]['sounds_like'],['明和'])
    def test_capture_uses_selected_device_and_closes_its_own_handle(self):
        stream=Mock();cancelled=threading.Event();cancelled.wait=Mock(return_value=False)
        def opened(**kwargs):
            self.assertEqual(kwargs['device'],7)
            stream.start.side_effect=lambda:kwargs['callback'](b'\x01\x00'*100,100,None,None)
            return stream,48000,1,7
        with patch('knight_flow.audio_input.resolve_input_device',return_value=7) as device,patch('knight_flow.audio_input.open_raw_input_stream',side_effect=opened):
            data=capture_take(self.app.config,cancelled)
        device.assert_called_once_with('Studio mic');self.assertTrue(data.startswith(b'RIFF'))
        stream.stop.assert_called_once();stream.close.assert_called_once()
    def test_cancel_during_capture_discards_audio(self):
        stream=Mock();cancelled=threading.Event()
        cancelled.wait=Mock(side_effect=lambda _:cancelled.set())
        with patch('knight_flow.audio_input.resolve_input_device',return_value=None),patch('knight_flow.audio_input.open_raw_input_stream',return_value=(stream,16000,1,None)):
            self.assertIsNone(capture_take(self.app.config,cancelled))
        stream.close.assert_called_once()
    def test_failed_microphone_close_keeps_registry_owner_visible(self):
        stream=Mock();self.practice.capture.side_effect=CaptureCloseFailure(stream)
        self.practice.start('Mayowa',self.status);self.run_worker();self.drain()
        self.assertTrue(self.registry.is_active());self.assertEqual(self.registry.owners()[0].phase,'stop-failed')
        self.assertIn('did not close',self.status.call_args.args[0]);self.persist.assert_not_called()

if __name__=='__main__':unittest.main()
