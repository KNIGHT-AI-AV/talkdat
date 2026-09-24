import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from knight_flow import packs, pronunciation, learned_words


class WordsRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def test_pack_roundtrip_retains_pronunciations(self):
        config={'dictionary':{'terms':[{'text':'Mayowa','sounds_like':['my yo wa'],'trained_aliases':['my yo wa']} ]}}
        path=packs.export_pack(config,self.root/'pack.json')
        restored={}; packs.import_pack(restored,path)
        self.assertEqual(restored['dictionary']['terms'],config['dictionary']['terms'])
    def test_bad_pack_cannot_partly_mutate_live_vocabulary(self):
        path=self.root/'pack.json';path.write_text(json.dumps({'talkdat_pack':1,'dictionary':{'words':['Added'],'replacements':42}}))
        config={'dictionary':{'words':['Original']}}; before=copy.deepcopy(config)
        with self.assertRaises((ValueError,TypeError)):packs.import_pack(config,path)
        self.assertEqual(config,before)
    def test_ask_first_does_not_auto_add_distinctive_spelling(self):
        self.assertEqual(learned_words.note_fix_evidence('SAHVVV',{'dictionary':{'auto_learn_mode':'offer'}},1000),'offer')
    def test_deleted_trained_word_does_not_return(self):
        with patch.object(pronunciation,'clips_root',return_value=self.root):
            pronunciation.store_clip({},'Mayowa',1,b'RIFFfake')
            config={'dictionary':{'terms':[],'learn_tombstones':['mayowa']}}
            pronunciation.refresh_term_aliases(config,lambda _: 'my yo wa')
            self.assertEqual(config['dictionary']['terms'],[])
    def test_distinct_non_latin_names_keep_separate_takes(self):
        with patch.object(pronunciation,'clips_root',return_value=self.root):
            a=pronunciation.store_clip({},'美和',1,b'first')
            b=pronunciation.store_clip({},'明和',1,b'second')
            self.assertNotEqual(a,b);self.assertEqual(a.read_bytes(),b'first')
    def test_non_latin_recognition_alias_is_retained(self):
        with patch.object(pronunciation,'clips_root',return_value=self.root):
            pronunciation.store_clip({},'美和',1,b'RIFFfake')
            self.assertEqual(pronunciation.harvest_aliases({},'美和',lambda _: '明和。'),['明和'])
    def test_legacy_pronunciation_folder_is_read_without_moving_audio(self):
        legacy=self.root/'mayowa';legacy.mkdir()
        (legacy/'term.json').write_text(json.dumps({'text':'Mayowa'}));(legacy/'take-1.wav').write_bytes(b'old take')
        with patch.object(pronunciation,'clips_root',return_value=self.root):
            self.assertEqual(pronunciation.clips_dir({},'Mayowa'),legacy)
            self.assertEqual(pronunciation.harvest_aliases({},'Mayowa',lambda _: 'my yo wa'),['my yo wa'])
    def test_pack_with_plain_and_pronunciation_entry_keeps_the_aliases(self):
        path=packs.export_pack({'dictionary':{'words':['Mayowa'],'terms':[{'text':'Mayowa','sounds_like':['my yo wa']}]}},self.root/'pack.json')
        restored={};packs.import_pack(restored,path)
        self.assertEqual(restored['dictionary']['words'],[])
        self.assertEqual(restored['dictionary']['terms'][0]['sounds_like'],['my yo wa'])
    def test_failed_pack_export_does_not_destroy_an_existing_pack(self):
        path=self.root/'pack.json';path.write_text('previous export')
        with patch('knight_flow.packs.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):packs.export_pack({},path)
        self.assertEqual(path.read_text(),'previous export')
        self.assertEqual(list(self.root.iterdir()),[path])
    def test_nonfinite_pack_data_is_rejected_before_changes(self):
        path=self.root/'bad.json';path.write_text('{"talkdat_pack":1,"dictionary":{"terms":[{"text":"Name","unknown":NaN}]}}')
        config={'keep':True}
        with self.assertRaises(ValueError):packs.import_pack(config,path)
        self.assertEqual(config,{'keep':True})

if __name__=='__main__':unittest.main()
