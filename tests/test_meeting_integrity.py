import datetime as dt,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from knight_flow.meeting import MeetingRecorder
from knight_flow.scribe import ScribeRecorder,save_notes,heuristic_summary,chunk_wav_for_transcription


class MeetingIntegrityTests(unittest.TestCase):
    def test_meeting_started_in_same_minute_preserves_earlier_transcript(self):
        with tempfile.TemporaryDirectory() as folder,patch('knight_flow.meeting.meetings_dir',return_value=Path(folder)),patch('knight_flow.meeting.threading.Thread'):
            first=MeetingRecorder({},on_status=Mock(),on_line=Mock());first.start();first.path.write_text('Keep this earlier meeting.',encoding='utf-8')
            second=MeetingRecorder({},on_status=Mock(),on_line=Mock());second.start()
            self.assertNotEqual(first.path,second.path);self.assertEqual(first.path.read_text(encoding='utf-8'),'Keep this earlier meeting.')
    def test_scribe_same_minute_preserves_previous_notes(self):
        when=dt.datetime(2026,9,20,10,30)
        with tempfile.TemporaryDirectory() as folder,patch('knight_flow.scribe.notes_folder',return_value=Path(folder)):
            first=save_notes([('You','Earlier notes 日本語')],[],when)
            second=save_notes([('You','Later notes')],[],when)
            self.assertNotEqual(first,second);self.assertIn('Earlier notes 日本語',first.read_text(encoding='utf-8'))
    def test_distinct_action_sentences_with_same_prefix_are_retained(self):
        prefix='We agreed that the final invoice for the demonstration project would be '
        first=prefix+'$1,200.';second=prefix+'$2,400.'
        summary=heuristic_summary([('You',first),('Them',second)])
        self.assertEqual(summary,[first,second])
    def test_zero_summary_limit_has_no_points(self):
        self.assertEqual(heuristic_summary([('You','We agreed to ship on Friday.')],max_points=0),[])
    def test_system_audio_request_does_not_silently_open_microphone(self):
        fake=SimpleNamespace(WasapiSettings=Mock(side_effect=TypeError('unsupported loopback')),RawInputStream=Mock())
        recorder=MeetingRecorder({'meeting':{'source':'system'}},on_status=Mock(),on_line=Mock())
        with patch.dict(sys.modules,{'sounddevice':fake}),patch('knight_flow.system_audio.open_loopback_stream',side_effect=RuntimeError('system output unavailable')):
            with self.assertRaises(Exception):recorder._open_stream(Mock())
        fake.RawInputStream.assert_not_called()
    def test_scribe_closes_stream_even_when_driver_stop_raises(self):
        with tempfile.TemporaryDirectory() as folder,patch('tempfile.mkdtemp',return_value=folder):
            recorder=ScribeRecorder();stream=Mock();stream.stop.side_effect=OSError('driver stop failed');recorder.streams=[stream]
            recorder.stop();stream.close.assert_called_once()
    def test_scribe_failed_start_releases_its_stream_and_wav(self):
        with tempfile.TemporaryDirectory() as folder,patch('tempfile.mkdtemp',return_value=folder):
            recorder=ScribeRecorder();recorder.config={'scribe':{'source':'microphone'}};stream=Mock();stream.start.side_effect=OSError('driver start failed')
            fake=SimpleNamespace(RawInputStream=Mock(return_value=stream))
            with patch.dict(sys.modules,{'sounddevice':fake}):
                with self.assertRaises(OSError):recorder.start()
            try:
                stream.close.assert_called_once()
                self.assertTrue(all(getattr(handle,'_file',None) is None for handle in recorder.wavs.values()))
            finally:
                for handle in recorder.wavs.values():handle.close()
    def test_meeting_failed_write_keeps_unsaved_words_and_reports_failure(self):
        status=Mock();line=Mock();recorder=MeetingRecorder({},on_status=status,on_line=line)
        recorder._pending.extend(b'\0' * 32000);recorder.path=Mock();recorder.path.open.side_effect=OSError('disk full')
        with patch('knight_flow.meeting.transcribe_pcm',return_value='Keep all these words 日本語'):
            recorder._flush_chunk()
        self.assertTrue(status.called,'A failed save must be visible')
        self.assertIn('Keep all these words 日本語',str(getattr(recorder,'unsaved_lines',[])))
    def test_recorded_pcm_is_readable_on_the_shipped_python_runtime(self):
        import wave
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'take.wav';frames=b'\x00\x01'*16000
            with wave.open(str(path),'wb') as handle:
                handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(16000);handle.writeframes(frames)
            self.assertEqual(list(chunk_wav_for_transcription(path)),[(0,frames)])


if __name__=='__main__':unittest.main()
