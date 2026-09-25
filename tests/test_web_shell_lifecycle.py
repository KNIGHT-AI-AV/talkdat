"""The renderer must not silently drop a draft when the application exits."""
import threading
import unittest
from unittest.mock import Mock, patch

from knight_flow.web_shell.shell_host import ShellController, _RendererApi


class ShellLifecycleTests(unittest.TestCase):
    def test_native_close_checks_js_draft_even_if_dirty_notice_is_still_in_flight(self):
        api = _RendererApi(Mock())
        api._window = Mock()
        api._ready.set()
        api._dirty = False
        with patch('knight_flow.web_shell.shell_host.threading.Thread'):
            self.assertFalse(api._closing())

    def controller(self):
        callbacks = []
        controller = ShellController('.', callbacks.append, Mock())
        controller.process = Mock()
        controller.process.is_alive.return_value = True
        controller.connection = Mock()
        return controller, callbacks

    def test_quit_waits_for_the_matching_renderer_confirmation(self):
        controller, callbacks = self.controller()
        done = Mock()
        with patch('knight_flow.web_shell.shell_host._send') as send:
            self.assertTrue(controller.confirm_close(done))
            token = send.call_args.args[2]['token']
            self.assertFalse(controller.accept_event({'event': 'close_confirmed', 'token': 'unrelated'}))
            self.assertEqual(callbacks, [])
            self.assertTrue(controller.accept_event({'event': 'close_confirmed', 'token': token}))
            self.assertEqual(len(callbacks), 1)
            callbacks.pop()()
            done.assert_called_once_with()

    def test_cancelled_quit_cannot_replay_a_later_confirmation(self):
        controller, callbacks = self.controller()
        with patch('knight_flow.web_shell.shell_host._send') as send:
            controller.confirm_close(Mock())
            token = send.call_args.args[2]['token']
            controller.accept_event({'event': 'close_cancelled', 'token': token})
            self.assertFalse(controller.accept_event({'event': 'close_confirmed', 'token': token}))
            self.assertEqual(callbacks, [])

    def test_dead_renderer_does_not_hold_the_app_open(self):
        controller, callbacks = self.controller()
        controller.process.is_alive.return_value = False
        self.assertFalse(controller.confirm_close(Mock()))
        self.assertEqual(callbacks, [])

    def test_duplicate_quit_reuses_the_pending_request(self):
        controller, _ = self.controller()
        with patch('knight_flow.web_shell.shell_host._send') as send:
            controller.confirm_close(Mock())
            controller.confirm_close(Mock())
            self.assertEqual(send.call_count, 1)

    def test_renderer_cancel_reports_only_the_current_native_request(self):
        api = _RendererApi(Mock())
        api._window = Mock()
        api._window.get_current_url.return_value = 'about:blank'
        api._guard_ready = True
        api._close_token = 'current'
        with patch('knight_flow.web_shell.shell_host._send') as send:
            self.assertTrue(api.request('cancel_close', {})['ok'])
            self.assertEqual(send.call_args.args[2], {'event': 'close_cancelled', 'token': 'current'})
            self.assertIsNone(api._close_token)

    def test_menu_dismiss_hides_without_destroying_the_warm_renderer(self):
        api = _RendererApi(Mock(), mode='menu')
        api._window = Mock()
        api._window.get_current_url.return_value = 'about:blank'
        api._guard_ready = True
        # X-682: the menu plays its exit first, then the host hides the window
        # (hiding at once cut every close to a single frame).
        timers = []

        class _Timer:
            def __init__(self, delay, fn):
                self.delay, self.fn, self.daemon = delay, fn, False
                timers.append(self)

            def start(self):
                pass

        with patch('knight_flow.web_shell.shell_host.threading.Timer', _Timer):
            self.assertTrue(api.request('dismiss', {})['ok'])
        api._window.hide.assert_not_called()
        self.assertEqual(len(timers), 1)
        self.assertGreater(timers[0].delay, 0)
        timers[0].fn()
        api._window.hide.assert_called_once_with()
        api._window.destroy.assert_not_called()


if __name__ == '__main__':
    unittest.main()
