import copy
import unittest
from knight_flow.web_shell.profiles_workspace import ProfilesWorkspace
from knight_flow.profiles import active_profile, apply_profile


def record(match='Slack', **changes):
    return dict(match=match, enabled=True, cleanup_level='', tone='', language='', auto_enter=None, **changes)


class AppPreferenceWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.config={'profiles':[],'privacy':{'local_only':True},'style_profile':{'votes':25,'contractions':30}}
        self.saved=[];self.service=ProfilesWorkspace(self.config,lambda candidate:self.saved.append(copy.deepcopy(candidate)))
    def call(self,operation,**values):return self.service.handle(dict(operation=operation,**values))
    def put(self,value,id='',revision=None):
        return self.call('put',id=id,revision=revision or self.call('list')['revision'],record=value)
    def test_add_reopen_and_return_to_default_preserves_other_preferences(self):
        value=record();value.update(tone='friendly',auto_enter=True)
        saved=self.put(value)
        reopened=self.call('list')['entries'][0]
        self.assertEqual(reopened['record'],value)
        value['auto_enter']=None;value['tone']=''
        self.put(value,id=saved['id'])
        self.assertNotIn('auto_enter',self.config['profiles'][0])
        effective=apply_profile({'dictation':{'press_enter_command':False}},self.config['profiles'][0])
        self.assertFalse(effective['dictation']['press_enter_command'])
        self.assertEqual(self.config['privacy'],{'local_only':True})
    def test_failed_save_keeps_the_original_and_all_other_config(self):
        snapshot=copy.deepcopy(self.config)
        def fail(candidate):raise OSError('disk fixture')
        self.service.persist=fail
        with self.assertRaisesRegex(ValueError,'could not be saved'):self.put(record())
        self.assertEqual(self.config,snapshot)
    def test_stale_edit_and_stale_delete_cannot_replace_another_change(self):
        original=self.put(record());old=original['revision']
        self.config['profiles'][0]['tone']='formal'
        with self.assertRaisesRegex(ValueError,'changed elsewhere'):self.put(record(),original['id'],old)
        with self.assertRaisesRegex(ValueError,'changed elsewhere'):self.call('delete',id=original['id'],revision=old,confirmed=True)
        self.assertEqual(self.config['profiles'][0]['tone'],'formal')
    def test_legacy_extra_fields_and_custom_tone_are_retained(self):
        self.config['profiles']=[{'match':'Safari','tone':'be exceptionally brief','language':'xx-custom','future':{'keep':42}}]
        row=self.call('list')['entries'][0];row['record']['enabled']=False
        self.put(row['record'],row['id'])
        self.assertEqual(self.config['profiles'][0]['future'],{'keep':42})
        self.assertEqual(self.config['profiles'][0]['tone'],'be exceptionally brief')
        self.assertEqual(self.config['profiles'][0]['language'],'xx-custom')
    def test_move_changes_the_first_matching_preference(self):
        self.put(record('slack'));value=record('slack.exe');value['tone']='formal';second=self.put(value)
        self.assertEqual(active_profile(self.config,'slack.exe')['match'],'slack')
        moved=self.call('move',id=second['id'],revision=second['revision'],direction='up')
        self.assertEqual(active_profile(self.config,'slack.exe')['tone'],'formal')
        self.assertEqual(self.call('list')['entries'][0]['id'],moved['id'])
    def test_only_confirmed_delete_removes_the_selected_entry(self):
        saved=self.put(record())
        with self.assertRaises(ValueError):self.call('delete',id=saved['id'],revision=saved['revision'],confirmed=False)
        self.assertEqual(len(self.config['profiles']),1)
        self.call('delete',id=saved['id'],revision=saved['revision'],confirmed=True)
        self.assertEqual(self.config['profiles'],[])
    def test_duplicate_app_name_is_rejected_case_insensitively(self):
        self.put(record())
        with self.assertRaisesRegex(ValueError,'already'):self.put(record(' slack '))
        self.assertEqual(len(self.config['profiles']),1)
    def test_bad_boolean_and_unexpected_fields_never_reach_disk(self):
        for field,value in [('enabled','false'),('auto_enter',1),('match',None),('match',''),('language','invalid language'),('cleanup_level','unknown')]:
            candidate=record();candidate[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.put(candidate)
        candidate=record();candidate['api_key']='fixture'
        with self.assertRaises(ValueError):self.put(candidate)
        self.assertEqual(self.saved,[])
    def test_damaged_entries_are_disclosed_and_preserved(self):
        self.config['profiles']=[None,{'match':123},{'match':'Slack'}]
        result=self.call('list');self.assertEqual(result['uneditable'],2)
        row=result['entries'][0];row['record']['tone']='friendly';self.put(row['record'],row['id'])
        self.assertEqual(self.config['profiles'][:2],[None,{'match':123}])
    def test_oversized_legacy_list_is_retained_without_moving_beyond_editor(self):
        self.config['profiles']=[{'match':f'App{i}'} for i in range(101)]
        result=self.call('list');self.assertEqual(result['uneditable'],1);self.assertFalse(result['can_add'])
        self.assertFalse(result['entries'][-1]['can_down'])
        with self.assertRaises(ValueError):self.put(record())
        with self.assertRaises(ValueError):self.call('move',id=result['entries'][-1]['id'],revision=result['revision'],direction='down')
        self.assertEqual(len(self.config['profiles']),101)
    def test_style_counts_are_not_raw_text_and_reset_is_confirmed(self):
        result=self.call('style');self.assertEqual(result['votes'],25);self.assertTrue(result['ready'])
        self.assertEqual(set(result),{'votes','ready','revision'})
        with self.assertRaises(ValueError):self.call('reset_style',revision=result['revision'],confirmed=False)
        self.call('reset_style',revision=result['revision'],confirmed=True)
        self.assertEqual(self.config['style_profile'],{})
        self.assertEqual(self.config['privacy'],{'local_only':True})
    def test_style_updates_do_not_block_unrelated_app_edits_but_do_block_stale_reset(self):
        app_revision=self.call('list')['revision'];style_revision=self.call('style')['revision']
        self.config['style_profile']['votes']+=1
        self.put(record(),revision=app_revision)
        self.assertEqual(self.config['style_profile']['votes'],26)
        with self.assertRaisesRegex(ValueError,'changed'):self.call('reset_style',revision=style_revision,confirmed=True)
    def test_failed_style_reset_retains_counts(self):
        state=self.call('style')
        def fail(candidate):raise OSError('disk fixture')
        self.service.persist=fail
        with self.assertRaisesRegex(ValueError,'could not be cleared'):self.call('reset_style',revision=state['revision'],confirmed=True)
        self.assertEqual(self.config['style_profile']['votes'],25)

if __name__=='__main__':unittest.main()
