from __future__ import annotations

import hashlib
import json
import urllib.error
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from knight_flow import updater
from knight_flow.updater import (
    UpdateError,
    UpdateInfo,
    _latest_release_payload,
    download_installer,
    is_newer_version,
    launch_installer,
    verify_installer,
    verify_release_receipt,
)


def _info(installer: Path, checksum: Path) -> UpdateInfo:
    return UpdateInfo(
        current_version="0.0.1",
        latest_version="0.0.2",
        available=True,
        release_url="https://example.test/release",
        installer_url=installer.as_uri(),
        installer_name="Talk-Dat-Setup.exe",
        installer_size=installer.stat().st_size,
        installer_sha256="",
        checksum_url=checksum.as_uri(),
        published_at="",
        release_notes="",
    )


class _FakeResponse:
    """Minimal stand-in for urlopen's context manager."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class UpdaterTests(unittest.TestCase):
    def setUp(self) -> None:
        """Give this module its own data directory, so it cannot touch the real one.

        The Authenticode ratchet is per-INSTALL state kept in a file under
        app_dir(): once a machine has accepted a signed release it demands a
        signature forever after. That is the point of it, and it makes the real
        app_dir the worst possible thing for a test to reach.

        Two ways it already bit:

        1. A test mocked verify_authenticode_signature but not the REMEMBERING,
           so the real marker got written into the developer's own install --
           silently arming the ratchet on a machine no signed release has ever
           reached.
        2. With the marker present, two checksum tests that never mention
           signing started failing, because every update path on that machine
           had begun demanding a signature.

        Patching one function would fix one symptom. Redirecting app_dir fixes
        the class: nothing in this file can reach the user's install, whatever
        a future test forgets to mock.
        """
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.app_dir = Path(folder.name)

        isolated = patch("knight_flow.config.app_dir", return_value=self.app_dir)
        isolated.start()
        self.addCleanup(isolated.stop)

    def _updates_dir(self, root: Path) -> Path:
        path = root / "updates"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def test_download_requires_matching_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installer = root / "Talk-Dat-Setup.exe"
            installer.write_bytes(b"real installer bytes")
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()
            checksum = root / "SHA256SUMS.txt"
            checksum.write_text(f"{digest}  Talk-Dat-Setup.exe\n", encoding="ascii")

            with patch("knight_flow.updater.updates_dir", return_value=self._updates_dir(root)):
                downloaded = download_installer(_info(installer, checksum))

            self.assertTrue(downloaded.exists())
            self.assertEqual(hashlib.sha256(downloaded.read_bytes()).hexdigest(), digest)

    def test_download_rejects_bad_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installer = root / "Talk-Dat-Setup.exe"
            installer.write_bytes(b"tampered bytes")
            checksum = root / "SHA256SUMS.txt"
            checksum.write_text(f"{'0' * 64}  Talk-Dat-Setup.exe\n", encoding="ascii")

            with patch("knight_flow.updater.updates_dir", return_value=self._updates_dir(root)):
                with self.assertRaises(UpdateError):
                    download_installer(_info(installer, checksum))

    def test_download_rejects_wrong_published_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installer = root / "Talk-Dat-Setup.exe"
            installer.write_bytes(b"complete installer")
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()
            checksum = root / "SHA256SUMS.txt"
            checksum.write_text(f"{digest}  Talk-Dat-Setup.exe\n", encoding="ascii")
            info = _info(installer, checksum)
            wrong_size = UpdateInfo(**{**info.__dict__, "installer_size": installer.stat().st_size + 1})

            with patch("knight_flow.updater.updates_dir", return_value=self._updates_dir(root)):
                with self.assertRaisesRegex(UpdateError, "size verification"):
                    download_installer(wrong_size)

    def test_launch_rechecks_cached_installer_before_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / "Talk-Dat-Setup.exe"
            installer.write_bytes(b"verified installer")
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()
            installer.write_bytes(b"changed after download")

            with patch("knight_flow.updater.subprocess.Popen") as popen:
                with self.assertRaisesRegex(UpdateError, "SHA256 verification"):
                    launch_installer(installer, expected_sha256=digest)

            popen.assert_not_called()

    @unittest.skipIf(sys.platform == "darwin", "macOS opens the disk image; see the mac tests below")
    def test_launch_hands_off_verified_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / "Talk-Dat-Setup.exe"
            installer.write_bytes(b"verified installer")
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()

            with patch("knight_flow.updater.subprocess.Popen") as popen:
                launch_installer(
                    installer,
                    expected_sha256=digest,
                    expected_size=installer.stat().st_size,
                )

            popen.assert_called_once()

    def test_launch_surfaces_verification_io_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / "Talk-Dat-Setup.exe"
            installer.write_bytes(b"verified installer")
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()

            with patch("knight_flow.updater._file_sha256", side_effect=OSError("file locked")):
                with self.assertRaisesRegex(UpdateError, "Could not verify update installer"):
                    launch_installer(installer, expected_sha256=digest)

    @unittest.skipIf(sys.platform == "darwin", "Authenticode is a Windows notion; macOS asks Gatekeeper")
    def test_signed_receipt_requires_authenticode_at_the_final_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / "Talk-Dat-Setup.exe"
            installer.write_bytes(b"signed installer bytes")
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()

            with patch("knight_flow.updater.verify_authenticode_signature", return_value="CN=Talk Dat Publisher") as verify:
                verified = verify_installer(
                    installer,
                    expected_sha256=digest,
                    expected_size=installer.stat().st_size,
                    require_authenticode=True,
                )

            self.assertEqual(verified, digest)
            verify.assert_called_once_with(installer)

    def test_release_receipt_binds_installer_to_tag_commit_size_and_digest(self) -> None:
        digest = hashlib.sha256(b"installer").hexdigest()
        receipt = {
            "repository": "KNIGHT-AI-AV/talk-dat-releases",
            "tag": "v0.3.28-beta",
            "commit": "a" * 40,
            "artifact_signing_enabled": True,
            "assets": [
                {
                    "name": "Talk-Dat-Setup.exe",
                    "size_bytes": 9,
                    "sha256": digest,
                }
            ],
        }

        verified = verify_release_receipt(
            receipt,
            release_tag="v0.3.28-beta",
            installer_name="Talk-Dat-Setup.exe",
            installer_size=9,
            installer_sha256=digest,
        )

        self.assertEqual(verified, (digest, 9, "a" * 40, True))

    def test_release_receipt_rejects_asset_size_mismatch(self) -> None:
        digest = hashlib.sha256(b"installer").hexdigest()
        receipt = {
            "repository": "KNIGHT-AI-AV/talk-dat-releases",
            "tag": "v0.3.28-beta",
            "commit": "b" * 40,
            "assets": [{"name": "Talk-Dat-Setup.exe", "size_bytes": 8, "sha256": digest}],
        }

        with self.assertRaisesRegex(UpdateError, "size does not match"):
            verify_release_receipt(
                receipt,
                release_tag="v0.3.28-beta",
                installer_name="Talk-Dat-Setup.exe",
                installer_size=9,
                installer_sha256=digest,
            )

    def test_release_receipt_requires_a_json_boolean_to_enable_signature_policy(self) -> None:
        digest = hashlib.sha256(b"installer").hexdigest()
        receipt = {
            "repository": "KNIGHT-AI-AV/talk-dat-releases",
            "tag": "v0.3.28-beta",
            "commit": "c" * 40,
            "artifact_signing_enabled": "false",
            "assets": [{"name": "Talk-Dat-Setup.exe", "size_bytes": 9, "sha256": digest}],
        }

        verified = verify_release_receipt(
            receipt,
            release_tag="v0.3.28-beta",
            installer_name="Talk-Dat-Setup.exe",
            installer_size=9,
            installer_sha256=digest,
        )

        self.assertFalse(verified[3])

    def test_stable_release_is_newer_than_same_number_beta(self) -> None:
        self.assertTrue(is_newer_version("0.3.28", "0.3.28-beta"))
        self.assertFalse(is_newer_version("0.3.28-beta", "0.3.28"))

    def test_prerelease_order_handles_numeric_identifiers(self) -> None:
        self.assertTrue(is_newer_version("0.3.28-beta.10", "0.3.28-beta.2"))
        self.assertTrue(is_newer_version("0.3.28-rc.1", "0.3.28-beta.9"))

    def test_beta_feed_selects_highest_version_not_first_created(self) -> None:
        payload = [
            {"tag_name": "v0.3.26-beta", "draft": False},
            {"tag_name": "v0.3.28-beta", "draft": False},
            {"tag_name": "v0.3.27-beta", "draft": False},
        ]

        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                import json

                return json.dumps(payload).encode("utf-8")

        from knight_flow import official_build

        with patch("knight_flow.updater.urllib.request.urlopen", return_value=Response()), \
                patch.object(official_build, "OFFICIAL", True):
            selected = _latest_release_payload(1.0, "beta")

        self.assertEqual(selected["tag_name"], "v0.3.28-beta")


if __name__ == "__main__":
    unittest.main()


class StableChannelFallbackTests(unittest.TestCase):
    """The default channel resolved to a 404 on every single check.

    These describe an OFFICIAL build, which reads Knight's release feed; a build
    from source checks nothing (tests/test_official_build.py).

    GitHub's /releases/latest excludes prereleases and 404s when every release
    is one. Talk DAT! has published nothing but betas, so "Check for updates"
    failed for every user on the default channel -- the one feature that
    delivers every other fix could never deliver anything.
    """

    def setUp(self) -> None:
        from knight_flow import official_build

        patcher = mock.patch.object(official_build, "OFFICIAL", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_404_on_latest_falls_back_to_the_release_list(self) -> None:
        listed = [
            {"tag_name": "v0.4.12-beta", "draft": False, "assets": []},
            {"tag_name": "v0.4.14-beta", "draft": False, "assets": []},
        ]
        calls: list[str] = []

        def fake_urlopen(request, timeout=None):
            url = request.full_url
            calls.append(url)
            if url.endswith("/releases/latest"):
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return _FakeResponse(json.dumps(listed).encode("utf-8"))

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            payload = updater._latest_release_payload(5.0, channel="stable")

        self.assertEqual(payload["tag_name"], "v0.4.14-beta", "must pick the newest, not the first")
        self.assertTrue(any(url.endswith("/releases/latest") for url in calls))
        self.assertTrue(any("per_page" in url for url in calls), "it must actually fall back")

    def test_it_still_reports_honestly_when_nothing_is_published(self) -> None:
        def fake_urlopen(request, timeout=None):
            url = request.full_url
            if url.endswith("/releases/latest"):
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return _FakeResponse(b"[]")

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(updater.UpdateError):
                updater._latest_release_payload(5.0, channel="stable")

    def test_a_real_stable_release_is_still_preferred_when_one_exists(self) -> None:
        """The fallback must not fire when /releases/latest works, or promoting
        a build to stable would stop meaning anything."""
        def fake_urlopen(request, timeout=None):
            self.assertTrue(request.full_url.endswith("/releases/latest"))
            return _FakeResponse(json.dumps({"tag_name": "v1.0.0", "draft": False}).encode("utf-8"))

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            payload = updater._latest_release_payload(5.0, channel="stable")
        self.assertEqual(payload["tag_name"], "v1.0.0")


class TheUpdaterMustNotFetchTheWrongPlatformsInstallerTests(unittest.TestCase):
    """Auto-download is on by default, so getting this wrong is silent.

    The asset name was a single constant, `Talk-Dat-Setup.exe`. A Mac asked for
    it by name, found it in the release, and quietly pulled a 118MB Windows
    executable it could never run -- no prompt, because nothing about the flow
    knew it had picked something impossible.
    """

    def test_macos_ignores_the_windows_installer(self) -> None:
        from unittest.mock import patch

        from knight_flow import updater

        with patch.object(updater.sys, "platform", "darwin"):
            self.assertFalse(updater._is_installer_for_this_platform("Talk-Dat-Setup.exe"))
            self.assertFalse(
                updater._is_installer_for_this_platform("Talk-Dat-Windows-Portable.zip")
            )

    def test_macos_takes_the_disk_image_whatever_its_version(self) -> None:
        """The version is stamped into the name by build-mac.sh, so this cannot
        be an exact match the way the Windows name is."""
        from unittest.mock import patch

        from knight_flow import updater

        with patch.object(updater.sys, "platform", "darwin"):
            for name in ("Talk-DAT-0.4.39-beta.dmg", "Talk-DAT-1.0.0.dmg", "TALK-DAT-2.0.DMG"):
                with self.subTest(name=name):
                    self.assertTrue(updater._is_installer_for_this_platform(name))

    def test_windows_still_matches_only_its_exact_name(self) -> None:
        from unittest.mock import patch

        from knight_flow import updater

        with patch.object(updater.sys, "platform", "win32"):
            self.assertTrue(updater._is_installer_for_this_platform("Talk-Dat-Setup.exe"))
            self.assertFalse(updater._is_installer_for_this_platform("Talk-DAT-0.4.39-beta.dmg"))
            self.assertFalse(updater._is_installer_for_this_platform("Talk-Dat-Setup-old.exe"))

    def test_neither_platform_matches_the_side_assets(self) -> None:
        from unittest.mock import patch

        from knight_flow import updater

        for platform in ("darwin", "win32"):
            with patch.object(updater.sys, "platform", platform):
                for name in ("SHA256SUMS.txt", "RELEASE-RECEIPT.json", ""):
                    with self.subTest(platform=platform, name=name):
                        self.assertFalse(updater._is_installer_for_this_platform(name))


@unittest.skipUnless(sys.platform == "darwin", "macOS update handoff")
class TheMacUpdateHandoffTests(unittest.TestCase):
    """A .dmg is a filesystem image, not a program.

    The Windows path executes the downloaded installer. Doing that to a disk
    image produced "Could not launch installer: [Errno 13] Permission denied"
    after a full multi-hundred-megabyte download.
    """

    def test_the_disk_image_is_opened_not_executed(self) -> None:
        from unittest.mock import patch

        from knight_flow.updater import launch_installer

        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "Talk-DAT-9.9.9.dmg"
            image.write_bytes(b"disk image bytes")
            digest = hashlib.sha256(image.read_bytes()).hexdigest()

            with patch("knight_flow.updater.subprocess.run") as run:
                run.return_value.returncode = 0
                launch_installer(image, expected_sha256=digest,
                                 expected_size=image.stat().st_size)

            argv = run.call_args.args[0]
            self.assertEqual(argv[0], "/usr/bin/open")
            self.assertEqual(argv[1], str(image))

    def test_a_failure_to_open_is_reported(self) -> None:
        from unittest.mock import patch

        from knight_flow.updater import UpdateError, launch_installer

        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "Talk-DAT-9.9.9.dmg"
            image.write_bytes(b"disk image bytes")
            digest = hashlib.sha256(image.read_bytes()).hexdigest()

            with patch("knight_flow.updater.subprocess.run") as run:
                run.return_value.returncode = 1
                run.return_value.stderr = b"no mountable file systems"
                with self.assertRaisesRegex(UpdateError, "disk image"):
                    launch_installer(image, expected_sha256=digest)

    def test_a_signed_release_is_checked_against_gatekeeper(self) -> None:
        """require_authenticode used to raise "can only be verified on Windows"
        here, which aborted the download -- so a signed release could never be
        installed on a Mac at all. Skipping the check instead would have been
        worse: it is the only thing proving the image is the publisher's."""
        from unittest.mock import patch

        from knight_flow.updater import verify_installer

        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "Talk-DAT-9.9.9.dmg"
            image.write_bytes(b"signed image bytes")
            digest = hashlib.sha256(image.read_bytes()).hexdigest()

            with patch("knight_flow.updater.verify_gatekeeper_acceptance",
                       return_value="accepted") as verify:
                result = verify_installer(image, expected_sha256=digest,
                                          expected_size=image.stat().st_size,
                                          require_authenticode=True)

            self.assertEqual(result, digest)
            verify.assert_called_once_with(image)

    def test_gatekeeper_rejection_refuses_the_update(self) -> None:
        from unittest.mock import patch

        from knight_flow.updater import UpdateError, verify_gatekeeper_acceptance

        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "Talk-DAT-9.9.9.dmg"
            image.write_bytes(b"unsigned image")
            with patch("knight_flow.updater.subprocess.run") as run:
                run.return_value.returncode = 3
                run.return_value.stderr = b"rejected"
                with self.assertRaisesRegex(UpdateError, "Gatekeeper"):
                    verify_gatekeeper_acceptance(image)
