from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from knight_flow.app import TalkDatApp
from knight_flow.licensing import LicenseState
from knight_flow.onboarding import ONBOARDING_VERSION


class AppReadinessTests(unittest.TestCase):
    def test_microphone_backend_is_warm_before_hotkeys_accept_triggers(self) -> None:
        app = TalkDatApp.__new__(TalkDatApp)
        events: list[str] = []

        class FakeHotkeys:
            def start(self) -> None:
                events.append("hotkeys")

        app.hotkeys = FakeHotkeys()
        self.assertTrue(
            hasattr(app, "_start_input_runtime"),
            "The app needs one startup gate that warms audio before enabling hotkeys.",
        )
        with patch("knight_flow.app.warm_audio_input_backend", side_effect=lambda: events.append("audio") or 12.0):
            app._start_input_runtime()

        self.assertEqual(events, ["audio", "hotkeys"])

    def test_first_launch_onboarding_is_shown_even_for_keyless_local_default(self) -> None:
        app = TalkDatApp.__new__(TalkDatApp)
        app.config = {"stt": {"provider": "local"}, "onboarding": {"completed": False, "version": 0}}
        self.assertTrue(app.needs_onboarding())
        app.config["onboarding"]["completed"] = True
        self.assertTrue(app.needs_onboarding(), "Older onboarding must be shown once after the guided setup ships.")
        app.config["onboarding"]["version"] = ONBOARDING_VERSION
        self.assertFalse(app.needs_onboarding())

    def test_browser_activation_updates_the_onboarding_safe_status(self) -> None:
        app = TalkDatApp.__new__(TalkDatApp)
        app.license_activation_lock = threading.Lock()
        app.license_activation_in_progress = False
        app._license_activation_cancel = threading.Event()
        app.license_activation_snapshot = {"state": "idle", "detail": "Not started."}

        class Manager:
            product_url = "https://example.test"

            def begin_activation(self) -> dict[str, object]:
                return {
                    "userCode": "ABCD-EFGH",
                    "deviceCode": "private-device-secret",
                    "verificationUri": "https://example.test/account",
                    "expiresIn": 60,
                    "interval": 2,
                }

            def exchange_activation(self, **_kwargs: object) -> LicenseState:
                return LicenseState(plan="trial", status="active", active=True, email="person@example.com", detail="Trial active.")

        class Overlay:
            def set_state(self, *_args: object) -> None:
                return None

        app.license_manager = Manager()
        app.overlay = Overlay()
        with patch("knight_flow.app.webbrowser.open"), patch("knight_flow.app.copy_text", return_value=True):
            app.activate_license()
            deadline = time.monotonic() + 2
            while app.license_activation_status()["in_progress"] and time.monotonic() < deadline:
                time.sleep(0.01)

        status = app.license_activation_status()
        self.assertEqual(status["state"], "active")
        # 2026-09-22: Talk DAT! is free; the snapshot carries no plan.
        self.assertNotIn("plan", status)
        self.assertNotIn("device_code", status)
        self.assertNotIn("private-device-secret", repr(status))


if __name__ == "__main__":
    unittest.main()
