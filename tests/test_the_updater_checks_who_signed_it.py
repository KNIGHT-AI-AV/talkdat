"""X-233: a valid signature is not the same as OUR signature.

`verify_authenticode_signature` asked Windows whether the installer carried a
valid Authenticode chain, read the publisher subject out of the answer, and
then RETURNED IT WITHOUT COMPARING IT TO ANYTHING. An attacker who can serve
an installer can sign it with their own certificate; Windows reports Valid,
because it genuinely is valid, and the gate opens on a file signed by somebody
else entirely.

The value needed was already in the function. It was fetched and discarded.

The second half is subtler. Whether the check runs at all came from
`artifact_signing_enabled` in the release RECEIPT, which is published beside
the very file being verified, so the artifact decided whether the artifact got
checked. That is a deliberate rollout state and docs/RELEASE_INTEGRITY.md says
so plainly, but the moment signing goes live it becomes a switch an attacker
can flip off. Enforcement now RATCHETS: once an install has accepted a signed
update it refuses an unsigned one forever. A receipt may raise the bar and can
never lower it.

WHAT THIS CANNOT PROVE: that Windows verifies the chain correctly, or that the
certificate is not stolen. It proves the app checks the name on it, which it
did not do before.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from knight_flow.updater import EXPECTED_PUBLISHER, publisher_is_ours

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "knight_flow" / "updater.py"


class OnlyOurOwnSignatureIsAcceptedTests(unittest.TestCase):
    def test_a_real_windows_subject_for_this_company_passes(self) -> None:
        """The shape Windows actually reports, not a simplified one."""
        self.assertTrue(
            publisher_is_ours("CN=Knight AI+AV LLC, O=Knight AI+AV LLC, L=New York, S=NY, C=US")
        )

    def test_a_validly_signed_installer_from_anyone_else_is_refused(self) -> None:
        """The whole point. Each of these carries a perfectly valid signature."""
        for subject in (
            "CN=Evil Corp, O=Evil Corp, C=XX",
            "CN=Microsoft Corporation, O=Microsoft Corporation, C=US",
            "CN=Knight Software Ltd, O=Knight Software Ltd, C=GB",
            "",
        ):
            with self.subTest(subject=subject or "(no subject)"):
                self.assertFalse(publisher_is_ours(subject))

    def test_it_survives_a_certificate_reissue(self) -> None:
        """Matched on the organisation, not the full distinguished name: a DN
        carries a serial and locality that change on renewal, and a check that
        breaks on renewal is a check somebody deletes rather than fixes."""
        self.assertTrue(publisher_is_ours("CN=Knight AI+AV LLC, O=Knight AI+AV LLC, C=US, serialNumber=99"))
        self.assertTrue(publisher_is_ours("cn=knight ai+av llc"))

    def test_the_verifier_actually_calls_it(self) -> None:
        """A predicate nothing consults is the same as no predicate, which is
        precisely the state this replaced: the subject was already being read."""
        source = UPDATER.read_text(encoding="utf-8")
        start = source.index("def verify_authenticode_signature")
        body = source[start:source.index("\ndef ", start + 10)]
        self.assertIn("publisher_is_ours(subject)", body)
        self.assertIn("raise UpdateError", body)

    def test_the_expected_publisher_is_this_company(self) -> None:
        self.assertEqual(EXPECTED_PUBLISHER, "Knight AI+AV")


class EnforcementRatchetsAndNeverRelaxesTests(unittest.TestCase):
    """The receipt may raise the bar. It must not be able to lower it."""

    def test_the_check_is_not_gated_on_the_receipt_alone(self) -> None:
        """A receipt saying "no signature needed" must not be the last word
        once this install has already accepted a signed release."""
        from unittest.mock import patch

        from knight_flow.updater import authenticode_required

        with patch("knight_flow.updater.signing_has_been_seen", return_value=True):
            self.assertTrue(authenticode_required(False))  # receipt says no; ratchet says yes
            self.assertTrue(authenticode_required(True))
        with patch("knight_flow.updater.signing_has_been_seen", return_value=False):
            self.assertTrue(authenticode_required(True))   # receipt may still RAISE it
            self.assertFalse(authenticode_required(False))

    def test_both_entry_points_consult_the_ratchet(self) -> None:
        """Downloading is not the only way an installer reaches a user. One
        fetched before signing went live is still sitting on disk, and running
        it is the moment that actually matters -- so the launch path has to ask
        the same question, not inherit an answer from whoever called it."""
        source = UPDATER.read_text(encoding="utf-8")
        for entry in ("def download_installer", "def launch_installer"):
            start = source.index(entry)
            body = source[start:source.index('\ndef ', start + 10)]
            self.assertIn(
                "authenticode_required(",
                body,
                f"{entry} can be handed a bare boolean and never checks the ratchet",
            )

    def test_verifying_bytes_does_not_secretly_read_this_machine(self) -> None:
        """The bug this replaced: verify_installer's signature promised it
        would check a signature only when asked, then ORed in a file on disk.
        The same call then meant different things on different machines -- and
        two checksum tests that never mentioned signing began failing on any
        machine that happened to carry the marker.

        Mechanism takes arguments. Policy reads the world. Not both."""
        import hashlib
        import tempfile
        from unittest.mock import patch

        from knight_flow.updater import verify_installer

        with tempfile.TemporaryDirectory() as folder:
            installer = Path(folder) / "TalkDat-Setup.exe"
            installer.write_bytes(b"not really an installer")
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()

            # The ratchet is fully engaged, and it must not reach in here.
            with patch("knight_flow.updater.signing_has_been_seen", return_value=True):
                with patch(
                    "knight_flow.updater.verify_authenticode_signature",
                    side_effect=AssertionError("verify_installer reached for global state"),
                ):
                    self.assertEqual(
                        verify_installer(installer, expected_sha256=digest).lower(),
                        digest.lower(),
                    )

    def test_accepting_a_signed_update_is_remembered(self) -> None:
        """Otherwise the ratchet has no teeth on the second update."""
        import hashlib
        import tempfile
        from unittest.mock import patch

        from knight_flow.updater import verify_installer

        with tempfile.TemporaryDirectory() as folder:
            installer = Path(folder) / "TalkDat-Setup.exe"
            installer.write_bytes(b"signed, allegedly")
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()

            # The ratchet is Windows doctrine; on macOS verify_installer routes
            # to Gatekeeper before the mocked verifier is reachable, so the
            # platform is pinned for the duration of the call.
            with patch("sys.platform", "win32"):
                with patch("knight_flow.updater.verify_authenticode_signature", return_value="CN=Knight AI+AV LLC"):
                    with patch("knight_flow.updater.remember_signing_was_seen") as remembered:
                        verify_installer(installer, expected_sha256=digest, require_authenticode=True)
            remembered.assert_called_once()

    def test_the_memory_is_not_a_config_key(self) -> None:
        """It has to survive "start over". A factory reset is about the user's
        data, not about lowering a security guarantee this install already met."""
        source = UPDATER.read_text(encoding="utf-8")
        self.assertIn('_SIGNING_SEEN_NAME = ".authenticode-seen"', source)
        self.assertNotIn('config["updates"]["authenticode', source)

    def test_an_unreadable_data_directory_does_not_brick_updates(self) -> None:
        """Fails OPEN, and only here: someone who has never seen a signed
        release must still be able to update. The signature check itself
        continues to fail closed."""
        from unittest.mock import patch

        with patch("knight_flow.config.app_dir", side_effect=OSError("gone")):
            from knight_flow.updater import signing_has_been_seen

            self.assertFalse(signing_has_been_seen())


if __name__ == "__main__":
    unittest.main()
