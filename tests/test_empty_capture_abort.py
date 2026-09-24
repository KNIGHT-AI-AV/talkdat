from __future__ import annotations

import unittest

from knight_flow.app import TalkDatApp


class _Session:
    def __init__(self, text: str = "", audio=None):
        self._text = text
        self._audio = audio

    def current_text(self) -> str:
        return self._text


SILENCE = b"\x00\x00" * 8000  # half a second of dead 16k mono
VOICE_LIKE = bytes(range(0, 250)) * 256  # loud varied samples, trips the RMS floor


class EmptyCaptureAbortTests(unittest.TestCase):
    """X-138, his priority: an accidental press with nothing said must not
    sit in "Finalizing" for a silence timeout. The predicate must be certain
    before it aborts -- a wrong True loses a dictation, a wrong False only
    costs a short wait."""

    def _app(self, audio):
        app = TalkDatApp.__new__(TalkDatApp)
        app.session_audio = lambda _session: audio
        return app

    def test_silent_capture_is_provably_empty(self) -> None:
        app = self._app((SILENCE, 16000, 1, False))
        self.assertTrue(app._session_heard_nothing(_Session("")))

    def test_interim_text_blocks_the_abort(self) -> None:
        app = self._app((SILENCE, 16000, 1, False))
        self.assertFalse(app._session_heard_nothing(_Session("hello there")))

    def test_vad_voice_blocks_the_abort(self) -> None:
        app = self._app((SILENCE, 16000, 1, True))
        self.assertFalse(app._session_heard_nothing(_Session("")))

    def test_rms_signal_blocks_the_abort(self) -> None:
        app = self._app((VOICE_LIKE, 16000, 1, False))
        self.assertFalse(app._session_heard_nothing(_Session("")))

    def test_unknown_audio_blocks_the_abort(self) -> None:
        app = self._app(None)
        self.assertFalse(app._session_heard_nothing(_Session("")))

    def test_a_predicate_error_blocks_the_abort(self) -> None:
        app = TalkDatApp.__new__(TalkDatApp)

        def boom(_session):
            raise RuntimeError("audio backend gone")

        app.session_audio = boom
        self.assertFalse(app._session_heard_nothing(_Session("")))


if __name__ == "__main__":
    unittest.main()
