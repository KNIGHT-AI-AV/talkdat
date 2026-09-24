"""An update that is ready to install, shown on Home (X-611).

The Update window was a square Tk window that every existing user met on every
release. Home already answered "Check for updates"; it now also carries the
whole offer: the version, the readable notes, the verified install with its
progress, Later, Skip this version and View on GitHub. The install itself is
the app's own verified path (App.install_update), unchanged; the Tk window is
the fallback when the renderer is unavailable.

The installer reports from its worker thread, so every field here is read and
written under one lock, and the page only ever sees a copy.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

INSTALLING_MESSAGE = "The verified installer is being prepared. Wait for it to finish."


def _details(data: dict[str, Any]) -> list[str]:
    details = []
    published = str(data.get("published_at", ""))[:10]
    if published:
        details.append(f"Published {published}")
    if data.get("predownloaded"):
        details.append("Already downloaded")
    if data.get("installer_size"):
        details.append(f"{int(data.get('installer_size', 0)) // (1024 * 1024)} MB")
    if data.get("provenance_verified") and data.get("source_commit"):
        details.append(f"Source {str(data.get('source_commit'))[:12]}")
    return details


def _ready_status(data: dict[str, Any]) -> tuple[str, bool]:
    """The same promise the Update window made, word for word, and whether
    Install may be pressed."""
    if data.get("has_installer") and data.get("has_checksum"):
        if data.get("publisher_signature_required"):
            trust = "receipt, SHA256, and Windows publisher signature"
        elif data.get("provenance_verified"):
            trust = "release receipt and SHA256"
        else:
            trust = "published SHA256"
        return f"Ready to install. Talk DAT! will verify the {trust} before launch.", True
    if data.get("has_installer"):
        return "This release has a setup EXE, but no SHA256 checksum. Install is blocked for safety.", False
    return "This release has no setup EXE attached yet. Use View on GitHub to download manually.", False


class UpdateOffer:
    def __init__(self, *, notify: Callable[[str, str], None], open_url: Callable[[str], Any],
                 count_dismissal: Callable[[], None]) -> None:
        self._notify, self._open_url, self._count_dismissal = notify, open_url, count_dismissal
        self._lock = threading.Lock()
        self._offer: dict[str, Any] | None = None
        self._install: Callable[..., None] | None = None
        self._skip: Callable[[], None] | None = None

    def offer(self, data: dict[str, Any], install: Callable[..., None], skip: Callable[[], None]) -> bool:
        """Show this release on Home. False while another install is running."""
        from knight_flow.release_notes import readable_release_notes

        status, can_install = _ready_status(data)
        with self._lock:
            if self._offer is not None and self._offer["phase"] == "installing":
                return False
            self._offer = {
                "current": str(data.get("current_version", "")),
                "latest": str(data.get("latest_version", "")),
                "details": _details(data),
                "notes": readable_release_notes(data.get("release_notes", "")),
                "release_url": str(data.get("release_url") or ""),
                "can_install": can_install,
                "phase": "ready" if can_install else "blocked",
                "status": status,
                "percent": None,
            }
            self._install, self._skip = install, skip
        return True

    def withdraw(self) -> None:
        """Take the offer back without counting a dismissal (Home did not open)."""
        with self._lock:
            if self._offer is not None and self._offer["phase"] != "installing":
                self._offer = None

    @property
    def installing(self) -> bool:
        with self._lock:
            return self._offer is not None and self._offer["phase"] == "installing"

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._offer, details=list(self._offer["details"])) if self._offer else None

    # The installer's three callbacks (App.install_update), from its worker.
    def _set_status(self, text: str) -> None:
        with self._lock:
            if self._offer is not None:
                self._offer["status"] = str(text)

    def _set_progress(self, downloaded: int, total: int) -> None:
        if total <= 0:
            return
        percent = min(100.0, downloaded / total * 100)
        with self._lock:
            if self._offer is not None:
                self._offer["percent"] = round(percent, 1)
                self._offer["status"] = f"Downloading update... {percent:.0f}%  ({downloaded // (1024 * 1024)} MB)"

    def _on_done(self, success: bool, message: str) -> None:
        with self._lock:
            if self._offer is not None:
                self._offer["phase"] = "started" if success else "failed"
                self._offer["status"] = str(message)
        self._notify("captured" if success else "error", str(message))

    def act(self, operation: str) -> str:
        """Install, later, skip or github. The answer is a message for the page."""
        with self._lock:
            offer = self._offer
            if offer is None:
                raise ValueError("There is no update waiting.")
            phase = offer["phase"]
            if operation != "github" and phase == "installing":
                raise ValueError(INSTALLING_MESSAGE)
            if operation == "install":
                if not offer["can_install"] or phase not in {"ready", "failed"}:
                    raise ValueError(offer["status"])
                offer["phase"], offer["status"], offer["percent"] = "installing", "Preparing update...", None
                install = self._install
            elif operation == "later":
                self._offer = None
            elif operation == "skip":
                skip, latest = self._skip, offer["latest"]
                self._offer = None
            elif operation != "github":
                raise ValueError("That update action is unavailable.")
        if operation == "install":
            try:
                install(self._set_progress, self._set_status, self._on_done)
            except Exception as error:
                self._on_done(False, f"The installer could not start: {error}")
            return ""
        if operation == "later":
            # X-47: each wave-away spends one of the three reminder strikes.
            self._count_dismissal()
            return "Okay. Talk DAT! will remind you later."
        if operation == "skip":
            if skip is not None:
                skip()
            self._notify("captured", f"Skipping v{latest}.")
            return f"Skipping v{latest}. You can still update from Home."
        url = offer["release_url"]
        if url:
            self._open_url(url)
        return ""
