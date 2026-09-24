from __future__ import annotations

import threading
import time
import unittest

from knight_flow import main_thread


class PostingFromAnyThreadTests(unittest.TestCase):
    """The queue itself, with no Tk involved."""

    def tearDown(self) -> None:
        main_thread.stop()
        while True:
            try:
                main_thread._queue.get_nowait()
            except Exception:
                break

    def test_a_posted_callback_is_not_run_by_the_posting_thread(self) -> None:
        """post() must never execute anything itself.

        If it ran the callback inline as a fallback, the crash it exists to
        prevent would come straight back -- the callback is UI work, and the
        posting thread is precisely the thread that must not do UI work.
        """
        ran_on: list[str] = []
        done = threading.Event()

        def worker() -> None:
            main_thread.post(lambda: ran_on.append(threading.current_thread().name))
            done.set()

        thread = threading.Thread(target=worker, name="poster")
        thread.start()
        done.wait(5)
        thread.join(5)
        self.assertEqual(ran_on, [], "post() executed the callback on the calling thread")

    def test_on_main_thread_is_honest(self) -> None:
        self.assertTrue(main_thread.on_main_thread())
        answers: list[bool] = []
        thread = threading.Thread(target=lambda: answers.append(main_thread.on_main_thread()))
        thread.start()
        thread.join(5)
        self.assertEqual(answers, [False])


class TkIsNeverTouchedFromAWorkerTests(unittest.TestCase):
    """The actual defect, reproduced and then held closed.

    tkinter's Misc.after runs tk.createcommand and tk.call on the calling
    thread. From a worker that corrupts the saved Python thread state, and the
    process aborts later on the main thread inside an unrelated callback:

        PyEval_RestoreThread <- PythonCmd <- TclNRRunCallbacks <- Tk_BindEvent

    21 of 25 crash reports on this Mac had that signature, about one every
    fifteen minutes from the moment the app was installed. None of them named
    the thread that caused it, because by the time it aborts that thread is
    long gone.
    """

    def setUp(self) -> None:
        from tests.tk_support import acquire_root, probe_error

        if probe_error is not None:
            self.skipTest(f"no usable Tk display: {probe_error}")
        self.root = acquire_root()
        self.calls: list[str] = []
        real = self.root.tk

        class Recorder:
            def __getattr__(inner, name):
                attribute = getattr(real, name)
                if not callable(attribute) or name.startswith("_"):
                    return attribute

                def wrapped(*args, **kwargs):
                    if threading.current_thread() is not threading.main_thread():
                        self.calls.append(f"{name} from {threading.current_thread().name}")
                    return attribute(*args, **kwargs)

                return wrapped

        self.recorder = Recorder()

    def tearDown(self) -> None:
        from tests.tk_support import release_root

        main_thread.stop()
        release_root(self.root)

    def test_after_from_a_worker_does_not_reach_the_interpreter(self) -> None:
        main_thread.bind(self.root)
        self.root.tk = self.recorder
        done = threading.Event()

        def worker() -> None:
            try:
                self.root.after(0, lambda: None)
            finally:
                done.set()

        thread = threading.Thread(target=worker, name="TalkDatWorker")
        thread.start()
        done.wait(5)
        thread.join(5)
        self.assertEqual(
            self.calls,
            [],
            "a worker thread reached the Tcl interpreter; this is what aborts the process",
        )

    def test_the_callback_still_runs_and_runs_on_the_main_thread(self) -> None:
        """Safety is worthless if the work silently stops happening.

        A worker posting a status update must still see it appear -- otherwise
        the fix trades a crash for every cross-thread message being dropped,
        which is harder to notice and nearly as bad.
        """
        main_thread.bind(self.root)
        ran_on: list[str] = []
        done = threading.Event()

        def worker() -> None:
            self.root.after(0, lambda: ran_on.append(threading.current_thread().name))
            done.set()

        thread = threading.Thread(target=worker, name="TalkDatWorker")
        thread.start()
        done.wait(5)
        thread.join(5)

        deadline = time.time() + 5
        while not ran_on and time.time() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertEqual(ran_on, [threading.main_thread().name])

    def test_a_failing_posted_callback_does_not_stop_the_pump(self) -> None:
        """A stopped pump drops every later cross-thread update, silently."""
        main_thread.bind(self.root)
        ran: list[str] = []

        def explode() -> None:
            raise RuntimeError("posted callback blew up")

        main_thread.post(explode)
        main_thread.post(lambda: ran.append("after the failure"))

        deadline = time.time() + 5
        while not ran and time.time() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertEqual(ran, ["after the failure"])

    def test_main_thread_after_keeps_a_real_cancellable_timer(self) -> None:
        """Scheduling from the main thread must be untouched.

        Debounces, the hover fade and the resize repaint all depend on
        after/after_cancel behaving exactly as tkinter's own does.
        """
        main_thread.bind(self.root)
        fired: list[int] = []
        identifier = self.root.after(50, lambda: fired.append(1))
        self.assertNotEqual(identifier, main_thread.CROSS_THREAD_TOKEN)
        self.root.after_cancel(identifier)
        deadline = time.time() + 0.4
        while time.time() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertEqual(fired, [], "a cancelled main-thread timer still fired")

    def test_binding_twice_does_not_stack_wrappers(self) -> None:
        """Tests build many overlays against one shared root, because macOS
        cannot create a second root at all. Rebinding has to be harmless."""
        main_thread.bind(self.root)
        first = self.root.after
        main_thread.bind(self.root)
        self.assertIs(self.root.after, first)


class EveryOverlayGetsTheProtectionTests(unittest.TestCase):
    """Installed where the root is made, so nothing can opt out by accident."""

    def test_the_overlay_binds_the_root_it_creates(self) -> None:
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        # The root-creation line moved when the Pill became a Toplevel on
        # macOS; anchor on the piece that cannot move -- the real root's
        # assignment.
        index = source.index("_real_root = self._supplied_root")
        self.assertIn("main_thread.bind(self.root)", source[index:index + 2400])


if __name__ == "__main__":
    unittest.main()
