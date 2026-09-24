import datetime,json,os,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import Mock,patch
from knight_flow.scribe_library import ScribeLibrary,save_review,RecoveredRecording


class ScribeLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.folder=self.root/'recording-one';self.folder.mkdir();self.library=ScribeLibrary(self.root)
        self.manifest={'version':1,'source':'microphone','closed':True,'offsets':{'you':.2},'errors':[]}
        self.write()
        with wave.open(str(self.folder/'you.wav'),'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\x00\x01'*16000)
    def write(self): (self.folder/'recording.json').write_text(json.dumps(self.manifest))
    def restore(self):return self.library.restore('recording-one',{'scribe':{'source':'both'}},dispatch=lambda f:None,on_state=Mock())
    def test_library_lists_real_originals_without_opening_capture(self):
        with patch('knight_flow.scribe_engine.ScribeRecorder',side_effect=AssertionError('No capture')):
            rows=self.library.catalog()['entries'];engine=self.restore()
        self.assertEqual(len(rows),1);self.assertFalse(rows[0]['draft']);self.assertTrue(engine.finished.is_set());self.assertTrue(engine.recorder.closed.is_set())
        self.assertEqual(engine.recorder.written_bytes['you'],32000);self.assertEqual(engine.config['scribe']['source'],'microphone')
    def test_unicode_edited_draft_survives_new_service(self):
        text='Edited 日本語 👩🏽‍💻\n'+('complete words '*8000)
        save_review(self.folder,text,datetime.datetime(2026,9,20,12,30),edited=True)
        engine=self.restore();self.assertEqual(engine.body,text);self.assertTrue(engine.review_edited);self.assertTrue(engine.draft_saved)
        self.assertEqual(engine.when.hour,12);self.assertTrue(self.library.catalog()['entries'][0]['draft'])
    def test_failed_atomic_draft_write_preserves_earlier_words(self):
        save_review(self.folder,'Original words',datetime.datetime.now())
        with patch('knight_flow.audio_spool.os.replace',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):save_review(self.folder,'Replacement',datetime.datetime.now())
        self.assertEqual(self.restore().body,'Original words')
    def test_interrupted_close_is_visible_without_reopening_devices(self):
        self.manifest['closed']=False;self.write();engine=self.restore()
        self.assertIn('without a complete close',engine.recorder.errors[0]);self.assertTrue(engine.snapshot()['audio_closed'])
    def test_path_traversal_and_foreign_recordings_are_refused(self):
        for value in ['../recording-one','recording-one/../recording-two','recording-missing',True,'C:\\notes']:
            with self.subTest(value=value),self.assertRaises(ValueError):self.library.folder(value)
    def test_corrupt_review_is_preserved_instead_of_replaced(self):
        path=self.folder/'review-v1.json';path.write_text('{broken')
        with self.assertRaises(ValueError):self.restore()
        self.assertEqual(path.read_text(),'{broken')
    def test_completed_transcript_is_recovered_without_recognition(self):
        value={'version':1,'parts':{'you:30':{'ok':True,'text':'Second decision'},'you:0':{'ok':True,'text':'First decision'},'you:60':{'ok':False,'text':''}}}
        (self.folder/'transcript-v1.json').write_text(json.dumps(value))
        engine=self.restore();self.assertIn('First decision',engine.body);self.assertIn('Second decision',engine.body)
        self.assertIn('Retry transcription',engine.body);self.assertFalse(engine.review_edited)
    def test_missing_saved_copy_does_not_claim_current_receipt(self):
        save_review(self.folder,'Keep me',datetime.datetime.now(),saved_path=self.root/'removed.md')
        self.assertIsNone(self.restore().saved_path)
    def test_existing_copy_receipt_survives_restart(self):
        path=self.root/'notes.md';path.write_text('Kept')
        save_review(self.folder,'Kept',datetime.datetime.now(),saved_path=path)
        self.assertEqual(self.restore().saved_path,path)
    def test_malformed_audio_is_marked_and_original_kept(self):
        (self.folder/'you.wav').write_bytes(b'x'*100)
        engine=self.restore();self.assertEqual(engine.recorder.tracks(),{});self.assertTrue(engine.recorder.errors)
        self.assertEqual((self.folder/'you.wav').read_bytes(),b'x'*100)
    def test_nonfinite_offsets_cannot_poison_transcript_times(self):
        self.manifest['offsets']={'you':float('inf')};self.write()
        self.assertEqual(self.restore().recorder.offsets['you'],0)
    def test_linked_review_is_refused(self):
        outside=self.root/'outside.json';outside.write_text('{"version":1,"body":"private"}')
        path=self.folder/'review-v1.json'
        try:path.symlink_to(outside)
        except OSError:self.skipTest('Host does not allow test symlinks')
        with self.assertRaises(ValueError):self.restore()
