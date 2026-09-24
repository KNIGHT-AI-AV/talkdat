"""The Windows Pill Panel remains usable at 100%, 150%, and 200% DPI.

The action accordion can be taller than a 1080p work area at high scale.  The
panel must keep full-size controls, clamp only its viewport, and translate every
pointer/drag coordinate through the Canvas scroll offset.  These tests exercise
the geometry without needing a physical high-DPI monitor.
"""

from __future__ import annotations

import unittest
import inspect
from types import SimpleNamespace

from knight_flow.overlay import Overlay


class FakeScrolledCanvas:
    def __init__(self, *, content_height: int, viewport_height: int, offset: int = 0) -> None:
        self.content_height = int(content_height)
        self.viewport_height = int(viewport_height)
        self.offset = int(offset)
        self.moveto_calls: list[float] = []
        self.scroll_calls: list[tuple[int, str]] = []

    def canvasy(self, y: int) -> float:
        return float(self.offset + int(y))

    def winfo_width(self) -> int:
        return 640

    def cget(self, name: str) -> int:
        if name == "width":
            return 640
        raise KeyError(name)

    def yview_moveto(self, fraction: float) -> None:
        self.moveto_calls.append(float(fraction))
        requested = int(round(float(fraction) * self.content_height))
        self.offset = max(0, min(requested, self.content_height - self.viewport_height))

    def yview_scroll(self, rows: int, units: str) -> None:
        self.scroll_calls.append((int(rows), str(units)))
        requested = self.offset + int(rows)
        self.offset = max(0, min(requested, self.content_height - self.viewport_height))


class FakeWindow:
    def __init__(self) -> None:
        self.geometries: list[str] = []

    def geometry(self, value: str) -> None:
        self.geometries.append(str(value))


class FakeResizeCanvas:
    def __init__(self) -> None:
        self.configured: dict[str, object] = {}
        self.placed: dict[str, object] = {}

    def configure(self, **kwargs: object) -> None:
        self.configured.update(kwargs)

    def place_configure(self, **kwargs: object) -> None:
        self.placed.update(kwargs)

def scaled_overlay(scale: float, *, expanded: bool = True) -> Overlay:
    overlay = Overlay.__new__(Overlay)
    overlay.MENU_ROW_TOP = round(12 * scale)
    overlay.MENU_ROW_PITCH = round(44 * scale)
    overlay.MENU_ROW_HEIGHT = round(40 * scale)
    overlay.MENU_WIDTH = round(320 * scale)
    overlay.MENU_FEATURES_WIDTH = round(276 * scale)
    overlay._menu_show_more = bool(expanded)
    overlay._menu_reset_armed = False
    overlay.context_menu_hover = ""
    overlay.context_menu_press_state = None
    overlay.context_menu_window = None
    overlay.context_menu_canvas = None
    overlay.context_menu_scrollbar = None
    overlay._context_menu_box = None
    overlay._context_menu_content_height = 0
    overlay._context_menu_viewport_limit = 0
    overlay.config = {"cleanup": {"format_intensity": "executive"}}
    overlay.callbacks = {}
    overlay._draw_context_menu = lambda: None
    return overlay


class HighDpiViewportGeometryTests(unittest.TestCase):
    def test_collapsed_and_expanded_geometry_at_supported_scales(self) -> None:
        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                collapsed = scaled_overlay(scale, expanded=False)
                expanded = scaled_overlay(scale, expanded=True)
                collapsed_content = collapsed._context_menu_window_height(
                    len(collapsed._context_menu_rows())
                )
                expanded_content = expanded._context_menu_window_height(
                    len(expanded._context_menu_rows())
                )
                collapsed_viewport = collapsed._context_menu_viewport_height(
                    collapsed_content, (0, 0, 1920, 1080)
                )
                expanded_viewport = expanded._context_menu_viewport_height(
                    expanded_content, (0, 0, 1920, 1080)
                )

                self.assertLessEqual(collapsed_viewport, 1080)
                self.assertLessEqual(expanded_viewport, 1080)
                self.assertEqual(collapsed_viewport, collapsed_content)
                # X-339: "expanded" grew DOWN until it pushed past the
                # screen (the founder's screenshot); the Features panel now
                # slides SIDEWAYS. Height is identical in both states; the
                # growth happens in width, scaled like every other metric.
                self.assertEqual(expanded_content, collapsed_content)
                self.assertEqual(expanded_viewport, expanded_content)
                self.assertEqual(
                    expanded._menu_total_width(),
                    expanded.MENU_WIDTH + expanded.MENU_FEATURES_WIDTH,
                )
                self.assertEqual(collapsed._menu_total_width(), collapsed.MENU_WIDTH)

    def test_1080p_at_200_percent_keeps_full_rows_and_scrolls_the_overflow(self) -> None:
        # History: the expanded menu was 1536 tall at 200% and HAD to
        # scroll inside 1080p. X-339 folded the flat list permanently
        # (features slide sideways), so the whole menu fits; the scrolling
        # contract is preserved against a shorter work area instead.
        overlay = scaled_overlay(2.0, expanded=True)
        content = overlay._context_menu_window_height(len(overlay._context_menu_rows()))
        viewport = overlay._context_menu_viewport_height(content, (0, 0, 1920, 1080))

        self.assertEqual(content, 1008)
        self.assertEqual(viewport, 1008)
        self.assertEqual(overlay.MENU_ROW_HEIGHT, 80, "DPI repair must not shrink controls")
        short_viewport = overlay._context_menu_viewport_height(content, (0, 0, 1920, 700))
        self.assertLess(short_viewport, content,
                        "a short work area must still clamp and scroll")

    def test_taskbar_reduced_work_area_is_also_respected(self) -> None:
        overlay = scaled_overlay(2.0, expanded=True)
        content = overlay._context_menu_window_height(len(overlay._context_menu_rows()))
        viewport = overlay._context_menu_viewport_height(content, (0, 0, 1920, 1040))
        self.assertEqual(viewport, 1008)

    def test_expanding_near_the_bottom_repositions_inside_the_work_area(self) -> None:
        overlay = scaled_overlay(2.0, expanded=True)
        window = FakeWindow()
        canvas = FakeResizeCanvas()
        overlay.context_menu_window = window
        overlay.context_menu_canvas = canvas
        overlay._context_menu_box = (640, 68, 640, 920)
        overlay._context_menu_viewport_limit = 1048
        overlay._logical_work_area = lambda: (0, 0, 1920, 1080)
        overlay._apply_window_region = lambda *_args: None

        overlay._resize_context_menu(1048, content_height=1536)

        self.assertEqual(overlay._context_menu_box, (640, 16, 640, 1048))
        self.assertEqual(window.geometries[-1], "640x1048+640+16")
        self.assertEqual(
            window.geometries,
            ["640x1048+640+16"],
            "ordinary menu chrome must settle in one geometry write without a region recut",
        )
        self.assertEqual(canvas.placed, {"x": 0, "y": 0, "width": 640, "height": 1048})

    def test_primary_route_and_finish_switches_are_pinned_above_the_scrolling_body(self) -> None:
        source = inspect.getsource(Overlay._draw_context_menu)
        self.assertIn('tags=("menu_pinned",)', source)
        self.assertIn('canvas.move("menu_pinned", 0, pinned_offset)', source)
        self.assertIn('canvas.tag_raise("menu_pinned")', source)


class KeyboardFocusRevealTests(unittest.TestCase):
    def setUp(self) -> None:
        # X-339: the full menu fits inside 1080p now (features slide
        # sideways). The reveal contract needs a CLIPPED viewport to prove
        # anything, so this suite pins it against a 700px work area.
        self.overlay = scaled_overlay(2.0, expanded=True)
        self.content = self.overlay._context_menu_window_height(len(self.overlay._context_menu_rows()))
        self.viewport = self.overlay._context_menu_viewport_height(self.content, (0, 0, 1920, 700))
        self.assertLess(self.viewport, self.content, "the reveal premise needs overflow")
        self.canvas = FakeScrolledCanvas(content_height=self.content, viewport_height=self.viewport)
        self.overlay.context_menu_canvas = self.canvas
        self.overlay._context_menu_box = (100, 16, self.overlay.MENU_WIDTH, self.viewport)
        self.overlay._context_menu_content_height = self.content

    def test_end_reveals_the_reset_footer_and_home_returns_to_the_route_switch(self) -> None:
        self.overlay.context_menu_hover = Overlay.MENU_ROUTE_FOCUS_STOPS[0][0]
        self.overlay._context_menu_key(SimpleNamespace(keysym="End"))

        self.assertEqual(self.overlay.context_menu_hover, Overlay.MENU_RESET_FOCUS)
        self.assertEqual(self.canvas.offset, self.content - self.viewport)
        self.assertGreater(self.canvas.offset, 0)
        self.assertTrue(self.canvas.moveto_calls)

        self.overlay._context_menu_key(SimpleNamespace(keysym="Home"))
        self.assertEqual(self.overlay.context_menu_hover, Overlay.MENU_ROUTE_FOCUS_STOPS[0][0])
        self.assertEqual(self.canvas.offset, 0)

    def test_arrow_navigation_reveals_each_newly_focused_row(self) -> None:
        order = self.overlay._context_menu_focus_order()
        self.overlay.context_menu_hover = order[-3]
        self.overlay._context_menu_reveal_focus()
        first_offset = self.canvas.offset
        self.overlay._context_menu_key(SimpleNamespace(keysym="Down"))

        self.assertGreaterEqual(self.canvas.offset, first_offset)
        bounds = self.overlay._context_menu_focus_bounds(self.overlay.context_menu_hover)
        self.assertIsNotNone(bounds)
        assert bounds is not None
        self.assertGreaterEqual(bounds[0], self.canvas.offset + self.overlay.MENU_ROWS_Y0)
        self.assertLessEqual(bounds[1], self.canvas.offset + self.canvas.viewport_height)


class ScrollAwarePointerAndReorderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.overlay = scaled_overlay(2.0, expanded=False)
        content = self.overlay._context_menu_window_height(len(self.overlay._context_menu_rows()))
        # Force a clipped viewport so the coordinate contract can be tested
        # independently of the scale-specific work-area fit.
        viewport = 480
        self.canvas = FakeScrolledCanvas(
            content_height=content,
            viewport_height=viewport,
            offset=2 * self.overlay.MENU_ROW_PITCH,
        )
        self.overlay.context_menu_canvas = self.canvas
        self.overlay._context_menu_box = (100, 16, self.overlay.MENU_WIDTH, viewport)
        self.overlay._context_menu_content_height = content

    def test_hit_testing_uses_scrolled_content_coordinates(self) -> None:
        viewport_y = self.overlay.MENU_ROWS_Y0 + 8
        content_y = self.overlay._context_menu_content_y(viewport_y)
        action = self.overlay._context_menu_action_at(content_y)

        self.assertEqual(action, "history")
        self.assertNotEqual(action, "settings")

    def test_release_dispatches_the_visible_scrolled_row(self) -> None:
        dispatched: list[str] = []
        self.overlay._activate_context_menu_action = lambda action: dispatched.append(action) or "break"
        self.overlay.context_menu_press_state = {
            "action": "history",
            "y": self.overlay.MENU_ROWS_Y0 + 2 * self.overlay.MENU_ROW_PITCH,
            "timer": None,
            "dragging": False,
            "order": [row[0] for row in self.overlay._context_menu_rows()],
        }
        event = SimpleNamespace(x=100, y=self.overlay.MENU_ROWS_Y0 + 8)

        self.assertEqual(self.overlay._context_menu_release(event), "break")
        self.assertEqual(dispatched, ["history"])

    def test_pinned_switch_hit_testing_stays_in_viewport_coordinates(self) -> None:
        routes: list[str] = []
        self.overlay._handle_route_tap = routes.append
        self.overlay._context_menu_press(SimpleNamespace(x=500, y=50))
        # X-525: two positions, so x=500 is the RIGHT half. The point of this
        # test is that the tap is hit-tested in viewport coordinates at all,
        # not which half it lands in.
        self.assertEqual(routes, ["byok"])

    def test_drag_reorder_maps_the_pointer_through_the_scroll_offset(self) -> None:
        order = [row[0] for row in self.overlay._context_menu_rows()]
        self.overlay.context_menu_press_state = {
            "action": order[0],
            "y": self.overlay.MENU_ROWS_Y0,
            "timer": None,
            "dragging": True,
            "order": list(order),
        }
        # Viewport row zero represents content row two after scrolling.
        event = SimpleNamespace(
            x=20,
            y=self.overlay.MENU_ROWS_Y0 + self.overlay.MENU_ROW_HEIGHT // 2 + 8,
        )
        self.assertEqual(self.overlay._context_menu_drag_motion(event), "break")

        reordered = self.overlay.context_menu_press_state["order"]
        self.assertEqual(reordered[2], order[0])
        self.assertEqual(sorted(reordered), sorted(order), "reorder must not lose or duplicate callbacks")


if __name__ == "__main__":
    unittest.main()
