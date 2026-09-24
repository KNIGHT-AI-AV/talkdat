"""X-26: smart Do-Not-Disturb. Dictation keeps working; the noise stops.

Mayowa's spec: when the user is plausibly on a call or sharing a screen,
everything still WORKS -- "but just doesn't pop over or make sounds". So this
module answers one question, cheaply: does the moment look like a meeting?

The heuristic is deliberately humble: a conferencing app having a process
alive. It catches the embarrassing cases (a chime through a Zoom mic, a
pop-over on a shared screen) without any fragile screen-capture detection,
and being wrong in the quiet direction costs one unplayed sound.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import Any

MEETING_PROCESSES = {
    "zoom.exe",
    "teams.exe",
    "ms-teams.exe",
    "webex.exe",
    "webexmta.exe",
    "slack.exe",  # huddles
    "discord.exe",
    "skype.exe",
    "gotomeeting.exe",
}

# The same apps as macOS names them. NSWorkspace reports bundle identifiers
# and localized names, neither of which ends in .exe, so the Windows set above
# would never match and every Mac would read as "not in a meeting".
MEETING_BUNDLE_MARKERS = (
    "us.zoom.xos",
    "com.microsoft.teams",
    "com.cisco.webexmeetingsapp",
    "com.webex.meetingmanager",
    "com.tinyspeck.slackmacgap",   # huddles
    "com.hnc.discord",
    "com.skype.skype",
    "com.logmein.gotomeeting",
    "com.google.chrome.app.kjgfgldnnfoeklkmfkjfagphfepbbdan",  # Meet PWA
)

_CACHE_SECONDS = 10.0
_state: dict[str, Any] = {"at": 0.0, "quiet": False}
# X-411: the scan below is `tasklist`, 1.4 to 2.5 s on the founder's PC, and it
# used to run inline at the start chime and the landing chime, so every
# dictation more than ten seconds after the last one paid it twice. It runs
# on a thread now; callers get the last answer at once and never wait.
_refresh_lock = threading.Lock()
_refresh_thread: threading.Thread | None = None


def _running_bundle_ids_mac() -> set[str]:
    """Bundle identifiers of every running application, from NSWorkspace.

    tasklist does not exist there, so the Windows probe returned nothing and a
    Mac was never quiet during a call. NSWorkspace answers the same question
    without spawning anything, and needs no permission: it reports only what
    is running, not what is on screen.
    """
    from AppKit import NSWorkspace

    names: set[str] = set()
    for app in NSWorkspace.sharedWorkspace().runningApplications() or ():
        bundle = app.bundleIdentifier()
        if bundle:
            names.add(str(bundle).lower())
    return names


def _scan_for_meeting() -> bool:
    """One scan, the platform's own way. Runs on the refresh thread only."""
    if sys.platform == "darwin":
        running = _running_bundle_ids_mac()
        return any(marker in name for name in running for marker in MEETING_BUNDLE_MARKERS)
    return bool(MEETING_PROCESSES & _running_process_names())


def _running_process_names() -> set[str]:
    out = subprocess.run(
        ["tasklist", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        timeout=5,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    names: set[str] = set()
    for line in (out.stdout or "").splitlines():
        if line.startswith('"'):
            names.add(line.split('","', 1)[0].strip('"').lower())
    return names


def meeting_in_progress(config: dict[str, Any] | None = None, *, now: float | None = None) -> bool:
    """Cached ~10s so callers may ask on every pop-over without cost.
    `notifications.meeting_quiet: false` opts out."""
    if config is not None and not bool(
        (config.get("notifications", {}) or {}).get("meeting_quiet", True)
    ):
        return False
    moment = time.monotonic() if now is None else now
    if moment - float(_state["at"]) >= _CACHE_SECONDS:
        _refresh_in_background(moment)
    return bool(_state["quiet"])


def _refresh_in_background(moment: float) -> None:
    global _refresh_thread
    with _refresh_lock:
        if _refresh_thread is not None and _refresh_thread.is_alive():
            return
        # Stamp first, so a burst of callers during the scan does not start
        # a second one; a failed scan is retried after the usual window.
        _state["at"] = moment

        def worker() -> None:
            try:
                _state["quiet"] = _scan_for_meeting()
            except Exception:
                # A probe failure reads as not-in-a-meeting: being wrong in the
                # loud direction is a chime nobody wanted, being wrong in the
                # quiet direction is a feature that silently stopped working.
                _state["quiet"] = False

        _refresh_thread = threading.Thread(target=worker, name="TalkDatMeetingProbe", daemon=True)
        _refresh_thread.start()


def _wait_for_refresh(timeout: float) -> None:
    """Tests only: block until the background scan, if any, has finished."""
    thread = _refresh_thread
    if thread is not None:
        thread.join(timeout)


def _reset_for_tests() -> None:
    global _refresh_thread
    with _refresh_lock:
        _state["at"] = 0.0
        _state["quiet"] = False
        _refresh_thread = None
