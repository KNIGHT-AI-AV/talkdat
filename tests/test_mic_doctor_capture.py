"""Mic Doctor must test the selected input, own it, and stay off Tk workers."""
import queue
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from knight_flow.app import TalkDatApp
from knight_flow.mic_registry import MicrophoneRegistry, MIC_DOCTOR


class MicDoctorCaptureTests(unittest.TestCase):
    def setUp(self):
        self.ui=queue.Queue();self.registry=MicrophoneRegistry()
        self.started=threading.Event();self.release=threading.Event();self.closed=threading.Event()
        self.captures=[];self.reports=[];self.tk_threads=[]
        self.app=TalkDatApp.__new__(TalkDatApp)
        self.app.config={'audio':{'input_device':'7: Chosen microphone'}}
        self.app.lock=threading.RLock();self.app.session=None;self.app.session_token=None
        self.app._cross_thread_calls=self.ui;self.app.cancel=lambda:None
        self.app.overlay=SimpleNamespace(_ui_thread_id=threading.get_ident(),set_state=lambda *args, **kwargs:None,
            root=SimpleNamespace(after=lambda delay,fn:(self.tk_threads.append(threading.get_ident()),self.ui.put(fn))))
        def record(*args,**kw):
            self.captures.append(kw);self.started.set()
            return SimpleNamespace(tobytes=lambda:b'\x00\x01'*48000)
        def wait():self.release.wait(3);self.closed.set()
        test=self
        class Stream:
            def start(self):
                test.started.set()
                def feed():
                    test.release.wait(3)
                    test.audio_callback(b'\x00\x01'*48000,48000,None,None)
                threading.Thread(target=feed,daemon=True).start()
            def stop(self):test.closed.set()
            def close(self):test.closed.set()
            def __enter__(self):self.start();return self
            def __exit__(self,*args):self.stop();self.close()
        def open_stream(**kw):
            self.captures.append(kw)
            self.audio_callback=kw['callback']
            return Stream(),16000,1,7
        for target,value in (
            ('sounddevice.rec',record),('sounddevice.wait',wait),('sounddevice.stop',self.release.set),
            ('knight_flow.audio_input.resolve_input_device',lambda value:7),
            ('knight_flow.audio_input.open_raw_input_stream',open_stream),
            ('knight_flow.app.microphone_registry',lambda:self.registry),
            ('knight_flow.mic_registry.microphone_registry',lambda:self.registry)):
            item=patch(target,value);item.start();self.addCleanup(item.stop)
    def pump(self):
        while not self.ui.empty():self.ui.get_nowait()()
    def tearDown(self):
        self.release.set();self.closed.wait(1)
        end=time.monotonic()+.2
        while time.monotonic()<end:self.pump();time.sleep(.005)
    def start(self):
        self.app.run_mic_doctor(self.reports.append)
        self.assertTrue(self.started.wait(1))
    def test_check_uses_the_selected_microphone(self):
        self.start();self.assertEqual(self.captures[0].get('device'),7)
    def test_capture_is_registered_while_listening(self):
        self.start();self.assertIn(MIC_DOCTOR,self.registry.names())
    def test_panic_stops_the_sample_before_its_timer_finishes(self):
        self.start();self.app.panic_stop()
        self.assertTrue(self.closed.wait(.5))
    def test_capture_worker_uses_the_ui_queue_instead_of_calling_tk(self):
        self.start();self.release.set()
        end=time.monotonic()+1
        while not self.reports and time.monotonic()<end:self.pump();time.sleep(.005)
        self.assertTrue(self.reports);self.assertEqual(self.tk_threads,[])


if __name__=='__main__':unittest.main()
