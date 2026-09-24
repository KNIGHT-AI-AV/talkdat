import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock
from knight_flow.web_shell.history_exports import HistoryExports


class HistoryExportJobsTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.path=self.root/'saved.txt';self.path.write_text('exact words')
        self.work=[];self.finish=[];self.opened=[];self.config={'privacy':{'history_backend':'jsonl'}}
        self.loader=Mock(return_value=dict(path=self.path,entries=3,format='txt',capped=False))
        self.service=HistoryExports(self.config,self.finish.append,self.opened.append,loader=self.loader,launch=self.work.append)
    def start(self,format='txt'):
        return self.service.handle({'command':'start','format':format})
    def complete(self):
        self.work.pop(0)();self.finish.pop(0)()
    def test_export_reads_and_saves_off_the_calling_ui_queue(self):
        result=self.start();self.assertTrue(result['active']);self.loader.assert_not_called()
        self.work.pop(0)();self.assertTrue(self.service.snapshot()['active'])
        self.assertEqual(self.service.snapshot()['receipts'],[])
        self.finish.pop(0)();self.assertFalse(self.service.snapshot()['active'])
        self.assertEqual(self.service.snapshot()['receipts'][0]['entries'],3)
    def test_configuration_is_captured_before_background_work(self):
        self.start();self.config['privacy']['history_backend']='sqlite';self.complete()
        self.assertEqual(self.loader.call_args.args[0]['privacy']['history_backend'],'jsonl')
    def test_fast_repeat_save_cannot_start_duplicate_jobs(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'still saving'):self.start('pdf')
        self.assertEqual(len(self.work),1)
    def test_no_file_opens_until_the_owner_chooses_an_engine_receipt(self):
        self.start();self.complete();self.assertEqual(self.opened,[])
        row=self.service.snapshot()['receipts'][0];self.assertNotIn('path',row)
        self.service.handle({'command':'open','id':row['id']});self.assertEqual(self.opened,[self.path])
        self.service.handle({'command':'folder','id':row['id']});self.assertEqual(self.opened[-1],self.root)
    def test_failed_save_retains_earlier_receipts_and_can_retry(self):
        self.start();self.complete();before=self.service.snapshot()['receipts']
        self.loader.side_effect=OSError('disk full')
        self.start();self.complete();state=self.service.snapshot()
        self.assertTrue(state['error']);self.assertFalse(state['active']);self.assertEqual(state['receipts'],before)
        self.loader.side_effect=None;self.start();self.complete();self.assertFalse(self.service.snapshot()['error'])
    def test_launch_failure_cannot_leave_export_stuck_active(self):
        self.service.launch=Mock(side_effect=RuntimeError('no threads'))
        state=self.start();self.assertFalse(state['active']);self.assertTrue(state['error'])
    def test_removed_file_and_forged_paths_cannot_open(self):
        self.start();self.complete();row=self.service.snapshot()['receipts'][0]
        self.path.unlink()
        for payload in ({'command':'open','id':row['id']},{'command':'open','id':'x'*32},
                        {'command':'open','id':row['id'],'path':'C:/config.json'},
                        {'command':'folder','id':'../../config.json'}):
            with self.subTest(payload=payload),self.assertRaises(ValueError):self.service.handle(payload)
        self.assertEqual(self.opened,[])
    def test_receipts_are_bounded_and_old_identifiers_expire(self):
        self.start();self.complete();first=self.service.snapshot()['receipts'][0]['id']
        for _ in range(12):self.start();self.complete()
        self.assertEqual(len(self.service.snapshot()['receipts']),12)
        with self.assertRaises(ValueError):self.service.handle({'command':'open','id':first})
    def test_protocol_rejects_invalid_fields_and_formats(self):
        for payload in (None,{}, {'command':'start','format':True},{'command':'start','format':'../x'},
                        {'command':'start','format':'txt','text':'injected'}, {'command':'status','id':'x'}):
            with self.subTest(payload=payload),self.assertRaises(ValueError):self.service.handle(payload)
        self.assertEqual(self.work,[])
    def test_real_worker_returns_while_storage_is_waiting(self):
        entered=threading.Event();release=threading.Event();finished=threading.Event()
        self.addCleanup(release.set)
        def load(config,format):
            entered.set();release.wait(3);return dict(path=self.path,entries=1,format=format)
        def dispatch(callback):self.finish.append(callback);finished.set()
        service=HistoryExports({},dispatch,self.opened.append,loader=load)
        self.assertTrue(service.handle({'command':'start','format':'txt'})['active'])
        self.assertTrue(entered.wait(2));self.assertTrue(service.handle({'command':'status'})['active'])
        release.set();self.assertTrue(finished.wait(2));self.finish.pop(0)()
        self.assertFalse(service.snapshot()['active'])


if __name__=='__main__':unittest.main()
