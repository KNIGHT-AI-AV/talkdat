"""X-641: the Pill reaches the screen with per-pixel alpha, not a colour key.

Polish audit P0-1 (2026-09-24): PIL draws the Pill with anti-aliased edges, a
rim and a contact shadow, then the window could only show a pixel fully
transparent or fully opaque. Tk blended every soft pixel over #010203, Windows
removed only exact #010203, a one-bit region cut the rest, and 1,380 pixels
meant to be partly transparent came out opaque near-black: a stepped black
outline on any light desktop.

The Pill is now pushed through UpdateLayeredWindow as a premultiplied BGRA
bitmap (knight_flow/layered_window.py). What is pinned here:

* the bitmap maths: premultiplied, BGRA order, colour never above alpha;
* the footprint: an anti-aliased capsule the size of the window (the old
  region's shape, smooth), so clicks land where they always did;
* the presenter's Win32 dance, against a fake: clear-then-set WS_EX_LAYERED
  (Tk's -alpha/-transparentcolor block UpdateLayeredWindow with error 87 until
  the bit is toggled), drop the old region, re-arm once after a failed push;
* on the real Overlay, on the offscreen desktop: the window is layered with
  no region; the pushed bitmap has intermediate alpha along its silhouette and
  no opaque near-black pixels outside the body (and the same frame through the
  old colour key has hundreds, so the check can go red); a click on the body
  lands on the Pill while a clear corner falls through to the window beneath;
  the update dot is drawn where its click is; the hover fade only changes the
  constant alpha; a stray Tk -alpha does not switch the layered Pill off;
* the frame cost stays within 1.5x of the colour-key path (it is measured far
  below it: the PhotoImage plus canvas swap was most of the old frame).
"""
from __future__ import annotations

import copy
import ctypes
import statistics
import sys
import time
import unittest
from ctypes import wintypes
from unittest import mock

import numpy as np
from PIL import Image

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.layered_window import (
    WS_EX_LAYERED,
    LayeredPresenter,
    capsule_alpha_mask,
    premultiplied_bgra,
)
from tests import gui_offscreen  # noqa: F401  (X-164: never on a human's screen)


class PremultipliedBitmapTests(unittest.TestCase):
    def test_a_half_transparent_pixel_is_premultiplied_and_swapped(self) -> None:
        image = Image.new("RGBA", (1, 1), (200, 100, 50, 128))
        blue, green, red, alpha = premultiplied_bgra(image)
        self.assertEqual(alpha, 128)
        self.assertAlmostEqual(red, 200 * 128 / 255, delta=1)
        self.assertAlmostEqual(green, 100 * 128 / 255, delta=1)
        self.assertAlmostEqual(blue, 50 * 128 / 255, delta=1)

    def test_colour_never_exceeds_alpha_and_clear_is_zero(self) -> None:
        rng = np.random.default_rng(641)
        pixels = rng.integers(0, 256, size=(24, 40, 4), dtype=np.uint8)
        pixels[0, :, 3] = 0
        data = np.frombuffer(premultiplied_bgra(Image.fromarray(pixels, "RGBA")), np.uint8).reshape(24, 40, 4)
        self.assertTrue(np.all(data[..., :3] <= data[..., 3:4]))
        self.assertEqual(int(data[0].sum()), 0)

    def test_the_numpy_fallback_agrees_with_pillow(self) -> None:
        rng = np.random.default_rng(7)
        image = Image.fromarray(rng.integers(0, 256, size=(9, 13, 4), dtype=np.uint8), "RGBA")
        fast = np.frombuffer(premultiplied_bgra(image), np.uint8).astype(int)
        real_tobytes = Image.Image.tobytes

        def no_bgra(self, encoder_name="raw", *args):
            if args and args[0] == "BGRa":
                raise ValueError("unknown raw mode")
            return real_tobytes(self, encoder_name, *args)

        with mock.patch.object(Image.Image, "tobytes", no_bgra):
            slow = np.frombuffer(premultiplied_bgra(image), np.uint8).astype(int)
        self.assertLessEqual(int(np.abs(fast - slow).max()), 1)


class CapsuleFootprintTests(unittest.TestCase):
    def test_corners_are_clear_the_middle_is_solid_the_edge_is_soft(self) -> None:
        mask = np.asarray(capsule_alpha_mask(92, 26))
        self.assertEqual(mask.shape, (26, 92))
        for corner in (mask[0, 0], mask[0, -1], mask[-1, 0], mask[-1, -1]):
            self.assertEqual(int(corner), 0)
        self.assertEqual(int(mask[13, 46]), 255)
        partial = (mask > 0) & (mask < 255)
        self.assertGreater(int(partial.sum()), 30)

    def test_it_is_the_shape_the_old_region_cut(self) -> None:
        # The region was CreateRoundRectRgn over the whole window with a
        # height-sized diameter: a capsule. Same area within a few pixels.
        width, height = 192, 35
        mask = np.asarray(capsule_alpha_mask(width, height)).astype(float) / 255.0
        radius = height / 2.0
        capsule_area = (width - height) * height + np.pi * radius * radius
        self.assertAlmostEqual(float(mask.sum()), capsule_area, delta=width * 0.05)
        np.testing.assert_array_equal(mask, mask[:, ::-1])


class FakeApi:
    def __init__(self, *, fail_pushes: int = 0) -> None:
        self.style = 0x00080088  # layered + topmost + toolwindow, as Tk leaves it
        self.calls: list[tuple] = []
        self.fail_pushes = fail_pushes
        self.handle = 4242

    def root_handle(self, client: int) -> int:
        return self.handle

    def get_extended_style(self, hwnd: int) -> int:
        return self.style

    def set_extended_style(self, hwnd: int, style: int) -> bool:
        self.style = style
        self.calls.append(("style", hwnd, bool(style & WS_EX_LAYERED)))
        return True

    def clear_region(self, hwnd: int) -> bool:
        self.calls.append(("region", hwnd))
        return True

    def update_layered(self, hwnd: int, width: int, height: int, bgra: bytes, alpha: int) -> bool:
        self.calls.append(("push", hwnd, width, height, len(bgra), alpha))
        if self.fail_pushes > 0:
            self.fail_pushes -= 1
            return False
        return True

    def update_alpha(self, hwnd: int, alpha: int) -> bool:
        self.calls.append(("alpha", hwnd, alpha))
        return True

    def invalidate(self, hwnd: int) -> bool:
        self.calls.append(("invalidate", hwnd))
        return True

    def close(self) -> None:
        self.calls.append(("close",))


class FakeWindow:
    def __init__(self, mapped: bool = True) -> None:
        self.mapped = mapped

    def winfo_ismapped(self) -> int:
        return int(self.mapped)

    def winfo_id(self) -> int:
        return 99


class PresenterTests(unittest.TestCase):
    def frame(self) -> Image.Image:
        return Image.new("RGBA", (30, 10), (255, 0, 0, 200))

    def test_arming_toggles_the_layered_bit_and_drops_the_region(self) -> None:
        api = FakeApi()
        presenter = LayeredPresenter(FakeWindow(), api=api)
        self.assertTrue(presenter.present(self.frame()))
        self.assertEqual(
            api.calls[:4],
            [("style", 4242, False), ("style", 4242, True), ("region", 4242), ("push", 4242, 30, 10, 1200, 255)],
        )
        self.assertTrue(presenter.armed)

    def test_a_steady_pill_does_not_re_arm(self) -> None:
        api = FakeApi()
        presenter = LayeredPresenter(FakeWindow(), api=api)
        presenter.present(self.frame())
        api.calls.clear()
        presenter.present(self.frame())
        self.assertEqual([call[0] for call in api.calls], ["push"])

    def test_one_failed_push_re_arms_and_retries(self) -> None:
        api = FakeApi(fail_pushes=1)
        presenter = LayeredPresenter(FakeWindow(), api=api)
        self.assertTrue(presenter.present(self.frame()))
        kinds = [call[0] for call in api.calls]
        self.assertEqual(kinds, ["style", "style", "region", "push", "style", "style", "region", "push"])

    @unittest.skipUnless(sys.platform == "win32", "ctypes.get_last_error is Windows-only")
    def test_two_failed_pushes_report_failure(self) -> None:
        api = FakeApi(fail_pushes=2)
        presenter = LayeredPresenter(FakeWindow(), api=api)
        self.assertFalse(presenter.present(self.frame()))
        self.assertRegex(presenter.last_error, r"^error \d+$")

    def test_a_recreated_wrapper_is_armed_again(self) -> None:
        api = FakeApi()
        presenter = LayeredPresenter(FakeWindow(), api=api)
        presenter.present(self.frame())
        api.handle = 5151
        api.calls.clear()
        presenter.present(self.frame())
        self.assertEqual(api.calls[0], ("style", 5151, False))
        self.assertEqual(presenter.hwnd, 5151)

    def test_a_withdrawn_pill_keeps_receiving_frames_once_armed(self) -> None:
        window = FakeWindow()
        api = FakeApi()
        presenter = LayeredPresenter(window, api=api)
        presenter.present(self.frame())
        window.mapped = False
        api.calls.clear()
        self.assertTrue(presenter.present(self.frame()))
        self.assertEqual([call[0] for call in api.calls], ["push"])

    def test_release_leaves_the_bit_set_for_tk_and_asks_for_a_repaint(self) -> None:
        """X-642: Tk never sets WS_EX_LAYERED again once it has; clearing it
        would leave the colour-key fallback with no transparency at all."""
        api = FakeApi()
        presenter = LayeredPresenter(FakeWindow(), api=api)
        presenter.present(self.frame())
        api.calls.clear()
        presenter.release()
        self.assertEqual(
            api.calls, [("style", 4242, False), ("style", 4242, True), ("invalidate", 4242), ("close",)]
        )
        self.assertTrue(api.style & WS_EX_LAYERED)
        self.assertFalse(presenter.armed)

    def test_nothing_is_touched_before_tk_maps_the_window(self) -> None:
        api = FakeApi()
        presenter = LayeredPresenter(FakeWindow(mapped=False), api=api)
        self.assertFalse(presenter.present(self.frame()))
        self.assertEqual(api.calls, [])
        self.assertFalse(presenter.armed)

    def test_the_hover_fade_is_stored_before_arming_and_applied_after(self) -> None:
        api = FakeApi()
        presenter = LayeredPresenter(FakeWindow(), api=api)
        presenter.set_alpha(0.94)
        self.assertEqual(api.calls, [])
        presenter.present(self.frame())
        self.assertEqual(api.calls[3][-1], 240)
        presenter.set_alpha(0.38)
        self.assertEqual(api.calls[-1], ("alpha", 4242, 97))


# ---------------------------------------------------------------------------
# The real Overlay, on the offscreen desktop.
# ---------------------------------------------------------------------------

_PRIVATE_USER32 = None


def private_user32():
    """A private user32 handle with its own argtypes (X-605: never retype
    ctypes.windll.user32, which every module in the process shares)."""
    global _PRIVATE_USER32
    if _PRIVATE_USER32 is None:
        dll = ctypes.WinDLL("user32", use_last_error=True)
        dll.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        dll.GetAncestor.restype = wintypes.HWND
        dll.WindowFromPoint.argtypes = (wintypes.POINT,)
        dll.WindowFromPoint.restype = wintypes.HWND
        dll.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        dll.SendMessageW.restype = ctypes.c_ssize_t
        dll.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
        dll.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        dll.GetWindowRgnBox.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        dll.GetWindowRgnBox.restype = ctypes.c_int
        dll.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        dll.GetWindowRect.restype = wintypes.BOOL
        _PRIVATE_USER32 = dll
    return _PRIVATE_USER32

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


def build_overlay(**overlay_config):
    from knight_flow.overlay import Overlay

    forget_default_root()
    config = copy.deepcopy(DEFAULT_CONFIG)
    config.setdefault("ui", {})["reduce_motion"] = False
    config.setdefault("overlay", {}).update(overlay_config)
    overlay = Overlay(config, callbacks={})
    pump(overlay.root, 0.5)
    return overlay


class PushedFrames:
    """Records every bitmap the presenter hands to UpdateLayeredWindow."""

    def __init__(self, overlay) -> None:
        self.frames: list[tuple[int, int, np.ndarray, int]] = []
        api = overlay._pill_presenter.api
        real = api.update_layered

        def spy(hwnd, width, height, bgra, alpha):
            ok = real(hwnd, width, height, bgra, alpha)
            if ok:
                pixels = np.frombuffer(bytes(bgra), np.uint8).reshape(height, width, 4).copy()
                self.frames.append((width, height, pixels, alpha))
            return ok

        api.update_layered = spy

    def last(self) -> np.ndarray:
        assert self.frames, "nothing was pushed"
        return self.frames[-1][2]


def unpremultiplied_rgb(bgra: np.ndarray) -> np.ndarray:
    alpha = bgra[..., 3:4].astype(float)
    rgb = bgra[..., [2, 1, 0]].astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(alpha > 0, rgb * 255.0 / np.maximum(alpha, 1), 0)
    return np.clip(out, 0, 255)


def body_coverage(overlay, width: int, height: int) -> np.ndarray:
    """Where the Pill's body is, from the Overlay's own body box and mask."""
    active = not overlay.compact
    body_w = min(width, overlay.active_pill_width) if active else width
    body_h = min(height, overlay.active_pill_height) if active else height
    x, y, w, h = overlay._pill_body_box(body_w, body_h)
    origin_x = (width - body_w) // 2
    origin_y = (height - body_h) // 2
    coverage = np.zeros((height, width), float)
    coverage[origin_y + y:origin_y + y + h, origin_x + x:origin_x + x + w] = (
        np.asarray(overlay._compact_mask(w, h), float) / 255.0
    )
    return coverage


def black_fringe(alpha: np.ndarray, rgb: np.ndarray, coverage: np.ndarray) -> int:
    """Opaque, near-black pixels outside the Pill's body: the old outline."""
    near_black = rgb.max(axis=2) < 40
    return int(((alpha >= 200) & near_black & (coverage <= 0.02)).sum())


def hard_steps(alpha: np.ndarray) -> int:
    """Opaque pixels that touch a fully clear one: an edge with no gradient."""
    clear = alpha == 0
    touching = np.zeros_like(clear)
    touching[1:, :] |= clear[:-1, :]
    touching[:-1, :] |= clear[1:, :]
    touching[:, 1:] |= clear[:, :-1]
    touching[:, :-1] |= clear[:, 1:]
    return int(((alpha >= 250) & touching).sum())


def colour_key_view(frame_rgba: np.ndarray, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """What the old path put on screen: blended over the key, keyed, region-cut."""
    key = np.array([1, 2, 3], float)
    alpha = frame_rgba[..., 3:4].astype(float) / 255.0
    rgb = np.round(frame_rgba[..., :3].astype(float) * alpha + key * (1 - alpha))
    is_key = np.all(rgb == key, axis=2)
    region = np.asarray(capsule_alpha_mask(width, height)) >= 128
    shown = (~is_key) & region
    return np.where(shown, 255, 0), rgb


@unittest.skipUnless(sys.platform == "win32", "UpdateLayeredWindow is Windows")
class TheRealPillIsLayeredTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.overlay = build_overlay()
        settle(cls.overlay)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.overlay.root.destroy()
        except Exception:
            pass
        forget_default_root()

    def outer(self) -> int:
        return int(private_user32().GetAncestor(int(self.overlay.root.winfo_id()), 2) or 0)

    def draw_idle(self) -> PushedFrames:
        overlay = self.overlay
        overlay.set_state("idle", "", "")
        settle(overlay)
        pushed = PushedFrames(overlay)
        overlay.idle_render_cache.clear()
        overlay._draw_visual()
        return pushed

    def test_the_pill_window_is_layered_with_no_region(self) -> None:
        self.draw_idle()
        presenter = self.overlay._pill_presenter
        self.assertTrue(presenter.armed, presenter.last_error)
        hwnd = self.outer()
        dll = private_user32()
        style = int(dll.GetWindowLongPtrW(hwnd, -20))
        self.assertTrue(style & WS_EX_LAYERED)
        self.assertTrue(style & 0x08000000, "the Pill lost WS_EX_NOACTIVATE")
        self.assertTrue(style & 0x00000008, "the Pill lost topmost")
        rect = wintypes.RECT()
        self.assertEqual(int(dll.GetWindowRgnBox(hwnd, ctypes.byref(rect))), 0, "a one-bit region is still set")

    def check_edge(self, pixels: np.ndarray) -> None:
        overlay = self.overlay
        height, width = pixels.shape[:2]
        alpha = pixels[..., 3]
        rgb = unpremultiplied_rgb(pixels)
        coverage = body_coverage(overlay, width, height)
        for corner in (alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1]):
            self.assertEqual(int(corner), 0, "the window's square corner is painted")
        partial = int(((alpha > 0) & (alpha < 255)).sum())
        self.assertGreater(partial, width, "the silhouette has no intermediate alpha")
        self.assertEqual(black_fringe(alpha, rgb, coverage), 0, "opaque near-black pixels outside the body")
        self.assertEqual(hard_steps(alpha), 0, "an opaque pixel sits directly on a clear one")

    def test_the_idle_edge_is_soft_and_has_no_black_fringe(self) -> None:
        pushed = self.draw_idle()
        self.check_edge(pushed.last())

    def test_the_listening_edge_is_soft_and_has_no_black_fringe(self) -> None:
        overlay = self.overlay
        overlay.set_state("listening", "", "")
        settle(overlay)
        pushed = PushedFrames(overlay)
        overlay.set_level(0.6)
        overlay._draw_visual()
        self.check_edge(pushed.last())
        overlay.set_state("idle", "", "")
        settle(overlay)

    def test_the_old_colour_key_fails_the_same_check(self) -> None:
        """The metric can go red: the same frame, keyed the old way."""
        overlay = self.overlay
        pushed = self.draw_idle()
        height, width = pushed.last().shape[:2]
        # The composed frame before the layered clip: what the canvas was given.
        frame = np.asarray(overlay._pill_layered_source.convert("RGBA")).copy()
        shown, rgb = colour_key_view(frame, width, height)
        coverage = body_coverage(overlay, width, height)
        self.assertGreater(black_fringe(shown, rgb, coverage), 40)
        self.assertGreater(hard_steps(shown), 40)

    def test_a_click_on_the_body_lands_on_the_pill_and_a_clear_corner_falls_through(self) -> None:
        import tkinter as tk

        self.draw_idle()
        overlay = self.overlay
        user32 = private_user32()
        hwnd = self.outer()
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        under = tk.Toplevel(overlay.root)
        under.overrideredirect(True)
        under.attributes("-alpha", 1.0)
        under.geometry(
            f"{rect.right - rect.left + 80}x{rect.bottom - rect.top + 80}+{rect.left - 40}+{rect.top - 40}"
        )
        try:
            pump(overlay.root, 0.2)
            overlay.force_visible()
            pump(overlay.root, 0.2)
            under_hwnd = int(user32.GetAncestor(int(under.winfo_id()), 2) or 0)

            def top_of(x: int, y: int) -> tuple[int, int]:
                child = int(user32.WindowFromPoint(wintypes.POINT(x, y)) or 0)
                return child, int(user32.GetAncestor(child, 2) or 0)

            centre = ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
            child, top = top_of(*centre)
            self.assertEqual(top, hwnd, "a click on the Pill's body does not reach the Pill")
            lparam = ((centre[1] & 0xFFFF) << 16) | (centre[0] & 0xFFFF)
            self.assertEqual(int(user32.SendMessageW(child, 0x0084, 0, lparam)), 1, "body is not HTCLIENT")
            left_end = (rect.left + 2, centre[1])
            self.assertEqual(top_of(*left_end)[1], hwnd, "the Pill's rounded end lets clicks through")
            for corner in ((rect.left, rect.top), (rect.right - 1, rect.top), (rect.left, rect.bottom - 1)):
                with self.subTest(corner=corner):
                    self.assertEqual(top_of(*corner)[1], under_hwnd, "a clear corner still catches clicks")
        finally:
            under.destroy()

    def test_a_hidden_pill_comes_back_showing_its_frame(self) -> None:
        """Withdrawn for fullscreen media, then shown: the bitmap is still there.

        Checked through hit testing, which follows the layered bitmap's alpha:
        a window that lost its bitmap would let the click through its body."""
        overlay = self.overlay
        self.draw_idle()
        user32 = private_user32()
        hwnd = self.outer()
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        overlay.root.withdraw()
        pump(overlay.root, 0.05)
        pushed = PushedFrames(overlay)
        overlay._draw_visual()
        self.assertTrue(pushed.frames, "a withdrawn Pill stopped receiving frames")
        overlay.root.deiconify()
        pump(overlay.root, 0.1)
        centre = wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        child = int(user32.WindowFromPoint(centre) or 0)
        self.assertEqual(int(user32.GetAncestor(child, 2) or 0), hwnd)

    def test_the_update_dot_is_drawn_where_its_click_is(self) -> None:
        overlay = self.overlay
        self.draw_idle()
        try:
            overlay.set_update_flag("red")
            pushed = PushedFrames(overlay)
            overlay._draw_visual()
            pixels = pushed.last()
            x0, y0, x1, y1 = overlay.canvas.coords("update_flag")
            cx, cy = int((x0 + x1) / 2), int((y0 + y1) / 2)
            blue, green, red, alpha = (int(v) for v in pixels[cy, cx])
            self.assertEqual(alpha, 255, "the dot is not opaque, so it would not take the click")
            self.assertGreater(red, 180)
            self.assertLess(green, 110)
            hit = overlay.canvas.find_overlapping(cx, cy, cx, cy)
            self.assertIn(overlay.canvas.find_withtag("update_flag")[0], hit)
        finally:
            overlay.set_update_flag("")
            overlay._draw_visual()

    def test_a_flag_at_rest_is_shown_without_waiting_for_a_redraw(self) -> None:
        overlay = self.overlay
        self.draw_idle()
        pushed = PushedFrames(overlay)
        try:
            overlay.set_update_flag("green")
            self.assertTrue(pushed.frames, "the new dot waits for the next animation frame")
        finally:
            overlay.set_update_flag("")

    def test_the_hover_fade_changes_only_the_constant_alpha(self) -> None:
        overlay = self.overlay
        self.draw_idle()
        presenter = overlay._pill_presenter
        calls: list[int] = []
        real = presenter.api.update_alpha
        presenter.api.update_alpha = lambda hwnd, alpha: calls.append(alpha) or real(hwnd, alpha)
        tk_alpha = float(overlay.root.attributes("-alpha"))
        overlay._apply_root_alpha(0.5, force=True)
        overlay._apply_root_alpha(overlay.opacity, force=True)
        self.assertEqual(calls, [128, round(overlay.opacity * 255)])
        self.assertEqual(float(overlay.root.attributes("-alpha")), tk_alpha, "Tk's -alpha was touched")

    def test_a_stray_tk_alpha_does_not_switch_the_layered_pill_off(self) -> None:
        overlay = self.overlay
        self.draw_idle()
        overlay.root.attributes("-alpha", 0.9)  # SetLayeredWindowAttributes underneath
        pump(overlay.root, 0.05)
        pushed = PushedFrames(overlay)
        overlay._draw_visual()
        self.assertTrue(pushed.frames, "the layered Pill stopped after a Tk -alpha")
        self.assertTrue(overlay._pill_presenter.armed)


def median_draw_ms(overlay, frames: int = 50) -> float:
    overlay.set_state("listening", "", "")
    settle(overlay)
    costs: list[float] = []
    levels = (0.1, 0.4, 0.8, 0.5, 0.2)
    for index in range(frames):
        overlay.set_level(levels[index % len(levels)])
        start = time.perf_counter()
        overlay._draw_visual()
        costs.append((time.perf_counter() - start) * 1000.0)
        overlay.root.update()
    return statistics.median(costs)


@unittest.skipUnless(sys.platform == "win32", "UpdateLayeredWindow is Windows")
class TheLayeredFrameIsNoDearerTests(unittest.TestCase):
    def test_a_live_frame_costs_at_most_one_and_a_half_colour_key_frames(self) -> None:
        # Two rounds, alternating, so a burst of load on this machine (other
        # suites share it) lands on both paths rather than skewing one.
        costs: dict[bool, list[float]] = {True: [], False: []}
        for _round in range(2):
            for per_pixel in (True, False):
                overlay = build_overlay(pill_per_pixel_alpha=per_pixel)
                try:
                    costs[per_pixel].append(median_draw_ms(overlay, frames=30))
                    presenter = overlay._pill_presenter
                    if per_pixel:
                        self.assertTrue(presenter is not None and presenter.armed)
                    else:
                        self.assertIsNone(presenter)
                finally:
                    overlay.root.destroy()
                    forget_default_root()
        layered_ms = statistics.fmean(costs[True])
        keyed_ms = statistics.fmean(costs[False])
        print(f"\nX-641 frame cost (median ms per round): layered {costs[True]}, colour key {costs[False]}")
        self.assertLessEqual(layered_ms, keyed_ms * 1.5)


if __name__ == "__main__":
    unittest.main()
