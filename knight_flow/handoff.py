"""X-11: the talkdat:// protocol -- sign in on the web, land in the app.

The browser's native "Open Talk DAT!?" prompt is the user-consent step the
spec asked for. Registration is per-user (HKCU, no admin); a second
instance launched by the browser drops the URI in a file for the running
app and exits, which keeps the single-instance rule intact.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCHEME = "talkdat"


def handoff_drop_path() -> Path:
    from .config import config_path

    return config_path().parent / "handoff-uri.txt"


def parse_signin_code(uri: str) -> str:
    """The one-time code out of talkdat://signin?code=..., or ""."""
    match = re.match(r"^talkdat:/{0,2}signin/?\?(?:.*&)?code=([A-Za-z0-9_-]{8,128})", str(uri or "").strip())
    return match.group(1) if match else ""


def register_protocol() -> bool:
    """Point talkdat:// at this executable, per-user. Idempotent."""
    if sys.platform == "darwin":
        # Nothing to register: macOS reads the scheme from the bundle's
        # CFBundleURLTypes, so a built .app is already the handler and a source
        # checkout can never be one. Returning True here would claim a
        # registration that did not happen; returning False says "not
        # registered by me", which is exactly right.
        from . import mac_support

        return bool(mac_support.IS_MAC and getattr(sys, "frozen", False))
    if sys.platform != "win32":
        return False
    try:
        import winreg

        executable = sys.executable
        if executable.lower().endswith("python.exe"):
            # Development runs register the script form so the flow is
            # testable without a build.
            command = f'"{executable}" "{Path(sys.argv[0]).resolve()}" "%1"'
        else:
            command = f'"{executable}" "%1"'
        root = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}")
        winreg.SetValueEx(root, None, 0, winreg.REG_SZ, "URL:Talk DAT! sign-in")
        winreg.SetValueEx(root, "URL Protocol", 0, winreg.REG_SZ, "")
        command_key = winreg.CreateKey(root, r"shell\open\command")
        winreg.SetValueEx(command_key, None, 0, winreg.REG_SZ, command)
        return True
    except Exception:
        return False


def stash_uri_for_primary(uri: str) -> None:
    """Second instance: leave the URI where the running app will find it."""
    try:
        path = handoff_drop_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(uri), encoding="utf-8")
    except Exception:
        pass


def take_stashed_uri() -> str:
    """Primary instance: claim and clear any dropped URI."""
    try:
        path = handoff_drop_path()
        if not path.exists():
            return ""
        uri = path.read_text(encoding="utf-8").strip()
        path.unlink(missing_ok=True)
        return uri
    except Exception:
        return ""
