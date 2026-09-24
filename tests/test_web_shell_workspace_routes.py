"""Document tools should remain in the shared native shell."""
import unittest
from tests import test_web_shell_app


class WorkspaceRouteTests(unittest.TestCase):
    def test_tools_open_the_shared_document_pages(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        for name in ('history','scratchpad','recovery'):
            with self.subTest(name=name):
                result=shell.backend.handle('action',{'name':name})
                self.assertEqual(result,{'page':name})
        app.overlay.open_history.assert_not_called()
        app.overlay.open_scratchpad.assert_not_called()

    def test_menu_enters_the_same_shared_workspaces(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        for name in ('history','scratchpad'):
            with self.subTest(name=name):
                shell.backend.handle('action',{'name':'menu:'+name})
                shell.settings_controller.open.assert_called_with(name)
        app.overlay._activate_context_menu_action.assert_not_called()

if __name__=='__main__':unittest.main()
