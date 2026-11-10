import copy,threading,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from knight_flow.overlay import Overlay
from tests import test_web_shell_app


class SetupRoutesTests(unittest.TestCase):
    def test_help_opens_shared_setup(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        self.assertEqual(shell.backend.handle('action',{'name':'getting_started'}),{'page':'setup'})
        app.overlay.open_onboarding.assert_not_called()
    def test_setup_is_discoverable(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        self.assertIn('setup',{p['id'] for p in shell.backend.snapshot()['pages']})
    def test_first_run_and_legacy_menu_entry_use_shared_setup(self):
        overlay=object.__new__(Overlay);callback=Mock(return_value=True);overlay.callbacks={'web_settings':callback}
        overlay.open_onboarding();callback.assert_called_once_with('setup')
    def test_native_setup_is_retained_as_fallback(self):
        overlay=object.__new__(Overlay);overlay.callbacks={'web_settings':Mock(return_value=False)}
        with patch('knight_flow.overlay.open_onboarding_wizard') as native:
            overlay.open_onboarding();native.assert_called_once_with(overlay)
    def test_workspace_saves_through_existing_setup_transaction(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        app.save_onboarding_settings=Mock(return_value={'saved':True,'runtime_refreshed':True})
        app.lock=threading.RLock();app.session_token=None
        app.hotkeys=SimpleNamespace(lock=threading.RLock(),_shortcut_recording_until=0)
        call=lambda **p:shell.backend.handle('workspace',{'area':'setup',**p})
        state=call(operation='state')
        result=call(operation='chapter',revision=state['revision'],value='voice')
        self.assertEqual(result['chapter'],'voice');app.save_onboarding_settings.assert_called_once()
    def test_shared_settings_keep_local_only_privacy_in_force(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        app.config.setdefault('privacy',{})['local_only']=True
        app.config['stt']['route_mode']='byok'
        with patch('knight_flow.brand_font.apply_app_family'),patch('knight_flow.net_fence.set_local_only') as fence:
            shell._applied()
        fence.assert_called_once_with(True)
    def test_a_legacy_route_keeps_the_fence_the_way_route_mode_reads_it(self):
        # X-480: route_mode() reads a saved "auto", or a "cloud" with no key, as Local, so the save keeps the fence up
        # for them with Local-only off, the rule the launch and the Pill's switch apply. It compared the raw string.
        for legacy in ('auto','cloud'):
            with self.subTest(route_mode=legacy):
                app,shell=test_web_shell_app.AppShellTests().make_shell()
                app.config.setdefault('privacy',{})['local_only']=False
                app.config['stt']['route_mode']=legacy
                with patch('knight_flow.brand_font.apply_app_family'),patch('knight_flow.net_fence.set_local_only') as fence:
                    shell._applied()
                fence.assert_called_once_with(True)
    def test_with_local_only_off_your_key_still_lowers_the_fence(self):
        # The control: the own-key route with Local-only off is not fenced, before the fix and after it.
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        app.config.setdefault('privacy',{})['local_only']=False
        app.config['stt']['route_mode']='byok'
        with patch('knight_flow.brand_font.apply_app_family'),patch('knight_flow.net_fence.set_local_only') as fence:
            shell._applied()
        fence.assert_called_once_with(False)
    def test_the_tk_setup_save_for_older_hosts_reads_the_route_through_route_mode(self):
        # LIST-0476: ui/onboarding.py's save for a host without the onboarding_save transaction compared the raw
        # route string, so a legacy "auto" (or a "cloud" with no key) with Local-only off lowered the fence.
        from knight_flow.ui.onboarding import OnboardingWizard
        for saved,expected in (('auto',True),('cloud',True),('local',True),('byok',False)):
            with self.subTest(route_mode=saved):
                wizard=object.__new__(OnboardingWizard)
                wizard.config={'privacy':{'local_only':False},'stt':{'route_mode':'local'}}
                wizard.host=SimpleNamespace(callbacks={'save_settings':Mock()},apply_runtime_config=Mock())
                wizard.status_var=Mock()
                with patch('knight_flow.net_fence.set_local_only') as fence:
                    self.assertTrue(wizard._save_setup({'privacy':{'local_only':False},'stt':{'route_mode':saved}}))
                fence.assert_called_once_with(expected)
                wizard.host.callbacks['save_settings'].assert_called_once_with()


if __name__=='__main__':unittest.main()
