from pathlib import Path
from types import SimpleNamespace
import tempfile,time,unittest
from unittest.mock import patch
from knight_flow.history import export_history,history_stats


class HistoryExportIntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.folder=Path(temporary.name);self.rows=[]
        self.store=SimpleNamespace(recent=lambda limit:self.rows[-limit:])
        for item in [patch('knight_flow.history.app_dir',return_value=self.folder),patch('knight_flow.history.create_history_store',return_value=self.store)]:
            item.start();self.addCleanup(item.stop)
    def test_two_saves_in_one_second_preserve_both_documents(self):
        original=time.strftime
        def stamp(format,*args):return '20260920-021500' if format=='%Y%m%d-%H%M%S' else original(format,*args)
        with patch('knight_flow.history.time.strftime',side_effect=stamp):
            self.rows=[{'text':'First original','created_at':None}]
            first=export_history({},'txt');saved=first.read_bytes()
            self.rows=[{'text':'Second original','created_at':None}]
            second=export_history({},'txt')
        self.assertNotEqual(first,second)
        self.assertEqual(first.read_bytes(),saved)
        self.assertIn('Second original',second.read_text(encoding='utf-8'))
    def test_bad_timestamps_do_not_prevent_text_and_markdown_exports(self):
        self.rows=[{'text':f'Keep entry{index} 日本語 👩🏽‍💻','created_at':date} for index,date in enumerate([float('nan'),float('inf'),1e300,True,None,'invalid'])]
        for format in ['txt','md']:
            with self.subTest(format=format):
                text=export_history({},format).read_text(encoding='utf-8')
                for row in self.rows:self.assertIn(row['text'],text)
    def test_capped_stats_keep_the_newest_entry_and_discard_the_oldest(self):
        self.rows=[{'text':'oldest excluded','created_at':None}]+[{'text':'middle','created_at':None}]*19999+[{'text':'newest four saved words','created_at':None}]
        stats=history_stats({})
        self.assertTrue(stats['capped']);self.assertEqual(stats['words'],19999+4)
    def test_failed_publish_does_not_leave_a_partial_history_document(self):
        self.rows=[{'text':'Do not damage previous exports','created_at':None}]
        from knight_flow.export_files import _publish_new
        with patch('knight_flow.export_files._publish_new',side_effect=OSError('fixture publication failure')):
            with self.assertRaises(OSError):export_history({},'txt')
        self.assertEqual(list((self.folder/'exports').iterdir()),[])

    def test_text_and_markdown_keep_original_surrounding_whitespace(self):
        original='  Indented opening\n\n  Two lines  \n'
        self.rows=[{'text':original,'created_at':0}]
        for format in ('txt','md'):
            self.assertIn(original,export_history({},format).read_text(encoding='utf-8'))

    def test_subtitle_draft_starts_at_zero_with_monotonic_nonempty_cues(self):
        import re,regex
        self.rows=[{'text':'  ','created_at':float('inf')},
                   {'text':('word 👩🏽‍💻 日本語 '*20),'created_at':float('nan')},
                   {'text':'e\u0301'*100,'created_at':1e300}]
        path=export_history({},'srt')
        self.assertIn('subtitle-draft',path.name)
        content=path.read_text(encoding='utf-8')
        blocks=content.strip().split('\n\n');previous=0;spoken=[]
        def millis(stamp):
            hour,minute,second,fraction=map(int,re.split('[:,]',stamp))
            return ((hour*60+minute)*60+second)*1000+fraction
        for index,block in enumerate(blocks,1):
            sequence,timing,*lines=block.splitlines();self.assertEqual(int(sequence),index)
            begin,end=map(millis,timing.split(' --> '))
            self.assertEqual(begin,previous);self.assertGreater(end,begin);previous=end
            self.assertTrue(1<=len(lines)<=2)
            for line in lines:self.assertTrue(0<len(regex.findall(r'\X',line))<=42)
            spoken.extend(lines)
        self.assertEqual(''.join(''.join(spoken).split()),''.join(''.join(row['text'] for row in self.rows).split()))

    def test_empty_history_does_not_create_a_successful_empty_export(self):
        with self.assertRaisesRegex(ValueError,'No saved text'):export_history({},'txt')
        self.assertFalse((self.folder/'exports').exists())

    def test_capped_export_receipt_keeps_newest_entry_and_discloses_limit(self):
        from knight_flow.history import export_history_document
        self.rows=[{'text':'oldest-excluded'}]+[{'text':'middle'}]*19999+[{'text':'newest-included'}]
        result=export_history_document({},'md')
        self.assertTrue(result['capped']);self.assertEqual(result['entries'],20000)
        text=result['path'].read_text(encoding='utf-8')
        self.assertIn('20,000',text);self.assertIn('newest-included',text);self.assertNotIn('oldest-excluded',text)


if __name__=='__main__':unittest.main()
