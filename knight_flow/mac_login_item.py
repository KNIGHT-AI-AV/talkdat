"""Run-at-login on macOS, via a LaunchAgent.

Windows registers a Start Menu Startup shortcut from its installer. macOS has no
equivalent the installer can drop, and a .dmg drag-install has no installer step
at all, so the app manages its own login item: a per-user LaunchAgent plist in
~/Library/LaunchAgents that launches the bundle at login.

There is deliberately no UI wired to this yet. The Windows build offers the
option only from its installer, not in-app, so adding an in-app toggle here
would be inventing a feature the product does not have on the other platform.
This is the mechanism, ready for the day a version adds the setting; until then
enable()/disable() are callable and tested, and nothing calls them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import mac_support

LABEL = "com.knightaiav.talkdat.login"


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _bundle_path() -> Path | None:
    """The .app this code is running from, or None outside a bundle.

    A login item that points at a checkout is useless -- there is nothing to
    launch at login but a source tree -- so enabling is refused unless we are
    running from a real bundle.
    """
    if not getattr(sys, "frozen", False):
        return None
    try:
        # Contents/MacOS/<exe> -> the .app is three parents up.
        executable = Path(sys.executable).resolve()
        app = executable.parent.parent.parent
        return app if app.suffix == ".app" and app.is_dir() else None
    except Exception:
        return None


def is_enabled() -> bool:
    return mac_support.IS_MAC and _plist_path().exists()


def enable() -> tuple[bool, str]:
    """Install and load the LaunchAgent. Returns (ok, human message)."""
    if not mac_support.IS_MAC:
        return False, "Run at login is only available on macOS here."
    bundle = _bundle_path()
    if bundle is None:
        return False, "Run at login needs the installed app, not a source checkout."

    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f"  <key>Label</key><string>{LABEL}</string>\n"
        "  <key>ProgramArguments</key>\n"
        f"  <array><string>/usr/bin/open</string><string>{bundle}</string></array>\n"
        "  <key>RunAtLoad</key><true/>\n"
        # LimitLoadToSessionType Aqua: a login item, not a background daemon, so
        # it does not try to launch in a headless or login-window context.
        "  <key>LimitLoadToSessionType</key><string>Aqua</string>\n"
        "</dict></plist>\n"
    )
    try:
        path = _plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plist, encoding="utf-8")
        # bootout any stale copy first; ignore its result, then bootstrap fresh.
        uid = _uid()
        subprocess.run(["/bin/launchctl", "bootout", f"gui/{uid}/{LABEL}"],
                       capture_output=True)
        result = subprocess.run(
            ["/bin/launchctl", "bootstrap", f"gui/{uid}", str(path)],
            capture_output=True,
        )
        if result.returncode != 0:
            # The plist is installed, so it will still load at the next login
            # even though this immediate bootstrap failed; say so honestly.
            return True, "Talk DAT! will open at login from the next sign-in."
        return True, "Talk DAT! will now open when you log in."
    except Exception as error:
        return False, f"Could not set up run at login: {error}."


def disable() -> tuple[bool, str]:
    if not mac_support.IS_MAC:
        return True, ""
    try:
        subprocess.run(["/bin/launchctl", "bootout", f"gui/{_uid()}/{LABEL}"],
                       capture_output=True)
        path = _plist_path()
        if path.exists():
            path.unlink()
        return True, "Talk DAT! will no longer open at login."
    except Exception as error:
        return False, f"Could not turn off run at login: {error}."


def _uid() -> int:
    import os

    return os.getuid()
