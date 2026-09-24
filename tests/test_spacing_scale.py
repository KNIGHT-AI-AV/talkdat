from __future__ import annotations

import re
import unittest
from pathlib import Path
import ast

UI_SOURCE = Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py"
NATIVE_LAYOUT_SOURCES = (
    UI_SOURCE,
    UI_SOURCE.parent / "ui" / "onboarding.py",
    UI_SOURCE.parent / "ui" / "flow_console.py",
)

# Every gap in the interface is a multiple of four. The step is what matters,
# not the particular numbers: a reader can tell 12 from 16 and cannot tell 14
# from 16, so a scale with a visible step is the difference between spacing
# that looks decided and spacing that looks accidental.
SPACING_STEP = 4

SCALAR = re.compile(r"\bpad[xy]=(\d+)\b")
PAIR = re.compile(r"\bpad[xy]=\((\d+),\s*(\d+)\)")


def spacing_values(source: str) -> set[int]:
    values = {int(v) for v in SCALAR.findall(source)}
    for first, second in PAIR.findall(source):
        values.update({int(first), int(second)})
    return values


class SpacingScaleTests(unittest.TestCase):
    """The interface used thirteen different gaps, chosen one at a time.

    padx and pady between them held 0, 3, 4, 5, 6, 8, 10, 11, 12, 14, 16, 18
    and 20 across 318 places. Nothing was wrong with any single one; the
    problem was that no two panels agreed, so every surface looked slightly
    unlike every other and none of it looked deliberate.

    Snapping to a four-pixel step moved 154 of them by at most two pixels and
    left one scale. This test is what stops the thirteen coming back, because
    the next person to add a widget will copy whatever is nearest and the drift
    restarts from there.
    """

    def setUp(self) -> None:
        self.source = UI_SOURCE.read_text(encoding="utf-8")

    def test_every_gap_sits_on_the_four_pixel_step(self) -> None:
        offenders = sorted(v for v in spacing_values(self.source) if v % SPACING_STEP)
        self.assertEqual(
            offenders,
            [],
            f"padding values off the {SPACING_STEP}px scale: {offenders}. "
            f"Round to the nearest multiple of {SPACING_STEP} rather than adding a new step.",
        )

    def test_the_scale_stays_small_enough_to_mean_something(self) -> None:
        """A scale with a step for every occasion is not a scale.

        Six or seven steps covers tight, snug, base, roomy and loose with room
        to spare. Past that the values stop carrying meaning and the constraint
        stops doing any work.
        """
        values = spacing_values(self.source)
        self.assertLessEqual(
            len(values),
            8,
            f"{len(values)} distinct spacing values: {sorted(values)}",
        )

    def test_the_snap_rule_is_the_one_that_was_applied(self) -> None:
        """Ties round up, so the pass adds breathing room rather than removing it.

        Written down because the next person to add a value needs the same
        rule, and "nearest multiple of four" alone does not settle 6, 10, 14
        or 18 -- which were four of the six values that actually moved.
        """
        def snap(n: int) -> int:
            return ((n + 2) // SPACING_STEP) * SPACING_STEP

        self.assertEqual([snap(n) for n in (3, 5, 6, 10, 11, 14, 18)], [4, 4, 8, 12, 12, 16, 20])
        # Values already on the scale must not move.
        for value in (0, 4, 8, 12, 16, 20):
            with self.subTest(value=value):
                self.assertEqual(snap(value), value)

    def test_native_pixel_layout_literals_use_a_scale_helper(self) -> None:
        pixel_keywords = {
            "padx",
            "pady",
            "ipadx",
            "ipady",
            "padding",
            "wraplength",
            "rowheight",
            "arrowsize",
        }
        offenders: list[str] = []

        def nonzero_literal(node: ast.AST) -> bool:
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return bool(node.value)
            if isinstance(node, (ast.Tuple, ast.List)) and all(
                isinstance(item, ast.Constant) and isinstance(item.value, (int, float))
                for item in node.elts
            ):
                return any(bool(item.value) for item in node.elts)
            return False

        for path in NATIVE_LAYOUT_SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.keyword)
                    and node.arg in pixel_keywords
                    and nonzero_literal(node.value)
                ):
                    offenders.append(f"{path.name}:{node.lineno}:{node.arg}")
        self.assertEqual(
            offenders,
            [],
            "nonzero native pixel metrics must use ui_scale.spacing/px or self.px",
        )

    def test_scaled_overlay_spacing_still_uses_the_four_pixel_step(self) -> None:
        """A scale helper must not become a hiding place for arbitrary gaps."""

        tree = ast.parse(self.source)
        offenders: list[str] = []

        def literal_values(node: ast.AST) -> list[float]:
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return [float(node.value)]
            if isinstance(node, (ast.Tuple, ast.List)) and all(
                isinstance(item, ast.Constant) and isinstance(item.value, (int, float))
                for item in node.elts
            ):
                return [float(item.value) for item in node.elts]
            return []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            helper = node.func
            is_spacing_helper = (
                isinstance(helper, ast.Attribute)
                and helper.attr == "spacing"
            ) or (
                isinstance(helper, ast.Name)
                and helper.id == "space"
            )
            if not is_spacing_helper:
                continue
            values = literal_values(node.args[0])
            if any(value and value % SPACING_STEP for value in values):
                offenders.append(
                    f"{UI_SOURCE.name}:{node.lineno}:{ast.unparse(node.args[0])}"
                )

        self.assertEqual(
            offenders,
            [],
            "scaled overlay spacing values must remain on the four-pixel step",
        )

    def test_universal_chrome_has_no_raw_pixel_geometry(self) -> None:
        """Shared titlebar affordances must grow with the same DPI contract.

        Canvas dimensions and drawing coordinates are physical pixels, as are
        ``place`` offsets.  Tk does not scale any of them when its font scale
        changes, which previously left the rainbow brush and help action at
        half size and in the wrong titlebar lane on a 200% display.
        """

        tree = ast.parse(self.source)
        method_names = {
            "_make_glass_titlebar",
        }
        methods = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name in method_names
        }
        self.assertEqual(set(methods), method_names)
        offenders: list[str] = []

        def literal_number(node: ast.AST) -> float | None:
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return float(node.value)
            if (
                isinstance(node, ast.UnaryOp)
                and isinstance(node.op, (ast.UAdd, ast.USub))
                and isinstance(node.operand, ast.Constant)
                and isinstance(node.operand.value, (int, float))
            ):
                value = float(node.operand.value)
                return -value if isinstance(node.op, ast.USub) else value
            return None

        for method_name, method in methods.items():
            for node in ast.walk(method):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                call_name = (
                    function.attr
                    if isinstance(function, ast.Attribute)
                    else function.id
                    if isinstance(function, ast.Name)
                    else ""
                )
                if call_name in {"Canvas", "Frame"}:
                    for keyword in node.keywords:
                        value = literal_number(keyword.value)
                        if keyword.arg in {"width", "height"} and value not in {None, 0.0, 1.0}:
                            offenders.append(
                                f"{method_name}:{node.lineno}:{call_name}.{keyword.arg}={value:g}"
                            )
                if call_name == "place":
                    for keyword in node.keywords:
                        value = literal_number(keyword.value)
                        if keyword.arg in {"x", "y", "width", "height"} and value not in {None, 0.0, 1.0, -1.0}:
                            offenders.append(
                                f"{method_name}:{node.lineno}:place.{keyword.arg}={value:g}"
                            )
                if call_name in {"create_arc", "create_oval"}:
                    for index, coordinate in enumerate(node.args[:4]):
                        value = literal_number(coordinate)
                        if value is not None:
                            offenders.append(
                                f"{method_name}:{node.lineno}:{call_name}[{index}]={value:g}"
                            )

        self.assertEqual(
            offenders,
            [],
            "shared titlebar dimensions, place offsets, and Canvas coordinates must use ui_scale.px",
        )

    def test_interactive_focus_thickness_uses_the_scale_helper(self) -> None:
        offenders: list[str] = []
        for path in NATIVE_LAYOUT_SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.keyword) or node.arg != "highlightthickness":
                    continue
                value = node.value
                if (
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, (int, float))
                    and value.value >= 2
                ):
                    offenders.append(f"{path.name}:{node.lineno}:{value.value}")
        self.assertEqual(
            offenders,
            [],
            "interactive focus thickness of two pixels or more must scale with DPI",
        )

    def test_front_facing_native_type_never_drops_below_nine_points(self) -> None:
        offenders: list[str] = []
        for path in NATIVE_LAYOUT_SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.keyword) or node.arg != "font":
                    continue
                value = node.value
                if not isinstance(value, ast.Tuple) or len(value.elts) < 2:
                    continue
                size = value.elts[1]
                if isinstance(size, ast.Constant) and isinstance(size.value, int) and 0 < size.value < 9:
                    offenders.append(f"{path.name}:{node.lineno}:{size.value}pt")
        self.assertEqual(offenders, [], "front-facing native text below the 9pt floor")


if __name__ == "__main__":
    unittest.main()


FONT_FAMILY = re.compile(r'font=\("([^"]+)"')

# Faces that ship with Windows 10 and every later version. Anything outside
# this set has to be justified, because Tk does not report a missing family --
# it silently substitutes a default, and the widget renders in a font nobody
# chose on a machine nobody tested.
SAFE_ON_WINDOWS_10 = frozenset({
    "Segoe UI",
    "Segoe UI Semibold",
    "Segoe UI Light",
    "Segoe UI Black",
    "Consolas",
    "Courier New",
    "Arial",
    "Tahoma",
    # In-box since Windows 2000 and still shipped in Windows 10/11's base
    # font set. Added for the scratchpad's paper surface: ruled clay wants a
    # book face, and Georgia is the only serif on a clean install that was
    # actually designed for screens.
    "Georgia",
})


class TypographyTests(unittest.TestCase):
    """Two faces in the context menu did not exist on the machine running it.

    "Segoe UI Variable Text" and "Segoe UI Variable Display Semibold" arrived
    with Windows 11. On Windows 10 -- which is what this was developed on --
    Tk substitutes a default face without complaint, so the pill's context
    menu, the surface reached most often in the product, drew its title and
    subtitle in a font nobody picked. Nothing errors, nothing logs, and it
    only looks wrong if you already know what it should look like.

    "Cascadia Mono" was the same trap one step further out: it arrives with
    Windows Terminal rather than with Windows, so it was present on the
    development machine and would be missing on a clean install -- the worst
    version, because testing locally proves nothing.
    """

    def setUp(self) -> None:
        self.source = UI_SOURCE.read_text(encoding="utf-8")

    def test_every_font_ships_with_windows_10(self) -> None:
        used = set(FONT_FAMILY.findall(self.source))
        unsafe = sorted(used - SAFE_ON_WINDOWS_10)
        self.assertEqual(
            unsafe, [],
            f"font families that may not exist on a customer's machine: {unsafe}. "
            "Tk substitutes silently, so this cannot be caught by running the app.",
        )

    def test_one_monospace_face_not_two(self) -> None:
        """Consolas and Cascadia Mono were both in use, three widgets to one."""
        used = set(FONT_FAMILY.findall(self.source))
        monospace = {family for family in used if family in {"Consolas", "Cascadia Mono", "Courier New"}}
        self.assertLessEqual(len(monospace), 1, f"more than one monospace face: {sorted(monospace)}")
