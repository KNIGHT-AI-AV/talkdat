"""T1: the UI Automation adapter, on a fake UI Automation provider that models
one text field (text, caret, selection). No real accessibility call is made;
the fake is the shape UIAutomationCore returns, reduced to what the adapter
uses.
"""
from __future__ import annotations

import unittest

from knight_flow.verified_replace import Draft, read_bound, replace_if_proved
from knight_flow.verified_target import (
    UIA_DOCUMENT, UiaTarget, collapse_selection, read_target, select_before_caret,
)


class Field:
    def __init__(self, text: str = "", password: bool = False, control: int = 50004) -> None:
        self.text, self.caret, self.selection = text, len(text), None
        self.password, self.control = password, control

    def span(self) -> tuple[int, int]:
        return self.selection if self.selection else (self.caret, self.caret)


class Range:
    def __init__(self, field: Field, start: int, end: int) -> None:
        self.field, self.start, self.end = field, start, end

    def Clone(self):
        return Range(self.field, self.start, self.end)

    def _point(self, endpoint: int) -> int:
        return self.start if endpoint == 0 else self.end

    def CompareEndpoints(self, endpoint, other, other_endpoint) -> int:
        a, b = self._point(endpoint), other._point(other_endpoint)
        return (a > b) - (a < b)

    def MoveEndpointByUnit(self, endpoint, unit, count) -> int:
        point = self._point(endpoint)
        moved = max(-point, min(len(self.field.text) - point, count))
        if endpoint == 0:
            self.start = point + moved
            self.end = max(self.end, self.start)
        else:
            self.end = point + moved
            self.start = min(self.start, self.end)
        return moved

    def MoveEndpointByRange(self, endpoint, other, other_endpoint) -> None:
        value = other._point(other_endpoint)
        if endpoint == 0:
            self.start = value
            self.end = max(self.end, value)
        else:
            self.end = value
            self.start = min(self.start, value)

    def GetText(self, limit: int) -> str:
        text = self.field.text[self.start:self.end]
        return text if limit < 0 else text[:limit]

    def Select(self) -> None:
        self.field.selection = None if self.start == self.end else (self.start, self.end)
        self.field.caret = self.end

    def Compare(self, other) -> bool:
        return (self.start, self.end) == (other.start, other.end)


class RangeArray:
    def __init__(self, ranges) -> None:
        self._ranges = ranges
        self.Length = len(ranges)

    def GetElement(self, index):
        return self._ranges[index]


class Pattern:
    def __init__(self, field: Field) -> None:
        self.field = field

    def GetSelection(self):
        start, end = self.field.span()
        return RangeArray([Range(self.field, start, end)])

    @property
    def DocumentRange(self):
        return Range(self.field, 0, len(self.field.text))


class Element:
    def __init__(self, field: Field, runtime: tuple) -> None:
        self.field, self._runtime = field, runtime
        self.CurrentHasKeyboardFocus = True
        self.CurrentControlType = field.control
        self.CurrentIsPassword = field.password

    def GetRuntimeId(self):
        return self._runtime

    def GetCurrentPattern(self, pattern_id):
        return Pattern(self.field)


class Automation:
    def __init__(self, *fields: Field) -> None:
        self.elements = [Element(field, (42, index)) for index, field in enumerate(fields)]
        self.focused = 0
        self.after_first_focus_read = None

    def GetFocusedElement(self):
        element = self.elements[self.focused]
        if self.after_first_focus_read is not None:
            self.focused, self.after_first_focus_read = self.after_first_focus_read, None
        return element

    def CompareElements(self, a, b) -> bool:
        return a.field is b.field


class TheRead(unittest.TestCase):
    def test_a_collapsed_caret_after_text(self):
        field = Field("Note: send it now")
        read = read_target(Automation(field), None, 7, read_bound("send it now"))
        self.assertTrue(read.ok)
        self.assertEqual((read.window, read.element, read.collapsed, read.password), (7, (42, 0), True, False))
        self.assertEqual((read.left, read.right), ("Note: send it now", ""))

    def test_a_bounded_left_and_the_text_after_the_caret(self):
        field = Field("x" * 100 + "tail" + "after the caret")
        field.caret = 104
        read = read_target(Automation(field), None, 1, 10)
        self.assertEqual(read.left, "x" * 6 + "tail")
        self.assertEqual(read.right, "after the caret")

    def test_a_selection_is_reported_as_not_collapsed(self):
        field = Field("Note: send it now")
        field.selection = (6, 10)
        field.caret = 10
        self.assertFalse(read_target(Automation(field), None, 1, 40).collapsed)

    def test_a_password_field_and_a_control_that_is_not_text(self):
        self.assertTrue(read_target(Automation(Field("x", password=True)), None, 1, 40).password)
        self.assertFalse(read_target(Automation(Field("x", control=50000)), None, 1, 40).ok)
        self.assertTrue(read_target(Automation(Field("x", control=UIA_DOCUMENT)), None, 1, 40).ok)

    def test_focus_moving_during_the_read_voids_it(self):
        automation = Automation(Field("one"), Field("two"))
        automation.after_first_focus_read = 1
        self.assertFalse(read_target(automation, None, 1, 40).ok)

    def test_a_provider_that_raises_is_not_proved(self):
        class Broken:
            def GetFocusedElement(self):
                raise OSError("UIA provider timed out")

        self.assertFalse(read_target(Broken(), None, 1, 40).ok)
        self.assertIsNone(select_before_caret(Broken(), None, "x"))
        collapse_selection(Broken(), None)  # no raise


class TheSelection(unittest.TestCase):
    def test_exactly_the_draft_is_selected_and_read_back(self):
        field = Field("Note: send it now")
        self.assertEqual(select_before_caret(Automation(field), None, "send it now"), "send it now")
        self.assertEqual(field.selection, (6, 17))

    def test_too_few_characters_before_the_caret(self):
        field = Field("now")
        self.assertIsNone(select_before_caret(Automation(field), None, "send it now"))
        self.assertIsNone(field.selection)

    def test_an_existing_selection_is_never_replaced(self):
        field = Field("Note: send it now")
        field.selection = (0, 4)
        field.caret = 4
        self.assertIsNone(select_before_caret(Automation(field), None, "Note"))
        self.assertEqual(field.selection, (0, 4))

    def test_collapse_puts_the_caret_after_the_selection(self):
        field = Field("Note: send it now")
        field.selection, field.caret = (6, 17), 17
        collapse_selection(Automation(field), None)
        self.assertEqual((field.selection, field.caret), (None, 17))


class AReplacementThroughTheAdapter(unittest.TestCase):
    def test_draft_to_polish(self):
        field = Field("Note: ")
        automation = Automation(field)

        def paste(text: str) -> bool:
            start, end = field.span()
            field.text = field.text[:start] + text + field.text[end:]
            field.caret, field.selection = start + len(text), None
            return True

        target = UiaTarget(automation, None, lambda: 7, paste)
        before = target.read(read_bound("send it now"))
        paste("send it now")
        after = target.read(read_bound("send it now"))
        take = object()
        draft = Draft(take=take, text="send it now", inserted_at=10.0, before=before, after=after)
        outcome = replace_if_proved(target, draft, "Send it now.", now_s=11.0, current_take=take, recording=False)
        self.assertEqual(outcome.reason, "replaced")
        self.assertEqual(field.text, "Note: Send it now.")

    def test_typing_after_the_draft_keeps_it(self):
        field = Field("Note: ")
        automation = Automation(field)

        def paste(text: str) -> bool:
            start, end = field.span()
            field.text = field.text[:start] + text + field.text[end:]
            field.caret, field.selection = start + len(text), None
            return True

        target = UiaTarget(automation, None, lambda: 7, paste)
        before = target.read(read_bound("send it now"))
        paste("send it now")
        after = target.read(read_bound("send it now"))
        paste(" please")  # the person typing
        take = object()
        draft = Draft(take=take, text="send it now", inserted_at=10.0, before=before, after=after)
        outcome = replace_if_proved(target, draft, "Send it now.", now_s=11.0, current_take=take, recording=False)
        self.assertEqual((outcome.replaced, outcome.reason), (False, "changed_before_caret"))
        self.assertEqual(field.text, "Note: send it now please")
        self.assertEqual(outcome.alternative, "Send it now.")


if __name__ == "__main__":
    unittest.main()
