import unittest
from knight_flow.web_shell.history_workspace import HistoryWorkspace

class Store:
    def __init__(self, rows): self.rows=rows
    def recent(self, limit): return self.rows[-limit:]
    def search(self, query, limit): return [row for row in self.rows if query.casefold() in row['text'].casefold()][-limit:]

class HistoryWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.text='A 👨‍👩‍👧‍👦 & <script>private()</script>\n'*3000
        self.store=Store([{'text':self.text,'created_at':1,'type':'dictation'},{'text':'new note','created_at':2}])
        self.pins=[]
        self.copied=[]
        self.service=HistoryWorkspace(self.store,lambda:self.pins,
            lambda text:self.pins.append({'text':text,'created_at':3}),
            lambda text:self.pins.clear(),self.copied.append)
    def listing(self,**kwargs):
        return self.service.handle({'operation':'list','query':'','offset':0,'pinned':False,**kwargs})
    def test_list_contains_only_bounded_previews_in_time_order(self):
        rows=self.listing()['entries']
        self.assertEqual(rows[0]['preview'],'new note')
        self.assertEqual(len(rows[1]['preview']),240)
        self.assertNotIn('text',rows[1])
    def test_chunks_reconstruct_the_entire_unicode_transcript(self):
        identifier=self.listing()['entries'][1]['id']
        parts=[]; offset=0
        while offset is not None:
            result=self.service.handle({'operation':'read','id':identifier,'offset':offset,'pinned':False})
            self.assertLessEqual(len(result['text']),16000)
            parts.append(result['text']);offset=result['next']
        self.assertEqual(''.join(parts),self.text)
    def test_copy_preserves_the_full_entry_and_never_uses_the_preview(self):
        identifier=self.listing()['entries'][1]['id']
        self.service.handle({'operation':'copy','id':identifier,'pinned':False})
        self.assertEqual(self.copied,[self.text])
    def test_pins_remain_accessible_after_history_expires(self):
        identifier=self.listing()['entries'][0]['id']
        self.service.handle({'operation':'pin','id':identifier,'pinned':False})
        self.store.rows=[]
        row=self.listing(pinned=True)['entries'][0]
        self.service.handle({'operation':'copy','id':row['id'],'pinned':True})
        self.assertEqual(self.copied,['new note'])
    def test_stale_identifier_cannot_copy_an_unrelated_entry(self):
        identifier=self.listing()['entries'][0]['id']
        self.store.rows=[]
        with self.assertRaises(ValueError): self.service.handle({'operation':'copy','id':identifier,'pinned':False})
        self.assertEqual(self.copied,[])
    def test_paths_extra_fields_and_invalid_offsets_are_refused(self):
        for payload in ({'operation':'read','id':'../../config.json','offset':0,'pinned':False},
                        {'operation':'list','query':'','offset':True,'pinned':False},
                        {'operation':'list','query':'','offset':-1,'pinned':False},
                        {'operation':'copy','id':'a'*32,'pinned':False,'text':'injected'}):
            with self.subTest(payload=payload),self.assertRaises(ValueError): self.service.handle(payload)

    def test_search_result_older_than_recent_page_still_opens_and_copies(self):
        self.store.rows=[{'text':'the older matching transcript','created_at':1}]+[
            {'text':f'newer {i}','created_at':i+2} for i in range(350)]
        row=self.listing(query='older matching')['entries'][0]
        result=self.service.handle({'operation':'read','id':row['id'],'offset':0,'pinned':False})
        self.assertEqual(result['text'],'the older matching transcript')
        self.service.handle({'operation':'copy','id':row['id'],'pinned':False})
        self.assertEqual(self.copied,['the older matching transcript'])
        self.store.rows=[]
        with self.assertRaises(ValueError):
            self.service.handle({'operation':'copy','id':row['id'],'pinned':False})

    def test_search_contexts_are_bounded_and_do_not_cache_transcripts(self):
        self.store.rows=[{'text':f'entry {i}','created_at':i} for i in range(350)]
        for i in range(350): self.listing(query=f'entry {i}')
        self.assertEqual(len(self.service.contexts),300)
        self.assertTrue(all(type(value) is str for value in self.service.contexts.values()))

    def test_unpin_uses_the_same_trimmed_value_as_the_pin_store(self):
        self.store.rows=[{'text':'  words with surrounding space\n','created_at':1}]
        values=[];self.service.unpin=values.append
        identifier=self.listing()['entries'][0]['id']
        self.service.handle({'operation':'unpin','id':identifier,'pinned':False})
        self.assertEqual(values,['words with surrounding space'])

if __name__=='__main__':unittest.main()
