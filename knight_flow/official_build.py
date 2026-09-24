"""One switch for every connection to Knight AI+AV's own services.

Talk DAT! is open source under Apache-2.0, and the same source builds two kinds
of app:

* OFFICIAL: the signed releases Knight AI+AV publishes (the Windows installer,
  the portable zip, the Mac disk image). The release build bakes
  ``OFFICIAL = True`` into ``knight_flow/_build_flags.py`` (written by
  ``scripts/write_build_flags.py``; the file is generated, never committed).
  These builds use Knight's services: the optional account at api.talkdat.app,
  the anonymous app counts, the feedback inbox, preference sync, and the update
  check against the ``KNIGHT-AI-AV/talk-dat-releases`` GitHub releases.
* SOURCE: everything else. A checkout started with ``run.ps1``, an app you
  built yourself, a fork. By default a source build contacts NONE of those
  services. Sign-in, feedback upload, preference sync, the anonymous counts
  and the update check are all off. Dictation is unaffected: it never needed
  any of them.

Every call site that reaches a Knight service asks this module first, and no
other module in ``knight_flow`` names Knight's hosts
(``tests/test_official_build.py`` enforces both).

Pointing a build at your own endpoints (documented in docs/NETWORK.md):

* at run time, ``TALKDAT_API_BASE=https://your.server`` (account, feedback,
  prefs; the counts too, but only in an official build) and
  ``TALKDAT_UPDATE_REPOSITORY=owner/repo`` (GitHub releases
  the updater reads); the config key ``licensing.api_base`` works too;
* at build time, ``TALKDAT_BUILD_API_BASE`` / ``TALKDAT_BUILD_UPDATE_REPOSITORY``
  are baked into ``_build_flags.py`` by ``scripts/write_build_flags.py``.

``TALKDAT_NO_PHONE_HOME=1`` turns every one of these connections off, in any
build.

The anonymous usage counts have their own setting, ``privacy.share_usage_counts``
(Settings > Privacy, "Share anonymous usage counts"; owner decision
2026-09-23). It is on by default in an official build and off, always, in a
source build. Local-only privacy (``privacy.local_only``) governs what a person
dictates -- audio, text and their own provider keys -- and does NOT decide the
counts, which carry none of that.

Pure stdlib, no tkinter, importable by tests and by the build scripts.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# Knight AI+AV's services. The ONLY place in knight_flow these are written.
KNIGHT_API_BASE = "https://api.talkdat.app"
KNIGHT_PRODUCT_URL = "https://www.talkdat.app"
KNIGHT_UPDATE_REPOSITORY = "KNIGHT-AI-AV/talk-dat-releases"
KNIGHT_HOST_SUFFIX = "talkdat.app"

ENV_API_BASE = "TALKDAT_API_BASE"
ENV_UPDATE_REPOSITORY = "TALKDAT_UPDATE_REPOSITORY"
ENV_NO_PHONE_HOME = "TALKDAT_NO_PHONE_HOME"

SIGN_IN_OFF = (
    "Sign-in is not available in this build. Official Talk DAT! downloads from "
    "talkdat.app include it; a build from source signs in only when it is pointed "
    "at an account service (see docs/NETWORK.md). Dictation works the same either way."
)
UPDATES_OFF = (
    "Update checks are off in this build. Official Talk DAT! downloads update "
    "themselves; a build from source updates when you pull and rebuild it."
)

# The owner's words for the switch (2026-09-23). Settings > Privacy and
# first-run setup show exactly these; settings-fields.json and setup.js carry
# the same text and tests/test_usage_counts_setting.py keeps them equal.
USAGE_COUNTS_LABEL = "Share anonymous usage counts"
USAGE_COUNTS_DETAIL = "First open, first dictation, still in use, day 7. Never your audio or text."
USAGE_COUNTS_LINE = (
    "Share anonymous usage counts: first open, first dictation, still in use, day 7. "
    "Never your audio or text."
)

_OFF_WORDS = {"off", "none", "0", "false", "no"}
_ON_WORDS = {"1", "true", "yes", "on"}


def _load_flags_module():
    """The generated module. A STATIC import on purpose: PyInstaller follows
    import statements, not importlib calls, and a frozen official app that
    lost this module would ship with every service switched off."""
    from . import _build_flags

    return _build_flags


def _read_flags(load=_load_flags_module) -> tuple[bool, str, str]:
    """(official, baked api base, baked update repository) from _build_flags.

    Absent means a source build. A broken file also means a source build, and
    says so in the log: failing towards "contact nothing" is the safe side.
    """
    try:
        module = load()
    except ImportError:
        return False, "", ""
    except Exception:
        log.warning("build flags unreadable; treating this as a source build", exc_info=True)
        return False, "", ""
    official = getattr(module, "OFFICIAL", False) is True
    api = str(getattr(module, "API_BASE", "") or "").strip().rstrip("/")
    repository = str(getattr(module, "UPDATE_REPOSITORY", "") or "").strip()
    return official, api, repository


OFFICIAL, BAKED_API_BASE, BAKED_UPDATE_REPOSITORY = _read_flags()


def is_official() -> bool:
    """True only in a build Knight AI+AV released. Read at call time, so a
    test can patch the module attribute."""
    return OFFICIAL is True


def build_kind() -> str:
    return "official" if is_official() else "source"


def phone_home_disabled() -> bool:
    """The kill switch: TALKDAT_NO_PHONE_HOME=1 turns every Knight connection off."""
    return str(os.environ.get(ENV_NO_PHONE_HOME, "")).strip().lower() in _ON_WORDS


def is_knight_host(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host == KNIGHT_HOST_SUFFIX or host.endswith("." + KNIGHT_HOST_SUFFIX)


def _clean_base(value: Any) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text or text.lower() in _OFF_WORDS:
        return ""
    return text


def _configured_api_base(config: dict[str, Any] | None) -> str:
    if not isinstance(config, dict):
        return ""
    licensing = config.get("licensing")
    if not isinstance(licensing, dict):
        return ""
    return _clean_base(licensing.get("api_base"))


def api_base(config: dict[str, Any] | None = None) -> str:
    """Where account, feedback, prefs and count requests go. "" means nowhere.

    Order: the kill switch, then TALKDAT_API_BASE, then the build. An official
    build honours ``licensing.api_base`` (staging, tests) and otherwise uses
    Knight's service. A source build uses a baked or configured endpoint, but
    never Knight's host merely because an old config file names it: every
    official install wrote that default into config.json, and a fork run on the
    same machine reads the same file.
    """
    if phone_home_disabled():
        return ""
    raw_env = os.environ.get(ENV_API_BASE)
    if raw_env is not None and raw_env.strip():
        return _clean_base(raw_env)
    configured = _configured_api_base(config)
    if is_official():
        # A fork's own official build bakes its endpoint; the Knight default an
        # old config.json carries must not override that.
        if configured and not (BAKED_API_BASE and is_knight_host(configured)):
            return configured
        return BAKED_API_BASE or KNIGHT_API_BASE
    if configured and not is_knight_host(configured):
        return configured
    return BAKED_API_BASE


def service_url(config: dict[str, Any] | None, path: str) -> str:
    """The full URL for ``path`` on the account service, or "" when it is off."""
    base = api_base(config)
    if not base:
        return ""
    return base + "/" + str(path or "").lstrip("/")


def share_usage_counts(config: dict[str, Any] | None) -> bool:
    """The person's "Share anonymous usage counts" choice, as saved.

    ``privacy.share_usage_counts``: on unless they turned it off (an absent key
    is the default, on). A privacy section that is not a dict, or a value that
    is not a recognisable yes, reads as OFF: failing towards sending nothing.
    This is only the choice; activation_api_base() also needs an official
    build and no kill switch.
    """
    if not isinstance(config, dict) or "privacy" not in config:
        return True
    privacy = config.get("privacy")
    if not isinstance(privacy, dict):
        return False
    if "share_usage_counts" not in privacy:
        return True
    value = privacy.get("share_usage_counts")
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in _ON_WORDS
    return False


def usage_counts_available() -> bool:
    """Whether this build can send the counts at all: an official build with
    the kill switch off. Settings and first-run setup show the toggle only
    then, so a source build never offers a switch that does nothing."""
    return is_official() and not phone_home_disabled()


def activation_api_base(config: dict[str, Any] | None) -> str:
    """Where the anonymous usage counts go, or "" when they must not be sent.

    Off in a source build (even one pointed at its own server: a fork that
    wants counts builds as official with its own baked endpoint), off with the
    kill switch, and off when the person turned "Share anonymous usage counts"
    off. Local-only privacy does not enter into it: that setting keeps audio
    and text on the computer, and the counts carry neither.
    """
    if not usage_counts_available() or not share_usage_counts(config):
        return ""
    return api_base(config)


def update_repository() -> str:
    """The GitHub ``owner/repo`` whose releases the updater reads, or "".

    Official builds read Knight's releases only; the updater also checks the
    release receipt and the publisher signature against it. A source build
    checks nothing unless it is given a repository of its own.
    """
    if phone_home_disabled():
        return ""
    raw_env = os.environ.get(ENV_UPDATE_REPOSITORY)
    if raw_env is not None and raw_env.strip():
        value = raw_env.strip()
        return "" if value.lower() in _OFF_WORDS else value
    if is_official():
        return BAKED_UPDATE_REPOSITORY or KNIGHT_UPDATE_REPOSITORY
    return BAKED_UPDATE_REPOSITORY


def describe(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """What this build will contact, for the log and diagnostics. No secrets."""
    return {
        "build": build_kind(),
        "api_base": api_base(config),
        "anonymous_counts": bool(activation_api_base(config)),
        "share_usage_counts": share_usage_counts(config),
        "update_repository": update_repository(),
        "phone_home_disabled": phone_home_disabled(),
    }


def render_build_flags(*, official: bool, api_base: str = "", update_repository: str = "") -> str:
    """The text of knight_flow/_build_flags.py. Kept beside the reader so the
    two cannot disagree about the format."""
    return (
        '"""Generated by scripts/write_build_flags.py at build time. Never commit."""\n'
        f"OFFICIAL = {bool(official)!r}\n"
        f"API_BASE = {str(api_base or '').strip().rstrip('/')!r}\n"
        f"UPDATE_REPOSITORY = {str(update_repository or '').strip()!r}\n"
    )
