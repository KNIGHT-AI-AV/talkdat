"""The Pill menu opens next to the Pill, on the Pill's own monitor.

The owner, 2026-10-09: "When I right-clicked the pill on a second monitor, the
menu is like off God knows where." His screens: a 3840x2160 primary at 150% and
a 2560x1440 monitor at 100% ABOVE it, origin (704, -1440), work area bottom -30.
So the case that matters most has negative coordinates and mixed scaling.

Found in the code, each pinned below:
1. while a message is showing, the Pill's window IS the message's envelope, and
   the menu centred on the envelope instead of the Pill;
2. when the native read failed, the web menu fell back to the work area of the
   FOREGROUND application's monitor, mixed with an unscaled click point;
3. the Tk menu (the fallback renderer) always used the foreground app's monitor.

The geometry matrix is Overwatch's (2026-10-09): monitors left of and above the
primary, mixed 100/125/150/200% scaling, the taskbar on every edge, the Pill
near every edge and corner, and a monitor unplugged mid-session.
"""
from __future__ import annotations

import ctypes
import itertools
import math
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow import menu_anchor
from knight_flow.web_shell.menu_geometry import pill_menu_bounds, pill_menu_side

#: (monitor rect, scale) per layout, in the physical pixels Windows reports.
LAYOUTS = {
    "owner: 150% primary, 100% screen above it": [((0, 0, 3840, 2160), 1.5), ((704, -1440, 3264, 0), 1.0)],
    "100% screen left of a 125% primary": [((0, 0, 2560, 1440), 1.25), ((-1920, 0, 0, 1080), 1.0)],
    "200% screen right of a 100% primary": [((0, 0, 1920, 1080), 1.0), ((1920, -300, 5760, 1860), 2.0)],
    "150% screen below a 100% primary": [((0, 0, 1920, 1080), 1.0), ((-200, 1080, 2360, 2520), 1.5)],
}
TASKBAR_EDGES = ("bottom", "top", "left", "right", "none")


def work_area(monitor, scale, edge):
    left, top, right, bottom = monitor
    bar = round(48 * scale)
    return {
        "bottom": (left, top, right, bottom - bar),
        "top": (left, top + bar, right, bottom),
        "left": (left + bar, top, right, bottom),
        "right": (left, top, right - bar, bottom),
        "none": (left, top, right, bottom),
    }[edge]


def pill_spots(area, scale):
    """The Pill (200x48 at 100%) hugging every edge and corner, and centred."""
    left, top, right, bottom = area
    w, h, inset = round(200 * scale), round(48 * scale), round(4 * scale)
    xs = (left + inset, (left + right - w) // 2, right - w - inset)
    ys = (top + inset, (top + bottom - h) // 2, bottom - h - inset)
    return [(x, y, w, h) for x, y in itertools.product(xs, ys)]


class PlacementMatrixTests(unittest.TestCase):
    def check(self, pill, area, scale, label):
        x, y, w, h = pill_menu_bounds(pill, area, scale)
        left, top, right, bottom = area
        margin = round(8 * scale)
        px, py, pw, ph = pill
        with self.subTest(case=label, pill=pill, area=area, scale=scale, menu=(x, y, w, h)):
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)
            # Never off the Pill's monitor, never under its taskbar.
            self.assertGreaterEqual(x, left + margin)
            self.assertGreaterEqual(y, top + margin)
            self.assertLessEqual(x + w, right - margin)
            self.assertLessEqual(y + h, bottom - margin)
            # Next to the Pill: it shares the Pill's columns...
            self.assertLess(x, px + pw)
            self.assertGreater(x + w, px)
            # ...and sits directly above or below it without covering it.
            gap = round(10 * scale)
            self.assertTrue(y + h == py - gap or y == py + ph + gap,
                            f"menu {y}..{y + h} is not against the Pill {py}..{py + ph}")

    def test_every_layout_scale_taskbar_and_pill_spot(self):
        cases = 0
        for name, monitors in LAYOUTS.items():
            for monitor, scale in monitors:
                for edge in TASKBAR_EDGES:
                    area = work_area(monitor, scale, edge)
                    for pill in pill_spots(area, scale):
                        self.check(pill, area, scale, f"{name} / taskbar {edge}")
                        cases += 1
        self.assertGreaterEqual(cases, 300)

    def test_the_owners_second_monitor(self):
        area = (704, -1440, 3264, -30)
        # The Pill parked at the bottom centre of the upper screen: the menu
        # opens upward, on that screen, centred on the Pill.
        pill = (1884, -110, 200, 48)
        x, y, w, h = pill_menu_bounds(pill, area, 1.0)
        self.assertEqual(y + h, pill[1] - 10)
        self.assertGreaterEqual(y, -1440 + 8)
        self.assertLessEqual(abs((x + w / 2) - (pill[0] + pill[2] / 2)), 0.5)

    def test_a_pill_left_behind_by_an_unplugged_monitor(self):
        # The Pill's rectangle still sits where a removed monitor used to be;
        # Windows answers the nearest monitor. The menu must land inside it.
        area = (0, 0, 1920, 1040)
        for pill in ((2500, 400, 200, 48), (-900, -300, 200, 48), (900, 1500, 200, 48)):
            x, y, w, h = pill_menu_bounds(pill, area, 1.0)
            with self.subTest(pill=pill):
                self.assertGreaterEqual(x, 8)
                self.assertGreaterEqual(y, 8)
                self.assertLessEqual(x + w, 1912)
                self.assertLessEqual(y + h, 1032)


#: The real heights of the menu's views at 100% (menu_geometry.menu_height).
VIEW_HEIGHTS = {"Home": 385, "Home with an update": 449, "Speech": 136, "Formatting": 185,
                "App controls": 256, "Tools": 296}


class TheSideStaysPutTests(unittest.TestCase):
    """Overwatch's review B2 (2026-10-10): once each view asked for its own height, a
    submenu could move the menu to the OTHER side of the Pill, because the side was
    chosen again from every view's height (at 100% on a 1080p screen, a Pill whose top
    sat anywhere from y=154 to y=336 opened Home below it and Speech above it). The side
    is chosen once, at open, from Home's height, and every view keeps it: the edge that
    faces the Pill never moves, nothing covers the Pill, and a view taller than the room
    on that side is capped there (its list scrolls)."""

    #: Tall screens, and (review R-B2a, 2026-10-10) the short ones where the room below
    #: the Pill is often less than Home: 1366x768 at 100%, 1080p at 150% and 175%, each
    #: with its taskbar. On the tall ones the below-side cap was never reached.
    SCREENS = ((1.0, (0, 0, 1920, 1032)), (1.5, (0, 0, 2880, 1548)), (1.0, (704, -1440, 3264, -30)),
               (2.0, (1920, -300, 5760, 1764)), (1.0, (0, 0, 1366, 728)), (1.5, (0, 0, 1920, 1008)),
               (1.75, (0, 0, 1920, 996)))

    def test_every_view_keeps_the_side_home_opened_on(self):
        for scale, area in self.SCREENS:
            left, top, right, bottom = area
            pw, ph = round(200 * scale), round(48 * scale)
            gap, margin = round(10 * scale), round(8 * scale)
            for home in (VIEW_HEIGHTS["Home"], VIEW_HEIGHTS["Home with an update"]):
                views = [home] + [VIEW_HEIGHTS[name] for name in ("Speech", "Formatting", "App controls", "Tools")]
                for py in range(top + round(4 * scale), bottom - ph - round(4 * scale) + 1, max(1, round(4 * scale))):
                    pill = ((left + right - pw) // 2, py, pw, ph)
                    side = pill_menu_side(pill, area, scale, height=home)
                    for height in views:
                        x, y, w, h = pill_menu_bounds(pill, area, scale, height=height, side=side)
                        with self.subTest(scale=scale, area=area, pill_top=py, home=home, view=height, side=side,
                                          menu=(x, y, w, h)):
                            if side == "above":
                                self.assertEqual(y + h, py - gap, "the menu left the Pill's top edge")
                            else:
                                self.assertEqual(y, py + ph + gap, "the menu left the Pill's bottom edge")
                            self.assertTrue(y + h <= py - gap or y >= py + ph + gap, "the menu covers the Pill")
                            self.assertGreater(h, 0)
                            self.assertLessEqual(h, round(height * scale))
                            self.assertGreaterEqual(y, top + margin)
                            self.assertLessEqual(y + h, bottom - margin)

    def test_a_view_taller_than_the_room_below_is_capped_there(self):
        # Review R-B2a: a 1280x672 work area at 125%, the Pill's top at 45. Home with an
        # update needs 561 px; 545 fit below. Uncapped, the final clamp lifted the menu
        # to y=101, over the Pill (45..105).
        pill, area = (515, 45, 250, 60), (0, 0, 1280, 672)
        side = pill_menu_side(pill, area, 1.25, height=VIEW_HEIGHTS["Home with an update"])
        self.assertEqual(side, "below")
        self.assertEqual(pill_menu_bounds(pill, area, 1.25, height=VIEW_HEIGHTS["Home with an update"], side=side),
                         [460, 117, 360, 545])

    def test_three_hundred_and_twenty_px_above_is_enough_for_above(self):
        # Review T-6: Home opens above when at least 320 px fit there, even if all of
        # Home does not (its list scrolls), because above is where the menu reads as
        # coming out of the Pill. Room above here: 348 - 8 - 10 = 330, under Home's 385.
        pill, area = (816, 348, 200, 48), (0, 0, 1920, 1032)
        self.assertEqual(pill_menu_side(pill, area, 1.0, height=VIEW_HEIGHTS["Home"]), "above")
        self.assertEqual(pill_menu_bounds(pill, area, 1.0, height=VIEW_HEIGHTS["Home"], side="above"),
                         [772, 8, 288, 330])
        # 319 px is not: the roomier side, below, wins.
        self.assertEqual(pill_menu_side((816, 337, 200, 48), area, 1.0, height=VIEW_HEIGHTS["Home"]), "below")

    def test_the_reviewers_case(self):
        # 100% on 1080p, the Pill's top at y=200: Home opens below, and Speech stays below.
        pill, area = (816, 200, 200, 48), (0, 0, 1920, 1032)
        side = pill_menu_side(pill, area, 1.0, height=385)
        self.assertEqual(side, "below")
        self.assertEqual(pill_menu_bounds(pill, area, 1.0, height=136, side=side)[1], 258)

    def test_when_neither_side_fits_the_menu_still_never_covers_the_pill(self):
        # Review B11: a short screen with the Pill in the middle.
        area, pill = (0, 0, 1280, 600), (540, 276, 200, 48)
        side = pill_menu_side(pill, area, 1.0, height=449)
        x, y, w, h = pill_menu_bounds(pill, area, 1.0, height=449, side=side)
        self.assertTrue(y + h <= pill[1] - 10 or y >= pill[1] + pill[3] + 10, (x, y, w, h))


class EnvelopeTests(unittest.TestCase):
    """A message on the Pill grows its window; the menu belongs to the Pill."""

    def test_the_pill_body_is_found_inside_a_message_envelope(self):
        # Tk geometry (system-DPI pixels) of the envelope and of the Pill inside it,
        # and the physical rectangle Windows reports for that same window at a
        # 1.5x physical-to-Tk ratio.
        envelope = SimpleNamespace(x=1000, y=900, w=600, h=80)
        pill = SimpleNamespace(x=1300, y=916, w=200, h=48)
        window = (1500, 1350, 2400, 1470)
        self.assertEqual(menu_anchor.pill_body_in_window(window, envelope, pill), (1950, 1374, 300, 72))

    def test_no_message_means_the_window_is_the_pill(self):
        self.assertEqual(menu_anchor.pill_body_in_window((10, 20, 210, 68), None, None), (10, 20, 200, 48))


@unittest.skipUnless(sys.platform == "win32", "the Windows anchor; the Mac anchor lives on mac-port")
class FallbackTests(unittest.TestCase):
    def shell(self, flag_view=None):
        from knight_flow.web_shell import shell_app

        shell = object.__new__(shell_app.AppShell)
        shell.overlay = SimpleNamespace(
            root=SimpleNamespace(winfo_rootx=lambda: 0, winfo_rooty=lambda: 0,
                                 winfo_width=lambda: 200, winfo_height=lambda: 48),
            _flag_view=flag_view,
            _logical_work_area=lambda: (0, 0, 1920, 1040),
        )
        return shell

    #: The owner's screens as work_area_at_point answers them, in physical pixels.
    UPPER = ((704, -1440, 3264, -30), 1.0)
    PRIMARY = ((0, 0, 3840, 2088), 1.5)

    def screen_at(self, x, y, *, physical):
        """The screen holding the point, so a wrong point gets a wrong screen."""
        self.assertIs(physical, True)
        return self.UPPER if 704 <= x < 3264 and -1440 <= y < 0 else self.PRIMARY

    def test_a_failed_native_read_uses_the_pointers_monitor(self):
        # Review M01 (2026-10-10): with a stub that gave every point the same screen,
        # asking about (0, 0) instead opened the menu on the primary and stayed green.
        shell = self.shell()
        with patch.object(menu_anchor, "read_pill_window", side_effect=OSError("no window")), \
             patch.object(menu_anchor, "cursor_position", return_value=(1984, -90)) as pointer, \
             patch.object(menu_anchor, "work_area_at_point", side_effect=self.screen_at) as at_point, \
             patch.object(shell.overlay, "_logical_work_area", side_effect=AssertionError("foreground monitor")):
            pill, area, scale = shell._pill_anchor(1300, -60)
        self.assertEqual(pointer.call_args.kwargs, {"physical": True})
        self.assertEqual(at_point.call_args.args, (1984, -90))
        self.assertEqual((pill, area, scale), ((1984, -90, 0, 0), *self.UPPER))

    def test_without_the_pointer_it_uses_the_click_point(self):
        shell = self.shell()
        with patch.object(menu_anchor, "read_pill_window", side_effect=OSError("no window")), \
             patch.object(menu_anchor, "cursor_position", return_value=None), \
             patch.object(menu_anchor, "work_area_at_point", side_effect=self.screen_at) as at_point:
            pill, area, scale = shell._pill_anchor(1984, -90)
        self.assertEqual(at_point.call_args.args, (1984, -90))
        self.assertEqual((pill, area, scale), ((1984, -90, 0, 0), *self.UPPER))

    def test_the_web_menu_measures_the_pill_not_the_message(self):
        view = SimpleNamespace(envelope=SimpleNamespace(x=1000, y=900, w=600, h=80),
                               pill=SimpleNamespace(x=1300, y=916, w=200, h=48))
        shell = self.shell(view)
        reading = menu_anchor.PillWindow(rect=(1500, 1350, 2400, 1470), work=(0, 0, 3840, 2066), scale=1.5)
        with patch.object(menu_anchor, "read_pill_window", return_value=reading):
            pill, area, scale = shell._pill_anchor(0, 0)
        self.assertEqual(pill, (1950, 1374, 300, 72))
        self.assertEqual(area, (0, 0, 3840, 2066))
        self.assertEqual(scale, 1.5)


class TkMenuTests(unittest.TestCase):
    #: The owner's screens in Tk's own (system-DPI) pixels.
    UPPER = ((704, -2160, 4544, -45), 1.0)
    PRIMARY = ((0, 0, 3840, 2088), 1.5)

    def screen_at(self, x, y, *, physical):
        self.assertIs(physical, False)
        return self.UPPER if 704 <= x < 4544 and -2160 <= y < 0 else self.PRIMARY

    def test_the_tk_menu_uses_the_click_point_monitor(self):
        # Review M02 (2026-10-10): the stub must answer per point, or a fixed point passes.
        from knight_flow.overlay import Overlay

        overlay = object.__new__(Overlay)
        overlay._logical_work_area = lambda: (0, 0, 1920, 1040)
        with patch.object(menu_anchor, "work_area_at_point", side_effect=self.screen_at) as at_point:
            self.assertEqual(overlay._context_menu_work_area(2000, -120), self.UPPER[0])
        self.assertEqual(at_point.call_args.args, (2000, -120))

    def origin(self, x_root, y_root, height=400):
        from knight_flow.overlay import Overlay

        return Overlay._context_menu_origin(x_root, y_root, 288, height, (0, 0, 1920, 1040), 8)

    def test_the_tk_menu_opens_above_the_click_then_below(self):
        self.assertEqual(self.origin(960, 900), (816, 488))
        self.assertEqual(self.origin(960, 100), (816, 112))
        self.assertEqual(self.origin(5, 900), (8, 488))
        self.assertEqual(self.origin(1915, 900), (1624, 488))

    def test_a_stranded_click_still_opens_the_tk_menu_on_its_screen(self):
        # Review R5 (2026-10-10): the web path's final clamp. A Pill left beyond its work
        # area (a monitor unplugged under it) opened the Tk menu off every screen, above
        # or below.
        for point in ((960, 3000), (960, -2000), (-4000, 500), (9000, 500), (9000, -2000), (-4000, 3000)):
            for height in (400, 1024):
                with self.subTest(point=point, height=height):
                    x, y = self.origin(*point, height=height)
                    self.assertGreaterEqual(x, 8)
                    self.assertLessEqual(x + 288, 1912)
                    self.assertGreaterEqual(y, 8)
                    self.assertLessEqual(y + height, 1032)

    def test_the_tk_menu_is_placed_through_the_clamp(self):
        import inspect

        from knight_flow.overlay import Overlay

        source = inspect.getsource(Overlay._open_context_menu)
        self.assertIn("x, y = self._context_menu_origin(x_root, y_root, width, height, work_area, margin)", source)
        self.assertNotIn("preferred_y", source, "a second copy of the placement crept back")

    def test_the_tk_menu_falls_back_to_the_pill_then_the_logical_area(self):
        from knight_flow.overlay import Overlay

        overlay = object.__new__(Overlay)
        overlay._logical_work_area = lambda: (0, 0, 1920, 1040)
        overlay._pill_monitor_work_area = lambda: (5, 6, 7, 8)
        with patch.object(menu_anchor, "work_area_at_point", return_value=None):
            self.assertEqual(overlay._context_menu_work_area(1, 2), (5, 6, 7, 8))
        overlay._pill_monitor_work_area = lambda: None
        with patch.object(menu_anchor, "work_area_at_point", return_value=None):
            self.assertEqual(overlay._context_menu_work_area(1, 2), (0, 0, 1920, 1040))


class _Export:
    """One user32 export: callable, and takes argtypes and restype like ctypes'."""

    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


class FakeDesktop:
    """The owner's two screens behind a fake private user32 (review R2: M03, M04).

    Windows answers in the calling thread's pixel space. A per-monitor-aware thread
    (-4) sees physical pixels. This app's threads are system-aware (-2) at the
    primary's 150%, so they see the 100% screen above it scaled by 1.5. A monitor
    lookup honours its flag: NEAREST (2) gives the closest screen to a point or a
    window off every screen, PRIMARY (1) gives the primary.
    """

    SYSTEM_AWARE = -2
    SYSTEM_DPI = 144
    #: handle: (monitor, work area) in physical pixels, and the scale in percent.
    SCREENS = {1: ((0, 0, 3840, 2160), (0, 0, 3840, 2088), 150),
               2: ((704, -1440, 3264, 0), (704, -1440, 3264, -30), 100)}

    def __init__(self, *, cursor=(1984, -90), window=(3300, -760, 3600, -688), info="ok", dpi=None, listed=None):
        self.context = self.SYSTEM_AWARE
        self.switches, self.flags = [], []
        self.cursor, self.window, self.info = cursor, window, info
        # The effective DPI per screen, and what GetScaleFactorForMonitor's fixed list
        # says for it (100, 120, 125, 140, 150, ...); they differ at a custom scale.
        self.dpi = {handle: round(96 * screen[2] / 100) for handle, screen in self.SCREENS.items()} | (dpi or {})
        self.listed = {handle: screen[2] for handle, screen in self.SCREENS.items()} | (listed or {})
        for name in ("SetThreadDpiAwarenessContext", "MonitorFromPoint", "MonitorFromWindow",
                     "GetMonitorInfoW", "GetCursorPos", "GetAncestor", "GetWindowRect"):
            setattr(self, name, _Export(getattr(self, "_" + name)))
        self.shcore = SimpleNamespace(GetScaleFactorForMonitor=_Export(self._scale_factor),
                                      GetDpiForMonitor=_Export(self._dpi_for_monitor))

    def dll(self, name, **_options):
        return {"user32": self, "shcore": self.shcore}[name]

    def _in_thread_space(self, rect, handle):
        scale = 1.0 if self.context == -4 else 150 / self.SCREENS[handle][2]
        return tuple(round(value * scale) for value in rect)

    def _monitor_for(self, rect, flag, screens):
        left, top, right, bottom = rect
        for handle, (s_left, s_top, s_right, s_bottom) in screens.items():
            if left < s_right and s_left < right and top < s_bottom and s_top < bottom:
                return handle
        if flag == 2:
            def gap(handle):
                s_left, s_top, s_right, s_bottom = screens[handle]
                return math.hypot(max(s_left - right, left - s_right, 0), max(s_top - bottom, top - s_bottom, 0))

            return min(screens, key=gap)
        return 1 if flag == 1 else 0

    def _physical_screens(self):
        return {handle: screen[0] for handle, screen in self.SCREENS.items()}

    @staticmethod
    def _signed(handle):
        value = getattr(handle, "value", handle) or 0
        bits = 8 * ctypes.sizeof(ctypes.c_void_p)
        return value - (1 << bits) if value >= 1 << (bits - 1) else value

    def _SetThreadDpiAwarenessContext(self, context):
        previous, self.context = self.context, self._signed(context)
        self.switches.append(self.context)
        return previous

    def _MonitorFromPoint(self, point, flag):
        self.flags.append(flag)
        screens = {handle: self._in_thread_space(screen[0], handle) for handle, screen in self.SCREENS.items()}
        return self._monitor_for((point.x, point.y, point.x + 1, point.y + 1), flag, screens)

    def _MonitorFromWindow(self, _hwnd, flag):
        self.flags.append(flag)
        return self._monitor_for(self.window, flag, self._physical_screens())

    def _GetMonitorInfoW(self, handle, info_ref):
        if self.info == "raise":
            raise OSError("the display driver went away")
        if self.info == "fail":
            return 0
        monitor, work, _percent = self.SCREENS[handle]
        if self.info == "empty":
            work = (0, 0, 0, 0)
        for field, rect in (("monitor", monitor), ("work", work)):
            target = getattr(info_ref._obj, field)
            target.left, target.top, target.right, target.bottom = self._in_thread_space(rect, handle)
        return 1

    def _GetCursorPos(self, point_ref):
        x, y = self.cursor
        handle = self._monitor_for((x, y, x + 1, y + 1), 2, self._physical_screens())
        point_ref._obj.x, point_ref._obj.y = self._in_thread_space((x, y), handle)
        return 1

    def _GetAncestor(self, _hwnd, _flag):
        return 0x200

    def _GetWindowRect(self, _hwnd, rect_ref):
        handle = self._monitor_for(self.window, 2, self._physical_screens())
        rect = rect_ref._obj
        rect.left, rect.top, rect.right, rect.bottom = self._in_thread_space(self.window, handle)
        return 1

    def _scale_factor(self, handle, factor_ref):
        factor_ref._obj.value = self.listed[handle]
        return 0

    def _dpi_for_monitor(self, handle, kind, x_ref, y_ref):
        """MDT_EFFECTIVE_DPI (0) as the calling thread sees it: the screen's own DPI to a
        per-monitor-aware thread, the system's to a system-aware one."""
        if kind != 0:
            return -2147024809  # E_INVALIDARG
        value = self.dpi[handle] if self.context == -4 else self.SYSTEM_DPI
        x_ref._obj.value = y_ref._obj.value = value
        return 0


@unittest.skipUnless(sys.platform == "win32", "the Windows anchor; the Mac anchor lives on mac-port")
class TheMonitorAndPixelSpaceTests(unittest.TestCase):
    """Review R2 (2026-10-10): the matrix above starts from a work area already chosen,
    so it never tested which monitor Windows is asked for, or in which pixels. M03
    (DEFAULTTOPRIMARY for DEFAULTTONEAREST) and M04 (never switching to physical pixels)
    both passed it. Here a fake private user32 answers the way Windows does."""

    UPPER_PHYSICAL = (704, -1440, 3264, -30)
    UPPER_SYSTEM_DPI = (1056, -2160, 4896, -45)

    def read(self, desktop, call):
        with patch.object(menu_anchor.ctypes, "WinDLL", side_effect=desktop.dll, create=True):
            return call()

    def test_a_point_off_every_screen_gets_the_nearest_screen(self):
        # Right of the upper screen: 136 px from it, 700 px from the primary.
        desktop = FakeDesktop()
        found = self.read(desktop, lambda: menu_anchor.work_area_at_point(3400, -700, physical=True))
        self.assertEqual(found, (self.UPPER_PHYSICAL, 1.0))
        self.assertEqual(desktop.flags, [2])

    def test_a_physical_read_switches_the_thread_and_puts_it_back(self):
        desktop = FakeDesktop()
        found = self.read(desktop, lambda: menu_anchor.work_area_at_point(1984, -90, physical=True))
        self.assertEqual(found, (self.UPPER_PHYSICAL, 1.0))
        self.assertEqual(desktop.switches, [-4, FakeDesktop.SYSTEM_AWARE])
        self.assertEqual(desktop.context, FakeDesktop.SYSTEM_AWARE)

    def test_a_read_that_fails_still_puts_the_thread_back(self):
        desktop = FakeDesktop(info="raise")
        self.assertIsNone(self.read(desktop, lambda: menu_anchor.work_area_at_point(1984, -90, physical=True)))
        self.assertEqual(desktop.switches, [-4, FakeDesktop.SYSTEM_AWARE])
        self.assertEqual(desktop.context, FakeDesktop.SYSTEM_AWARE)

    def test_a_system_dpi_read_never_switches_the_thread(self):
        # In system-DPI pixels every screen is drawn at the system's scale (150% here).
        desktop = FakeDesktop()
        found = self.read(desktop, lambda: menu_anchor.work_area_at_point(2976, -135, physical=False))
        self.assertEqual(found, (self.UPPER_SYSTEM_DPI, 1.5))
        self.assertEqual(desktop.switches, [])

    def test_a_custom_scale_is_read_exactly(self):
        # Review B12 (2026-10-10): GetScaleFactorForMonitor answers from a fixed list
        # (100, 120, 125, 140, 150, ...), so a custom scale between two steps reads as
        # one of them; read low (130% as 125% here), the menu's window came out shorter
        # than its content. The monitor's effective DPI (125 at 130%) is exact.
        desktop = FakeDesktop(dpi={2: 125}, listed={2: 125})
        found = self.read(desktop, lambda: menu_anchor.work_area_at_point(1984, -90, physical=True))
        self.assertEqual(found, (self.UPPER_PHYSICAL, 125 / 96))
        root = SimpleNamespace(winfo_id=lambda: 0x100)
        self.assertEqual(self.read(desktop, lambda: menu_anchor.read_pill_window(root)).scale, 125 / 96)

    def test_a_dpi_that_cannot_be_right_is_not_used(self):
        # Review T-8 (N31): 96..480 DPI is 100% to 500%. Anything else falls back to the
        # listed scale instead of a zero or absurd menu height.
        for dpi in (0, 95, 481, 1000):
            with self.subTest(dpi=dpi):
                desktop = FakeDesktop(dpi={2: dpi})
                found = self.read(desktop, lambda: menu_anchor.work_area_at_point(1984, -90, physical=True))
                self.assertEqual(found, (self.UPPER_PHYSICAL, 1.0))

    def test_without_the_dpi_the_listed_scale_still_answers(self):
        desktop = FakeDesktop()
        desktop.shcore = SimpleNamespace(GetScaleFactorForMonitor=_Export(desktop._scale_factor))
        found = self.read(desktop, lambda: menu_anchor.work_area_at_point(1984, -90, physical=True))
        self.assertEqual(found, (self.UPPER_PHYSICAL, 1.0))

    def test_the_pointer_is_read_in_the_pixels_asked_for(self):
        desktop = FakeDesktop()
        self.assertEqual(self.read(desktop, lambda: menu_anchor.cursor_position(physical=True)), (1984, -90))
        self.assertEqual(self.read(desktop, lambda: menu_anchor.cursor_position(physical=False)), (2976, -135))
        self.assertEqual(desktop.switches, [-4, FakeDesktop.SYSTEM_AWARE])

    def test_the_pill_window_is_read_in_physical_pixels_on_the_nearest_screen(self):
        # A Pill stranded just right of the upper screen, as when a monitor goes away.
        desktop = FakeDesktop()
        root = SimpleNamespace(winfo_id=lambda: 0x100)
        reading = self.read(desktop, lambda: menu_anchor.read_pill_window(root))
        self.assertEqual(reading, menu_anchor.PillWindow(rect=(3300, -760, 3600, -688),
                                                         work=self.UPPER_PHYSICAL, scale=1.0))
        self.assertEqual(desktop.flags, [2])
        self.assertEqual(desktop.context, FakeDesktop.SYSTEM_AWARE)

    def test_no_answer_from_windows_is_none(self):
        for info in ("fail", "empty"):
            with self.subTest(info=info):
                desktop = FakeDesktop(info=info)
                self.assertIsNone(self.read(desktop, lambda: menu_anchor.work_area_at_point(1984, -90, physical=True)))


if __name__ == "__main__":
    unittest.main()
