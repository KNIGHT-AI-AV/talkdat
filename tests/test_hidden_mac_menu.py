"""Mac prewarming must never activate the user's background renderer."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from knight_flow.web_shell import shell_host

class MacActivationTests(unittest.TestCase):
    def test_hidden_menu_start_prohibits_application_activation(self):
        app=Mock()
        view=SimpleNamespace(app=app)
        webview=MagicMock()
        modules={'webview':webview,'webview.platforms.cocoa':SimpleNamespace(BrowserView=view)}
        with patch.dict(sys.modules,modules),patch.object(shell_host.sys,'platform','darwin'),patch.object(shell_host,'_install_mac_policy'),patch.object(shell_host.threading,'Thread'):
            shell_host._run_window(Mock(),'<html></html>','menu',hidden=True,mode='menu')
        app.setActivationPolicy_.assert_called_once_with(2)

    def test_explicit_open_restores_activation_on_the_mac_ui_thread(self):
        api=shell_host._RendererApi(Mock(),mode='menu')
        api._window=Mock()
        app=Mock()
        queued=[]
        modules={'webview.platforms.cocoa':SimpleNamespace(BrowserView=SimpleNamespace(app=app)),
                 'PyObjCTools':SimpleNamespace(AppHelper=SimpleNamespace(callAfter=lambda fn:queued.append(fn)))}
        with patch.dict(sys.modules,modules),patch.object(shell_host.sys,'platform','darwin'):
            api._show()
            app.setActivationPolicy_.assert_not_called()
            api._window.show.assert_not_called()
            self.assertEqual(len(queued),1)
            queued.pop()()
        app.setActivationPolicy_.assert_called_once_with(1)
        api._window.show.assert_called_once_with()

if __name__=='__main__':unittest.main()
