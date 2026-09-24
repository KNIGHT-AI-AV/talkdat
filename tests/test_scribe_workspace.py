import datetime,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from knight_flow.web_shell.scribe_workspace import ScribeWorkspace


def engine(body='Notes 日本語 👩🏽‍💻'):
    item=SimpleNamespace(body=body,saved_path=None,phase='review',when=datetime.datetime.now(),review_edited=False,draft_saved=False,
        finished=threading.Event(),_lock=threading.RLock(),recorder=SimpleNamespace(started_at=0,written_bytes={'you':32000},rates={'you':16000},channels={'you':1},folder=Path('recording-one')))
    item.finished.set()
    item.snapshot=lambda:{'phase':item.phase,'message':'Review your notes.','body':item.body,'saved_path':str(item.saved_path or ''),
        'finished':item.finished.is_set(),'audio_closed':True,'recording_folder':'recording-one','completed':1,'gaps':0,'issues':[]}
    return item


class ScribeWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'notes.md'
        self.current=engine();self.tasks=[];self.ui=[];self.calls=[];self.fail=set();self.config={'scribe':{'source':'both'},'private':{'key':'never return'}}
        self.persist=Mock();self.service=ScribeWorkspace(self.config,self.persist,self.utility,self.ui.append,self.tasks.append)
        self.service.handle({'operation':'open'});self.drain()
    def utility(self,action,value):
        self.calls.append((action,value))
        if action in self.fail:raise OSError('fixture failure')
        if action=='current':return self.current
        if action=='platform':return 'win32'
        if action=='catalog':return {'entries':[{'id':'recording-one','name':'Sep 20','source':'both','draft':True,'interrupted':False}],'limited':False}
        if action=='save':self.path.write_text(value,encoding='utf-8');return self.path
        if action=='start':self.current=engine('');self.current.phase='preparing';self.current.finished.clear()
        if action=='restore':return engine('Recovered notes')
        if action=='adopt':
            if self.current is not value['previous']:raise ValueError('Changed recording')
            self.current=value['engine']
    def drain(self):
        while self.tasks:self.tasks.pop(0)()
        while self.ui:self.ui.pop(0)()
    def act(self,operation,**extra):return self.service.handle({'operation':operation,**extra})
    def edit(self,text='Edited 日本語 👩🏽‍💻'):
        token=self.act('begin_edit',revision=self.service.revision)['token']
        self.act('append_edit',token=token,offset=0,text=text)
        return self.act('commit_edit',token=token)
    def test_open_reads_actual_engine_without_starting_audio(self):
        state=self.act('status');self.assertEqual(state['seconds'],1);self.assertEqual(state['length'],len(self.current.body))
        self.assertFalse(any(action=='start' for action,_ in self.calls));self.assertNotIn('never return',repr(state));self.assertEqual(len(state['library']),1)
    def test_source_saves_transaction_and_rejects_stale_configuration(self):
        revision=self.act('status')['config_revision'];self.act('source',source='microphone',config_revision=revision)
        self.assertEqual(self.config['scribe']['source'],'microphone')
        with self.assertRaises(ValueError):self.act('source',source='system',config_revision=revision)
        self.assertEqual(self.config['private']['key'],'never return')
    def test_failed_source_write_keeps_choice(self):
        self.persist.side_effect=OSError()
        with self.assertRaises(ValueError):self.act('source',source='system',config_revision=self.act('status')['config_revision'])
        self.assertEqual(self.config['scribe']['source'],'both')
    def test_completed_edit_waits_for_durable_checkpoint(self):
        state=self.edit();self.assertTrue(state['active']);self.assertFalse(state['draft_saved']);self.assertTrue(state['edited'])
        self.drain();state=self.act('status');self.assertTrue(state['draft_saved']);self.assertTrue(state['edited']);self.assertEqual(self.current.body,'Edited 日本語 👩🏽‍💻')
    def test_failed_checkpoint_preserves_complete_memory_draft(self):
        self.fail.add('checkpoint');self.edit();self.drain();state=self.act('status')
        self.assertFalse(state['draft_saved']);self.assertIn('could not be saved',state['message']);self.assertEqual(self.service.text,'Edited 日本語 👩🏽‍💻')
    def test_incomplete_transfer_does_not_replace_previous_notes(self):
        token=self.act('begin_edit',revision=self.service.revision)['token']
        with self.assertRaises(ValueError):self.act('append_edit',token=token,offset=2,text='Lost')
        self.assertEqual(self.current.body,'Notes 日本語 👩🏽‍💻')
    def test_stale_revision_cannot_overwrite_new_engine_words(self):
        previous=self.service.revision;self.current.body='Newer notes'
        with self.assertRaises(ValueError):self.act('begin_edit',revision=previous)
        self.assertEqual(self.service.text,'Newer notes')
    def test_start_refuses_unsaved_edits_even_if_checkpointed(self):
        self.edit();self.drain()
        with self.assertRaises(ValueError):self.act('start',revision=self.service.revision)
    def test_save_runs_off_ui_and_receipt_appears_only_after_completion(self):
        self.edit();self.drain();state=self.act('save',revision=self.service.revision)
        self.assertTrue(state['saving']);self.assertEqual(state['receipts'],[]);self.assertFalse(self.path.exists())
        self.drain();state=self.act('status');self.assertFalse(state['edited']);self.assertTrue(state['receipts'][0]['current']);self.assertEqual(self.path.read_text(encoding='utf-8'),'Edited 日本語 👩🏽‍💻')
    def test_failed_export_keeps_edit_and_prior_receipts(self):
        self.fail.add('save');self.edit();self.drain();self.act('save',revision=self.service.revision);self.drain()
        state=self.act('status');self.assertEqual(state['receipts'],[]);self.assertTrue(state['edited']);self.assertIn('could not be saved',state['message'])
    def test_unknown_receipt_cannot_open_an_arbitrary_path(self):
        with self.assertRaises(ValueError):self.act('open_file',id='C:\\private.md')
    def test_copy_delivers_all_unicode_words(self):
        self.act('copy',revision=self.service.revision);self.assertIn(('copy',self.current.body),self.calls)
    def test_new_engine_does_not_replace_an_edited_draft(self):
        self.edit();self.drain();self.current=engine('Other recording');state=self.act('status')
        self.assertTrue(state['other_recording']);self.assertEqual(self.service.text,'Edited 日本語 👩🏽‍💻')
    def test_restore_uses_worker_then_adopts_on_ui(self):
        self.act('restore',id='recording-one',revision=self.service.revision)
        self.assertNotEqual(self.current.body,'Recovered notes');self.drain();self.assertEqual(self.service.text,'Recovered notes')
    def test_changed_owner_blocks_late_restore(self):
        self.act('restore',id='recording-one',revision=self.service.revision);replacement=engine('Another session');self.current=replacement;self.drain()
        self.assertIs(self.current,replacement)
    def test_failed_library_refresh_keeps_previous_rows(self):
        self.fail.add('catalog');self.act('library');self.drain();state=self.act('status')
        self.assertEqual(len(state['library']),1);self.assertIn('could not be listed',state['library_message'])
    def test_closed_workspace_cannot_mutate_until_reopened(self):
        self.service.close()
        with self.assertRaises(ValueError):self.act('copy',revision=self.service.revision)
        self.act('open');self.act('copy',revision=self.service.revision)
    def test_invalid_actions_and_boolean_revision_are_rejected(self):
        for payload in [{'operation':'source','source':'both'},{'operation':'status','extra':True},{'operation':'copy','revision':True}]:
            with self.subTest(payload=payload),self.assertRaises(ValueError):self.service.handle(payload)
