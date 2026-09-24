from __future__ import annotations

import ast
import unittest
from pathlib import Path

OVERLAY = Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py"


def find_function(tree: ast.AST, name: str) -> ast.FunctionDef:
    """The named function, wherever it is nested.

    `apply_settings_theme` is a closure inside `open_settings`, so a top-level
    scan would never see it.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from overlay.py")


class ThemeChangeReachesThePageBodiesTests(unittest.TestCase):
    """X-82 (0.4.70): a theme change must repaint the pages, not only the chrome.

    Upstream shipped this fix with no test, and it is precisely the shape of
    block a later three-way merge drops without anyone noticing: it is a plain
    loop appended inside a long closure, on a file that diverges between the
    platforms, and nothing else in the suite fails if it disappears. The
    symptom is not a crash -- it is the theme picker looking broken, which is
    the bug X-82 existed to fix in the first place.

    These assert the mechanism at the AST level rather than by rendering,
    because standing up a real settings window under Tk 9 aqua costs a root
    that later window tests have to survive.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ast.parse(OVERLAY.read_text(encoding="utf-8"))
        cls.apply = find_function(cls.tree, "apply_settings_theme")
        cls.source = ast.unparse(cls.apply)

    def test_the_walk_covers_every_page(self) -> None:
        """Not one page, not the visible page -- all six, so switching tabs
        after a theme change never reveals a stale one."""
        self.assertIn("page_outers.values()", self.source)

    def test_the_scroll_canvas_is_recolored(self) -> None:
        """The X-74 scroll canvas is the page's actual background. Leaving it
        behind is what made the picker read as dead."""
        self.assertIn("_scroll_canvas", self.source)
        self.assertRegex(self.source, r"scroll_canvas\.configure\(bg=palette\['panel'\]\)")

    def test_the_section_holders_and_their_headers_are_recolored(self) -> None:
        self.assertIn("_sections", self.source)
        self.assertRegex(self.source, r"holder\.configure\(bg=palette\['panel'\]\)")
        # Headers keep their weight: a muted caption stays muted in the new
        # palette and a title stays text, so the fg is the measured one.
        self.assertRegex(self.source, r"child\.configure\(bg=palette\['panel'\], fg=foreground\)")
        self.assertIn("foreground = palette['muted'] if current == previous_palette['muted'] else palette['text']", self.source)

    def test_every_recolor_survives_a_dead_widget(self) -> None:
        """A page whose window went away mid-theme-change must not abort the
        walk and leave the pages after it in the old palette."""
        walk = self.source[self.source.index("page_outers.values()"):]
        self.assertGreaterEqual(
            walk.count("contextlib.suppress(tk.TclError)"), 3,
            "each configure in the page walk needs its own suppression",
        )

    def test_the_headers_are_matched_by_type_not_by_position(self) -> None:
        """Section holders carry non-label children too; recoloring by index
        would paint whatever happened to sit first."""
        self.assertIn("isinstance(child, tk.Label)", self.source)


class ThemePickerRowsWearTheirOwnThemeTests(unittest.TestCase):
    """The other half of X-82: each bar in the list IS that theme.

    The rows are built in `open_theme_picker`'s loop over the palettes. The
    contract is full bleed -- the label sits on the theme's own background, not
    on an inset panel -- with panel and accent as swatches.
    """

    @classmethod
    def setUpClass(cls) -> None:
        tree = ast.parse(OVERLAY.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            source = ast.unparse(node)
            if "SETTINGS_THEME_PALETTES.get(family, {}).get(mode)" in source and "cursor='hand2'" in source:
                cls.source = source
                break
        else:  # pragma: no cover - only on a port that lost the picker
            raise AssertionError("the theme picker rows are gone from overlay.py")

    def test_the_label_sits_on_the_themes_own_background(self) -> None:
        # X-337: the bar IS the theme's material, and the name is inked by
        # measured contrast against it.
        self.assertIn("material = theme_material(palette, mode)", self.source)
        self.assertIn("ink = material_ink(palette, material)", self.source)
        self.assertRegex(self.source, r"row = tk\.Frame\(rows, bg=material\)")
        self.assertRegex(self.source, r"button = FlatButton\(row, text=option, .*?bg=material, fg=ink")

    def test_both_panel_and_accent_show_as_swatches(self) -> None:
        for key in ("panel", "accent"):
            self.assertRegex(
                self.source,
                rf"{key}_swatch = tk\.Frame\(row, bg=palette\['{key}'\], width=ui_scale\.px\(28, self\.config\), height=ui_scale\.px\(16, self\.config\)",
                f"the {key} swatch is missing from the picker row",
            )

    def test_the_whole_row_is_clickable(self) -> None:
        """The swatches and the label cover most of the bar's area; binding the
        frame alone leaves a row that ignores most clicks at it."""
        # The name is the button; the two swatches beside it forward their
        # click to it, so the whole bar picks.
        self.assertIn("for swatch in (accent_swatch, panel_swatch):", self.source)
        self.assertRegex(self.source, r"swatch\.bind\('<Button-1>', lambda _e, target=button: \(target\.focus_set\(\), target\.invoke\(\), 'break'\)\[-1\]\)")


if __name__ == "__main__":
    unittest.main()
