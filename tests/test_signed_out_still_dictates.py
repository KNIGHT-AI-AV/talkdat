"""X-98: a signed-out machine with a local model must still dictate.

The 0.4.7x cloud-first migration wrote the managed leg into every config.
The account gate then refused the SESSION when it should have refused the
ROUTE: seven push-to-talk attempts in one morning each died with "Sign in to
use Talk DAT! Cloud" while a downloaded on-device model sat idle. These run
the real start_session against a stub app and assert the three outcomes that
matter:

- signed out + model on disk  -> the session RUNS, on-device, and says so
- signed out + nothing on disk -> the refusal naming the two ways in
- signed in                    -> exactly the same as signed out

2026-09-22: Talk DAT! is free, and the account gate is gone. The legacy
managed name is handled identically whoever is signed in.

They stub at module seams (create_stt_session, safety capture, connectivity)
rather than inside knight_flow, so the entire routing body -- resolve_route,
the account gate, the offline preflight -- executes for real.
"""
from __future__ import annotations

import threading
import types
import unittest

from knight_flow import platform_copy
from unittest import mock

from knight_flow import mac_support


# X-465: this module is about the world where local-only is OFF.
#
# Talk DAT! is local-only by default now: the speech route, the formatter and
# the door that lets text leave all read one switch, and a config that has
# never heard of that switch is treated as local-only, which is the right
# answer for a real install upgrading from an older version. The fixtures
# below are bare dicts asking for the managed or bring-your-own-key route, so
# without this they would resolve to local and test nothing they mean to.
#
# That route still exists for anybody who deliberately turns the switch off,
# and it still has to work. Naming the world here is the point: these
# assertions are about the cloud contract, not about whichever default happens
# to be in force.
_LOCAL_ONLY_OFF = mock.patch("knight_flow.stt_registry.local_only", return_value=False)


def setUpModule() -> None:
    _LOCAL_ONLY_OFF.start()


def tearDownModule() -> None:
    _LOCAL_ONLY_OFF.stop()


def _fake_local_model():
    from knight_flow.local_stt import LOCAL_MODELS

    return LOCAL_MODELS[0]


class _Overlay:
    def __init__(self) -> None:
        self.states: list[tuple[str, str, str]] = []
        self.root = types.SimpleNamespace(after=lambda *_a, **_k: None)

    def set_state(self, state: str, message: str = "", detail: str = "") -> None:
        self.states.append((state, message, detail))

    def set_level(self, level: float) -> None:  # pragma: no cover - noise
        pass


class _FakeApp:
    """The minimum start_session touches, and nothing more."""

    def __init__(self, *, account_active: bool) -> None:
        # route_mode "cloud" pins the pill to the explicit-cloud position.
        # On "auto" resolve_route already sidesteps an unentitled managed leg
        # before the gate; "cloud" is the position that was refusing signed-out
        # machines, so it is the position these tests must drive.
        self.config = {
            "stt": {
                "provider": "talk_dat_cloud",
                "route_mode": "cloud",
                "providers": {},
            },
            "dictation": {},
        }
        self.paused = False
        self.overlay = _Overlay()
        self.lock = threading.Lock()
        self.session = None
        self.session_token = None
        self.session_mode = "idle"
        self.session_control = "idle"
        self.session_error_message = ""
        self.offline_fallback_notice = ""
        self.safety_capture = None
        self.safety_capture_token = None
        self._screen_names: list[str] = []
        self._session_audio_seen = False
        self._dead_mic_warned = None
        self.session_chime_token = None
        self.safety_capture_failure_token = None
        self._released_processing = False
        self._trigger_released_at = None
        self.license_manager = types.SimpleNamespace(
            status=lambda: types.SimpleNamespace(
                active=account_active, permanent_core=False
            )
        )

    # Collaborators start_session calls on self -----------------------------
    def _scribe_busy(self) -> bool:
        from knight_flow.app import TalkDatApp
        return TalkDatApp._scribe_busy(self)

    def _maybe_return_to_cloud(self) -> None:
        pass

    def _note_cloud_fallback(self) -> None:
        pass

    def session_limits(self, control: str, provider_id: str) -> dict:
        return {
            "max_seconds": 90,
            "no_speech_timeout_seconds": 10,
            "silence_timeout_seconds": 2,
        }

    def begin_activation_guards(self) -> None:
        pass


class _Session:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True


def _run_start_session(app: _FakeApp, *, model_on_disk: bool):
    """Drive the REAL TalkDatApp.start_session against the stub app.

    Returns the kwargs create_stt_session was called with, or None if the
    session never got that far.
    """
    import knight_flow.app as app_module

    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _Session()

    fallback = _fake_local_model() if model_on_disk else None
    patches = [
        mock.patch.object(app_module, "create_stt_session", fake_create),
        mock.patch.object(
            app_module, "start_safety_capture", lambda **_k: types.SimpleNamespace()
        ),
        mock.patch(
            "knight_flow.local_fallback.fallback_model", lambda _c=None: fallback
        ),
        # The preflight must see a healthy network so it stays out of the way
        # and the ACCOUNT reroute is the only fallback that can fire.
        mock.patch("knight_flow.local_fallback.network_is_available", lambda: True),
    ]
    for p in patches:
        p.start()
    try:
        app_module.TalkDatApp.start_session(app, "ptt", "Listening...")
    finally:
        for p in patches:
            p.stop()
    return captured if captured else None


class SignedOutStillDictatesTests(unittest.TestCase):
    def test_signed_out_with_a_local_model_dictates_on_device(self) -> None:
        app = _FakeApp(account_active=False)
        captured = _run_start_session(app, model_on_disk=True)
        self.assertIsNotNone(captured, "the session must run, not be refused")
        session_config = captured["config"]
        self.assertEqual(session_config["stt"]["provider"], "local")
        errors = [s for s in app.overlay.states if s[0] == "error"]
        self.assertEqual(errors, [], "a served dictation must not show an error")
        # X-480: the pill still says why, but "sign in" is no longer the
        # reason. There is nothing to sign in TO for dictation: the two routes
        # are this machine and the person's own key, and this one ran here.
        self.assertIn(platform_copy.THIS_COMPUTER, app.offline_fallback_notice,
                      "the pill must still say where this ran")

    def test_signed_out_with_nothing_on_disk_is_refused_with_the_way_in(self) -> None:
        app = _FakeApp(account_active=False)
        captured = _run_start_session(app, model_on_disk=False)
        self.assertIsNone(captured, "nothing on the machine can serve this")
        errors = [s for s in app.overlay.states if s[0] == "error"]
        self.assertTrue(errors, "a refusal with no message is a dead end")
        # X-480: the WAY IN is what this test is really about, and it changed
        # with the product. Signing in does not get you dictation any more.
        # Downloading a model or adding your own key does, and the refusal has
        # to name both, because those are the two routes there are.
        message = errors[0][1] + " " + (errors[0][2] if len(errors[0]) > 2 else "")
        # 2026-09-23: the menu row is "Local models" now, the name Settings,
        # the tray and the sidebar already used ("Offline speech" was a
        # second name for the same place).
        self.assertIn("Local models", message, "it must say where to get a model")
        self.assertIn("your own provider key", message, "it must offer the other route")

    def test_an_account_no_longer_changes_which_engine_runs(self) -> None:
        """X-480: this used to assert that signing in moved you onto the
        managed leg. There is no managed leg.

        An account still exists, for sign-in and preference sync, but it has
        no say over which engine transcribes a person's voice. Signed in with
        a local model on disk is the same dictation as signed out with one --
        including what the pill says about where it ran (2026-09-22)."""
        signed_in = _FakeApp(account_active=True)
        captured = _run_start_session(signed_in, model_on_disk=True)
        self.assertIsNotNone(captured)
        session_config = captured["config"]
        self.assertEqual(session_config["stt"]["provider"], "local")
        signed_out = _FakeApp(account_active=False)
        _run_start_session(signed_out, model_on_disk=True)
        self.assertEqual(signed_in.offline_fallback_notice, signed_out.offline_fallback_notice)

    def test_an_account_no_longer_changes_a_refusal_either(self) -> None:
        signed_in = _FakeApp(account_active=True)
        self.assertIsNone(_run_start_session(signed_in, model_on_disk=False))
        self.assertTrue([s for s in signed_in.overlay.states if s[0] == "error"])


if __name__ == "__main__":
    unittest.main()
