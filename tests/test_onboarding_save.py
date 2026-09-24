import copy,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch

from knight_flow.app import TalkDatApp
from knight_flow.config import DEFAULT_CONFIG


class OnboardingSaveTests(unittest.TestCase):
    def app(self):
        app=object.__new__(TalkDatApp);app.config=copy.deepcopy(DEFAULT_CONFIG)
        app.overlay=Mock();app.save_settings=Mock();return app

    def test_persistence_failure_keeps_live_settings_and_runtime_unchanged(self):
        app=self.app();original=copy.deepcopy(app.config);candidate=copy.deepcopy(original)
        candidate['onboarding'].update(completed=True,version=3)
        with patch('knight_flow.web_shell.shell_persistence.save_settings_config',side_effect=OSError('fixture disk failure')):
            with self.assertRaises(OSError):app.save_onboarding_settings(candidate)
        self.assertEqual(app.config,original);app.overlay.apply_runtime_config.assert_not_called();app.save_settings.assert_not_called()

    def test_success_applies_the_persisted_candidate_without_a_second_save(self):
        app=self.app();candidate=copy.deepcopy(app.config);candidate['audio']['input_device']='Fixture input'
        reference=app.config;written=[]
        def persist(value):
            self.assertEqual(app.config['audio']['input_device'],'');written.append(copy.deepcopy(value))
        with patch('knight_flow.web_shell.shell_persistence.save_settings_config',side_effect=persist),patch('knight_flow.net_fence.set_local_only') as fence:
            result=app.save_onboarding_settings(candidate)
        self.assertIs(app.config,reference);self.assertEqual(app.config,written[0]);self.assertEqual(candidate,written[0])
        app.save_settings.assert_called_once_with(persist=False);fence.assert_called_with(True)
        self.assertEqual(result,{'saved':True,'runtime_refreshed':True})

    def test_runtime_failure_does_not_discard_a_successful_save(self):
        app=self.app();candidate=copy.deepcopy(app.config);candidate['onboarding']['completed']=True
        app.save_settings.side_effect=RuntimeError('fixture runtime failure')
        with patch('knight_flow.web_shell.shell_persistence.save_settings_config'),patch('knight_flow.net_fence.set_local_only'):
            result=app.save_onboarding_settings(candidate)
        self.assertEqual(app.config,candidate);self.assertEqual(result,{'saved':True,'runtime_refreshed':False})

    def test_privacy_fence_follows_the_existing_local_only_setting(self):
        app=self.app();candidate=copy.deepcopy(app.config);candidate['stt']['route_mode']='byok'
        with patch('knight_flow.web_shell.shell_persistence.save_settings_config'),patch('knight_flow.net_fence.set_local_only') as fence:
            app.save_onboarding_settings(candidate)
        fence.assert_called_with(True);self.assertTrue(app.config['privacy']['local_only'])


if __name__=='__main__':unittest.main()
