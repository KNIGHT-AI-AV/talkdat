"""Application entry points must honor the new shell's existing-action contract."""
import unittest
from unittest.mock import Mock
from knight_flow.app import TalkDatApp as App
from knight_flow.overlay import Overlay


class AppWebShellTests(unittest.TestCase):
    def test_quit_waits_for_the_settings_draft_before_touching_capture(self):
        app = object.__new__(App)
        app.web_shell = Mock()
        app.web_shell.confirm_exit.return_value = True
        app.quit()
        app.web_shell.confirm_exit.assert_called_once()

    def test_restart_waits_before_launching_another_process(self):
        app = object.__new__(App)
        app.web_shell = Mock()
        app.web_shell.confirm_exit.return_value = True
        app.restart()
        app.web_shell.confirm_exit.assert_called_once()

    def test_settings_deep_link_reaches_the_web_shell(self):
        overlay = object.__new__(Overlay)
        overlay.force_visible = Mock()
        callback = Mock(return_value=True)
        overlay.callbacks = {'web_settings': callback}
        overlay._settings_initial_page = ('Speech', 'Local models')
        overlay.open_settings()
        callback.assert_called_once_with(('Speech', 'Local models'))
        self.assertIsNone(overlay._settings_initial_page)


if __name__ == '__main__':
    unittest.main()
