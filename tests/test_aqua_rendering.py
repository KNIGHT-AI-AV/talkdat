from __future__ import annotations

import os
import time
import tkinter as tk
import sys
import unittest
from pathlib import Path

from knight_flow import mac_support
from knight_flow.flat_button import FlatButton
from tests.tk_support import acquire_root, probe_error as _ROOT_ERROR, release_root

ROOT_DIR = Path(__file__).resolve().parents[1]


def _capture_window(win):
    """The window's real pixels from the window server, or None if unavailable."""
    try:
        from PIL import Image
        from Quartz import (
            CGDataProviderCopyData,
            CGImageGetBytesPerRow,
            CGImageGetDataProvider,
            CGImageGetHeight,
            CGImageGetWidth,
            CGRectNull,
            CGWindowListCopyWindowInfo,
            CGWindowListCreateImage,
            kCGWindowImageBoundsIgnoreFraming,
            kCGWindowListOptionAll,
            kCGWindowListOptionIncludingWindow,
        )
    except Exception:
        return None
    wid = None
    info = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, 0)
    for w in info or []:
        if w.get("kCGWindowOwnerPID") != os.getpid():
            continue
        if abs(w.get("kCGWindowBounds", {}).get("Width", 0) - win.winfo_width()) <= 2:
            wid = w["kCGWindowNumber"]
    if wid is None:
        return None
    img = CGWindowListCreateImage(CGRectNull, kCGWindowListOptionIncludingWindow, wid,
                                  kCGWindowImageBoundsIgnoreFraming)
    if img is None:
        return None
    w_, h_ = CGImageGetWidth(img), CGImageGetHeight(img)
    data = CGDataProviderCopyData(CGImageGetDataProvider(img))
    return Image.frombuffer("RGBA", (w_, h_), bytes(data), "raw", "BGRA",
                            CGImageGetBytesPerRow(img), 1)


class NoNativeButtonsInTheDarkUITests(unittest.TestCase):
    """tk.Button is banned from the styled UI, structurally.

    On Aqua the native theme paints tk.Button's face white no matter what bg=
    says, while fg= is honoured -- so this UI's dark-face/near-white-text
    styling rendered as white slabs with invisible labels. Onboarding's primary
    controls shipped that way. cget() reports the configured colour, which is
    how a colour audit passed while the screen was unreadable: the audit read
    what was asked, Aqua painted what it liked.

    ttk.Button stays allowed: the app forces the clam theme, which draws its
    own faces and honours the style map.
    """

    FILES = ("knight_flow/overlay.py", "knight_flow/ui/onboarding.py")

    def test_no_file_constructs_a_native_button(self) -> None:
        import re

        offenders = []
        for rel in self.FILES:
            text = (ROOT_DIR / rel).read_text(encoding="utf-8")
            # (?<!t) so ttk.Button does not count: the naive substring match is
            # exactly the mistake that briefly rewrote 110 ttk sites in this
            # codebase, so the guard itself must not repeat it.
            count = len(re.findall(r"(?<!t)tk\.Button\(", text))
            if count:
                offenders.append(f"{rel}: {count}x tk.Button(")
        self.assertEqual(offenders, [],
                         f"native buttons will render white-on-white on macOS: {offenders}")


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class FlatButtonBehavesLikeAButtonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = acquire_root()
        self.fired: list[str] = []
        self.button = FlatButton(self.root, text="Go", bg="#16282d", fg="#edf7f3",
                                 command=lambda: self.fired.append("hit"))
        self.button.place(x=10, y=10, width=90, height=30)
        self.root.update()

    def tearDown(self) -> None:
        try:
            self.button.destroy()
        except Exception:
            pass
        release_root(self.root)

    @unittest.skipUnless(sys.platform == "darwin", "Aqua click delivery is macOS behaviour")

    def test_click_inside_fires_the_command_once(self) -> None:
        self.button.event_generate("<ButtonPress-1>", x=5, y=5)
        self.button.event_generate("<ButtonRelease-1>", x=5, y=5)
        self.root.update()
        self.assertEqual(self.fired, ["hit"])

    def test_dragging_off_before_release_cancels(self) -> None:
        """tk.Button's contract: press, change your mind, slide off, release."""
        self.button.event_generate("<ButtonPress-1>", x=5, y=5)
        self.button.event_generate("<ButtonRelease-1>", x=500, y=500)
        self.root.update()
        self.assertEqual(self.fired, [])

    def test_disabled_swallows_clicks_and_invoke(self) -> None:
        self.button.configure(state="disabled")
        self.button.event_generate("<ButtonPress-1>", x=5, y=5)
        self.button.event_generate("<ButtonRelease-1>", x=5, y=5)
        self.button.invoke()
        self.root.update()
        self.assertEqual(self.fired, [])
        self.button.configure(state="normal")
        self.button.invoke()
        self.assertEqual(self.fired, ["hit"])

    def test_command_can_be_swapped_after_construction(self) -> None:
        """Several windows rewire next_button.configure(command=...) at runtime."""
        self.button.configure(command=lambda: self.fired.append("second"))
        self.button.invoke()
        self.assertEqual(self.fired, ["second"])

    @unittest.skipUnless(mac_support.IS_MAC, "the rendering claim is about Aqua")
    def test_the_face_pixels_are_the_configured_colour(self) -> None:
        """The whole point: what is on screen, not what cget says."""
        window = tk.Toplevel(self.root)
        # No titlebar: the capture includes the frame, and a titlebar shifts
        # every content coordinate down by its own height.
        window.overrideredirect(True)
        window.geometry("220x80+400+300")
        window.configure(bg="#061012")
        button = FlatButton(window, text="Continue", bg="#37e2c0", fg="#0d1417")
        button.place(x=20, y=20, width=140, height=36)
        self.root.update()
        time.sleep(0.35)
        shot = _capture_window(window)
        if shot is None:
            window.destroy()
            self.skipTest("window-server capture unavailable")
        scale = shot.width / max(1, window.winfo_width())
        # Face, not glyphs: near the left edge at half height.
        px = shot.getpixel((int((20 + 4) * scale), int((20 + 18) * scale)))
        window.destroy()
        # Tolerance, not equality: the window server colour-matches the frame
        # through the display profile, which shifts channels by more than a
        # few counts on a wide-gamut monitor -- measured up to 55 on this
        # rig's panel, entirely in ColorSync, with plain sRGB primaries
        # bleeding across channels (pure red picks up +30 blue). The failure
        # this guards against is a NATIVE WHITE face (~235+ per channel) or
        # black -- a 70-count drift of mint is still unmistakably mint.
        expected = (55, 226, 192)
        drift = max(abs(px[i] - expected[i]) for i in range(3))
        self.assertLessEqual(
            drift, 70,
            f"configured mint face rendered as {px[:3]} -- Aqua repainted it")


@unittest.skipUnless(mac_support.IS_MAC, "macOS only")
@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class ThePillIsNeverRemappedTests(unittest.TestCase):
    """Remapping is what turned the Pill's corners black.

    withdraw()/deiconify() on Aqua silently drops per-pixel transparency: the
    -transparent attribute still reads as set while every systemTransparent
    surface rasterises opaque black, and neither re-applying the attribute nor
    clearing the NSWindow heals it -- all verified against captured pixels. So
    the Pill hides by parking off-screen and shows by being positioned back.
    """

    def source(self) -> str:
        return (ROOT_DIR / "knight_flow" / "overlay.py").read_text(encoding="utf-8")

    def test_the_fullscreen_hide_parks_instead_of_withdrawing(self) -> None:
        source = self.source()
        block = source[source.index("def _sync_fullscreen_visibility"):][:1400]
        self.assertIn("_mac_parked", block)
        self.assertIn("+20000+20000", block)

    def test_force_visible_does_not_deiconify_a_mapped_window(self) -> None:
        source = self.source()
        block = source[source.index("def force_visible"):][:1600]
        self.assertIn('self.root.state() == "withdrawn"', block)

    def test_pill_corner_pixels_are_transparent_on_screen(self) -> None:
        """The end-to-end fact, measured. Everything else is a proxy for this."""
        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay
        from tests.tk_support import acquire_root, release_root

        root = acquire_root()
        overlay = Overlay(config=load_config(), callbacks={}, root=root)
        try:
            overlay.force_visible()
            pill = overlay.root  # on macOS the Pill is a Toplevel, not the root
            for _ in range(20):
                pill.update()
                time.sleep(0.03)
            shot = _capture_window(pill)
            if shot is None:
                self.skipTest("window-server capture unavailable")
            w, h = shot.size
            corners = [shot.getpixel(p) for p in ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3))]
            opaque = [c for c in corners if c[3] > 40]
            self.assertEqual(
                opaque, [],
                f"pill corners are opaque on screen: {corners} -- the black-box regression",
            )
        finally:
            release_root(root)

    def test_the_pill_window_has_no_title_bar_on_screen(self) -> None:
        """The traffic-lights regression, held shut by geometry.

        A borderless window's on-screen bounds equal its content size; a
        titled one is ~28-32pt taller. Tk applies overrideredirect to the ROOT
        only at a remap, and a remap permanently breaks per-pixel
        transparency, so the Pill lives in a Toplevel -- which gets both
        properties at first map, exactly like the context menu always has.
        """
        import os as _os

        from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionAll

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay
        from tests.tk_support import acquire_root, release_root

        root = acquire_root()
        overlay = Overlay(config=load_config(), callbacks={}, root=root)
        try:
            overlay.force_visible()
            pill = overlay.root
            self.assertIsInstance(pill, tk.Toplevel,
                                  "on macOS the Pill must be a Toplevel, not the Tk root")
            for _ in range(15):
                pill.update()
                time.sleep(0.03)
            content = (pill.winfo_width(), pill.winfo_height())
            onscreen = None
            for w in CGWindowListCopyWindowInfo(kCGWindowListOptionAll, 0) or []:
                if w.get("kCGWindowOwnerPID") != _os.getpid():
                    continue
                b = w.get("kCGWindowBounds", {})
                if abs(b.get("Width", 0) - content[0]) <= 4 and b.get("Height", 0) >= content[1]:
                    onscreen = (int(b["Width"]), int(b["Height"]))
            if onscreen is None:
                self.skipTest("pill window not found in the window list")
            self.assertLessEqual(
                onscreen[1] - content[1], 6,
                f"the Pill wears a title bar: content {content}, on-screen {onscreen}",
            )
        finally:
            release_root(root)


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class ContextMenuNeverBlacksOutTests(unittest.TestCase):
    """X-111's mac order: "menu blacked out sometimes".

    systemTransparent plus an alpha attribute is the racing pair upstream
    root-caused on Windows, and Aqua can rebuild the transparent backing
    (a black flush) at map and again at focus. The menu therefore pins
    alpha at 1.0 on macOS and repaints shortly after both moments, so a
    flush can survive at most one frame.
    """

    def test_menu_alpha_is_pinned_and_heal_repaints_fire(self) -> None:
        from knight_flow import mac_support
        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay
        from tests.tk_support import acquire_root, release_root

        root = acquire_root()
        overlay = Overlay(config=load_config(), callbacks={}, root=root)
        paints: list[int] = []
        real_draw = overlay._draw_context_menu

        def counting_draw() -> None:
            paints.append(1)
            real_draw()

        overlay._draw_context_menu = counting_draw
        try:
            overlay._open_context_menu(500, 500)
            menu = overlay.context_menu_window
            self.assertIsNotNone(menu, "context menu did not open")
            if mac_support.IS_MAC:
                self.assertEqual(
                    float(menu.attributes("-alpha")), 1.0,
                    "menu alpha must be pinned at 1.0 on macOS -- an alpha "
                    "attribute on a systemTransparent surface races the "
                    "backing off (the blacked-out menu)",
                )
            end = time.time() + 0.45
            while time.time() < end:
                menu.update()
                time.sleep(0.02)
            floor = 3 if mac_support.IS_MAC else 1
            self.assertGreaterEqual(
                len(paints), floor,
                f"expected the initial paint plus both heal repaints, got {len(paints)}",
            )
            overlay._close_context_menu()
        finally:
            release_root(root)
