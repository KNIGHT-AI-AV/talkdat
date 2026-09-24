import queue
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from knight_flow.microphone_check import MicrophoneCheck
from knight_flow.mic_registry import MicrophoneRegistry, MIC_DOCTOR, RACE


class MicrophoneCheckTests(unittest.TestCase):
    def setUp(self):
        self.registry=MicrophoneRegistry();self.ui=queue.Queue();self.calls=[];self.done=[]
        self.started=threading.Event();self.allow_close=threading.Event();self.allow_close.set()
        self.closed=threading.Event();self.feed=None;self.fail_close=False;self.fail_start=False
        self.rate=16000;self.channels=1;self.actual=7;self.selection=7;self.flag=None
        self.prepare=lambda _:None;self.recognize=lambda *args:'A clear sentence.'
        self.config={'audio':{'input_device':'7: Selected mic'}}
        test=self
        class Stream:
            def start(self):
                test.started.set()
                if test.fail_start:raise OSError('start')
                if test.feed is not None:test.callback(test.feed,0,None,test.flag)
            def stop(self):test.allow_close.wait(2)
            def close(self):
                if test.fail_close:raise OSError('close')
                test.closed.set()
        self.stream=Stream()
        def open_stream(**kwargs):
            self.calls.append(kwargs);self.callback=kwargs['callback']
            return self.stream,self.rate,self.channels,self.actual
        self.patches=[patch('knight_flow.audio_input.resolve_input_device',lambda _:self.selection),
                      patch('knight_flow.audio_input.open_raw_input_stream',open_stream)]
        for item in self.patches:item.start();self.addCleanup(item.stop)
        self.check=None
    def tearDown(self):
        self.allow_close.set();self.fail_close=False
        if self.check:self.check.stop();self.check.finished.wait(1)
    def begin(self,mode='mic'):
        self.check=MicrophoneCheck(self.config,registry=self.registry,dispatch=self.ui.put,mode=mode,
            on_done=self.done.append,prepare=self.prepare,recognize=self.recognize)
        self.check.start();return self.check
    def finish(self):
        self.assertTrue(self.check.finished.wait(2),self.check.snapshot())
        while not self.ui.empty():self.ui.get_nowait()()
        return self.check.snapshot()
    def test_selected_input_is_explicit_and_device_fallback_is_disabled(self):
        self.begin();self.assertTrue(self.started.wait(1))
        self.assertEqual(self.calls[0]['device'],7)
        self.assertIs(self.calls[0]['allow_device_fallback'],False)
        self.assertIn(MIC_DOCTOR,self.registry.names())
    def test_panic_stops_capture_without_waiting_three_seconds(self):
        self.begin();self.assertTrue(self.started.wait(1));before=time.monotonic()
        self.registry.stop_all();state=self.finish()
        self.assertLess(time.monotonic()-before,.5);self.assertEqual(state['phase'],'cancelled')
        self.assertFalse(self.registry.is_active());self.assertTrue(self.closed.is_set());self.assertEqual(self.done,[])
    def test_registry_remains_until_worker_finishes_closing(self):
        self.allow_close.clear();self.begin();self.assertTrue(self.started.wait(1))
        self.registry.stop_all();time.sleep(.05)
        self.assertIn(MIC_DOCTOR,self.registry.names());self.assertFalse(self.check.finished.is_set())
        self.assertEqual(self.registry.owners()[0].phase,'closing')
        self.allow_close.set();self.finish();self.assertFalse(self.registry.is_active())
    def test_close_failure_remains_owned_until_panic_retry_succeeds(self):
        self.fail_close=True;self.begin();self.assertTrue(self.started.wait(1));self.check.stop()
        self.assertTrue(self.check.capture_done.wait(1));self.assertFalse(self.check.finished.is_set())
        self.assertEqual(self.registry.owners()[0].phase,'stop-failed')
        self.fail_close=False;self.registry.stop_all();self.finish()
        self.assertFalse(self.registry.is_active())
    def test_start_failure_closes_handle_and_delivers_error_through_queue(self):
        self.fail_start=True;self.begin();state=self.finish()
        self.assertEqual(state['phase'],'error');self.assertTrue(self.closed.is_set())
        self.assertFalse(self.registry.is_active());self.assertEqual(len(self.done),1)
    def test_missing_selection_never_opens_a_different_microphone(self):
        self.selection=None;self.begin();state=self.finish()
        self.assertEqual(self.calls,[]);self.assertIn('unavailable',state['message'])
    def test_unexpected_fallback_handle_is_closed_before_failure(self):
        self.actual=9;self.begin();state=self.finish()
        self.assertFalse(self.started.is_set());self.assertTrue(self.closed.is_set())
        self.assertEqual(state['phase'],'error')
    def test_callbacks_only_deliver_after_ui_queue_is_drained(self):
        self.feed=b'\x01\x00'*48000;self.begin()
        self.assertTrue(self.check.finished.wait(1));self.assertEqual(self.done,[])
        self.finish();self.assertEqual(len(self.done),1)
    def test_stop_before_queued_result_prevents_delivery(self):
        self.feed=b'\x01\x00'*48000;self.begin();self.assertTrue(self.check.finished.wait(1))
        self.check.stop();self.finish();self.assertEqual(self.done,[])
    def test_actual_format_and_exact_duration_are_passed_to_local_recognition(self):
        self.rate=48000;self.channels=2;self.feed=b'\x01\x00'*(48000*2*10)
        received=[]
        def recognize(config,pcm,rate,channels):
            self.assertFalse(self.registry.is_active());self.assertTrue(self.closed.is_set())
            received.append((len(pcm),rate,channels));return 'Hello.'
        self.recognize=recognize;self.begin('speech');state=self.finish()
        self.assertEqual(received,[(8*48000*2*2,48000,2)])
        self.assertEqual(state['text'],'Hello.');self.assertIsNotNone(state['recognition_ms'])
    def test_stereo_levels_keep_one_hundred_millisecond_windows(self):
        self.rate=48000;self.channels=2;self.feed=b'\x01\x00'*(3*48000*2)
        from knight_flow.mic_doctor import analyze_sample
        with patch('knight_flow.mic_doctor.analyze_sample',wraps=analyze_sample) as analyze:
            self.begin();self.finish()
        self.assertEqual(analyze.call_args.kwargs['sample_rate'],96000)
    def test_input_overflow_fails_without_presenting_a_healthy_result(self):
        self.feed=b'\x01\x00'*48000;self.flag=SimpleNamespace(input_overflow=True)
        self.begin();state=self.finish()
        self.assertEqual(state['phase'],'error');self.assertIsNone(state['report'])
        self.assertIn('interrupted',state['message'])
    def test_cancelling_recognition_discards_late_result_and_waits_for_worker(self):
        entered=threading.Event();release=threading.Event();self.feed=b'\x01\x00'*(16000*8)
        def recognize(*args):entered.set();release.wait(2);return 'Late text'
        self.recognize=recognize;self.begin('speech');self.assertTrue(entered.wait(1));self.check.stop()
        self.assertFalse(self.check.finished.is_set());self.assertFalse(self.registry.is_active())
        release.set();state=self.finish();self.assertEqual(state['text'],'');self.assertEqual(state['phase'],'cancelled')
    def test_cancel_during_preparation_never_opens_microphone(self):
        entered=threading.Event();release=threading.Event()
        def prepare(_):entered.set();release.wait(2)
        self.prepare=prepare;self.begin('speech');self.assertTrue(entered.wait(1));self.registry.stop_all();release.set()
        self.finish();self.assertEqual(self.calls,[]);self.assertFalse(self.registry.is_active())
    def test_missing_model_fails_before_capture(self):
        def prepare(_):raise ValueError('Download a local speech model first.')
        self.prepare=prepare;self.begin('speech');state=self.finish()
        self.assertEqual(self.calls,[]);self.assertIn('Download',state['message'])
    def test_config_is_copied_before_the_worker_runs(self):
        received=[];self.feed=b'\x01\x00'*(16000*8)
        check=MicrophoneCheck(self.config,registry=self.registry,dispatch=self.ui.put,mode='speech',
            prepare=lambda config:received.append(config['audio']['input_device']),recognize=self.recognize)
        self.config['audio']['input_device']='9: Changed';self.check=check;check.start();self.finish()
        self.assertEqual(received,['7: Selected mic'])
    def test_thread_launch_failure_releases_the_registered_owner(self):
        with patch('knight_flow.microphone_check.threading.Thread.start',side_effect=RuntimeError('thread')):
            with self.assertRaises(RuntimeError):self.begin()
        self.assertFalse(self.registry.is_active());self.assertTrue(self.check.finished.is_set())


if __name__=='__main__':unittest.main()
