"""Real-Tk proofs for monitor-safe transient and resize geometry.

The four synthetic work areas exercise the coordinate arrangements Windows
actually reports: primary, a monitor to the right, one to the left (negative
X), and one above (negative Y).  Windows are transparent through
``gui_offscreen``; measurements and bindings remain real.
"""

from __future__ import annotations

from knight_flow import mac_support

import os
import tempfile
import time
import unittest
from unittest import mock

from tests import gui_offscreen  # noqa: F401
from knight_flow.flat_button import FlatButton  # tk.Button off macOS, a styled Label on it

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - tkinter missing entirely
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]


WORK_AREAS = {
    "primary": (0, 0, 1920, 1040),
    "right": (1920, 40, 3840, 1080),
    "negative_left": (-1920, 0, 0, 1040),
    "negative_above": (0, -1080, 1920, -40),
}


def pump(root: tk.Misc, seconds: float = 0.08) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.005)


def descendants(widget: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    stack = list(widget.winfo_children())
    while stack:
        child = stack.pop()
        found.append(child)
        stack.extend(child.winfo_children())
    return found


def assert_inside(
    case: unittest.TestCase,
    window: tk.Misc,
    work_area: tuple[int, int, int, int],
    *,
    inset: int = 8,
) -> None:
    left, top, right, bottom = work_area
    x = int(window.winfo_rootx())
    y = int(window.winfo_rooty())
    width = int(window.winfo_width())
    height = int(window.winfo_height())
    case.assertGreaterEqual(x, left + inset)
    case.assertGreaterEqual(y, top + inset)
    case.assertLessEqual(x + width, right - inset)
    case.assertLessEqual(y + height, bottom - inset)


@unittest.skipIf(tk is None, "tkinter unavailable")
class RealMonitorGeometryContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_home = os.environ.get("TALK_DAT_HOME")
        cls._home = tempfile.TemporaryDirectory(prefix="talkdat-monitor-geometry-")
        os.environ["TALK_DAT_HOME"] = cls._home.name

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        cls.overlay = Overlay(load_config(), callbacks={})
        pump(cls.overlay.root, 0.15)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.overlay.root.destroy()
        except Exception:
            pass
        try:
            tk._default_root = None  # type: ignore[attr-defined]
        except Exception:
            pass
        if cls._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = cls._previous_home
        cls._home.cleanup()

    def _probe(self, rect: tuple[int, int, int, int], width: int = 640, height: int = 420) -> tk.Toplevel:
        left, top, right, bottom = rect
        x = left + (right - left - width) // 2
        y = top + (bottom - top - height) // 2
        probe = tk.Toplevel(self.overlay.root)
        probe.overrideredirect(True)
        probe.geometry(f"{width}x{height}+{x}+{y}")
        probe.update_idletasks()
        return probe

    def test_every_edge_and_corner_stays_inside_each_work_area(self) -> None:
        starts = {
            "n": (320, 1),
            "s": (320, 419),
            "w": (1, 210),
            "e": (639, 210),
            "nw": (1, 1),
            "ne": (639, 1),
            "sw": (1, 419),
            "se": (639, 419),
        }
        for monitor_name, rect in WORK_AREAS.items():
            left, top, right, bottom = rect
            for edge, (local_x, local_y) in starts.items():
                with self.subTest(monitor=monitor_name, edge=edge):
                    probe = self._probe(rect)
                    with mock.patch.object(self.overlay, "_window_monitor_work_area", return_value=rect):
                        self.overlay._bind_edge_resize(probe, 320, 220)
                        probe.event_generate(
                            "<ButtonPress-1>",
                            x=local_x,
                            y=local_y,
                            rootx=probe.winfo_rootx() + local_x,
                            rooty=probe.winfo_rooty() + local_y,
                            state=0x100,
                        )
                        target_x = left - 600 if "w" in edge else (right + 600 if "e" in edge else probe.winfo_rootx() + local_x)
                        target_y = top - 600 if "n" in edge else (bottom + 600 if "s" in edge else probe.winfo_rooty() + local_y)
                        probe.event_generate(
                            "<B1-Motion>",
                            x=local_x,
                            y=local_y,
                            rootx=target_x,
                            rooty=target_y,
                            state=0x100,
                        )
                        probe.event_generate(
                            "<ButtonRelease-1>",
                            x=local_x,
                            y=local_y,
                            rootx=target_x,
                            rooty=target_y,
                            state=0,
                        )
                        pump(self.overlay.root)
                    assert_inside(self, probe, rect)
                    self.assertGreaterEqual(probe.winfo_width(), 320)
                    self.assertGreaterEqual(probe.winfo_height(), 220)
                    probe.destroy()

    def test_shared_resize_grip_stays_inside_each_work_area(self) -> None:
        for monitor_name, rect in WORK_AREAS.items():
            with self.subTest(monitor=monitor_name):
                probe = self._probe(rect)
                with mock.patch.object(self.overlay, "_window_monitor_work_area", return_value=rect):
                    self.overlay._install_utility_resize_grip(
                        probe,
                        minimum_size=(320, 220),
                        bg="#101418",
                    )
                    pump(self.overlay.root)
                    grip = next(
                        child
                        for child in descendants(probe)
                        if isinstance(child, tk.Canvas) and str(child.cget("cursor")) == mac_support.RESIZE_CORNER_CURSOR
                    )
                    grip.event_generate(
                        "<ButtonPress-1>",
                        x=10,
                        y=10,
                        rootx=grip.winfo_rootx() + 10,
                        rooty=grip.winfo_rooty() + 10,
                        state=0x100,
                    )
                    grip.event_generate(
                        "<B1-Motion>",
                        x=10,
                        y=10,
                        rootx=rect[2] + 800,
                        rooty=rect[3] + 800,
                        state=0x100,
                    )
                    grip.event_generate("<ButtonRelease-1>", x=10, y=10, state=0)
                    pump(self.overlay.root)
                assert_inside(self, probe, rect)
                probe.destroy()

    def test_help_note_receipt_toast_and_history_more_stay_with_their_host_monitor(self) -> None:
        for monitor_name, rect in WORK_AREAS.items():
            with self.subTest(monitor=monitor_name):
                left, top, right, bottom = rect
                host = self._probe(rect, 520, 360)
                host.geometry(f"520x360+{right - 532}+{bottom - 372}")
                with (
                    mock.patch.object(self.overlay, "_window_monitor_work_area", return_value=rect),
                    mock.patch.object(self.overlay, "_pill_monitor_work_area", return_value=rect),
                ):
                    before = set(host.winfo_children())
                    self.overlay._open_help_note(host, "geometry proof")
                    pump(self.overlay.root)
                    note = next(
                        child
                        for child in host.winfo_children()
                        if child not in before and isinstance(child, tk.Toplevel)
                    )
                    assert_inside(self, note, rect)
                    note.destroy()

                    self.overlay.root.geometry(f"240x40+{left + 12}+{top + 12}")
                    pump(self.overlay.root)
                    with mock.patch("knight_flow.meeting_quiet.meeting_in_progress", return_value=False):
                        self.overlay.show_learned_word("Mayowa's production review " * 18, lambda: None)
                    pump(self.overlay.root)
                    receipt = next(
                        child
                        for child in self.overlay.root.winfo_children()
                        if isinstance(child, tk.Toplevel)
                        and any(isinstance(item, (tk.Button, FlatButton)) and str(item.cget("text")) == "Don't save" for item in descendants(child))
                    )
                    assert_inside(self, receipt, rect)
                    receipt.destroy()

                    self.overlay._show_toast_now(("The production review is ready for the photo shoot. " * 24).strip())
                    pump(self.overlay.root)
                    toast = self.overlay._toast_window
                    self.assertIsNotNone(toast)
                    assert_inside(self, toast, rect)
                    toast.destroy()
                    self.overlay._toast_window = None

                host.destroy()

                with (
                    mock.patch.object(self.overlay, "_window_monitor_work_area", return_value=rect),
                    mock.patch.object(self.overlay, "_pill_monitor_work_area", return_value=rect),
                ):
                    self.overlay.open_history()
                    pump(self.overlay.root, 0.2)
                    history = self.overlay.utility_windows["history"]
                    history.geometry(f"900x640+{right - 912}+{bottom - 652}")
                    pump(self.overlay.root)
                    more = next(
                        child
                        for child in descendants(history)
                        if isinstance(child, ttk.Button) and str(child.cget("text")) == "Export and clear..."
                    )
                    more.invoke()
                    pump(self.overlay.root)
                    popup = next(
                        child
                        for child in history.winfo_children()
                        if isinstance(child, tk.Toplevel)
                        and any(
                            isinstance(item, (tk.Button, FlatButton)) and str(item.cget("text")) == "Export Markdown"
                            for item in descendants(child)
                        )
                    )
                    assert_inside(self, popup, rect)
                    popup.destroy()
                    history.destroy()
                    self.overlay.utility_windows.pop("history", None)

    def test_ramble_saved_and_dragged_positions_are_monitor_contained(self) -> None:
        from knight_flow.monitors import Monitor

        monitors = [
            Monitor(left, top, right, bottom, left, top, right, bottom, name == "primary")
            for name, (left, top, right, bottom) in WORK_AREAS.items()
        ]
        for monitor_name, rect in WORK_AREAS.items():
            with self.subTest(monitor=monitor_name):
                left, top, right, bottom = rect
                self.overlay.config.setdefault("ui", {})["ramble_indicator_pos"] = f"{left + 12},{top + 12}"
                with (
                    mock.patch("knight_flow.overlay.list_monitors", return_value=monitors),
                    mock.patch.object(self.overlay, "_pill_monitor_work_area", return_value=rect),
                    mock.patch.object(self.overlay, "_window_monitor_work_area", return_value=rect),
                ):
                    self.overlay.show_ramble_indicator()
                    pump(self.overlay.root)
                    bar = self.overlay._ramble_indicator
                    assert_inside(self, bar, rect, inset=0)
                    canvas = next(child for child in descendants(bar) if isinstance(child, tk.Canvas))
                    canvas.event_generate(
                        "<ButtonPress-1>",
                        x=10,
                        y=10,
                        rootx=bar.winfo_rootx() + 10,
                        rooty=bar.winfo_rooty() + 10,
                        state=0x100,
                    )
                    canvas.event_generate(
                        "<B1-Motion>",
                        x=10,
                        y=10,
                        rootx=right + 900,
                        rooty=bottom + 900,
                        state=0x100,
                    )
                    canvas.event_generate("<ButtonRelease-1>", x=10, y=10, state=0)
                    pump(self.overlay.root)
                    assert_inside(self, bar, rect)
                    saved_x, saved_y = (
                        int(value)
                        for value in self.overlay.config["ui"]["ramble_indicator_pos"].split(",", 1)
                    )
                    self.assertEqual((saved_x, saved_y), (bar.winfo_x(), bar.winfo_y()))
                    self.overlay.hide_ramble_indicator()


if __name__ == "__main__":
    unittest.main()
