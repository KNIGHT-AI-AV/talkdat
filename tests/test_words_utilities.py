import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from knight_flow.web_shell.words_workspace import WordsWorkspace
from knight_flow.web_shell.workspace_adapter import Workspaces


class WordsUtilitiesTests(unittest.TestCase):
    def setUp(self):
        self.config={'dictionary':{'words':['Original'],'terms':[],'replacements':[]},'snippets':[],'ui':{'theme':'old'}}
        self.persist=Mock();self.utility=Mock()
        self.service=WordsWorkspace(self.config,self.persist,utility=self.utility)
    def call(self,operation,**kwargs):return self.service.handle({'operation':operation,**kwargs})
    def preview(self):
        candidate=copy.deepcopy(self.config);candidate['dictionary']['words'].append('Imported')
        self.utility.return_value=(candidate,{'words':1,'replacements':0,'snippets':0})
        return self.call('pack_preview',source='file')
    def test_preview_does_not_mutate_and_apply_preserves_other_settings(self):
        result=self.preview();self.assertEqual(self.config['dictionary']['words'],['Original']);self.persist.assert_not_called()
        self.config['ui']['theme']='new';self.call('pack_apply',token=result['token'],confirmed=True)
        self.assertEqual(self.config['dictionary']['words'],['Original','Imported']);self.assertEqual(self.config['ui']['theme'],'new')
        with self.assertRaises(ValueError):self.call('pack_apply',token=result['token'],confirmed=True)
    def test_changed_vocabulary_and_expired_preview_cannot_apply(self):
        result=self.preview();self.config['dictionary']['words'].append('External')
        with self.assertRaises(ValueError):self.call('pack_apply',token=result['token'],confirmed=True)
        result=self.preview()
        with patch('knight_flow.web_shell.words_workspace.time.monotonic',return_value=self.service.pending_pack[2]+301):
            with self.assertRaises(ValueError):self.call('pack_apply',token=result['token'],confirmed=True)
        self.persist.assert_not_called()
    def test_wrong_or_cancelled_token_cannot_apply(self):
        result=self.preview()
        with self.assertRaises(ValueError):self.call('pack_apply',token='another',confirmed=True)
        self.call('pack_cancel')
        with self.assertRaises(ValueError):self.call('pack_apply',token=result['token'],confirmed=True)
    def test_failed_pack_write_keeps_data_and_allows_retry(self):
        result=self.preview();before=copy.deepcopy(self.config);self.persist.side_effect=OSError('disk full')
        with self.assertRaises(OSError):self.call('pack_apply',token=result['token'],confirmed=True)
        self.assertEqual(self.config,before);self.persist.side_effect=None
        self.call('pack_apply',token=result['token'],confirmed=True);self.assertIn('Imported',self.config['dictionary']['words'])
    def test_file_picker_reentrancy_cannot_overwrite_a_new_vocabulary_change(self):
        old=copy.deepcopy(self.config)
        def import_while_changed(*args):
            self.config['dictionary']['words'].append('Arrived while picking')
            return old,{'words':0,'replacements':0,'snippets':0}
        self.utility.side_effect=import_while_changed
        with self.assertRaisesRegex(ValueError,'while choosing'):self.call('pack_preview',source='file')
        self.assertIn('Arrived while picking',self.config['dictionary']['words']);self.persist.assert_not_called()
    def test_learning_updates_existing_engine_settings_atomically(self):
        for mode in ('off','offer','auto-on-second'):
            self.call('learning',mode=mode,revision=self.service.revision())
            self.assertEqual(self.config['dictionary']['auto_learn'],mode!='off')
            self.assertEqual(self.call('options')['mode'],mode)
    def test_suggestions_never_add_or_reoffer_dismissed_words(self):
        self.config['dictionary']['learn_tombstones']=['dismissed'];self.utility.return_value=['Dismissed','Candidate']
        self.assertEqual(self.call('suggestions')['words'],['Candidate']);self.persist.assert_not_called()
    def test_renderer_cannot_supply_an_import_path_or_practice_spelling(self):
        with self.assertRaises(ValueError):self.call('pack_preview',source='C:/private.json')
        with self.assertRaises(ValueError):self.call('practice_start',text='arbitrary',revision=self.service.revision())
        self.utility.assert_not_called()
    def test_practice_uses_only_a_current_saved_entry(self):
        listing=self.call('list',collection='vocabulary',query='',offset=0)
        self.utility.return_value={'active':True}
        self.call('practice_start',id=listing['entries'][0]['id'],revision=listing['revision'])
        self.utility.assert_called_once_with('practice_start','Original')
    def test_real_industry_pack_is_previewed_deduplicated_and_persisted(self):
        app=SimpleNamespace(config=self.config,overlay=Mock())
        adapter=Workspaces(app,self.persist,lambda:False)
        result=adapter.handle({'area':'words','operation':'pack_preview','source':'medical'})
        self.assertGreater(result['counts']['words'],100);self.persist.assert_not_called()
        adapter.handle({'area':'words','operation':'pack_apply','token':result['token'],'confirmed':True})
        self.assertIn('HIPAA',self.config['dictionary']['words'])
        again=adapter.handle({'area':'words','operation':'pack_preview','source':'medical'})
        self.assertEqual(again['counts']['words'],0)

if __name__=='__main__':unittest.main()
