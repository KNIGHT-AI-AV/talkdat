import unittest
from tests import test_web_shell_app


class TranslationWorkspaceRoutesTests(unittest.TestCase):
    def test_translation_tool_opens_the_shared_page(self):
        app, shell = test_web_shell_app.AppShellTests().make_shell()
        self.assertEqual(shell.backend.handle('action', {'name':'translation'}), {'page':'translation'})
        app.overlay.open_translation.assert_not_called()

    def test_translation_menu_opens_the_same_page(self):
        app, shell = test_web_shell_app.AppShellTests().make_shell()
        app.overlay._context_menu_access_rows.return_value.append(('translation','Translate','Translate a passage',None))
        shell.backend.actions = shell._actions()
        shell.backend.handle('action', {'name':'menu:translation'})
        shell.settings_controller.open.assert_called_once_with('translation')
        app.overlay._activate_context_menu_action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
