from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from knight_flow import mac_support

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "build-mac.sh"


class TheBuildSignsWithSomethingStableTests(unittest.TestCase):
    """An ad-hoc signature costs the owner every permission on every build.

    macOS binds Accessibility, Microphone and Input Monitoring to an app's
    designated requirement. Ad-hoc signing makes that requirement a hash of the
    build itself:

        designated => cdhash H"b149f528..."

    so a rebuild is a different app to macOS and every grant is cleared. That
    happened around thirty times during this port, each one a dialog the owner
    of the machine had to answer by hand. Signing with any stable certificate
    replaces it with an identifier-and-certificate requirement that is the same
    across builds.
    """

    def script(self) -> str:
        return BUILD_SCRIPT.read_text(encoding="utf-8")

    def test_the_build_creates_a_local_identity_when_there_is_no_developer_id(self) -> None:
        script = self.script()
        self.assertIn("ensure_local_identity", script)
        self.assertIn("sign_with_local_identity", script)

    def test_signing_pins_the_bundle_identifier(self) -> None:
        """The requirement is identifier AND certificate; both have to be fixed.

        PyInstaller names the main executable "Talk DAT!", and codesign would
        otherwise derive the identifier from that filename rather than from the
        bundle id, which is not what the installed app is known by.
        """
        script = self.script()
        block = script[script.index("sign_with_local_identity() {"):][:2000]
        self.assertIn("--identifier", block)
        self.assertIn("BUNDLE_ID", block)

    def test_a_developer_id_takes_precedence(self) -> None:
        """The local identity is a stopgap, never something to sign a release with."""
        self.assertIn('[ "$do_sign" -eq 1 ] && use_local_id=0', self.script())

    def test_the_keychain_password_is_generated_not_the_users(self) -> None:
        """Nothing in this mechanism may touch the login keychain or its password.

        The owner has typed that password enough times because of this build.
        """
        script = self.script()
        block = script[script.index("ensure_local_identity() {"):][:2600]
        self.assertIn("openssl rand", block)
        self.assertNotIn("login.keychain", block)

    def test_codesign_is_pre_authorised_so_it_never_shows_a_prompt(self) -> None:
        """Without set-key-partition-list, every signature raises a GUI dialog.

        That would reintroduce the exact interruption the mechanism removes,
        once per build instead of once per permission.
        """
        self.assertIn("set-key-partition-list", self.script())

    def test_the_probe_launch_happens_after_signing(self) -> None:
        """Probing the unsigned bundle proves nothing about the signed one.

        Re-signing is itself a step that can break a launch, and the signed
        bundle is what gets installed.
        """
        script = self.script()
        self.assertLess(
            script.index("sign_with_local_identity()"),
            script.index('echo "==> Probe launch"'),
            "the probe must run against the bundle that will be installed",
        )

    def test_the_search_list_is_put_back(self) -> None:
        """A build script that permanently rewrites a developer's keychain
        search list has changed their machine, not built an app."""
        script = self.script()
        block = script[script.index("sign_with_local_identity() {"):][:2000]
        self.assertGreaterEqual(block.count("list-keychains -d user -s"), 2)


class TheInstalledAppKeepsItsPermissionsTests(unittest.TestCase):
    """The property that matters, read off the installed app itself."""

    APP = Path("/Applications/Talk DAT!.app")

    @unittest.skipUnless(mac_support.IS_MAC, "macOS only")
    def test_the_installed_bundle_is_not_cdhash_bound(self) -> None:
        if not self.APP.exists():
            self.skipTest("Talk DAT! is not installed")
        result = subprocess.run(
            ["codesign", "-d", "-r-", str(self.APP)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        requirement = (result.stdout + result.stderr)
        designated = [line for line in requirement.splitlines() if "designated" in line]
        self.assertTrue(designated, f"no designated requirement reported: {requirement!r}")
        self.assertNotIn(
            "cdhash",
            designated[0],
            "the installed app is ad-hoc signed, so the next rebuild clears every "
            "macOS permission again",
        )


if __name__ == "__main__":
    unittest.main()
