"""X-538: a scrolling view must not call a scrollbar that has been destroyed.

Seen in the founder's own log on 2026-09-08, twice inside two seconds, and
eight times since 2026-08-05:

    ERROR knight_flow.overlay: unhandled exception in a Tk callback
    Traceback (most recent call last):
      File "tkinter\\__init__.py", line 2074, in __call__
      File "tkinter\\__init__.py", line 3749, in set
    _tkinter.TclError: invalid command name ".!toplevel10.!frame5.!scrollbar"

Line 3749 is ``Scrollbar.set``. The link that calls it is configured on the
*view* -- ``canvas.configure(yscrollcommand=bar.set)`` -- so it outlives the
scrollbar. Destroy the bar while the canvas is still alive and the next
geometry event inside that canvas invokes a Tcl command that no longer exists.

``scrollable.py`` already guards the opposite direction: its wheel handler asks
``canvas.winfo_exists()`` because the canvas can die before the toplevel-level
binding does. This is the same hazard pointing the other way, and it was not
guarded.

Why only Settings sees it. Every other window is torn down by one
``window.destroy()``, where Tk deletes the subtree itself and no half-destroyed
state is ever observable. Settings is large enough (>= 220 widgets) to take
``_retire_toplevel_in_slices``, which deletes leaves in small batches with real
frames in between -- so a scrollbar and the canvas that points at it are
genuinely alive at different times. The planner's own docstring already records
this hazard for *timers* ("made parent timers target already-deleted
scrollbars") and cancels those; the scroll-command link was left connected.
"""

from __future__ import annotations

import inspect
import tkinter as tk
import unittest
from tkinter import ttk

try:
    _probe = tk.Tk()
    _probe.destroy()
    _ROOT_ERROR: Exception | None = None
except Exception as error:  # no display, or Tk not built in
    _ROOT_ERROR = error

from tests import gui_offscreen  # noqa: F401  (X-164: never show on a real screen)


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class SeveringScrollLinksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.geometry("300x200")
        self.addCleanup(self._destroy_root)
        self.frame = tk.Frame(self.root)
        self.frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.frame, width=200, height=100)
        self.bar = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")
        # Content taller than the view, or yview_moveto has nothing to report
        # and the link is never exercised.
        self.canvas.create_rectangle(0, 0, 180, 900, fill="#202020")
        self.canvas.configure(scrollregion=(0, 0, 180, 900))
        self.root.update()

    def _destroy_root(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass

    def _scroll_and_collect_background_errors(self) -> list[str]:
        """Scroll the canvas and return whatever reached Tk's error handler.

        ``yview_moveto`` does NOT propagate this failure to its caller: Tk
        defers the scroll notification, so it runs inside ``CallWrapper``
        (tkinter line 2074, exactly as in the founder's traceback) and the only
        outlet is ``report_callback_exception``. Asserting on a raise at the
        call site therefore reports "no defect" against a machine that is
        producing the error twice a second.
        """
        seen: list[str] = []
        self.root.report_callback_exception = (  # type: ignore[method-assign]
            lambda exc_type, exc_value, exc_tb: seen.append(f"{exc_type.__name__}: {exc_value}")
        )
        self.canvas.yview_moveto(0.5)
        self.root.update()
        self.root.update_idletasks()
        return seen

    def test_the_defect_is_real_when_the_link_is_left_connected(self) -> None:
        """The witness. Without severing, this is the founder's traceback.

        Kept as a test rather than a comment so that if some future Tk stops
        producing it, the guard below is known to be protecting nothing.
        """
        self.bar.destroy()
        errors = self._scroll_and_collect_background_errors()
        self.assertTrue(errors, "the defect no longer reproduces; the guard may be moot")
        self.assertTrue(
            all("invalid command name" in error for error in errors),
            f"expected the dead-scrollbar error, got {errors}",
        )

    def test_a_severed_view_survives_losing_its_scrollbar(self) -> None:
        from knight_flow.ui.scrollable import sever_scroll_links

        sever_scroll_links([self.root, self.frame, self.canvas, self.bar])
        self.bar.destroy()
        self.assertEqual(self._scroll_and_collect_background_errors(), [])
        # Severing must not disable scrolling itself, only the notification.
        self.assertGreater(self.canvas.yview()[0], 0.0)

    def test_severing_also_releases_the_scrollbar_side_of_the_pair(self) -> None:
        """The bar's ``command`` points at the canvas, so a dragged bar fails
        the same way when the canvas dies first -- which slicing also allows.

        A drag cannot be synthesized reliably here (a synthesized ButtonPress
        on ttk is dropped on macOS -- see aqua-drops-synthesized-buttonpress),
        so this pins the released option rather than the drag.
        """
        from knight_flow.ui.scrollable import sever_scroll_links

        self.assertNotEqual(str(self.bar.cget("command")), "")
        sever_scroll_links([self.frame, self.canvas, self.bar])
        self.assertEqual(str(self.bar.cget("command")), "")

    def test_severing_ignores_widgets_that_cannot_scroll(self) -> None:
        from knight_flow.ui.scrollable import sever_scroll_links

        label = tk.Label(self.frame, text="not a scroller")
        # Returns the number of links it actually cut, so a silent no-op in a
        # future refactor is visible rather than merely unproven.
        self.assertEqual(sever_scroll_links([label]), 0)
        self.assertEqual(sever_scroll_links([self.canvas, self.bar]), 2)

    def test_severing_never_raises_on_an_already_destroyed_widget(self) -> None:
        from knight_flow.ui.scrollable import sever_scroll_links

        self.bar.destroy()
        sever_scroll_links([self.canvas, self.bar])


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class TheSlicePlannerSeversBeforeItDestroysTests(unittest.TestCase):
    """Wiring, executed rather than asserted about in prose.

    The planner is driven for real against a >= 220 widget Toplevel, bound to a
    stub carrying only the four Overlay attributes it touches. Building a whole
    Overlay here would drag in its PhotoImages and the default-root conflict
    that ``test_gui_regressions`` exists to avoid.
    """

    def setUp(self) -> None:
        self.root = tk.Tk()
        self.addCleanup(self._destroy_root)

    def _destroy_root(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_the_planner_severs_the_tree_it_is_about_to_slice(self) -> None:
        from knight_flow import overlay as overlay_module
        from knight_flow.overlay import Overlay

        window = tk.Toplevel(self.root)
        frame = tk.Frame(window)
        frame.pack()
        canvas = tk.Canvas(frame, width=100, height=60)
        bar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack()
        bar.pack()
        # The planner takes the atomic path below 220 widgets, which is the
        # safe one and not what this pins.
        for index in range(230):
            tk.Label(frame, text=str(index))
        self.root.update()

        class _StubOverlay:
            _root_destroyed = False
            _shell_window = None
            _toplevel_widget_tree = Overlay._toplevel_widget_tree
            _cancel_toplevel_owned_callbacks = Overlay._cancel_toplevel_owned_callbacks
            _retire_toplevel_in_slices = Overlay._retire_toplevel_in_slices

            def __init__(self, root: tk.Misc) -> None:
                self.root = root

        seen: list[list[tk.Misc]] = []
        original = overlay_module.sever_scroll_links

        def recording(widgets):  # type: ignore[no-untyped-def]
            seen.append(list(widgets))
            return original(widgets)

        overlay_module.sever_scroll_links = recording  # type: ignore[assignment]
        try:
            _StubOverlay(self.root)._retire_toplevel_in_slices(window)
        finally:
            overlay_module.sever_scroll_links = original  # type: ignore[assignment]

        self.assertTrue(seen, "the slice planner never severed the scroll links")
        severed = seen[0]
        self.assertIn(canvas, severed)
        self.assertIn(bar, severed)
        self.assertEqual(str(canvas.cget("yscrollcommand")), "")

    def test_the_severing_happens_before_the_first_destroy(self) -> None:
        """Order is the whole guarantee. Severing after a batch has already run
        would leave exactly the window in which the founder's error fired."""
        source = inspect.getsource(
            __import__("knight_flow.overlay", fromlist=["Overlay"]).Overlay._retire_toplevel_in_slices
        )
        sever_at = source.find("sever_scroll_links(")
        destroy_at = source.find("widget.destroy()")
        self.assertGreater(sever_at, -1, "the planner no longer severs scroll links")
        self.assertGreater(destroy_at, -1, "the planner no longer destroys widgets")
        self.assertLess(sever_at, destroy_at, "severing must precede the first destroy")


if __name__ == "__main__":
    unittest.main()
