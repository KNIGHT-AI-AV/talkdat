"""T1 on a Mac: the AX adapter, on a simulated AX provider (tests/simulated_ax.py).

No real accessibility call is made. The module refuses to run if anything loads
ApplicationServices or CoreFoundation through ctypes, and tests/device_guard.py
refuses every AX function besides. Everything the adapter does is reached
through the module object (``vtm.X``), so the mutation tests can swap a
mutant in for any part of it.
"""
from __future__ import annotations

import ctypes
import re
import time
import unittest
from pathlib import Path

from knight_flow import verified_replace as vr
from knight_flow import verified_target_mac as vtm
from tests import test_verified_replace as base
from tests.device_guard import FOREIGN_RULES
from tests.simulated_ax import SimulatedAX, unit_len
from tests.simulated_editor import Desktop

T0 = 1000.0
FIELD, OTHER, ELSEWHERE = (1, ("edit", 1)), (1, ("edit", 2)), (2, ("edit", 3))

# --- the machine check: no AX library is loaded by this module -------------------
_LOADED: list[str] = []
_REAL_INIT = ctypes.CDLL.__init__
_REAL_CORE = vtm._core


def _watching_init(self, name, *args, **kwargs):
    if name and re.search(r"ApplicationServices|CoreFoundation|HIServices", str(name)):
        _LOADED.append(str(name))
        raise AssertionError(f"a T1 Mac test loaded {name}")
    return _REAL_INIT(self, name, *args, **kwargs)


def _no_real_provider():
    raise AssertionError("a T1 Mac test reached the real AX provider")


def setUpModule() -> None:
    ctypes.CDLL.__init__ = _watching_init
    vtm._core = _no_real_provider


def tearDownModule() -> None:
    ctypes.CDLL.__init__ = _REAL_INIT
    vtm._core = _REAL_CORE
    assert not _LOADED, f"AX libraries were loaded: {_LOADED}"


# --- building a desktop and the Mac adapter over it -------------------------------
DRAFTS = {
    **base.DRAFTS,
    "family emoji (ZWJ)": ("send 👨‍👩‍👧 to mum", "Send 👨‍👩‍👧 to Mum."),
    "flag": ("we land in 🇳🇬 today", "We land in 🇳🇬 today."),
    "combining accent": ("café at noon", "Café at noon."),
    "CJK": ("東京に送って", "東京に送ってください。"),
    "emoji next to the anchor": ("🎉 done", "🎉 Done."),
}
PREFIXES = {
    **base.PREFIXES,
    "family emoji (ZWJ)": "Plan: ",
    "flag": "Trip 🛫 ",
    "combining accent": "Lunch: ",
    "CJK": "メモ: ",
    "emoji next to the anchor": "🎉🎉🎉",
}


def build(prefix: str, **options) -> tuple[Desktop, SimulatedAX]:
    desktop = Desktop()
    desktop.add(*FIELD, text=prefix, **options)
    desktop.add(*OTHER, text="another field")
    desktop.add(*ELSEWHERE, text="another window")
    desktop.focus_on(*FIELD)
    return desktop, SimulatedAX(desktop)


def target(desktop: Desktop, ax: SimulatedAX, **options) -> "vtm.MacTarget":
    return vtm.MacTarget(paste=desktop.app_paste, provider=ax, inline=True, **options)


def insert_draft(desktop: Desktop, ax: SimulatedAX, text: str, take: object, route: str = "clipboard") -> vr.Draft:
    reader = target(desktop, ax)
    before = reader.read(vr.read_bound(text) + 8)
    delivered = desktop.app_paste(text)
    after = reader.read(vr.read_bound(text))
    return vr.Draft(take=take, text=text, inserted_at=T0, before=before, after=after, route=route,
                    succeeded=delivered)


def replace(desktop: Desktop, ax: SimulatedAX, draft: vr.Draft, polished: str, **options) -> vr.Outcome:
    settings = {"now_s": T0 + 1.0, "current_take": draft.take, "recording": False, **options}
    return vr.replace_if_proved(target(desktop, ax), draft, polished, **settings)


class TheMatrixOnAMac(unittest.TestCase):
    """T1's whole matrix, every scenario x every draft shape, through the AX
    adapter, against the same three invariants as tests/test_verified_replace."""

    def check(self, shape: str, name: str, **field) -> None:
        draft_text, polished = DRAFTS[shape]
        action, expected = base.TheMatrix.SCENARIOS[name]
        desktop, ax = build(PREFIXES[shape], **field)
        take = object()
        draft = insert_draft(desktop, ax, draft_text, take)
        self.assertEqual(vr.insertion_proved(draft), "", f"{shape}: the draft insertion was not proved")
        action(desktop, len(draft_text))
        before = desktop.everything()
        box = desktop.windows[FIELD[0]][FIELD[1]]
        caret, selection = box.caret, box.selection
        outcome = replace(desktop, ax, draft, polished)
        after = desktop.everything()
        self.assertEqual(outcome.reason, expected, f"{shape} / {name}")
        for key, text in after.items():
            if key != FIELD:
                self.assertEqual(text, before[key], f"{shape} / {name}: wrong target {key}")
        if outcome.replaced:
            field_draft = vr.field_form(before[FIELD][:caret], draft_text)
            start = caret - len(field_draft)
            shaped = box.paste_transform(polished) if box.paste_transform else polished
            self.assertEqual(after[FIELD], before[FIELD][:start] + shaped + before[FIELD][caret:])
            self.assertIsNone(box.selection, f"{shape} / {name}: a selection was left behind")
        else:
            self.assertEqual(after[FIELD], before[FIELD], f"{shape} / {name}: an edit was overwritten")
            self.assertEqual((box.caret, box.selection), (caret, selection), f"{shape} / {name}: caret moved")
            self.assertEqual(outcome.alternative, polished)

    def test_every_scenario_and_shape(self):
        for shape in DRAFTS:
            for name in base.TheMatrix.SCENARIOS:
                with self.subTest(shape=shape, scenario=name):
                    self.check(shape, name)

    def test_a_field_that_stores_line_breaks_as_crlf(self):
        crlf = {"paste_transform": lambda text: text.replace("\n", "\r\n")}
        for name in base.TheMatrix.SCENARIOS:
            with self.subTest(scenario=name):
                self.check("line breaks", name, **crlf)


class TheTakeAndTheClockOnAMac(unittest.TestCase):
    def setUp(self):
        self.desktop, self.ax = build("Note: ")
        self.take = object()
        self.draft = insert_draft(self.desktop, self.ax, "send it now", self.take)
        self.text = dict(self.desktop.everything())

    def outcome(self, **options):
        return replace(self.desktop, self.ax, self.draft, "Send it now.", **options)

    def untouched(self, outcome, reason):
        self.assertFalse(outcome.replaced)
        self.assertEqual(outcome.reason, reason)
        self.assertEqual(outcome.alternative, "Send it now.")
        self.assertEqual(self.desktop.everything(), self.text)

    def test_a_second_dictation(self):
        self.untouched(self.outcome(current_take=object()), "newer_take")

    def test_recording_again(self):
        self.untouched(self.outcome(recording=True), "recording_again")

    def test_a_late_polish(self):
        self.untouched(self.outcome(now_s=T0 + vr.MAX_AGE_SECONDS + 0.01), "too_late")

    def test_an_early_polish_in_time(self):
        self.assertTrue(self.outcome(now_s=T0).replaced)

    def test_an_identical_polish(self):
        outcome = replace(self.desktop, self.ax, self.draft, "send it now")
        self.assertEqual((outcome.replaced, outcome.reason, outcome.alternative), (False, "identical", None))

    def test_an_empty_polish(self):
        outcome = replace(self.desktop, self.ax, self.draft, "  ")
        self.assertEqual((outcome.replaced, outcome.reason, outcome.alternative), (False, "no_polish", None))

    def test_a_failed_paste(self):
        self.desktop.field.accepts_paste = False
        outcome = self.outcome()
        self.untouched(outcome, "paste_failed")
        self.assertIsNone(self.desktop.field.selection)

    def test_a_paste_the_app_dropped(self):
        self.desktop.field.drops_paste = True
        outcome = self.outcome()
        self.assertFalse(outcome.replaced)
        self.assertEqual(outcome.reason, "check_the_text")
        self.assertEqual(outcome.alternative, "Send it now.")
        self.assertEqual(self.desktop.everything(), self.text)
        self.assertIsNone(self.desktop.field.selection)
        self.assertEqual(self.desktop.field.caret, len(self.text[FIELD]))

    def test_a_paste_the_app_changed(self):
        self.desktop.field.paste_transform = lambda text: text.replace("Send", "Sned")
        outcome = self.outcome()
        self.assertEqual((outcome.replaced, outcome.reason), (False, "check_the_text"))
        self.assertIsNone(self.desktop.field.selection)


class FieldsThatAreNeverTargets(unittest.TestCase):
    def draft_in(self, **setup):
        desktop, ax = build("Note: ", **setup.pop("field", {}))
        for name, value in setup.items():
            setattr(ax, name, value) if not isinstance(getattr(ax, name), (dict, set)) else getattr(ax, name).update(value)
        take = object()
        draft = insert_draft(desktop, ax, "send it now", take)
        text = dict(desktop.everything())
        outcome = replace(desktop, ax, draft, "Send it now.")
        self.assertFalse(outcome.replaced)
        self.assertEqual(outcome.alternative, "Send it now.")
        self.assertEqual(desktop.everything(), text)
        return draft, outcome, ax

    def test_a_password_field_is_never_read(self):
        draft, outcome, ax = self.draft_in(field={"password": True})
        self.assertTrue(draft.after.ok and draft.after.password)
        self.assertEqual(outcome.reason, "insertion_unsafe_field")
        self.assertFalse(ax.read_text_of(*FIELD), "the adapter read a password field's text")

    def test_terminals(self):
        for app in ("Terminal.app", "iTerm.app", "Ghostty.app", "kitty.app", "WezTerm.app"):
            with self.subTest(app=app):
                draft, outcome, _ax = self.draft_in(apps={1: app})
                self.assertEqual(outcome.reason, "insertion_unread")

    def test_remote_desktops(self):
        for app in ("Microsoft Remote Desktop.app", "Windows App.app", "Jump Desktop.app", "VNC Viewer.app",
                    "TeamViewer.app", "AnyDesk.app", "Screen Sharing.app", "Parsec.app"):
            with self.subTest(app=app):
                draft, outcome, _ax = self.draft_in(apps={1: app})
                self.assertEqual(outcome.reason, "insertion_unread")

    def test_an_app_nobody_can_name(self):
        draft, outcome, _ax = self.draft_in(apps={1: ""})
        self.assertEqual(outcome.reason, "insertion_unread")

    def test_a_field_without_a_window(self):
        draft, outcome, _ax = self.draft_in(windowless={1})
        self.assertEqual(outcome.reason, "insertion_unread")

    def test_roles_that_are_not_text_fields(self):
        for role in ("AXWebArea", "AXGroup", "AXStaticText", "AXButton", None):
            with self.subTest(role=role):
                draft, outcome, _ax = self.draft_in(roles={FIELD: role})
                self.assertEqual(outcome.reason, "insertion_unread")

    def test_an_unreadable_field(self):
        draft, outcome, _ax = self.draft_in(field={"readable": False})
        self.assertEqual(outcome.reason, "insertion_unread")

    def test_ax_errors(self):
        for method in ("focused", "attribute", "string_for_range", "same"):
            with self.subTest(method=method):
                draft, outcome, _ax = self.draft_in(failing={method})
                self.assertEqual(outcome.reason, "insertion_unread")

    def test_an_app_that_answers_a_shorter_range(self):
        draft, outcome, _ax = self.draft_in(short_reads=True)
        self.assertEqual(outcome.reason, "insertion_unread")


class ReadingTheField(unittest.TestCase):
    def test_a_read_racing_a_focus_change_is_void(self):
        desktop, ax = build("Note: send it now")
        ax.after("focused", 1, lambda: desktop.focus_on(*OTHER))
        self.assertFalse(vtm.read_target(ax, 40).ok)

    def test_a_read_racing_a_caret_move_is_void(self):
        desktop, ax = build("Note: send it now")
        ax.after("string_for_range", 1, lambda: desktop.move(-2))
        self.assertFalse(vtm.read_target(ax, 40).ok)

    def test_offsets_are_utf16_units(self):
        text = "a 👨‍👩‍👧 b 🇳🇬 c é"
        desktop, ax = build(text)
        read = vtm.read_target(ax, 100)
        self.assertTrue(read.ok)
        self.assertEqual(read.left, text)
        self.assertEqual(vtm.utf16_len(text), unit_len(text))
        self.assertGreater(vtm.utf16_len(text), len(text))

    def test_a_read_that_splits_an_emoji_at_its_far_end_drops_the_half(self):
        # 2 * left_chars + 2 units reach into the middle of the first emoji.
        text = "🚀" * 7 + "abcdef"
        desktop, ax = build(text)
        read = vtm.read_target(ax, 4)
        self.assertTrue(read.ok)
        self.assertEqual(read.left, text[-4:])
        wide = vtm.read_target(ax, 9)
        self.assertEqual(wide.left, text[-9:])
        self.assertFalse(any("\ud800" <= ch <= "\udfff" for ch in wide.left))

    def test_right_of_the_caret_is_bounded_and_whole(self):
        desktop, ax = build("x" + "🚀" * 40)
        desktop.click(1)
        read = vtm.read_target(ax, 10)
        self.assertEqual(read.right, ("🚀" * 40)[: vr.ANCHOR_CHARS])

    def test_a_selection_reads_as_not_collapsed(self):
        desktop, ax = build("Note: send it now")
        desktop.select(6, 10)
        read = vtm.read_target(ax, 40)
        self.assertTrue(read.ok)
        self.assertFalse(read.collapsed)

    def test_the_same_field_keeps_its_number_across_targets_and_reads(self):
        desktop, ax = build("Note: ")
        first, second = target(desktop, ax).read(20), target(desktop, ax).read(20)
        self.assertEqual((first.window, first.element), (second.window, second.element))

    def test_two_fields_with_the_same_text_are_different_fields(self):
        desktop, ax = build("same words")
        desktop.windows[OTHER[0]][OTHER[1]].text = "same words"
        here = vtm.read_target(ax, 20)
        desktop.focus_on(*OTHER)
        desktop.field.caret = len(desktop.field.text)
        there = vtm.read_target(ax, 20)
        self.assertEqual((here.left, here.window), (there.left, there.window))
        self.assertNotEqual(here.element, there.element)

    def test_another_window_has_another_number(self):
        desktop, ax = build("Note: ")
        here = vtm.read_target(ax, 20)
        desktop.focus_on(*ELSEWHERE)
        there = vtm.read_target(ax, 20)
        self.assertNotEqual(here.window, there.window)

    def test_element_references_are_released_when_forgotten(self):
        ids = vtm._Identities(limit=2)
        desktop, ax = build("a")
        self.assertEqual(ids.number(ax, ax.focused()), 1)
        for index in range(3):
            desktop.add(3, ("edit", 10 + index), text="x")
            desktop.focus_on(3, ("edit", 10 + index))
            ids.number(ax, ax.focused())
        self.assertEqual(sum(ax.retained.values()), 2)
        desktop.focus_on(*FIELD)
        self.assertEqual(ids.number(ax, ax.focused()), 5, "an evicted element came back with its old number")

    def test_a_hung_app_times_out_unread(self):
        desktop, ax = build("Note: ")
        ax.delay = 0.2
        reader = vtm.MacTarget(paste=desktop.app_paste, provider=ax, timeout=0.05)
        self.assertFalse(reader.read(20).ok)


class SelectingAndPasting(unittest.TestCase):
    def setUp(self):
        self.desktop, self.ax = build("Note: send it now")
        self.mac = target(self.desktop, self.ax)

    def test_selects_exactly_the_draft_and_reads_it_back(self):
        self.assertEqual(self.mac.select_before_caret("send it now"), "send it now")
        self.assertEqual(self.desktop.field.selection, (6, 17))

    def test_never_selects_text_it_has_not_read(self):
        # The draft is not what sits before the caret: nothing may be selected
        # by count over it.
        self.assertIsNone(self.mac.select_before_caret("send it NOW"))
        self.assertNotIn("set_selected_range", [call[0] for call in self.ax.calls])
        self.assertIsNone(self.desktop.field.selection)

    def test_an_app_that_ignores_the_request(self):
        self.ax.selecting[FIELD] = "ignore"
        self.assertIsNone(self.mac.select_before_caret("send it now"))

    def test_an_app_that_selects_something_else(self):
        self.ax.selecting[FIELD] = "other"
        self.assertIsNone(self.mac.select_before_caret("send it now"))
        self.mac.collapse_to(vr.TargetRead(ok=True))
        self.assertEqual((self.desktop.field.caret, self.desktop.field.selection), (17, None))

    def test_an_app_that_selects_less(self):
        self.ax.selecting[FIELD] = "clamp"
        self.assertIsNone(self.mac.select_before_caret("send it now"))
        self.mac.collapse_to(vr.TargetRead(ok=True))
        self.assertEqual((self.desktop.field.caret, self.desktop.field.selection), (17, None))

    def test_an_app_that_refuses(self):
        self.ax.selecting[FIELD] = "refuse"
        self.assertIsNone(self.mac.select_before_caret("send it now"))
        self.mac.collapse_to(vr.TargetRead(ok=True))
        self.assertEqual((self.desktop.field.caret, self.desktop.field.selection), (17, None))

    def test_never_pastes_without_a_selection_it_made(self):
        self.assertFalse(self.mac.paste("Send it now."))
        self.assertEqual(self.desktop.field.text, "Note: send it now")

    def test_never_pastes_after_the_person_moved_the_selection(self):
        self.assertEqual(self.mac.select_before_caret("send it now"), "send it now")
        self.desktop.click(3)
        self.assertFalse(self.mac.paste("Send it now."))
        self.assertEqual(self.desktop.field.text, "Note: send it now")

    def test_never_pastes_into_another_field(self):
        self.assertEqual(self.mac.select_before_caret("send it now"), "send it now")
        self.desktop.focus_on(*OTHER)
        self.desktop.select(0, 7)
        self.assertFalse(self.mac.paste("Send it now."))
        self.assertEqual(self.desktop.windows[OTHER[0]][OTHER[1]].text, "another field")

    def test_restoring_never_touches_another_field(self):
        self.assertEqual(self.mac.select_before_caret("send it now"), "send it now")
        self.desktop.focus_on(*OTHER)
        self.desktop.select(0, 7)
        self.mac.collapse_to(vr.TargetRead(ok=True))
        self.assertEqual(self.desktop.field.selection, (0, 7))

    def test_restoring_with_nothing_selected_by_us_changes_nothing(self):
        self.desktop.select(2, 4)
        self.mac.collapse_to(vr.TargetRead(ok=True))
        self.assertEqual(self.desktop.field.selection, (2, 4))

    def test_a_selection_that_moves_before_the_paste_keeps_the_polish(self):
        desktop, ax = build("Note: ")
        draft = insert_draft(desktop, ax, "send it now", object())
        text = dict(desktop.everything())
        # The person clicks right after the selection was read back as proved.
        ax.after("set_selected_range", 1, lambda: ax.after("attribute", ax._counts["attribute"] + 2,
                                                         lambda: desktop.click(2)))
        outcome = replace(desktop, ax, draft, "Send it now.")
        self.assertFalse(outcome.replaced)
        self.assertEqual(outcome.alternative, "Send it now.")
        self.assertEqual(desktop.everything(), text)
        # The person's click is theirs: the caret stays where they put it.
        self.assertEqual((desktop.field.caret, desktop.field.selection), (2, None))

    def test_a_selection_that_lands_after_the_wait_is_still_undone(self):
        desktop, ax = build("Note: send it now")
        ax.delays["set_selected_range"] = 0.12  # the app takes the selection long after the wait ran out
        mac = vtm.MacTarget(paste=desktop.app_paste, provider=ax, timeout=0.5, write_timeout=0.03, settle=5.0)
        self.assertIsNone(mac.select_before_caret("send it now"))
        mac.collapse_to(vr.TargetRead(ok=True))
        time.sleep(0.3)  # long enough for the slow app's selection to have landed, if it still could
        self.assertEqual((desktop.field.caret, desktop.field.selection), (17, None))
        self.assertEqual(desktop.field.text, "Note: send it now")

    def test_a_person_who_selects_after_a_failed_proof_keeps_their_selection(self):
        self.ax.selecting[FIELD] = "other"
        self.assertIsNone(self.mac.select_before_caret("send it now"))
        self.desktop.select(0, 4)
        self.mac.collapse_to(vr.TargetRead(ok=True))
        self.assertEqual(self.desktop.field.selection, (0, 4))


class TheMachineChecks(unittest.TestCase):
    def test_building_a_target_loads_nothing(self):
        before = list(_LOADED)
        vtm.MacTarget(paste=lambda _text: False)
        self.assertEqual(_LOADED, before)

    def test_the_device_guard_refuses_every_ax_function_the_binding_uses(self):
        source = Path(vtm.__file__).read_text(encoding="utf-8")
        used = set(re.findall(r'bind\(ax, "(AX\w+)"', source))
        pure = {"AXValueCreate", "AXValueGetValue", "AXValueGetType"}  # plain values, no other program
        self.assertTrue(used - pure)
        self.assertLessEqual(used - pure, set(FOREIGN_RULES["applicationservices"]))

    def test_the_app_builds_the_mac_adapter_on_a_mac(self):
        source = Path(vtm.__file__).with_name("app.py").read_text(encoding="utf-8")
        self.assertIn('if sys.platform == "darwin":\n                from .verified_target_mac import MacTarget',
                      source)


if __name__ == "__main__":
    unittest.main()
