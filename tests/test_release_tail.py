"""X-768: after you let go of the key, the microphone stays open only for the words still coming at that moment.

The owner, 2026-10-16: "a lot of times it's still listening to me after I'm done and I let go ... it's like a little
bit too long". The release tail (stt_sessions._drain_tail) waits for 140 ms of quiet before it closes the microphone,
but it judged quiet on the level AFTER the adaptive front end, against a fixed 0.025. The front end lifts every pause
toward its speech target (X-405 measured a 67-second take on the founder's PC that never once dropped under that
level), so the quiet never came: every release paid the whole tail_capture_ms (520 ms by default), and whatever the
microphone heard in it was transcribed with the take.

These takes run through the real capture loop with a fake microphone that feeds 20 ms chunks in real time and a front
end that does what the founder's PC does to a pause: lifts it to speech loudness. The key is released at a known point
of the script, and the test measures how long the microphone stayed open after it.
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from knight_flow import stt_sessions
from knight_flow.stt_sessions import BatchSTTSession

RATE = 16000
CHUNK = RATE // 50  # 20 ms of mono audio, in samples


def _wave(amplitude: float) -> bytes:
    """A square wave at 400 Hz: the same RMS in every 20 ms chunk."""
    value = int(amplitude * 32767)
    return b"".join((value if (i // 20) % 2 else -value).to_bytes(2, "little", signed=True) for i in range(CHUNK))


# rms_level() reads 6x the raw RMS, against the gate's VOICE_LEVEL of 0.025.
SPEECH = _wave(0.3)  # a raw speaking level (reads 1.0)
ROOM = _wave(0.002)  # a quiet room (reads 0.012), under any voice threshold
WHISPER = _wave(0.0035)  # speech on a mic so quiet that it reads 0.021, under 0.025: the raw gate never hears it


class LiftedFrontEnd:
    """What the adaptive front end does on the founder's PC (X-405): a pause comes out as loud as speech."""

    def process(self, data: bytes) -> bytes:
        return SPEECH[: len(data)]

    def visual_level(self, level: float) -> float:
        return 0.0


class Microphone:
    """A stream that plays a script of (seconds, chunk) parts in real time and releases the key at RELEASE."""

    def __init__(self, callback, script: list) -> None:
        self.callback, self.script = callback, script
        self.closed = threading.Event()
        self.released_at = None
        self.closed_at = None
        self.session = None

    def __enter__(self):
        threading.Thread(target=self._feed, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self.closed_at = time.monotonic()
        self.closed.set()

    def _feed(self) -> None:
        for seconds, chunk in self.script:
            if chunk == "RELEASE":
                self.released_at = time.monotonic()
                self.session.stop()
                continue
            for _ in range(max(1, round(seconds * 50))):
                if self.closed.is_set():
                    return
                self.callback(chunk, CHUNK, None, None)
                time.sleep(0.02)


def take(script: list, tail_ms: int, lifted: bool = True) -> float:
    """Run one take through the real capture loop; seconds the microphone stayed open after the release."""
    done = threading.Event()
    microphones: list[Microphone] = []
    noop = lambda *a, **k: None  # noqa: E731
    session = BatchSTTSession(
        provider_id="openrouter", api_key="k", api_base="https://x", model="m", variant="", language="en",
        sample_rate=RATE, channels=1, max_seconds=60, no_speech_timeout_seconds=30, silence_timeout_seconds=45,
        tail_capture_ms=tail_ms, min_capture_ms=0, extra={},
        on_update=noop, on_status=noop, on_level=noop, on_done=lambda text: done.set(), on_error=noop,
    )
    if lifted:
        session.front_end = LiftedFrontEnd()
    session._transcribe = lambda wav: "words"

    def open_stream(**kwargs):
        microphones.append(Microphone(kwargs["callback"], script))
        microphones[-1].session = session
        return microphones[-1], RATE, 1, None

    with patch.object(stt_sessions, "open_raw_input_stream", open_stream), \
         patch.object(stt_sessions, "input_stream_active", lambda stream: True):
        session.start()
        if not done.wait(timeout=20):
            raise AssertionError("the take never finished")
    microphone = microphones[0]
    return microphone.closed_at - microphone.released_at


class ReleaseTailTests(unittest.TestCase):
    # Every take starts with a little room, as a real press does: the key goes down, then the words come
    # (audio_battery.compose does the same). The raw gate learns the room's floor from it.

    def test_a_finished_sentence_closes_the_microphone_at_the_release(self) -> None:
        """Done talking, a pause, then the key: nothing after the release belongs to the take."""
        open_for = take([(0.3, ROOM), (0.8, SPEECH), (0.4, ROOM), (0, "RELEASE"), (3.0, ROOM)], tail_ms=520)
        self.assertLess(open_for, 0.25, f"the microphone stayed open {open_for:.2f} s after the release")

    def test_a_release_mid_word_keeps_the_microphone_open_until_the_word_ends(self) -> None:
        """Let go a moment early and the last word is still recorded, then the microphone closes."""
        open_for = take([(0.3, ROOM), (0.8, SPEECH), (0, "RELEASE"), (0.26, SPEECH), (3.0, ROOM)], tail_ms=900)
        self.assertGreaterEqual(open_for, 0.24, "the last word was cut")
        self.assertLess(open_for, 0.62, f"the microphone stayed open {open_for:.2f} s, past the end of the word")

    def test_the_budget_still_caps_someone_who_keeps_talking(self) -> None:
        open_for = take([(0.3, ROOM), (0.8, SPEECH), (0, "RELEASE"), (3.0, SPEECH)], tail_ms=520)
        self.assertGreaterEqual(open_for, 0.45)
        self.assertLess(open_for, 0.85)

    def test_a_mic_too_quiet_for_the_raw_gate_keeps_the_old_wait(self) -> None:
        """Speech the raw gate never hears must not lose its last word: the old rule (and its budget) still holds."""
        open_for = take([(0.3, ROOM), (0.8, WHISPER), (0, "RELEASE"), (3.0, WHISPER)], tail_ms=400)
        self.assertGreaterEqual(open_for, 0.35, "a quiet microphone's tail was cut short")

    def test_a_take_that_starts_mid_word_and_never_pauses_keeps_the_old_wait(self) -> None:
        """Talking before the key went down: the first chunk is speech, so the raw gate takes it for the room's floor
        and hears nothing until a pause. It must fall back to the old rule, never cut."""
        open_for = take([(0.8, SPEECH), (0, "RELEASE"), (3.0, SPEECH)], tail_ms=400)
        self.assertGreaterEqual(open_for, 0.35, "a take the raw gate could not read was cut short")


if __name__ == "__main__":
    unittest.main()
