"""Focused real-Tk scheduler contracts for ``FlowPageStack``.

The fixture uses three empty native frames.  It verifies generation ownership,
layout-signature stabilization, and predecessor visibility without paying the
cost or inheriting the behavior of the full Settings tree.
"""

from __future__ import annotations

import sys
import time
import unittest

if sys.platform == "win32":
    from tests import gui_offscreen  # noqa: F401

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]

from knight_flow.overlay import FlowPageStack


def pump(root, seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.005)


@unittest.skipIf(tk is None, "tkinter unavailable")
class FlowPageStackSchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = tk.Tk()
        cls.root.geometry("360x220+20+20")
        cls.root.update()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:
            pass
        try:
            tk._default_root = None  # type: ignore[attr-defined]
        except Exception:
            pass

    def setUp(self) -> None:
        self.stack = FlowPageStack(self.root, width=320, height=180)
        self.stack.pack(fill="both", expand=True)
        self.pages = {
            name: ttk.Frame(self.stack, width=320, height=180)
            for name in ("A", "B", "C")
        }
        for name, page in self.pages.items():
            self.stack.add(page, text=name)
        self.root.update()

        # The first page's initial presentation event was delivered before this
        # binding.  Every receipt below therefore belongs to an audited switch.
        self.events: list[str] = []
        self.stack.bind(
            "<<NotebookTabChanged>>",
            lambda _event: self.events.append(
                str(self.stack.tab(self.stack.select(), "text"))
            ),
            add="+",
        )
        self.assertIs(self.stack._visible, self.pages["A"])
        self.assertTrue(self.pages["A"].winfo_ismapped())

    def tearDown(self) -> None:
        try:
            self.stack.destroy()
        except Exception:
            pass
        self.root.update()

    def _wait_until(self, predicate, *, timeout: float = 1.1, message: str) -> None:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.005)
        raise AssertionError(message)

    def test_none_then_stable_verified_signature_commits_before_fallback(self) -> None:
        a = self.pages["A"]
        b = self.pages["B"]
        signatures = iter(
            (
                None,
                ("layout", 1),
                ("layout", 2),
                ("layout", 2),
            )
        )
        observed: list[object | None] = []

        def probe():
            try:
                value = next(signatures)
            except StopIteration:
                value = ("layout", 2)
            observed.append(value)
            return value

        self.stack.register_layout_probe(b, probe)
        started = time.perf_counter()
        self.stack.select(b)

        self.assertIs(self.stack._selected, b)
        self.assertIs(self.stack._visible, a)
        self.assertTrue(a.winfo_ismapped())
        self.assertEqual(self.events, [])

        self._wait_until(
            lambda: self.stack._visible is b and self.events == ["B"],
            message="the verified B layout did not commit before fallback",
        )
        elapsed = time.perf_counter() - started

        self.assertEqual(
            observed[:4],
            [None, ("layout", 1), ("layout", 2), ("layout", 2)],
            "the stack committed without two matching non-None signatures",
        )
        self.assertLess(elapsed, 1.1, "the healthy page waited for the 1200 ms fallback")
        self.assertIsNone(self.stack._transition)
        self.assertIsNone(self.stack._switch_confirm_after)
        self.assertIsNone(self.stack._switch_fallback_after)
        self.assertTrue(b.winfo_ismapped())
        self.assertFalse(a.winfo_ismapped())

    def test_rapid_b_then_c_keeps_a_until_only_c_commits(self) -> None:
        a = self.pages["A"]
        b = self.pages["B"]
        c = self.pages["C"]
        c_ready = {"value": False}

        self.stack.register_layout_probe(b, lambda: None)
        self.stack.register_layout_probe(
            c,
            lambda: ("C", 320, 180) if c_ready["value"] else None,
        )

        self.stack.select(b)
        pump(self.root, 0.05)
        self.assertIs(self.stack._selected, b)
        self.assertIs(self.stack._visible, a)
        self.assertTrue(a.winfo_ismapped())
        self.assertEqual(self.events, [])

        self.stack.select(c)
        pump(self.root, 0.06)
        self.assertIs(self.stack._selected, c)
        self.assertIs(self.stack._visible, a)
        self.assertTrue(a.winfo_ismapped())
        self.assertFalse(b.winfo_ismapped())
        self.assertEqual(c.winfo_manager(), "place")
        self.assertEqual(self.events, [])

        # Until C reports a stable layout, A remains the complete visible page.
        c_ready["value"] = True
        deadline = time.perf_counter() + 1.1
        while self.stack._visible is not c and time.perf_counter() < deadline:
            self.assertIs(self.stack._visible, a)
            self.assertTrue(a.winfo_ismapped())
            self.assertNotIn("B", self.events)
            self.root.update()
            time.sleep(0.005)

        self.assertIs(self.stack._visible, c)
        self._wait_until(
            lambda: self.events == ["C"],
            message="C committed without its one settled tab event",
        )
        self.assertFalse(a.winfo_ismapped())
        self.assertFalse(b.winfo_ismapped())
        self.assertTrue(c.winfo_ismapped())

        # Run past B's original fallback deadline. A cancelled generation must
        # never present B or emit a stale event later.
        pump(self.root, 1.25)
        self.assertIs(self.stack._visible, c)
        self.assertEqual(self.events, ["C"])
        self.assertFalse(b.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
