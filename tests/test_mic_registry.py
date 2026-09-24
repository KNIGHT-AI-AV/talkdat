"""X-175: the microphone registry, and the false claim it exists to retire.

The 0.4.104 UI/UX audit found that Panic Stop and the diagnostics pane both treat
the dictation session as the only microphone owner. Both were read in the source
and both are exactly as reported:

    def panic_stop(self) -> None:
        log.info("panic stop requested")
        self.cancel()

    "Mic/Deepgram are active only when session_active is true."

Live captions, the Settings level meter, Mic Doctor, Race, pronunciation
practice, Translation's Speak and onboarding's rehearsal all open the microphone
outside that session. So Panic silences one of them and the pane tells a person
the microphone is idle while it is not.

These tests pin the registry's behaviour, and they concentrate on the properties
that make a privacy claim TRUSTWORTHY rather than merely present. A registry that
under-reports is worse than no registry, because a person who is told "not in
use" stops looking.
"""

from __future__ import annotations

import threading
import unittest

from knight_flow.mic_registry import (
    CAPTIONS,
    DEFERRED_MICROPHONE_RELEASE,
    DICTATION,
    MIC_DOCTOR,
    SETTINGS_METER,
    MicrophoneRegistry,
    microphone_registry,
)


class TheRegistryTracksEveryOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = MicrophoneRegistry()

    def test_nothing_is_active_to_begin_with(self) -> None:
        self.assertFalse(self.registry.is_active())
        self.assertEqual(self.registry.owners(), ())

    def test_several_surfaces_can_hold_the_microphone_at_once(self) -> None:
        """The whole premise: more than one owner is a normal state, not an error."""
        self.registry.acquire(DICTATION)
        self.registry.acquire(CAPTIONS)
        self.registry.acquire(SETTINGS_METER)
        self.assertTrue(self.registry.is_active())
        self.assertEqual(set(self.registry.names()), {DICTATION, CAPTIONS, SETTINGS_METER})

    def test_releasing_one_owner_leaves_the_others_alone(self) -> None:
        first = self.registry.acquire(DICTATION)
        self.registry.acquire(CAPTIONS)
        self.assertTrue(self.registry.release(first))
        self.assertEqual(self.registry.names(), (CAPTIONS,))
        self.assertTrue(self.registry.is_active())

    def test_release_is_idempotent(self) -> None:
        token = self.registry.acquire(MIC_DOCTOR)
        self.assertTrue(self.registry.release(token))
        self.assertFalse(self.registry.release(token))
        self.assertFalse(self.registry.is_active())

    def test_releasing_none_is_harmless(self) -> None:
        """Teardown paths call this with whatever they have, including nothing."""
        self.assertFalse(self.registry.release(None))

    def test_the_phase_can_be_updated_and_is_reported(self) -> None:
        token = self.registry.acquire(DICTATION, phase="starting")
        self.registry.set_phase(token, "listening")
        self.assertEqual(self.registry.owners()[0].phase, "listening")

    def test_setting_the_phase_of_an_unknown_token_does_not_resurrect_it(self) -> None:
        token = self.registry.acquire(DICTATION)
        self.registry.release(token)
        self.registry.set_phase(token, "listening")
        self.assertFalse(self.registry.is_active(), "a stale phase update revived a dead owner")


class TokensAreNeverReusedTests(unittest.TestCase):
    """The subtle one, and the reason this is not a set of booleans.

    A page that is torn down late calls release() with the token it captured. If
    tokens were recycled, that late call would free whichever owner had since
    inherited the number, and the registry would report a live microphone as
    closed. That is the exact bug this module exists to prevent, so the module
    must not contain it.
    """

    def setUp(self) -> None:
        self.registry = MicrophoneRegistry()

    def test_a_new_owner_never_gets_a_retired_token(self) -> None:
        seen = set()
        for _ in range(50):
            token = self.registry.acquire(DICTATION)
            self.assertNotIn(token, seen, "a token was handed out twice")
            seen.add(token)
            self.registry.release(token)

    def test_a_late_release_cannot_free_somebody_else(self) -> None:
        stale = self.registry.acquire(CAPTIONS)
        self.registry.release(stale)
        live = self.registry.acquire(DICTATION)

        self.registry.release(stale)  # the torn-down page, arriving late

        self.assertTrue(
            self.registry.is_active(),
            "a stale release closed a different owner's microphone claim",
        )
        self.assertEqual(self.registry.names(), (DICTATION,))
        self.registry.release(live)


class PanicStopsEveryOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = MicrophoneRegistry()

    def test_every_owner_stopper_runs(self) -> None:
        stopped: list[str] = []
        for name in (DICTATION, CAPTIONS, MIC_DOCTOR):
            self.registry.acquire(name, stop=lambda name=name: stopped.append(name))
        remaining = self.registry.stop_all()
        self.assertEqual(set(stopped), {DICTATION, CAPTIONS, MIC_DOCTOR})
        self.assertEqual(remaining, ())
        self.assertFalse(self.registry.is_active())

    def test_one_broken_stopper_stays_disclosed_without_blocking_the_others(self) -> None:
        """A raising surface remains visible, but cannot abort the panic sweep."""
        stopped: list[str] = []

        def explode() -> None:
            raise RuntimeError("this surface is broken")

        self.registry.acquire(CAPTIONS, stop=explode)
        self.registry.acquire(DICTATION, stop=lambda: stopped.append(DICTATION))

        remaining = self.registry.stop_all()

        self.assertEqual(stopped, [DICTATION], "a raising stopper aborted the panic sweep")
        self.assertEqual(remaining, (CAPTIONS,))
        self.assertTrue(self.registry.is_active())
        self.assertEqual(self.registry.owners()[0].phase, "stop-failed")

    def test_a_stopper_that_forgets_to_release_is_still_cleared(self) -> None:
        """Otherwise the pane shows a phantom owner forever and people learn to
        ignore the indicator, which is the failure mode this whole module is
        about."""
        self.registry.acquire(CAPTIONS, stop=lambda: None)
        self.assertEqual(self.registry.stop_all(), ())
        self.assertFalse(self.registry.is_active())

    def test_an_async_stopper_keeps_its_claim_until_the_driver_releases(self) -> None:
        token = self.registry.acquire(
            MIC_DOCTOR,
            phase="metering",
            stop=lambda: DEFERRED_MICROPHONE_RELEASE,
        )

        remaining = self.registry.stop_all()

        self.assertEqual(remaining, (MIC_DOCTOR,))
        self.assertTrue(self.registry.is_active())
        self.registry.set_phase(token, "closing")
        self.assertEqual(self.registry.owners()[0].phase, "closing")
        self.registry.release(token)
        self.assertFalse(self.registry.is_active())

    def test_an_owner_with_no_stopper_remains_disclosed_as_failed(self) -> None:
        """Being unstoppable centrally is bad; being invisible is worse."""
        self.registry.acquire("mystery-surface")
        self.assertEqual(self.registry.names(), ("mystery-surface",))
        self.assertEqual(self.registry.stop_all(), ("mystery-surface",))
        self.assertEqual(self.registry.owners()[0].phase, "stop-failed")

    def test_a_stopper_may_call_release_without_deadlocking(self) -> None:
        """The realistic case: every well-behaved surface releases inside its stop.

        stop_all holds the registry lock to snapshot and must drop it before
        calling out, or the panic path deadlocks against its own owners. A
        deadlocked panic button is worse than no panic button, so this runs on a
        timer rather than trusting it.
        """
        token = self.registry.acquire(DICTATION)
        self.registry._stoppers[token] = lambda: self.registry.release(token)

        finished = threading.Event()

        def run() -> None:
            self.registry.stop_all()
            finished.set()

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        self.assertTrue(finished.wait(timeout=5), "stop_all deadlocked against a releasing stopper")
        self.assertFalse(self.registry.is_active())


class TheDisclosureIsHonestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = MicrophoneRegistry()

    def test_idle_says_so_plainly(self) -> None:
        lines = self.registry.describe()
        self.assertEqual(len(lines), 1)
        self.assertIn("none active", lines[0])
        self.assertIn("Registered auxiliary", lines[0])

    def test_in_use_names_every_surface_and_never_undercounts(self) -> None:
        self.registry.acquire(CAPTIONS, device="Blue Yeti", phase="listening")
        self.registry.acquire(SETTINGS_METER, phase="metering")
        text = "\n".join(self.registry.describe())
        self.assertIn("Registered auxiliary", text)
        self.assertIn("2 active", text)
        self.assertIn(CAPTIONS, text)
        self.assertIn(SETTINGS_METER, text)
        self.assertIn("Blue Yeti", text)

    def test_a_surface_without_a_named_device_still_appears(self) -> None:
        """An unknown device must never be a reason to omit an owner."""
        self.registry.acquire(MIC_DOCTOR)
        text = "\n".join(self.registry.describe())
        self.assertIn(MIC_DOCTOR, text)
        self.assertIn("default device", text)


class ThereIsOneRegistryTests(unittest.TestCase):
    def test_the_accessor_returns_the_same_object_every_time(self) -> None:
        """Two registries would each be confidently wrong about half the app."""
        self.assertIs(microphone_registry(), microphone_registry())


if __name__ == "__main__":
    unittest.main()
