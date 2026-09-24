"""Release notes reach every user's screen, so they are held to public-safe.

Two halves. The digest: a user updating across several versions sees a
bulleted summary of each skipped version before any detail, so days of work
never read as one small change. The safety: everything the updater can show
comes from CHANGELOG.md, so the whole file is scanned for the things that must
never ship in it -- keys, internal hostnames, infrastructure names. Sensitive
work gets described vaguely there or not at all; the specifics live in
docs/CODEX_LOG.md, which does not ship.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

from knight_flow.updater import _notes_spanning_versions
from knight_flow.version import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)
# chr(10) + "## ": the next section heading, without writing an escape.
SECTION_BREAK = chr(10) + "## "


def release(tag: str, body: str) -> dict:
    return {"tag_name": tag, "body": body}


class MultiVersionDigestTests(unittest.TestCase):
    RELEASES = [
        release("v0.4.31-beta", "### Local Forever is $29, once\ndetail a"),
        release("v0.4.32-beta", "### Crisp on every display\ndetail b\n### Never lose what you said\ndetail c"),
        release("v0.4.33-beta", "### It writes data the way you would\ndetail d"),
    ]

    def setUp(self) -> None:
        # The digest is fetched from Knight's release feed, which only an
        # OFFICIAL build reads (tests/test_official_build.py).
        from knight_flow import official_build

        patcher = mock.patch.object(official_build, "OFFICIAL", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def notes(self, current: str, latest: str) -> str:
        with mock.patch("knight_flow.updater.urllib.request.urlopen") as opener:
            import io, json

            body = json.dumps(self.RELEASES).encode()
            response = io.BytesIO(body)
            response.__enter__ = lambda *a: response
            response.__exit__ = lambda *a: False
            opener.return_value = response
            return _notes_spanning_versions(current, latest, self.RELEASES[-1]["body"], 5.0)

    def test_a_multi_version_jump_gets_bullets_per_version_before_details(self) -> None:
        notes = self.notes("0.4.30-beta", "0.4.33-beta")
        self.assertIn("New since 0.4.30-beta - 3 updates.", notes)
        # Every skipped version's headlines, as bullets, newest first.
        self.assertIn("**0.4.33-beta**", notes)
        self.assertIn("- It writes data the way you would", notes)
        self.assertIn("- Crisp on every display", notes)
        self.assertIn("- Local Forever is $29, once", notes)
        self.assertLess(
            notes.index("- It writes data the way you would"),
            notes.index("detail d"),
            "the digest must come before any detail",
        )
        self.assertLess(
            notes.index("**0.4.33-beta**"),
            notes.index("**0.4.32-beta**"),
            "newest first",
        )

    def test_a_single_version_jump_stays_the_plain_body(self) -> None:
        notes = self.notes("0.4.32-beta", "0.4.33-beta")
        self.assertEqual(self.RELEASES[-1]["body"], notes)

    def test_a_failed_fetch_falls_back_to_the_latest_body(self) -> None:
        with mock.patch("knight_flow.updater.urllib.request.urlopen", side_effect=OSError("no network")):
            notes = _notes_spanning_versions("0.4.30-beta", "0.4.33-beta", "latest body", 5.0)
        self.assertEqual("latest body", notes)


class ChangelogIsPublicSafeTests(unittest.TestCase):
    """The changelog ships to strangers. These patterns must never be in it."""

    FORBIDDEN = (
        # Credentials of any shape.
        (re.compile(r"sk_(live|test)_[A-Za-z0-9]"), "a Stripe key"),
        (re.compile(r"sk-or-v1-[A-Za-z0-9]"), "an OpenRouter key"),
        (re.compile(r"AIza[0-9A-Za-z_-]{10}"), "a Google API key"),
        (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"), "a private key"),
        # Infrastructure that is nobody's business.
        (re.compile(r"knight-fleet-01|cli-proxy-api|007-fleet-net", re.IGNORECASE), "fleet infrastructure names"),
        (re.compile(r"knight-postgres|navorb-", re.IGNORECASE), "internal project infrastructure"),
        (re.compile(r"\bIAP\b|tunnel-through-iap"), "internal access tooling"),
    )

    def test_the_shipped_changelog_names_no_secrets_or_infrastructure(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8-sig")
        for pattern, what in self.FORBIDDEN:
            self.assertIsNone(
                pattern.search(changelog),
                f"CHANGELOG.md contains {what}; describe it vaguely or move it to docs/CODEX_LOG.md",
            )


class HouseStyleTests(unittest.TestCase):
    """The section about to be published is held to the house style.

    Mayowa's rule for customer copy is no em dashes, and a CHANGELOG section is
    customer copy twice over: publish_release.py posts it verbatim as the GitHub
    release body, and the installer ships the file so the What's New tab can show
    the running version's section with no network.

    Only the CURRENT version's section is checked, deliberately. The 81 em dashes
    in older sections were published as release bodies at the time, and the
    updater shows those bodies by fetching them from GitHub, not by reading this
    file. Rewriting them here would change nothing any user will ever see, while
    making the file disagree with what was actually published, which is the record
    of what customers were told. So history is left alone and the rule is enforced
    where it still has an effect: the next thing to ship.
    """

    def test_the_section_about_to_ship_has_no_em_dashes(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8-sig")
        marker = f"## {APP_VERSION}"
        self.assertIn(marker, changelog, f"CHANGELOG.md has no section for {APP_VERSION}")
        section = changelog.split(marker, 1)[1].split(SECTION_BREAK, 1)[0]
        self.assertNotIn(
            EM_DASH,
            section,
            f"the {APP_VERSION} section uses an em dash; customer copy takes a comma, "
            "a colon or a full stop instead",
        )

    def test_no_section_has_an_em_dash(self) -> None:
        """X-511: the WHOLE file, not just the section about to ship.

        Scoping this to the current version grandfathered 81 em dashes across
        the history, and history is not private: CHANGELOG.md is bundled into
        the app, and the updater builds a digest spanning every version
        somebody skipped, so old sections reach screens too.

        All 81 are now commas. The rule was never "the newest release notes
        take a comma"; it is that customer copy does.
        """
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8-sig")
        self.assertNotIn(
            EM_DASH,
            changelog,
            "an em dash is back in CHANGELOG.md; it ships inside the app and "
            "the updater shows old sections to anyone who skipped a version",
        )


if __name__ == "__main__":
    unittest.main()
