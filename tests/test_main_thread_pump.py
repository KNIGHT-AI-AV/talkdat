from __future__ import annotations

import time
import tkinter as tk
import unittest

from knight_flow import main_thread
from tests import gui_offscreen  # noqa: F401  (X-164: never show on a real screen)


class PumpDoesNotLeakTclCommandsTests(unittest.TestCase):
    """X-141, the founder's "why is Talk DAT! using 12% CPU": every pump pass
    registered a brand-new Tcl command for _drain and never deleted it, so
    root._tclCommands grew ~40 entries a second forever, and tkinter cleans
    every expired after-callback with a LINEAR remove() over that list. One
    full core, growing with uptime. The pump must reuse ONE registered
    command no matter how many times it arms."""

    def test_a_thousand_pump_passes_register_one_command(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        try:
            root.withdraw()
            main_thread.bind(root)
            before = len(root._tclCommands or [])
            for _ in range(1000):
                # Cancel the armed timer, then arm again: the exact cycle the
                # live pump performs every POLL_MS.
                if main_thread._pump is not None:
                    try:
                        root.tk.call("after", "cancel", main_thread._pump)
                    except tk.TclError:
                        pass
                main_thread._schedule_pump()
            after = len(root._tclCommands or [])
            self.assertLessEqual(
                after - before,
                1,
                f"pump passes leaked {after - before} Tcl commands; the drain "
                "command must be registered once and reused",
            )
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass

    def test_rebinding_one_root_never_arms_duplicate_pumps(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        try:
            root.withdraw()
            for _ in range(20):
                main_thread.bind(root)
            drain_command = main_thread._drain_command
            self.assertIsNotNone(drain_command)
            armed = tuple(root.tk.call("after", "info"))
            matching = [
                receipt
                for receipt in armed
                if drain_command in str(root.tk.call("after", "info", receipt))
            ]
            self.assertEqual(matching, [main_thread._pump])
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass

    def test_destroy_cancels_the_pump_before_tk_retires_its_command(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        root.withdraw()
        main_thread.bind(root)
        pump = main_thread._pump
        drain_command = main_thread._drain_command
        self.assertIsNotNone(pump)
        self.assertIsNotNone(drain_command)

        root.destroy()

        # ``destroy .`` leaves the Tcl interpreter available for inspection.
        # There must be no after-script left to call the now-deleted command.
        self.assertNotIn(pump, tuple(root.tk.call("after", "info")))
        self.assertEqual(str(root.tk.call("info", "commands", drain_command)), "")
        self.assertIsNone(main_thread._root)
        self.assertIsNone(main_thread._pump)
        self.assertIsNone(main_thread._drain_command)

    def test_posted_callbacks_keep_draining_across_rearms(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        try:
            root.withdraw()
            main_thread.bind(root)
            delivered: list[str] = []

            for marker in ("first", "second"):
                main_thread.post(lambda value=marker: delivered.append(value))
                deadline = time.monotonic() + 1.0
                while marker not in delivered and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.005)

            self.assertEqual(delivered, ["first", "second"])
            self.assertIsNotNone(main_thread._pump)
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass

    def test_switching_roots_retires_the_old_interpreter_first(self) -> None:
        roots: list[tk.Tk] = []
        try:
            for _ in range(2):
                root = tk.Tk()
                root.withdraw()
                roots.append(root)
        except tk.TclError:
            for root in roots:
                try:
                    root.destroy()
                except tk.TclError:
                    pass
            self.skipTest("no display")

        first, second = roots
        try:
            main_thread.bind(first)
            first_pump = main_thread._pump
            first_command = main_thread._drain_command
            main_thread.bind(second)

            self.assertNotIn(first_pump, tuple(first.tk.call("after", "info")))
            self.assertEqual(str(first.tk.call("info", "commands", first_command)), "")
            self.assertIs(main_thread._root, second)
            self.assertIsNotNone(main_thread._pump)
        finally:
            for root in roots:
                try:
                    root.destroy()
                except tk.TclError:
                    pass


if __name__ == "__main__":
    unittest.main()
