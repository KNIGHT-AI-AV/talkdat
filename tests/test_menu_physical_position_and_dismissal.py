"""Native menu placement and click-away do not depend on DOM focus."""
import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from knight_flow.web_shell.shell_host import _RendererApi, _position_menu_window


class NativeMenuTests(unittest.TestCase):
    def api(self, mode="menu", visible=True):
        api = _RendererApi(Mock(), mode=mode)
        api._window = SimpleNamespace(native=SimpleNamespace(Visible=visible))
        api._hide_menu_after_exit = Mock()
        return api

    def test_native_focus_loss_dismisses_even_without_dom_blur(self):
        api = self.api()
        api._native_menu_deactivated()
        api._hide_menu_after_exit.assert_called_once()

    def test_hidden_menu_and_settings_do_not_start_dismissal(self):
        for api in (self.api(visible=False), self.api(mode="settings")):
            api._native_menu_deactivated()
            api._hide_menu_after_exit.assert_not_called()

    def test_physical_negative_bounds_are_applied_inside_per_monitor_context(self):
        events = []
        context = Mock(side_effect=lambda value: events.append(("context", getattr(value, "value", value))) or 123)
        position = Mock(side_effect=lambda *args: events.append(("position", args)) or 1)
        user32 = SimpleNamespace(SetThreadDpiAwarenessContext=context, SetWindowPos=position)
        bounds = [-2310, 170, 456, 828]
        _position_menu_window(4242, bounds, user32=user32)
        self.assertEqual(events, [("context", ctypes.c_void_p(-4).value),
                                  ("position", (4242, None, *bounds, 0x0014)), ("context", 123)])

    def test_failed_position_restores_the_calling_threads_context(self):
        context = Mock(return_value=123)
        user32 = SimpleNamespace(SetThreadDpiAwarenessContext=context, SetWindowPos=Mock(return_value=0))
        with self.assertRaises(OSError):
            _position_menu_window(4242, [0, 0, 304, 552], user32=user32)
        self.assertEqual(context.call_args.args, (123,))


if __name__ == "__main__":
    unittest.main()
