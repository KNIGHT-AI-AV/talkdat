from __future__ import annotations

import unittest

import tkinter as tk

from knight_flow.ui import scrollable_region
from tests import gui_offscreen  # noqa: F401  (X-164: never show on a real screen)
from tests.tk_support import acquire_root, probe_error as _ROOT_ERROR, release_root


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class ScrollableRegionTests(unittest.TestCase):
    """The local model list ran off the bottom of the window with no way back.

    Measured before this existed: 53 widgets and 1526 pixels past the bottom of
    an 800 pixel window. No scrollbar, no wheel binding, and no resize border
    either, because utility windows are overrideredirect. Everything below
    "Whisper Large v3" -- its Download button included -- could only be reached
    by finding the 22 pixel grip in the corner and dragging the window taller
    than the screen.

    These run against a bare Tk root rather than the settings window. Proving
    it through settings meant building that window a third time in one test
    class, which was slow enough that an unrelated HTTP test started timing
    out five seconds in -- a Tk problem wearing a networking costume.
    """

    def setUp(self) -> None:
        self.root = acquire_root()
        self.root.geometry("400x200")
        self.addCleanup(self._destroy)
        self.holder, self.content = scrollable_region(self.root, "#101010")
        self.holder.pack(fill="both", expand=True)
        for index in range(40):
            tk.Label(self.content, text=f"row {index}", bg="#101010", fg="#ffffff").pack(fill="x")
        self.root.update()

    def _destroy(self) -> None:
        release_root(self.root)

    def canvas(self) -> tk.Canvas:
        found = [c for c in self.holder.winfo_children() if isinstance(c, tk.Canvas)]
        self.assertTrue(found, "no canvas in the region")
        return found[0]

    def test_content_taller_than_the_view_becomes_scrollable(self) -> None:
        canvas = self.canvas()
        region = str(canvas.cget("scrollregion")).split()
        self.assertEqual(len(region), 4, "no scrollregion was set")
        height = int(float(region[3])) - int(float(region[1]))
        self.assertGreater(
            height, canvas.winfo_height(),
            "the fixture fits in the view, so it cannot prove anything about scrolling",
        )

    def test_the_region_actually_moves(self) -> None:
        canvas = self.canvas()
        start = canvas.yview()[0]
        canvas.yview_scroll(5, "units")
        self.root.update()
        self.assertGreater(canvas.yview()[0], start)

    def test_it_shows_a_scrollbar(self) -> None:
        """A region that scrolls silently gives no sign that it can."""
        bars = [c for c in self.holder.winfo_children() if c.winfo_class() in ("Scrollbar", "TScrollbar")]
        self.assertTrue(bars, "scrolling with no scrollbar is invisible")

    def test_the_wheel_survives_the_canvas_being_destroyed(self) -> None:
        """The binding lives on the toplevel, so the canvas can die first.

        Scrolling a destroyed widget raises inside a Tk event handler, where
        the only outlet is the background error handler -- once per wheel
        event. That produced a run of "bgerror failed to handle background
        error" and destabilised the whole test process.
        """
        self.holder.destroy()
        self.root.update()
        event = tk.Event()
        event.widget = self.root
        event.delta = 120
        # Reaching the handler through the binding table is what a real wheel
        # event does, and it must not raise now that the canvas is gone.
        self.root.event_generate("<MouseWheel>", delta=120, x=10, y=10)
        self.root.update()

    def test_the_wheel_ignores_widgets_outside_the_region(self) -> None:
        """Tk delivers the wheel to the widget under the pointer and does not
        walk up to ancestors, so the binding sits on the toplevel and has to
        decide for itself whether the pointer is inside. Without that check a
        wheel anywhere in the window scrolls this panel."""
        canvas = self.canvas()
        outside = tk.Label(self.root, text="not in the region")
        outside.pack()
        self.root.update()
        start = canvas.yview()[0]
        outside.event_generate("<MouseWheel>", delta=-120, x=1, y=1)
        self.root.update()
        self.assertEqual(canvas.yview()[0], start, "a wheel outside the region scrolled it")


if __name__ == "__main__":
    unittest.main()
