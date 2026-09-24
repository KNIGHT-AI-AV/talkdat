from __future__ import annotations

import ast
import unittest
from pathlib import Path

KNIGHT_FLOW = Path(__file__).resolve().parents[1] / "knight_flow"
SOURCES = (
    KNIGHT_FLOW / "overlay.py",
    KNIGHT_FLOW / "ui" / "onboarding.py",
    KNIGHT_FLOW / "ui" / "flow_console.py",
)

BUTTONS = {"Button", "AtelierButton", "Checkbutton", "Radiobutton", "Menubutton"}

#: Words that are capitalised because that is their spelling, not because the
#: label was Title Cased. Acronyms, product names, and proper nouns.
SPELLED_CAPITALISED = {
    "Talk", "DAT", "Windows", "Mac", "macOS", "iOS", "Android", "PC",
    "JSON", "SRT", "CSV", "PDF", "URL", "API", "AI", "GPU", "CPU", "RAM",
    "Deepgram", "OpenAI", "Whisper", "Parakeet", "Ollama", "Qwen", "NVIDIA",
    "Stripe", "Pro", "Word", "Excel", "Markdown", "Knight", "Google",
    "I", "OK", "ID", "TV", "USB", "Aa", "English",
}


def _button_labels(source: Path) -> list[tuple[int, str]]:
    """Every literal ``text=`` on a button constructor, from the AST.

    AST rather than a regular expression so the guard cannot fire on a label
    quoted inside a comment that explains the rule -- which is how the deploy
    guard in this repo first failed.
    """

    tree = ast.parse(source.read_text(encoding="utf-8"))
    labels: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in BUTTONS:
            continue
        for keyword in node.keywords:
            if keyword.arg == "text" and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, str):
                    labels.append((keyword.lineno, keyword.value.value))
    return labels


def _is_title_cased(label: str) -> bool:
    words = [w for w in label.replace("...", "").split() if w.isalpha()]
    if len(words) < 2:
        return False
    later = [w for w in words[1:] if w not in SPELLED_CAPITALISED]
    if not later:
        return False
    return all(word[:1].isupper() for word in later)


class ControlLabelsReadTheSameWayTests(unittest.TestCase):
    """One button row had quietly decided on its own capitalisation.

    "Save Setup", "Full Settings" and "Use Local Default" sat in a single row
    in Title Case while the other ~190 control labels in the app were sentence
    case -- which is also what Windows and macOS both set controls in. Nothing
    was wrong with any one of those three. The problem was that the row decided
    for itself, so the panel read as slightly unlike every other panel and none
    of it read as decided (X-536).
    """

    def test_no_control_is_title_cased(self) -> None:
        offenders = [
            f"{source.name}:{line} \"{label}\""
            for source in SOURCES
            for line, label in _button_labels(source)
            if _is_title_cased(label)
        ]
        self.assertEqual(
            offenders,
            [],
            "Controls are sentence case: capitalise the first word and any word "
            "that is spelled that way. Add a genuine proper noun to "
            "SPELLED_CAPITALISED rather than Title Casing around it.\n  "
            + "\n  ".join(offenders),
        )

    def test_no_label_carries_a_doubled_space(self) -> None:
        offenders = [
            f"{source.name}:{line} \"{label}\""
            for source in SOURCES
            for line, label in _button_labels(source)
            if "  " in label.strip()
        ]
        self.assertEqual(offenders, [], "\n  ".join(offenders))

    def test_the_rule_can_actually_fail(self) -> None:
        """A guard nobody has seen go red is a guard nobody has tested.

        Both directions, because a check that fires on everything is as useless
        as one that fires on nothing.
        """

        self.assertTrue(_is_title_cased("Save Setup"))
        self.assertTrue(_is_title_cased("Use Local Default"))
        self.assertFalse(_is_title_cased("Save setup"))
        self.assertFalse(_is_title_cased("Use local default"))
        self.assertFalse(_is_title_cased("Continue"))
        self.assertFalse(_is_title_cased("Talk DAT!"), "a product name is spelled, not cased")
        self.assertFalse(_is_title_cased("Export SRT subtitles"), "an acronym is spelled")


if __name__ == "__main__":
    unittest.main()
