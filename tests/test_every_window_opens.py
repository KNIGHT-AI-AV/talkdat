from __future__ import annotations

import unittest

import gc
import tkinter as tk

from knight_flow.config import load_config
from knight_flow.overlay import Overlay
from tests import gui_offscreen  # noqa: F401  (X-164: never show on a real screen)
from tests.tk_support import IS_MAC, acquire_root, probe_error as _ROOT_ERROR, release_root

# Every window the user can reach from the pill menu, the tray, or a button.
# open_feedback_form and open_update_window need arguments, so they are driven
# with representative ones rather than skipped.
NO_ARG_WINDOWS = (
    "open_account",
    "open_history",
    "open_local_models",
    "open_model_guide",
    "open_scratchpad",
    "open_settings",
    "open_stats",
    "open_status",
    "open_translation",
)


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class EveryWindowOpensTests(unittest.TestCase):
    """Opening any window must not raise.

    _utility_window calls overrideredirect(True), which removes the OS
    titlebar, before the window's own close button is built. So a failure
    partway through construction leaves a blank panel the user cannot close --
    and because Tk sends callback exceptions to stderr, which a --windowed
    PyInstaller build discards, it fails completely silently.

    That is exactly what shipped: tkinter.font.Font takes `root`, not `master`,
    and the bad keyword reached Tcl as `-master`. Every settings entry point
    opened blank and unclosable, with nothing in the log.
    """

    # On macOS one Overlay serves the whole class. Two reasons, both learned
    # here: the process cannot create a second Tk root without crashing, and
    # Overlay is not built to be instantiated repeatedly against one root --
    # each new instance re-registers bindings, images and the Tk exception
    # hook on a root that still carries the previous one's, and the fourth
    # construction took the interpreter down. Windows keeps a fresh overlay per
    # test, which is better isolated and costs nothing there.
    _class_overlay: Overlay | None = None

    @classmethod
    def setUpClass(cls) -> None:
        if IS_MAC and _ROOT_ERROR is None:
            cls._class_overlay = Overlay(
                config=load_config(), callbacks={}, root=acquire_root()
            )

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._class_overlay is not None:
            release_root(cls._class_overlay.root)
            cls._class_overlay = None
            gc.collect()

    def setUp(self) -> None:
        if IS_MAC:
            self.overlay = type(self)._class_overlay
            self.addCleanup(self._close_opened_windows)
            return
        self.overlay = Overlay(config=load_config(), callbacks={})
        self.addCleanup(self._destroy)

    def _close_opened_windows(self) -> None:
        """Leave the shared overlay with no windows open for the next test."""
        for child in list(self.overlay.root.winfo_children()):
            if isinstance(child, tk.Toplevel):
                try:
                    child.destroy()
                except Exception:
                    pass
        try:
            self.overlay.root.update()
        except Exception:
            pass

    def _destroy(self) -> None:
        release_root(self.overlay.root)
        self.overlay = None
        gc.collect()

    def test_every_window_opens_without_raising(self) -> None:
        failures: list[str] = []
        for name in NO_ARG_WINDOWS:
            opener = getattr(self.overlay, name, None)
            if not callable(opener):
                failures.append(f"{name}: missing")
                continue
            try:
                opener()
                self.overlay.root.update()
            except Exception as error:
                failures.append(f"{name}: {type(error).__name__}: {error}")
        self.assertEqual(failures, [], f"windows that fail to open: {failures}")

    def test_no_window_keeps_a_title_bar_it_never_displays(self) -> None:
        """A created-but-unmanaged title bar is invisible and permanent.

        _make_glass_titlebar packed the bar before anything checked whether the
        window could take a packed child. Tk refuses pack in a container that
        already has grid slaves, so the raise happened inside the helper and
        the caller's grid and place branches were unreachable from the day they
        were written. Settings, Account and Local Models each carried a Frame
        that was built, recorded on the window, and never shown.

        Nothing looked broken, because those three build their own header and
        Close button. The visible symptom was only a missing title -- and the
        handler that was supposed to report it referenced an undefined `log`,
        so it raised NameError into an after_idle callback, where a --windowed
        build has no stderr to print it to.
        """
        orphans: list[str] = []
        for name in NO_ARG_WINDOWS:
            before = set(self.overlay.root.winfo_children())
            getattr(self.overlay, name)()
            self.overlay.root.update()
            opened = [
                child for child in self.overlay.root.winfo_children()
                if child not in before and isinstance(child, tk.Toplevel)
            ]
            if not opened:
                continue
            window = opened[-1]
            bar = getattr(window, "_glass_titlebar", None)
            # No bar at all is a valid outcome: the window supplies its own.
            if bar is not None and bar.winfo_exists() and not bar.winfo_manager():
                orphans.append(name)
            window.destroy()
        self.assertEqual(orphans, [], f"windows with an invisible title bar: {orphans}")

    def test_the_feedback_form_opens_for_each_kind(self) -> None:
        for kind in ("feature", "bug"):
            with self.subTest(kind=kind):
                self.overlay.open_feedback_form(kind)
                self.overlay.root.update()

    def test_the_whats_new_window_opens(self) -> None:
        """Shown automatically after an update, so a failure here greets the
        user immediately after installing and looks like a broken upgrade."""
        self.overlay.open_whats_new(
            "0.4.8-beta",
            "0.4.9-beta",
            "Captures the last word on release.\nCloud transcription via OpenRouter.",
            "https://www.talkdat.app/",
        )
        self.overlay.root.update()

    def test_destroy_cancels_every_pending_tk_callback(self) -> None:
        """Closing the app must retire animation and utility-window timers.

        Tcl deletes the Python command behind an ``after`` callback when its
        window disappears, but the timer can remain queued.  When it later
        fires it becomes an ``invalid command name`` background error.  A real
        app restart can then inherit a half-torn-down overlay.
        """
        utility = tk.Toplevel(self.overlay.root)
        self.overlay.root.after(60_000, lambda: None)
        utility.after(60_000, lambda: None)
        self.assertGreater(len(tuple(self.overlay.root.tk.call("after", "info"))), 0)

        self.overlay._cancel_pending_tk_callbacks()

        self.assertEqual(tuple(self.overlay.root.tk.call("after", "info")), ())

    def test_destroying_one_utility_window_cancels_only_its_callbacks(self) -> None:
        window = self.overlay._utility_window(
            "timer_cleanup_test",
            "Talk DAT! Timer cleanup",
            "480x320",
            bg="#101820",
        )
        self.assertIsNotNone(window)
        assert window is not None
        window.after(60_000, lambda: None)
        child = tk.Frame(window)
        child.after(60_000, lambda: None)
        root_timer = self.overlay.root.after(60_000, lambda: None)

        window.destroy()

        pending = tuple(self.overlay.root.tk.call("after", "info"))
        self.assertIn(root_timer, pending, "closing a menu must not stop the Pill")


if __name__ == "__main__":
    unittest.main()


class ClayReachesEveryWindowTests(unittest.TestCase):
    """The clay texture was rewritten and then wired to one surface.

    _apply_glass_effect carried a comment claiming "the tactile quality comes
    from the painted clay texture instead", which described an intention rather
    than the code: flow_console_material was called once, for the context menu,
    while every settings, history, stats and update window was a flat fill.
    Reported as "you never did the lime wash and Roman clay", correctly.
    """

    def source(self) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py").read_text(encoding="utf-8")

    def function_source(self, name: str) -> str:
        import ast

        source = self.source()
        tree = ast.parse(source)
        matches = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == name
        ]
        self.assertEqual(len(matches), 1)
        return ast.get_source_segment(source, matches[0]) or ""

    def test_the_shared_window_styler_paints_clay(self) -> None:
        source = self.source()
        block = source[source.index("def _apply_glass_effect"):][:400]
        self.assertIn("_paint_clay_backdrop", block,
                      "every utility window goes through here; if clay is not applied here it reaches almost nothing")

    def test_the_backdrop_uses_the_real_clay_field(self) -> None:
        block = self.function_source("_paint_clay_backdrop")
        self.assertIn("clay_field(", block)

    def test_the_backdrop_cannot_disturb_a_layout(self) -> None:
        """Two of these windows lay their children out with grid and the rest
        use pack. place() participates in neither, so it cannot conflict."""
        block = self.function_source("_paint_clay_backdrop")
        self.assertIn(".place(", block)
        self.assertNotIn(".pack(", block)
        self.assertNotIn(".grid(", block)

    def test_the_backdrop_sits_behind_the_content(self) -> None:
        block = self.function_source("_paint_clay_backdrop")
        self.assertIn(".lower()", block)

    def test_decoration_failure_never_blocks_a_window(self) -> None:
        block = self.function_source("_paint_clay_backdrop")
        self.assertIn("except Exception", block)
