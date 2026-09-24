from unittest.mock import patch
import unittest
from tests import test_scribe_engine as baseline


class ScribeReviewTests(unittest.TestCase):
    setUp=baseline.ScribeEngineTests.setUp
    finish=baseline.ScribeEngineTests.finish
    complete=baseline.ScribeEngineTests.complete
    def test_empty_body_contains_no_generated_meeting_notes(self):
        self.recognize.return_value='';self.complete();self.assertEqual(self.engine.body,'')
    def test_empty_sections_really_retry_instead_of_reusing_empty_receipt(self):
        self.recognize.return_value='';self.complete();self.recognize.return_value='Recovered words'
        self.engine.retry();self.assertTrue(self.engine.finished.wait(2))
        self.assertEqual(self.recognize.call_count,2);self.assertIn('Recovered words',self.engine.body)
    def test_retry_adopts_current_model_but_keeps_recorded_source(self):
        self.complete();before=self.engine.body
        config={'scribe':{'source':'system'},'stt':{'providers':{'local':{'model':'new-model','language':'fr'}}},'privacy':{'local_only':True}}
        self.engine.retry(config=config);self.assertTrue(self.engine.finished.wait(2))
        self.assertEqual(self.prepare.call_args.args[0]['stt'],config['stt'])
        self.assertEqual(self.engine.config['scribe']['source'],'microphone')
        self.assertEqual((self.folder/'Earlier notes.md').read_text(encoding='utf-8'),before)
    def test_failed_archive_never_overwrites_previous_draft(self):
        self.complete();before=self.engine.body;calls=self.recognize.call_count
        with patch('knight_flow.scribe_engine.save_new_export',side_effect=OSError('disk full')):
            self.engine.retry();self.assertTrue(self.engine.finished.wait(2))
        self.assertEqual(self.engine.body,before);self.assertEqual(self.recognize.call_count,calls)
    def test_export_failure_leaves_durable_recovery_draft(self):
        import json
        with patch('knight_flow.scribe_engine.save_new_export',side_effect=OSError('disk full')):self.complete()
        saved=json.loads((self.folder/'review-v1.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['body'],self.engine.body);self.assertTrue(self.engine.draft_saved)
