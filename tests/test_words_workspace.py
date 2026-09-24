import copy
import unittest
from unittest.mock import Mock
from knight_flow.web_shell.words_workspace import WordsWorkspace


class WordsWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.config={'dictionary': {'words':['OpenAI'], 'terms':[{'text':'Mayowa','sounds_like':['my yo wa'],'learned':True}],
             'replacements':[{'from':'teh','to':'the','case_sensitive':True}], 'auto_learn':True},
             'snippets':[{'trigger':'my signature','text':'Best,\nMayowa','enabled':True}], 'unrelated':{'keep':42}}
        self.persist=Mock();self.applied=Mock()
        self.service=WordsWorkspace(self.config,self.persist,self.applied)
    def listing(self,collection='vocabulary',query='',offset=0):
        return self.service.handle({'operation':'list','collection':collection,'query':query,'offset':offset})
    def put(self,collection,record,identifier='',revision=None):
        return self.service.handle({'operation':'put','collection':collection,'record':record,'id':identifier,'revision':revision or self.service.revision()})
    def read(self,collection,row):
        return self.service.handle({'operation':'read','collection':collection,'id':row['id'],'revision':self.service.revision()})
    def test_vocabulary_combines_saved_spellings_and_pronunciations(self):
        rows=self.listing()['entries']
        self.assertEqual([row['label'] for row in rows],['OpenAI','Mayowa'])
        self.assertTrue(rows[1]['learned'])
        self.assertNotIn('original',rows[0]);self.assertNotIn('index',rows[0])
    def test_search_matches_spoken_aliases(self):
        self.assertEqual(self.listing(query='MY YO')['entries'][0]['label'],'Mayowa')
    def test_new_name_is_in_the_existing_engine_terms_collection(self):
        self.put('vocabulary',{'text':'Déjà Vu','sounds_like':['day zha voo']})
        self.assertEqual(self.config['dictionary']['terms'][-1],{'text':'Déjà Vu','sounds_like':['day zha voo']})
        self.assertEqual(self.config['unrelated'],{'keep':42});self.persist.assert_called_once();self.applied.assert_called_once()
    def test_editing_plain_word_with_an_alias_moves_it_without_duplication(self):
        row=self.listing()['entries'][0]
        self.put('vocabulary',{'text':'OpenAI','sounds_like':['open a eye']},row['id'])
        self.assertEqual(self.config['dictionary']['words'],[])
        self.assertEqual([row['label'] for row in self.listing()['entries']].count('OpenAI'),1)
    def test_editing_replacement_keeps_its_existing_extra_options(self):
        row=self.listing('replacements')['entries'][0]
        self.put('replacements',{'from':'teh','to':'THE'},row['id'])
        self.assertTrue(self.config['dictionary']['replacements'][0]['case_sensitive'])
    def test_snippet_preserves_unicode_line_breaks_and_leading_spaces(self):
        text='  中文\n👨‍👩‍👧‍👦\n  ending '
        self.put('snippets',{'trigger':'family note','text':text,'enabled':False})
        row=self.listing('snippets',query='family note')['entries'][0]
        self.assertEqual(self.read('snippets',row)['record']['text'],text)
        self.assertFalse(row['enabled'])
    def test_duplicate_is_case_insensitive_and_never_overwrites(self):
        before=copy.deepcopy(self.config)
        with self.assertRaises(ValueError):self.put('vocabulary',{'text':'MAYOWA','sounds_like':[]})
        self.assertEqual(self.config,before);self.persist.assert_not_called()
    def test_failed_disk_save_leaves_live_vocabulary_unchanged(self):
        before=copy.deepcopy(self.config);self.persist.side_effect=OSError('disk full')
        with self.assertRaises(OSError):self.put('snippets',{'trigger':'new phrase','text':'my words','enabled':True})
        self.assertEqual(self.config,before);self.applied.assert_not_called()
    def test_stale_revision_never_overwrites_an_external_edit(self):
        revision=self.service.revision();self.config['dictionary']['words'].append('External')
        with self.assertRaisesRegex(ValueError,'changed elsewhere'):self.put('vocabulary',{'text':'New','sounds_like':[]},revision=revision)
        self.assertIn('External',self.config['dictionary']['words']);self.persist.assert_not_called()
    def test_delete_requires_confirmation_and_remembers_deliberate_removal(self):
        row=self.listing(query='Mayowa')['entries'][0]
        request={'operation':'delete','collection':'vocabulary','id':row['id'],'revision':self.service.revision(),'confirmed':False}
        with self.assertRaises(ValueError):self.service.handle(request)
        request['confirmed']=True;self.service.handle(request)
        self.assertEqual(self.listing(query='Mayowa')['total'],0)
        self.assertIn('mayowa',self.config['dictionary']['learn_tombstones'])
    def test_manual_add_clears_a_previous_dismissal(self):
        self.config['dictionary']['learn_tombstones']=['new name','leave me']
        self.put('vocabulary',{'text':'New Name','sounds_like':[]})
        self.assertEqual(self.config['dictionary']['learn_tombstones'],['leave me'])
    def test_invalid_or_empty_fields_do_not_save(self):
        for record in ({'trigger':'','text':'hello','enabled':True},{'trigger':'name','text':'','enabled':True},{'trigger':'name','text':'hello','enabled':'true'}):
            with self.assertRaises(ValueError):self.put('snippets',record)
        self.persist.assert_not_called()
    def test_pages_are_bounded_and_navigate_without_dropping_entries(self):
        self.config['dictionary']['words']=[f'Name {i:03d}' for i in range(85)]
        first=self.listing();second=self.listing(offset=first['next']);third=self.listing(offset=second['next'])
        self.assertEqual([len(page['entries']) for page in (first,second,third)],[40,40,6])
        self.assertIsNone(third['next'])
    def test_invalid_legacy_rows_are_kept_and_disclosed(self):
        self.config['snippets'].append({'unknown':'keep'})
        self.assertEqual(self.listing('snippets')['uneditable'],1)
        self.put('snippets',{'trigger':'other','text':'words','enabled':True})
        self.assertIn({'unknown':'keep'},self.config['snippets'])
    def test_runtime_refresh_failure_is_reported_as_saved(self):
        self.applied.side_effect=RuntimeError('runtime busy')
        result=self.put('vocabulary',{'text':'New name','sounds_like':[]})
        self.assertIn('Saved.',result['message']);self.assertIn('Restart',result['message'])
        self.assertEqual(self.listing(query='New name')['total'],1)
    def test_arbitrary_collection_and_unexpected_payload_are_rejected(self):
        with self.assertRaises(ValueError):self.listing('account')
        with self.assertRaises(ValueError):self.service.handle({'operation':'list','collection':'vocabulary','query':'','offset':0,'path':'config.json'})
        self.persist.assert_not_called()

    def test_returned_saved_id_can_be_edited_again(self):
        first=self.put('vocabulary',{'text':'New name','sounds_like':[]})
        second=self.put('vocabulary',{'text':'Newer name','sounds_like':[]},first['id'],first['revision'])
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(self.listing(query='Newer name')['total'],1)

    def test_empty_replacement_can_deliberately_remove_a_phrase(self):
        self.put('replacements',{'from':'remove this phrase','to':''})
        self.assertEqual(self.config['dictionary']['replacements'][-1]['to'],'')

if __name__=='__main__':unittest.main()
