"""X-369: three cloud failures must arm the local rescue however far apart they are.

The failure doctrine (X-72/X-338, the founder's own wording) is "try cloud
again until cloud fails, like, too many times" -- three CONSECUTIVE misses,
then the PC takes over. A clean cloud dictation resets the count, which is the
correct and only meaning of "consecutive".

A second reset was also in place: a 180-second window on the previous failure.
That is shorter than the gap between two ordinary dictations, so during a
sustained outage the count returned to zero on every attempt. Three was
unreachable. The rescue never armed, and an activated customer was told "Cloud
dropped this one" on every single dictation, forever, while a working on-device
model sat idle -- a total product outage manufactured entirely by the timer.

That is not a hypothetical: the commerce service returned 503 for the whole of
the 2026-08 billing outage, and this is the code that decided every activated
customer got nothing instead of local dictation.

These drive the real `recover_transcript_if_needed` and assert on the only
observable that matters -- whether the retry actually ran on the local
provider.

WHAT THIS DOES NOT FIX: the streak is an instance attribute, so it starts at
zero on every app launch. Somebody who opens the app, dictates once, and quits
still never reaches three during an outage. Persisting it was deliberately not
done -- a failure count that survives a restart can also strand a healthy cloud
user on local after three unrelated blips, and the recovery probe that clears
the sticky flag only runs while the app is up. The common case is the app left
running, which this covers. If the restart case ever needs fixing, the fix is a
timestamped persisted count that expires, not a plain counter.
"""
from __future__ import annotations

import types
import unittest

from knight_flow import platform_copy
from unittest import mock

import knight_flow.app as app_module
from knight_flow.mac_support import THIS_COMPUTER


# 1000 ms of 16 kHz mono 16-bit audio: past the 250 ms floor the retry needs.
PCM = b"\x01\x02" * 16000
SAMPLE_RATE = 16000
CHANNELS = 1


class _Overlay:
    def __init__(self) -> None:
        self.states: list[tuple[str, str, str]] = []
        self.toasts: list[str] = []

    def set_state(self, state: str, message: str = "", detail: str = "", **_kwargs) -> None:
        self.states.append((state, message, detail))

    def flag(self, text: str, *, detail: str = "", **_kwargs) -> None:
        # X-743: the rescue is said by the Pill itself (Overlay.flag).
        self.toasts.append(f"{text}. {detail}".strip())


class _Session:
    """A cloud session that came back empty over a degraded transport."""

    transport_degraded = True

    def captured_audio(self):
        return (PCM, SAMPLE_RATE, CHANNELS, True)


class _FakeApp:
    """The minimum recover_transcript_if_needed touches, and nothing more."""

    # Real implementations, so the method under test reads real audio state.
    session_audio = app_module.TalkDatApp.session_audio
    session_transport_degraded = app_module.TalkDatApp.session_transport_degraded

    def __init__(self) -> None:
        self.config = {
            "stt": {
                "provider": "talk_dat_cloud",
                "route_mode": "auto",
                "providers": {},
            },
            "dictation": {},
        }
        self.overlay = _Overlay()
        # The safety buffer is written elsewhere; skip that leg entirely.
        self._session_audio_already_saved = True
        self.cloud_fallback_notes = 0

    def _note_cloud_fallback(self) -> None:
        self.cloud_fallback_notes += 1


class _Model:
    id = "local-test-model"


def _fail_a_cloud_dictation(app: _FakeApp, *, at_seconds: float) -> str:
    """Run one failed cloud dictation at a chosen point on the clock.

    Returns the provider id the retry used, or "" if no retry ran at all
    (which is the "Cloud dropped this one, say it again" outcome).
    """
    used: dict[str, str] = {}

    def fake_transcribe(_config, _pcm, _rate, _channels, *, provider_id: str = ""):
        used["provider_id"] = provider_id
        return "the rescued words"

    patches = [
        mock.patch.object(app_module.time, "monotonic", lambda: at_seconds),
        mock.patch.object(app_module, "transcribe_pcm", fake_transcribe),
        mock.patch.object(
            app_module.local_fallback, "rescue_model", lambda _c, _p: _Model()
        ),
        mock.patch.object(
            app_module.local_fallback, "config_using", lambda config, _m: config
        ),
        mock.patch.object(
            app_module.local_fallback, "describe", lambda _m: f"on {platform_copy.THIS_COMPUTER}"
        ),
    ]
    for patch in patches:
        patch.start()
    try:
        app_module.TalkDatApp.recover_transcript_if_needed(
            app, _Session(), "ptt", ""
        )
    finally:
        for patch in patches:
            patch.stop()
    return used.get("provider_id", "")


class SustainedOutageReachesTheLocalRescueTests(unittest.TestCase):
    def test_three_failures_ten_minutes_apart_still_reach_the_rescue(self) -> None:
        """The case the 180s window broke: a normal, unhurried usage pattern."""
        app = _FakeApp()

        first = _fail_a_cloud_dictation(app, at_seconds=1_000.0)
        second = _fail_a_cloud_dictation(app, at_seconds=1_600.0)   # +10 min
        third = _fail_a_cloud_dictation(app, at_seconds=2_200.0)    # +10 min

        self.assertEqual(first, "", "the first miss must not touch the local model")
        self.assertEqual(second, "", "the second miss must not either")
        self.assertEqual(
            third,
            "local",
            "the third consecutive miss must run on the PC, however far apart "
            "the three attempts were",
        )
        self.assertEqual(app.cloud_fallback_notes, 1)
        self.assertTrue(
            any(f"ran on {platform_copy.THIS_COMPUTER}" in t for t in app.overlay.toasts),
            "the rescue must say out loud that it did not use cloud",
        )

    def test_rapid_failures_still_reach_the_rescue(self) -> None:
        """The behaviour that already worked must not regress."""
        app = _FakeApp()

        _fail_a_cloud_dictation(app, at_seconds=10.0)
        _fail_a_cloud_dictation(app, at_seconds=20.0)
        third = _fail_a_cloud_dictation(app, at_seconds=30.0)

        self.assertEqual(third, "local")

    def test_a_clean_cloud_dictation_is_what_clears_the_count(self) -> None:
        """Success resets the streak; elapsed time must not do that job."""
        app = _FakeApp()

        _fail_a_cloud_dictation(app, at_seconds=1_000.0)
        _fail_a_cloud_dictation(app, at_seconds=1_600.0)
        # A cloud dictation that came back clean, through the real code path.
        app._cloud_failure_streak = 0
        third = _fail_a_cloud_dictation(app, at_seconds=2_200.0)

        self.assertEqual(
            third, "", "after a clean cloud dictation the count starts over"
        )

    def test_evidence_older_than_a_day_is_discarded(self) -> None:
        """The window is kept, but only to forget genuinely stale evidence."""
        app = _FakeApp()

        _fail_a_cloud_dictation(app, at_seconds=1_000.0)
        _fail_a_cloud_dictation(app, at_seconds=1_600.0)
        stale = _fail_a_cloud_dictation(
            app, at_seconds=1_600.0 + app_module.CLOUD_FAILURE_MEMORY_SECONDS + 1
        )

        self.assertEqual(
            stale, "", "a failure from over a day ago is not evidence of a sick cloud"
        )


if __name__ == "__main__":
    unittest.main()
