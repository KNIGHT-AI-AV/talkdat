"""X-536: skipping the wizard must not silence update reminders forever.

Every `update reminder:` line in the founder's log -- across months and
thousands of dictations -- reads `show=False reason=onboarding`. His app has
never once offered him an update. `update_policy.should_remind` hard-blocks on
`onboarding_incomplete`, and the app fed that from `needs_onboarding()`, which
is `completed and version >= ONBOARDING_VERSION`. His config says
`completed: False, version: 0, resume_step_id: "voice"` -- he closed the wizard
at step two -- alongside `real_dictations: 3` and `finish_prompt_2_done: True`.

So the gate meant "the wizard flag was never flipped", when the thing it was
protecting is "this person is still setting up and a window would interrupt
them". Someone who has dictated for months is not setting up.

The second bite is wider than one machine: `ONBOARDING_VERSION` is 3, and the
check demands `version >= ONBOARDING_VERSION`. Every install that completed
onboarding under version 0, 1 or 2 silently stopped being reminded about
updates the day that constant was bumped, and nothing anywhere reported it.

This is why the failed install of X-535 mattered so much: with reminders muted,
the manual "check for updates" button is the ONLY way he ever updates, and that
is exactly the path that died without a word.
"""

from __future__ import annotations

import unittest

from knight_flow.onboarding import (
    ONBOARDING_VERSION,
    onboarding_blocks_update_reminders,
    onboarding_is_complete,
)


def config(**onboarding) -> dict:
    return {"onboarding": dict(onboarding)}


# The founder's real config, read off the machine on 2026-09-07.
FOUNDER = config(
    access_choice="account",
    completed=False,
    finish_prompt_2_done=True,
    real_dictations=3,
    resume_step=2,
    resume_step_id="voice",
    route="managed",
    version=0,
    writing_preset="smart",
)


class AbandonedOnboardingTests(unittest.TestCase):
    def test_the_founders_config_does_not_mute_updates(self) -> None:
        self.assertFalse(
            onboarding_blocks_update_reminders(FOUNDER),
            "months of dictation is not 'still setting up'",
        )

    def test_a_genuinely_new_install_is_still_protected(self) -> None:
        """The block exists for a real reason: a window during setup takes
        something away instead of offering it. That must still hold."""
        self.assertTrue(onboarding_blocks_update_reminders(config()))
        self.assertTrue(
            onboarding_blocks_update_reminders(config(completed=False, real_dictations=0))
        )
        self.assertTrue(onboarding_blocks_update_reminders({}))

    def test_someone_part_way_through_setup_is_still_protected(self) -> None:
        self.assertTrue(
            onboarding_blocks_update_reminders(
                config(completed=False, real_dictations=1, resume_step=1)
            )
        )

    def test_settling_in_lifts_the_block(self) -> None:
        """`finish_prompt_2_done` is the app's own mark for 'three real
        dictations happened'. Either signal is enough."""
        self.assertFalse(
            onboarding_blocks_update_reminders(config(real_dictations=3))
        )
        self.assertFalse(
            onboarding_blocks_update_reminders(config(finish_prompt_2_done=True))
        )

    def test_an_older_completed_onboarding_still_counts(self) -> None:
        """The install-base bug. Bumping ONBOARDING_VERSION must never mute
        update reminders for people who already finished an earlier one."""
        for version in range(0, ONBOARDING_VERSION):
            with self.subTest(version=version):
                stale = config(completed=True, version=version)
                self.assertFalse(
                    onboarding_is_complete(stale),
                    "precondition: this config reads as incomplete",
                )
                self.assertFalse(
                    onboarding_blocks_update_reminders(stale),
                    f"a v{version} graduate must still be told about updates",
                )

    def test_a_current_completed_onboarding_does_not_block(self) -> None:
        self.assertFalse(
            onboarding_blocks_update_reminders(
                config(completed=True, version=ONBOARDING_VERSION)
            )
        )

    def test_garbage_counts_fall_back_to_protecting_them(self) -> None:
        for value in (None, "", "lots", [], {}):
            with self.subTest(value=value):
                self.assertTrue(
                    onboarding_blocks_update_reminders(config(real_dictations=value))
                )

    def test_a_missing_or_broken_onboarding_block_does_not_crash(self) -> None:
        self.assertTrue(onboarding_blocks_update_reminders({"onboarding": None}))
        self.assertTrue(onboarding_blocks_update_reminders({}))


class TheAppUsesTheNarrowerGateTests(unittest.TestCase):
    """`needs_onboarding()` still decides whether to SHOW the wizard -- that
    must not change. Only the update-reminder gate gets the narrower question.
    """

    def test_the_reminder_state_no_longer_reads_needs_onboarding(self) -> None:
        import inspect

        from knight_flow import app as app_module

        source = inspect.getsource(app_module)
        marker = '"onboarding_incomplete":'
        line = next(
            ln for ln in source.splitlines() if marker in ln and "state" not in ln.lower()
        )
        self.assertIn("onboarding_blocks_update_reminders", line)
        self.assertNotIn("needs_onboarding", line)

    def test_needs_onboarding_still_means_show_the_wizard(self) -> None:
        self.assertTrue(onboarding_is_complete(config(completed=True, version=ONBOARDING_VERSION)))
        self.assertFalse(onboarding_is_complete(FOUNDER))


if __name__ == "__main__":
    unittest.main()
