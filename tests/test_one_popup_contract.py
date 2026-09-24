from __future__ import annotations

import unittest

from knight_flow.ui import flyout
from knight_flow.ui.flyout import Flyout


class HoverAndClickBothOpenItTests(unittest.TestCase):
    """His words: "must be both hover-activated and click-activated"."""

    def test_hover_opens_it_after_a_pause(self) -> None:
        f = Flyout()
        self.assertEqual(f.pointer_entered_trigger(), "schedule_open")
        self.assertFalse(f.open, "nothing opens before the delay elapses")
        self.assertEqual(f.open_timer_fired(), "open")
        self.assertTrue(f.open)

    def test_passing_over_a_trigger_opens_nothing(self) -> None:
        """The reason the delay exists at all.

        A pointer crossing the control on its way somewhere else must not leave
        a menu behind it. Without this, every trip across the window flashes
        whatever it passed.
        """

        f = Flyout()
        f.pointer_entered_trigger()
        self.assertEqual(f.pointer_left_trigger(), "cancel_open")
        self.assertEqual(f.open_timer_fired(), None, "a cancelled open must stay shut")
        self.assertFalse(f.open)

    def test_a_click_opens_it_now_with_no_delay(self) -> None:
        f = Flyout()
        self.assertEqual(f.clicked_trigger(), "open")
        self.assertTrue(f.open)
        self.assertTrue(f.pinned)

    def test_a_click_on_an_open_popup_pins_it_rather_than_fighting_you(self) -> None:
        """Hover opened it, you clicked it. That means keep it, not close it."""

        f = Flyout()
        f.pointer_entered_trigger()
        f.open_timer_fired()
        self.assertTrue(f.open)
        self.assertFalse(f.pinned)

        self.assertIsNone(f.clicked_trigger())
        self.assertTrue(f.open, "clicking what you can see must not dismiss it")
        self.assertTrue(f.pinned)

        # A second click on a pinned popup is a real toggle.
        self.assertEqual(f.clicked_trigger(), "close")
        self.assertFalse(f.open)


class ItVanishesWhenNotActiveTests(unittest.TestCase):
    """His words: "the menu does not disappear when inactive"."""

    def _hovered_open(self) -> Flyout:
        f = Flyout()
        f.pointer_entered_trigger()
        f.open_timer_fired()
        return f

    def test_leaving_it_closes_it(self) -> None:
        f = self._hovered_open()
        self.assertEqual(f.pointer_left_trigger(), "schedule_close")
        self.assertEqual(f.close_timer_fired(), "close")
        self.assertFalse(f.open)

    def test_the_diagonal_from_trigger_to_row_does_not_dismiss_it(self) -> None:
        """The single most common way a menu is made unusable.

        The pointer's path from a trigger to the item it wants leaves the
        trigger before it reaches the popup. A menu that closes the instant the
        trigger is left cannot be reached by a real hand.
        """

        f = self._hovered_open()
        self.assertEqual(f.pointer_left_trigger(), "schedule_close")
        self.assertEqual(f.pointer_entered_popup(), "cancel_close")
        self.assertEqual(
            f.close_timer_fired(),
            None,
            "a close scheduled before the pointer arrived must not fire after it",
        )
        self.assertTrue(f.open)

    def test_the_grace_period_is_longer_than_the_open_delay(self) -> None:
        """The asymmetry is the design, so state it as a fact and hold it."""

        self.assertGreater(flyout.CLOSE_GRACE_MS, flyout.OPEN_DELAY_MS)

    def test_a_click_elsewhere_closes_even_a_pinned_popup(self) -> None:
        f = Flyout()
        f.clicked_trigger()
        self.assertTrue(f.pinned)
        self.assertEqual(f.clicked_outside(), "close")
        self.assertFalse(f.open)
        self.assertFalse(f.pinned, "the next hover must behave like a fresh one")

    def test_escape_and_lost_focus_close_it_too(self) -> None:
        for name, act in (("escape", Flyout.escaped), ("focus", Flyout.focus_left)):
            with self.subTest(name):
                f = Flyout()
                f.clicked_trigger()
                self.assertEqual(act(f), "close")
                self.assertFalse(f.open)

    def test_a_pinned_popup_ignores_the_pointer_wandering_off(self) -> None:
        f = Flyout()
        f.clicked_trigger()
        f.pointer_entered_trigger()
        self.assertIsNone(f.pointer_left_trigger())
        self.assertIsNone(f.close_timer_fired())
        self.assertTrue(f.open, "a clicked menu stays until it is dismissed")


class ItKeepsWhatYouWereTypingTests(unittest.TestCase):
    """His words: "preserve the text the user was in the middle of typing in
    case they click away", and "reappear if the user has not yet pressed
    enter"."""

    def test_clicking_away_mid_word_does_not_destroy_it(self) -> None:
        f = Flyout()
        f.clicked_trigger()
        f.remember("search", "plasterpie")
        f.clicked_outside()

        f.clicked_trigger()
        self.assertEqual(
            f.restore("search"),
            "plasterpie",
            "half-typed work must survive a click away",
        )

    def test_pressing_enter_spends_the_draft(self) -> None:
        """A committed value has already been applied.

        Re-offering it on reopen looks like the app failed to take it, which is
        worse than starting clean.
        """

        f = Flyout()
        f.clicked_trigger()
        f.remember("search", "plasterpiece")
        f.commit("search")
        f.clicked_outside()

        f.clicked_trigger()
        self.assertEqual(f.restore("search"), "")

    def test_an_empty_uncommitted_field_is_not_worth_remembering(self) -> None:
        f = Flyout()
        f.remember("search", "")
        self.assertEqual(f.drafts, {})
        self.assertEqual(f.restore("search"), "")

    def test_drafts_are_per_field(self) -> None:
        f = Flyout()
        f.remember("search", "plaster")
        f.remember("sounds_like", "plasta")
        f.commit("search")
        self.assertEqual(f.restore("search"), "")
        self.assertEqual(f.restore("sounds_like"), "plasta")

    def test_a_field_never_typed_into_restores_empty(self) -> None:
        self.assertEqual(Flyout().restore("never-touched"), "")


class TheContractHoldsUnderRepetitionTests(unittest.TestCase):
    def test_a_full_hover_open_leave_close_cycle_returns_to_rest(self) -> None:
        f = Flyout()
        for _round in range(4):
            f.pointer_entered_trigger()
            f.open_timer_fired()
            self.assertTrue(f.open)
            f.pointer_left_trigger()
            f.close_timer_fired()
            self.assertFalse(f.open)

        self.assertEqual(
            (f.open, f.pinned, f.open_pending, f.close_pending,
             f.pointer_in_trigger, f.pointer_in_popup),
            (False, False, False, False, False, False),
            "no flag may survive a completed cycle, or the next open is wrong",
        )

    def test_a_stale_timer_after_a_reopen_cannot_close_the_new_popup(self) -> None:
        """The bug this shape of code always has.

        A close was scheduled, the person came back, and the old timer fires
        anyway. Checking the live pointer state at fire time rather than
        trusting the schedule is what makes that harmless.
        """

        f = Flyout()
        f.pointer_entered_trigger()
        f.open_timer_fired()
        f.pointer_left_trigger()
        f.pointer_entered_trigger()
        self.assertIsNone(f.close_timer_fired())
        self.assertTrue(f.open)


if __name__ == "__main__":
    unittest.main()
