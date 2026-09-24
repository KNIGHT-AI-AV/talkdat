"""Bridge boundary checks. Only synthetic settings are used."""
import copy
import math
import unittest
from knight_flow.web_shell.shell_state import SettingsStore, SettingsConflict

FIELDS = [
 {'id':'cleanup.max_ai_format_ms','label':'Formatting time budget','type':'number','min':100,'max':30000,'step':1},
 {'id':'privacy.save_history','label':'Save history','type':'toggle'},
 {'id':'ui.settings_theme','label':'Theme','type':'select','options':[{'value':'Flow Dark','label':'Flow Dark'},{'value':'Flow Light','label':'Flow Light'}]},
]

class BridgeSettingsTests(unittest.TestCase):
    def test_external_key_change_invalidates_draft_without_exposing_the_key(self):
        fields = FIELDS + [{'id':'provider.api_key','label':'Provider key','type':'secret'}]
        store = SettingsStore(self.config, fields, self.persisted.append)
        before = store.snapshot()
        self.config['provider']['api_key'] = 'changed-synthetic-key'
        after = store.snapshot()
        self.assertNotEqual(before['revision'], after['revision'])
        self.assertNotIn('changed-synthetic-key', str(after))
        with self.assertRaises(SettingsConflict):
            store.save({'revision':before['revision'],'changes':{'provider.api_key':'stale-draft'}})

    def setUp(self):
        self.config={'cleanup':{'max_ai_format_ms':1200},'privacy':{'save_history':True},'ui':{'settings_theme':'Flow Dark'},'provider':{'api_key':'synthetic-secret'},'license':{'token':'synthetic-license'}}
        self.persisted=[]
        self.store=SettingsStore(self.config,FIELDS,lambda config:self.persisted.append(copy.deepcopy(config)))

    def payload(self,changes): return {'revision':self.store.snapshot()['revision'],'changes':changes}

    def test_snapshot_never_exposes_unlisted_configuration(self):
        snapshot=self.store.snapshot()
        self.assertNotIn('synthetic-secret',str(snapshot));self.assertNotIn('synthetic-license',str(snapshot))
        self.assertEqual(snapshot['values']['cleanup.max_ai_format_ms'],1200)

    def test_mixed_bad_patch_is_rejected_before_any_write(self):
        for changes in ({'privacy.save_history':False,'provider.api_key':'replacement'},
                        {'privacy.save_history':False,'cleanup.max_ai_format_ms':math.inf},
                        {'privacy.save_history':'false'},{'cleanup.max_ai_format_ms':True},
                        {'cleanup.max_ai_format_ms':0},{'ui.settings_theme':'unknown'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.store.save(self.payload(changes))
        self.assertTrue(self.config['privacy']['save_history']);self.assertEqual(self.persisted,[])

    def test_stale_draft_cannot_overwrite_another_change(self):
        payload=self.payload({'privacy.save_history':False})
        self.config['cleanup']['max_ai_format_ms']=1500
        with self.assertRaises(SettingsConflict):self.store.save(payload)
        self.assertEqual(self.persisted,[])

    def test_failed_disk_write_leaves_live_settings_and_draft_revision_intact(self):
        old=self.store.snapshot()
        def fail(_):raise OSError('synthetic disk failure')
        self.store.persist=fail
        with self.assertRaises(OSError):self.store.save(self.payload({'privacy.save_history':False}))
        self.assertEqual(self.store.snapshot(),old)

    def test_success_changes_only_named_settings_and_retains_credentials(self):
        result=self.store.save(self.payload({'privacy.save_history':False}))
        self.assertFalse(result['values']['privacy.save_history'])
        self.assertEqual(self.config['provider']['api_key'],'synthetic-secret')
        self.assertEqual(len(self.persisted),1)

    def test_provider_secret_is_write_only_and_can_be_explicitly_removed(self):
        fields = FIELDS + [{'id':'provider.api_key','label':'Provider key','type':'secret'}]
        store = SettingsStore(self.config, fields, self.persisted.append)
        snapshot = store.snapshot()
        self.assertEqual(snapshot['values']['provider.api_key'], '')
        self.assertNotIn('synthetic-secret', str(snapshot))
        store.save({'revision':snapshot['revision'],'changes':{'provider.api_key':'new-synthetic-key'}})
        self.assertEqual(self.config['provider']['api_key'], 'new-synthetic-key')
        self.assertNotIn('new-synthetic-key',str(store.snapshot()))
        store.save({'revision':store.snapshot()['revision'],'changes':{'provider.api_key':None}})
        self.assertEqual(self.config['provider']['api_key'], '')

    def test_structured_lists_and_endpointing_round_trip_without_type_drift(self):
        fields = [{'id':'snippets','label':'Snippets','type':'textarea','codec':'json-list'},
                  {'id':'deepgram.endpointing','label':'Endpointing','type':'text','codec':'endpointing'},
                  {'id':'dictionary.words','label':'Words','type':'textarea','codec':'words'}]
        self.config.update({'snippets':[{'trigger':'hello','text':'Hello there'}], 'deepgram':{'endpointing':False}, 'dictionary':{'words':['Talk DAT']}})
        store=SettingsStore(self.config,fields,self.persisted.append)
        self.assertEqual(store.snapshot()['values']['deepgram.endpointing'],'false')
        result=store.save({'revision':store.snapshot()['revision'],'changes':{'deepgram.endpointing':'450','dictionary.words':'Talk DAT, Taskrune\nTalk DAT'}})
        self.assertEqual(self.config['deepgram']['endpointing'],450)
        self.assertEqual(self.config['dictionary']['words'],['Talk DAT','Taskrune'])
        self.assertEqual(result['values']['deepgram.endpointing'],'450')
        for invalid in ('{}','[NaN]','not json'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                store.save({'revision':store.snapshot()['revision'],'changes':{'snippets':invalid}})

    def test_normalization_happens_on_candidate_before_persistence(self):
        def normalize(candidate, changed):
            candidate['derived'] = sorted(changed)
        store=SettingsStore(self.config,FIELDS,self.persisted.append,normalize=normalize)
        store.save({'revision':store.snapshot()['revision'],'changes':{'privacy.save_history':False}})
        self.assertEqual(self.persisted[0]['derived'],['privacy.save_history'])

if __name__=='__main__':unittest.main()
