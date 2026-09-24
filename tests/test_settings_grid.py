from __future__ import annotations

import ast
import unittest
from collections import defaultdict
from pathlib import Path

OVERLAY = Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py"

# The helpers that place a widget in a settings tab, and where the row number
# sits in each one's arguments. Both span the full two-column width: add_row
# puts its label in column 0 and its widget in column 1, and check spans both.
ROW_ARGUMENT = {"add_row": 1, "check": 3}


class Placement:
    """One claim on a rectangle of grid cells, and where it was made."""

    def __init__(self, row: int, first_column: int, span: int, line: int) -> None:
        self.row = row
        self.columns = range(first_column, first_column + max(1, span))
        self.line = line

    def overlaps(self, other: "Placement") -> bool:
        return self.row == other.row and bool(set(self.columns) & set(other.columns))


class Walker(ast.NodeVisitor):
    """Collect grid placements, keyed by the method the frame was built in.

    Scoping matters: `body`, `options` and `footer` are each used as a local
    frame name in several unrelated windows, and treating the bare name as
    global reports every one of them as colliding with the others.
    """

    def __init__(self) -> None:
        self.scope: list[str] = []
        self.found: dict[str, list[Placement]] = defaultdict(list)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def key(self, frame: ast.AST) -> str:
        # The outermost enclosing method, so a nested `def refresh()` that
        # grids into the same tab is still measured against it.
        if not isinstance(frame, ast.Name) or not self.scope:
            return ""
        return f"{self.scope[0]}::{frame.id}"

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)

        if isinstance(node.func, ast.Name) and node.func.id in ROW_ARGUMENT:
            index = ROW_ARGUMENT[node.func.id]
            if len(node.args) > index:
                row = constant(node.args[index])
                key = self.key(node.args[0])
                if key and row is not None:
                    self.found[key].append(Placement(row, 0, 2, node.lineno))
            return

        if isinstance(node.func, ast.Attribute) and node.func.attr == "grid":
            built = node.func.value
            if not (isinstance(built, ast.Call) and built.args):
                return
            key = self.key(built.args[0])
            keywords = {kw.arg: constant(kw.value) for kw in node.keywords}
            row = keywords.get("row")
            if key and row is not None:
                self.found[key].append(
                    Placement(row, keywords.get("column") or 0, keywords.get("columnspan") or 1, node.lineno)
                )


def constant(node: ast.AST) -> int | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, int) else None


def collisions() -> dict[str, list[tuple[int, int]]]:
    walker = Walker()
    walker.visit(ast.parse(OVERLAY.read_text(encoding="utf-8")))
    overlapping: dict[str, list[tuple[int, int]]] = {}
    for key, placements in walker.found.items():
        pairs = [
            (left.line, right.line)
            for index, left in enumerate(placements)
            for right in placements[index + 1:]
            if left.overlaps(right)
        ]
        if pairs:
            overlapping[key] = pairs
    return overlapping


class NoTwoSettingsWidgetsShareAGridCellTests(unittest.TestCase):
    """Tk stacks two widgets in one cell instead of complaining about it.

    This has already happened once: a readiness label was added at row 13 of a
    tab that was using row 13, and the two drew on top of each other until rows
    14 to 16 were shifted down by hand. Nothing failed, nothing logged, and it
    was only visible by opening the window and looking at it -- which is not a
    thing that happens on every change.

    Cheap to check statically and impossible to notice otherwise, which is the
    combination that makes a guard worth having.

    Two things it has to get right or it is worse than nothing. Row alone is
    not a cell -- the providers tab legitimately puts a label at (13, 0) and a
    value at (13, 1) -- and a frame name is only unique within the method that
    built it, since `body`, `options` and `footer` each name a different frame
    in several different windows. Ignoring either one reports eight collisions
    that are all fine, and a check that cries wolf gets deleted.

    Only literal rows and columns are read; anything computed is skipped rather
    than guessed at.
    """

    def test_no_settings_widget_is_drawn_on_top_of_another(self) -> None:
        found = collisions()
        self.assertEqual(
            found, {},
            "two widgets share a grid cell and will draw on top of each other; "
            f"overlay.py lines: {found}",
        )

    def test_the_dictation_tab_is_actually_being_read(self) -> None:
        """Proves the parser found something, so the check above cannot pass by
        silently matching nothing after a helper is renamed."""
        walker = Walker()
        walker.visit(ast.parse(OVERLAY.read_text(encoding="utf-8")))
        rows = {placement.row for placement in walker.found.get("open_settings::dictation_tab", [])}
        self.assertGreaterEqual(len(rows), 15, f"only found {len(rows)} rows on the dictation tab")
        self.assertEqual(min(rows), 0)

    def test_the_guard_notices_a_real_overlap(self) -> None:
        same_cell = Placement(4, 0, 2, 10)
        self.assertTrue(same_cell.overlaps(Placement(4, 1, 1, 11)), "columns 0-1 and column 1 overlap")
        self.assertTrue(same_cell.overlaps(Placement(4, 0, 1, 11)))

    def test_the_guard_allows_a_shared_row_in_different_columns(self) -> None:
        """The providers tab does this deliberately, twice."""
        self.assertFalse(Placement(13, 0, 1, 10).overlaps(Placement(13, 1, 1, 11)))
        self.assertFalse(Placement(13, 0, 1, 10).overlaps(Placement(14, 0, 1, 11)))


if __name__ == "__main__":
    unittest.main()
