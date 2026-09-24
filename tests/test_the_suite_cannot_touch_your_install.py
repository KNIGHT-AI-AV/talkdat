"""A test run must not be able to change the machine it runs on.

This exists because the suite broke that rule and nothing noticed for a while.
X-233 added an Authenticode "ratchet": a marker file under app_dir() recording
that this install has accepted a properly signed update, after which it refuses
an unsigned one forever. A test mocked the signature check but not the writing
of that marker, so the real file landed in the developer's own Talk DAT!
directory.

The run that did it passed. The damage showed up afterwards, in two tests about
CHECKSUMS that had never mentioned signing -- because every update path on that
machine had quietly begun demanding a signature. The failure was real, the
diagnosis pointed at the wrong file, and the tempting fix (delete the marker)
would have left the cause in place to happen again.

So the floor is set in tests/__init__.py, and this asserts the floor is really
there. It is not a test of the updater. It is a test of the test suite.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from knight_flow.config import app_dir


class TheSuiteWritesToScratchNotToYourRealInstallTests(unittest.TestCase):
    def test_the_data_directory_is_redirected(self) -> None:
        self.assertTrue(
            os.environ.get("TALK_DAT_HOME"),
            "tests/__init__.py did not run, so every test is writing to the real install",
        )

    def test_it_is_not_the_real_one(self) -> None:
        roaming = os.environ.get("APPDATA")
        if not roaming:
            self.skipTest("no APPDATA on this platform")
        real = (Path(roaming) / "TalkDat").resolve()
        here = app_dir().resolve()
        self.assertNotEqual(here, real)
        self.assertFalse(
            real == here or real in here.parents,
            f"tests are writing inside the real install: {here}",
        )

    def test_the_ratchet_marker_would_land_in_scratch(self) -> None:
        """The specific file that caused this, checked by name.

        Asserting on app_dir() alone would pass even if the updater grew a
        second path to the real directory. This follows the actual write."""
        from knight_flow import updater

        # Self-healing: a marker left behind by a crashed or previously buggy
        # run lives in SCRATCH (that is the point of this file), so clearing
        # it here weakens nothing -- the assertion below is about WHERE the
        # write lands, not about historical state.
        (app_dir() / updater._SIGNING_SEEN_NAME).unlink(missing_ok=True)

        with self.assertRaises(FileNotFoundError):
            # Nothing has legitimately armed the ratchet in a test run.
            (app_dir() / updater._SIGNING_SEEN_NAME).read_text(encoding="utf-8")

        updater.remember_signing_was_seen()
        landed = app_dir() / updater._SIGNING_SEEN_NAME
        self.addCleanup(landed.unlink, True)
        self.assertTrue(landed.exists())

        roaming = os.environ.get("APPDATA")
        if roaming:
            self.assertFalse(
                (Path(roaming) / "TalkDat" / updater._SIGNING_SEEN_NAME).exists(),
                "remember_signing_was_seen() reached the real install anyway",
            )
