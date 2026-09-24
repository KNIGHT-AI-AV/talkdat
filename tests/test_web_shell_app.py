import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import sys
from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.shell_app import AppShell


class AppShellTests(unittest.TestCase):
    def make_shell(self):
        overlay = Mock()
        overlay._settings_palette = object.__new__(Overlay)._settings_palette
        overlay._context_menu_access_rows.return_value = [('paste_last','Paste last transcript','Insert in your app',None),('quit_app','Close app','Close Talk DAT',None)]
        overlay._context_menu_rows.return_value = overlay._context_menu_access_rows.return_value
        overlay._context_menu_feature_rows.return_value = [('ramble','Ramble','Long speech',None)]
        overlay._context_menu_default_rows.return_value = overlay._context_menu_rows.return_value
        overlay.MENU_SAFETY_ZONE_ACTIONS = Overlay.MENU_SAFETY_ZONE_ACTIONS
        overlay._logical_work_area.return_value = (0,0,900,700)
        overlay._foreground_target_window.return_value = 123
        app = Mock()
        app.config = copy.deepcopy(DEFAULT_CONFIG)
        app.overlay = overlay
        app._cross_thread_calls = Mock()
        shell = AppShell(app, assets=Path(__file__).resolve().parents[1]/'knight_flow/web_shell/shell_assets', controller_factory=lambda *args, **kwargs: Mock())
        return app, shell

    @patch('knight_flow.web_shell.shell_app.sys.platform', 'win32')
    @patch.object(AppShell, '_target_is_shell', return_value=False)
    def test_menu_preserves_original_paste_target_and_clamps_to_monitor(self, _target_check):
        app, shell = self.make_shell()
        shell.open_menu(890,690)
        self.assertEqual(app.overlay.context_menu_target_hwnd,123)
        bounds=shell.menu_controller.open.call_args.kwargs['bounds']
        x,y,width,height=bounds
        self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
        self.assertLessEqual(x+width,900);self.assertLessEqual(y+height,700)
        shell.backend.handle('action',{'name':'menu:paste_last'})
        app.overlay._activate_context_menu_action.assert_called_once_with('paste_last')

    def test_mac_paste_restores_the_external_application(self):
        app, shell = self.make_shell()
        target = Mock()
        target.activateWithOptions_.return_value = True
        shell._mac_paste_target = target
        with patch('knight_flow.web_shell.shell_app.sys.platform', 'darwin'):
            shell.backend.handle('action', {'name':'menu:paste_last'})
        target.activateWithOptions_.assert_called_once_with(0)
        app.overlay._activate_context_menu_action.assert_called_once_with('paste_last')

    def test_mac_paste_copies_if_the_external_application_cannot_return(self):
        app, shell = self.make_shell()
        target = Mock()
        target.activateWithOptions_.return_value = False
        shell._mac_paste_target = target
        app.overlay.callbacks = {'copy_last': Mock()}
        with patch('knight_flow.web_shell.shell_app.sys.platform', 'darwin'):
            shell.backend.handle('action', {'name':'menu:paste_last'})
        app.overlay.callbacks['copy_last'].assert_called_once_with()
        app.overlay._activate_context_menu_action.assert_not_called()

    def test_atomic_save_applies_runtime_without_a_second_disk_write(self):
        app,shell=self.make_shell()
        with patch('knight_flow.web_shell.shell_app.save_config') as persist,patch('knight_flow.brand_font.apply_app_family'),patch('knight_flow.net_fence.set_local_only') as fence:
            shell.backend.handle('save',{'revision':shell.backend.snapshot()['revision'],'changes':{'cleanup.max_ai_format_ms':1600}})
            persist.assert_called_once()
            app.save_settings.assert_called_once_with(persist=False)
            app.overlay.apply_runtime_config.assert_called_once()
            fence.assert_called_once_with(True)

    def test_features_remain_a_disclosure_with_real_destinations(self):
        app, shell = self.make_shell()
        app.overlay._context_menu_rows.return_value.insert(1, ('more_features','Features','Occasional tools',None))
        menu = shell.backend.snapshot()['menu']
        features = next(row for row in menu if row.get('id') == 'more_features')
        self.assertEqual(features['children'][0]['action'], 'menu:ramble')
        self.assertNotIn('menu:more_features', shell.backend.actions)
        self.assertTrue(next(row for row in menu if row['id'] == 'quit_app')['fixed'])

    def test_windows_paste_without_an_external_target_copies_instead(self):
        app, shell = self.make_shell()
        app.overlay.context_menu_target_hwnd = 0
        app.overlay.callbacks = {'copy_last': Mock()}
        with patch('knight_flow.web_shell.shell_app.sys.platform', 'win32'):
            shell.backend.handle('action', {'name':'menu:paste_last'})
        app.overlay.callbacks['copy_last'].assert_called_once_with()
        app.overlay._activate_context_menu_action.assert_not_called()

    def test_only_settings_draft_can_defer_application_exit(self):
        app,shell=self.make_shell()
        done=Mock()
        shell.settings_controller.confirm_close.return_value=True
        self.assertTrue(shell.confirm_exit(done))
        shell.settings_controller.confirm_close.assert_called_once_with(done)
        shell.menu_controller.confirm_close.assert_not_called()

    def test_every_web_menu_page_opens_the_settings_host_directly(self):
        app, shell = self.make_shell()
        for identifier, page in {'settings':'general', 'history':'history', 'stats':'stats',
                                 'scratchpad':'scratchpad', 'add_words':'words', 'translation':'translation',
                                 'ramble':'ramble', 'scribe':'scribe', 'local_models':'models',
                                 'help':'help', 'formatting':'formatting'}.items():
            with self.subTest(action=identifier):
                shell.backend.handle('action', {'name':'menu:'+identifier})
                shell.settings_controller.open.assert_called_with(page)
        app.overlay._activate_context_menu_action.assert_not_called()

    def test_unavailable_settings_destination_reports_failure(self):
        app, shell = self.make_shell()
        shell.settings_controller.open.side_effect = OSError('Synthetic launch error')
        with self.assertRaisesRegex(ValueError, 'could not open'):
            shell.backend.handle('action', {'name':'menu:settings'})

    def test_menu_formatting_uses_atomic_save_and_returns_updated_state(self):
        app, shell = self.make_shell()
        with patch.object(shell, '_applied'), patch('knight_flow.web_shell.shell_app.save_config') as persist:
            before=app.config['cleanup']['format_intensity']
            result=shell.backend.handle('action', {'name':'menu:toggle_intensity'})
            persist.assert_called_once()
            self.assertNotEqual(app.config['cleanup']['format_intensity'],before)
            self.assertEqual(result['state']['intensity'],app.config['cleanup']['format_intensity'])
        app.overlay._activate_context_menu_action.assert_not_called()


if __name__=='__main__':unittest.main()
