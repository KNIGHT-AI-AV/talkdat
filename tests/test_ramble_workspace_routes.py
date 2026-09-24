import unittest
from tests import test_web_shell_app


class RambleWorkspaceRoutesTests(unittest.TestCase):
    def test_ramble_tool_opens_the_shared_page(self):
        app, shell = test_web_shell_app.AppShellTests().make_shell()
        self.assertEqual(shell.backend.handle('action', {'name':'ramble'}), {'page':'ramble'})
        app.start_ramble.assert_not_called()

    def test_ramble_menu_opens_the_same_page(self):
        app, shell = test_web_shell_app.AppShellTests().make_shell()
        app.overlay._context_menu_access_rows.return_value.append(('ramble','Ramble','Longer recording',None))
        shell.backend.actions = shell._actions()
        shell.backend.handle('action', {'name':'menu:ramble'})
        shell.settings_controller.open.assert_called_once_with('ramble')
        app.overlay._activate_context_menu_action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
