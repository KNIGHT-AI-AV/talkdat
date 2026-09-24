import sys,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from knight_flow.system_audio import WindowsLoopbackStream,open_loopback_stream


class SystemAudioTests(unittest.TestCase):
    def setUp(self):
        self.stream=Mock();self.manager=Mock();self.manager.open.return_value=self.stream
        self.manager.get_default_wasapi_loopback.return_value={'isLoopbackDevice':True,'defaultSampleRate':48000,'maxInputChannels':2,'name':'Fixture output [Loopback]','index':9}
        self.audio=SimpleNamespace(PyAudio=Mock(return_value=self.manager),paInt16=8,paContinue=0,paComplete=1,paAbort=2)
        self.patch=patch.dict(sys.modules,{'pyaudiowpatch':self.audio});self.patch.start();self.addCleanup(self.patch.stop)
    def test_default_loopback_format_is_preserved_without_starting(self):
        captured=[];stream=WindowsLoopbackStream(lambda *args:captured.append(args))
        self.assertEqual((stream.samplerate,stream.channels),(48000,2))
        self.assertEqual(self.manager.open.call_args.kwargs['input_device_index'],9)
        self.assertFalse(self.manager.open.call_args.kwargs['start']);self.stream.start_stream.assert_not_called()
        callback=self.manager.open.call_args.kwargs['stream_callback'];self.assertEqual(callback(b'\0'*16,4,{},0),(None,0));self.assertEqual(captured[0][0],b'\0'*16)
        stream.close();self.manager.terminate.assert_called_once()
    def test_non_loopback_device_is_refused(self):
        self.manager.get_default_wasapi_loopback.return_value['isLoopbackDevice']=False
        with self.assertRaises(RuntimeError):WindowsLoopbackStream(Mock())
        self.manager.open.assert_not_called();self.manager.terminate.assert_called_once()
    def test_failed_open_terminates_manager(self):
        self.manager.open.side_effect=OSError('device unavailable')
        with self.assertRaises(OSError):WindowsLoopbackStream(Mock())
        self.manager.terminate.assert_called_once()
    def test_failed_start_closes_stream(self):
        self.stream.start_stream.side_effect=OSError('start failed')
        stream=WindowsLoopbackStream(Mock())
        with self.assertRaises(OSError):stream.start()
        self.stream.close.assert_called_once();self.manager.terminate.assert_called_once()
    def test_stop_failure_does_not_skip_close(self):
        self.stream.stop_stream.side_effect=OSError('stop failed')
        with self.assertRaises(OSError):
            with WindowsLoopbackStream(Mock()):pass
        self.stream.close.assert_called_once();self.manager.terminate.assert_called_once()
    def test_close_is_idempotent(self):
        stream=WindowsLoopbackStream(Mock());stream.close();stream.close();self.stream.close.assert_called_once();self.manager.terminate.assert_called_once()
    def test_callback_failure_is_exposed_and_aborts(self):
        stream=WindowsLoopbackStream(Mock(side_effect=OSError('disk full')))
        callback=self.manager.open.call_args.kwargs['stream_callback'];self.assertEqual(callback(b'\0'*16,4,{},0),(None,2))
        self.assertTrue(stream.error)
        stream.close()
    def test_other_platform_never_opens_windows_device(self):
        with patch('knight_flow.system_audio.sys.platform','linux'):
            with self.assertRaises(RuntimeError):open_loopback_stream(Mock())
        self.audio.PyAudio.assert_not_called()


if __name__=='__main__':unittest.main()
