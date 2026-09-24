"""X-605: the text beside the caret comes from the focused field alone.

The owner's log, 2026-09-19 to 09-23: nearly every dictation into the Claude
desktop app landed with its first word lowercased ("the formatting seems a bit
weird"). Measured on his PC: in an empty Electron message box, moving the
caret range back 32 characters walked out of the editor and returned the app's
own buttons ("Skip\\nSubmit\\n\\ufffc\\nChat mode\\n\\ufffc"). That read as an
unfinished sentence, so every take was treated as a continuation.

Two defences, each tested on its own:
  _read_uia clamps both ranges to the editor's DocumentRange, and
  apply_caret_context calls a take a continuation only after a word or a
  clause mark (",", ";").
And the Pill menu: its window must not start CenterScreen, or the first menu
after a launch opens wherever WinForms centres it, not on the Pill.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from knight_flow.caret_context import _read_uia, apply_caret_context

ROOT = Path(__file__).resolve().parents[1]
START, END = 0, 1


class _Range:
    """A text range over one string, as UIA sees it: [start, end) offsets."""

    def __init__(self, page: str, start: int, end: int) -> None:
        self.page, self.start, self.end = page, start, end

    def Clone(self):
        return _Range(self.page, self.start, self.end)

    def MoveEndpointByUnit(self, endpoint, _unit, count):
        # Like Chromium: free to walk anywhere in the page.
        if endpoint == START:
            self.start = max(0, self.start + count)
        else:
            self.end = min(len(self.page), self.end + count)
        return count

    def CompareEndpoints(self, endpoint, other, other_endpoint):
        mine = self.start if endpoint == START else self.end
        theirs = other.start if other_endpoint == START else other.end
        return (mine > theirs) - (mine < theirs)

    def MoveEndpointByRange(self, endpoint, other, other_endpoint):
        value = other.start if other_endpoint == START else other.end
        if endpoint == START:
            self.start = value
        else:
            self.end = value

    def GetText(self, limit):
        return self.page[self.start:self.end][:limit]

    def Compare(self, other):
        return (self.start, self.end) == (other.start, other.end)


class _Selection:
    def __init__(self, caret):
        self.Length, self._caret = 1, caret

    def GetElement(self, _index):
        return self._caret


def _editor(page: str, field_start: int, field_end: int, caret: int):
    uia = SimpleNamespace(UIA_EditControlTypeId=1, UIA_DocumentControlTypeId=2, UIA_TextPatternId=3,
                          IUIAutomationTextPattern=object, TextPatternRangeEndpoint_Start=START,
                          TextPatternRangeEndpoint_End=END, TextUnit_Character=0)
    caret_range = _Range(page, caret, caret)
    pattern = SimpleNamespace(DocumentRange=_Range(page, field_start, field_end),
                              GetSelection=lambda: _Selection(caret_range))
    pattern.QueryInterface = lambda _iface: pattern
    element = SimpleNamespace(CurrentIsPassword=False, CurrentHasKeyboardFocus=True,
                              CurrentControlType=1, GetCurrentPattern=lambda _id: pattern)
    automation = SimpleNamespace(GetFocusedElement=lambda: element, CompareElements=lambda a, b: True)
    return automation, uia


class TheReadStaysInsideTheFieldTests(unittest.TestCase):
    PAGE = "tion\nSkip\nSubmit\n￼\nChat mode\n￼" + "\n" + "Stop\nAdd\nPress and hold"

    def test_an_empty_message_box_reads_nothing_from_the_page_around_it(self):
        box = self.PAGE.index("\nStop")  # the empty editor is the "\n" before the buttons
        automation, uia = _editor(self.PAGE, box, box + 1, box)
        context = _read_uia(automation, uia)
        self.assertEqual(context, {"left": "", "right": "\n"})
        self.assertEqual(apply_caret_context("The formatting seems a bit weird.", "the formatting seems a bit weird",
                                             context, {}), "The formatting seems a bit weird.")

    def test_text_inside_the_field_is_still_read(self):
        page = "Buttons\nSubmit\n" + "I think we should" + "\nMore buttons"
        start = page.index("I think")
        end = start + len("I think we should")
        automation, uia = _editor(page, start, end, end)
        context = _read_uia(automation, uia)
        self.assertEqual(context["left"], "I think we should")
        self.assertEqual(context["right"], "")

    def test_an_embedded_object_is_a_boundary(self):
        page = "Hello ￼"
        automation, uia = _editor(page, 0, len(page), len(page))
        context = _read_uia(automation, uia)
        self.assertEqual(context["left"], "Hello \n")


class AContinuationNeedsAWordBeforeTheCaretTests(unittest.TestCase):
    def check(self, left: str) -> str:
        return apply_caret_context("So what can I read?", "so what can I read", {"left": left, "right": ""}, {})

    def test_after_a_word_or_a_comma_the_take_continues(self):
        self.assertEqual(self.check("and I asked "), "so what can I read?")
        self.assertEqual(self.check("Honestly, "), "so what can I read?")

    def test_anything_else_starts_a_new_sentence(self):
        for left in ("", "\n", "Chat mode\n", "￼", "Done. ", "Why? ", "Note: ", "#", "→ ", "- ", "\U0001f600 "):
            with self.subTest(left=left):
                self.assertEqual(self.check(left), "So what can I read?")


class ThePillMenuStartsWhereItIsPutTests(unittest.TestCase):
    def test_the_menu_window_is_never_left_to_start_centred(self):
        source = (ROOT / "knight_flow" / "web_shell" / "shell_host.py").read_text(encoding="utf-8")
        menu = source[source.index("if mode == 'menu':"):source.index("window = webview.create_window(")]
        self.assertIn("options.update(x=0, y=0)", menu)
        self.assertIn("sys.platform == 'win32'", menu)

    def test_the_menu_is_placed_again_after_it_shows(self):
        source = (ROOT / "knight_flow" / "web_shell" / "shell_host.py").read_text(encoding="utf-8")
        navigate = source[source.index("if message.get('command') == 'navigate':"):]
        navigate = navigate[:navigate.index("continue")]
        self.assertLess(navigate.index("self._show()"), navigate.rindex("self._place_menu("))

    @unittest.skipUnless(sys.platform == "win32", "WinForms start position")
    def test_pywebview_turns_a_given_position_into_a_manual_start(self):
        import webview.platforms.winforms as winforms

        source = Path(winforms.__file__).read_text(encoding="utf-8")
        manual = source.index("if window.initial_x is not None and window.initial_y is not None:")
        self.assertIn("FormStartPosition.Manual", source[manual:manual + 200])


if __name__ == "__main__":
    unittest.main()
