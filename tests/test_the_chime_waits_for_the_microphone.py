"""P1-2 (find-more sweep): the "listening" chime waits for the microphone's first audio.

Sessions report "listening" when the input stream OPENS (stt_sessions.py,
deepgram_live.py), and the app chimed and showed listening right then. The
first frame can come much later (a Bluetooth headset switching to its call
profile, a USB mic waking, which also deliver exact digital silence first),
so the person started talking on the chime and the first words were lost.

Now the chime and the listening state wait for the first frame that is not
pure digital silence, or 1 s at most, and nothing is announced once the
trigger has been released.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.test_app_session_lifecycle import _app

SILENCE = b"\x00\x00" * 160
SOUND = b"\x10\x02" * 160


class _Root:
    def __init__(self) -> None:
        self.timers: list = []

    def after(self, delay: int, callback) -> None:
        self.timers.append((delay, callback))


class TheChimeWaitsForTheMicrophone(unittest.TestCase):
    def setUp(self) -> None:
        self.token = object()
        self.app = _app(self.token)
        self.app.session_chime_token = None
        self.app._session_audio_seen = False  # what start_session sets
        self.app._released_processing = False
        self.app.overlay.root = _Root()
        self.chimes: list[str] = []
        self.app.play_sound = self.chimes.append
        self.posted: list = []
        patcher = patch("knight_flow.app.main_thread.post", side_effect=self.posted.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def frame(self, data: bytes) -> None:
        self.app.on_session_audio(self.token, data, 16000, 1, False)

    def run_posted(self) -> None:
        while self.posted:
            self.posted.pop(0)()

    def listening_shown(self) -> bool:
        return any(state == "listening" for state, _message in self.app.overlay.states)

    def test_the_stream_opening_is_not_listening_yet(self) -> None:
        self.app.on_session_status(self.token, "dictation", "listening", "hold")
        self.run_posted()
        self.assertEqual(self.chimes, [])
        self.assertFalse(self.listening_shown())

    def test_silence_from_a_waking_device_does_not_count(self) -> None:
        self.app.on_session_status(self.token, "dictation", "listening", "hold")
        self.frame(SILENCE)
        self.run_posted()
        self.assertEqual(self.chimes, [])

    def test_the_first_real_frame_chimes_once(self) -> None:
        self.app.on_session_status(self.token, "dictation", "listening", "hold")
        with self.assertLogs("knight_flow.app", level="INFO") as logs:
            self.frame(SOUND)
            self.frame(SOUND)
            self.run_posted()
        self.assertEqual(self.chimes, ["on"])
        self.assertEqual(self.app.overlay.states[-1], ("listening", "Hold mode: release to stop."))
        self.assertTrue(any("microphone: listening shown" in line and "first frame" in line for line in logs.output))

    def test_audio_that_came_first_chimes_at_once(self) -> None:
        self.frame(SOUND)
        self.app.on_session_status(self.token, "dictation", "listening", "hold")
        self.assertEqual(self.chimes, ["on"])
        self.assertTrue(self.listening_shown())

    def test_no_audio_at_all_still_chimes_after_the_wait(self) -> None:
        # Conservative: a device that never delivers still gets the old
        # chime, 1 s late; the dead-mic check then says what is wrong.
        self.app.on_session_status(self.token, "dictation", "listening", "hold")
        self.run_posted()
        (delay, fallback), = self.app.overlay.root.timers
        self.assertEqual(delay, self.app.FIRST_FRAME_WAIT_MS)
        fallback()
        self.assertEqual(self.chimes, ["on"])
        self.assertTrue(self.listening_shown())

    def test_nothing_is_announced_after_the_release(self) -> None:
        self.app.on_session_status(self.token, "dictation", "listening", "hold")
        self.run_posted()
        self.app._released_processing = True  # stop_session stamps this
        self.frame(SOUND)
        self.run_posted()
        _delay, fallback = self.app.overlay.root.timers[0]
        fallback()
        self.assertEqual(self.chimes, [])
        self.assertFalse(self.listening_shown())

    def test_an_app_built_without_a_session_start_keeps_the_old_timing(self) -> None:
        del self.app._session_audio_seen
        self.app.on_session_status(self.token, "dictation", "listening", "hold")
        self.assertEqual(self.chimes, ["on"])


if __name__ == "__main__":
    unittest.main()
