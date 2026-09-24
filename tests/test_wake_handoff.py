import unittest
from unittest.mock import Mock
from tests import test_wake_runtime as runtime_tests


class WakeHandoffTests(unittest.TestCase):
    def setUp(self):
        fixture = runtime_tests.WakeRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.app, self.runtime, self.listeners = (
            fixture.app,
            fixture.runtime,
            fixture.listeners,
        )
        self.runtime.refresh()
        self.listener = self.listeners[0]
        self.listener.stop = Mock()

    def poll_handoff(self):
        delay, callback = self.app.overlay.root.after.call_args.args
        self.assertEqual(delay, 50)
        callback()

    def test_explicit_capture_waits_for_confirmed_close(self):
        begin = Mock()
        self.assertTrue(self.runtime.handoff(begin))
        begin.assert_not_called()
        self.listener.stop.assert_called()
        self.listener.closed.set()
        self.poll_handoff()
        begin.assert_called_once()

    def test_release_during_handoff_cancels_the_deferred_take(self):
        begin = Mock()
        self.runtime.handoff(begin)
        self.assertTrue(self.runtime.cancel_handoff())
        self.listener.closed.set()
        self.poll_handoff()
        begin.assert_not_called()

    def test_poll_cannot_restart_wake_while_capture_is_waiting(self):
        self.runtime.handoff(Mock())
        self.listener.running = False
        self.listener.closed.set()
        self.runtime.refresh()
        self.assertEqual(self.listener.starts, 1)

    def test_repeated_press_does_not_queue_two_captures(self):
        first, second = Mock(), Mock()
        self.runtime.handoff(first)
        self.runtime.handoff(second)
        self.listener.closed.set()
        self.poll_handoff()
        first.assert_called_once()
        second.assert_not_called()

    def test_panic_cancels_waiting_capture(self):
        begin = Mock()
        self.runtime.handoff(begin)
        self.runtime.suspend()
        self.listener.closed.set()
        self.poll_handoff()
        begin.assert_not_called()

    def test_close_deadline_refuses_capture(self):
        begin = Mock()
        self.runtime.handoff(begin)
        self.runtime.capture_deadline = 0
        self.poll_handoff()
        begin.assert_not_called()
        self.assertIsNone(self.runtime.capture_pending)
        self.assertIn("still closing", self.app.overlay.set_state.call_args.args[1])

    def test_closed_or_preparing_listener_does_not_delay_capture(self):
        self.listener.closed.set()
        self.assertFalse(self.runtime.handoff(Mock()))
        self.listener.stop.assert_called_once()

    def test_queued_detection_cannot_be_erased_by_poll_restart(self):
        self.listener.running = False
        self.listener.closed.set()
        self.listener.phase = "detected"
        self.runtime.refresh()
        self.assertEqual(self.listener.starts, 1)
        self.runtime._wake(self.listener, self.listener.generation)
        self.app.toggle_hands_free.assert_called_once()

    def test_ignored_detection_can_resume_after_other_capture_finishes(self):
        self.listener.running = False
        self.listener.closed.set()
        self.listener.phase = "detected"
        self.app.session = object()
        self.runtime._wake(self.listener, self.listener.generation)
        self.app.session = None
        self.runtime.refresh()
        self.assertEqual(self.listener.starts, 2)
