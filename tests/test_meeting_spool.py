import tempfile,unittest,wave
from pathlib import Path
from unittest.mock import Mock,patch
from knight_flow.meeting import MeetingRecorder


class MeetingSpoolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)
        self.status=Mock();self.line=Mock();self.recorder=MeetingRecorder({'meeting':{'source':'microphone','chunk_seconds':8}},on_status=self.status,on_line=self.line)
        self.recorder.path=self.folder/'notes.md';self.recorder.path.write_text('Earlier notes.\n',encoding='utf-8')
        self.audio=self.folder/'you.wav'
        with wave.open(str(self.audio),'wb') as file:
            file.setnchannels(1);file.setsampwidth(2);file.setframerate(16000);file.writeframes(b'\0\x01'*16000*17)
    def test_disk_backlog_reads_only_one_bounded_section(self):
        with patch('knight_flow.meeting.transcribe_pcm',return_value='First section') as transcribe:
            self.assertTrue(self.recorder._read_next(self.audio,final=False));self.assertEqual(len(transcribe.call_args.args[1]),256000)
        self.assertEqual(self.recorder._position,256000);self.assertEqual(self.recorder._pending,bytearray())
    def test_last_partial_second_is_not_discarded(self):
        with patch('knight_flow.meeting.transcribe_pcm',return_value='Kept') as transcribe:
            self.recorder._read_next(self.audio,final=False);self.recorder._read_next(self.audio,final=False)
            self.assertFalse(self.recorder._read_next(self.audio,final=False));self.assertTrue(self.recorder._read_next(self.audio,final=True))
            self.assertEqual(len(transcribe.call_args.args[1]),32000)
            self.assertFalse(self.recorder._read_next(self.audio,final=True))
    def test_failed_recognition_marks_gap_and_retains_original_file(self):
        with patch('knight_flow.meeting.transcribe_pcm',side_effect=OSError('failed')):self.recorder._read_next(self.audio,final=True)
        self.assertIn('Transcription unavailable',self.recorder.path.read_text(encoding='utf-8'));self.assertEqual(self.recorder.failed_chunks,[0.0]);self.assertTrue(self.audio.exists())
    def test_failed_save_stops_capture_and_keeps_words(self):
        capture=Mock();self.recorder._recorder=capture;self.recorder.path=Mock();self.recorder.path.open.side_effect=OSError('full')
        with patch('knight_flow.meeting.transcribe_pcm',return_value='Keep all these words 日本語'):self.recorder._read_next(self.audio,final=True)
        self.assertTrue(self.recorder._stop_event.is_set());capture.request_stop.assert_called();self.line.assert_not_called()
        self.assertIn('Keep all these words 日本語',self.recorder.unsaved_lines[0])
    def test_times_describe_audio_position_not_completion_wall_clock(self):
        self.recorder._position=16000*2*65
        self.recorder._pending.extend(b'\0'*32000)
        with patch('knight_flow.meeting.transcribe_pcm',return_value='A later section'):self.recorder._flush_chunk()
        self.assertIn('[01:05]',self.recorder.path.read_text(encoding='utf-8'))
    def test_invalid_limits_cannot_allocate_unbounded_chunk(self):
        for limit in (True,-1,1000000,'bad'):
            recorder=MeetingRecorder({'meeting':{'chunk_seconds':limit}},on_status=Mock(),on_line=Mock())
            self.assertEqual(recorder.chunk_seconds,25)
    def test_stop_signals_audio_close_without_waiting_for_transcription(self):
        capture=Mock();self.recorder._recorder=capture;self.recorder.stop()
        self.assertTrue(self.recorder._stop_event.is_set());capture.request_stop.assert_called_once()
    def test_local_only_privacy_overrides_a_saved_remote_provider(self):
        self.recorder.config={'privacy':{'local_only':True},'stt':{'provider':'deepgram','route_mode':'byok'}}
        with patch('knight_flow.meeting.transcribe_pcm',return_value='Kept locally') as transcribe:
            self.recorder._read_next(self.audio,final=True)
        self.assertEqual(transcribe.call_args.kwargs.get('provider_id'),'local')
