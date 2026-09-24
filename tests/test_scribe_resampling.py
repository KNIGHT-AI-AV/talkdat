import tempfile,unittest,wave
from pathlib import Path
import numpy as np
from knight_flow.scribe import chunk_wav_for_transcription


class ScribeResamplingTests(unittest.TestCase):
    def fixture(self,rate,channels,seconds=2.25,width=2):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        path=Path(folder.name)/'original.wav'
        count=int(rate*seconds);values=np.full((count,channels),1200,dtype='<i2')
        with wave.open(str(path),'wb') as file:
            file.setnchannels(channels);file.setsampwidth(width);file.setframerate(rate)
            file.writeframes(values.tobytes() if width==2 else b'\0'*(count*channels*width))
        return path
    def test_rates_keep_duration_chunk_boundaries_and_final_partial_audio(self):
        for rate in (8000,16000,22050,44100,48000,96000):
            with self.subTest(rate=rate):
                chunks=list(chunk_wav_for_transcription(self.fixture(rate,2),chunk_seconds=1))
                self.assertEqual([start for start,_ in chunks],[0,1,2])
                self.assertEqual([len(raw) for _,raw in chunks],[32000,32000,8000])
                samples=np.frombuffer(b''.join(raw for _,raw in chunks),dtype='<i2')
                self.assertLessEqual(int(np.max(np.abs(samples[100:-100].astype(int)-1200))),1)
    def test_downmix_does_not_double_volume(self):
        chunks=list(chunk_wav_for_transcription(self.fixture(16000,8),chunk_seconds=1))
        self.assertTrue(np.all(np.frombuffer(b''.join(raw for _,raw in chunks),dtype='<i2')==1200))
    def test_antiphase_stereo_cancels_without_clipping(self):
        path=self.fixture(48000,2,1);samples=np.tile(np.array([30000,-30000],dtype='<i2'),(48000,1))
        with wave.open(str(path),'wb') as file:
            file.setnchannels(2);file.setsampwidth(2);file.setframerate(48000);file.writeframes(samples.tobytes())
        self.assertEqual(set(b''.join(raw for _,raw in chunk_wav_for_transcription(path))),{0})
    def test_unsupported_sample_width_is_refused(self):
        with self.assertRaises(ValueError):list(chunk_wav_for_transcription(self.fixture(16000,1,width=3)))
    def test_invalid_chunk_limits_are_refused(self):
        for limit in (0,-1,301,True,'30',1.5):
            with self.subTest(limit=limit),self.assertRaises(ValueError):list(chunk_wav_for_transcription(self.fixture(16000,1),chunk_seconds=limit))
    def test_empty_recording_returns_no_fake_chunk(self):
        self.assertEqual(list(chunk_wav_for_transcription(self.fixture(48000,2,0))),[])
