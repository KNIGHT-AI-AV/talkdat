import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from knight_flow.credentials import credential_target
from knight_flow.web_shell.shell_persistence import save_settings_config
from tests.test_credentials import MemoryCredentialStore


class WebSettingsPersistenceTests(unittest.TestCase):
    def test_failed_file_swap_restores_the_previous_protected_key(self):
        target = credential_target('STT','openai')
        store = MemoryCredentialStore({target:'synthetic-old'})
        config = {'stt':{'providers':{'openai':{'api_key':'synthetic-new'}}}}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TALK_DAT_HOME':folder}), patch('knight_flow.web_shell.shell_persistence.credential_store',return_value=store):
            destination = Path(folder)/'config.json'
            destination.write_text('{"existing":true}',encoding='utf-8')
            with patch('knight_flow.config.os.replace',side_effect=OSError('synthetic disk failure')):
                with self.assertRaises(OSError):save_settings_config(config)
            self.assertEqual(store.read(target),'synthetic-old')
            self.assertEqual(json.loads(destination.read_text()),{'existing':True})

    def test_refused_key_write_does_not_report_success_or_change_the_file(self):
        target = credential_target('STT','openai')
        store = MemoryCredentialStore({target:'synthetic-old'}, fail_writes=True)
        config = {'stt':{'providers':{'openai':{'api_key':'synthetic-new'}}}}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TALK_DAT_HOME':folder}), patch('knight_flow.web_shell.shell_persistence.credential_store',return_value=store):
            with self.assertRaises(ValueError):save_settings_config(config)
            self.assertFalse((Path(folder)/'config.json').exists())
            self.assertEqual(store.read(target),'synthetic-old')

    def test_successful_key_change_reaches_the_vault_and_never_the_file(self):
        target = credential_target('STT','openai')
        store = MemoryCredentialStore({target:'synthetic-old'})
        config = {'stt':{'providers':{'openai':{'api_key':'synthetic-new'}}}}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TALK_DAT_HOME':folder}), patch('knight_flow.web_shell.shell_persistence.credential_store',return_value=store):
            save_settings_config(config)
            self.assertEqual(store.read(target),'synthetic-new')
            self.assertNotIn('synthetic-new',(Path(folder)/'config.json').read_text())
            self.assertEqual(config['stt']['providers']['openai']['api_key'],'synthetic-new')


if __name__=='__main__':unittest.main()
