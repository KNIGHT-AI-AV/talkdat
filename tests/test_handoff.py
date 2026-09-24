from __future__ import annotations

import unittest

from knight_flow.handoff import parse_signin_code
import os
import tempfile
import unittest
from unittest import mock

from knight_flow.handoff import parse_signin_code, stash_uri_for_primary, take_stashed_uri


class TheLinkCarriesExactlyOneCodeTests(unittest.TestCase):
    """X-11. The URI parser is the app's attack surface for this feature:
    only the code shape we mint gets through, everything else reads as no
    code at all."""

    def test_the_minted_shape_parses(self) -> None:
        self.assertEqual(
            parse_signin_code("talkdat://signin?code=BwcHBwcHBwcHBwcHBwcHBwcHBwc"),
            "BwcHBwcHBwcHBwcHBwcHBwcHBwc",
        )
        self.assertEqual(parse_signin_code("talkdat:signin?code=abc123DEF456_-x"), "abc123DEF456_-x")

    def test_extra_params_do_not_confuse_it(self) -> None:
        self.assertEqual(parse_signin_code("talkdat://signin?utm=x&code=abcdefgh1234"), "abcdefgh1234")

    def test_junk_reads_as_no_code(self) -> None:
        for uri in (
            "",
            "talkdat://signin",
            "talkdat://signin?code=short",
            "talkdat://other?code=abcdefgh1234",
            "https://evil.example/?code=abcdefgh1234",
            "talkdat://signin?code=has spaces here",
            "talkdat://signin?code=<script>alert(1)</script>",
        ):
            with self.subTest(uri=uri):
                self.assertEqual(parse_signin_code(uri), "")



class TheBrowserLaunchReachesTheRunningAppTests(unittest.TestCase):
    """X-113: the receive half. The browser starts a SECOND copy of the exe
    with the URI in argv; that copy stashes and exits, and the primary's
    watcher claims the file. Before this wave nothing called the stash at
    all, so 'Activate this PC' opened an 'already running' message box and
    the code evaporated."""

    def setUp(self) -> None:
        self._home = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"TALK_DAT_HOME": self._home.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._home.cleanup)

    def test_stash_then_take_round_trips_and_clears(self) -> None:
        uri = "talkdat://signin?code=abcdefgh1234"
        stash_uri_for_primary(uri)
        self.assertEqual(take_stashed_uri(), uri)
        self.assertEqual(take_stashed_uri(), "", "a claimed stash must not deliver twice")

    def test_a_stashed_junk_uri_still_parses_as_no_code(self) -> None:
        stash_uri_for_primary("https://evil.example/?code=abcdefgh1234")
        self.assertEqual(parse_signin_code(take_stashed_uri()), "")

    def test_the_entrypoint_recognises_the_protocol_argument(self) -> None:
        # The same expression main() uses to spot a protocol launch, pinned
        # here so a rename or case change cannot quietly disconnect it.
        for argv, expected in (
            (["Talk Dat!.exe", "talkdat://signin?code=abcdefgh1234"], "talkdat://signin?code=abcdefgh1234"),
            (["Talk Dat!.exe", "TALKDAT://signin?code=abcdefgh1234"], "TALKDAT://signin?code=abcdefgh1234"),
            (["Talk Dat!.exe", "--status"], ""),
            (["Talk Dat!.exe"], ""),
        ):
            with self.subTest(argv=argv):
                found = next((arg for arg in argv[1:] if arg.lower().startswith("talkdat:")), "")
                self.assertEqual(found, expected)


if __name__ == "__main__":
    unittest.main()
