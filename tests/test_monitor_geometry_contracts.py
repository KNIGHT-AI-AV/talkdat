from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest
from unittest import mock

from knight_flow.monitors import Monitor, centre_on
from knight_flow.overlay import Overlay


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"

WORK_AREAS = {
    "primary": (0, 0, 1920, 1040),
    "right": (1920, 40, 3840, 1080),
    "negative_left": (-1920, 0, 0, 1040),
    "negative_above": (0, -1080, 1920, -40),
}


def function_source(name: str) -> str:
    source = OVERLAY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {name!r}, found {len(matches)}")
    return ast.get_source_segment(source, matches[0]) or ""


def geometry_parts(value: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", value)
    if match is None:
        raise AssertionError(f"not a complete Tk geometry: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


class MonitorGeometryFoundationTests(unittest.TestCase):
    def test_centring_preserves_negative_monitor_origins_and_work_area_insets(self) -> None:
        for name, (left, top, right, bottom) in WORK_AREAS.items():
            with self.subTest(monitor=name):
                monitor = Monitor(
                    left,
                    top,
                    right,
                    bottom,
                    left,
                    top,
                    right,
                    bottom,
                    name == "primary",
                )
                width, height, x, y = centre_on(monitor, 900, 640)
                self.assertGreaterEqual(x, left + 16)
                self.assertGreaterEqual(y, top + 16)
                self.assertLessEqual(x + width, right - 16)
                self.assertLessEqual(y + height, bottom - 16)

    def test_utility_geometry_uses_the_pill_work_area_for_all_coordinate_quadrants(self) -> None:
        overlay = Overlay.__new__(Overlay)
        overlay.config = {"ui": {"popup_monitor": "pill"}}
        for name, rect in WORK_AREAS.items():
            with self.subTest(monitor=name), mock.patch.object(
                overlay,
                "_pill_monitor_work_area",
                return_value=rect,
            ):
                width, height, x, y = geometry_parts(overlay._utility_geometry("900x640"))
                left, top, right, bottom = rect
                self.assertGreaterEqual(x, left + 8)
                self.assertGreaterEqual(y, top + 8)
                self.assertLessEqual(x + width, right - 8)
                self.assertLessEqual(y + height, bottom - 8)


class MonitorGeometrySourceContracts(unittest.TestCase):
    def test_edge_and_grip_resizing_use_the_window_monitor_not_primary_dimensions(self) -> None:
        for function in ("_bind_edge_resize", "_install_utility_resize_grip"):
            with self.subTest(function=function):
                block = function_source(function)
                self.assertIn("self._window_monitor_work_area(window)", block)
                self.assertIn("self._logical_work_area()", block)
                self.assertNotIn("winfo_screenwidth", block)
                self.assertNotIn("winfo_screenheight", block)

    def test_transients_query_the_host_or_pill_monitor_and_keep_signed_coordinates(self) -> None:
        expected = {
            # X-742: every Pill message is placed by _flag_build on the
            # monitor _flag_work_area names: the Pill's own.
            "_flag_work_area": "self._pill_monitor_work_area()",
            "open_more_menu": "self._window_monitor_work_area(window)",
            "_open_help_note": "self._window_monitor_work_area(window)",
            "show_ramble_indicator": "list_monitors()",
        }
        for function, monitor_call in expected.items():
            with self.subTest(function=function):
                block = function_source(function)
                self.assertIn(monitor_call, block)
                self.assertNotIn("abs(", block, "absolute coordinates would break left/above monitors")

    def test_ramble_release_persists_only_after_monitor_clamping(self) -> None:
        indicator = function_source("show_ramble_indicator")
        block = indicator[indicator.index("def release("):]
        self.assertIn("self._window_monitor_work_area(bar)", block)
        self.assertLess(block.index("bar.geometry"), block.index("ramble_indicator_pos"))
        self.assertIn("bar.winfo_x()", block)
        self.assertIn("bar.winfo_y()", block)


if __name__ == "__main__":
    unittest.main()
