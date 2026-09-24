import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from knight_flow.feedback import submit_feedback,build_feedback_payload
from knight_flow.format_journal import journal_tail


class Response:
    def __init__(self,body):self.body=json.dumps(body).encode()
    def read(self,*args):return self.body
    def __enter__(self):return self
    def __exit__(self,*args):return False


class FeedbackIntegrityTests(unittest.TestCase):
    # The feedback inbox belongs to OFFICIAL builds (2026-09-23, open source);
    # a build from source falls back to email before any request is built.
    def setUp(self):
        from knight_flow import official_build
        patcher=patch.object(official_build,'OFFICIAL',True);patcher.start();self.addCleanup(patcher.stop)
    def test_a_string_false_is_not_a_delivery_receipt(self):
        with patch('urllib.request.urlopen',return_value=Response({'received':'false'})):
            self.assertFalse(submit_feedback({'text':'A synthetic idea.'}))
    def test_a_numeric_flag_is_not_a_delivery_receipt(self):
        with patch('urllib.request.urlopen',return_value=Response({'received':1})):
            self.assertFalse(submit_feedback({'text':'A synthetic idea.'}))
    def test_opening_an_email_draft_cannot_be_reported_as_sent(self):
        from knight_flow.app import TalkDatApp
        with patch('knight_flow.app.submit_feedback',return_value=False),patch('knight_flow.app.webbrowser.open',return_value=True) as opened:
            self.assertFalse(TalkDatApp.send_feedback(SimpleNamespace(),title='A synthetic idea'))
            opened.assert_not_called()
    def test_reports_beyond_the_servers_text_limit_are_not_silently_shortened(self):
        with patch('urllib.request.urlopen',return_value=Response({'received':True})) as opened:
            with self.assertRaisesRegex(ValueError,'2,000'):
                submit_feedback(build_feedback_payload(title='Synthetic title',details='a'*2200))
            opened.assert_not_called()
    def test_unicode_journal_tail_honors_its_byte_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'journal.jsonl'
            rows=[json.dumps({'n':i,'raw':'日本語'*400},ensure_ascii=False) for i in range(30)]
            path.write_text('\n'.join(rows)+'\n',encoding='utf-8')
            with patch('knight_flow.format_journal.journal_path',return_value=path):tail=journal_tail(max_bytes=48000)
        self.assertLessEqual(len(tail.encode('utf-8')),48000)
        self.assertEqual(json.loads(tail.splitlines()[-1])['n'],29)
    def test_unicode_attachment_stays_below_the_request_byte_limit(self):
        captured=[]
        def fake(request,**kwargs):captured.append(request.data);return Response({'received':True})
        payload=build_feedback_payload(title='Synthetic idea',logs='日本語'*16000)
        with patch('urllib.request.urlopen',side_effect=fake):submit_feedback(payload)
        self.assertTrue(captured)
        self.assertLessEqual(len(captured[0]),64*1024)

if __name__=='__main__':unittest.main()
