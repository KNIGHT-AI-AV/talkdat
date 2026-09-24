"""Smart formatting sets itself up on a Mac too, and only when asked.

A Mac had no scripted engine install, so the setup card hid itself there and
Settings could only open Ollama's download page. mac_ollama_install is the
Mac's installer now. These tests pin what makes it safe:

- it runs only from Set up smart formatting (a click): never from a snapshot,
  a status poll, Check again, the download page, Not now or an import;
- Homebrew, when this user can run it, installs the official cask with no
  terminal to answer from; otherwise Ollama's own download is installed only
  after codesign, spctl, the pinned team and the signed requirement all pass,
  into ~/Applications, then started with open -a;
- a refused signature installs nothing and says why in plain words;
- Apple silicon counts as a capable GPU, and the 4B is a Mac's model only with
  16 GB of memory or more, everywhere that choice is made;
- the setup card shows on a Mac again.

No test reaches the network, runs a real command or touches the real home
folder: the downloader, the command runner and the home folder are fakes, and
urlopen is a tripwire wherever the real downloader is not the thing tested.
"""
from __future__ import annotations

import ast
import copy
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from knight_flow import llm, mac_support, smart_formatting
from knight_flow import mac_ollama_install as mi
from knight_flow.config import DEFAULT_CONFIG, LOCAL_FORMATTER_MODEL
from knight_flow.local_finish import LOCAL_GPU_MODEL, MachineSpeed
from knight_flow.smart_formatting import SmartFormattingSetup
from knight_flow.web_shell.setup_workspace import SetupWorkspace

ROOT = Path(__file__).resolve().parents[1]
TB = 10**12
TEAM = "3MU9H2V9Y9"


def no_network(*_args, **_kwargs):
    raise AssertionError("a Mac smart formatting test reached the network")


def done(returncode=0, stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


def ollama_zip(path, *, entries=()):
    """A zip shaped like Ollama-darwin.zip: Ollama.app with its command line tool."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Ollama.app/Contents/Info.plist", "<plist/>")
        archive.writestr("Ollama.app/Contents/MacOS/Ollama", "app")
        archive.writestr("Ollama.app/Contents/Resources/ollama", "cli")
        for name, data, symlink in entries:
            info = zipfile.ZipInfo(name)
            if symlink:
                info.external_attr = 0o120777 << 16
            archive.writestr(info, data)


class FakeMac:
    """The commands the installer runs, answered the way a Mac would, and recorded."""

    def __init__(self, *, verify=0, assess=0, team=TEAM, requirement=0, open_rc=0, ditto=0, brew=0, on_brew=None):
        self.verify, self.assess, self.team, self.requirement = verify, assess, team, requirement
        self.open_rc, self.ditto, self.brew, self.on_brew = open_rc, ditto, brew, on_brew
        self.calls: list[list[str]] = []
        self.envs: list[dict | None] = []

    def names(self):
        """Each call as the tool and the flag that tells the checks apart."""
        out = []
        for args in self.calls:
            if args[0] == mi.CODESIGN:
                out.append("codesign " + ("-R" if any(a.startswith("-R=") for a in args) else "-dv" if "-dv" in args else "--verify"))
            elif args[0] in (mi.DITTO, mi.SPCTL, mi.OPEN):
                out.append(Path(args[0]).name + (" -x" if args[0] == mi.DITTO and "-x" in args else ""))
            else:
                out.append("brew")
        return out

    def __call__(self, args, *, timeout, env=None):
        args = list(args)
        self.calls.append(args)
        self.envs.append(env)
        tool = args[0]
        if tool == mi.DITTO and "-x" in args:
            if self.ditto == 0:
                with zipfile.ZipFile(args[3]) as archive:
                    archive.extractall(args[4])
            return done(self.ditto)
        if tool == mi.DITTO:
            shutil.copytree(args[1], args[2], symlinks=True)
            return done(0)
        if tool == mi.CODESIGN and any(a.startswith("-R=") for a in args):
            return done(self.requirement)
        if tool == mi.CODESIGN and "-dv" in args:
            return done(0, f"Executable={args[-1]}/Contents/MacOS/Ollama\nIdentifier=com.electron.ollama\n"
                           f"Authority=Developer ID Application: Ollama Inc ({self.team})\nTeamIdentifier={self.team}\n")
        if tool == mi.CODESIGN:
            return done(self.verify, f"{args[-1]}: valid on disk")
        if tool == mi.SPCTL:
            return done(self.assess, f"{args[-1]}: accepted\nsource=Notarized Developer ID")
        if tool == mi.OPEN:
            return done(self.open_rc)
        if args[1:] == ["install", "--cask", mi.HOMEBREW_CASK]:
            if self.on_brew:
                self.on_brew()
            return done(self.brew, "==> Installing Cask ollama-app")
        raise AssertionError(f"an unexpected command ran: {args}")


class InstallerFixture(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="talkdat-mac-home-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        self.downloaded: list[str] = []
        self.engine = ""
        self.ticks = 0.0
        self.progress: list[tuple[str, int | None]] = []
        for target, replacement in {"urllib.request.urlopen": no_network,
                                    "knight_flow.mac_support.IS_MAC": True}.items():
            patcher = mock.patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def clock(self):
        self.ticks += 1.0
        return self.ticks

    def fake_download(self, url, destination, report):
        self.downloaded.append(url)
        ollama_zip(destination)
        for percent in (0, 40, 100):
            report(percent)

    def installer(self, fake, *, download=None, brew=()):
        return mi.MacOllamaInstaller(run=fake, download=download or self.fake_download,
                                     find_engine=lambda: self.engine, home=self.home,
                                     brew_candidates=brew, sleep=lambda _s: None, clock=self.clock)

    def install(self, fake, *, engine_ready=None, **kwargs):
        return self.installer(fake, **kwargs).install(lambda m, p=None: self.progress.append((m, p)),
                                                      engine_ready=engine_ready)

    @property
    def installed(self):
        return self.home / "Applications" / "Ollama.app"

    def leftovers(self):
        caches = self.home / "Library" / "Caches" / "TalkDat"
        return sorted(p.name for p in caches.iterdir()) if caches.exists() else []

    def fake_brew(self):
        bin_dir = self.home / "homebrew" / "bin"
        bin_dir.mkdir(parents=True)
        brew = bin_dir / "brew"
        brew.write_text("#!/bin/bash\n")
        brew.chmod(0o755)  # homebrew() requires X_OK; a freshly written file is not executable
        return str(brew)

    def brew_installs_the_app(self):
        """What the cask leaves behind: the app in Applications and its tool linked into Homebrew's bin."""
        app = self.home / "SystemApplications" / "Ollama.app"
        cli = app / "Contents" / "Resources" / "ollama"
        cli.parent.mkdir(parents=True)
        cli.write_text("cli")
        self.engine = str(cli)


class TheSignedDownloadTests(InstallerFixture):
    def test_the_official_download_is_verified_then_installed_in_the_home_applications_folder(self):
        fake = FakeMac()
        ok, message = self.install(fake, engine_ready=lambda: True)
        self.assertEqual((ok, message), (True, mi.INSTALLED))
        self.assertEqual(self.downloaded, ["https://ollama.com/download/Ollama-darwin.zip"])
        self.assertEqual(fake.names(), ["ditto -x", "codesign --verify", "spctl", "codesign -dv", "codesign -R", "open"])
        self.assertTrue((self.installed / "Contents" / "Resources" / "ollama").is_file())
        self.assertEqual(self.leftovers(), [], "the download and the unpacked copy are deleted")

    def test_each_check_is_the_one_asked_for(self):
        fake = FakeMac()
        self.install(fake)
        verify, assess, details, pinned, opened = fake.calls[1:]
        self.assertEqual(verify[:4], [mi.CODESIGN, "--verify", "--deep", "--strict"])
        self.assertEqual(assess[:4], [mi.SPCTL, "--assess", "--type", "execute"])
        self.assertEqual(details[:2], [mi.CODESIGN, "-dv"])
        self.assertIn(f'-R=anchor apple generic and certificate leaf[subject.OU] = "{TEAM}"', pinned)
        self.assertEqual(opened, [mi.OPEN, "-a", str(self.installed), "--args", "hidden", "--fast-startup"])
        for args in fake.calls[1:5]:
            self.assertTrue(args[-1].endswith("Ollama.app"))
            self.assertNotIn(str(self.home / "Applications"), args[-1], "checked before it is installed")

    def test_the_pinned_team_is_ollamas(self):
        self.assertEqual(mi.OLLAMA_TEAM_ID, TEAM)
        self.assertIn(TEAM, mi.REQUIREMENT)

    def test_progress_moves_through_download_check_move_and_start(self):
        self.install(FakeMac())
        messages = [m for m, _p in self.progress]
        percents = [p for m, p in self.progress if m == mi.DOWNLOADING]
        self.assertEqual(percents, [0, 0, 40, 100])
        order = [mi.DOWNLOADING, mi.CHECKING, mi.MOVING, mi.STARTING]
        self.assertEqual([m for m in dict.fromkeys(messages)], order)

    def test_a_download_that_fails_installs_nothing(self):
        def broken(url, destination, report):
            raise OSError("connection reset")
        fake = FakeMac()
        self.assertEqual(self.install(fake, download=broken), (False, mi.DOWNLOAD_FAILED))
        self.assertEqual(fake.calls, [])
        self.assertFalse(self.installed.exists())
        self.assertEqual(self.leftovers(), [])

    def test_an_app_already_in_applications_is_left_alone(self):
        (self.installed / "Contents").mkdir(parents=True)
        fake = FakeMac()
        self.assertEqual(self.install(fake), (False, mi.ALREADY_THERE))
        self.assertEqual((self.downloaded, fake.calls), ([], []))

    def test_the_move_needs_no_administrator(self):
        fake = FakeMac()
        self.install(fake)
        for args in fake.calls:
            self.assertNotIn("sudo", " ".join(args))
            self.assertNotIn("osascript", " ".join(args))
        self.assertEqual(self.installed.parent, self.home / "Applications")

    def test_another_volume_is_copied_and_the_copy_checked_again(self):
        import errno

        real_rename = mi.os.rename

        def cross_device(src, dst):
            if str(dst).endswith("Ollama.app"):
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_rename(src, dst)
        fake = FakeMac()
        with mock.patch.object(mi.os, "rename", cross_device):
            self.assertTrue(self.install(fake)[0])
        self.assertEqual(fake.names().count("codesign -R"), 2)
        self.assertTrue((self.installed / "Contents" / "Resources" / "ollama").is_file())


class ARefusedSignatureInstallsNothingTests(InstallerFixture):
    def refused(self, fake):
        ok, message = self.install(fake)
        self.assertFalse(ok)
        self.assertFalse(self.installed.exists(), "nothing reaches Applications")
        self.assertNotIn("open", fake.names(), "a refused app is never started")
        self.assertEqual(self.leftovers(), [], "the refused download is deleted")
        return message

    def test_a_broken_signature(self):
        self.assertEqual(self.refused(FakeMac(verify=1)), mi.NOT_SIGNED)

    def test_gatekeeper_rejecting_it(self):
        self.assertEqual(self.refused(FakeMac(assess=3)), mi.NOT_SIGNED)

    def test_another_developers_team(self):
        self.assertEqual(self.refused(FakeMac(team="ABCDE12345")), mi.NOT_OLLAMA)

    def test_an_ad_hoc_signature_has_no_team(self):
        self.assertEqual(self.refused(FakeMac(team="not set")), mi.NOT_OLLAMA)

    def test_the_requirement_failing_even_with_the_right_team_text(self):
        self.assertEqual(self.refused(FakeMac(requirement=3)), mi.NOT_OLLAMA)

    def test_a_check_that_cannot_run_is_a_refusal(self):
        fake = FakeMac()

        def missing_spctl(args, **kwargs):
            if args[0] == mi.SPCTL:
                raise FileNotFoundError(args[0])
            return fake(args, **kwargs)
        ok, message = self.installer(missing_spctl).install()
        self.assertEqual((ok, message), (False, mi.NOT_SIGNED))
        self.assertFalse(self.installed.exists())

    def test_the_messages_say_why_in_plain_words(self):
        for message in (mi.NOT_SIGNED, mi.NOT_OLLAMA):
            self.assertIn("not installed", message)
            self.assertIn("Retry", message)


class TheArchiveIsCheckedBeforeItIsUnpackedTests(InstallerFixture):
    def install_zip(self, entries):
        def download(url, destination, report):
            ollama_zip(destination, entries=entries)
        fake = FakeMac()
        result = self.install(fake, download=download)
        self.assertEqual(fake.calls, [], "ditto never saw it")
        self.assertFalse(self.installed.exists())
        return result

    def test_a_name_that_climbs_out(self):
        self.assertEqual(self.install_zip([("Ollama.app/../../escape", "x", False)]), (False, mi.NOT_THE_FILE))

    def test_an_absolute_name(self):
        self.assertEqual(self.install_zip([("/etc/escape", "x", False)]), (False, mi.NOT_THE_FILE))

    def test_a_symlink_that_points_out(self):
        self.assertEqual(self.install_zip([("Ollama.app/Contents/link", "../../..", True)]), (False, mi.NOT_THE_FILE))
        self.assertEqual(self.install_zip([("Ollama.app/Contents/abs", "/Users", True)]), (False, mi.NOT_THE_FILE))

    def test_not_a_zip_at_all(self):
        def download(url, destination, report):
            Path(destination).write_text("<html>not found</html>")
        fake = FakeMac()
        self.assertEqual(self.install(fake, download=download), (False, mi.NOT_THE_FILE))
        self.assertEqual(fake.calls, [])

    def test_the_real_shape_passes(self):
        path = self.home / "ok.zip"
        ollama_zip(path, entries=[("Ollama.app/Contents/Frameworks/X.framework/Versions/Current", "A", True)])
        self.assertTrue(mi.archive_is_safe(path))

    def test_a_zip_without_the_app(self):
        path = self.home / "other.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Other.app/Contents/Info.plist", "x")
        self.assertFalse(mi.archive_is_safe(path))


class HomebrewTests(InstallerFixture):
    def test_homebrew_installs_the_official_cask_without_a_terminal(self):
        brew = self.fake_brew()
        fake = FakeMac(on_brew=self.brew_installs_the_app)
        ok, message = self.install(fake, brew=(brew,), engine_ready=lambda: True)
        self.assertEqual((ok, message), (True, mi.INSTALLED))
        self.assertEqual(fake.calls[0], [brew, "install", "--cask", "ollama-app"])
        self.assertEqual(self.downloaded, [], "Homebrew's route downloads nothing itself")
        env = fake.envs[0]
        self.assertTrue(env["PATH"].startswith(str(Path(brew).parent.parent) + "/bin"))
        self.assertEqual(env["HOMEBREW_NO_ENV_HINTS"], "1")
        app = Path(os.path.realpath(self.engine)).parents[2]
        self.assertEqual(fake.calls[1], [mi.OPEN, "-a", str(app), "--args", "hidden", "--fast-startup"])
        self.assertEqual(self.progress[0], (mi.BREW_WORKING, None))

    def test_the_cask_is_the_current_official_token(self):
        # Homebrew renamed the cask: ollama-app, with old_tokens ["ollama"].
        self.assertEqual(mi.HOMEBREW_CASK, "ollama-app")

    def test_homebrew_failing_is_a_retry_not_a_second_route(self):
        brew = self.fake_brew()
        fake = FakeMac(brew=1)
        self.assertEqual(self.install(fake, brew=(brew,)), (False, mi.BREW_FAILED))
        self.assertEqual(fake.names(), ["brew"])
        self.assertEqual(self.downloaded, [])

    def test_homebrew_that_reports_an_error_but_installed_it_is_accepted(self):
        brew = self.fake_brew()
        fake = FakeMac(brew=1, on_brew=self.brew_installs_the_app)
        self.assertTrue(self.install(fake, brew=(brew,))[0])

    def test_homebrew_this_user_cannot_write_to_is_passed_over(self):
        brew = self.fake_brew()
        real_access = mi.os.access

        def access(path, mode):
            if mode == mi.os.W_OK and Path(path) == Path(brew).parent:
                return False
            return real_access(path, mode)
        fake = FakeMac()
        with mock.patch.object(mi.os, "access", access):
            self.assertTrue(self.install(fake, brew=(brew,))[0])
        self.assertNotIn("brew", fake.names())
        self.assertEqual(self.downloaded, [mi.DOWNLOAD_URL])

    def test_the_real_runner_never_waits_on_a_terminal(self):
        with mock.patch.object(mi.subprocess, "run", return_value=done(0)) as run:
            mi._run(["/opt/homebrew/bin/brew", "install", "--cask", "ollama-app"], timeout=5)
        kwargs = run.call_args.kwargs
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 5)
        self.assertFalse(kwargs["check"])


class StartingItTests(InstallerFixture):
    def test_setup_waits_for_the_apps_own_engine(self):
        answers = iter([False, False, True])
        polls = []

        def ready():
            polls.append(1)
            return next(answers)
        self.assertTrue(self.install(FakeMac(), engine_ready=ready)[0])
        self.assertEqual(len(polls), 3)

    def test_the_wait_ends_even_if_the_engine_never_answers(self):
        polls = []
        self.assertTrue(self.install(FakeMac(), engine_ready=lambda: polls.append(1) or False)[0])
        self.assertLessEqual(len(polls), mi.ENGINE_START_WAIT_S + 1)

    def test_an_app_that_would_not_open_is_still_installed_and_setup_starts_the_engine(self):
        polls = []
        self.assertTrue(self.install(FakeMac(open_rc=1), engine_ready=lambda: polls.append(1) or True)[0])
        self.assertEqual(polls, [], "no wait for an app that did not open")
        self.assertTrue(self.installed.exists())

    def test_nothing_it_meets_escapes_as_an_exception(self):
        def explodes(*_a, **_k):
            raise RuntimeError("boom")
        self.assertEqual(self.installer(explodes).install(), (False, mi.UNEXPECTED))

    def test_off_a_mac_it_does_nothing(self):
        with mock.patch.object(mac_support, "IS_MAC", False), \
             mock.patch.object(mi, "MacOllamaInstaller", side_effect=AssertionError("constructed off a Mac")):
            self.assertEqual(mi.install_ollama(), (False, mi.NOT_A_MAC))
            self.assertFalse(mi.available())

    def test_a_mac_can_install_with_homebrew_or_its_own_tools(self):
        tools = {mi.CODESIGN, mi.SPCTL, mi.DITTO, mi.OPEN}
        with mock.patch.object(mi.MacOllamaInstaller, "homebrew", return_value=""):
            with mock.patch.object(mi.os.path, "isfile", side_effect=lambda p: p in tools):
                self.assertTrue(mi.available())
            with mock.patch.object(mi.os.path, "isfile", return_value=False):
                self.assertFalse(mi.available())
        with mock.patch.object(mi.MacOllamaInstaller, "homebrew", return_value="/opt/homebrew/bin/brew"), \
             mock.patch.object(mi.os.path, "isfile", return_value=False):
            self.assertTrue(mi.available())


class ImportingTheInstallerTests(unittest.TestCase):
    def test_importing_it_runs_nothing(self):
        import importlib

        with mock.patch.object(subprocess, "run", side_effect=AssertionError("ran a command on import")), \
             mock.patch.object(subprocess, "Popen", side_effect=AssertionError("started a process on import")), \
             mock.patch("urllib.request.urlopen", no_network):
            importlib.reload(mi)


class TheDownloaderTests(unittest.TestCase):
    class Response(io.BytesIO):
        def __init__(self, data, *, url="https://release-assets.githubusercontent.com/x", length=None):
            super().__init__(data)
            self.url = url
            self.headers = {"Content-Length": str(len(data) if length is None else length)}

        def geturl(self):
            return self.url

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            self.close()

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="talkdat-download-"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def fetch(self, response):
        seen, requests = [], []

        def urlopen(request, timeout):
            requests.append(request)
            return response
        with mock.patch.object(mi.urllib.request, "urlopen", urlopen):
            mi._download(mi.DOWNLOAD_URL, self.folder / "Ollama-darwin.zip", seen.append)
        return seen, requests

    def test_it_streams_the_whole_file_with_whole_percents(self):
        data = b"z" * (mi.DOWNLOAD_CHUNK * 3)
        seen, requests = self.fetch(self.Response(data))
        self.assertEqual(seen, [33, 66, 100])
        self.assertEqual((self.folder / "Ollama-darwin.zip").read_bytes(), data)
        self.assertEqual(requests[0].full_url, "https://ollama.com/download/Ollama-darwin.zip")

    def test_an_unknown_size_reports_once(self):
        response = self.Response(b"z" * (mi.DOWNLOAD_CHUNK * 2))
        response.headers = {}
        self.assertEqual(self.fetch(response)[0], [None])

    def test_a_download_that_leaves_https_is_refused(self):
        with self.assertRaises(OSError):
            self.fetch(self.Response(b"zip", url="http://example.com/Ollama-darwin.zip"))

    def test_a_short_download_is_refused(self):
        with self.assertRaises(OSError):
            self.fetch(self.Response(b"zip", length=10))

    def test_an_oversized_download_is_refused_before_writing(self):
        with self.assertRaises(OSError):
            self.fetch(self.Response(b"zip", length=mi.MAX_DOWNLOAD_BYTES + 1))
        self.assertFalse((self.folder / "Ollama-darwin.zip").exists())


class ReadingTheSignatureTests(unittest.TestCase):
    def test_the_team_line_is_read_exactly(self):
        self.assertEqual(mi.signing_team("Identifier=x\nTeamIdentifier=3MU9H2V9Y9\nSealed Resources=x"), TEAM)
        self.assertEqual(mi.signing_team("TeamIdentifier=not set"), "not set")
        self.assertEqual(mi.signing_team("TeamIdentifier=3MU9H2V9Y9 \r\n"), TEAM)
        self.assertEqual(mi.signing_team("Authority=Developer ID Application: Ollama Inc (3MU9H2V9Y9)"), "")
        self.assertEqual(mi.signing_team(""), "")

    def test_the_app_is_found_from_homebrews_link(self):
        folder = Path(tempfile.mkdtemp(prefix="talkdat-app-"))
        self.addCleanup(shutil.rmtree, folder, True)
        cli = folder / "Ollama.app" / "Contents" / "Resources" / "ollama"
        cli.parent.mkdir(parents=True)
        cli.write_text("cli")
        self.assertEqual(mi.app_for(str(cli)), Path(os.path.realpath(folder)) / "Ollama.app")
        self.assertIsNone(mi.app_for(str(folder / "bin" / "ollama")))
        self.assertIsNone(mi.app_for(""))


class MacEngineFixture(unittest.TestCase):
    """A simulated Apple silicon Mac with 16 GB and no Ollama; `self.models` is what the engine lists."""

    memory_gb = 16.0

    def setUp(self):
        self.models: set[str] | None = None
        self.executable = ""
        self.calls: list[tuple] = []
        self.installs: list = []
        self.install_result = (True, mi.INSTALLED)
        self.opened: list[str] = []
        self.watch: SmartFormattingSetup | None = None
        self.during_install: list[dict] = []
        patches = {
            "knight_flow.mac_support.IS_MAC": True,
            "knight_flow.mac_support._MEMORY_GB": self.memory_gb,
            "knight_flow.mac_ollama_install.install_ollama": self.install,
            "knight_flow.mac_ollama_install.available": lambda: True,
            "knight_flow.translation.install_ollama_runtime": self.windows_installer,
            "knight_flow.translation._ensure_ollama_running": self.run_engine,
            "knight_flow.llm._local_ollama_executable": lambda: self.executable,
            "knight_flow.llm._ollama_models": lambda *_a, **_k: None if self.models is None else set(self.models),
            "knight_flow.llm.pull_local_formatter_model": self.pull,
            "knight_flow.llm.prepare_local_formatter": lambda cfg: self.calls.append(("prepare",)),
            "knight_flow.llm.local_formatter_preparing": lambda cfg: False,
            "knight_flow.llm.local_finish_target": lambda cfg, executive: ("http://localhost:11434", LOCAL_FORMATTER_MODEL),
            "knight_flow.llm.local_finish_speed": lambda base, model: None,
            "knight_flow.llm.warm_local_finish": lambda base, model: self.calls.append(("warm", model)),
            "urllib.request.urlopen": no_network,
            "webbrowser.open": lambda url: self.opened.append(url) or True,
        }
        for target, replacement in patches.items():
            patcher = mock.patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def install(self, progress=None, *, engine_ready=None):
        self.installs.append(engine_ready)
        self.calls.append(("install_mac",))
        if progress and self.watch is not None:
            progress(mi.DOWNLOADING, 40)
            self.during_install.append(self.watch.snapshot())
            progress(mi.CHECKING, None)
            self.during_install.append(self.watch.snapshot())
        if self.install_result[0]:
            self.executable = str(Path.home() / "Applications/Ollama.app/Contents/Resources/ollama")
        return self.install_result

    def windows_installer(self):
        raise AssertionError("a Mac ran the Windows installer")

    def run_engine(self, api_base="http://localhost:11434"):
        self.calls.append(("start_engine",))
        if self.models is None:
            self.models = set()
        return True, "running"

    def pull(self, cfg, progress=None, *, timeout=1800.0, model=None):
        self.calls.append(("pull", model))
        self.models.add(model.lower())
        return True, "ok"

    def setup(self, cfg=None, *, gpu=True):
        job = SmartFormattingSetup(cfg or copy.deepcopy(DEFAULT_CONFIG), start_worker=lambda work: work(),
                                   probe_gpu=lambda: gpu, free_disk=lambda: TB, sleep=lambda _s: None)
        self.watch = job
        return job


class TheCardShowsOnAMacTests(MacEngineFixture):
    def test_a_mac_without_ollama_is_offered_one_click_setup(self):
        state = self.setup().snapshot()
        self.assertEqual(state["state"], "not_set_up")
        self.assertTrue(state["offer_in_setup"], "the setup card is visible on a Mac")
        self.assertTrue(state["can_start"])
        self.assertFalse(state["download_page"], "Get Ollama is for when setup cannot do it")
        self.assertTrue(state["recommended"], "Apple silicon counts as a capable GPU")
        self.assertIn(mac_support.OLLAMA_APP_NAME, state["explanation"])
        self.assertNotIn("Ollama engine", state["explanation"])

    def test_the_setup_page_carries_it(self):
        mic = mock.Mock()
        mic.snapshot.return_value = {"check": {"phase": "idle", "mode": "mic"}, "devices": {}, "selected": ""}
        job = self.setup()
        service = SetupWorkspace(job.config, lambda c: {"saved": True, "runtime_refreshed": True},
                                 lambda name, value: [] if name == "permissions" else None, mic, job)
        self.assertTrue(service.snapshot()["formatting"]["offer_in_setup"])

    def test_a_mac_the_installer_cannot_serve_still_points_at_the_download_page(self):
        with mock.patch("knight_flow.mac_ollama_install.available", lambda: False):
            state = self.setup().snapshot()
        self.assertEqual(state["state"], "needs_engine")
        self.assertTrue(state["download_page"])
        self.assertIn("Install the Ollama app", state["message"])


class SetUpRunsTheMacInstallerTests(MacEngineFixture):
    def test_set_up_installs_ollama_then_pulls_and_warms_the_model(self):
        job = self.setup()
        job.start()
        self.assertEqual([c[0] for c in self.calls], ["install_mac", "start_engine", "pull", "prepare", "warm"])
        self.assertEqual(job.snapshot()["state"], "ready")

    def test_install_progress_reaches_the_card_and_settings(self):
        self.setup().start()
        downloading, checking = self.during_install
        self.assertEqual((downloading["state"], downloading["label"], downloading["percent"]), ("downloading", "Downloading 40%", 40))
        self.assertEqual(downloading["message"], mi.DOWNLOADING)
        self.assertEqual(checking["label"], "Installing the Ollama app")
        self.assertEqual(checking["message"], mi.CHECKING)

    def test_setup_waits_on_the_configured_engine(self):
        self.setup().start()
        engine_ready = self.installs[0]
        self.models = None
        self.assertFalse(engine_ready())
        self.models = set()
        self.assertTrue(engine_ready())

    def test_a_refused_install_is_failed_with_retry_and_get_ollama(self):
        self.install_result = (False, mi.NOT_SIGNED)
        job = self.setup()
        job.start()
        state = job.snapshot()
        self.assertEqual((state["state"], state["label"], state["message"]), ("failed", "Failed", mi.NOT_SIGNED))
        self.assertTrue(state["can_start"], "Retry")
        self.assertTrue(state["download_page"], "Get Ollama and Check again")
        self.assertTrue(state["offer_in_setup"])
        self.install_result = (True, mi.INSTALLED)
        job.start()
        self.assertEqual(job.snapshot()["state"], "ready")

    def test_an_installed_ollama_is_not_installed_again(self):
        self.executable = "/Applications/Ollama.app/Contents/Resources/ollama"
        self.setup().start()
        self.assertEqual(self.installs, [])


class ItNeverRunsWithoutAClickTests(MacEngineFixture):
    def test_looking_polling_and_checking_install_nothing(self):
        job = self.setup()
        for _ in range(5):
            job.snapshot()
        job.check_again()
        job.open_download_page()
        cfg = job.config
        with mock.patch.object(smart_formatting, "_SHARED", None), \
             mock.patch.object(smart_formatting, "capable_gpu", lambda: True):
            smart_formatting.shared(cfg).snapshot()
        mic = mock.Mock()
        mic.snapshot.return_value = {"check": {"phase": "idle", "mode": "mic"}, "devices": {}, "selected": ""}
        service = SetupWorkspace(cfg, lambda c: {"saved": True, "runtime_refreshed": True},
                                 lambda name, value: [] if name == "permissions" else None, mic, job)
        for value in ("later", "check", "download_page"):
            service.handle({"operation": "formatting", "revision": service.revision(), "value": value})
        from knight_flow.web_shell.shell_backend import ShellBackend
        backend = object.__new__(ShellBackend)
        backend.formatting, backend.workspaces, backend.models, backend.actions = job, None, None, {}
        for name in ("status", "check", "download_page"):
            backend.handle("action", {"name": "smart_formatting:" + name})
        self.assertEqual(self.installs, [], "nothing installs until Set up is chosen")
        backend.handle("action", {"name": "smart_formatting:start"})
        self.assertEqual(len(self.installs), 1)

    def test_the_setup_card_button_is_the_other_way_in(self):
        job = self.setup()
        mic = mock.Mock()
        mic.snapshot.return_value = {"check": {"phase": "idle", "mode": "mic"}, "devices": {}, "selected": ""}
        service = SetupWorkspace(job.config, lambda c: {"saved": True, "runtime_refreshed": True},
                                 lambda name, value: [] if name == "permissions" else None, mic, job)
        service.handle({"operation": "formatting", "revision": service.revision(), "value": "start"})
        self.assertEqual(len(self.installs), 1)

    def test_only_start_reaches_the_installer(self):
        """In the source: install_ollama in _install_engine, _install_engine in _run, _run in start."""
        tree = ast.parse((ROOT / "knight_flow" / "smart_formatting.py").read_text(encoding="utf-8"))
        where: dict[str, set[str]] = {"install_ollama": set(), "_install_engine": set(), "_run": set()}
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.Attribute) and node.attr in where:
                    where[node.attr].add(function.name)
        self.assertEqual(where, {"install_ollama": {"_install_engine"}, "_install_engine": {"_run"}, "_run": {"start"}})

    def test_no_other_module_imports_the_installer(self):
        importers = set()
        for path in sorted((ROOT / "knight_flow").rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ""] + [alias.name for alias in node.names]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                if any(name.split(".")[-1] == "mac_ollama_install" for name in names):
                    importers.add(path.relative_to(ROOT).as_posix())
        self.assertEqual(importers, {"knight_flow/smart_formatting.py"})

class TheMacModelFollowsItsMemoryTests(unittest.TestCase):
    """Apple silicon is a capable GPU; the 4B needs 16 GB of memory on a Mac."""

    def mac(self, memory_gb):
        stack = mock.patch.multiple(mac_support, IS_MAC=True, _MEMORY_GB=memory_gb)
        stack.start()
        self.addCleanup(stack.stop)

    def test_apple_silicon_is_a_capable_gpu_and_an_intel_mac_is_not(self):
        self.mac(8.0)
        with mock.patch("platform.machine", return_value="arm64"):
            self.assertTrue(smart_formatting.capable_gpu())
        with mock.patch("platform.machine", return_value="x86_64"):
            self.assertFalse(smart_formatting.capable_gpu())

    def test_the_model_by_memory(self):
        for memory, model in ((8.0, LOCAL_FORMATTER_MODEL), (15.9, LOCAL_FORMATTER_MODEL),
                              (16.0, LOCAL_GPU_MODEL), (18.0, LOCAL_GPU_MODEL), (24.0, LOCAL_GPU_MODEL),
                              (32.0, LOCAL_GPU_MODEL), (64.0, LOCAL_GPU_MODEL), (0.0, LOCAL_FORMATTER_MODEL)):
            with self.subTest(memory=memory), mock.patch.multiple(mac_support, IS_MAC=True, _MEMORY_GB=memory):
                self.assertEqual(smart_formatting.wanted_models(copy.deepcopy(DEFAULT_CONFIG), gpu=True), [model])

    def test_the_card_names_the_size_it_will_download(self):
        for memory, size in ((8.0, "1.4 GB"), (16.0, "2.5 GB")):
            with self.subTest(memory=memory), mock.patch.multiple(mac_support, IS_MAC=True, _MEMORY_GB=memory), \
                 mock.patch("knight_flow.llm._local_ollama_executable", return_value=""), \
                 mock.patch("knight_flow.mac_ollama_install.available", return_value=True), \
                 mock.patch("urllib.request.urlopen", no_network):
                state = SmartFormattingSetup(copy.deepcopy(DEFAULT_CONFIG), start_worker=lambda work: work(),
                                             probe_gpu=lambda: True, free_disk=lambda: TB).snapshot()
                self.assertEqual(state["download_size"], size)
                self.assertIn(f"about {size}", state["explanation"])
                self.assertTrue(state["recommended"])
                self.assertEqual(state["note"], "", "a small Mac is not told it has no graphics card")

    def test_off_a_mac_memory_is_not_the_question(self):
        with mock.patch.multiple(mac_support, IS_MAC=False, _MEMORY_GB=2.0):
            self.assertTrue(mac_support.gpu_model_fits())
            self.assertEqual(smart_formatting.wanted_models(copy.deepcopy(DEFAULT_CONFIG), gpu=True), [LOCAL_GPU_MODEL])

    def test_memory_is_read_once(self):
        reads = []
        with mock.patch.multiple(mac_support, IS_MAC=True, _MEMORY_GB=None), \
             mock.patch("knight_flow.pc_audit._mac_ram_gb", side_effect=lambda: reads.append(1) or 16.0):
            self.assertEqual(mac_support.unified_memory_gb(), 16.0)
            self.assertTrue(mac_support.gpu_model_fits())
            self.assertEqual(reads, [1])

    def test_a_chosen_model_is_left_alone(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["transforms"]["llm"]["model"] = "llama3.2:3b"
        with mock.patch.multiple(mac_support, IS_MAC=True, _MEMORY_GB=64.0):
            self.assertEqual(smart_formatting.wanted_models(cfg, gpu=True), ["llama3.2:3b"])


BASE = "http://127.0.0.1:11987"


def formatter_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["transforms"]["llm"].update(provider="ollama", api_base=BASE, model=LOCAL_FORMATTER_MODEL, auto_install=True)
    return cfg


def speed(on_gpu):
    return MachineSpeed(prefill_tps=4000.0, generation_tps=150.0, on_gpu=on_gpu)


class TheFinisherKeepsASmallMacOnTheSmallModelTests(unittest.TestCase):
    """The launch warm-up and every dictation apply the same 16 GB rule as setup."""

    def setUp(self):
        self.addCleanup(self.reset)
        self.reset()

    @staticmethod
    def reset():
        for model in (LOCAL_FORMATTER_MODEL, LOCAL_GPU_MODEL):
            key = llm.local_finish_key(BASE, model)
            llm._LOCAL_SPEED.pop(key, None)
            llm._OLLAMA_PREPARE_IN_FLIGHT.discard(key)
            llm._OLLAMA_PREPARED.discard(key)
        llm._OLLAMA_READY_CACHE.clear()

    def target(self, memory, installed):
        with mock.patch.multiple(mac_support, IS_MAC=True, _MEMORY_GB=memory), \
             mock.patch("knight_flow.llm._ollama_models", return_value=set(installed)):
            return llm.local_finish_target(formatter_config(), executive=False)[1]

    def test_a_4b_on_the_gpu_answers_only_on_a_16_gb_mac(self):
        llm._LOCAL_SPEED[llm.local_finish_key(BASE, LOCAL_GPU_MODEL)] = speed(True)
        both = {LOCAL_GPU_MODEL.lower(), LOCAL_FORMATTER_MODEL}
        self.assertEqual(self.target(8.0, both), LOCAL_FORMATTER_MODEL)
        self.assertEqual(self.target(16.0, both), LOCAL_GPU_MODEL)

    def prepare(self, memory, models):
        state = {"models": set(models)}
        warmed, pulled = [], []

        def warm(api_base, model, **_k):
            warmed.append(model)
            result = speed(True)
            llm._LOCAL_SPEED[llm.local_finish_key(api_base, model)] = result
            return result

        def run(argv, **_k):
            pulled.append(argv[-1])
            state["models"].add(argv[-1].lower())
            return mock.Mock(returncode=0)

        class Now:
            def __init__(self, target, **_k):
                self.target = target

            def start(self):
                self.target()

        def no_process(*_a, **_k):
            raise AssertionError("a test started a real process")

        with mock.patch.multiple(mac_support, IS_MAC=True, _MEMORY_GB=memory), \
             mock.patch("knight_flow.llm._ollama_models", side_effect=lambda *a, **k: set(state["models"])), \
             mock.patch("knight_flow.llm.warm_local_finish", side_effect=warm), \
             mock.patch("knight_flow.llm._local_ollama_executable", return_value="/Applications/Ollama.app/Contents/Resources/ollama"), \
             mock.patch("knight_flow.llm.subprocess.run", side_effect=run), \
             mock.patch("knight_flow.llm.subprocess.Popen", side_effect=no_process), \
             mock.patch("knight_flow.llm.threading.Thread", Now):
            llm.prepare_local_formatter(formatter_config())
        return warmed, pulled

    def test_an_8_gb_mac_never_pulls_the_4b_at_launch(self):
        warmed, pulled = self.prepare(8.0, {LOCAL_FORMATTER_MODEL})
        self.assertEqual((warmed, pulled), ([LOCAL_FORMATTER_MODEL], []))

    def test_an_8_gb_mac_never_warms_a_4b_it_already_has(self):
        warmed, pulled = self.prepare(8.0, {LOCAL_FORMATTER_MODEL, LOCAL_GPU_MODEL.lower()})
        self.assertEqual((warmed, pulled), ([LOCAL_FORMATTER_MODEL], []))

    def test_a_16_gb_mac_gets_the_4b_as_before(self):
        warmed, pulled = self.prepare(16.0, {LOCAL_FORMATTER_MODEL})
        self.assertEqual(pulled, [LOCAL_GPU_MODEL])
        self.assertEqual(warmed, [LOCAL_FORMATTER_MODEL, LOCAL_GPU_MODEL])


class TheMacCopyIsPlainTests(unittest.TestCase):
    PRICE = re.compile(r"\$|\bpric(e|ing)\b|\bbuy\b|\bpurchase|\bsubscri|\btrial\b|\bcost\b|\bpaid\b", re.IGNORECASE)

    def messages(self):
        return [value for name, value in vars(mi).items()
                if name.isupper() and isinstance(value, str) and " " in value and name != "REQUIREMENT"]

    def test_every_message_is_plain(self):
        self.assertGreaterEqual(len(self.messages()), 12)
        for text in self.messages():
            with self.subTest(text=text):
                self.assertNotIn(chr(0x2014), text)
                self.assertNotIn(" -- ", text)
                self.assertIsNone(self.PRICE.search(text))
                self.assertNotRegex(text, r"\b(PC|Windows)\b")
                self.assertTrue(text.endswith("."), "a sentence, not a fragment")

    def test_the_mac_says_app_where_windows_says_engine(self):
        with mock.patch.object(mac_support, "IS_MAC", True):
            self.assertEqual(smart_formatting.engine_name(), "the Ollama app")
        with mock.patch.object(mac_support, "IS_MAC", False):
            self.assertEqual(smart_formatting.engine_name(), "the Ollama engine")


if __name__ == "__main__":
    unittest.main()
