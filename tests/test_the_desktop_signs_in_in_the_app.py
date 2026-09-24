"""X-432: the desktop signs in from its own Account window, on Mac and Windows.

His order: "full login and account setup" from the menu on Mac and Windows,
with the website as an option. Until this, the desktop's only sign-in opened a
browser and polled: the app had no way to take an email, send a code, or verify
one, even though the service has offered exactly those routes since X-404.

The chain is every route the website already uses, in the order the website
uses them, with the app standing where the browser stood:

  device/start -> auth/email/start -> auth/email/verify -> device/approve -> device/token

The first and last already existed as begin_activation and exchange_activation,
so the licence lands through the one acceptance path every other activation
uses. The account is created on the first verify and a fresh account gets its
trial when this device is approved, which is why "setup" is not a third step.

And the Mac: credential_store() answered Unavailable on anything but Windows,
and the licence acceptor refuses an unavailable store, so on a Mac NO sign-in
of any kind could ever finish. A keychain store backed by /usr/bin/security
fixes that for every path at once.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LICENSING = (ROOT / "knight_flow" / "licensing.py").read_text(encoding="utf-8")
APP = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8")
OVERLAY = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")


def block(source: str, start: str, length: int = 2600) -> str:
    return source[source.index(start):source.index(start) + length]


class TheClientRunsTheWebsitesChainTests(unittest.TestCase):
    def test_the_three_missing_calls_exist(self) -> None:
        for name in ("def start_email_code(", "def verify_email_code(", "def approve_device("):
            self.assertIn(name, LICENSING, name)

    def test_they_hit_the_routes_the_website_hits(self) -> None:
        self.assertIn('"/v1/auth/email/start"', LICENSING)
        self.assertIn('"/v1/auth/email/verify"', LICENSING)
        self.assertIn('"/v1/device/approve"', LICENSING)

    def test_the_route_that_needs_a_bearer_gets_one(self) -> None:
        approve = block(LICENSING, "def approve_device(", 900)
        self.assertIn("bearer=access_token", approve)
        request = block(LICENSING, "def _json_request(", 700)
        self.assertIn('headers["authorization"] = f"Bearer {bearer}"', request)

    def test_the_request_id_is_the_shape_the_route_demands(self) -> None:
        """The web route 400s on anything but 32 hex characters."""
        self.assertIn('"requestId": secrets.token_hex(16)', LICENSING)

    def test_the_client_names_its_platform(self) -> None:
        self.assertIn('"talkdat-mac" if sys.platform == "darwin" else "talkdat-windows"', LICENSING)

    def test_a_bad_address_or_code_is_refused_before_the_network(self) -> None:
        from knight_flow.licensing import LicenseError, LicenseManager

        manager = LicenseManager.__new__(LicenseManager)
        with self.assertRaises(LicenseError):
            LicenseManager.start_email_code(manager, "not-an-address")
        with self.assertRaises(LicenseError):
            LicenseManager.verify_email_code(manager, "a@b.co", "12")
        with self.assertRaises(LicenseError):
            LicenseManager.approve_device(manager, "", "ABCD-EFGH")


class TheAppWiresTheTwoStepsTests(unittest.TestCase):
    def test_the_window_has_both_callbacks(self) -> None:
        self.assertIn('"license_email_start": self.begin_email_sign_in,', APP)
        self.assertIn('"license_email_verify": self.finish_email_sign_in,', APP)

    def test_the_first_step_reserves_this_device_and_sends_the_code(self) -> None:
        begin = block(APP, "def begin_email_sign_in(")
        self.assertIn("self.license_manager.begin_activation()", begin)
        self.assertIn("self.license_manager.start_email_code(email)", begin)
        self.assertIn('"state": "code_sent"', begin)
        self.assertIn('"user_code": user_code', begin)
        self.assertIn('"device_code": device_code', begin)

    def test_the_second_step_verifies_approves_and_lands_through_the_one_path(self) -> None:
        finish = block(APP, "def finish_email_sign_in(", 3200)
        self.assertIn("self.license_manager.verify_email_code(email, code)", finish)
        self.assertIn("self.license_manager.approve_device(token,", finish)
        self.assertIn("self.license_manager.exchange_activation(", finish)
        self.assertIn('"state": "active"', finish)

    def test_a_wrong_code_keeps_the_box_open(self) -> None:
        """A mistyped digit is one retype away, not a restart."""
        finish = block(APP, "def finish_email_sign_in(", 3200)
        self.assertIn('"code_error"', finish)
        self.assertIn('"code_invalid", "code_expired"', finish)

    def test_verifying_without_a_code_on_the_way_says_so(self) -> None:
        finish = block(APP, "def finish_email_sign_in(", 3200)
        self.assertIn('if pending.get("state") not in {"code_sent", "code_error"}:', finish)
        self.assertIn("Ask for a code first.", finish)


class TheAccountWindowTests(unittest.TestCase):
    def test_the_form_is_there_and_the_website_stays_an_option(self) -> None:
        window = block(OVERLAY, 'text="Sign in or create your account"', 5200)
        self.assertIn('text="Email me a code"', window)
        self.assertIn('text="Six-digit code"', window)
        self.assertIn('text="Send a new code"', window)
        self.assertIn('text="Sign in with this code"', window)
        self.assertIn('text="Prefer your browser? Sign in on the website instead"', window)
        self.assertIn('self._callback("license_activate")', window)

    def test_the_form_reaches_the_callbacks(self) -> None:
        window = block(OVERLAY, 'text="Sign in or create your account"', 5200)
        self.assertIn('self.callbacks.get("license_email_start")', window)
        self.assertIn('self.callbacks.get("license_email_verify")', window)

    def test_the_code_box_opens_on_code_sent_and_closes_when_done(self) -> None:
        refresh = block(OVERLAY, 'elif phase in {"code_sent", "verifying", "code_error"}:', 900)
        self.assertIn("code_entry_row.grid()", refresh)
        self.assertIn(
            'if phase not in {"code_sent", "verifying", "code_error"} and code_entry_row.winfo_ismapped():',
            OVERLAY,
        )

    def test_the_stale_google_promise_is_gone(self) -> None:
        self.assertNotIn("that is where Google sign-in", OVERLAY)

    def test_the_form_hides_once_signed_in(self) -> None:
        self.assertIn("signin_row.grid_remove()", OVERLAY)


class TheMacHasSomewhereToKeepTheLicenceTests(unittest.TestCase):
    def test_the_store_exists_and_is_chosen_on_darwin(self) -> None:
        from knight_flow import credentials

        self.assertTrue(hasattr(credentials, "MacKeychainStore"))
        source = (ROOT / "knight_flow" / "credentials.py").read_text(encoding="utf-8")
        self.assertIn('if sys.platform == "darwin":', block(source, "def credential_store()", 400))

    def test_the_round_trip_through_a_fake_security_tool(self) -> None:
        from knight_flow.credentials import MacKeychainStore

        vault: dict[str, str] = {}

        class Done:
            def __init__(self, code: int, out: str = "") -> None:
                self.returncode, self.stdout = code, out

        def fake_security(args: list[str]) -> Done:
            verb, opts = args[0], dict(zip(args[1::2], args[2::2]))
            service = opts.get("-s", "")
            if verb == "add-generic-password":
                vault[service] = opts["-w"]
                return Done(0)
            if verb == "find-generic-password":
                return Done(0, vault[service] + "\n") if service in vault else Done(44)
            if verb == "delete-generic-password":
                return Done(0) if vault.pop(service, None) is not None else Done(44)
            return Done(1)

        store = MacKeychainStore(runner=fake_security)
        store.available = True  # the fake does not care what platform runs the test
        self.assertEqual(store.read("TalkDat/License/x"), "")
        self.assertTrue(store.write("TalkDat/License/x", "signed.token"))
        self.assertEqual(store.read("TalkDat/License/x"), "signed.token")
        self.assertTrue(store.write("TalkDat/License/x", "newer.token"), "a second sign-in must update in place")
        self.assertEqual(store.read("TalkDat/License/x"), "newer.token")
        self.assertTrue(store.delete("TalkDat/License/x"))
        self.assertTrue(store.delete("TalkDat/License/x"), "deleting twice is idempotent, as on Windows")
        self.assertEqual(store.read("TalkDat/License/x"), "")

    def test_nothing_still_names_the_wrong_store_to_a_mac_user(self) -> None:
        for source in (LICENSING, APP):
            self.assertNotIn("Windows Credential Manager could not save", source)
            self.assertNotIn("Windows Credential Manager was unavailable", source)


if __name__ == "__main__":
    unittest.main()
