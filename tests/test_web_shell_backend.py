"""Real product metadata against synthetic configuration and actions."""
import copy
import json
from pathlib import Path
import sys
import unittest
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.shell_backend import ShellBackend


class ShellBackendTests(unittest.TestCase):
    def test_model_guide_filters_use_catalog_status_ids(self):
        from knight_flow.model_catalog import catalog_entries
        actual = self.backend.snapshot()['model_guide']
        self.assertEqual([entry['status_id'] for entry in actual],
                         [entry.status for entry in catalog_entries()])

    def test_the_mac_globe_shortcut_can_be_saved_and_read_back(self):
        self.backend.handle('save', {'revision':self.backend.snapshot()['revision'],
                                    'changes':{'hotkeys.push_to_talk':[['fn']]}})
        fields = [field for page in self.backend.snapshot()['pages'] for section in page['sections'] for field in section['fields']]
        self.assertEqual(next(field['value'] for field in fields if field['id']=='hotkeys.push_to_talk'), [['fn']])
        self.assertEqual(self.persisted[0]['hotkeys']['push_to_talk'], [['fn']])

    def test_shortcut_chords_preserve_punctuation_without_text_delimiters(self):
        chords = [['ctrl',';'],['alt','+']]
        self.backend.handle('save', {'revision':self.backend.snapshot()['revision'],
                                    'changes':{'hotkeys.paste_last':chords}})
        fields = [field for page in self.backend.snapshot()['pages'] for section in page['sections'] for field in section['fields']]
        self.assertEqual(next(field['value'] for field in fields if field['id']=='hotkeys.paste_last'), chords)
        self.assertEqual(self.config['hotkeys']['paste_last'], chords)

    def test_menu_order_cannot_move_lifecycle_actions_into_daily_actions(self):
        self.backend.handle('save', {'revision':self.backend.snapshot()['revision'],
                                    'changes':{'overlay.menu_order':json.dumps(['quit_app','history','settings'])}})
        order = self.config['overlay']['menu_order']
        self.assertEqual(order[:2], ['history','settings'])
        self.assertEqual(order[-3:], ['check_updates','restart_app','quit_app'])

    def test_bad_menu_ids_do_not_reach_disk(self):
        with self.assertRaisesRegex(ValueError, 'menu'):
            self.backend.handle('save', {'revision':self.backend.snapshot()['revision'],
                                        'changes':{'overlay.menu_order':'["run_command"]'}})
        self.assertEqual(self.persisted, [])

    def test_changing_formatter_provider_does_not_carry_the_previous_key(self):
        self.config['transforms']['llm'].update(provider='openai',api_key='synthetic-previous-key')
        self.backend.handle('save', {'revision':self.backend.snapshot()['revision'], 'changes':{'transforms.llm.provider':'ollama'}})
        self.assertEqual(self.config['transforms']['llm']['api_key'],'')
        self.assertNotIn('synthetic-previous-key',json.dumps(self.persisted))

    def setUp(self):
        self.config=copy.deepcopy(DEFAULT_CONFIG)
        self.config['stt']['providers']['openai']['api_key']='synthetic-provider-secret'
        self.config['licensing']={'token':'synthetic-license'}
        self.persisted=[]
        self.effects=[]
        self.overlay=object.__new__(Overlay)
        self.backend=ShellBackend(self.config,Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets',self.persisted.append,
                                  lambda:self.effects.append('applied'),self.overlay._settings_palette,
                                  actions={'scratchpad':lambda:self.effects.append('scratchpad')})

    def test_complete_settings_and_all_themes_are_sanitized(self):
        state=self.backend.handle('state',{})
        fields={field['id']:field for page in state['pages'] for section in page['sections'] for field in section['fields']}
        self.assertEqual(len(state['themes']),80)
        for identifier in ('hotkeys.fix_that','translation.glossary','dictation.restore_clipboard_after_paste',
                           'transforms.llm.provider','privacy.history_backend','ui.app_font','stt.providers.local.model'):
            self.assertIn(identifier,fields)
        serialized=json.dumps(state)
        self.assertNotIn('synthetic-provider-secret',serialized)
        self.assertNotIn('synthetic-license',serialized)
        self.assertTrue(fields['stt.providers.openai.api_key']['saved'])
        self.assertEqual(fields['cleanup.format_intensity']['options'][0]['value'],'standard')

    def test_save_applies_after_persistence_and_keeps_existing_access(self):
        state=self.backend.snapshot()
        self.backend.handle('save',{'revision':state['revision'],'changes':{'ui.settings_theme':'Flow Light','privacy.save_history':False}})
        self.assertEqual(self.config['ui']['theme'],'light')
        self.assertFalse(self.persisted[0]['privacy']['save_history'])
        self.assertEqual(self.effects,['applied'])
        self.assertEqual(self.config['licensing']['token'],'synthetic-license')

    def test_only_registered_tool_actions_can_run(self):
        self.backend.handle('action',{'name':'scratchpad'})
        self.assertEqual(self.effects,['scratchpad'])
        for payload in ({'name':'run_command','command':'synthetic'}, {'name':'scratchpad','text':'unexpected'}, {'name':'unknown'}):
            with self.subTest(payload=payload),self.assertRaises(ValueError):self.backend.handle('action',payload)
        self.assertEqual(self.effects,['scratchpad'])

    def test_deepgram_key_update_preserves_legacy_consumer(self):
        self.backend.handle('save',{'revision':self.backend.snapshot()['revision'],
                                  'changes':{'stt.providers.deepgram.api_key':'new-synthetic-key'}})
        self.assertEqual(self.config['deepgram']['api_key'],'new-synthetic-key')
        self.assertNotIn('new-synthetic-key',json.dumps(self.backend.snapshot()))

    def test_a_runtime_refresh_failure_does_not_misreport_a_completed_disk_save(self):
        def fail():raise RuntimeError('synthetic runtime failure')
        self.backend.applied=fail
        result=self.backend.handle('save',{'revision':self.backend.snapshot()['revision'],
                                          'changes':{'privacy.save_history':False}})
        self.assertFalse(self.config['privacy']['save_history'])
        self.assertIn('saved',result['message'])
        self.assertIn('Restart',result['message'])


if __name__=='__main__':unittest.main()
