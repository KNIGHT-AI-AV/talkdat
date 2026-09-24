"""2026-09-22: Talk DAT! is zero cloud and all free.

The owner's decision: no prices, trials, subscriptions, weekly word caps, plan
gating or purchase / forever-code redemption anywhere in the desktop app.
Sign-in stays (device and emailed-code flows, sign-out, preference sync); it
decides nothing about dictation.

Two guarantees are pinned here, one behavioural and one structural:

1. No dictation can be refused for a plan, trial or word-count reason. The
   REAL start_session is driven against a stub app whose account is every
   shape the old gate refused -- lapsed plan, exhausted free words, expired
   trial, stale offline licence -- and whose licence manager cannot even be
   asked. Every one of them opens a session.

2. No desktop source reports usage to, or routes words through, our servers:
   nothing under knight_flow/ names the metering or managed-cloud endpoints,
   and the modules that did (the gate, the meter, the price list, the
   capability lock) are gone rather than switched off, so a flag cannot bring
   them back.
"""
from __future__ import annotations

import re
import types
import unittest
from pathlib import Path

from tests.test_signed_out_still_dictates import _FakeApp, _run_start_session

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "knight_flow"
APP = PACKAGE / "app.py"

RETIRED_MODULES = ("entitlement_gate.py", "usage_reporting.py", "pricing.py", "premium.py")

# The metering, managed-cloud and code-redemption routes of the account
# service. Sign-in (/v1/device, /v1/auth), /v1/prefs, /v1/handoff and
# /v1/feedback are deliberately NOT here: they stay.
FORBIDDEN_ENDPOINTS = ("/v1/free/", "/v1/cloud/", "/v1/code/redeem", "/v1/taste/")

# Names that only ever existed to meter, gate or sell.
FORBIDDEN_NAMES = (
    "evaluate_gate",
    "entitlement_decision",
    "licensing_is_enforced",
    "record_trial_start",
    "report_free_words",
    "free_words_used",
    "maybe_show_trial_moment",
    "open_trial_moment",
    "redeem_forever_code",
    "license_redeem_code",
    "apply_premium_lock",
    "show_premium_notice",
    "upgrade_page_opened",
)

SOURCE_SUFFIXES = {".py", ".js", ".json", ".html", ".css"}


def desktop_sources() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE.rglob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES and "__pycache__" not in path.parts
    )


def _gate_shaped_account(label: str):
    """A licence manager in one of the states the old gate refused."""
    states = {
        "lapsed_plan": dict(plan="pro", status="expired", active=False, permanent_core=False),
        "expired_trial": dict(plan="trial", status="expired", active=False, permanent_core=False),
        "never_signed_in": dict(plan="none", status="not_activated", active=False, permanent_core=False),
        "invalid_token": dict(plan="none", status="invalid", active=False, permanent_core=False),
    }
    shape = states[label]
    return types.SimpleNamespace(status=lambda: types.SimpleNamespace(email="", detail="", **shape))


class _UnaskableLicence:
    """Proves start_session never consults the account at all."""

    def status(self):  # pragma: no cover - reaching this IS the failure
        raise AssertionError("start_session asked the licence manager whether to dictate")


def _local_app(license_manager) -> _FakeApp:
    app = _FakeApp(account_active=False)
    app.config = {
        "stt": {"provider": "local", "route_mode": "local", "providers": {}},
        "dictation": {},
        # Every value the retired gate and meter read, set to its most
        # refusing shape. None of it may matter any more.
        "licensing": {
            "enforcement": "enforce",
            "trial_started_at": 1.0,
            "server_now": 10_000_000_000.0,
            "last_server_check": 1.0,
            "free_words_used": 10**9,
            "free_week_started_at": 10_000_000_000.0,
        },
    }
    app.license_manager = license_manager
    return app


class NoDictationIsRefusedForMoneyTests(unittest.TestCase):
    def assert_session_opens(self, app: _FakeApp) -> None:
        captured = _run_start_session(app, model_on_disk=True)
        self.assertIsNotNone(captured, f"a dictation was refused: {app.overlay.states}")
        errors = [state for state in app.overlay.states if state[0] == "error"]
        self.assertEqual(errors, [], "a served dictation must not show an error")

    def test_every_account_shape_the_old_gate_refused_still_dictates(self) -> None:
        for label in ("lapsed_plan", "expired_trial", "never_signed_in", "invalid_token"):
            with self.subTest(account=label):
                self.assert_session_opens(_local_app(_gate_shaped_account(label)))

    def test_the_account_is_never_asked(self) -> None:
        self.assert_session_opens(_local_app(_UnaskableLicence()))

    def test_start_session_has_no_gate_to_consult(self) -> None:
        source = APP.read_text(encoding="utf-8")
        match = re.search(r"\n    def start_session\(self.*?(?=\n    def )", source, re.S)
        self.assertIsNotNone(match, "start_session moved; point this guard at it")
        body = match.group(0)
        for needle in ("license_manager", "entitlement", "licensing_is_enforced", "free_words", "trial"):
            code_only = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
            self.assertNotIn(needle, code_only, f"start_session consults {needle!r} again")

    def test_the_recording_ceiling_ignores_any_plan(self) -> None:
        from knight_flow.config import engine_recording_ceiling

        self.assertEqual(engine_recording_ceiling(cloud_engine=False), 36000)
        self.assertEqual(engine_recording_ceiling(cloud_engine=True), 3600)


class NothingMetersOrSellsTests(unittest.TestCase):
    def test_the_guard_can_see_the_sources(self) -> None:
        self.assertGreater(len(desktop_sources()), 50, "the source scan found almost nothing")

    def test_the_retired_modules_are_gone(self) -> None:
        for name in RETIRED_MODULES:
            with self.subTest(module=name):
                self.assertFalse((PACKAGE / name).exists(), f"knight_flow/{name} is back")

    def test_no_desktop_source_names_a_metering_or_managed_endpoint(self) -> None:
        offenders = []
        for path in desktop_sources():
            text = path.read_text(encoding="utf-8", errors="replace")
            for endpoint in FORBIDDEN_ENDPOINTS:
                if endpoint in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {endpoint}")
        self.assertEqual(offenders, [])

    def test_no_desktop_source_revives_a_gate_meter_or_shop(self) -> None:
        offenders = []
        for path in desktop_sources():
            text = path.read_text(encoding="utf-8", errors="replace")
            for name in FORBIDDEN_NAMES:
                if name in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {name}")
        self.assertEqual(offenders, [])

    def test_the_default_config_carries_no_paywall_switch(self) -> None:
        from knight_flow.config import DEFAULT_CONFIG

        self.assertNotIn("enforcement", DEFAULT_CONFIG["licensing"])
        self.assertNotIn("talk_dat_cloud", DEFAULT_CONFIG["stt"]["providers"])

    def test_old_installs_lose_the_paywall_switch(self) -> None:
        from knight_flow.config import _migrate_licensing_enforcement

        config = {"licensing": {"enforcement": "enforce", "device_id": "td-keep"}}
        _migrate_licensing_enforcement(config)
        self.assertNotIn("enforcement", config["licensing"])
        self.assertEqual(config["licensing"]["device_id"], "td-keep", "sign-in state must survive")

    def test_sign_in_is_kept(self) -> None:
        from knight_flow import licensing

        for name in ("begin_activation", "exchange_activation", "start_email_code",
                     "verify_email_code", "approve_device", "forget_license"):
            with self.subTest(method=name):
                self.assertTrue(hasattr(licensing.LicenseManager, name))
        self.assertTrue(licensing.DEFAULT_COMMERCE_API_URL.startswith("https://"))
        self.assertFalse(hasattr(licensing.LicenseManager, "redeem_code"))


if __name__ == "__main__":
    unittest.main()
