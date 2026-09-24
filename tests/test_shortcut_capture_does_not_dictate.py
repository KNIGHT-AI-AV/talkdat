import unittest
from unittest.mock import Mock, patch
from knight_flow.hotkeys import HotkeyController


class ShortcutCaptureTests(unittest.TestCase):
    def controller(self):
        return HotkeyController({'hands_free':[['ctrl','space']], 'push_to_talk':[['ctrl']]}, {})

    def test_recording_a_shortcut_cannot_start_a_capture(self):
        controller = self.controller()
        controller._trigger = Mock()
        controller.record_shortcut(True)
        controller.pressed = {'ctrl','space'}
        controller._evaluate_press()
        controller._trigger.assert_not_called()
        self.assertIsNone(controller.pending_hold)

    def test_abandoned_renderer_lease_expires_and_shortcuts_work_again(self):
        controller = self.controller()
        controller._trigger = Mock()
        with patch('knight_flow.hotkeys.time.monotonic', return_value=100):
            controller.record_shortcut(True)
        with patch('knight_flow.hotkeys.time.monotonic', return_value=116):
            controller.pressed = {'ctrl','space'}
            controller._evaluate_press()
        controller._trigger.assert_called_once_with('hands_free')

    def test_capture_does_not_interrupt_an_existing_hold(self):
        controller = self.controller()
        controller.active_hold = 'push_to_talk'
        with self.assertRaises(ValueError):
            controller.record_shortcut(True)
        self.assertEqual(controller.active_hold,'push_to_talk')

    def test_panic_remains_available_if_another_surface_starts_recording(self):
        controller = self.controller()
        controller.hotkeys['panic'] = [{'ctrl','shift','esc'}]
        controller._trigger = Mock()
        controller.record_shortcut(True)
        controller.pressed = {'ctrl','shift','esc'}
        controller._evaluate_press()
        controller._trigger.assert_called_once_with('panic')
