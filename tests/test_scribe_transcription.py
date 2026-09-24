import datetime as dt,json,tempfile,threading,unittest,wave
from pathlib import Path
from unittest.mock import Mock,patch
from knight_flow.scribe import Chunk
from knight_flow.scribe_transcription import TranscriptResult,notes_body,transcribe_tracks


class ScribeTranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)
        self.track=self.folder/'you.wav'
        with wave.open(str(self.track),'wb') as file:
            file.setnchannels(1);file.setsampwidth(2);file.setframerate(16000);file.writeframes(b'\0\x01'*16000*31)
    def run_transcript(self,recognize,**kwargs):
        return transcribe_tracks({'you':self.track},recognize,folder=self.folder,identity='local-model:auto',**kwargs)
    def test_failed_section_is_marked_and_only_that_section_retries(self):
        recognize=Mock(side_effect=['Keep the agreed price of $1,200.',OSError('engine failed')])
        first=self.run_transcript(recognize);self.assertEqual(first.completed,1);self.assertEqual(len(first.issues),1)
        self.assertIn('unavailable',first.turns[0][1]);self.assertEqual(len(first.gaps),1)
        retry=Mock(return_value='We will send the invoice tomorrow 日本語.');second=self.run_transcript(retry)
        retry.assert_called_once();self.assertEqual((second.reused,second.completed),(1,2));self.assertFalse(second.issues)
        self.assertIn('$1,200',second.turns[0][1]);self.assertIn('日本語',second.turns[0][1])
    def test_changed_audio_does_not_reuse_old_words(self):
        self.run_transcript(Mock(return_value='Earlier words'))
        with self.track.open('r+b') as file:file.seek(44);file.write(b'\0\x02'*16000)
        recognize=Mock(return_value='New words');result=self.run_transcript(recognize)
        self.assertEqual(recognize.call_count,1);self.assertEqual(result.reused,1)
    def test_changed_model_or_language_retranscribes_audio(self):
        self.run_transcript(Mock(return_value='Earlier words'))
        recognize=Mock(return_value='New words')
        result=transcribe_tracks({'you':self.track},recognize,folder=self.folder,identity='different-model:fr')
        self.assertEqual(recognize.call_count,2);self.assertEqual(result.reused,0)
    def test_cancel_preserves_completed_checkpoint(self):
        cancelled=threading.Event();result=self.run_transcript(Mock(return_value='Keep these words'),cancelled=cancelled,progress=lambda _:cancelled.set())
        self.assertEqual(result.completed,1);self.assertIn('paused',result.issues[0]);self.assertTrue((self.folder/'transcript-v1.json').exists())
        retry=Mock(return_value='Second section');self.run_transcript(retry);retry.assert_called_once()
    def test_progress_save_failure_keeps_recognized_words_in_result(self):
        with patch('knight_flow.scribe_transcription._save_ledger',side_effect=OSError('disk full')):
            result=self.run_transcript(Mock(return_value='Keep me even when the disk is full.'))
        self.assertIn('Keep me',result.turns[0][1]);self.assertIn('could not be saved',result.issues[0])
    def test_corrupt_progress_is_not_overwritten(self):
        path=self.folder/'transcript-v1.json';path.write_text('{broken',encoding='utf-8');recognize=Mock()
        with self.assertRaisesRegex(ValueError,'could not be read'):self.run_transcript(recognize)
        recognize.assert_not_called();self.assertEqual(path.read_text(encoding='utf-8'),'{broken')
    def test_false_receipt_is_retried(self):
        self.run_transcript(Mock(return_value='Earlier words'));path=self.folder/'transcript-v1.json';data=json.loads(path.read_text(encoding='utf-8'))
        for item in data['parts'].values():item['ok']='true'
        path.write_text(json.dumps(data),encoding='utf-8');recognize=Mock(return_value='Verified words');result=self.run_transcript(recognize)
        self.assertEqual(recognize.call_count,2);self.assertEqual(result.reused,0)
    def test_corrupt_audio_has_visible_warning(self):
        self.track.write_bytes(b'bad');result=self.run_transcript(Mock());self.assertIn('could not be read',result.issues[0])
    def test_empty_recognition_has_no_fabricated_words(self):
        result=self.run_transcript(Mock(return_value=''));self.assertEqual(result.turns,[]);self.assertEqual(result.completed,2)
    def test_track_offsets_and_source_labels_are_retained(self):
        result=self.run_transcript(Mock(return_value='Words'),offsets={'you':1.25});self.assertEqual(result.chunks[1].start,31.25);self.assertEqual(result.chunks[0].speaker,'Microphone')
    def test_large_summary_keeps_full_transcript_and_never_sends_truncated_text(self):
        text='Keep the exact amount and deadline. '*1300;result=TranscriptResult(chunks=[Chunk('Microphone',0,text)])
        summarize=Mock();body=notes_body(result,dt.datetime(2026,9,20),summarize=summarize)
        summarize.assert_not_called();self.assertIn(text.strip(),body);self.assertIn('exceeds the summary input limit',body);self.assertIn('## Selected lines',body)
    def test_gaps_do_not_delete_valid_sentences_from_selected_lines(self):
        result=TranscriptResult(chunks=[Chunk('Microphone',0,'[Transcription unavailable]'),Chunk('Microphone',30,'We agreed to send the invoice tomorrow.')],issues=['Missing section'],gaps={('Microphone',0)})
        summarize=Mock();body=notes_body(result,dt.datetime(2026,9,20),summarize=summarize)
        summarize.assert_not_called();self.assertIn('- We agreed to send the invoice tomorrow.',body);self.assertIn('## Review needed',body)
    def test_summary_failure_is_disclosed_and_original_text_remains(self):
        result=TranscriptResult(chunks=[Chunk('Microphone',0,'We agreed the exact amount is $1,200.')])
        body=notes_body(result,dt.datetime(2026,9,20),summarize=Mock(side_effect=OSError('unavailable')))
        self.assertIn('did not return a summary',body);self.assertIn('$1,200',body);self.assertNotIn('## AI summary',body)
    def test_summary_receipt_has_honest_label_and_source_timing_disclosure(self):
        result=TranscriptResult(chunks=[Chunk('Microphone',0,'We agreed the deadline is Friday.')])
        body=notes_body(result,dt.datetime(2026,9,20),summarize=lambda text:'The deadline is Friday.')
        self.assertIn('## AI summary',body);self.assertIn('not identified speakers',body);self.assertIn('approximate 30-second blocks',body)
