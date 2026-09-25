"""X-642: the layered Pill always has the colour key to fall back to.

X-641 moved the Pill to UpdateLayeredWindow. That call can fail where the old
path worked: an older or unusual Windows, a remote desktop session, a driver
that refuses a layered bitmap, or something unforeseen. A Pill that cannot
present is invisible, and the Pill is the only piece of the app that is always
on screen, so a failure must never leave it that way.

What is pinned here, on the real Overlay on the offscreen desktop:

* `overlay.pill_per_pixel_alpha: false` in config.json forces the old path from
  the start, and the log says so;
* when UpdateLayeredWindow fails for good mid-session, the Pill goes back to the
  colour key in the same frame: Tk's colour key and alpha are set again (read
  back with GetLayeredWindowAttributes), the capsule region is back, the frame
  is painted on the canvas, the transition frames are rebuilt as PhotoImages,
  and a warning names the failure;
* when it fails on the very first frame, the Pill still ends up on the key;
* the log names the path in use on every start.
"""
from __future__ import annotations

import copy
import ctypes
import sys
import time
import unittest
from ctypes import wintypes
from unittest import mock

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.pill_motion import TRANSPARENT_COLOR
from tests import gui_offscreen  # noqa: F401  (X-164: never on a human's screen)

LWA_COLORKEY = 0x1
LWA_ALPHA = 0x2


def forget_default_root() -> None:
    import tkinter

    existing = getattr(tkinter, "_default_root", None)
    try:
        alive = existing is not None and bool(existing.winfo_exists())
    except Exception:
        alive = False
    if not alive:
        tkinter._default_root = None  # type: ignore[attr-defined]


def pump(root, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        root.update()
        time.sleep(0.005)


def settle(overlay, seconds: float = 3.0) -> None:
    deadline = time.perf_counter() + seconds
    pump(overlay.root, 0.1)
    while overlay._open_anim_active and time.perf_counter() < deadline:
        pump(overlay.root, 0.01)
    pump(overlay.root, 0.1)


_PRIVATE_USER32 = None


def private_user32():
    """A private user32 handle with its own argtypes (X-605: never retype
    ctypes.windll.user32, which every module in the process shares)."""
    global _PRIVATE_USER32
    if _PRIVATE_USER32 is None:
        dll = ctypes.WinDLL("user32", use_last_error=True)
        dll.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        dll.GetAncestor.restype = wintypes.HWND
        dll.GetLayeredWindowAttributes.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.COLORREF),
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.POINTER(wintypes.DWORD),
        )
        dll.GetLayeredWindowAttributes.restype = wintypes.BOOL
        dll.GetWindowRgnBox.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        dll.GetWindowRgnBox.restype = ctypes.c_int
        _PRIVATE_USER32 = dll
    return _PRIVATE_USER32


def outer_handle(overlay) -> int:
    return int(private_user32().GetAncestor(int(overlay.root.winfo_id()), 2) or 0)


def colour_key_state(overlay) -> tuple[bool, int, int, bool]:
    """(SLWA active, key COLORREF, flags, region present) on the Pill's HWND."""
    user32 = private_user32()
    hwnd = outer_handle(overlay)
    key = wintypes.COLORREF()
    alpha = ctypes.c_ubyte()
    flags = wintypes.DWORD()
    # Succeeds only for a window set up with SetLayeredWindowAttributes, i.e.
    # Tk's -alpha/-transparentcolor; it fails for an UpdateLayeredWindow one.
    active = bool(user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags)))
    rect = wintypes.RECT()
    region = int(user32.GetWindowRgnBox(hwnd, ctypes.byref(rect))) != 0
    return active, int(key.value), int(flags.value), region


def colorref(hex_colour: str) -> int:
    value = hex_colour.lstrip("#")
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def build_overlay(**overlay_config):
    from knight_flow.overlay import Overlay

    forget_default_root()
    config = copy.deepcopy(DEFAULT_CONFIG)
    config.setdefault("ui", {})["reduce_motion"] = False
    config.setdefault("overlay", {}).update(overlay_config)
    overlay = Overlay(config, callbacks={})
    pump(overlay.root, 0.5)
    return overlay


def canvas_frames(overlay):
    """Count PhotoImages the Pill makes for its canvas during one draw."""
    import knight_flow.overlay as module

    real = module.ImageTk.PhotoImage
    made: list[object] = []

    def spy(*args, **kwargs):
        made.append(args[0] if args else kwargs.get("image"))
        return real(*args, **kwargs)

    return made, mock.patch.object(module.ImageTk, "PhotoImage", side_effect=spy)


@unittest.skipUnless(sys.platform == "win32", "UpdateLayeredWindow is Windows")
class TheFlagForcesTheOldPathTests(unittest.TestCase):
    def tearDown(self) -> None:
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            try:
                overlay.root.destroy()
            except Exception:
                pass
        forget_default_root()

    def test_the_flag_off_keeps_the_colour_key_and_says_so(self) -> None:
        with self.assertLogs("knight_flow.overlay", level="INFO") as logs:
            self.overlay = build_overlay(pill_per_pixel_alpha=False)
        overlay = self.overlay
        settle(overlay)
        self.assertIsNone(overlay._pill_presenter)
        self.assertIn("colour key", overlay._pill_presenter_path)
        self.assertTrue(any("pill_per_pixel_alpha" in line for line in logs.output), logs.output)
        made, patch = canvas_frames(overlay)
        with patch:
            overlay.idle_render_cache.clear()
            overlay.idle_photo_cache.clear()
            overlay._draw_visual()
        self.assertTrue(made, "the flag-off Pill is not painted on its canvas")
        active, key, flags, region = colour_key_state(overlay)
        self.assertTrue(active and flags & LWA_COLORKEY, "no colour key on the flag-off Pill")
        self.assertEqual(key, colorref(TRANSPARENT_COLOR))
        self.assertTrue(region, "the flag-off Pill lost its capsule region")

    def test_the_default_is_per_pixel_alpha_and_the_log_says_so(self) -> None:
        self.assertTrue(DEFAULT_CONFIG["overlay"]["pill_per_pixel_alpha"])
        with self.assertLogs("knight_flow.overlay", level="INFO") as logs:
            self.overlay = build_overlay()
            settle(self.overlay)
        self.assertIsNotNone(self.overlay._pill_presenter)
        self.assertTrue(self.overlay._pill_presenter.armed)
        self.assertIn("per-pixel alpha", self.overlay._pill_presenter_path)
        self.assertTrue(any("per-pixel alpha" in line for line in logs.output), logs.output)


@unittest.skipUnless(sys.platform == "win32", "UpdateLayeredWindow is Windows")
class AFailingLayeredWindowFallsBackTests(unittest.TestCase):
    def tearDown(self) -> None:
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            try:
                overlay.root.destroy()
            except Exception:
                pass
        forget_default_root()

    def test_a_mid_session_failure_goes_back_to_the_colour_key_in_the_same_frame(self) -> None:
        self.overlay = overlay = build_overlay()
        settle(overlay)
        presenter = overlay._pill_presenter
        self.assertTrue(presenter.armed)
        presenter.api.update_layered = lambda *args, **kwargs: False
        made, patch = canvas_frames(overlay)
        with self.assertLogs("knight_flow.overlay", level="WARNING") as logs, patch:
            overlay.idle_render_cache.clear()
            overlay.idle_photo_cache.clear()
            overlay._draw_visual()
        self.assertIsNone(overlay._pill_presenter)
        self.assertIn("colour key", overlay._pill_presenter_path)
        self.assertTrue(any("UpdateLayeredWindow" in line for line in logs.output), logs.output)
        self.assertTrue(made, "the failed frame was dropped instead of painted on the canvas")
        active, key, flags, region = colour_key_state(overlay)
        self.assertTrue(active and flags & LWA_COLORKEY, "the colour key was not restored")
        self.assertEqual(key, colorref(TRANSPARENT_COLOR))
        self.assertTrue(flags & LWA_ALPHA, "the Pill's opacity was not restored")
        self.assertTrue(region, "the capsule region was not restored")

    def test_the_transition_is_rebuilt_for_the_canvas_after_a_fallback(self) -> None:
        from PIL import Image

        self.overlay = overlay = build_overlay()
        settle(overlay)
        overlay._pill_presenter.api.update_layered = lambda *args, **kwargs: False
        overlay._draw_visual()
        self.assertIsNone(overlay._pill_presenter)
        overlay.set_state("listening", "", "")
        settle(overlay)
        self.assertTrue(overlay._open_frames)
        self.assertFalse(
            any(isinstance(frame, Image.Image) for frame in overlay._open_frames),
            "the canvas is being handed PIL frames the layered path kept",
        )
        self.assertFalse(overlay.compact)

    def test_a_failure_on_the_very_first_frame_still_ends_on_the_colour_key(self) -> None:
        from knight_flow import layered_window

        real_default = layered_window._default_api

        def failing_api():
            api = real_default()
            api.update_layered = lambda *args, **kwargs: False
            return api

        with mock.patch.object(layered_window, "_default_api", failing_api):
            self.overlay = overlay = build_overlay()
            settle(overlay)
        self.assertIsNone(overlay._pill_presenter)
        active, key, flags, region = colour_key_state(overlay)
        self.assertTrue(active and flags & LWA_COLORKEY)
        self.assertTrue(region)


if __name__ == "__main__":
    unittest.main()
