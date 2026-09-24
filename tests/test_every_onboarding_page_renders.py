from __future__ import annotations

import gc
import tkinter as tk
import unittest

from knight_flow.config import load_config
from knight_flow.onboarding import ONBOARDING_STEPS
from knight_flow.overlay import Overlay
from knight_flow.ui.onboarding import OnboardingWizard
from tests.tk_support import IS_MAC, acquire_root, probe_error as _ROOT_ERROR, release_root


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class EveryOnboardingPageRendersTests(unittest.TestCase):
    """Setup has pages; nothing rendered them.

    `test_every_window_opens` covers the windows reachable from the menu, and
    the wizard is one window, so every page inside it went untested. The
    microphone step -- the one that picks a microphone and shows the level
    meter -- raised `TclError: cannot use geometry manager "pack" inside ...
    grid is already managing its content windows` on EVERY render, from the
    day X-24 added the Mic Doctor row with pack into a grid-managed container.
    It shipped that way on both platforms.

    The failure mode is the same one `_utility_window` has bitten us with
    before: `render_step` raises partway through, so the page is left half
    built, and Tk sends the traceback to a stderr a --windowed build discards.
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

    def test_every_page_renders_without_raising(self) -> None:
        wizard = OnboardingWizard(self.overlay)
        self.addCleanup(lambda: wizard.window.destroy() if wizard.window.winfo_exists() else None)
        self.root.update()
        failures: list[str] = []
        for index, step in enumerate(ONBOARDING_STEPS):
            try:
                wizard.render_step(index)
                self.root.update()
            except Exception as error:
                failures.append(f"{step.id}: {type(error).__name__}: {error}")
        self.assertEqual(failures, [], f"onboarding pages that fail to render: {failures}")

    def test_no_page_mixes_pack_and_grid_in_the_shared_content_frame(self) -> None:
        """The specific trap, stated so the next page cannot repeat it.

        Every page builds into `self.content`, which the page heading grids
        into. Tk refuses pack in a container that already has grid slaves, so a
        page that packs anything directly into content raises -- and the raise
        happens after the heading is already on screen, which is why it looks
        like a half-drawn window rather than an error.
        """
        wizard = OnboardingWizard(self.overlay)
        self.addCleanup(lambda: wizard.window.destroy() if wizard.window.winfo_exists() else None)
        self.root.update()
        offenders: list[str] = []
        for index, step in enumerate(ONBOARDING_STEPS):
            try:
                wizard.render_step(index)
                self.root.update()
            except Exception:
                continue
            for child in wizard.content.winfo_children():
                if child.winfo_manager() == "pack":
                    offenders.append(f"{step.id}: {type(child).__name__} packed into content")
        self.assertEqual(offenders, [], f"pages packing into a grid-managed frame: {offenders}")


@unittest.skipUnless(IS_MAC, "macOS only")
class TheKeyboardShownIsTheOneInFrontOfYouTests(unittest.TestCase):
    """The superpowers card drew a Windows keyboard on a Mac.

    Its whole job is teaching the trigger chord, so printing a key the machine
    does not have teaches the wrong chord on the one page that exists to teach
    it.
    """

    def source(self) -> str:
        from pathlib import Path

        return (Path(__file__).resolve().parents[1] / "knight_flow" / "ui" / "onboarding.py").read_text(encoding="utf-8")

    def test_no_windows_key_is_drawn_on_a_mac(self) -> None:
        # The illustrated keyboard is gone; the Controls page now draws the
        # REAL chord, and its keycap labels come from hotkey_labels(), which
        # spells the keys the way this platform's keyboards print them.
        source = self.source()
        block = source[source.index("def _render_controls"):][:3000]
        self.assertIn("labels = hotkey_labels(chord)", block,
                      "the keycaps must be spelled from the platform's own key labels")
        self.assertIn("self._draw_keycap(canvas, label, False)", block)


if __name__ == "__main__":
    unittest.main()
