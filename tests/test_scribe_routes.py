import unittest
from unittest.mock import Mock
from knight_flow.overlay import Overlay
from tests import test_web_shell_app


class ScribeRoutesTests(unittest.TestCase):
    def test_scribe_action_opens_shared_page_without_recording(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        self.assertEqual(shell.backend.handle('action',{'name':'scribe'}),{'page':'scribe'})
    def test_scribe_menu_opens_the_same_page(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        shell.backend.handle('action',{'name':'menu:scribe'})
        shell.settings_controller.open.assert_called_once_with('scribe');app.overlay._activate_context_menu_action.assert_not_called()
    def test_scribe_is_discoverable_under_writing(self):
        app,shell=test_web_shell_app.AppShellTests().make_shell()
        self.assertIn('scribe',{p['id'] for p in shell.backend.snapshot()['pages']})
    def test_native_pill_menu_opens_shared_review_before_recording(self):
        overlay=Overlay.__new__(Overlay);overlay.context_menu_target_hwnd=None;overlay._close_context_menu=Mock()
        shared=Mock(return_value=True);capture=Mock();overlay.callbacks={'web_settings':shared,'scribe_toggle':capture}
        overlay._activate_context_menu_action('scribe');shared.assert_called_once_with('scribe');capture.assert_not_called()
    def test_unavailable_renderer_retains_existing_capture_fallback(self):
        overlay=Overlay.__new__(Overlay);overlay.context_menu_target_hwnd=None;overlay._close_context_menu=Mock()
        capture=Mock();overlay.callbacks={'web_settings':Mock(return_value=False),'scribe_toggle':capture}
        overlay._activate_context_menu_action('scribe');capture.assert_called_once()
