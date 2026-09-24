import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from knight_flow.web_shell.notes_workspace import NotesWorkspace, NotesConflict


class NotesWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'notes.json'
        self.legacy=self.path.with_suffix('.md')
        self.copied=[]
        self.service=NotesWorkspace(self.path,self.legacy,self.copied.append)
    def call(self,operation,**kwargs):return self.service.handle({'operation':operation,**kwargs})
    def first(self):return self.call('list')['notes'][0]
    def begin(self,note,title='Edited',as_copy=False):
        return self.call('begin_save',id=note['id'],revision=note['revision'],title=title,as_copy=as_copy)['token']
    def save(self,note,text,title='Edited',as_copy=False):
        token=self.begin(note,title,as_copy)
        for offset in range(0,len(text),16000):self.call('append_save',token=token,offset=offset,text=text[offset:offset+16000])
        return self.call('finish_save',token=token)
    def test_open_does_not_write_and_legacy_words_survive_first_edit(self):
        self.legacy.write_text('legacy 👩🏿‍💻 words',encoding='utf-8')
        note=self.first()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.call('read',id=note['id'],revision=note['revision'],offset=0)['text'],'legacy 👩🏿‍💻 words')
        self.save(note,'legacy 👩🏿‍💻 words plus new')
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['tabs'][0]['text'],'legacy 👩🏿‍💻 words plus new')
        self.assertEqual(self.legacy.read_text(encoding='utf-8'),'legacy 👩🏿‍💻 words')
    def test_old_snapshot_cannot_overwrite_same_note(self):
        note=self.first()
        self.save(note,'saved elsewhere')
        with self.assertRaises(NotesConflict):self.save(note,'stale draft')
        self.assertEqual(self.service.load()['tabs'][0]['text'],'saved elsewhere')
    def test_finishing_transfer_rechecks_revision_and_save_copy_keeps_both(self):
        note=self.save(self.first(),'original')
        token=self.begin(note)
        self.call('append_save',token=token,offset=0,text='my draft')
        other=NotesWorkspace(self.path,self.legacy,self.copied.append)
        doc=other.load();doc['tabs'][0]['text']='other edit';other.write(doc)
        with self.assertRaises(NotesConflict):self.call('finish_save',token=token)
        self.save(note,'my draft',as_copy=True)
        self.assertEqual([n['text'] for n in self.service.load()['tabs']],['other edit','my draft'])
    def test_other_note_change_is_preserved_when_this_note_saves(self):
        first=self.save(self.first(),'first')
        second=self.call('new')
        self.save(second,'second changed')
        self.save(first,'first changed')
        self.assertEqual([n['text'] for n in self.service.load()['tabs']],['first changed','second changed'])
    def test_failed_atomic_replace_preserves_file_and_pending_words(self):
        note=self.save(self.first(),'saved text')
        before=self.path.read_bytes()
        token=self.begin(note)
        self.call('append_save',token=token,offset=0,text='new words')
        with patch.object(Path,'replace',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):self.call('finish_save',token=token)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.service.pending['parts'],['new words'])
        self.call('finish_save',token=token)
        self.assertEqual(self.service.load()['tabs'][0]['text'],'new words')
    def test_long_unicode_chunks_reconstruct_and_full_copy_preserves_text(self):
        text='Family 👨‍👩‍👧‍👦 <literal> and 中文\n'*2500
        note=self.save(self.first(),text)
        offset=0;parts=[]
        while offset is not None:
            result=self.call('read',id=note['id'],revision=note['revision'],offset=offset)
            parts.append(result['text']);offset=result['next']
        self.assertEqual(''.join(parts),text)
        self.call('copy',id=note['id']);self.assertEqual(self.copied,[text])
    def test_corrupt_or_duplicate_notes_never_overwrite_saved_file(self):
        for value in ('{broken',json.dumps({'tabs':[{'id':'a','text':'first','title':'A'},{'id':'a','text':'second','title':'B'}]})):
            self.path.write_text(value,encoding='utf-8')
            with self.assertRaises(ValueError):self.call('new')
            self.assertEqual(self.path.read_text(encoding='utf-8'),value)
    def test_delete_checks_revision_and_keeps_one_blank_note(self):
        old=self.first();new=self.save(old,'keep')
        with self.assertRaises(NotesConflict):self.call('delete',id=old['id'],revision=old['revision'])
        self.call('delete',id=new['id'],revision=new['revision'])
        self.assertEqual(len(self.call('list')['notes']),1)
        self.assertEqual(self.service.load()['tabs'][0]['text'],'')
    def test_cancelled_and_out_of_order_transfer_cannot_change_notes(self):
        note=self.save(self.first(),'keep')
        token=self.begin(note)
        with self.assertRaises(ValueError):self.call('append_save',token=token,offset=5,text='wrong')
        self.call('cancel_save',token=token)
        with self.assertRaises(ValueError):self.call('finish_save',token=token)
        self.assertEqual(self.service.load()['tabs'][0]['text'],'keep')
    def test_unexpected_paths_are_not_accepted(self):
        with self.assertRaises(ValueError):self.call('list',path='elsewhere')

    def test_search_finds_words_beyond_the_preview(self):
        self.save(self.first(),'ordinary '*200+'hidden searchable phrase')
        result=self.call('list',query='searchable phrase')
        self.assertEqual(len(result['notes']),1)
        self.assertNotIn('searchable phrase',result['notes'][0]['preview'])

    def test_import_cancellation_and_export_preserve_original_content(self):
        self.service.import_file=lambda:None
        self.assertTrue(self.call('import')['cancelled'])
        self.assertFalse(self.path.exists())
        self.service.import_file=lambda:('Imported','  exact words 👩🏿‍💻\n')
        note=self.call('import')
        exports=[]
        self.service.export_file=lambda title,text,format:exports.append((title,text,format)) or 'chosen.md'
        self.call('export',id=note['id'],format='md')
        self.assertEqual(exports,[('Imported','  exact words 👩🏿‍💻\n','md')])

    def test_chunk_read_refuses_changed_note_instead_of_mixing_versions(self):
        note=self.save(self.first(),'a'*20000)
        result=self.call('read',id=note['id'],revision=note['revision'],offset=0)
        self.save(note,'b'*20000)
        with self.assertRaises(NotesConflict):self.call('read',id=note['id'],revision=note['revision'],offset=result['next'])

if __name__=='__main__':unittest.main()
