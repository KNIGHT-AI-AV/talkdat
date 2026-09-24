from __future__ import annotations

import unittest

from knight_flow.speculative import (
    MAX_REPLACE_AGE_SECONDS,
    MAX_REPLACE_CHARS,
    MAX_REPLACE_MILLISECONDS,
    MILLISECONDS_PER_KEYSTROKE,
    UNDO_REPLACEMENT_CHOICES,
    ReplaceDecision,
    common_prefix_length,
    replacement_plan,
    should_replace,
    undo_replacement_choice,
    undo_replacement_enabled,
    worth_speculating,
)

NOW = 1_800_000_000.0


def state(**kwargs) -> dict:
    base = {
        "pasted_text": "so i think we should ship it",
        "improved_text": "So I think we should ship it.",
        "paste_succeeded": True,
        "paste_window": 12345,
        "foreground_window": 12345,
        "user_typed_since_paste": False,
        "session_active": False,
        "sent_enter": False,
        "pasted_at": NOW - 1.0,
    }
    base.update(kwargs)
    return base


class ItReplacesWhenItIsSafeTests(unittest.TestCase):
    def test_an_improved_rewrite_replaces_the_local_text(self) -> None:
        decision = should_replace(state(), now=NOW)
        self.assertTrue(decision.replace)
        self.assertEqual(decision.backspaces, len("so i think we should ship it"))

    def test_an_identical_rewrite_does_nothing(self) -> None:
        """19% of logged dictations came back unchanged. Replacing text with
        itself is thousands of keystrokes for no visible result."""
        same = state(improved_text=state()["pasted_text"])
        self.assertFalse(should_replace(same, now=NOW).replace)


class ItRefusesWhenItCannotProveSafetyTests(unittest.TestCase):
    """Every one of these destroys work that was never ours.

    The text is already on screen and may already be typed over, so the
    replacement has to refuse itself whenever it cannot prove it is safe. The
    cost of refusing is only that the person keeps the locally formatted text,
    which is exactly what they get today.
    """

    def test_it_will_not_type_into_a_different_window(self) -> None:
        decision = should_replace(state(foreground_window=999), now=NOW)
        self.assertFalse(decision.replace)
        self.assertEqual(decision.reason, "window_changed")

    def test_two_failed_window_reads_do_not_become_permission(self) -> None:
        decision = should_replace(state(paste_window=0, foreground_window=0), now=NOW)
        self.assertFalse(decision.replace)
        self.assertEqual(decision.reason, "window_changed")

    def test_either_unknown_window_refuses_the_replacement(self) -> None:
        for paste_window, foreground_window in ((0, 12345), (12345, 0)):
            with self.subTest(paste_window=paste_window, foreground_window=foreground_window):
                self.assertFalse(
                    should_replace(
                        state(
                            paste_window=paste_window,
                            foreground_window=foreground_window,
                        ),
                        now=NOW,
                    ).replace
                )

    def test_it_stops_once_the_user_has_typed(self) -> None:
        decision = should_replace(state(user_typed_since_paste=True), now=NOW)
        self.assertFalse(decision.replace)
        self.assertEqual(decision.reason, "user_typed")

    def test_it_gives_up_after_the_age_limit(self) -> None:
        decision = should_replace(
            state(pasted_at=NOW - MAX_REPLACE_AGE_SECONDS - 1), now=NOW)
        self.assertFalse(decision.replace)
        self.assertEqual(decision.reason, "too_late")

    def test_it_does_not_replace_after_enter_was_sent(self) -> None:
        """Enter submits in most applications, so the text has already left and
        backspacing would eat whatever the field holds now."""
        decision = should_replace(state(sent_enter=True), now=NOW)
        self.assertFalse(decision.replace)
        self.assertEqual(decision.reason, "already_submitted")

    def test_it_does_not_replace_after_a_failed_paste(self) -> None:
        """Otherwise the backspaces delete whatever is in front of the cursor
        rather than text we put there."""
        decision = should_replace(state(paste_succeeded=False), now=NOW)
        self.assertFalse(decision.replace)
        self.assertEqual(decision.reason, "paste_failed")

    def test_it_stands_down_while_another_dictation_is_recording(self) -> None:
        decision = should_replace(state(session_active=True), now=NOW)
        self.assertFalse(decision.replace)
        self.assertEqual(decision.reason, "recording_again")

    def test_an_expensive_rewrite_keeps_the_local_formatting(self) -> None:
        """What costs keystrokes is the rewrite, not the length of the text.

        This asserted the opposite until the cost was measured: a long text
        was refused outright, however cheap its correction was. The example
        below is the case that exposed it -- hundreds of characters whose
        rewrite only appends a full stop, so the shared prefix covers all of
        it and the edit is zero keystrokes.
        """
        long_text = "word " * 200
        cheap = should_replace(
            state(pasted_text=long_text, improved_text=long_text + "."), now=NOW)
        self.assertTrue(cheap.replace, "appending one character costs nothing to apply")
        self.assertEqual(cheap.backspaces, 0)

        # The same length, rewritten from the first character, retypes all of
        # it -- seconds of visible deleting, which is the reported complaint.
        expensive = should_replace(
            state(pasted_text=long_text, improved_text="Word " + long_text[5:]), now=NOW)
        self.assertFalse(expensive.replace)
        self.assertEqual(expensive.reason, "too_long")

    def test_an_empty_rewrite_never_wipes_good_text(self) -> None:
        self.assertFalse(should_replace(state(improved_text=""), now=NOW).replace)


class ReplacementPlanTests(unittest.TestCase):
    """Only the differing tail is rewritten, because every keystroke skipped is
    a smaller window in which the person can type into the replacement."""

    def test_a_shared_opening_is_not_retyped(self) -> None:
        backspaces, typed = replacement_plan(
            "so i think we should ship it", "so i think we should ship it today")
        self.assertEqual(backspaces, 0)
        self.assertEqual(typed, " today")

    def test_a_changed_opening_rewrites_everything(self) -> None:
        backspaces, typed = replacement_plan("hello there", "Goodbye there")
        self.assertEqual(backspaces, len("hello there"))
        self.assertEqual(typed, "Goodbye there")

    def test_the_plan_reconstructs_the_improved_text_exactly(self) -> None:
        for pasted, improved in [
            ("so i think we should ship it", "So I think we should ship it."),
            ("call mom i mean call dad", "Call dad."),
            ("a", "ab"),
            ("abc", "abc!"),
        ]:
            with self.subTest(pasted=pasted):
                backspaces, typed = replacement_plan(pasted, improved)
                rebuilt = pasted[: len(pasted) - backspaces] + typed
                self.assertEqual(rebuilt, improved)

    def test_common_prefix_handles_empties(self) -> None:
        self.assertEqual(common_prefix_length("", "abc"), 0)
        self.assertEqual(common_prefix_length("abc", ""), 0)
        self.assertEqual(common_prefix_length("abc", "abc"), 3)


class DecisionShapeTests(unittest.TestCase):
    def test_the_decision_is_frozen(self) -> None:
        decision = should_replace(state(), now=NOW)
        self.assertIsInstance(decision, ReplaceDecision)
        with self.assertRaises(Exception):
            decision.replace = False  # type: ignore[misc]

    def test_it_does_not_mutate_the_state(self) -> None:
        original = state()
        snapshot = dict(original)
        should_replace(original, now=NOW)
        self.assertEqual(original, snapshot)


class ItOnlyTouchesWhatItPastedTests(unittest.TestCase):
    """The field usually contains text the replacement must not disturb.

    Two ways that can go wrong. The paste layer prepends a leading space when
    smart_leading_space applies, and the refine path is handed the text without
    it -- so what was typed is one character longer than what the plan counts.
    And people dictate into documents that already have content in front of the
    cursor. Both cases must leave everything before the pasted run untouched.

    Verified with real keystrokes into a focused Tk field as well as here:
    'prior. so i think' became 'prior. So I think.' rather than eating 'prior.'
    """

    def rebuild(self, field: str, believed: str, improved: str) -> str:
        """Apply the plan the way the keyboard does: delete from the end, type."""
        backspaces, typed = replacement_plan(believed, improved)
        return field[: len(field) - backspaces] + typed

    def test_text_before_the_pasted_run_is_untouched(self) -> None:
        self.assertEqual(self.rebuild("existing text ABC", "ABC", "XYZ."), "existing text XYZ.")

    def test_a_prepended_leading_space_is_preserved(self) -> None:
        """The plan counts the text without the space; the space survives in
        front of the correction, which is where it was meant to be."""
        self.assertEqual(self.rebuild(" so i think", "so i think", "So I think."), " So I think.")

    def test_a_shared_prefix_shortens_the_edit(self) -> None:
        backspaces, typed = replacement_plan("ABC", "ABC done.")
        self.assertEqual(backspaces, 0, "nothing needs deleting when only a suffix is added")
        self.assertEqual(typed, " done.")

    def test_it_never_deletes_more_than_it_pasted(self) -> None:
        """The count is bounded by the pasted run, so no amount of difference
        between the two versions can reach into text that was already there."""
        for believed, improved in [("a", "completely different"), ("short", ""), ("abc", "xyz")]:
            with self.subTest(believed=believed):
                backspaces, _ = replacement_plan(believed, improved)
                self.assertLessEqual(backspaces, len(believed))

class ReplacementMustNotBeWatchableTests(unittest.TestCase):
    """A correction that takes 30 seconds is worse than no correction.

    pyautogui applies a 0.1 second PAUSE between every call, so pressing
    backspace in a Python loop deleted a 300 character paragraph at ten
    characters a second -- 31 seconds of the text visibly eating itself.
    Reported from real use, and measured at 102ms per keystroke.

    The fix is to let pyautogui repeat the key internally and suspend PAUSE
    for the duration: the same paragraph now takes about a third of a second.
    These assert the shape of that, since timing itself belongs in a probe
    rather than a test suite.
    """

    def source(self) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[1] / "knight_flow" / "paste.py").read_text(encoding="utf-8")

    def body(self) -> str:
        src = self.source()
        return src[src.index("def _replace_typed_text_unlocked"):][:3000]

    def test_backspaces_are_one_call_not_a_loop(self) -> None:
        body = self.body()
        self.assertIn("presses=backspaces", body,
                      "a Python loop pays pyautogui's PAUSE on every keystroke")
        self.assertNotIn("for _ in range(backspaces)", body)

    def test_the_global_pause_is_suspended_and_restored(self) -> None:
        body = self.body()
        self.assertIn("pyautogui.PAUSE = 0", body)
        self.assertIn("pyautogui.PAUSE = previous_pause", body)
        self.assertIn("finally:", body, "the pause must be restored even if typing raises")

    def test_it_does_not_touch_the_clipboard(self) -> None:
        """A clipboard paste measured marginally faster, but a correction
        landing a second later must not overwrite what the person just copied."""
        body = self.body()
        self.assertNotIn("copy_text(replacement)", body)
        self.assertNotIn('hotkey("ctrl", "v")', body)

    # Measured on this machine after the pause fix: 243 characters in 0.54s.
    SECONDS_PER_CHARACTER = 0.0022

    def test_the_worst_case_stays_under_two_seconds(self) -> None:
        """The cap is a time budget, not a view about length.

        Asserting a character count directly is what this test did first, and
        it went stale the moment replacement got twenty times faster -- it
        failed for a change that made the product better. Deriving the bound
        from the measured rate keeps it meaningful when the rate changes again.
        """
        worst_case = MAX_REPLACE_CHARS * self.SECONDS_PER_CHARACTER
        self.assertLess(worst_case, 2.0,
                        f"a {MAX_REPLACE_CHARS} character replacement would take {worst_case:.1f}s")

    def test_the_budget_is_short_enough_to_read_as_a_flicker(self) -> None:
        """600ms was chosen against a measured 4.3ms a keystroke.

        The previous version of this asserted the cap was at least 600
        *characters*, so that "a few sentences still gets corrected". At the
        real rate that is 2.6 seconds of visible deleting, and the cap was
        actually 900 -- 3.9 seconds. The assertion protected the symptom it
        was supposed to prevent, because it was written in characters while
        the complaint was about time.
        """
        self.assertLessEqual(MAX_REPLACE_MILLISECONDS, 600)
        self.assertAlmostEqual(
            MAX_REPLACE_CHARS * MILLISECONDS_PER_KEYSTROKE,
            MAX_REPLACE_MILLISECONDS,
            delta=MILLISECONDS_PER_KEYSTROKE,
        )

    def test_long_dictation_never_speculates_so_it_never_needs_correcting(self) -> None:
        """The other half of the fix, and the half that matters most.

        Capping the correction alone would have left long dictation showing
        the local formatting and silently never improving it. Instead it does
        not speculate at all: it waits for the model, about 950ms, and the
        finished text arrives once with no edit. A second at the end of a
        paragraph someone spent thirty seconds speaking is not noticeable.
        Watching that paragraph delete itself is.
        """
        self.assertTrue(worth_speculating(40), "a short phrase corrects in well under the budget")
        self.assertTrue(worth_speculating(MAX_REPLACE_CHARS))
        self.assertFalse(worth_speculating(MAX_REPLACE_CHARS + 1))
        self.assertFalse(worth_speculating(900), "the reported case: a whole paragraph")

if __name__ == "__main__":
    unittest.main()


class UndoReplacementIsConstantTimeTests(unittest.TestCase):
    """The only way found to make replacement not depend on length.

    Editors group a paste into one undo step, so Ctrl+Z removes it in a single
    operation and the whole correction is two chords. Measured against a real
    focused editor at 100, 300 and 900 characters: 197ms, 196ms, 197ms. The
    keystroke path is 4.3ms a character, which is 3.9 seconds at 900.

    Batching was tried before this and does not work: one Win32 SendInput call
    carrying the whole edit measured *slower* than one call per key, because
    Windows throttles synthetic input per event. Length is only escapable by
    not sending one event per character.

    On by default only where the undo grouping was measured -- Win32 edit
    controls and Chromium -- and off everywhere else, which is what "auto"
    means. These tests pin that it is not simply on. An application with no
    undo ignores Ctrl+Z and the correction lands after the original instead of
    over it, so the text appears twice -- worse than a slow delete, and
    undetectable from our side because the target's contents cannot be read
    back.
    """

    def test_the_shipped_default_asks_the_application_rather_than_assuming(self) -> None:
        """Not `True`. The difference is somebody's text appearing twice in an
        editor nobody tested, and there are two of those that matter."""
        from knight_flow.config import DEFAULT_CONFIG
        self.assertEqual(DEFAULT_CONFIG["dictation"]["undo_replacement"], "auto")

    def test_the_default_is_still_off_in_an_untested_application(self) -> None:
        self.assertFalse(undo_replacement_enabled("auto", verified_application=False))

    def test_length_stops_deciding_when_undo_is_on(self) -> None:
        self.assertFalse(worth_speculating(900), "backspacing 900 characters takes 3.9 seconds")
        self.assertTrue(worth_speculating(900, undo_replacement=True))
        self.assertTrue(worth_speculating(9_000, undo_replacement=True),
                        "undo costs the same at any length, so there is no ceiling")

    def test_the_keystroke_budget_does_not_apply_to_undo(self) -> None:
        long_text = "word " * 200
        rewritten = "Word " + long_text[5:]
        keystrokes = should_replace(state(pasted_text=long_text, improved_text=rewritten), now=NOW)
        self.assertFalse(keystrokes.replace, "too many keystrokes to watch")
        self.assertEqual(keystrokes.reason, "too_long")

        undo = should_replace(
            state(pasted_text=long_text, improved_text=rewritten, undo_replacement=True), now=NOW)
        self.assertTrue(undo.replace, "undo does not pay per character")

    def test_undo_never_overrides_a_safety_refusal(self) -> None:
        """Every reason to refuse is about correctness, not cost. Undo makes
        the edit cheap; it does not make it safe to aim at the wrong window."""
        for unsafe in (
            {"foreground_window": 999},
            {"user_typed_since_paste": True},
            {"paste_succeeded": False},
            {"sent_enter": True},
            {"session_active": True},
        ):
            with self.subTest(**unsafe):
                decision = should_replace(state(undo_replacement=True, **unsafe), now=NOW)
                self.assertFalse(decision.replace)

    def test_the_helper_restores_the_clipboard(self) -> None:
        """The correction sits on the clipboard for the moment it takes to
        paste. Leaving it there overwrites whatever the person copied."""
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "paste.py").read_text(encoding="utf-8")
        body = source[source.index("def replace_by_undo"):][:5200]
        self.assertIn("restore_clipboard_if_unchanged", body)
        # The modifier is Ctrl on Windows and Command on macOS, so the chord is
        # sent through EDIT_MODIFIER rather than a literal.
        self.assertIn('hotkey(EDIT_MODIFIER, "z")', body)

    def test_undo_is_refused_when_the_text_was_typed_rather_than_pasted(self) -> None:
        """The shipped app no longer invokes undo replacement for any route."""
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "app.py").read_text(encoding="utf-8")
        self.assertIn("speculative = False", source)
        self.assertNotIn("replace_by_undo", source)

    def test_the_refine_worker_is_told_how_the_text_was_delivered(self) -> None:
        """Without the method the guard above cannot exist."""
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "app.py").read_text(encoding="utf-8")
        self.assertIn("paste_method=str(delivery.get(\"method\") or \"\")", source)
        self.assertIn("paste_method: str = \"\"", source)


class UndoReplacementIsDecidedPerApplicationTests(unittest.TestCase):
    """The setting has three states because two cannot describe the evidence.

    Undo replacement is constant time -- 197ms at 100, 300 and 900 characters
    -- and was verified correct in Win32 edit controls and in Chromium. It is
    unverified in RichEdit and Monaco, where a wrong guess pastes the
    correction after the original and the person sees their words twice.

    A boolean forces one of those facts to be ignored. "auto" does not.
    """

    def test_auto_follows_the_application(self) -> None:
        self.assertTrue(undo_replacement_enabled("auto", verified_application=True))
        self.assertFalse(undo_replacement_enabled("auto", verified_application=False))

    def test_always_and_never_ignore_the_application(self) -> None:
        for verified in (True, False):
            with self.subTest(verified=verified):
                self.assertTrue(undo_replacement_enabled("always", verified_application=verified))
                self.assertFalse(undo_replacement_enabled("never", verified_application=verified))

    def test_a_config_from_an_older_release_still_means_what_it_meant(self) -> None:
        """The setting was a bool before this. Someone who wrote `true` by hand
        asked for it everywhere, and must not be quietly downgraded to auto."""
        self.assertTrue(undo_replacement_enabled(True, verified_application=False))
        self.assertFalse(undo_replacement_enabled(False, verified_application=True))

    def test_an_unreadable_setting_is_the_safe_one(self) -> None:
        """Anything unrecognised has to fall to the slow path, because the fast
        path is the one that can duplicate someone's text."""
        for setting in (None, "yes-please", "maybe", [], {}, 0.5):
            with self.subTest(setting=setting):
                self.assertFalse(
                    undo_replacement_enabled(setting, verified_application=False),
                    "an unreadable setting must never enable undo on its own",
                )

    def test_a_missing_setting_reads_as_auto(self) -> None:
        """An empty string is what a cleared combobox writes."""
        self.assertTrue(undo_replacement_enabled("", verified_application=True))

    def test_the_displayed_choice_and_the_behaviour_cannot_disagree(self) -> None:
        """Settings shows `undo_replacement_choice`; the paste path acts on
        `undo_replacement_enabled`. Two parsers would eventually drift, so one
        is written in terms of the other and this pins that."""
        for setting in ("auto", "always", "never", "", True, False, None, "nonsense", 1):
            for verified in (True, False):
                with self.subTest(setting=setting, verified=verified):
                    choice = undo_replacement_choice(setting)
                    self.assertIn(choice, UNDO_REPLACEMENT_CHOICES)
                    expected = verified if choice == "auto" else choice == "always"
                    self.assertEqual(
                        undo_replacement_enabled(setting, verified_application=verified),
                        expected,
                        f"Settings would show {choice!r} while the paste path did the opposite",
                    )

    def test_case_and_whitespace_do_not_change_the_meaning(self) -> None:
        self.assertEqual(undo_replacement_choice("  AUTO  "), "auto")
        self.assertEqual(undo_replacement_choice("Always"), "always")


class AFailedUndoNeverFallsIntoBlindBackspacingTests(unittest.TestCase):
    """A boolean failure cannot prove whether Ctrl+Z already committed.

    Backspacing after an undo attempt may delete text preceding the dictation.
    Backspace-and-type can also fail after deletion begins. Speculative
    correction therefore has one automatic route: a measured one-undo/one-paste
    transaction. Every other result keeps the safe local formatting.
    """

    def source(self) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[1] / "knight_flow" / "app.py").read_text(encoding="utf-8")

    def test_the_refine_path_contains_no_typed_fallback(self) -> None:
        source = self.source()
        block = source.split("def _refine_after_paste", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("safe single delivery is active", block)
        self.assertNotIn("replace_by_undo", block)
        self.assertNotIn("replace_typed_text(", block)

    def test_the_app_no_longer_imports_the_backspace_budget(self) -> None:
        source = self.source()
        self.assertNotIn("MAX_REPLACE_CHARS", source.split("class TalkDatApp", 1)[0])

    def test_waiving_the_budget_is_still_tied_to_undo(self) -> None:
        """If this stops being conditional, every long dictation backspaces."""
        from knight_flow.speculative import should_replace
        long_text = "a" * (MAX_REPLACE_CHARS + 200)
        base = dict(
            pasted_text=long_text,
            improved_text="b" + long_text,
            paste_succeeded=True,
            paste_window=7,
            foreground_window=7,
            pasted_at=NOW,
        )
        self.assertFalse(should_replace({**base, "undo_replacement": False}, now=NOW).replace)
        self.assertTrue(should_replace({**base, "undo_replacement": True}, now=NOW).replace)


class UndoIsSpentOnlyWhereItBuysSomethingTests(unittest.TestCase):
    """Which corrections take the risky path, and why so few of them do.

    Undo has exactly one failure mode: an application that groups undo
    differently from a paste leaves the text twice over, and there is no way to
    read the target back and find out. Every correction routed through it is an
    exposure to that.

    Under the keystroke budget it buys almost nothing -- 120-301ms of typing
    against a flat 156ms -- so roughly 100ms is not worth the exposure, and
    ordinary one-sentence dictation stays on the path that is incapable of
    duplicating anything.

    Past the budget the comparison changes completely. The keystroke path is
    not slower there, it is refused: a paragraph deleting itself for seconds is
    worse than keeping the local formatting, which is what the product did
    before any of this. So the real choice is undo against no correction at
    all, and that is worth the exposure.
    """

    def decide(self, backspaces: int, *, undo: bool):
        pasted = "x" * (backspaces + 40)
        improved = pasted[:40] + "y" * backspaces
        return should_replace(
            state(pasted_text=pasted, improved_text=improved, undo_replacement=undo),
            now=NOW,
        )

    def test_a_short_correction_types_even_when_undo_is_available(self) -> None:
        decision = self.decide(MAX_REPLACE_CHARS - 1, undo=True)
        self.assertTrue(decision.replace)
        self.assertFalse(
            decision.use_undo,
            "undo saves ~100ms here and risks the text appearing twice; that is a bad trade",
        )
        self.assertEqual(decision.reason, "replace")

    def test_a_long_correction_uses_undo_when_it_is_available(self) -> None:
        decision = self.decide(MAX_REPLACE_CHARS + 1, undo=True)
        self.assertTrue(decision.replace)
        self.assertTrue(decision.use_undo)
        self.assertEqual(decision.reason, "replace_by_undo")

    def test_a_long_correction_is_still_refused_without_undo(self) -> None:
        decision = self.decide(MAX_REPLACE_CHARS + 1, undo=False)
        self.assertFalse(decision.replace)
        self.assertEqual(decision.reason, "too_long")

    def test_the_boundary_is_the_measured_budget_and_not_an_off_by_one(self) -> None:
        """Exactly at the budget is still affordable to type."""
        self.assertFalse(self.decide(MAX_REPLACE_CHARS, undo=True).use_undo)
        self.assertTrue(self.decide(MAX_REPLACE_CHARS + 1, undo=True).use_undo)

    def test_a_refusal_never_carries_use_undo(self) -> None:
        """Every safety refusal must come back with nothing to act on."""
        refusals = [
            state(pasted_text="", improved_text="anything", undo_replacement=True),
            state(pasted_text="a", improved_text="", undo_replacement=True),
            state(pasted_text="a", improved_text="b", paste_succeeded=False, undo_replacement=True),
            state(pasted_text="a", improved_text="b", user_typed_since_paste=True, undo_replacement=True),
            state(pasted_text="a", improved_text="b", sent_enter=True, undo_replacement=True),
        ]
        for index, refusal in enumerate(refusals):
            with self.subTest(index=index):
                decision = should_replace(refusal, now=NOW)
                self.assertFalse(decision.replace)
                self.assertFalse(decision.use_undo)

    def test_the_caller_acts_on_the_decision_rather_than_the_setting(self) -> None:
        """The shipped caller must not perform any post-paste correction."""
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "app.py").read_text(encoding="utf-8")
        self.assertIn("speculative = False", source)
        self.assertNotIn("replace_by_undo", source)
