"""The Mac's Ollama install, run only when the person chooses Set up smart formatting.

Windows gets the engine from winget (translation.install_ollama_runtime). A Mac
had no scripted path, so smart formatting setup hid itself there and Settings
could only open the download page: a Mac user got the local writing model only
by installing Ollama by hand. This module is the Mac's engine installer.

It has one caller, the worker behind "Set up smart formatting"
(SmartFormattingSetup._run, which only SmartFormattingSetup.start begins, from
a click in the setup card or in Settings, Formatting). Nothing calls it at
launch, and importing it does nothing.

Two routes, the first that applies:

1. Homebrew, when this user can run it (brew is there and its bin folder is
   theirs to write): `brew install --cask ollama-app`, with no terminal to
   answer from. `ollama-app` is the official cask's current token. It used to
   be `ollama` (formulae.brew.sh/api/cask/ollama-app.json lists old_tokens
   ["ollama"], checked 2026-09-23), and plain `ollama` is also the name of a
   separate formula that builds only the command line tool. Homebrew checks
   the download against the cask's own checksum.

2. Otherwise Ollama's own Mac download (DOWNLOAD_URL). Nothing from it is
   installed unless all four checks pass on the unpacked app:

       codesign --verify --deep --strict    the signature is intact, nested code too
       spctl --assess --type execute        Gatekeeper accepts it: notarized Developer ID
       codesign -dv                         its TeamIdentifier is OLLAMA_TEAM_ID
       codesign --verify -R <requirement>   the signing certificate is that team's

   Only then does it move into ~/Applications, the person's own folder, so no
   administrator password is asked for, and `open -a` starts it.

Every failure is (False, one plain sentence), which setup shows with Retry.
The download is deleted whatever happens.
"""
from __future__ import annotations

import errno
import logging
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from . import mac_support

log = logging.getLogger(__name__)

#: Ollama's own Mac download: the zip its install script fetches on a Mac
#: (scripts/install.sh in github.com/ollama/ollama sets
#: DOWNLOAD_URL="https://ollama.com/download/Ollama-darwin.zip"). Checked
#: 2026-09-23: ollama.com answers it with a redirect to
#: github.com/ollama/ollama/releases/latest/download/Ollama-darwin.zip, which
#: was v0.34.3, 197,276,226 bytes, that day. The download button on
#: ollama.com/download/mac serves the same app as a disk image.
DOWNLOAD_URL = "https://ollama.com/download/Ollama-darwin.zip"

#: Ollama's Apple Developer ID team: the OU of the certificate that signs
#: Ollama.app. Not guessed. It is the team in the app's designated requirement,
#: as read from the signed app and published by App Catalog
#: (appcatalog.cloud/apps/ollama): identifier "com.electron.ollama" and anchor
#: apple generic and ... certificate leaf[subject.OU] = "3MU9H2V9Y9". The
#: Installomator project's ollama label pins the same expectedTeamID and checks
#: it with spctl on every download. Both read 2026-09-23. VERIFIED 2026-09-24 on
#: knight-mac against Ollama-darwin.zip (Ollama 0.34.3, unpacked in /tmp, not
#: installed): `codesign -dv` shows "Developer ID Application: Infra
#: Technologies, Inc (3MU9H2V9Y9)" and TeamIdentifier=3MU9H2V9Y9; spctl says
#: "accepted, Notarized Developer ID"; the -R requirement with this team passes
#: and the same requirement with a wrong team is refused.
OLLAMA_TEAM_ID = "3MU9H2V9Y9"

#: The same team, asked of the signature itself: Apple's anchor, and that team
#: in the signing certificate. codesign evaluates this cryptographically, so it
#: does not rest on reading text back.
REQUIREMENT = f'anchor apple generic and certificate leaf[subject.OU] = "{OLLAMA_TEAM_ID}"'

#: The official cask's current token (see the module docstring).
HOMEBREW_CASK = "ollama-app"
#: Homebrew's own locations: Apple silicon, then Intel.
BREW_CANDIDATES = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")

CODESIGN = "/usr/bin/codesign"
SPCTL = "/usr/sbin/spctl"
DITTO = "/usr/bin/ditto"
OPEN = "/usr/bin/open"

APP_NAME = "Ollama.app"
#: Where the app keeps its command line tool (Ollama's macOS docs), which is
#: what llm._local_ollama_executable finds in ~/Applications afterwards.
CLI_IN_APP = ("Contents", "Resources", "ollama")

#: "hidden" is what Ollama's install script passes (open -a Ollama --args
#: hidden): start without showing a window. "--fast-startup" skips the app's
#: "Move to Applications?" question (app/cmd/app/app.go runs
#: maybeMoveAndRestart only without it), which ~/Applications would otherwise
#: trigger. An Ollama that no longer knows the flag ignores it.
LAUNCH_ARGS = ("hidden", "--fast-startup")

#: The zip was 197 MB on 2026-09-23. Anything far past that is not that file.
MAX_DOWNLOAD_BYTES = 1_000_000_000
MAX_UNPACKED_BYTES = 4_000_000_000
DOWNLOAD_CHUNK = 1 << 20
#: How long to let the app bring its engine up before setup starts one itself.
#: When /usr/local/bin/ollama is not already its link, the app asks for an
#: administrator password to make one (installSymlink in app/cmd/app/app.go),
#: and it starts its engine only after that question is answered either way.
ENGINE_START_WAIT_S = 90.0
BREW_TIMEOUT_S = 1800
TOOL_TIMEOUT_S = 600

# What the person reads. Setup shows these beside its own label.
BREW_WORKING = "Installing Ollama with Homebrew. This can take a few minutes."
DOWNLOADING = "Downloading the Ollama app."
CHECKING = "Checking that the app is signed by Ollama."
MOVING = "Putting Ollama in your Applications folder."
STARTING = (
    "Starting Ollama. If Ollama asks for your password to add its command line tool, "
    "you can allow it or cancel. Talk DAT works either way."
)
INSTALLED = "Ollama is installed."

BREW_FAILED = "Homebrew could not install Ollama. Choose Retry, or Get Ollama to install it yourself."
DOWNLOAD_FAILED = "Ollama did not finish downloading. Check your internet connection, then choose Retry."
NOT_THE_FILE = "The Ollama download was not the file Talk DAT expected, so nothing was installed. Choose Retry."
NOT_SIGNED = (
    "The downloaded Ollama app did not pass the macOS security check, so it was not installed. "
    "Choose Retry, or Get Ollama to install it yourself."
)
NOT_OLLAMA = (
    "The downloaded app is not signed by Ollama, so it was not installed. "
    "Choose Retry, or Get Ollama to install it yourself."
)
ALREADY_THERE = "An Ollama app is already in your Applications folder. Open it once, then choose Check again."
NOT_MOVED = "Ollama could not be put in your Applications folder. Choose Retry."
UNEXPECTED = "Ollama could not be installed. Choose Retry, or Get Ollama to install it yourself."
NOT_A_MAC = "This installer is for a Mac."

Progress = Callable[[str, "int | None"], None]
Runner = Callable[..., Any]
Downloader = Callable[[str, Path, Callable[["int | None"], None]], None]


def _run(args: list[str], *, timeout: float, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """One command, never waiting on a terminal: stdin is empty, output is kept for the log."""
    return subprocess.run(
        list(args),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def _download(url: str, destination: Path, report: Callable[[int | None], None]) -> None:
    """Stream the zip to disk, reporting whole percents. Raises OSError unless the whole file arrived.

    No net_fence check here on purpose: the fence guards requests that carry
    what a person said, and this carries nothing of theirs, the same as winget
    on Windows and the model pull Ollama makes itself.
    """
    request = urllib.request.Request(url, headers={"User-Agent": mac_support.USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        if not str(response.geturl()).lower().startswith("https://"):
            raise OSError("the download was redirected off HTTPS")
        total = int(response.headers.get("Content-Length") or 0)
        if total > MAX_DOWNLOAD_BYTES:
            raise OSError(f"the download is {total} bytes, far larger than Ollama's app")
        done: int = 0
        last: object = object()  # nothing reported yet
        with open(destination, "wb") as handle:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_DOWNLOAD_BYTES:
                    raise OSError("the download is far larger than Ollama's app")
                handle.write(chunk)
                percent = min(100, done * 100 // total) if total else None
                if percent != last:
                    last = percent
                    report(percent)
    if total and done != total:
        raise OSError(f"the download stopped at {done} of {total} bytes")


def _find_engine() -> str:
    from .llm import _local_ollama_executable

    return _local_ollama_executable()


def _tail(text: Any, size: int = 600) -> str:
    return str(text or "").strip()[-size:]


def signing_team(codesign_details: str) -> str:
    """The TeamIdentifier value of `codesign -dv` output ("not set" when ad hoc), or "" when absent."""
    found = re.search(r"^TeamIdentifier=(.+?)\s*$", str(codesign_details or ""), re.MULTILINE)
    return found.group(1) if found else ""


def archive_is_safe(path: Path) -> bool:
    """Whether the zip holds Ollama.app and nothing that could land outside its folder.

    Checked before ditto unpacks anything, because the signature can only be
    checked after unpacking: a name with .. in it, an absolute name, or a
    symlink that points out of the folder could write somewhere else first.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            unpacked = 0
            has_app = False
            for entry in archive.infolist():
                name = entry.filename
                parts = PurePosixPath(name).parts
                if not parts or name.startswith("/") or ".." in parts:
                    return False
                has_app = has_app or parts[0] == APP_NAME
                unpacked += max(0, int(entry.file_size))
                if unpacked > MAX_UNPACKED_BYTES:
                    return False
                if (entry.external_attr >> 16) & 0o170000 == 0o120000:  # a symlink
                    target = archive.read(entry).decode("utf-8", "replace")
                    landed = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                    if target.startswith("/") or landed == ".." or landed.startswith("../"):
                        return False
            return has_app
    except Exception:  # not a zip, truncated, encrypted, unreadable
        return False


def looks_like_the_app(app: Path) -> bool:
    """A real bundle (not a link to one) with Ollama's command line tool where the docs put it."""
    return (
        app.is_dir()
        and not app.is_symlink()
        and app.joinpath(*CLI_IN_APP).is_file()
        and (app / "Contents" / "Info.plist").is_file()
    )


def app_for(cli: str) -> Path | None:
    """The .app a command line path belongs to (Homebrew links it out of the app), or None."""
    if not cli:
        return None
    real = Path(os.path.realpath(cli))
    if tuple(real.parts[-3:]) == CLI_IN_APP and len(real.parents) > 2 and real.parents[2].suffix == ".app":
        return real.parents[2]
    return None


class MacOllamaInstaller:
    """Homebrew or the signed download, then start it. Every seam can be replaced in a test."""

    def __init__(
        self,
        *,
        run: Runner | None = None,
        download: Downloader | None = None,
        find_engine: Callable[[], str] | None = None,
        home: Path | str | None = None,
        brew_candidates: tuple[str, ...] = BREW_CANDIDATES,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.run = run or _run
        self.download = download or _download
        self.find_engine = find_engine or _find_engine
        self.home = Path(home) if home is not None else Path.home()
        self.brew_candidates = tuple(brew_candidates)
        self.sleep = sleep
        self.clock = clock

    # --------------------------------------------------------------- routes
    def homebrew(self) -> str:
        """brew, if it is there and this user can install with it (its bin folder is theirs)."""
        for candidate in self.brew_candidates:
            if (
                os.path.isfile(candidate)
                and os.access(candidate, os.X_OK)
                and os.access(os.path.dirname(candidate), os.W_OK)
            ):
                return candidate
        return ""

    def install(self, progress: Progress | None = None, *, engine_ready: Callable[[], bool] | None = None) -> tuple[bool, str]:
        """Install Ollama and start it. Returns (ok, one plain sentence). Never raises."""
        report: Progress = progress or (lambda _message, _percent=None: None)
        try:
            brew = self.homebrew()
            ok, message, app = self._with_homebrew(brew, report) if brew else self._from_download(report)
            if not ok:
                return False, message
            self._start(app, report, engine_ready)
            return True, INSTALLED
        except Exception:  # a button's worker must never die silently
            log.warning("the Ollama install stopped unexpectedly", exc_info=True)
            return False, UNEXPECTED

    def _with_homebrew(self, brew: str, report: Progress) -> tuple[bool, str, Path | None]:
        report(BREW_WORKING, None)
        prefix = os.path.dirname(os.path.dirname(brew))
        env = dict(os.environ)
        env.update(
            HOMEBREW_NO_ENV_HINTS="1",
            HOMEBREW_NO_INSTALL_CLEANUP="1",
            # An app opened from Finder has launchd's short PATH; brew needs its own.
            PATH=":".join((f"{prefix}/bin", f"{prefix}/sbin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")),
        )
        try:
            result = self.run([brew, "install", "--cask", HOMEBREW_CASK], timeout=BREW_TIMEOUT_S, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("brew install --cask %s did not finish: %s", HOMEBREW_CASK, exc)
            return False, BREW_FAILED, None
        engine = self.find_engine()
        if result.returncode != 0 or not engine:
            log.warning("brew install --cask %s exited %s (engine found: %s): %s",
                        HOMEBREW_CASK, result.returncode, bool(engine), _tail(result.stdout))
            if not engine:
                return False, BREW_FAILED, None
        return True, "", app_for(engine)

    def _from_download(self, report: Progress) -> tuple[bool, str, Path | None]:
        applications = self.home / "Applications"
        destination = applications / APP_NAME
        if destination.exists() or destination.is_symlink():
            # Something is already there that the engine search did not accept.
            return False, ALREADY_THERE, None
        parent = self.home / "Library" / "Caches" / "TalkDat"
        parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="ollama-install-", dir=parent))
        try:
            archive = staging / "Ollama-darwin.zip"
            report(DOWNLOADING, 0)
            try:
                self.download(DOWNLOAD_URL, archive, lambda percent: report(DOWNLOADING, percent))
            except Exception as exc:
                log.warning("the Ollama download failed: %s", exc)
                return False, DOWNLOAD_FAILED, None
            report(CHECKING, None)
            if not archive_is_safe(archive):
                log.warning("the Ollama download is not a zip holding %s and nothing unsafe", APP_NAME)
                return False, NOT_THE_FILE, None
            unpacked = staging / "unpacked"
            unpacked.mkdir()
            result = self._tool([DITTO, "-x", "-k", str(archive), str(unpacked)])
            app = unpacked / APP_NAME
            if result is None or result.returncode != 0 or not looks_like_the_app(app):
                return False, NOT_THE_FILE, None
            archive.unlink(missing_ok=True)  # the space is needed more than the zip now
            refusal = self._verify(app)
            if refusal:
                return False, refusal, None
            report(MOVING, None)
            applications.mkdir(exist_ok=True)
            if destination.exists() or destination.is_symlink():
                return False, ALREADY_THERE, None
            try:
                os.rename(app, destination)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    log.warning("could not move Ollama into %s: %s", applications, exc)
                    return False, NOT_MOVED, None
                # Another volume: copy with everything a signature needs, then check the copy.
                copied = self._tool([DITTO, str(app), str(destination)])
                refusal = NOT_MOVED if copied is None or copied.returncode != 0 else self._verify(destination)
                if refusal:
                    shutil.rmtree(destination, ignore_errors=True)
                    return False, refusal, None
            return True, "", destination
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    # ----------------------------------------------------------- the checks
    def _tool(self, args: list[str], *, timeout: float = TOOL_TIMEOUT_S) -> Any:
        try:
            result = self.run(args, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("%s did not run: %s", args[0], exc)
            return None
        if result.returncode != 0:
            log.warning("%s exited %s: %s", " ".join(args[:3]), result.returncode, _tail(result.stdout))
        return result

    def _verify(self, app: Path) -> str:
        """Empty when the app is Ollama's own, intact and notarized; otherwise why it is refused."""
        target = str(app)
        intact = self._tool([CODESIGN, "--verify", "--deep", "--strict", "--verbose=2", target])
        if intact is None or intact.returncode != 0:
            return NOT_SIGNED
        accepted = self._tool([SPCTL, "--assess", "--type", "execute", "--verbose=2", target])
        if accepted is None or accepted.returncode != 0:
            return NOT_SIGNED
        details = self._tool([CODESIGN, "-dv", "--verbose=2", target])
        team = signing_team(details.stdout) if details is not None and details.returncode == 0 else ""
        if team != OLLAMA_TEAM_ID:
            log.warning("the downloaded Ollama app is signed by team %r, not %s", team, OLLAMA_TEAM_ID)
            return NOT_OLLAMA
        pinned = self._tool([CODESIGN, "--verify", "--strict", "-R=" + REQUIREMENT, target])
        if pinned is None or pinned.returncode != 0:
            return NOT_OLLAMA
        return ""

    # ---------------------------------------------------------------- start
    def _start(self, app: Path | None, report: Progress, engine_ready: Callable[[], bool] | None) -> None:
        """open -a, then give the app's engine time to answer before setup starts one itself."""
        report(STARTING, None)
        opened = self._tool([OPEN, "-a", str(app) if app is not None else "Ollama", "--args", *LAUNCH_ARGS], timeout=60)
        if opened is None or opened.returncode != 0 or engine_ready is None:
            return  # setup's own start (ollama serve) takes it from here
        deadline = self.clock() + ENGINE_START_WAIT_S
        while self.clock() < deadline:
            try:
                if engine_ready():
                    return
            except Exception:
                pass
            self.sleep(1.0)


def available() -> bool:
    """Whether this Mac can install Ollama on a click: Homebrew, or the tools the signed download needs."""
    if not mac_support.IS_MAC:
        return False
    return bool(MacOllamaInstaller().homebrew()) or all(
        os.path.isfile(tool) for tool in (CODESIGN, SPCTL, DITTO, OPEN)
    )


def install_ollama(progress: Progress | None = None, *, engine_ready: Callable[[], bool] | None = None) -> tuple[bool, str]:
    """Install Ollama on this Mac. Smart formatting setup's worker is the only caller."""
    if not mac_support.IS_MAC:
        return False, NOT_A_MAC
    return MacOllamaInstaller().install(progress, engine_ready=engine_ready)
