from __future__ import annotations

import threading
import time
import sys
import unittest
from unittest.mock import MagicMock, patch

from knight_flow import single_instance
from knight_flow.wake import WakeWordListener


class _LaggingListener(WakeWordListener):
    """A listener whose worker takes a moment to wind down after stop().

    The real worker polls the stop event every 0.25s and only then leaves its
    audio stream, so it stays alive for a short window after stop() returns.
    That window is where the restart race lives, so the fake reproduces it
    rather than exiting instantly.
    """

    teardown_seconds = 0.15

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.worker_started = threading.Event()
        self.worker_runs = 0

    def _run(self) -> None:
        self.worker_runs += 1
        self.worker_started.set()
        while not self._stop_event.is_set():
            time.sleep(0.005)
        time.sleep(self.teardown_seconds)


class WakeWordListenerLifecycleTests(unittest.TestCase):
    def _listener(self) -> _LaggingListener:
        listener = _LaggingListener({}, on_wake=lambda: None, on_status=lambda _message: None)
        self.addCleanup(listener.stop)
        return listener

    def test_a_new_listener_is_not_running(self) -> None:
        self.assertFalse(self._listener().running)

    def test_start_runs_the_worker(self) -> None:
        listener = self._listener()

        listener.start()

        self.assertTrue(listener.worker_started.wait(2.0))
        self.assertTrue(listener.running)

    def test_start_is_idempotent_while_already_running(self) -> None:
        listener = self._listener()
        listener.start()
        self.assertTrue(listener.worker_started.wait(2.0))

        listener.start()

        self.assertEqual(listener.worker_runs, 1)

    def test_stop_ends_the_worker(self) -> None:
        listener = self._listener()
        listener.start()
        self.assertTrue(listener.worker_started.wait(2.0))

        listener.stop()
        time.sleep(listener.teardown_seconds + 0.3)

        self.assertFalse(listener.running)

    def test_start_immediately_after_stop_leaves_the_listener_running(self) -> None:
        """Toggling the setting off and straight back on must leave it listening.

        stop() only sets the event; the worker is still alive for a moment
        afterwards. A start() landing in that window used to see running=True
        and return early, so the outgoing worker exited and nothing replaced
        it -- the user toggled the feature back on and silently got nothing.
        """
        listener = self._listener()
        listener.start()
        self.assertTrue(listener.worker_started.wait(2.0))

        listener.stop()
        listener.start()  # lands while the outgoing worker is still winding down
        time.sleep(listener.teardown_seconds + 0.3)

        self.assertTrue(listener.running)
        self.assertEqual(listener.worker_runs, 2)


def _fake_ctypes(handle: object, last_error: int) -> MagicMock:
    fake = MagicMock()
    fake.WinDLL.return_value.CreateMutexW.return_value = handle
    fake.get_last_error.return_value = last_error
    return fake


class SingleInstanceTests(unittest.TestCase):
    def setUp(self) -> None:
        single_instance._mutex_handle = None
        self.addCleanup(setattr, single_instance, "_mutex_handle", None)

    def test_never_reports_a_duplicate_off_windows(self) -> None:
        with patch("knight_flow.single_instance.sys.platform", "linux"):
            self.assertFalse(single_instance.already_running())

    @unittest.skipUnless(sys.platform == "darwin", "exercises the macOS NSAlert path; on Windows the duplicate notice is a normal modal message box in the exiting process")

    def test_the_duplicate_notice_never_blocks(self) -> None:
        """The second instance has to reach the `return` after this call.

        An NSAlert here hung every duplicate launch. The app is LSUIElement, so
        the second process is not the active application and its modal alert
        appeared with no focus; `runModal` then waited for a dismissal of
        something nobody could see, and the process stayed alive holding a
        second copy of the model in memory.
        """
        finished: list[bool] = []

        def call() -> None:
            single_instance.show_already_running_message()
            finished.append(True)

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(timeout=10)
        self.assertTrue(finished, "show_already_running_message did not return within 10s")

    def test_reports_a_duplicate_when_the_mutex_already_exists(self) -> None:
        fake = _fake_ctypes(handle=1234, last_error=single_instance.ERROR_ALREADY_EXISTS)

        with patch("knight_flow.single_instance.sys.platform", "win32"), \
             patch("knight_flow.single_instance.ctypes", fake):
            self.assertTrue(single_instance.already_running())

        # The duplicate must not hold the mutex open, or the first instance
        # would never be able to release it.
        fake.WinDLL.return_value.CloseHandle.assert_called_once_with(1234)
        self.assertIsNone(single_instance._mutex_handle)

    def test_first_instance_keeps_the_handle_alive(self) -> None:
        fake = _fake_ctypes(handle=4321, last_error=0)

        with patch("knight_flow.single_instance.sys.platform", "win32"), \
             patch("knight_flow.single_instance.ctypes", fake):
            self.assertFalse(single_instance.already_running())

        # Dropping the handle would release the mutex and let a second copy start.
        self.assertEqual(single_instance._mutex_handle, 4321)
        fake.WinDLL.return_value.CloseHandle.assert_not_called()

    def test_a_failed_mutex_does_not_block_startup(self) -> None:
        fake = _fake_ctypes(handle=None, last_error=5)

        with patch("knight_flow.single_instance.sys.platform", "win32"), \
             patch("knight_flow.single_instance.ctypes", fake):
            self.assertFalse(single_instance.already_running())

        self.assertIsNone(single_instance._mutex_handle)

    def test_the_message_box_is_skipped_off_windows(self) -> None:
        with patch("knight_flow.single_instance.sys.platform", "linux"), \
             patch("knight_flow.single_instance.ctypes") as fake:
            single_instance.show_already_running_message()

        fake.windll.user32.MessageBoxW.assert_not_called()


if __name__ == "__main__":
    unittest.main()
