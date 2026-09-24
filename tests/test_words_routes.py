import unittest
from tests import test_web_shell_app

class WordsRoutesTests(unittest.TestCase):
    def test_words_tool_stays_in_the_shared_shell(self):
        app, shell = test_web_shell_app.AppShellTests().make_shell()
        self.assertEqual(shell.backend.handle('action', {'name':'words'}), {'page':'words'})
        app.overlay.open_add_words.assert_not_called()

    def test_words_menu_opens_the_same_page(self):
        app, shell = test_web_shell_app.AppShellTests().make_shell()
        app.overlay._context_menu_access_rows.return_value.append(('add_words','Words & Phrases','Personal spellings',None))
        shell.backend.actions = shell._actions()
        shell.backend.handle('action', {'name':'menu:add_words'})
        shell.settings_controller.open.assert_called_once_with('words')
        app.overlay._activate_context_menu_action.assert_not_called()

if __name__ == '__main__': unittest.main()
