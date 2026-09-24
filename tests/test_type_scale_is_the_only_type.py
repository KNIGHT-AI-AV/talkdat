from __future__ import annotations

import ast
import unittest
from pathlib import Path

from knight_flow.ui import type_scale

KNIGHT_FLOW = Path(__file__).resolve().parents[1] / "knight_flow"

#: A string in the family slot only means a font if it names one. Without this
#: the guard reads every two-element tuple in the file -- coordinates, sizes,
#: grid spans -- as type, and reports 0pt and 44pt "fonts".
FONT_FAMILY_NAMES = {
    "Consolas", "Segoe UI", "Courier New", "Cascadia Mono", "Cascadia Code",
    "Arial", "Helvetica", "Tahoma", "Verdana",
    "TkDefaultFont", "TkFixedFont", "TkTextFont", "TkMenuFont",
}
TYPED_SOURCES = (
    KNIGHT_FLOW / "overlay.py",
    KNIGHT_FLOW / "ui" / "onboarding.py",
    KNIGHT_FLOW / "ui" / "flow_console.py",
    KNIGHT_FLOW / "ui" / "atelier_controls.py",
)


def _literal_font_sizes(source: Path) -> list[tuple[int, int]]:
    """Every hard-coded type size in a file, as (line, size).

    Read from the AST rather than with a regular expression, and that choice is
    load-bearing: a guard written against the text of the file fires on its own
    explanatory comment the first time someone quotes the banned line while
    explaining why it is banned. That happened to the deploy guard in this repo.
    An AST cannot see a comment at all, so the failure mode does not exist.

    Every ``(family, size)`` TUPLE is checked, not only the ones written
    directly at a ``font=``. The first version of this guard looked at the
    keyword, and two live sizes walked straight through it -- a 9pt bold
    ``chip_font = (BRAND_UI_FAMILY, 9, "bold")`` bound to a name three lines
    above its use, and a 10pt default argument on a helper. Both were then
    passed as ``font=chip_font``, which is not a tuple and so was not looked at.
    A check is only as good as the shape it assumes the defect will take.
    """

    tree = ast.parse(source.read_text(encoding="utf-8"))
    found: list[tuple[int, int]] = []

    def note_tuple(node: ast.AST) -> None:
        if not isinstance(node, ast.Tuple) or not (2 <= len(node.elts) <= 3):
            return
        head, size = node.elts[0], node.elts[1]
        if isinstance(head, ast.Name):
            # BRAND_UI_FAMILY, scratch_font_family, family, chip_font...
            head_is_family = "family" in head.id.lower() or "font" in head.id.lower()
        elif isinstance(head, ast.Constant) and isinstance(head.value, str):
            head_is_family = head.value in FONT_FAMILY_NAMES
        else:
            head_is_family = False
        if head_is_family and isinstance(size, ast.Constant):
            if isinstance(size.value, int) and not isinstance(size.value, bool):
                found.append((node.lineno, size.value))

    for node in ast.walk(tree):
        note_tuple(node)
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "size" and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, int) and keyword.value.value > 0:
                        found.append((keyword.lineno, keyword.value.value))
    return found


class TheScaleIsTheOnlyTypeTests(unittest.TestCase):
    """A documented scale that nothing enforces is a document, not a scale.

    ``type_scale`` was written to end exactly this, and its docstring names the
    symptom: "85% of every window sitting at 9-11pt, so nothing was a heading,
    nothing was body." It was then applied to onboarding and the console and
    never to overlay.py -- which holds 208 of the app's 266 type sites. Measured
    before this guard existed: 144 literal sizes in that one file, of which 61
    sat at 9pt, BELOW the floor the module says nothing ships under, and 12 more
    were off the scale entirely.

    Nothing was wrong with the module. Nothing checked it.
    """

    def test_no_surface_hard_codes_a_font_size(self) -> None:
        offenders: list[str] = []
        for source in TYPED_SOURCES:
            for line, size in _literal_font_sizes(source):
                offenders.append(f"{source.name}:{line} renders {size}pt directly")
        self.assertEqual(
            offenders,
            [],
            "Type sizes come from knight_flow.ui.type_scale, never from a number "
            "written at the call site. Pick the step for what the text IS "
            f"(one of {type_scale.SCALE}), or type_scale.snap() if it is computed.\n  "
            + "\n  ".join(offenders),
        )

    def test_nothing_renders_below_the_floor(self) -> None:
        for size in type_scale.SCALE:
            self.assertGreaterEqual(
                size,
                type_scale.FLOOR,
                f"{size}pt is under the {type_scale.FLOOR}pt floor",
            )

    def test_leading_gets_looser_as_type_gets_smaller(self) -> None:
        """Apple's rule, and the reason it is a rule.

        Large text is separated by its own height and reads as loose at body
        leading; a caption in a dense settings panel is the line most likely to
        be misread and needs the most air relative to its size. So the ratio has
        to move in the opposite direction to the size, at every step.
        """

        ratios = [type_scale.leading_ratio(step) for step in type_scale.SCALE]
        self.assertEqual(
            ratios,
            sorted(ratios),
            f"largest-to-smallest leading must never tighten: {ratios}",
        )
        self.assertLess(type_scale.leading_ratio(type_scale.DISPLAY), 1.2)
        self.assertGreater(type_scale.leading_ratio(type_scale.CAPTION), 1.4)

    def test_tracking_tightens_as_type_grows(self) -> None:
        """Negative at display, zero at body, positive at caption."""

        tracking = [type_scale.tracking(step) for step in type_scale.SCALE]
        self.assertEqual(
            tracking,
            sorted(tracking),
            f"tracking must open up as type shrinks: {tracking}",
        )
        self.assertLess(type_scale.tracking(type_scale.DISPLAY), 0)
        self.assertEqual(type_scale.tracking(type_scale.BODY), 0)
        self.assertGreater(type_scale.tracking(type_scale.CAPTION), 0)

    def test_extra_leading_never_asks_tk_for_the_impossible(self) -> None:
        """Tk's spacing options only ever ADD to the font's own linespace.

        Segoe UI already renders about 1.33x its size, which is looser than
        DISPLAY wants. A negative number there would be silently ignored by Tk
        while reading, in our own source, as though we had tightened it.
        """

        for step in type_scale.SCALE:
            generous_natural = step * 2.0
            self.assertEqual(type_scale.extra_leading_px(step, generous_natural), 0)
            self.assertGreaterEqual(type_scale.extra_leading_px(step, 0), 0)

        self.assertGreater(
            type_scale.extra_leading_px(type_scale.BODY, type_scale.BODY * 1.33),
            0,
            "body copy must gain leading over the font's own linespace",
        )

    def test_a_reading_surface_is_set_looser_than_dense_ui(self) -> None:
        """The same size is not the same leading in the two reading contexts.

        A settings row and a page the customer writes into are different
        reading tasks, and setting them identically gets one of them wrong.
        The bonus is the only knob, so the two can never cross over.
        """

        for step in type_scale.SCALE:
            self.assertGreater(
                type_scale.leading_ratio(step, prose=True),
                type_scale.leading_ratio(step),
                f"{step}pt prose must be looser than {step}pt UI",
            )

        # The scratchpad had reached 4px by hand before the scale covered it.
        # Landing within a pixel of an independently tuned value is the
        # evidence that the ratio is right rather than merely consistent.
        self.assertAlmostEqual(
            type_scale.extra_leading_px(type_scale.BODY, 21, prose=True),
            4,
            delta=1,
        )

    def test_every_computed_size_lands_on_the_scale(self) -> None:
        for candidate in range(1, 40):
            self.assertIn(type_scale.snap(candidate), type_scale.SCALE)
        self.assertEqual(type_scale.snap(9), type_scale.CAPTION)
        self.assertEqual(type_scale.snap(3), type_scale.FLOOR)


if __name__ == "__main__":
    unittest.main()
