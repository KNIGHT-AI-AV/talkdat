"""One Tk root per process on macOS, because a second one crashes the suite.

Tk 9.0 on Aqua does not survive `Tk()` -> `destroy()` -> `Tk()` in one process:
the second root is created, and the next `update_idletasks()` segfaults inside
Tcl. Nothing in the application does that -- it builds one root and keeps it for
the life of the process -- but a test suite naturally builds one per test, and
under `unittest discover` that took the whole run down before it reached the
last third of the files.

So on macOS the root is created once and handed out repeatedly, with its
children cleared between tests to give each one a clean surface. On Windows and
Linux nothing changes: a fresh root per test, destroyed afterwards, which is
both cheap and better isolated.

Import `probe_error` to decide whether to skip; it is None when Tk is usable.
"""

from __future__ import annotations

import atexit
import subprocess
import sys
from typing import Any

IS_MAC = sys.platform == "darwin"


def _inside_the_gui_session() -> bool:
    """Can this process reach the WindowServer at all?

    Asked BEFORE tk.Tk(), because on macOS that call does not fail without a
    session -- it blocks inside AppKit and never returns. `launchctl
    managername` answers "Aqua" in the logged-in session and "Background" over
    ssh, and it costs about a millisecond.
    """
    if not IS_MAC:
        return True
    try:
        answer = subprocess.run(
            ["launchctl", "managername"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        # No launchctl, or it hung: assume the worst and skip rather than risk
        # a hang that takes the whole suite with it.
        return False
    return answer.stdout.strip() == "Aqua"

probe_error: Exception | None = None
_shared_root: Any = None

try:
    import tkinter as tk

    try:
        if IS_MAC and not _inside_the_gui_session():
            raise RuntimeError(
                "no Aqua session: Tk cannot reach the WindowServer from here "
                "(ssh). Run the GUI tests from the logged-in session."
            )
        if IS_MAC:
            # Keep the probe: it becomes the shared root, so the process never
            # creates a second one.
            _shared_root = tk.Tk()
            _shared_root.withdraw()
        else:
            _probe = tk.Tk()
            _probe.destroy()
    except Exception as error:  # no display, or Tk not built in
        probe_error = error
except Exception as error:  # pragma: no cover - tkinter missing entirely
    probe_error = error


def _shutdown_shared_root() -> None:
    """Tear the shared root down before the interpreter exits.

    Left alone, it is finalised during interpreter shutdown with its timers and
    bindings still attached, and Tcl aborts the process (SIGTRAP) after the last
    test has already reported success -- a green run with a non-zero exit code.
    """
    global _shared_root
    root, _shared_root = _shared_root, None
    if root is None:
        return
    try:
        for timer_id in root.tk.eval("after info").split():
            try:
                root.after_cancel(timer_id)
            except Exception:
                pass
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


if IS_MAC and probe_error is None:
    atexit.register(_shutdown_shared_root)


def acquire_root() -> Any:
    """A usable Tk root, fresh on Windows and Linux, shared on macOS."""
    if probe_error is not None:  # pragma: no cover - callers skip first
        raise RuntimeError("Tk is not usable in this interpreter")
    if not IS_MAC:
        return tk.Tk()
    for child in list(_shared_root.children.values()):
        try:
            child.destroy()
        except Exception:
            pass
    # A test that left the root hidden, resized, or mid-grab must not hand that
    # state to the next one.
    try:
        _shared_root.deiconify()
        _shared_root.geometry("800x600")
    except Exception:
        pass
    return _shared_root


def release_root(root: Any) -> None:
    """Destroy the root off macOS; on macOS just empty it for the next test."""
    if root is None:
        return
    if not IS_MAC:
        try:
            root.destroy()
        except Exception:
            pass
        return
    # A destroyed root takes its pending `after` callbacks with it. A shared one
    # does not, so the overlay's animation loop would keep firing into the next
    # test and repaint widgets this call is about to delete.
    try:
        for timer_id in root.tk.eval("after info").split():
            with_error = False
            try:
                root.after_cancel(timer_id)
            except Exception:
                with_error = True
            if with_error:
                continue
    except Exception:
        pass
    # Overlay binds <Configure> on the root itself. That binding outlives a
    # cleared root, so the next test's geometry call re-entered the previous
    # overlay's repaint and painted widgets that no longer existed.
    try:
        for sequence in root.bind():
            try:
                root.unbind(sequence)
            except Exception:
                pass
    except Exception:
        pass
    for child in list(getattr(root, "children", {}).values()):
        try:
            child.destroy()
        except Exception:
            pass
    try:
        root.withdraw()
    except Exception:
        pass
