from __future__ import annotations

import unittest
from unittest.mock import patch

from knight_flow.mac_support import IS_MAC


@unittest.skipUnless(IS_MAC, "X-11 handoff on macOS")
class TheSignInHandoffArrivesDifferentlyHereTests(unittest.TestCase):
    """Windows gets every talkdat:// open as a second process with the URI in
    argv, and talk_dat.py branches on that before the app constructs.

    macOS only behaves that way when the app is NOT already running. When it is
    -- which is the normal case, since someone signing in on the web has the
    app open -- the system delivers an Apple Event to the live process and
    starts nothing at all. The argv branch, which is the entire Windows
    mechanism, never fires.
    """

    def test_registration_does_not_claim_what_it_did_not_do(self) -> None:
        """macOS reads the scheme from the bundle's CFBundleURLTypes, so a
        source checkout can never be the handler. Returning True would claim a
        registration that did not happen."""
        from knight_flow.handoff import register_protocol

        with patch("knight_flow.handoff.sys") as s:
            s.platform = "darwin"
            s.frozen = False
            self.assertFalse(register_protocol())

    def test_the_bundle_declares_the_scheme(self) -> None:
        from pathlib import Path

        spec = (Path(__file__).resolve().parents[1] / "TalkDat-mac.spec").read_text(encoding="utf-8")
        self.assertIn("CFBundleURLTypes", spec)
        self.assertIn('"talkdat"', spec)
        # Cold start still needs the event turned into argv for talk_dat.py.
        self.assertIn("argv_emulation=True", spec)

    def test_the_apple_event_feeds_the_same_drop_file(self) -> None:
        """Both platforms must converge on one code path. The tick that claims
        the drop file is shared; only how the URI gets there differs."""
        import inspect

        from knight_flow.app import TalkDatApp

        source = inspect.getsource(TalkDatApp.start_handoff_watch)
        self.assertIn("watch_url_scheme", source)
        self.assertIn("stash_uri_for_primary", source)

    def test_only_a_real_code_shape_survives_the_round_trip(self) -> None:
        """The Apple Event hands over an arbitrary string from the browser, so
        the parser is the trust boundary on this platform too."""
        from knight_flow.handoff import parse_signin_code

        self.assertEqual(parse_signin_code("talkdat://signin?code=abc123XYZ_-456"), "abc123XYZ_-456")
        for junk in (
            "talkdat://signin?code=../../etc/passwd",
            "talkdat://evil?code=abc123XYZ",
            "https://example.com/signin?code=abc123XYZ",
            "talkdat://signin?code=short",
            "",
        ):
            with self.subTest(uri=junk):
                self.assertEqual(parse_signin_code(junk), "")


if __name__ == "__main__":
    unittest.main()
