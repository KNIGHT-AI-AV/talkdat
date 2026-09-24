"""No shipped string may name a platform that the reader might not be on.

This is the anti-drift guard, and it lives on MAIN on purpose.

`THIS_COMPUTER` used to exist only on `mac-port`, inside `mac_support.py`. So
main wrote "this PC" freely, `mac-port` converted those strings after every
merge, and the next merge brought them back. The cycle ran at least twice:
twelve strings in an earlier pass over `overlay.py` and `ui/onboarding.py`, then
twenty-two more on 2026-09-21 -- found only because a Mac user was shown "your
PC". Moving the constant to main without moving the guard would simply restart
the cycle with a shorter fuse.

A previous version of this test existed on `mac-port` and was GREEN throughout,
because it scanned exactly two files:

    FILES = ("knight_flow/overlay.py", "knight_flow/ui/onboarding.py")

`app.py` was not one of them and held six offenders. A guard whose scope is
narrower than the fault it names is not a guard, so this one reads every module
and every shipped data file.

AST rather than grep, for the Python half: a comment or a docstring must stay
free to discuss PCs while explaining why the constant exists, and line-based
comment stripping cannot tell a docstring from a message a person reads.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from knight_flow.onboarding import ONBOARDING_STEPS
from knight_flow.platform_copy import THIS_COMPUTER, THIS_COMPUTER_SENTENCE

ROOT = Path(__file__).resolve().parents[1]

#: Phrases that assert a platform the reader may not be using.
BANNED = ("this PC", "your PC", "This PC", "Your PC")

#: The only file allowed to contain them, because it defines them.
EXEMPT = ("knight_flow/platform_copy.py",)


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Nodes that are docstrings rather than copy."""
    found: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body:
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.add(id(first.value))
    return found


class NoShippedStringNamesAPlatformTests(unittest.TestCase):
    def test_no_module_hardcodes_a_platform_name(self) -> None:
        offenders = []
        for path in sorted((ROOT / "knight_flow").rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel in EXEMPT or "__pycache__" in rel:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = _docstring_ids(tree)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                if id(node) in docstrings:
                    continue
                if any(phrase in node.value for phrase in BANNED):
                    offenders.append(f"{rel}:{node.lineno}: {node.value.strip()[:70]}")
        self.assertEqual(
            offenders, [],
            "these strings name a platform the reader may not be on. Use "
            "platform_copy.THIS_COMPUTER (mid-sentence) or "
            f"THIS_COMPUTER_SENTENCE (sentence-initial): {offenders}",
        )

    def test_no_shipped_data_file_hardcodes_a_platform_name(self) -> None:
        """JSON and JS cannot reach a Python constant, so their copy is neutral.

        Settings tips and field descriptions are read on whichever machine the
        person is using, and "this computer" is true on both.
        """
        offenders = []
        for pattern in ("knight_flow/**/*.json", "knight_flow/**/*.js"):
            for path in sorted(ROOT.glob(pattern)):
                rel = path.relative_to(ROOT).as_posix()
                if "__pycache__" in rel:
                    continue
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if any(phrase in line for phrase in BANNED):
                        offenders.append(f"{rel}:{number}: {line.strip()[:70]}")
        self.assertEqual(offenders, [],
                         f"shipped data names a platform: {offenders}")

    def test_a_continuation_line_is_not_a_blind_spot(self) -> None:
        """An implicit concatenation reports ONE lineno, for its first line.

        `ui/onboarding.py` split "audio never leaves " / "this PC." across two
        physical lines. An AST-located, line-based rewrite fixed the first and
        left the second, and the scan above is what caught it. This asserts the
        scan reads the whole literal, not the line the literal starts on.
        """
        source = "x = (\n    'audio never leaves '\n    'this PC.'\n)\n"
        tree = ast.parse(source)
        values = [n.value for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        self.assertTrue(any("this PC" in value for value in values),
                        "the scanner would miss a phrase on a continuation line")


class TheConstantIsUsableInBothPositionsTests(unittest.TestCase):
    def test_it_resolves_to_one_of_the_two_machines(self) -> None:
        self.assertIn(THIS_COMPUTER, ("this Mac", "this PC"))

    def test_the_sentence_form_only_moves_the_first_letter(self) -> None:
        """`.capitalize()` gives "This mac"; `.title()` gives "This Pc"."""
        self.assertIn(THIS_COMPUTER_SENTENCE, ("This Mac", "This PC"))
        self.assertEqual(THIS_COMPUTER_SENTENCE[1:], THIS_COMPUTER[1:])
        self.assertEqual(THIS_COMPUTER_SENTENCE[0], THIS_COMPUTER[0].upper())

    def test_the_module_stays_free_of_platform_imports(self) -> None:
        """Main builds Windows. This module must never drag AppKit in.

        It exists precisely so main does not have to import mac_support, which
        is 1,265 lines of Aqua primitives.
        """
        tree = ast.parse((ROOT / "knight_flow" / "platform_copy.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported - {"__future__"}, {"sys"},
                         f"platform_copy grew a dependency: {sorted(imported)}")


class TheRailLabelsAreDistinctTests(unittest.TestCase):
    """Two dots both named "Access" on a ten-step rail read as a mistake.

    The permissions step shipped wearing the account step's label. Caught on a
    screenshot of the rail, not in any review of the file that defines it --
    the labels live thirty lines apart and each read fine alone.
    """

    def test_no_two_steps_share_a_label(self) -> None:
        labels = [step.label for step in ONBOARDING_STEPS]
        duplicates = sorted({label for label in labels if labels.count(label) > 1})
        self.assertEqual(duplicates, [], f"onboarding rail shows duplicate labels: {duplicates}")


class ReadonlyComboboxesAreMappedTests(unittest.TestCase):
    """clam takes a readonly widget's colours from the state MAP.

    Nearly every combobox here is state="readonly", and with only configure()
    colours the readonly state fell back to the theme's light grey --
    "System default microphone" rendered pale-on-pale in the middle of
    onboarding. The configured colours read back correctly the whole time;
    only the pixels disagreed.
    """

    def test_the_flow_combobox_maps_its_readonly_state(self) -> None:
        source = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        index = source.index('"Flow.TCombobox",\n            fieldbackground')
        block = source[index:index + 4000]
        self.assertIn("style.map(", block)
        self.assertRegex(block, r'fieldbackground=\[.*?\("readonly", palette\["field"\]\)')
        self.assertRegex(block, r'\bforeground=\[.*?\("readonly", palette\["text"\]\)')


if __name__ == "__main__":
    unittest.main()

if __name__ == "__main__":
    unittest.main()
