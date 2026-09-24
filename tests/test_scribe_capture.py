import queue,tempfile,threading,time,unittest,wave
from pathlib import Path
from unittest.mock import Mock,patch
from knight_flow.scribe import ScribeRecorder
from knight_flow.mic_registry import MicrophoneRegistry,MEETING


class ScribeCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.registry=MicrophoneRegistry();self.callbacks={};self.mic=Mock();self.loop=Mock(samplerate=48000,channels=2)
        patches=[patch('knight_flow.config.app_dir',return_value=Path(self.temp.name)),
                 patch('knight_flow.mic_registry.microphone_registry',return_value=self.registry),
                 patch('knight_flow.audio_input.resolve_input_device',return_value=7),
                 patch('knight_flow.audio_input.open_raw_input_stream',side_effect=self.open_mic),
                 patch('knight_flow.system_audio.open_loopback_stream',side_effect=self.open_loop)]
        for item in patches:item.start();self.addCleanup(item.stop)
        self.recorders=[];self.addCleanup(self.close_all)
    def close_all(self):
        for recorder in self.recorders:
            for stream in recorder.streams:stream.close.side_effect=None
            recorder.stop()
    def open_mic(self,**kwargs):
        self.callbacks['you']=kwargs['callback'];self.assertFalse(kwargs['allow_device_fallback']);self.assertEqual(kwargs['device'],7)
        return self.mic,16000,1,None
    def open_loop(self,callback):
        self.callbacks['them']=callback;return self.loop
    def make(self,source='both'):
        recorder=ScribeRecorder({'scribe':{'source':source},'audio':{'input_device':'Chosen microphone'}})
        self.recorders.append(recorder);return recorder
    def send(self,name,raw,status=0):self.callbacks[name](raw,len(raw)//(2 if name=='you' else 4),{},status)
    def test_records_only_explicit_microphone_and_flushes_accepted_audio(self):
        recorder=self.make('microphone');recorder.start();self.assertEqual(self.registry.names(),(MEETING,))
        self.assertNotIn('them',self.callbacks);self.send('you',b'\x00\x01'*800)
        tracks=recorder.stop();self.assertFalse(self.registry.is_active());self.assertEqual(set(tracks),{'you'})
        with wave.open(str(tracks['you']),'rb') as file:self.assertEqual(file.readframes(800),b'\x00\x01'*800)
    def test_system_only_never_opens_microphone(self):
        recorder=self.make('system');recorder.start();self.assertNotIn('you',self.callbacks)
        self.send('them',b'\x00\x01'*1600);tracks=recorder.stop()
        with wave.open(str(tracks['them']),'rb') as file:self.assertEqual((file.getframerate(),file.getnchannels()),(48000,2))
    def test_both_sources_are_opened_before_either_starts(self):
        self.mic.start.side_effect=lambda:self.assertIn('them',self.callbacks)
        recorder=self.make();recorder.start();self.loop.start.assert_called_once()
    def test_second_source_failure_closes_microphone_without_recording(self):
        recorder=self.make()
        with patch('knight_flow.system_audio.open_loopback_stream',side_effect=OSError('output unavailable')):
            with self.assertRaises(OSError):recorder.start()
        self.mic.start.assert_not_called();self.mic.close.assert_called_once();self.assertFalse(self.registry.is_active())
    def test_selected_missing_microphone_is_refused(self):
        recorder=self.make('microphone')
        with patch('knight_flow.audio_input.resolve_input_device',return_value=None),self.assertRaisesRegex(RuntimeError,'selected microphone'):recorder.start()
        self.assertFalse(self.callbacks);self.assertFalse(self.registry.is_active())
    def test_configuration_is_snapshotted(self):
        config={'scribe':{'source':'microphone'},'audio':{'input_device':'chosen'}}
        recorder=ScribeRecorder(config);self.recorders.append(recorder);config['scribe']['source']='system'
        recorder.start();self.assertEqual(set(self.callbacks),{'you'})
    def test_panic_retains_owner_until_driver_close_completes(self):
        recorder=self.make('microphone');recorder.start();entered=threading.Event();release=threading.Event()
        def close():entered.set();release.wait(3)
        self.mic.close.side_effect=close
        try:
            self.registry.stop_all();self.assertTrue(entered.wait(1));self.assertTrue(self.registry.is_active())
            self.assertEqual(self.registry.owners()[0].phase,'closing')
        finally:release.set()
        self.assertTrue(recorder.closed.wait(1));self.assertFalse(self.registry.is_active())
    def test_failed_close_stays_visible_and_panic_can_retry(self):
        recorder=self.make('microphone');recorder.start();self.mic.close.side_effect=OSError('close failed')
        with self.assertRaisesRegex(RuntimeError,'not closed'):recorder.stop()
        self.assertTrue(self.registry.is_active());self.assertEqual(self.registry.owners()[0].phase,'stop-failed')
        self.mic.close.side_effect=None;self.registry.stop_all();self.assertTrue(recorder.closed.wait(1));self.assertFalse(self.registry.is_active())
    def test_device_overflow_stops_with_visible_incomplete_recording(self):
        recorder=self.make('microphone');recorder.start();self.send('you',b'\0'*1600,status=2)
        self.assertTrue(recorder.closed.wait(1));self.assertTrue(any('interruption' in error for error in recorder.errors))
    def test_disk_failure_stops_without_audio_thread_waiting_for_close(self):
        recorder=self.make('microphone');recorder.start()
        with patch.object(recorder.wavs['you'],'writeframes',side_effect=OSError('disk full')):
            self.send('you',b'\0'*1600);self.assertTrue(recorder.closed.wait(1))
        self.assertTrue(any('saved completely' in error for error in recorder.errors));self.assertFalse(self.registry.is_active())
    def test_queue_is_bounded_and_overflow_is_visible(self):
        recorder=self.make('microphone');recorder.channels={'you':1};recorder.started_at=time.monotonic()
        for _ in range(recorder.QUEUE_BLOCKS+1):recorder._receiver('you')(b'\0'*1600,800,{},0)
        self.assertEqual(recorder._queue.qsize(),recorder.QUEUE_BLOCKS);self.assertTrue(recorder._stop_event.is_set())
        self.assertTrue(any('faster' in error for error in recorder.errors))
        while not recorder._queue.empty():recorder._queue.get_nowait()
    def test_invalid_source_never_opens_capture(self):
        recorder=self.make('unknown')
        with self.assertRaises(ValueError):recorder.start()
        self.assertFalse(self.callbacks);self.assertFalse(self.registry.is_active())
    def test_empty_recording_does_not_fabricate_a_track(self):
        recorder=self.make('microphone');recorder.start();self.assertEqual(recorder.stop(),{})
    def test_stopped_callback_cannot_append_new_audio(self):
        recorder=self.make('microphone');recorder.start();recorder.stop();self.send('you',b'\0'*1600)
        self.assertTrue(recorder._queue.empty());self.assertEqual(recorder.tracks(),{})
    def test_file_size_limit_stops_before_invalid_wav_length(self):
        recorder=self.make('microphone');recorder.start();recorder.MAX_TRACK_BYTES=100
        self.send('you',b'\0'*1600);self.assertTrue(recorder.closed.wait(1));self.assertEqual(recorder.tracks(),{})
        self.assertTrue(any('size limit' in error for error in recorder.errors))
