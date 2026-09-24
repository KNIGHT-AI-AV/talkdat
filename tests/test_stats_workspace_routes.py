import unittest
from unittest.mock import Mock
from tests import test_web_shell_app
from knight_flow.app import TalkDatApp


class StatsWorkspaceRoutesTests(unittest.TestCase):
    def test_stats_tool_opens_the_shared_page(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        self.assertEqual(shell.backend.handle('action',{'name':'stats'}),{'page':'stats'})
        app.overlay.open_stats.assert_not_called()
    def test_stats_menu_opens_the_same_page(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        app.overlay._context_menu_access_rows.return_value.append(('stats','Stats','Activity',None))
        shell.backend.actions=shell._actions()
        shell.backend.handle('action',{'name':'menu:stats'})
        shell.settings_controller.open.assert_called_once_with('stats')
        app.overlay._activate_context_menu_action.assert_not_called()
    def test_app_stats_entrypoint_uses_the_shared_shell(self):
        app=TalkDatApp.__new__(TalkDatApp);app.web_shell=Mock();app.overlay=Mock()
        app.web_shell.open_settings.return_value=True
        app.open_stats()
        app.web_shell.open_settings.assert_called_once_with('stats')
        app.overlay.root.after.assert_not_called()


if __name__=='__main__':unittest.main()
