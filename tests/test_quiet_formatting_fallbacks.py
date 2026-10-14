"""A take that fell back to the rules formatter is a normal take.

The owner, 2026-10-09, shown "Your text was formatted by the built-in rules,
not the model. The model's edit failed a meaning check": "This should just
happen. We don't need to tell people that we formatted it slightly better."

So when the words arrived through the rules formatter because the model's edit
was refused by the meaning check, timed out, overran the budget, came back
empty or the model was still warming up, the Pill says nothing extra and the
reason goes to the log. A reason the person can act on (the model is missing,
this PC is too slow for the budget, an unknown refusal) is still said once:
that is X-465 (tests/test_a_local_failure_is_never_silent.py), and without it
Chill and Executive would quietly do nothing on a machine that cannot run them.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow.app import local_finish_is_worth_saying
from knight_flow.formatting import note_local_finish_refusal, take_local_finish_notice
from knight_flow.paste import PasteReceipt
from tests.test_esc_while_processing_keeps_the_words import processing_app

QUIET = ("model_safety_fallback", "polish_safety_fallback", "timeout", "budget_exceeded",
         "invalid_response", "preparing")
PASTED = PasteReceipt(True, "clipboard", "clipboard", ("clipboard",))
FAILED = PasteReceipt(False, "clipboard", "none", ("clipboard",))
COPIED = PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))
FAILED_LINE = ("error", "Insertion and clipboard unavailable. Transcript kept for retry. Mic off.")


CAPTURED_LINE = ("captured", "Captured locally. Auto paste is off.")
TRANSLATION_LINE = ("error", "Translation unavailable; the original text was kept safely.")
BUILT_IN_RULES = "Your text was formatted by the built-in rules, not the model"


def answers(receipts):
    """paste_text_with_receipt's answers in order, the last one repeating."""
    queue = list(receipts)
    return lambda *_args, **_kwargs: queue.pop(0) if len(queue) > 1 else queue[0]


def translation(fails: bool):
    """Automatic translation on, failing as a missing local model does; or untouched."""
    from contextlib import ExitStack, nullcontext

    from knight_flow.translation import TranslationError

    if not fails:
        return nullcontext()
    stack = ExitStack()
    stack.enter_context(patch("knight_flow.app.auto_translation_enabled", return_value=True))
    stack.enter_context(patch("knight_flow.app.translate_text",
                              side_effect=TranslationError("model_missing", "The translation model is not installed.")))
    return stack
SAID = ("too_slow", "model_unavailable", "the local model is not running")
FALLBACK_WORDS = ("built-in rules", "meaning check", "Executive polish was skipped", "kept in Chill",
                  "kept with rules formatting")


def assert_the_line_follows_the_take(test: unittest.TestCase, events: list[dict], title: str) -> None:
    """Review CL4-2 (2026-10-10): what the Pill is handed, in order, with what it reads.

    The take's own "Captured locally. Auto paste is off." (said as a warn) comes first and
    nothing is flagged before it. Then exactly one flag: the line, an error the person
    caused, keyed "formatting", that waits behind the take's line (after_key "state").
    The Pill's own queue decides the rest (tests/test_the_formatting_line_reaches_the_pill.py)."""
    said = [(event["kind"], event.get("state"), event["message"]) for event in events]
    captured = [index for index, event in enumerate(events)
                if event["kind"] == "state" and (event["state"], event["message"]) == CAPTURED_LINE]
    test.assertEqual(len(captured), 1, said)
    test.assertEqual(events[captured[0]]["say"], "warn")
    test.assertFalse([event for event in events[:captured[0]] if event["kind"] == "flag"],
                     f"a flag reached the Pill before the take's own line: {said}")
    after = events[captured[0] + 1:]
    test.assertEqual([event["kind"] for event in after], ["flag"], said)
    line = after[0]
    test.assertTrue(line["message"].startswith(title), line)
    test.assertEqual((line["tone"], line["key"], line["origin"], line["after_key"]),
                     ("error", "formatting", "person", "state"), line)


class QuietFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        take_local_finish_notice()

    def tearDown(self) -> None:
        take_local_finish_notice()

    def deliver(self, notice: str, receipts=(PASTED,), *, auto_paste=True, translation_fails=False):
        app, token = processing_app()
        app.config["dictation"]["auto_paste"] = auto_paste

        def formatted(*_args, **_kwargs):
            # The formatter records its reason while it runs, as format_dictation does.
            note_local_finish_refusal(notice)
            return SimpleNamespace(original="the words", text="The words.", send_enter=False)

        with patch("knight_flow.app.process_dictation", side_effect=formatted), \
             patch("knight_flow.app.paste_text_with_receipt", side_effect=answers(receipts)), \
             patch("knight_flow.app.foreground_window_id", return_value=111), \
             translation(translation_fails):
            result = app.handle_dictation("the words", delivery_token=token, guided_sink=None)
        return app, result

    def test_with_auto_paste_off_the_reason_follows_the_take(self) -> None:
        # Review F1 (2026-10-10): with Auto paste off every take is captured, never
        # pasted, so none ever ended on the routine line and the reason was never said.
        # The take's own line stays; the reason follows it on the Pill.
        for code in SAID:
            with self.subTest(code=code):
                app, result = self.deliver(code, auto_paste=False)
                self.assertTrue(result["delivery"]["success"])
                self.assertEqual(app.overlay.states[-1], CAPTURED_LINE)
                self.assertTrue(any(toast.startswith(BUILT_IN_RULES) for toast in app.overlay.toasts), app.overlay.toasts)

    def test_with_auto_paste_off_the_pill_is_handed_the_takes_line_then_the_reason(self) -> None:
        # Review CL4-2 (2026-10-10): the round 4 fake kept states and flags apart and
        # dropped tone, key and origin, so a line that hid "Captured locally" (tone warn
        # or error, key "state") or was flagged before it passed every test.
        for code in SAID:
            with self.subTest(code=code):
                app, _result = self.deliver(code, auto_paste=False)
                assert_the_line_follows_the_take(self, app.overlay.events, BUILT_IN_RULES)

    def test_a_failed_translation_keeps_its_own_line(self) -> None:
        # Review F2/T3-1: a translation that failed is this take's own news, so the
        # reason does not take its place either.
        for code in SAID:
            with self.subTest(code=code):
                app, _result = self.deliver(code, translation_fails=True)
                self.assertEqual(app.overlay.states[-1], TRANSLATION_LINE)

    def test_a_reason_worth_saying_never_hides_a_failed_insertion(self) -> None:
        # Review J-B1 (2026-10-10): the X-465 line came before every delivery outcome,
        # so a take whose words never went in said only "formatted by the built-in
        # rules". The take's own outcome comes first; the reason is said on a take that
        # landed (it recurs: the model is still missing).
        for code in SAID:
            with self.subTest(code=code):
                app, result = self.deliver(code, receipts=(FAILED, FAILED))
                self.assertFalse(result["delivery"]["success"])
                self.assertEqual(app.overlay.states[-1], FAILED_LINE)

    def test_a_per_take_fallback_says_nothing_extra(self) -> None:
        for code in QUIET:
            with self.subTest(code=code):
                app, result = self.deliver(code)
                said = [message for _state, message in app.overlay.states]
                self.assertFalse([m for m in said if any(word in m for word in FALLBACK_WORDS)], said)
                self.assertTrue(result["delivery"]["success"])
                self.assertEqual(take_local_finish_notice(), "", "the notice is used up, not left for the next take")

    def test_a_reason_the_person_can_act_on_is_still_said_once(self) -> None:
        for code in SAID:
            with self.subTest(code=code):
                app, _result = self.deliver(code)
                self.assertIn(("error", "Your text was formatted by the built-in rules, not the model."),
                              app.overlay.states)

    def test_the_quiet_codes_are_exactly_the_per_take_ones(self) -> None:
        for code in QUIET:
            self.assertFalse(local_finish_is_worth_saying(code), code)
            self.assertFalse(local_finish_is_worth_saying(f"  {code.upper()} "), code)
        for code in SAID:
            self.assertTrue(local_finish_is_worth_saying(code), code)
        self.assertFalse(local_finish_is_worth_saying(""))

    def test_the_takes_history_entry_keeps_what_the_pill_no_longer_says(self) -> None:
        # Overwatch's review, 2026-10-09: hiding the notice must not hide the fact. If
        # the words came through the built-in rules, the take's own History entry says
        # so, in the words the Pill used to say it.
        wording = ("Your text was formatted by the built-in rules, not the model.",
                   "Executive polish was skipped. Your text was kept in Chill.")
        for code in QUIET + SAID:
            with self.subTest(code=code):
                app, _result = self.deliver(code)
                self.assertIn(app.history[-1].get("format_note", ""), wording,
                              "the fallback left no trace outside the log")

    def test_a_take_formatted_as_asked_carries_no_note(self) -> None:
        app, _result = self.deliver("")
        self.assertNotIn("format_note", app.history[-1])

    def test_a_quiet_fallback_still_reaches_the_log(self) -> None:
        with self.assertLogs("knight_flow.app", level="INFO") as logs:
            self.deliver("model_safety_fallback")
        self.assertTrue(any("model_safety_fallback" in line for line in logs.output), logs.output)


class RepeatedFallbacksEscalateTests(unittest.TestCase):
    """Overwatch's review B4 (2026-10-10): quiet per take must not mean quiet for ever.
    The local model records its speed only when a reply arrives, so one that times out on
    every take never becomes "too slow" (llm.py's own 2026-09-22 note saw this on the
    owner's PC), and Chill or Executive would silently never apply. After 3 fallbacks of
    the same stalling kind in a row, the Pill says once what is happening and what to do;
    a take formatted as asked resets the count. The meaning-check fallbacks stay quiet:
    those are the owner's own case."""

    TITLE = "Formatting isn't being applied."

    def setUp(self) -> None:
        take_local_finish_notice()

    def tearDown(self) -> None:
        take_local_finish_notice()

    def takes(self, codes) -> list[bool]:
        """Deliver one take per code ("" is a take formatted as asked) on what is, take
        to take, one app: the streak the last take left is carried into the next."""
        said, streak = [], None
        for code in codes:
            app, token = processing_app()
            if streak is not None:
                app._quiet_fallback_streak = streak

            def formatted(*_args, code=code, **_kwargs):
                if code:
                    note_local_finish_refusal(code)
                return SimpleNamespace(original="the words", text="The words.", send_enter=False)

            with patch("knight_flow.app.process_dictation", side_effect=formatted), \
                 patch("knight_flow.app.paste_text_with_receipt",
                       return_value=PasteReceipt(True, "clipboard", "clipboard", ("clipboard",))), \
                 patch("knight_flow.app.foreground_window_id", return_value=111):
                app.handle_dictation("the words", delivery_token=token, guided_sink=None)
            said.append(any(message == self.TITLE for _state, message in app.overlay.states))
            streak = getattr(app, "_quiet_fallback_streak", None)
        return said

    def test_three_stalls_in_a_row_say_one_line(self) -> None:
        for code in ("timeout", "budget_exceeded", "invalid_response", "preparing"):
            with self.subTest(code=code):
                self.assertEqual(self.takes([code] * 5), [False, False, True, False, False])

    def test_an_isolated_stall_stays_quiet(self) -> None:
        self.assertEqual(self.takes(["timeout", "", "timeout", "", "timeout", "invalid_response"]), [False] * 6)

    def test_a_take_formatted_as_asked_starts_the_count_again(self) -> None:
        self.assertEqual(self.takes(["timeout"] * 3 + [""] + ["timeout"] * 3),
                         [False, False, True, False, False, False, True])

    def test_the_meaning_check_fallbacks_never_escalate(self) -> None:
        for code in ("model_safety_fallback", "polish_safety_fallback"):
            with self.subTest(code=code):
                self.assertEqual(self.takes([code] * 5), [False] * 5)

    ESCALATION = ("error", TITLE)

    def lines(self, takes) -> list[tuple[str, str]]:
        """The Pill's last line after each (code, outcome) take, the streak carried over."""
        return [state for state, _toasts in self.run_takes(takes)]

    def run_takes(self, takes) -> list[tuple[tuple[str, str], list[str]]]:
        """(the Pill's last line, the flags said after it) for each (code, outcome) take.

        outcome: "pasted"; "failed" (no insertion and no copy); "copied" (the insertion
        failed and the recovery copy worked); "auto paste off"; "setup" (the Setup test's
        own sink took the words); "translation failed" (pasted untranslated); "auto paste
        off, translation failed" (captured untranslated). self.overlays keeps each take's
        overlay, with its ordered events."""
        result, streak = [], None
        self.overlays = []
        for code, outcome in takes:
            app, token = processing_app()
            self.overlays.append(app.overlay)
            if streak is not None:
                app._quiet_fallback_streak = streak
            sink = None
            if "auto paste off" in outcome:
                app.config["dictation"]["auto_paste"] = False
            if outcome == "setup":
                sink = [].append
                app.overlay.onboarding_test_sink = sink
                app._guided_delivery_token = token  # Setup still owns this take
            receipts = {"failed": [FAILED, FAILED], "copied": [FAILED, COPIED]}.get(outcome, [PASTED])

            def formatted(*_args, code=code, **_kwargs):
                if code:
                    note_local_finish_refusal(code)
                return SimpleNamespace(original="the words", text="The words.", send_enter=False)

            with patch("knight_flow.app.process_dictation", side_effect=formatted), \
                 patch("knight_flow.app.paste_text_with_receipt", side_effect=answers(receipts)), \
                 patch("knight_flow.app.foreground_window_id", return_value=111), \
                 translation("translation failed" in outcome):
                app.handle_dictation("the words", delivery_token=token, guided_sink=sink)
            result.append((app.overlay.states[-1], list(app.overlay.toasts)))
            streak = getattr(app, "_quiet_fallback_streak", None)
        return result

    def test_a_failed_insertion_on_the_escalating_take_is_said_and_the_line_waits(self) -> None:
        # Review J-B1 (2026-10-10): on the take where the line was due, it replaced that
        # take's own outcome, so a failed insertion went unsaid, and the line was spent.
        # The take's outcome is said; the line waits for the next stall that landed.
        lines = self.lines([("timeout", "pasted"), ("timeout", "pasted"), ("timeout", "failed"),
                            ("timeout", "pasted"), ("timeout", "pasted")])
        self.assertEqual(lines[2], FAILED_LINE)
        self.assertEqual(lines[3], self.ESCALATION)
        self.assertNotEqual(lines[4], self.ESCALATION)

    def test_every_other_outcome_keeps_its_own_line_too(self) -> None:
        # The take's own news is said, and the line waits for the next stall that landed.
        for outcome, line in (("copied", ("captured", "Insertion unavailable. Copied for manual paste. Mic off.")),
                              ("setup", ("captured", "Setup test complete. Mic off.")),
                              ("translation failed", TRANSLATION_LINE)):
            with self.subTest(outcome=outcome):
                lines = self.lines([("timeout", "pasted")] * 2 + [("timeout", outcome), ("timeout", "pasted")])
                self.assertEqual(lines[2], line)
                self.assertEqual(lines[3], self.ESCALATION)

    def test_with_auto_paste_off_the_line_follows_the_take_once(self) -> None:
        # Review F1 (2026-10-10): with Auto paste off no take ever lands as a paste, so a
        # line that waited for one was never said: B4 again. The take keeps "Captured
        # locally"; the line follows it on the Pill on the third stall, once.
        said = self.run_takes([("timeout", "auto paste off")] * 6)
        self.assertEqual([state for state, _toasts in said], [CAPTURED_LINE] * 6)
        escalations = [[toast for toast in toasts if toast.startswith(self.TITLE.rstrip("."))] for _state, toasts in said]
        self.assertEqual([len(found) for found in escalations], [0, 0, 1, 0, 0, 0])
        self.assertIn("Settings > Writing > Formatting", escalations[2][0])

    def test_with_auto_paste_off_the_pill_is_handed_the_takes_line_then_the_escalation(self) -> None:
        # Review CL4-2: the same order and the same attributes for the escalation.
        self.run_takes([("timeout", "auto paste off")] * 3)
        assert_the_line_follows_the_take(self, self.overlays[2].events, self.TITLE.rstrip("."))
        for overlay in self.overlays[:2]:
            self.assertFalse([event for event in overlay.events if event["kind"] == "flag"], overlay.events)

    def test_with_auto_paste_off_a_failed_translation_keeps_its_line_and_the_escalation_waits(self) -> None:
        # Review TL4-3 (W2): Auto paste off and a failed translation on the escalating
        # take. The translation's line is that take's news and nothing follows it; the
        # escalation stays due and follows the next captured take.
        said = self.run_takes([("timeout", "auto paste off")] * 2
                              + [("timeout", "auto paste off, translation failed"), ("timeout", "auto paste off")])
        self.assertEqual(said[2][0], TRANSLATION_LINE)
        self.assertFalse([event for event in self.overlays[2].events if event["kind"] == "flag"], self.overlays[2].events)
        self.assertEqual(said[3][0], CAPTURED_LINE)
        assert_the_line_follows_the_take(self, self.overlays[3].events, self.TITLE.rstrip("."))

    def test_a_still_preparing_model_keeps_its_own_count(self) -> None:
        # Review T3-2 (K02, K03): preparing is neither slow nor empty, so it neither adds
        # to nor takes from their counts.
        self.assertEqual(self.takes(["preparing", "preparing", "timeout"]), [False] * 3)
        self.assertEqual(self.takes(["invalid_response", "preparing", "invalid_response"]), [False] * 3)
        self.assertEqual(self.takes(["preparing"] * 3), [False, False, True])

    def test_every_stalling_code_has_a_kind(self) -> None:
        # Review T3-5: a stalling code added without a kind would have crashed the take.
        from knight_flow.app import STALL_KIND, STALLING_LOCAL_FINISH, quiet_fallback_streak

        self.assertEqual(set(STALL_KIND), set(STALLING_LOCAL_FINISH))
        with patch.dict(STALLING_LOCAL_FINISH, {"a_new_stall": "Check it in Settings.",
                                                "another_new_stall": "Check it in Settings."}):
            self.assertEqual(quiet_fallback_streak(("timeout", 2, False), "a_new_stall"), ("a_new_stall", 1, False))
            # Review TL4-5: and it counts on, as its own kind; another code without a kind
            # is another kind.
            self.assertEqual(quiet_fallback_streak(("a_new_stall", 1, False), "a_new_stall"), ("a_new_stall", 2, False))
            self.assertEqual(quiet_fallback_streak(("another_new_stall", 2, False), "a_new_stall"),
                             ("a_new_stall", 1, False))

    def test_every_stalling_code_is_quiet_per_take(self) -> None:
        # Review CL4-5: a stalling code that the Pill said on every take would be said
        # again by its escalation. Each one is quiet per take; the escalation is its line.
        from knight_flow.app import QUIET_LOCAL_FINISH, STALLING_LOCAL_FINISH

        self.assertLessEqual(set(STALLING_LOCAL_FINISH), set(QUIET_LOCAL_FINISH))

    def test_the_stalls_that_share_a_cause_count_together(self) -> None:
        # Review R-B4b (2026-10-10): a model too slow for the time budget times out on a
        # short take and overruns the budget on a long one. Same text, same fix: one count.
        # Alternating them used to reset the count every take, so it was never said.
        self.assertEqual(self.takes(["timeout", "budget_exceeded", "timeout", "budget_exceeded", "timeout"]),
                         [False, False, True, False, False])
        self.assertEqual(self.takes(["budget_exceeded", "budget_exceeded", "timeout"]), [False, False, True])

    def test_a_different_kind_of_stall_keeps_its_own_count(self) -> None:
        # A slow model and an empty reply are different faults with different fixes, so
        # neither carries the other's count (N18), and a kind starts unsaid even after
        # another kind's line was said (N19).
        self.assertEqual(self.takes(["timeout", "invalid_response"] * 3), [False] * 6)
        self.assertEqual(self.takes(["timeout"] * 3 + ["invalid_response"] * 3),
                         [False, False, True, False, False, True])
        self.assertEqual(self.takes(["timeout"] * 3 + ["budget_exceeded"] * 3), [False, False, True] + [False] * 3)

    def test_the_line_says_what_to_do(self) -> None:
        from knight_flow.app import quiet_fallback_escalation

        for code in ("timeout", "budget_exceeded", "invalid_response", "preparing"):
            state, title, detail = quiet_fallback_escalation(code)
            with self.subTest(code=code):
                self.assertEqual((state, title), ("error", self.TITLE))
                self.assertIn("Settings > Writing > Formatting", detail)


if __name__ == "__main__":
    unittest.main()
