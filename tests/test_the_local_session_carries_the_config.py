"""X-435: a session built for the local route must carry the config, or the
local live-captions toggle (X-416) is a switch wired to nothing.

Seen in the film trace on 2026-09-04: with `stt.local_live_captions` on and
the Parakeet route selected, `live_captions_wanted` was called with
`config is dict False` and answered False. `create_stt_session` handed the
config to the cloud session only. The unit tests for X-416 pass the config
straight to the session, which is why they stayed green while the feature
never once ran for a user.
"""
from __future__ import annotations

import unittest

from knight_flow.local_live import live_captions_wanted
from knight_flow.stt_sessions import create_stt_session


def _noop(*_args, **_kwargs) -> None:
    return None


def _local_config(live: bool) -> dict:
    return {
        "stt": {
            "provider": "local",
            "local_model": "parakeet-tdt-0.6b-v3",
            "local_live_captions": live,
        },
        "audio": {},
        "dictation": {},
    }


class TheLocalSessionCarriesTheConfig(unittest.TestCase):
    def _session(self, config: dict):
        return create_stt_session(
            config=config,
            max_seconds=30,
            no_speech_timeout_seconds=8,
            silence_timeout_seconds=4,
            tail_capture_ms=500,
            min_capture_ms=900,
            on_update=_noop,
            on_status=_noop,
            on_level=_noop,
            on_done=_noop,
            on_error=_noop,
        )

    def test_the_local_session_sees_the_config_it_was_built_from(self) -> None:
        config = _local_config(live=True)
        session = self._session(config)
        self.assertEqual(session.provider_id, "local")
        self.assertIs(session.extra.get("config"), config)

    def test_the_live_gate_reads_true_through_the_session(self) -> None:
        """The exact call the session makes at start(), with what it holds."""
        session = self._session(_local_config(live=True))
        self.assertTrue(
            live_captions_wanted(session.extra.get("config"), provider_id=session.provider_id, gpu=False)
        )

    def test_the_toggle_off_still_reads_off(self) -> None:
        session = self._session(_local_config(live=False))
        self.assertFalse(
            live_captions_wanted(session.extra.get("config"), provider_id=session.provider_id, gpu=False)
        )


if __name__ == "__main__":
    unittest.main()
