"""0.4.173 (f): the updater offers only a release this machine can install.

Read from the code on 2026-10-16: check_for_update took the release GitHub marks Latest (or, on the beta channel, the
newest by version) and set available = newer, whether or not that release carried an installer for this platform.
So a Mac on 0.4.170 was offered 0.4.172, a Windows-only release with no disk image ("update available", nothing to
install), and a Mac-only release would have made every Windows client's check fail outright: its receipt names no
Talk-Dat-Setup.exe. Now a release without this platform's installer is passed over for the newest release that has
one, and if none is newer than this build, the answer is "up to date". The stable and beta channels take the same path.
"""

from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest import mock

from knight_flow import official_build, updater

REPO = "KNIGHT-AI-AV/talk-dat-releases"
API = f"https://api.github.com/repos/{REPO}"
EXE = "Talk-Dat-Setup.exe"


def digest(text: str) -> str:
    return (text * 64)[:64]


def release(version: str, *names: str) -> dict:
    tag = f"v{version}"
    files = {name: (1000 + i, digest("abcdef0123456789"[i % 16])) for i, name in enumerate(names)}
    assets = [{"name": name, "browser_download_url": f"https://dl.test/{tag}/{name}", "size": size,
               "digest": f"sha256:{sha}"} for name, (size, sha) in files.items()]
    assets.append({"name": "RELEASE-RECEIPT.json", "browser_download_url": f"https://dl.test/{tag}/receipt", "size": 9})
    assets.append({"name": "SHA256SUMS.txt", "browser_download_url": f"https://dl.test/{tag}/sums", "size": 9})
    receipt = {"schema_version": 1, "repository": REPO, "tag": tag, "commit": "a" * 40,
               "assets": [{"name": name, "size_bytes": size, "sha256": sha} for name, (size, sha) in files.items()]}
    sums = "".join(f"{sha}  {name}\n" for name, (size, sha) in files.items())
    return {"tag_name": tag, "draft": False, "prerelease": False, "body": f"## {version}\n- notes",
            "html_url": f"https://github.com/{REPO}/releases/tag/{tag}", "published_at": "2026-10-16T00:00:00Z",
            "assets": assets, "_receipt": receipt, "_sums": sums}


class FakeGitHub:
    def __init__(self, releases: list, latest: dict) -> None:
        self.releases, self.latest = releases, latest

    def urlopen(self, request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url == f"{API}/releases/latest":
            return self.answer(self.public(self.latest))
        if url.startswith(f"{API}/releases?"):
            return self.answer([self.public(r) for r in self.releases])
        for item in self.releases:
            tag = item["tag_name"]
            if url == f"https://dl.test/{tag}/receipt":
                return self.answer(item["_receipt"])
            if url == f"https://dl.test/{tag}/sums":
                return io.BytesIO(item["_sums"].encode("utf-8"))
        raise urllib.error.HTTPError(url, 404, "not found", None, None)

    @staticmethod
    def public(item: dict) -> dict:
        return {k: v for k, v in item.items() if not k.startswith("_")}

    @staticmethod
    def answer(payload) -> io.BytesIO:
        return io.BytesIO(json.dumps(payload).encode("utf-8"))


class TheUpdaterOffersOnlyWhatThisPlatformCanInstallTests(unittest.TestCase):
    def check(self, platform: str, current: str, releases: list, latest: dict, channel: str = "stable"):
        github = FakeGitHub(releases, latest)
        with mock.patch.object(updater.sys, "platform", platform), \
                mock.patch.object(official_build, "update_repository", return_value=REPO), \
                mock.patch.object(updater.urllib.request, "urlopen", side_effect=github.urlopen):
            try:
                return updater.check_for_update(current, timeout=1.0, channel=channel)
            except Exception as error:  # any crash is this test's failure, never an error that hides it
                self.fail(f"the check failed instead of choosing an installable release: {type(error).__name__}: {error}")

    def windows_only_latest(self) -> tuple:
        r172 = release("0.4.172-beta", EXE, "Talk-Dat-Windows-Portable.zip")
        r171 = release("0.4.171-beta", EXE, "Talk-Dat-Windows-Portable.zip")
        r170 = release("0.4.170-beta", "Talk-DAT-0.4.170-beta.dmg", EXE)
        return [r172, r171, r170], r172

    def mac_only_latest(self) -> tuple:
        r173 = release("0.4.173-beta", "Talk-DAT-0.4.173-beta.dmg")
        r172 = release("0.4.172-beta", EXE, "Talk-Dat-Windows-Portable.zip")
        return [r173, r172], r173

    def test_a_mac_facing_a_windows_only_latest_is_up_to_date(self) -> None:
        for channel in ("stable", "beta"):
            with self.subTest(channel=channel):
                releases, latest = self.windows_only_latest()
                info = self.check("darwin", "0.4.170-beta", releases, latest, channel)
                self.assertFalse(info.available, f"a Mac was offered {info.latest_version} with nothing to install")
                self.assertEqual(info.latest_version, "0.4.170-beta", "the newest release with a disk image is this one")

    def test_a_windows_client_facing_a_mac_only_latest_takes_the_newest_setup(self) -> None:
        for channel in ("stable", "beta"):
            with self.subTest(channel=channel):
                releases, latest = self.mac_only_latest()
                info = self.check("win32", "0.4.171-beta", releases, latest, channel)
                self.assertTrue(info.available)
                self.assertEqual(info.latest_version, "0.4.172-beta")
                self.assertEqual(info.installer_url, f"https://dl.test/v0.4.172-beta/{EXE}")
                self.assertTrue(info.receipt_verified, "the chosen release's receipt was not checked")

    def test_a_windows_client_already_on_the_newest_setup_is_up_to_date(self) -> None:
        releases, latest = self.mac_only_latest()
        info = self.check("win32", "0.4.172-beta", releases, latest)
        self.assertFalse(info.available)

    def test_no_release_with_this_platforms_installer_is_up_to_date(self) -> None:
        only_windows = [release("0.4.172-beta", EXE), release("0.4.171-beta", EXE)]
        info = self.check("darwin", "0.4.170-beta", only_windows, only_windows[0])
        self.assertFalse(info.available)
        self.assertEqual(info.installer_url, "")

    def test_the_stable_channel_never_falls_back_to_a_prerelease(self) -> None:
        prerelease = release("0.4.173-beta", EXE)
        prerelease["prerelease"] = True
        releases = [release("0.4.174-beta", "Talk-DAT-0.4.174-beta.dmg"), prerelease, release("0.4.172-beta", EXE)]
        info = self.check("win32", "0.4.171-beta", releases, releases[0])
        self.assertEqual((info.available, info.latest_version), (True, "0.4.172-beta"))

    def test_a_latest_with_this_platforms_installer_is_taken_as_before(self) -> None:
        releases, latest = self.windows_only_latest()
        info = self.check("win32", "0.4.171-beta", releases, latest)
        self.assertEqual((info.available, info.latest_version), (True, "0.4.172-beta"))
        self.assertEqual(info.installer_url, f"https://dl.test/v0.4.172-beta/{EXE}")
        mac_releases = [release("0.4.173-beta", "Talk-DAT-0.4.173-beta.dmg", EXE)]
        info = self.check("darwin", "0.4.170-beta", mac_releases, mac_releases[0])
        self.assertEqual(info.installer_url, "https://dl.test/v0.4.173-beta/Talk-DAT-0.4.173-beta.dmg")


if __name__ == "__main__":
    unittest.main()
