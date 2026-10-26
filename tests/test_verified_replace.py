"""T1: the scripted matrix. A late polish never overwrites the person's edits and
never lands in the wrong place; every polish it does not apply is kept.

Synthetic only: a simulated desktop (tests/simulated_editor.py) stands in for
real applications, so no key, click or clipboard reaches anything.
"""
from __future__ import annotations

import unittest

from knight_flow.verified_replace import (
    ANCHOR_CHARS, MAX_AGE_SECONDS, Draft, TargetRead, as_delivered, decide, field_form, insertion_proved,
    keep_alternative, read_bound, replace_if_proved,
)
from tests.simulated_editor import Desktop

T0 = 1000.0
FIELD, OTHER, ELSEWHERE = (1, ("edit", 1)), (1, ("edit", 2)), (2, ("edit", 3))

DRAFTS = {
    "short": ("send the report on friday", "Send the report on Friday."),
    "long": (" ".join(["the quarterly numbers are in and they look good"] * 18),
             " ".join(["The quarterly numbers are in, and they look good."] * 18)),
    "line breaks": ("first point\nsecond point", "First point.\nSecond point."),
    "emoji": ("ship it 🚀 today", "Ship it 🚀 today."),
    "repeats what is before it": ("send the report", "Send the report."),
}
PREFIXES = {
    "short": "Note: ",
    "long": "Summary for the board. ",
    "line breaks": "Agenda\n",
    "emoji": "Status: ",
    "repeats what is before it": "send the report and then send the report ",
}


def build(prefix: str, **options) -> Desktop:
    desktop = Desktop()
    desktop.add(*FIELD, text=prefix, **options)
    desktop.add(*OTHER, text="another field")
    desktop.add(*ELSEWHERE, text="another window")
    desktop.focus_on(*FIELD)
    return desktop


def insert_draft(desktop: Desktop, text: str, take: object, route: str = "clipboard") -> Draft:
    before = desktop.read(read_bound(text))
    delivered = desktop.app_paste(text)
    after = desktop.read(read_bound(text))
    return Draft(take=take, text=text, inserted_at=T0, before=before, after=after, route=route,
                 succeeded=delivered)


class TheMatrix(unittest.TestCase):
    """Every scenario x every draft shape, against the same three invariants."""

    # name -> (what the person does between the draft and the polish, expected reason)
    SCENARIOS = {
        "nothing": (lambda d, n: None, "replaced"),
        "types after the draft": (lambda d, n: d.type(" ok"), "changed_before_caret"),
        "types before the draft": (lambda d, n: (d.move(-n - 1), d.type("X"), d.move(n)), "changed_before_caret"),
        "types inside the draft": (lambda d, n: (d.move(-3), d.type("Z")), "changed_before_caret"),
        "moves the caret away": (lambda d, n: d.move(-4), "changed_before_caret"),
        "moves away and comes back": (lambda d, n: (d.move(-4), d.move(4)), "replaced"),
        "selects part of the draft": (lambda d, n: d.select(d.field.caret - 3, d.field.caret), "selection"),
        "selects everything": (lambda d, n: d.select(0, len(d.field.text)), "selection"),
        "clicks into another field": (lambda d, n: d.focus_on(*OTHER), "other_field"),
        "switches window": (lambda d, n: d.focus_on(*ELSEWHERE), "other_window"),
        "submits the field": (lambda d, n: d.submit(), "changed_before_caret"),
        "deletes the draft": (lambda d, n: d.backspace(n), "changed_before_caret"),
        "deletes one character": (lambda d, n: d.backspace(1), "changed_before_caret"),
        "pastes their own text after it": (lambda d, n: d.type(" [their paste]"), "changed_before_caret"),
        "types and deletes back to the same text": (lambda d, n: (d.type("abc"), d.backspace(3)), "replaced"),
    }

    def check(self, shape: str, name: str) -> None:
        draft_text, polished = DRAFTS[shape]
        action, expected = self.SCENARIOS[name]
        desktop = build(PREFIXES[shape])
        take = object()
        draft = insert_draft(desktop, draft_text, take)
        self.assertEqual(insertion_proved(draft), "", f"{shape}: the draft insertion was not proved")
        action(desktop, len(draft_text))
        before_polish = desktop.everything()
        box = desktop.windows[FIELD[0]][FIELD[1]]
        caret, selection = box.caret, box.selection
        outcome = replace_if_proved(desktop, draft, polished, now_s=T0 + 1.0, current_take=take, recording=False)
        after = desktop.everything()
        self.assertEqual(outcome.reason, expected, f"{shape} / {name}")
        # 1. No other field changed, whatever happened.
        for key, text in after.items():
            if key != FIELD:
                self.assertEqual(text, before_polish[key], f"{shape} / {name}: wrong target {key}")
        # 2. In the field: exactly the draft became the polish, or nothing changed.
        if outcome.replaced:
            start = caret - len(draft_text)
            self.assertEqual(after[FIELD], before_polish[FIELD][:start] + polished + before_polish[FIELD][caret:])
            self.assertIsNone(box.selection, f"{shape} / {name}: the app left a selection behind")
        else:
            self.assertEqual(after[FIELD], before_polish[FIELD], f"{shape} / {name}: an edit was overwritten")
            # The person's own selection (or caret) is theirs; the app left it as it was.
            self.assertEqual((box.caret, box.selection), (caret, selection), f"{shape} / {name}: caret moved")
            # 3. A polish that was not applied is kept for the person.
            self.assertEqual(outcome.alternative, polished)

    def test_every_scenario_and_shape(self):
        for shape in DRAFTS:
            for name in self.SCENARIOS:
                with self.subTest(shape=shape, scenario=name):
                    self.check(shape, name)


class TheTakeAndTheClock(unittest.TestCase):
    def setUp(self):
        self.desktop = build("Note: ")
        self.take = object()
        self.draft = insert_draft(self.desktop, "send it now", self.take)
        self.text = dict(self.desktop.everything())

    def run_with(self, **kwargs):
        options = {"now_s": T0 + 1.0, "current_take": self.take, "recording": False, **kwargs}
        return replace_if_proved(self.desktop, self.draft, "Send it now.", **options)

    def assert_untouched(self, outcome, reason):
        self.assertFalse(outcome.replaced)
        self.assertEqual(outcome.reason, reason)
        self.assertEqual(outcome.alternative, "Send it now.")
        self.assertEqual(self.desktop.everything(), self.text)

    def test_a_newer_take_owns_the_field(self):
        self.assert_untouched(self.run_with(current_take=object()), "newer_take")

    def test_recording_again(self):
        self.assert_untouched(self.run_with(recording=True), "recording_again")

    def test_a_late_polish_is_kept_not_applied(self):
        self.assert_untouched(self.run_with(now_s=T0 + MAX_AGE_SECONDS + 0.01), "too_late")

    def test_in_time(self):
        outcome = self.run_with(now_s=T0 + MAX_AGE_SECONDS)
        self.assertTrue(outcome.replaced)
        self.assertEqual(self.desktop.field.text, "Note: Send it now.")


class WhatIsNeverReplaced(unittest.TestCase):
    def outcome(self, desktop, draft, polished="Send it now."):
        return replace_if_proved(desktop, draft, polished, now_s=T0 + 1, current_take=draft.take, recording=False)

    def test_an_identical_or_empty_polish_keeps_nothing(self):
        desktop = build("Note: ")
        draft = insert_draft(desktop, "Send it now.", object())
        for polished, reason in (("Send it now.", "identical"), ("   ", "no_polish"), ("", "no_polish")):
            outcome = self.outcome(desktop, draft, polished)
            self.assertEqual((outcome.replaced, outcome.reason, outcome.alternative), (False, reason, None))

    def test_a_draft_that_never_arrived(self):
        desktop = build("Note: ", accepts_paste=False)
        draft = insert_draft(desktop, "send it now", object())
        outcome = self.outcome(desktop, draft)
        self.assertEqual(outcome.reason, "draft_not_delivered")
        self.assertEqual(desktop.field.text, "Note: ")

    def test_typed_and_copy_routes(self):
        for route in ("typing", "copy_only", ""):
            desktop = build("Note: ")
            draft = insert_draft(desktop, "send it now", object(), route=route)
            self.assertEqual(self.outcome(desktop, draft).reason, "route_not_replaceable")
            self.assertEqual(desktop.field.text, "Note: send it now")

    def test_a_field_that_changes_what_is_pasted(self):
        desktop = build("Note: ", paste_transform=lambda text: text.replace("now", "NOW"))
        draft = insert_draft(desktop, "send it now", object())
        self.assertEqual(self.outcome(desktop, draft).reason, "insertion_not_verbatim")
        self.assertEqual(desktop.field.text, "Note: send it NOW")

    def test_a_password_field(self):
        desktop = build("", password=True)
        draft = insert_draft(desktop, "hunter two", object())
        self.assertEqual(self.outcome(desktop, draft).reason, "insertion_unsafe_field")

    def test_a_field_that_cannot_be_read(self):
        desktop = build("Note: ", readable=False)
        draft = insert_draft(desktop, "send it now", object())
        self.assertEqual(self.outcome(desktop, draft).reason, "insertion_unread")

    def test_a_field_that_becomes_unreadable(self):
        desktop = build("Note: ")
        draft = insert_draft(desktop, "send it now", object())
        desktop.field.readable = False
        self.assertEqual(self.outcome(desktop, draft).reason, "unreadable")
        self.assertEqual(desktop.field.text, "Note: send it now")

    def test_a_field_that_becomes_a_password_field(self):
        desktop = build("Note: ")
        draft = insert_draft(desktop, "send it now", object())
        desktop.field.password = True
        self.assertEqual(self.outcome(desktop, draft).reason, "password_field")


class TheReplacementStepsProveThemselves(unittest.TestCase):
    def setUp(self):
        self.desktop = build("Note: ")
        self.draft = insert_draft(self.desktop, "send it now", object())

    def outcome(self):
        return replace_if_proved(self.desktop, self.draft, "Send it now.", now_s=T0 + 1,
                                 current_take=self.draft.take, recording=False)

    def test_a_selection_that_is_not_the_draft_is_undone(self):
        self.desktop.field.select_short_by = 1
        outcome = self.outcome()
        self.assertEqual((outcome.replaced, outcome.reason), (False, "selection_not_the_draft"))
        self.assertEqual(self.desktop.field.text, "Note: send it now")
        self.assertIsNone(self.desktop.field.selection)
        self.assertEqual(outcome.alternative, "Send it now.")

    def test_a_paste_that_does_not_arrive_changes_nothing(self):
        self.desktop.field.accepts_paste = False
        outcome = self.outcome()
        self.assertEqual((outcome.replaced, outcome.reason), (False, "paste_failed"))
        self.assertEqual(self.desktop.field.text, "Note: send it now")
        self.assertIsNone(self.desktop.field.selection)

    def test_a_paste_that_lands_differently_is_flagged_and_kept(self):
        self.desktop.field.paste_transform = lambda text: text.upper()
        outcome = self.outcome()
        self.assertEqual((outcome.replaced, outcome.reason), (False, "check_the_text"))
        # Only the draft's own characters were ever selected, so the prefix is intact.
        self.assertTrue(self.desktop.field.text.startswith("Note: "))
        self.assertEqual(outcome.alternative, "Send it now.")
        self.assertEqual(outcome.steps[-1], "unverified")

    def test_a_paste_that_never_arrives_leaves_no_selection(self):
        self.desktop.field.drops_paste = True
        outcome = self.outcome()
        self.assertEqual((outcome.replaced, outcome.reason), (False, "check_the_text"))
        self.assertEqual(self.desktop.field.text, "Note: send it now")
        self.assertIsNone(self.desktop.field.selection, "the next key would replace the selected draft")
        self.assertEqual(self.desktop.field.caret, len("Note: send it now"))
        self.assertEqual(outcome.steps[-2:], ["collapsed", "unverified"])

    def test_the_steps_of_a_replacement(self):
        outcome = self.outcome()
        self.assertEqual(outcome.steps, ["decided", "selected", "pasted", "verified"])
        self.assertEqual(self.desktop.field.text, "Note: Send it now.")


class LineBreaksAsTheFieldStoresThem(unittest.TestCase):
    def test_a_field_that_stores_crlf(self):
        desktop = build("Agenda\r\n", paste_transform=lambda text: text.replace("\n", "\r\n"))
        draft = insert_draft(desktop, "first point\nsecond point", object())
        self.assertEqual(insertion_proved(draft), "")
        desktop.field.paste_transform = lambda text: text.replace("\n", "\r\n")
        outcome = replace_if_proved(desktop, draft, "First point.\nSecond point.", now_s=T0 + 1,
                                    current_take=draft.take, recording=False)
        self.assertEqual(outcome.reason, "replaced")
        self.assertEqual(desktop.field.text, "Agenda\r\nFirst point.\r\nSecond point.")

    def test_field_form(self):
        self.assertEqual(field_form("ab\r\ncd", "b\ncd"), "b\r\ncd")
        self.assertEqual(field_form("x\r\ny", "\ny"), "\r\ny")
        self.assertIsNone(field_form("abc", "zz"))
        self.assertIsNone(field_form("abc", ""))


class TheDecisionAlone(unittest.TestCase):
    def read(self, **values):
        base = {"ok": True, "window": 1, "element": ("edit", 1), "left": "Note: draft", "right": "",
                "collapsed": True, "password": False}
        return TargetRead(**{**base, **values})

    def draft(self, **values):
        base = {"take": "t", "text": "draft", "inserted_at": T0, "before": self.read(left="Note: "),
                "after": self.read()}
        return Draft(**{**base, **values})

    def test_reasons(self):
        draft = self.draft()
        cases = [
            (self.read(), "replace"),
            (self.read(ok=False), "unreadable"),
            (self.read(window=2), "other_window"),
            (self.read(window=0), "other_window"),
            (self.read(element=("edit", 2)), "other_field"),
            (self.read(element=()), "other_field"),
            (self.read(collapsed=False), "selection"),
            (self.read(password=True), "password_field"),
            (self.read(left="Note: draft!"), "changed_before_caret"),
            (self.read(right="x"), "changed_after_caret"),
        ]
        for now, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(decide(draft, now, "Draft.", now_s=T0 + 1, current_take="t",
                                        recording=False).reason, reason)

    def test_the_insertion_reads(self):
        cases = [
            (self.draft(), ""),
            (self.draft(before=self.read(ok=False)), "insertion_unread"),
            (self.draft(text=""), "insertion_empty"),
            (self.draft(after=self.read(window=2)), "insertion_moved"),
            (self.draft(after=self.read(element=("edit", 9))), "insertion_moved"),
            (self.draft(before=self.read(left="Note: ", collapsed=False)), "insertion_unsafe_field"),
            (self.draft(after=self.read(left="Note: draf")), "insertion_not_verbatim"),
            (self.draft(before=self.read(left="Other: ")), "insertion_moved"),
            (self.draft(after=self.read(left="Note: draft", right="z")), "insertion_not_at_caret"),
        ]
        for draft, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(insertion_proved(draft), reason)

    def test_a_read_that_is_too_short_to_see_the_anchor(self):
        prefix = "x" * (ANCHOR_CHARS + 10)
        draft = self.draft(before=self.read(left=prefix), after=self.read(left=prefix[-5:] + "draft"))
        self.assertEqual(insertion_proved(draft), "insertion_read_too_short")


class TheAlternativeIsKeptBesideTheTake(unittest.TestCase):
    def test_keep_alternative(self):
        entry = {"type": "dictation", "text": "send it now", "original": "send it now"}
        kept = keep_alternative(entry, "Send it now.", "changed_before_caret")
        self.assertEqual(kept["text"], "send it now")
        self.assertEqual(kept["original"], "send it now")
        self.assertEqual(kept["alternatives"], [{"kind": "polished", "text": "Send it now.",
                                                 "reason": "changed_before_caret"}])
        self.assertEqual(keep_alternative(kept, "Send it now.", "too_late")["alternatives"], kept["alternatives"])
        self.assertNotIn("alternatives", entry)


def _drop_period(text: str) -> str:
    """The paste layer's one-sentence rule, as drop_single_sentence_period has it."""
    trimmed = text.rstrip()
    if trimmed.endswith(".") and not trimmed.endswith("..") and sum(trimmed.count(c) for c in ".!?") == 1 \
            and "\n" not in trimmed:
        return trimmed[:-1]
    return text


class ThePolishIsShapedLikeTheDraft(unittest.TestCase):
    def test_unshaped(self):
        self.assertEqual(as_delivered("Send it now.", "send it now", "send it now", _drop_period), "Send it now.")

    def test_the_leading_space(self):
        self.assertEqual(as_delivered("Send it now.", "send it now", " send it now", _drop_period), " Send it now.")
        # A draft that began with a space of its own gets none added.
        self.assertEqual(as_delivered("x", " send it", " send it", _drop_period), "x")

    def test_the_period_a_chat_app_drops(self):
        self.assertEqual(as_delivered("Sounds good to me.", "sounds good.", "sounds good", _drop_period),
                         "Sounds good to me")
        self.assertEqual(as_delivered("Sounds good. See you.", "sounds good.", "sounds good", _drop_period),
                         "Sounds good. See you.", "two sentences keep their period, as the paste layer would")
        self.assertEqual(as_delivered("Sounds good.", "sounds good.", " sounds good", _drop_period), " Sounds good")

    def test_a_shape_it_cannot_read_is_refused(self):
        self.assertIsNone(as_delivered("Send it now.", "send it now", "SEND IT NOW", _drop_period))
        self.assertIsNone(as_delivered("Send it now.", "send it now", "send it", _drop_period))


if __name__ == "__main__":
    unittest.main()
