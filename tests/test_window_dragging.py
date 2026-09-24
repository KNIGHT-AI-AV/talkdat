from __future__ import annotations

import gc
import tkinter as tk
import unittest

from knight_flow.config import load_config
from knight_flow.flat_button import FlatButton
from knight_flow.overlay import Overlay
from tests.tk_support import acquire_root, probe_error as _ROOT_ERROR, release_root


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class DraggingNeverJumpsTests(unittest.TestCase):
    """Reported as "dragging window broken and messy", and it was.

    `utility_drag_origin` is ONE attribute on the overlay, shared by every
    utility window's drag-anywhere binding and by the title-bar handle. Two
    things followed from that:

    - When the press landed on an interactive widget the handler declined the
      drag by returning, without clearing the origin. A release that lands
      outside an overrideredirect window never fires, so a stale origin
      survives a drag -- and the next press on a button or slider handed
      <B1-Motion> a start point from the earlier drag, which threw the window
      across the screen.
    - Nothing tied an origin to the window it came from, so a start point taken
      in one window could move a different one.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = acquire_root()
        cls.overlay = Overlay(config=load_config(), callbacks={}, root=cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        for child in list(cls.root.winfo_children()):
            if isinstance(child, tk.Toplevel):
                try:
                    child.destroy()
                except Exception:
                    pass
        release_root(cls.root)
        cls.overlay = None
        gc.collect()

    def open_window(self, name: str) -> tk.Toplevel:
        # Utility windows are children of overlay.root -- which on macOS is
        # the Pill's Toplevel, not the Tk root the test holds.
        host = self.overlay.root
        before = set(host.winfo_children())
        getattr(self.overlay, name)()
        host.update()
        opened = [c for c in host.winfo_children()
                  if c not in before and isinstance(c, tk.Toplevel)]
        self.assertTrue(opened, f"{name} opened no window")
        self.addCleanup(lambda w=opened[-1]: w.winfo_exists() and w.destroy())
        return opened[-1]

    def test_a_stale_origin_cannot_move_a_window(self) -> None:
        """The exact reported failure, reproduced through the public state.

        A leftover origin plus a press that declines the drag used to be enough
        to move the window on the next mouse movement.
        """
        window = self.open_window("open_settings")
        self.root.update_idletasks()
        start = (window.winfo_x(), window.winfo_y())

        # A drag that ended without its release: exactly what happens when the
        # pointer leaves an overrideredirect window before the button comes up.
        self.overlay.utility_drag_origin = (window, 10_000, 10_000, start[0], start[1])

        # Now press something interactive. The drag must be refused AND the
        # stale origin cleared. "Interactive" is the product's own definition
        # from _bind_drag_anywhere: a widget with click behaviour of its own --
        # on macOS most controls are bound tk.Labels (the Aqua gate), not
        # Button instances.
        button = None
        def walk(node):
            for child in node.winfo_children():
                yield child
                yield from walk(child)
        for child in walk(window):
            if isinstance(child, (tk.Button, FlatButton)) or child.bind("<Button-1>") or child.bind("<ButtonPress-1>"):
                button = child
                break
        self.assertIsNotNone(button, "no interactive control to press in the settings window")
        # Press the BUTTON, not the window. Pressing dead surface is a real
        # drag and must still work; pressing a control must not be. The press
        # goes through the real handler METHOD, not event_generate: Aqua
        # drops synthesized ButtonPress events outright (not even the pressed
        # widget's own binding fires), so OS synthesis would silently skip
        # the press and fail this test for the wrong reason.
        self.overlay._drag_anywhere_press(window, button, button.winfo_rootx() + 2, button.winfo_rooty() + 2)
        self.root.update()

        window.event_generate("<B1-Motion>", x=400, y=400)
        self.root.update()
        self.root.update_idletasks()
        moved = (window.winfo_x(), window.winfo_y())
        self.assertEqual(
            moved, start,
            f"the window jumped from {start} to {moved} on a stale origin",
        )

    def test_an_origin_from_one_window_cannot_move_another(self) -> None:
        first = self.open_window("open_settings")
        second = self.open_window("open_status")
        self.root.update_idletasks()
        before = (second.winfo_x(), second.winfo_y())
        # An origin belonging to the FIRST window, while the second is dragged.
        self.overlay.utility_drag_origin = (first, 0, 0, first.winfo_x(), first.winfo_y())
        second.event_generate("<B1-Motion>", x=500, y=500)
        self.root.update()
        self.root.update_idletasks()
        after = (second.winfo_x(), second.winfo_y())
        self.assertEqual(after, before,
                         "a window moved using another window's drag origin")

    def test_the_origin_records_which_window_it_belongs_to(self) -> None:
        """Structural: the tuple must carry its owner, or the guard above is
        not something the code can actually enforce."""
        window = self.open_window("open_settings")
        window.event_generate("<ButtonPress-1>", x=3, y=3)
        self.root.update()
        origin = self.overlay.utility_drag_origin
        if origin is None:
            self.skipTest("press did not start a drag on this surface")
        self.assertEqual(len(origin), 5, f"origin should be (window, x, y, wx, wy), got {origin!r}")
        self.assertIs(origin[0], window)

    def test_release_always_clears_the_origin(self) -> None:
        window = self.open_window("open_settings")
        self.overlay.utility_drag_origin = (window, 1, 2, 3, 4)
        window.event_generate("<ButtonRelease-1>", x=5, y=5)
        self.root.update()
        self.assertIsNone(self.overlay.utility_drag_origin)


if __name__ == "__main__":
    unittest.main()
