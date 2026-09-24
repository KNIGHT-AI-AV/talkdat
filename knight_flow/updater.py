from __future__ import annotations

import json
import logging
import os
import re
import hashlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import official_build
from .config import app_dir
from .version import (
    APP_REPOSITORY,
    APP_RELEASES_URL,
    APP_VERSION,
    INSTALLER_ASSET_NAME,
    MAC_INSTALLER_ASSET_SUFFIX,
    WINDOWS_INSTALLER_ASSET_NAME,
)


log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]
CHECKSUM_ASSET_NAME = "SHA256SUMS.txt"
RECEIPT_ASSET_NAME = "RELEASE-RECEIPT.json"

STORE_PRODUCT_ID = "9NF64GDNBPF5"
STORE_PRODUCT_URI = f"ms-windows-store://pdp/?productid={STORE_PRODUCT_ID}"


def running_from_store() -> bool:
    """True when this process runs with MSIX package identity.

    X-116, Microsoft certification policy 10.2.5: a Store-installed app must
    update ONLY through the Store. The certification failure quoted our own
    "Check for updates" back at us. Package identity is the OS's answer to
    "was this installed from the Store" -- GetCurrentPackageFullName returns
    APPMODEL_ERROR_NO_PACKAGE (15700) for a plain installer copy.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes

        length = ctypes.c_uint32(0)
        result = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
        return result != 15700
    except Exception:
        log.warning("package identity probe failed; treating this copy as non-Store", exc_info=True)
        return False


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    available: bool
    release_url: str
    installer_url: str
    installer_name: str
    installer_size: int
    installer_sha256: str
    checksum_url: str
    published_at: str
    release_notes: str
    receipt_url: str = ""
    receipt_commit: str = ""
    receipt_verified: bool = False
    artifact_signing_enabled: bool = False
    # X-84: a "red" update installs itself; a "green" one waits to be asked.
    # Set deliberately at publish time -- never inferred from the version
    # number, because only the person who wrote the change knows whether it
    # fixes something a user is currently living with.
    severity: str = "green"

    @property
    def forced(self) -> bool:
        return self.severity == "red"


class UpdateError(RuntimeError):
    pass


def version_parts(version: str) -> tuple[int, ...]:
    raw = str(version).strip().lower().split("+", 1)[0]
    raw = raw[1:] if raw.startswith("v") else raw
    core = raw.split("-", 1)[0]
    parts = [int(part) for part in re.findall(r"\d+", core)]
    return tuple(parts or [0])


def _prerelease_parts(version: str) -> tuple[str, ...] | None:
    raw = str(version).strip().lower().split("+", 1)[0]
    raw = raw[1:] if raw.startswith("v") else raw
    if "-" not in raw:
        return None
    return tuple(part for part in raw.split("-", 1)[1].split(".") if part)


def _compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    for left_part, right_part in zip(left, right):
        if left_part == right_part:
            continue
        left_numeric = left_part.isdigit()
        right_numeric = right_part.isdigit()
        if left_numeric and right_numeric:
            return 1 if int(left_part) > int(right_part) else -1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return 1 if left_part > right_part else -1
    if len(left) == len(right):
        return 0
    return 1 if len(left) > len(right) else -1


def compare_versions(left: str, right: str) -> int:
    left_parts = list(version_parts(left))
    right_parts = list(version_parts(right))
    width = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (width - len(left_parts)))
    right_parts.extend([0] * (width - len(right_parts)))
    if tuple(left_parts) != tuple(right_parts):
        return 1 if tuple(left_parts) > tuple(right_parts) else -1

    left_pre = _prerelease_parts(left)
    right_pre = _prerelease_parts(right)
    if left_pre is None and right_pre is None:
        return 0
    if left_pre is None:
        return 1
    if right_pre is None:
        return -1
    return _compare_prerelease(left_pre, right_pre)


def is_newer_version(latest: str, current: str) -> bool:
    return compare_versions(latest, current) > 0


def _releases_api_url(repository: str) -> str:
    return f"https://api.github.com/repos/{repository}/releases?per_page=15"


def _latest_release_api_url(repository: str) -> str:
    return f"https://api.github.com/repos/{repository}/releases/latest"


def _update_repository() -> str:
    """The releases this build may read, or UpdateError when it reads none.

    2026-09-23, open source: official builds read Knight's releases; a build
    from source checks nothing unless it was given a repository of its own
    (official_build.update_repository). Asked at call time, never at import.
    """
    repository = official_build.update_repository()
    if not repository:
        raise UpdateError(official_build.UPDATES_OFF)
    return repository


def _request(url: str, timeout: float) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"TalkDat/{APP_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def _download_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": f"TalkDat/{APP_VERSION}",
        },
    )


def _read_text_url(url: str, timeout: float) -> str:
    with urllib.request.urlopen(_download_request(url), timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _read_receipt_url(url: str, timeout: float) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(_download_request(url), timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8-sig"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
        raise UpdateError(f"Could not verify the release receipt: {error}.") from error
    if not isinstance(payload, dict):
        raise UpdateError("The release receipt is not a JSON object.")
    return payload


def _is_installer_for_this_platform(asset_name: str) -> bool:
    """Whether this release asset is the installer for the machine we are on.

    Windows matches the exact filename it has always used. macOS matches the
    .dmg by suffix, because the Mac disk image carries the version in its name.

    The point of the split is what happens when there is no match: no installer
    url, so `check_for_update` reports no installable update and nothing is
    downloaded. Before this, a Mac asked for Talk-Dat-Setup.exe by name, found
    it, and -- with auto-download on by default -- quietly pulled a 118MB
    Windows executable it could never run, without asking anyone.
    """
    name = (asset_name or "").strip().lower()
    if not name:
        return False
    if sys.platform == "darwin":
        return name.endswith(MAC_INSTALLER_ASSET_SUFFIX)
    return name == WINDOWS_INSTALLER_ASSET_NAME.lower()


def _sha256_from_digest(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("sha256:"):
        raw = raw.split(":", 1)[1]
    return raw if re.fullmatch(r"[a-f0-9]{64}", raw) else ""


def _sha256_from_sums(text: str, filename: str) -> str:
    target = filename.strip().lower()
    for line in text.splitlines():
        match = re.match(r"^\s*([a-fA-F0-9]{64})\s+\*?(.+?)\s*$", line)
        if not match:
            continue
        digest = match.group(1).lower()
        name = Path(match.group(2).strip()).name.lower()
        if name == target:
            return digest
    return ""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_release_receipt(
    receipt: dict[str, Any],
    *,
    release_tag: str,
    installer_name: str,
    installer_size: int = 0,
    installer_sha256: str = "",
) -> tuple[str, int, str, bool]:
    """Bind a release asset to its repository, tag, commit, size, and digest."""

    expected_repository = official_build.update_repository() or APP_REPOSITORY
    if str(receipt.get("repository") or "").strip().lower() != expected_repository.lower():
        raise UpdateError("The release receipt belongs to a different repository.")
    if str(receipt.get("tag") or "").strip() != str(release_tag or "").strip():
        raise UpdateError("The release receipt tag does not match the selected release.")
    commit = str(receipt.get("commit") or "").strip()
    if not re.fullmatch(r"[a-fA-F0-9]{40}", commit):
        raise UpdateError("The release receipt does not contain an exact source commit.")

    assets = receipt.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("The release receipt has no asset provenance list.")
    target = next(
        (
            asset
            for asset in assets
            if isinstance(asset, dict)
            and str(asset.get("name") or "").strip().lower() == installer_name.strip().lower()
        ),
        None,
    )
    if target is None:
        raise UpdateError(
            "The release receipt does not identify the macOS disk image."
            if sys.platform == "darwin"
            else "The release receipt does not identify the Windows installer."
        )

    receipt_sha256 = _sha256_from_digest(target.get("sha256"))
    if not receipt_sha256:
        raise UpdateError("The release receipt has no valid installer SHA256.")
    try:
        receipt_size = int(target.get("size_bytes") or 0)
    except (TypeError, ValueError) as error:
        raise UpdateError("The release receipt has an invalid installer size.") from error
    if receipt_size <= 0:
        raise UpdateError("The release receipt has no valid installer size.")
    if installer_size > 0 and receipt_size != installer_size:
        raise UpdateError("The release receipt installer size does not match the release asset.")
    published_sha256 = _sha256_from_digest(installer_sha256)
    if published_sha256 and receipt_sha256 != published_sha256:
        raise UpdateError("The release receipt installer SHA256 does not match the release asset.")
    return receipt_sha256, receipt_size, commit.lower(), receipt.get("artifact_signing_enabled") is True


# X-233: the organisation this project's Windows binaries are signed by.
#
# Matched on the organisation rather than a full distinguished name, because
# the DN carries a serial and locality that change when the certificate is
# reissued, and a check that breaks on renewal is a check somebody deletes.
EXPECTED_PUBLISHER = "Knight AI+AV"

# The ratchet's memory. A file rather than config, because it must survive a
# settings reset: "start over" is about the user's data, not about lowering a
# security guarantee this install has already met.
_SIGNING_SEEN_NAME = ".authenticode-seen"


def signing_has_been_seen() -> bool:
    """Whether this install has ever accepted a properly signed update."""
    try:
        from .config import app_dir

        return (app_dir() / _SIGNING_SEEN_NAME).exists()
    except Exception:
        # Fail OPEN here and only here: an unreadable data directory must not
        # brick updates for someone who has never seen a signed release. The
        # signature check itself still fails closed.
        #
        # Logged rather than swallowed, because this is the one path that can
        # quietly lower the bar. If it starts happening every launch, the
        # ratchet has stopped ratcheting and nothing else would say so.
        log.warning("could not read the Authenticode ratchet; not requiring a signature", exc_info=True)
        return False


def remember_signing_was_seen() -> None:
    try:
        from .config import app_dir

        (app_dir() / _SIGNING_SEEN_NAME).write_text("1", encoding="utf-8")
    except OSError:
        log.debug("could not record that a signed update was seen", exc_info=True)


def authenticode_required(receipt_says: bool) -> bool:
    """Whether this install must see a valid signature, ratchet included.

    This is POLICY, and it lives here rather than inside verify_installer on
    purpose. verify_installer is the mechanism: give it a checksum and a flag
    and it does exactly what its arguments say. If it also reached out and read
    a file on this machine, then `verify_installer(path, expected_sha256=x)`
    would mean two different things on two different machines, which is not a
    contract anybody can test or reason about.

    So the two real entry points -- downloading an update, and launching one --
    ask this question once and pass the answer down.
    """
    return bool(receipt_says) or signing_has_been_seen()


def publisher_is_ours(subject: str) -> bool:
    """Whether an Authenticode subject belongs to this project.

    Deliberately case-insensitive and substring-based: a Windows subject looks
    like `CN=Knight AI+AV LLC, O=Knight AI+AV LLC, L=..., C=US`, and the parts
    around the organisation are not stable across a reissue.
    """
    return EXPECTED_PUBLISHER.lower() in (subject or "").lower()


def verify_authenticode_signature(path: Path) -> str:
    """Require a Windows-trusted Authenticode signature and return its subject."""

    if os.name != "nt":
        raise UpdateError("A signed Windows update can only be verified on Windows.")
    literal_path = str(path).replace("'", "''")
    script = (
        f"$signature = Get-AuthenticodeSignature -LiteralPath '{literal_path}'; "
        "$subject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { '' }; "
        "[ordered]@{ status = [string]$signature.Status; subject = [string]$subject } | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise UpdateError(f"Could not verify the installer publisher signature: {error}.") from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "PowerShell signature verification failed."
        raise UpdateError(detail)
    try:
        signature = json.loads(result.stdout.strip())
    except json.JSONDecodeError as error:
        raise UpdateError("Windows returned an unreadable installer signature result.") from error
    status = str(signature.get("status") or "") if isinstance(signature, dict) else ""
    subject = str(signature.get("subject") or "").strip() if isinstance(signature, dict) else ""
    if status.lower() != "valid" or not subject:
        raise UpdateError(f"The signed release receipt requires a valid Windows publisher signature; status was {status or 'Unknown'}.")
    # X-233: "valid" answers "did Windows trust the chain", not "is this us".
    #
    # An attacker who can serve an installer can sign it with their OWN
    # certificate. Windows reports Valid, because it IS valid, and the check
    # passed on a file signed by somebody else entirely. Reading the subject
    # and then not comparing it is the whole gap: the value was already here,
    # returned and discarded.
    if not publisher_is_ours(subject):
        raise UpdateError(
            "The installer is signed, but not by Knight AI+AV. Refusing to run it. "
            f"Publisher was: {subject}"
        )
    return subject


def verify_installer(
    path: Path,
    *,
    expected_sha256: str,
    expected_size: int = 0,
    require_authenticode: bool = False,
) -> str:
    """Verify the exact installer bytes immediately before they are trusted."""

    if not path.exists() or not path.is_file():
        raise UpdateError(f"Installer was not found: {path}")
    expected = _sha256_from_digest(expected_sha256)
    if not expected:
        raise UpdateError("The installer has no valid published SHA256 checksum. Refusing to launch it.")
    try:
        actual_size = path.stat().st_size
        actual = _file_sha256(path)
    except OSError as error:
        raise UpdateError(f"Could not verify update installer: {error}.") from error
    if expected_size > 0 and actual_size != expected_size:
        raise UpdateError(
            "Downloaded update failed size verification. "
            f"Expected {expected_size} bytes, got {actual_size} bytes."
        )
    if actual.lower() != expected.lower():
        raise UpdateError(
            "Downloaded update failed SHA256 verification. "
            f"Expected {expected.lower()}, got {actual.lower()}."
        )
    # X-233: does the signature get checked. The RATCHET that decides this is
    # in authenticode_required(); by the time it reaches here the question has
    # been answered, and this function does what its arguments say and no more.
    if require_authenticode:
        # Parity union, corrected by the mac guard that caught the first
        # draft: the signing RATCHET is Windows doctrine -- it remembers that
        # an Authenticode-signed update was accepted and refuses unsigned
        # downgrades after. Gatekeeper acceptance is macOS's own enforcement;
        # stamping there armed the ratchet during ordinary test runs.
        if sys.platform == "darwin":
            verify_gatekeeper_acceptance(path)
        else:
            verify_authenticode_signature(path)
            remember_signing_was_seen()
    return actual



def verify_gatekeeper_acceptance(path: Path) -> str:
    """The macOS counterpart of the Authenticode check, and just as mandatory.

    `require_authenticode` reaching macOS previously raised "A signed Windows
    update can only be verified on Windows" -- which aborted the *download*, not
    just the launch, so a signed release could never be installed here at all.
    Skipping the check instead would have been worse: it is the only thing
    proving the disk image is the publisher's.

    spctl is the assessment Gatekeeper itself performs when someone opens a
    downloaded image, so this asks the same question the OS will ask, before
    spending the user's attention on it. A notarised, stapled image passes
    offline; an unsigned one does not.
    """
    result = subprocess.run(
        ["/usr/sbin/spctl", "--assess", "--type", "open",
         "--context", "context:primary-signature", str(path)],
        capture_output=True,
    )
    detail = (result.stderr or b"").decode("utf-8", "replace").strip()
    if result.returncode != 0:
        raise UpdateError(
            "The update disk image is not accepted by Gatekeeper "
            f"({detail or 'unsigned or not notarised'}). Refusing to open it."
        )
    return detail


def _installer_checksum(checksum_url: str, installer_name: str, timeout: float) -> str:
    if not checksum_url:
        return ""
    try:
        return _sha256_from_sums(_read_text_url(checksum_url, timeout), installer_name)
    except (urllib.error.URLError, TimeoutError, OSError):
        return ""


def _newest_release(payload: Any, *, channel: str) -> dict[str, Any]:
    """Pick the semantically newest published release from a list payload.

    GitHub sorts by creation time, which can place a republished older tag ahead
    of the newest version, so selection is by version rather than by position.
    """
    releases = [
        release
        for release in payload
        if isinstance(release, dict) and not release.get("draft", False) and release.get("tag_name")
    ]
    if not releases:
        raise UpdateError(f"No published GitHub release found on the {channel} channel.")
    selected = releases[0]
    for release in releases[1:]:
        if compare_versions(str(release.get("tag_name", "")), str(selected.get("tag_name", ""))) > 0:
            selected = release
    return selected


def _notes_spanning_versions(current: str, latest: str, latest_body: str, timeout: float) -> str:
    """Notes for the whole gap, not only the newest release.

    Someone updating 0.4.30 -> 0.4.33 skipped two releases, and showing them
    only 0.4.33's notes presents days of work as one small change -- the
    update looks thinner than it is, which is exactly backwards as a reason
    to install it. So a multi-version jump opens with a highlights digest --
    each skipped version's section headings as bullets -- and the full
    details follow, newest first.

    Every body shown here is a CHANGELOG section, which is written for the
    public by rule (tests/test_release_notes_are_public_safe.py holds the
    whole file to that). Any failure to fetch the extra releases falls back
    to the latest body alone: worse notes must never mean no update.
    """
    try:
        gap: list[dict[str, Any]] = []
        releases_url = _releases_api_url(_update_repository())
        with urllib.request.urlopen(_request(releases_url, timeout), timeout=timeout) as response:
            listed = json.loads(response.read().decode("utf-8"))
        if isinstance(listed, list):
            for release in listed:
                tag = str(release.get("tag_name", ""))
                if is_newer_version(tag, current) and not is_newer_version(tag, latest):
                    gap.append(release)
        import functools

        gap.sort(
            key=functools.cmp_to_key(
                lambda a, b: compare_versions(str(a.get("tag_name", "")), str(b.get("tag_name", "")))
            ),
            reverse=True,
        )
        if len(gap) <= 1:
            return latest_body
        digest: list[str] = [f"New since {current} - {len(gap)} updates.", ""]
        for release in gap:
            tag = str(release.get("tag_name", "")).lstrip("v")
            digest.append(f"**{tag}**")
            headline = [
                line.lstrip("# ").strip()
                for line in str(release.get("body") or "").splitlines()
                if line.startswith("### ")
            ]
            digest.extend(f"- {title}" for title in headline or ["Improvements and fixes"])
            digest.append("")
        digest.append("---")
        digest.append("")
        for release in gap:
            digest.append(f"## {str(release.get('tag_name', '')).lstrip('v')}")
            digest.append(str(release.get("body") or "").strip())
            digest.append("")
        return "\n".join(digest).strip()
    except Exception:
        # The digest is a nicety; the update is the point. Logged, because a
        # digest that silently never appears would read as "this feature does
        # not exist" on every machine where the second fetch fails.
        log.debug("multi-version notes unavailable; showing the latest release only", exc_info=True)
        return latest_body


def _latest_release_payload(timeout: float, channel: str = "stable") -> dict[str, Any]:
    repository = _update_repository()
    releases_url = _releases_api_url(repository)
    url = releases_url if channel == "beta" else _latest_release_api_url(repository)
    try:
        with urllib.request.urlopen(_request(url, timeout), timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404 and channel != "beta":
            # GitHub's "latest" endpoint excludes prereleases and 404s when
            # every release is one. Talk DAT! has shipped nothing but betas, so
            # the default channel resolved to 404 on every check and no user has
            # ever been able to update from inside the app. Falling back to the
            # release list means the updater keeps working while the product is
            # in beta, and needs no change on the day a stable build ships.
            try:
                with urllib.request.urlopen(_request(releases_url, timeout), timeout=timeout) as response:
                    listed = json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
                raise UpdateError("No official Talk DAT! release has been published yet.") from error
            if isinstance(listed, list) and listed:
                return _newest_release(listed, channel=channel)
            raise UpdateError("No official Talk DAT! release has been published yet.") from error
        if error.code == 404:
            raise UpdateError("No official Talk DAT! release has been published yet.") from error
        raise UpdateError(f"Talk DAT! release check failed: HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        raise UpdateError(f"Could not reach the Talk DAT! update service: {error.reason}.") from error
    except (TimeoutError, json.JSONDecodeError, OSError) as error:
        raise UpdateError(f"Could not read GitHub release information: {error}.") from error
    if channel == "beta" and isinstance(payload, list):
        return _newest_release(payload, channel="beta")
    if not isinstance(payload, dict):
        raise UpdateError("The Talk DAT! update service returned an unexpected response.")
    return payload


# The marker publish_release.py stamps into the release body. Absent means
# green: an update is optional unless someone deliberately says otherwise.
FORCED_UPDATE_MARKER = "<!-- talk-dat-update: red -->"


def release_severity(body: str) -> str:
    """red (install it for them) or green (offer it)."""
    return "red" if FORCED_UPDATE_MARKER in (body or "") else "green"


def check_for_update(current_version: str = APP_VERSION, timeout: float = 8.0, channel: str = "stable") -> UpdateInfo:
    payload = _latest_release_payload(timeout, channel if channel in {"stable", "beta"} else "stable")
    tag_name = str(payload.get("tag_name") or "").strip()
    latest_version = tag_name[1:] if tag_name.lower().startswith("v") else tag_name
    if not latest_version:
        raise UpdateError("The latest GitHub release has no version tag.")

    assets = payload.get("assets", [])
    installer_url = ""
    installer_name = INSTALLER_ASSET_NAME
    installer_size = 0
    installer_sha256 = ""
    checksum_url = ""
    receipt_url = ""
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "")
            if _is_installer_for_this_platform(name):
                installer_name = name
                installer_url = str(asset.get("browser_download_url") or "")
                installer_size = int(asset.get("size") or 0)
                installer_sha256 = _sha256_from_digest(asset.get("digest"))
            elif name.lower() == CHECKSUM_ASSET_NAME.lower():
                checksum_url = str(asset.get("browser_download_url") or "")
            elif name.lower() == RECEIPT_ASSET_NAME.lower():
                receipt_url = str(asset.get("browser_download_url") or "")
        if not installer_sha256 and checksum_url:
            installer_sha256 = _installer_checksum(checksum_url, installer_name, timeout)

    receipt_commit = ""
    receipt_verified = False
    artifact_signing_enabled = False
    if receipt_url:
        receipt = _read_receipt_url(receipt_url, timeout)
        installer_sha256, installer_size, receipt_commit, artifact_signing_enabled = verify_release_receipt(
            receipt,
            release_tag=tag_name,
            installer_name=installer_name,
            installer_size=installer_size,
            installer_sha256=installer_sha256,
        )
        receipt_verified = True

    release_url = str(payload.get("html_url") or APP_RELEASES_URL)
    notes = _notes_spanning_versions(
        current_version,
        latest_version,
        str(payload.get("body") or ""),
        timeout,
    )
    return UpdateInfo(
        severity=release_severity(str(payload.get("body") or "")),
        current_version=current_version,
        latest_version=latest_version,
        available=is_newer_version(latest_version, current_version),
        release_url=release_url,
        installer_url=installer_url,
        installer_name=installer_name,
        installer_size=installer_size,
        installer_sha256=installer_sha256,
        checksum_url=checksum_url,
        published_at=str(payload.get("published_at") or ""),
        release_notes=notes,
        receipt_url=receipt_url,
        receipt_commit=receipt_commit,
        receipt_verified=receipt_verified,
        artifact_signing_enabled=artifact_signing_enabled,
    )


def updates_dir() -> Path:
    path = app_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def prune_stale_installers(keep: Path | None = None) -> int:
    """Delete downloaded installers that can no longer serve any update.

    Thirty of these were found parked on the founder's machine -- 6.5 GB of
    Talk-Dat-Setup-*.exe going back a month, one per release the auto-download
    fetched. Each was useful for exactly one hop and worthless the moment a
    newer release existed, but nothing ever deleted them, so the pile grew a
    quarter-gigabyte per release forever.

    Removed: every downloaded installer except `keep` (the one just fetched,
    still needed for the launch handoff) and any installer NEWER than the
    running version (a predownload still waiting for its moment). Half-written
    `.part` files are always removed -- a crash mid-download is the only way
    one survives, and it can never be trusted again.
    """
    removed = 0
    try:
        directory = updates_dir()
        candidates = list(directory.glob("Talk-Dat-Setup-*.exe")) + list(
            directory.glob("Talk-Dat-Setup-*.part")
        )
    except OSError as error:
        log.warning("could not scan the updates folder for stale installers: %s", error)
        return 0
    for path in candidates:
        if keep is not None and path == keep:
            continue
        version = path.stem.removeprefix("Talk-Dat-Setup-")
        if path.suffix == ".exe" and version and is_newer_version(version, APP_VERSION):
            continue
        if path.suffix == ".part":
            # X-535: the next launch is the ONLY place an abandoned download
            # can still be reported. The install worker is a daemon thread, so
            # quitting mid-download tears it down without unwinding -- no
            # except, no finally, nothing reaches the log while it happens.
            # This half-written file is the sole surviving evidence, and
            # folding it into the bare count below hid twelve hours of a
            # closed, two-versions-stale app behind "pruned 1 stale installer".
            try:
                partial = path.stat().st_size
            except OSError:
                partial = 0
            log.warning(
                "interrupted update download found: %s stopped at %d bytes; "
                "discarding it, the next check will fetch it again",
                version or path.name,
                partial,
            )
        try:
            path.unlink()
            removed += 1
        except OSError as error:
            # A locked file just stays for the next launch to collect.
            log.warning("could not remove stale installer %s: %s", path.name, error)
    if removed:
        log.info("pruned %d stale update installer(s) from %s", removed, updates_dir())
    return removed


def download_installer(
    info: UpdateInfo,
    progress: ProgressCallback | None = None,
    timeout: float = 30.0,
    *,
    require_checksum: bool = True,
) -> Path:
    if not info.installer_url:
        if sys.platform == "darwin":
            raise UpdateError("This release does not include a macOS disk image yet.")
        raise UpdateError("The latest release does not include the Windows setup EXE yet.")
    safe_version = re.sub(r"[^0-9A-Za-z._-]+", "-", info.latest_version).strip("-") or "latest"
    suffix = ".dmg" if sys.platform == "darwin" else ".exe"
    destination = updates_dir() / f"Talk-Dat-Setup-{safe_version}{suffix}"
    temp_destination = destination.with_suffix(".part")
    try:
        with urllib.request.urlopen(_download_request(info.installer_url), timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with temp_destination.open("wb") as file:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    file.write(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, total)
        expected_sha256 = info.installer_sha256 or _installer_checksum(info.checksum_url, info.installer_name, timeout)
        if require_checksum and not expected_sha256:
            raise UpdateError(
                "The update downloaded, but no SHA256 checksum was published for the installer. "
                "Refusing to launch an unverified EXE."
            )
        if expected_sha256:
            verify_installer(
                temp_destination,
                expected_sha256=expected_sha256,
                expected_size=info.installer_size,
                require_authenticode=authenticode_required(info.artifact_signing_enabled),
            )
        temp_destination.replace(destination)
    except urllib.error.URLError as error:
        raise UpdateError(f"Could not download update: {error.reason}.") from error
    except OSError as error:
        raise UpdateError(f"Could not save update installer: {error}.") from error
    finally:
        try:
            if temp_destination.exists():
                temp_destination.unlink()
        except OSError:
            pass
    prune_stale_installers(keep=destination)
    return destination


def launch_installer(
    path: Path,
    *,
    expected_sha256: str,
    expected_size: int = 0,
    require_authenticode: bool = False,
    silent: bool = True,
) -> None:
    # Revalidate cached or predownloaded bytes at the handoff boundary. This
    # closes the gap between download verification and process launch.
    #
    # The ratchet is applied HERE too, not only on download: an installer that
    # was fetched before signing went live still sits on disk, and launching it
    # is the moment that actually matters.
    verify_installer(
        path,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
        require_authenticode=authenticode_required(require_authenticode),
    )
    if sys.platform == "darwin":
        _open_disk_image(path)
        return
    try:
        if silent:
            subprocess.Popen(
                [str(path), "--silent-install"],
                cwd=str(path.parent),
                close_fds=True,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        else:
            os.startfile(str(path))  # type: ignore[attr-defined]
    except OSError as error:
        raise UpdateError(f"Could not launch installer: {error}.") from error



def _open_disk_image(path: Path) -> None:
    """Hand the verified disk image to the user, mounted and open.

    The Windows path executes the installer directly. Doing that with a .dmg
    yields "Could not launch installer: [Errno 13] Permission denied" after a
    full multi-hundred-megabyte download -- the file is a filesystem image, not
    a program.

    The copy into /Applications is deliberately left to the person. Replacing a
    running application from inside itself means unmounting, copying over the
    bundle currently executing, and relaunching, and getting any step of that
    wrong leaves no working copy on the machine. Drag-to-Applications is the
    convention on this platform and the image is built with that layout, so the
    honest move is to open it and get out of the way.
    """
    result = subprocess.run(["/usr/bin/open", str(path)], capture_output=True)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip() or "unknown error"
        raise UpdateError(f"Could not open the update disk image: {detail}.")


def record_version_seen(config: dict[str, Any]) -> None:
    updates = config.setdefault("updates", {})
    now = int(time.time())
    updates.setdefault("first_seen_version", APP_VERSION)
    updates["current_version"] = APP_VERSION
    updates["last_run_at"] = now


def bundled_changelog_section(version: str) -> str:
    """The build's own CHANGELOG section -- the What's New tab's offline floor.

    The tab must never open empty (his rule: details for EVERY update,
    always), and the network is not allowed to be a precondition for that.
    The installer ships CHANGELOG.md beside the app; this reads the current
    version's section from it, and degrades to one honest line rather than
    to nothing.
    """
    import sys
    from pathlib import Path

    roots = []
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        roots.append(Path(bundle))
    roots.append(Path(__file__).resolve().parents[1])
    for root in roots:
        for candidate in (root / "CHANGELOG.md", root / "docs" / "CHANGELOG.md"):
            try:
                text = candidate.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            marker = f"## {version}"
            if marker in text:
                return text.split(marker, 1)[1].split("\n## ", 1)[0].strip()
    return "Improvements and fixes across the app."
