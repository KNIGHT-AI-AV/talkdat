"""X-740: the message model, with no window (knight_flow/island.py).

The owner's rule for every message: the host part ITSELF changes shape in its
own material ("they don't come out flush, they look like a separate piece" was
rejected). On the desktop the host is the Pill. These tests pin the parts of
that which need no display: the springs of the message spec's section 9.1, the
reading times of section 10, where the Pill stretches (section 3: the pinned
end, the side it rises from, the flips at a screen edge and around a caret),
and the queue table of section 11 together with the two safety-lane rules it
must keep (an info never replaces an unread error, X-629; a word notice never
replaces another, X-631).
"""
from __future__ import annotations

import unittest

from knight_flow import island
from knight_flow.island import (
    Context,
    FlagAction,
    MessageQueue,
    PillMotion,
    Rect,
    Shape,
    hold_ms,
    message_from,
    pill_frame,
    say_tone,
    settle_ms,
    spring,
)
from knight_flow.pill_motion import error_toast_hold_ms

WORK = Rect(0, 0, 1920, 1040)


def peak(response: float, damping: float) -> float:
    return max(spring(i / 2000.0, response, damping) for i in range(1, 4000))


class TheSpringsAreTheSpecsTests(unittest.TestCase):
    """Section 9.1: 98% at, settled (0.1%) at, and overshoot, per motion."""

    TABLE = (
        ("Pill lengthens", island.GROW_LENGTH, 227, 496, 1.0),
        ("Pill rises", island.GROW_HEIGHT, 279, 441, 0.0),
        ("art compresses", island.COMPRESS, 241, 382, 0.0),
        ("Pill contracts", island.CONTRACT, 241, 382, 0.0),
        ("replace", island.REPLACE, 279, 441, 0.0),
        ("dictation pre-empts", island.PREEMPT, 167, 265, 0.0),
    )

    def test_each_spring_reaches_and_settles_when_the_spec_says(self) -> None:
        for name, (response, damping), at_98, settled, overshoot in self.TABLE:
            with self.subTest(motion=name):
                self.assertAlmostEqual(settle_ms(response, damping, 0.02), at_98, delta=3)
                self.assertAlmostEqual(settle_ms(response, damping, 0.001), settled, delta=3)
                self.assertAlmostEqual((peak(response, damping) - 1.0) * 100.0, overshoot, delta=0.1)

    def test_the_formula_starts_at_rest_and_ends_at_the_target(self) -> None:
        self.assertEqual(spring(0.0, 0.36, 0.825), 0.0)
        self.assertAlmostEqual(spring(3.0, 0.36, 0.825), 1.0, places=6)
        self.assertAlmostEqual(spring(3.0, 0.26, 1.0), 1.0, places=6)


class ReadingTimesTests(unittest.TestCase):
    def test_info_and_done_read_at_240_ms_a_word_between_1_8_and_4_5_s(self) -> None:
        self.assertEqual(hold_ms("info", "Copied"), 1800)
        self.assertEqual(hold_ms("done", "one two three four five six seven"), 900 + 240 * 7)
        self.assertEqual(hold_ms("info", " ".join(["word"] * 40)), 4500)

    def test_warn_errors_busy_and_segments(self) -> None:
        self.assertEqual(hold_ms("warn", "Short"), 3000)
        self.assertEqual(hold_ms("warn", " ".join(["w"] * 40)), 6000)
        title, detail = "The microphone did not start.", "Check your microphone, or open Mic Doctor."
        self.assertEqual(hold_ms("error", title, detail), error_toast_hold_ms(title, detail))
        self.assertIsNone(hold_ms("busy", "Installing 1.2.4"))
        self.assertEqual(hold_ms("info", "Added", segment="word"), 6000)
        self.assertEqual(hold_ms("info", "Ready", segment="update"), 20000)

    def test_leaving_a_hovered_message_restarts_it_at_half_never_under_1_2_s(self) -> None:
        self.assertEqual(island.resumed_hold_ms(8000), 4000)
        self.assertEqual(island.resumed_hold_ms(1800), 1200)


class SayToneTests(unittest.TestCase):
    def test_none_keeps_todays_behaviour_only_errors_speak(self) -> None:
        self.assertEqual(say_tone("error", None), "error")
        self.assertIsNone(say_tone("captured", None))

    def test_true_speaks_with_the_states_tone_and_a_name_overrides_it(self) -> None:
        self.assertEqual(say_tone("captured", True), "done")
        self.assertEqual(say_tone("idle", True), "info")
        self.assertEqual(say_tone("processing", True), "busy")
        self.assertEqual(say_tone("captured", "warn"), "warn")
        self.assertIsNone(say_tone("error", False))
        self.assertIsNone(say_tone("listening", True))


def bottom_centre() -> Rect:
    return Rect(912, 1040 - 24 - 18, 96, 18)


class WhereThePillStretchesTests(unittest.TestCase):
    """Section 3.1, all four positions and the corners."""

    def test_a_centred_bottom_pill_pins_its_left_end_and_rises(self) -> None:
        pill = bottom_centre()
        placement = pill_frame(pill, WORK, (300, 36))
        self.assertEqual((placement.home, placement.pin, placement.vgrow), ("bottom", "left", "up"))
        self.assertEqual(placement.rect.x, pill.x, "the left end moved")
        self.assertEqual(placement.rect.bottom, pill.bottom, "it did not rise away from the bottom edge")
        self.assertEqual((placement.rect.w, placement.rect.h), (300, 36))

    def test_a_top_pill_grows_down(self) -> None:
        pill = Rect(912, 24, 96, 18)
        placement = pill_frame(pill, WORK, (300, 36))
        self.assertEqual((placement.home, placement.vgrow), ("top", "down"))
        self.assertEqual(placement.rect.y, pill.y)

    def test_a_pill_in_the_bottom_right_corner_pins_its_right_end(self) -> None:
        pill = Rect(1920 - 24 - 96, 998, 96, 18)
        placement = pill_frame(pill, WORK, (300, 36))
        self.assertEqual(placement.pin, "right")
        self.assertEqual(placement.rect.right, pill.right)
        self.assertEqual(placement.rect.bottom, pill.bottom)

    def test_a_pill_in_the_bottom_left_corner_pins_its_left_end(self) -> None:
        pill = Rect(24, 998, 96, 18)
        placement = pill_frame(pill, WORK, (300, 36))
        self.assertEqual((placement.pin, placement.rect.x), ("left", 24))

    def test_a_pill_against_a_side_rises_about_its_centre_and_pins_that_side(self) -> None:
        for side, x in (("left", 0), ("right", 1920 - 96)):
            with self.subTest(side=side):
                pill = Rect(x, 500, 96, 18)
                placement = pill_frame(pill, WORK, (300, 54))
                self.assertEqual((placement.home, placement.pin, placement.vgrow), (side, side, "center"))
                self.assertAlmostEqual(placement.rect.cy, pill.cy, delta=0.5)

    def test_the_end_nearer_a_side_stays_even_when_either_would_fit(self) -> None:
        pill = Rect(1400, 998, 96, 18)  # the right gap is the smaller one
        for width in (300, 700):  # 300 fits either way: only the rule decides
            with self.subTest(width=width):
                placement = pill_frame(pill, WORK, (width, 36))
                self.assertEqual(placement.pin, "right")
                self.assertEqual(placement.rect.right, pill.right)

    def test_a_pill_inside_the_margin_still_keeps_the_capsule_on_screen(self) -> None:
        pill = Rect(4, 998, 96, 18)
        placement = pill_frame(pill, WORK, (300, 36), compact_size=(240, 36))
        self.assertGreaterEqual(placement.rect.x, 12)
        self.assertLessEqual(placement.rect.right, WORK.right - 12)

    def test_neither_side_fits_the_compact_form(self) -> None:
        narrow = Rect(0, 0, 500, 400)
        pill = Rect(202, 358, 96, 18)
        placement = pill_frame(pill, narrow, (460, 54), compact_size=(280, 36))
        self.assertTrue(placement.compact)
        self.assertEqual((placement.rect.w, placement.rect.h), (280, 36))

    def test_a_known_caret_flips_the_pinned_end(self) -> None:
        pill = bottom_centre()
        caret = Rect(1150, 990, 2, 18)  # to the right of the Pill, where it would stretch
        placement = pill_frame(pill, WORK, (300, 36), caret=caret)
        self.assertEqual(placement.pin, "right")
        self.assertFalse(placement.rect.inflate(24).intersects(caret))

    def test_a_caret_everywhere_still_gets_the_message_in_compact_form(self) -> None:
        pill = bottom_centre()
        caret = Rect(0, 900, 1920, 140)
        placement = pill_frame(pill, WORK, (300, 36), caret=caret, compact_size=(200, 36))
        self.assertTrue(placement.compact, "a message must never be lost")

    def test_the_envelope_holds_the_pill_the_capsule_and_its_overshoot(self) -> None:
        pill = bottom_centre()
        placement = pill_frame(pill, WORK, (300, 36))
        box = island.envelope(pill, placement)
        self.assertTrue(box.x <= pill.x and box.right >= placement.rect.right + 6)
        self.assertEqual(box.bottom, pill.bottom)
        self.assertEqual(box.y, placement.rect.y)


class TheMotionStartsFromWhatIsOnScreenTests(unittest.TestCase):
    REST = island.rest_shape(96, 18)
    TARGET = Shape(w=320, h=36, head=44, feather=18)

    def test_frame_zero_is_the_pill_and_it_settles_on_the_capsule(self) -> None:
        motion = PillMotion(self.REST, 0.0)
        motion.grow(self.TARGET, 0.0)
        first = motion.sample(0.0)
        self.assertEqual((first.w, first.h, first.head, first.feather, first.text), (96, 18, 96, 0, 0))
        self.assertFalse(motion.settled(300.0))
        self.assertTrue(motion.settled(520.0))
        last = motion.sample(520.0)
        self.assertAlmostEqual(last.w, 320, delta=0.5)
        self.assertAlmostEqual(last.h, 36, delta=0.1)
        self.assertAlmostEqual(last.head, 44, delta=0.1)

    def test_the_length_settles_past_its_target_by_at_most_one_percent(self) -> None:
        motion = PillMotion(self.REST, 0.0)
        motion.grow(self.TARGET, 0.0)
        widest = max(motion.sample(float(t)).w for t in range(0, 600, 4))
        self.assertGreater(widest, 320)
        self.assertLessEqual(widest - 320, (320 - 96) * 0.0105)

    def test_the_words_arrive_after_the_cap_lands_and_the_tone_before(self) -> None:
        motion = PillMotion(self.REST, 0.0)
        motion.grow(self.TARGET, 0.0)
        self.assertEqual(motion.sample(170.0).text, 0.0)
        self.assertEqual(motion.sample(85.0).tone, 0.0)
        self.assertGreater(motion.sample(200.0).tone, 0.5)
        self.assertEqual(motion.sample(345.0).text, 1.0)

    def test_an_interruption_continues_from_the_presented_value(self) -> None:
        motion = PillMotion(self.REST, 0.0)
        motion.grow(self.TARGET, 0.0)
        before = motion.sample(150.0)
        motion.contract(150.0)
        after = motion.sample(150.0)
        self.assertAlmostEqual(before.w, after.w, delta=0.01)
        self.assertAlmostEqual(before.h, after.h, delta=0.01)
        self.assertTrue(motion.settled(150.0 + 60.0 + 390.0))
        rest = motion.sample(700.0)
        self.assertAlmostEqual(rest.w, 96, delta=0.2)
        self.assertEqual(rest.text, 0.0)

    def test_the_contraction_takes_the_words_first(self) -> None:
        motion = PillMotion(self.REST, 0.0)
        motion.grow(self.TARGET, 0.0)
        motion.contract(1000.0)
        self.assertAlmostEqual(motion.sample(1055.0).w, motion.sample(1000.0).w, delta=0.01,
                               msg="the springs start 60 ms after the words begin to leave")
        self.assertEqual(motion.sample(1091.0).text, 0.0)

    def test_reduced_motion_fades_at_full_size(self) -> None:
        motion = PillMotion(self.REST, 0.0, reduced=True)
        motion.grow(self.TARGET, 0.0)
        first = motion.sample(0.0)
        self.assertEqual((first.w, first.h, first.mix), (320, 36, 0.0))
        self.assertAlmostEqual(motion.sample(60.0).mix, 0.5, delta=0.01)
        self.assertEqual(motion.sample(120.0).mix, 1.0)
        motion.nudge(200.0)
        self.assertEqual(motion.sample(250.0).pulse, 1.0, "reduced motion: no nudge")
        motion.contract(500.0)
        self.assertEqual(motion.sample(560.0).w, 320, "nothing travels")
        self.assertEqual(motion.sample(620.0).mix, 0.0)

    def test_a_repeat_nudges_to_1_03_and_back(self) -> None:
        motion = PillMotion(self.REST, 0.0)
        motion.grow(self.TARGET, 0.0)
        motion.nudge(1000.0)
        self.assertAlmostEqual(motion.sample(1110.0).pulse, 1.03, delta=0.001)
        self.assertEqual(motion.sample(1300.0).pulse, 1.0)


def msg(title: str, tone: str = "info", **kwargs) -> island.Message:
    return message_from(title, tone=tone, **kwargs)


def undo() -> tuple[FlagAction, ...]:
    return (FlagAction("Undo", lambda: None, "<Alt-d>"),)


class TheQueueTableTests(unittest.TestCase):
    def test_one_message_at_a_time_equal_or_higher_replaces(self) -> None:
        queue = MessageQueue()
        self.assertEqual(queue.offer(msg("Copied"), 0.0).kind, "show")
        self.assertEqual(queue.offer(msg("No speech heard", "error"), 100.0).kind, "replace")
        self.assertEqual(queue.showing.title, "No speech heard")

    def test_an_info_never_replaces_an_unread_error(self) -> None:
        """X-629 (interaction grid d10)."""
        queue = MessageQueue()
        queue.offer(msg("No sound is reaching the microphone.", "error"), 0.0)
        decision = queue.offer(msg("Talk DAT! is up to date"), 100.0)
        self.assertEqual(decision.kind, "queue")
        self.assertEqual(queue.showing.tone, "error")
        queue.finished()
        self.assertEqual(queue.next(1000.0).message.title, "Talk DAT! is up to date")

    def test_the_same_key_updates_in_place(self) -> None:
        queue = MessageQueue()
        queue.offer(msg("Installing 1.2.4", "warn", key="update", progress=0.1), 0.0)
        decision = queue.offer(msg("Installing 1.2.4", "warn", key="update", progress=0.6), 50.0)
        self.assertEqual(decision.kind, "update")
        self.assertEqual(queue.showing.progress, 0.6)

    def test_a_word_notice_waits_for_the_one_showing_and_keeps_its_undo(self) -> None:
        """X-631: the first keeps its Undo; the second comes after."""
        queue = MessageQueue()
        queue.offer(msg('Added "Alpha"', actions=undo(), key="word", origin="person"), 0.0)
        decision = queue.offer(msg('Added "Beta"', actions=undo(), key="word", origin="person"), 50.0)
        self.assertEqual(decision.kind, "queue")
        self.assertEqual(queue.showing.title, 'Added "Alpha"')

    def test_an_error_replaces_a_segment_which_comes_back(self) -> None:
        queue = MessageQueue()
        word = msg('Added "Alpha"', actions=undo(), key="word")
        queue.offer(word, 0.0)
        decision = queue.offer(msg("The microphone did not start.", "error"), 100.0)
        self.assertEqual(decision.kind, "replace")
        self.assertIs(decision.requeued, word)
        self.assertTrue(queue.requeue(word, 4000))
        queue.finished()
        again = queue.next(5000.0)
        self.assertIs(again.message, word)
        self.assertEqual(word.reading_ms(), 4000)

    def test_a_warn_does_not_replace_a_segment(self) -> None:
        queue = MessageQueue()
        queue.offer(msg("Update ready", actions=undo(), key="update"), 0.0)
        self.assertEqual(queue.offer(msg("Using this PC for now", "warn"), 10.0).kind, "queue")

    def test_at_most_three_wait_and_the_oldest_info_drops_first(self) -> None:
        queue = MessageQueue()
        queue.offer(msg("An error", "error"), 0.0)
        for index, tone in enumerate(("info", "done", "info")):
            queue.offer(msg(f"note {index}", tone), 10.0 + index)
        queue.offer(msg("Using this PC for now", "warn"), 20.0)
        titles = [item.title for item in queue.waiting]
        self.assertEqual(len(titles), 3)
        self.assertNotIn("note 0", titles)
        self.assertEqual(titles[0], "Using this PC for now", "the higher priority waits first")

    def test_errors_and_actions_never_drop(self) -> None:
        queue = MessageQueue()
        live = Context(live=True)
        for index in range(5):
            queue.offer(msg(f"Error {index}", "error"), 10.0 + index, live)
        queue.offer(msg("Added", actions=undo(), key="word"), 20.0, live)
        self.assertEqual(len(queue.waiting), 6, "an error or an action was dropped")
        self.assertEqual(queue.offer(msg("An info"), 30.0, live).kind, "drop")

    def test_an_error_replaces_an_error(self) -> None:
        queue = MessageQueue()
        queue.offer(msg("First error", "error"), 0.0)
        self.assertEqual(queue.offer(msg("Second error", "error"), 10.0).kind, "replace")

    def test_the_same_words_within_10_s_are_a_nudge_or_nothing(self) -> None:
        queue = MessageQueue()
        queue.offer(msg("Copied"), 0.0)
        self.assertEqual(queue.offer(msg("Copied"), 2000.0).kind, "nudge")
        queue.finished()
        self.assertEqual(queue.offer(msg("Copied"), 5000.0).kind, "drop")
        self.assertEqual(queue.offer(msg("Copied"), 12_500.0).kind, "show")

    def test_one_entrance_per_700_ms(self) -> None:
        queue = MessageQueue()
        queue.offer(msg("First"), 0.0)
        queue.finished()
        decision = queue.offer(msg("Second"), 300.0)
        self.assertEqual((decision.kind, decision.due_ms), ("queue", 700.0))
        self.assertEqual(queue.next(400.0).kind, "wait")
        self.assertEqual(queue.next(700.0).message.title, "Second")

    def test_messages_nobody_caused_are_capped_at_six_a_minute(self) -> None:
        queue = MessageQueue()
        shown = 0
        for index in range(9):
            decision = queue.offer(msg(f"background {index}", origin="system"), index * 1000.0)
            if decision.kind == "show":
                shown += 1
            queue.finished()
        self.assertEqual(shown, 6)
        self.assertEqual(queue.offer(msg("An error", "error"), 9500.0).kind, "show", "errors are exempt")
        queue.finished()
        self.assertEqual(queue.offer(msg("You pressed this", origin="person"), 11_000.0).kind, "show")

    def test_nothing_stretches_while_the_pill_is_live(self) -> None:
        queue = MessageQueue()
        live = Context(live=True)
        self.assertEqual(queue.offer(msg("An error", "error"), 0.0, live).kind, "queue")
        self.assertEqual(queue.next(1000.0, live).kind, "drop")
        self.assertEqual(queue.next(1000.0).message.title, "An error")

    def test_during_a_meeting_only_errors_and_the_persons_own_segments(self) -> None:
        queue = MessageQueue()
        meeting = Context(meeting=True)
        self.assertEqual(queue.offer(msg("Copied", "done"), 0.0, meeting).kind, "recent")
        self.assertEqual(queue.offer(msg("Added", actions=undo(), origin="system"), 1.0, meeting).kind, "recent")
        self.assertEqual(queue.offer(msg("Added", actions=undo(), origin="person"), 2.0, meeting).kind, "show")
        self.assertIn("Copied", [entry["title"] for entry in queue.recent_messages()])

    def test_a_withdrawn_pill_keeps_errors_for_60_s(self) -> None:
        queue = MessageQueue()
        hidden = Context(withdrawn=True)
        self.assertEqual(queue.offer(msg("Copied", "done"), 0.0, hidden).kind, "recent")
        self.assertEqual(queue.offer(msg("An error", "error"), 0.0, hidden).kind, "held")
        self.assertEqual(queue.next(30_000.0).message.title, "An error")
        queue.finished()
        queue.offer(msg("Old error", "error"), 40_000.0, hidden)
        self.assertEqual(queue.next(101_000.0).kind, "drop", "a 61 s old error still showed")

    def test_busy_waits_700_ms_and_its_result_cancels_it(self) -> None:
        queue = MessageQueue()
        decision = queue.offer(msg("Recovering captured audio", "busy", key="state"), 0.0)
        self.assertEqual((decision.kind, decision.due_ms), ("wait", 700.0))
        queue.offer(msg("Recovered captured audio", "done", key="state"), 300.0)
        self.assertEqual(queue.busy_due("state", 700.0).kind, "drop")
        queue.finished()
        slow = queue.offer(msg("Installing 1.2.4", "busy", key="install"), 5000.0)
        self.assertEqual(queue.busy_due("install", slow.due_ms).kind, "show")

    def test_the_recent_list_keeps_twenty(self) -> None:
        queue = MessageQueue()
        for index in range(25):
            queue.offer(msg(f"message {index}", origin="person"), index * 800.0)
            queue.finished()
        recent = queue.recent_messages()
        self.assertEqual(len(recent), 20)
        self.assertEqual(recent[-1]["title"], "message 24")

    def test_a_dictation_requeues_errors_and_segments_and_drops_an_info(self) -> None:
        queue = MessageQueue()
        info = msg("Copied")
        queue.offer(info, 0.0)
        self.assertFalse(queue.requeue(info, 1000))
        error = msg("An error", "error")
        queue.offer(error, 1000.0)
        self.assertTrue(queue.requeue(error, 3000))
        self.assertFalse(queue.requeue(msg("Spent", "error"), 0))

    def test_message_from_keeps_tone_and_origin_to_their_names(self) -> None:
        made = message_from("  Two   spaces ", tone="LOUD", origin="nobody")
        self.assertEqual((made.title, made.tone, made.origin), ("Two spaces", "info", "system"))


if __name__ == "__main__":
    unittest.main()
