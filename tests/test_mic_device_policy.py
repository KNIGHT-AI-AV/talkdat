import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from knight_flow.audio_input import open_raw_input_stream


class DiagnosticDevicePolicyTests(unittest.TestCase):
    def test_diagnostics_can_refuse_a_different_device_without_losing_rate_fallback(self):
        attempts=[]
        def stream(**kw):
            attempts.append((kw['device'],kw['samplerate']))
            if kw['device']==7 and kw['samplerate']==48000:return 'selected'
            raise OSError('unsupported')
        fake=SimpleNamespace(query_devices=lambda *a,**kw:{'default_samplerate':48000},RawInputStream=stream)
        with patch.dict(sys.modules,{'sounddevice':fake}),patch.dict('os.environ',{'TALK_DAT_MIC_WAV':''}):
            result=open_raw_input_stream(samplerate=16000,channels=1,device=7,callback=lambda *a:None,allow_device_fallback=False)
        self.assertEqual(result,('selected',48000,1,7));self.assertEqual(attempts,[(7,16000),(7,48000)])
    def test_failed_selected_input_is_not_replaced_by_a_working_default(self):
        attempts=[]
        def stream(**kw):
            attempts.append(kw['device'])
            if kw['device']!=7:return 'wrong microphone'
            raise OSError('selected failed')
        fake=SimpleNamespace(query_devices=lambda *a,**kw:{'default_samplerate':48000},RawInputStream=stream)
        with patch.dict(sys.modules,{'sounddevice':fake}),patch.dict('os.environ',{'TALK_DAT_MIC_WAV':''}):
            with self.assertRaises(OSError):
                open_raw_input_stream(samplerate=16000,channels=1,device=7,callback=lambda *a:None,allow_device_fallback=False)
        self.assertTrue(attempts);self.assertEqual(set(attempts),{7})
    def test_default_diagnostic_input_never_silently_selects_another_named_input(self):
        attempts=[]
        def stream(**kw):attempts.append(kw['device']);raise OSError('default failed')
        fake=SimpleNamespace(query_devices=lambda *a,**kw:{'default_samplerate':48000},RawInputStream=stream)
        with patch.dict(sys.modules,{'sounddevice':fake}),patch.dict('os.environ',{'TALK_DAT_MIC_WAV':''}):
            with self.assertRaises(OSError):
                open_raw_input_stream(samplerate=16000,channels=1,callback=lambda *a:None,allow_device_fallback=False)
        self.assertTrue(attempts);self.assertEqual(set(attempts),{None})


if __name__=='__main__':unittest.main()
