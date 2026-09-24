from __future__ import annotations

import unittest

from knight_flow.update_policy import (
    DAY,
    HOUR,
    IDLE_SETTLE_SECONDS,
    MIN_SPACING,
    RETURN_IDLE_SECONDS,
    TRIGGER_IDLE,
    TRIGGER_QUIT,
    TRIGGER_RETURN,
    TRIGGER_START,
    ReminderDecision,
    next_snooze,
    should_remind,
)

NOW = 1_800_000_000


def state(**kwargs) -> dict:
    base = {
        "update_available": True,
        "trigger": TRIGGER_START,
        "latest_version": "0.5.0-beta",
        "first_seen_at": NOW,
        "last_reminded_at": 0,
    }
    base.update(kwargs)
    return base


class InterruptionTests(unittest.TestCase):
    """The reason this module exists.

    A modal window that takes focus while someone is speaking eats the words
    they were saying, and there is no undo. Every block below was reachable
    before: a silent check that found an update opened the window immediately,
    on a 24 hour timer that could not see the microphone.
    """

    def test_it_never_interrupts_an_active_dictation(self) -> None:
        decision = should_remind(state(session_active=True), now=NOW)
        self.assertFalse(decision.should_remind)
        self.assertEqual(decision.reason, "dictating")

    def test_it_never_interrupts_transcription_in_flight(self) -> None:
        decision = should_remind(state(session_processing=True), now=NOW)
        self.assertFalse(decision.should_remind)
        self.assertEqual(decision.reason, "processing")

    def test_it_does_not_stack_a_second_window_on_the_first(self) -> None:
        self.assertFalse(should_remind(state(update_window_open=True), now=NOW).should_remind)

    def test_it_waits_until_someone_has_finished_setting_up(self) -> None:
        self.assertFalse(should_remind(state(onboarding_incomplete=True), now=NOW).should_remind)

    def test_it_stays_quiet_while_a_screen_is_being_shared(self) -> None:
        """Presenting is when a popup is most embarrassing and least welcome."""
        self.assertFalse(should_remind(state(presenting=True), now=NOW).should_remind)

    def test_a_moment_that_is_not_a_seam_is_never_used(self) -> None:
        decision = should_remind(state(trigger="random_timer_tick"), now=NOW)
        self.assertFalse(decision.should_remind)
        self.assertEqual(decision.reason, "not_a_seam")


class SeamTests(unittest.TestCase):
    def test_launching_the_app_is_a_seam(self) -> None:
        self.assertTrue(should_remind(state(trigger=TRIGGER_START), now=NOW).should_remind)

    def test_a_finished_dictation_is_a_seam_once_it_has_settled(self) -> None:
        just_finished = state(trigger=TRIGGER_IDLE, seconds_since_session=5)
        self.assertFalse(should_remind(just_finished, now=NOW).should_remind,
                         "the next sentence may already be coming")

        settled = state(trigger=TRIGGER_IDLE, seconds_since_session=IDLE_SETTLE_SECONDS + 1)
        self.assertTrue(should_remind(settled, now=NOW).should_remind)

    def test_coming_back_counts_only_after_a_real_absence(self) -> None:
        pause = state(trigger=TRIGGER_RETURN, seconds_idle=60)
        self.assertFalse(should_remind(pause, now=NOW).should_remind, "thinking is not leaving")

        away = state(trigger=TRIGGER_RETURN, seconds_idle=RETURN_IDLE_SECONDS + 1)
        self.assertTrue(should_remind(away, now=NOW).should_remind)

    def test_quitting_is_always_offered(self) -> None:
        """Nothing is being interrupted, and it is where installs actually
        happen -- so it ignores the escalation ramp entirely."""
        recent = state(trigger=TRIGGER_QUIT, last_reminded_at=NOW - MIN_SPACING - 1)
        decision = should_remind(recent, now=NOW)
        self.assertTrue(decision.should_remind)
        self.assertEqual(decision.reason, "quit")
        self.assertFalse(decision.intrusive)


class RespectingTheAnswerTests(unittest.TestCase):
    def test_a_skipped_version_is_never_mentioned_again(self) -> None:
        skipped = state(latest_version="0.5.0-beta", skip_version="0.5.0-beta")
        self.assertFalse(should_remind(skipped, now=NOW).should_remind)

    def test_skipping_one_version_does_not_silence_the_next(self) -> None:
        later = state(latest_version="0.6.0-beta", skip_version="0.5.0-beta")
        self.assertTrue(should_remind(later, now=NOW).should_remind)

    def test_a_snooze_is_honoured_until_it_expires(self) -> None:
        self.assertFalse(should_remind(state(snooze_until=NOW + HOUR), now=NOW).should_remind)
        self.assertTrue(should_remind(state(snooze_until=NOW - 1), now=NOW).should_remind)

    def test_reminders_are_spaced_even_across_different_seams(self) -> None:
        """Several short dictations in a row are several seams. Without a floor
        each one would be its own reminder."""
        recent = state(trigger=TRIGGER_IDLE, seconds_since_session=999,
                       last_reminded_at=NOW - 60)
        self.assertFalse(should_remind(recent, now=NOW).should_remind)

    def test_snoozing_repeatedly_backs_off_but_never_gives_up(self) -> None:
        gaps = [next_snooze(NOW, times_snoozed=n) - NOW for n in range(0, 8)]
        self.assertEqual(gaps[0], HOUR)
        for earlier, later in zip(gaps, gaps[1:]):
            self.assertLessEqual(earlier, later, "each 'not now' should buy more quiet")
        self.assertEqual(max(gaps), 24 * HOUR, "but it must always come back")


class EscalationTests(unittest.TestCase):
    """A week-old security fix and a day-old typo fix do not deserve the same
    patience, so the gap between reminders shrinks as the update ages."""

    def test_a_fresh_update_is_mentioned_sparingly(self) -> None:
        fresh = state(first_seen_at=NOW - HOUR, last_reminded_at=NOW - DAY)
        self.assertFalse(should_remind(fresh, now=NOW).should_remind,
                         "one day is inside the initial three-day gap")

    def test_an_ignored_update_becomes_a_daily_mention(self) -> None:
        aging = state(first_seen_at=NOW - 5 * DAY, last_reminded_at=NOW - DAY - 1)
        self.assertTrue(should_remind(aging, now=NOW).should_remind)

    def test_a_fortnight_old_update_earns_a_window_that_takes_focus(self) -> None:
        stale = state(first_seen_at=NOW - 15 * DAY, last_reminded_at=NOW - DAY)
        decision = should_remind(stale, now=NOW)
        self.assertTrue(decision.should_remind)
        self.assertTrue(decision.intrusive)

    def test_a_fresh_update_never_takes_focus(self) -> None:
        decision = should_remind(state(first_seen_at=NOW - HOUR), now=NOW)
        self.assertTrue(decision.should_remind)
        self.assertFalse(decision.intrusive, "a badge and a toast are enough")

    def test_a_security_update_skips_the_gentle_end_of_the_ramp(self) -> None:
        secure = state(security_update=True, first_seen_at=NOW - HOUR,
                       last_reminded_at=NOW - 5 * HOUR)
        decision = should_remind(secure, now=NOW)
        self.assertTrue(decision.should_remind)
        self.assertTrue(decision.intrusive)

    def test_even_a_security_update_will_not_interrupt_speech(self) -> None:
        """Urgency changes the cadence, never the hard blocks."""
        secure = state(security_update=True, session_active=True)
        self.assertFalse(should_remind(secure, now=NOW).should_remind)


class ShapeTests(unittest.TestCase):
    def test_no_update_means_nothing_to_say(self) -> None:
        self.assertFalse(should_remind(state(update_available=False), now=NOW).should_remind)

    def test_the_decision_is_frozen(self) -> None:
        decision = should_remind(state(), now=NOW)
        self.assertIsInstance(decision, ReminderDecision)
        with self.assertRaises(Exception):
            decision.should_remind = False  # type: ignore[misc]

    def test_it_does_not_mutate_the_state_it_is_given(self) -> None:
        original = state()
        snapshot = dict(original)
        should_remind(original, now=NOW)
        self.assertEqual(original, snapshot, "persistence is the caller's job")


if __name__ == "__main__":
    unittest.main()
