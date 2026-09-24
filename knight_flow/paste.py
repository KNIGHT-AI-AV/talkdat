from __future__ import annotations

import ctypes
import logging
import os
import sys
import re
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager, suppress
from functools import wraps
from dataclasses import asdict, dataclass

# X-87: pyautogui is imported LAZILY. Measured at boot it costs 250ms of the
# 1.36s import budget all by itself -- it drags in pyscreeze (138ms) and
# pygetwindow (120ms), both of which exist for on-screen image matching this
# product never performs. Nothing here runs until a dictation finishes, so
# paying for it during startup buys a slower launch for every user in
# exchange for nothing. The module-level PAUSE default moves with it.
_PYAUTOGUI = None


def _pyautogui():
    """Import on first use, configure once, reuse thereafter."""
    global _PYAUTOGUI
    if _PYAUTOGUI is None:
        import pyautogui as module

        module.PAUSE = 0.025
        _PYAUTOGUI = module
    return _PYAUTOGUI


class _LazyPyAutoGui:
    """Attribute access forwards to the real module, importing it then.

    Keeping the `pyautogui.hotkey(...)` spelling at every call site matters:
    those lines are the ones a reader checks when paste behaviour is wrong,
    and rewriting twelve of them into _pyautogui().hotkey(...) would make the
    diff about plumbing instead of about the fix.
    """

    def __getattr__(self, name: str):
        return getattr(_pyautogui(), name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(_pyautogui(), name, value)

    def __delattr__(self, name: str) -> None:
        # mock.patch restores by deleting what it added. Without this the
        # proxy swallowed the set and then failed the delete, so every test
        # that patched a pyautogui call errored on exit rather than on the
        # assertion it was actually making.
        delattr(_pyautogui(), name)


pyautogui = _LazyPyAutoGui()
import pyperclip

from . import mac_support


log = logging.getLogger(__name__)

# Synthetic keyboard/clipboard delivery is a single shared output channel. A
# Redo session may record and format while an already-committed direct-typing
# route finishes, but the two transactions must never interleave keystrokes.
_EXTERNAL_DELIVERY_LOCK = threading.RLock()

# A text comparison is not clipboard ownership. Another application can copy
# after Talk DAT! reads ``expected`` but before it writes ``previous`` back.
# Windows increments this sequence for every clipboard mutation, including
# writes made by other processes. Remember the sequence immediately after each
# verified Talk DAT! write and require the same sequence inside the locked
# Windows clipboard transaction before restoring anything.
_CLIPBOARD_OWNERSHIP: tuple[str, int] | None = None


class CommittedTypingError(RuntimeError):
    """Direct typing failed after at least one input event reached the target."""


@contextmanager
def external_delivery_claim():
    """Hold the shared keyboard-and-clipboard channel as one transaction.

    Higher-level operations sometimes need more than one helper call (for
    example, check ownership, replace text, then update their result model).
    Exposing the same re-entrant lock lets those operations stay indivisible
    without duplicating delivery primitives or creating a second lock.
    """

    with _EXTERNAL_DELIVERY_LOCK:
        yield

# PAUSE is set in _pyautogui() at first use, so importing this module
# costs nothing.

# Every synthetic edit chord in this module is the same on both platforms except
# for which modifier carries it: Ctrl on Windows, Command on macOS.
EDIT_MODIFIER = mac_support.PASTE_MODIFIER

NO_LEADING_SPACE_STARTS = set(" \t\r\n.,;:!?)]}%")
NO_SPACE_AFTER_LEFT = set(" \t\r\n([{")
REMOTE_PROCESS_MARKERS = (
    "mstsc",
    # Apple's RDP client has been called both of these; neither contains
    # "mstsc", so without them auto mode never switches to typed delivery in a
    # remote session on a Mac -- the case the list exists for.
    "windows app",
    "microsoft remote desktop",
    "jump",
    "vnc",
    "teamviewer",
    "anydesk",
    "rustdesk",
    "parsec",
    "splashtop",
    "nomachine",
    "moonlight",
)


# Applications whose undo behaviour has actually been measured, so the instant
# correction can be used in them without waiting for someone to try it in Word.
#
# Verified by pasting, correcting, then reading the field back through the
# clipboard: 156ms in Notepad, 158-227ms in an Edge textarea, flat at 120, 400
# and 900 characters, with no duplication. Both are engine families rather than
# single programs -- Notepad is a Win32 edit control and Edge is Chromium -- so
# the other Chromium browsers below run the same undo code, which is a
# different claim from "it is probably similar".
#
# The list is deliberately short. Being absent costs a slower correction; being
# wrongly present costs somebody their sentence twice over. That asymmetry is
# the whole design, so the bar for adding a name is a measurement or the same
# engine, not a good argument about how an editor probably behaves.
#
# Two rounds of pruning are worth recording, because the reasoning that put
# them here will look reasonable again:
#
# - WordPad, added as "the same control family as Notepad". It is not: it is
#   RichEdit, which is the one family the measurements explicitly could not
#   reach.
# - Slack, Discord, Teams, Obsidian and Notion, added as "Electron, therefore
#   Chromium". They are, but none of them dictate into a plain text field --
#   each ships a rich composer with its own undo stack, which is the same
#   unknown as Monaco, and Monaco is excluded.
UNDO_VERIFIED_PROCESSES = (
    "notepad.exe",     # Win32 edit control, measured
    "msedge.exe",      # Chromium, measured
    "chrome.exe",
    "brave.exe",
    "vivaldi.exe",
    "opera.exe",
    "chromium.exe",
    "comet.exe",       # Perplexity; Chromium 150, ships chrome.dll
)

# Chromium browsers that are not on that list by name.
#
# The list was written from the browsers a developer thinks of, and the machine
# this ships from runs none of them -- its browser is Comet, a Perplexity fork
# nobody had heard of a year ago. Arc, Zen, Dia and whatever is next have the
# same problem, and each miss silently costs the feature in the one application
# somebody actually dictates into.
#
# Asking the executable is better than guessing its name. A Chromium browser
# ships the engine as a DLL beside itself or in a version folder --
# `chrome.dll` for Chrome, Brave and Comet, `msedge.dll` for Edge -- and this
# is what separates a browser from an Electron application, which bundles
# Chromium but ships neither (checked against a real one: resources/,
# ffmpeg.dll and libGLESv2.dll, no engine DLL). That distinction is the whole
# reason Slack and Discord are excluded, so it is the right thing to test.
CHROMIUM_ENGINE_LIBRARIES = ("chrome.dll", "msedge.dll")

# One stat per executable per run rather than one per dictation. The same fix
# as the PID cache in Work Mode Guardian, for the same reason: a cheap call
# made on every pass stops being cheap.
_chromium_browsers: dict[str, bool] = {}


def _looks_like_a_chromium_browser(path: str) -> bool:
    """Whether a Chromium engine DLL sits beside this executable.

    Version folders are checked too, because Chrome and Edge both put the
    engine in one named after the release. Only directories starting with a
    digit are opened, so this is a couple of stats rather than a directory
    walk.
    """
    if not path:
        return False
    cached = _chromium_browsers.get(path)
    if cached is not None:
        return cached
    found = False
    try:
        folder = os.path.dirname(path)
        found = any(
            os.path.exists(os.path.join(folder, library))
            for library in CHROMIUM_ENGINE_LIBRARIES
        )
        if not found:
            # Only Edge needs this -- it keeps msedge.dll in the version folder
            # while Chrome, Brave and Comet leave chrome.dll beside the exe. It
            # is second because the alternative is listing System32 the first
            # time anything in System32 takes focus, for two stats' worth of
            # answer.
            with os.scandir(folder) as entries:
                versions = [
                    entry.path for entry in entries
                    if entry.name[:1].isdigit() and entry.is_dir()
                ]
            found = any(
                os.path.exists(os.path.join(version, library))
                for version in versions
                for library in CHROMIUM_ENGINE_LIBRARIES
            )
    except OSError:
        # An unreadable directory is not evidence of a browser, and the cost of
        # being wrong here is somebody's text pasted twice.
        log.debug("could not inspect %s for a Chromium engine", path, exc_info=True)
        found = False
    _chromium_browsers[path] = found
    return found


def undo_is_verified_here() -> bool:
    """Whether the focused application's undo grouping is one we can rely on.

    Used to switch the instant correction on where it is known to work rather
    than leaving it off everywhere. An unknown application keeps the keystroke
    path, which is slower and cannot duplicate anything.

    Matched exactly rather than by substring, unlike REMOTE_PROCESS_MARKERS
    above. A substring match reads as harmless and is not: "notepad" also
    matches notepad++.exe, which is Scintilla and shares nothing with the
    control that was measured. Remote clients can afford a loose match because
    a false positive there only refuses an optimisation; here it enables one.

    Nothing on macOS is on this list, because nothing on macOS has been
    measured. Every name here was earned by pasting into the application and
    reading the field back; the same asymmetry that keeps Word off the Windows
    list -- missing costs a slower correction, wrongly present costs somebody
    their sentence twice -- keeps every Mac application off it until someone
    does that work. TextEdit and Safari are the obvious first two to measure.
    """
    if mac_support.IS_MAC:
        return False
    path = foreground_process_path()
    if os.path.basename(path).lower() in UNDO_VERIFIED_PROCESSES:
        return True
    return _looks_like_a_chromium_browser(path)


@dataclass(frozen=True)
class PasteReceipt:
    """Non-content receipt for the route used to deliver dictated text.

    Receipts intentionally contain no transcript text or clipboard contents. They
    are safe to show in the Pill and to retain in local diagnostics.
    """

    success: bool
    requested_mode: str
    method: str
    attempts: tuple[str, ...]
    fallback_used: bool = False

    def __bool__(self) -> bool:
        return self.success

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def visible_label(self) -> str:
        labels = {
            "clipboard": "Inserted via clipboard",
            "shift_insert": "Inserted with Shift+Insert",
            "direct_type": "Inserted by direct typing",
            "copy_only": "Copied to clipboard",
            "enter": "Sent Enter",
        }
        label = labels.get(self.method, "Insertion failed")
        if self.success and self.fallback_used:
            return f"{label} after automatic fallback"
        return label


@dataclass(frozen=True)
class UndoReplacementReceipt:
    """Outcome of a verified undo-and-paste replacement.

    ``undo_attempted`` is deliberately separate from success. Once Ctrl+Z may
    have reached the editor, a caller must never assume the original insertion
    is still present and must never issue a blind backspace fallback.
    """

    success: bool
    undo_attempted: bool

    def __bool__(self) -> bool:
        return self.success


def _serialized_external_delivery(
    function: Callable[..., PasteReceipt],
) -> Callable[..., PasteReceipt]:
    @wraps(function)
    def serialized(*args: object, **kwargs: object) -> PasteReceipt:
        with _EXTERNAL_DELIVERY_LOCK:
            return function(*args, **kwargs)

    return serialized


def clipboard_text() -> str:
    with suppress(Exception):
        value = pyperclip.paste()
        return "" if value is None else str(value)
    return ""


def clipboard_sequence_number() -> int:
    """Current Windows clipboard generation, or zero when unavailable.

    Zero is deliberately not a usable ownership token. The macOS branch needs
    its own NSPasteboard ``changeCount`` implementation; falling back to a text
    comparison there would recreate the same lost-copy race.
    """

    if os.name != "nt":
        return 0
    try:
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:
        log.debug("clipboard sequence number unavailable", exc_info=True)
        return 0


def _restore_windows_clipboard_text_if_owned(
    expected: str,
    previous: str,
    owned_sequence: int,
) -> bool:
    """Replace CF_UNICODETEXT while the owned Windows clipboard is locked.

    ``OpenClipboard`` excludes competing writers for the final sequence/content
    proof and the replacement itself. This closes the external TOCTOU that an
    in-process RLock cannot close.
    """

    if sys.platform != "win32" or not owned_sequence:
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    cf_unicode_text = 13
    gmem_moveable = 0x0002

    try:
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_int
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = ctypes.c_int
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = ctypes.c_int
        user32.GetClipboardData.argtypes = [ctypes.c_uint]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = ctypes.c_int
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.restype = ctypes.c_void_p
    except Exception:
        log.debug("Windows clipboard API signatures unavailable", exc_info=True)
        return False

    if clipboard_sequence_number() != owned_sequence:
        return False
    if not user32.OpenClipboard(None):
        return False

    allocation: int | None = None
    transferred = False
    try:
        # Recheck after OpenClipboard so another process cannot change the
        # value between this proof and EmptyClipboard/SetClipboardData.
        if clipboard_sequence_number() != owned_sequence:
            return False
        handle = user32.GetClipboardData(cf_unicode_text)
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return False
        try:
            current = ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
        if current != expected:
            return False

        encoded = (previous + "\0").encode("utf-16-le")
        allocation = int(kernel32.GlobalAlloc(gmem_moveable, len(encoded)) or 0)
        if not allocation:
            return False
        destination = kernel32.GlobalLock(allocation)
        if not destination:
            return False
        try:
            ctypes.memmove(destination, encoded, len(encoded))
        finally:
            kernel32.GlobalUnlock(allocation)

        if not user32.EmptyClipboard():
            return False
        if not user32.SetClipboardData(cf_unicode_text, allocation):
            return False
        transferred = True
        # X-604: the restore puts back what the person had; it is not a new
        # copy for their history, and it never goes to the cloud clipboard.
        _mark_open_clipboard_private(transient=True)
        return True
    except Exception:
        log.debug("owned clipboard restore failed safely", exc_info=True)
        return False
    finally:
        if allocation and not transferred:
            try:
                kernel32.GlobalFree(allocation)
            except Exception:
                log.debug("clipboard restore allocation cleanup failed", exc_info=True)
        try:
            user32.CloseClipboard()
        except Exception:
            log.debug("clipboard restore could not close its handle", exc_info=True)


#: X-604: what an app (a password manager above all) puts beside its text to
#: say "do not keep this": Windows' clipboard-history and cloud-clipboard
#: opt-outs, and the older viewer convention KeePass still sets.
PRIVATE_CLIPBOARD_FORMATS = (
    "ExcludeClipboardContentFromMonitorProcessing", "Clipboard Viewer Ignore", "CanIncludeInClipboardHistory",
)
#: The macOS convention (nspasteboard.org): concealed is a password,
#: transient and auto-generated are gone in a moment.
PRIVATE_PASTEBOARD_TYPES = (
    "org.nspasteboard.ConcealedType", "org.nspasteboard.TransientType", "org.nspasteboard.AutoGeneratedType",
)


def clipboard_is_private() -> bool:
    """Whether the app that filled the clipboard asked everyone else not to keep it.

    Answers without opening the clipboard, and fails CLOSED: a probe that
    errors says "private", so the learner simply skips that copy.
    """
    try:
        if os.name == "nt":
            user32 = ctypes.WinDLL("user32", use_last_error=True)  # private: argtypes below
            user32.RegisterClipboardFormatW.argtypes = (ctypes.c_wchar_p,)
            user32.RegisterClipboardFormatW.restype = ctypes.c_uint
            user32.IsClipboardFormatAvailable.argtypes = (ctypes.c_uint,)
            user32.IsClipboardFormatAvailable.restype = ctypes.c_int
            for name in PRIVATE_CLIPBOARD_FORMATS:
                registered = user32.RegisterClipboardFormatW(name)
                if registered and user32.IsClipboardFormatAvailable(registered):
                    return True
            return False
        if sys.platform == "darwin":
            from AppKit import NSPasteboard

            types = NSPasteboard.generalPasteboard().types() or []
            return any(str(kind) in PRIVATE_PASTEBOARD_TYPES for kind in types)
    except Exception:
        log.debug("clipboard privacy probe failed; skipping this copy", exc_info=True)
        return True
    return False


def clipboard_contains_non_text_formats() -> bool:
    """Whether restoring plain text would destroy richer clipboard content.

    Windows can expose HTML, RTF, images, and file lists alongside a Unicode
    text fallback. Pyperclip cannot faithfully snapshot those formats. When a
    person asks Talk DAT! to preserve their clipboard, the safe response is to
    use direct typing and leave the clipboard untouched rather than silently
    flattening an image or rich selection into plain text.
    """

    if sys.platform != "win32":
        # No NSPasteboard probe yet. "Plain" is the honest answer here: a
        # conservative True routed every macOS paste through per-character
        # typing and refused every selection capture. Follow-up: NSPasteboard
        # types, so the protection below can hold on macOS too.
        return False
    user32 = ctypes.windll.user32
    if not user32.OpenClipboard(None):
        return True
    try:
        plain_text_formats = {1, 7, 13, 16}  # TEXT, OEMTEXT, UNICODETEXT, LOCALE
        current = 0
        while True:
            current = int(user32.EnumClipboardFormats(current))
            if not current:
                break
            if current not in plain_text_formats:
                return True
        return False
    except Exception:
        log.debug("clipboard format probe failed; preserving it conservatively", exc_info=True)
        return True
    finally:
        try:
            user32.CloseClipboard()
        except Exception:
            log.debug("clipboard format probe could not close its handle", exc_info=True)


# X-406: a rich clipboard no longer forces key-by-key typing.
#
# On 2026-09-03 a 1,072-character dictation took 10.5 seconds to land: the
# clipboard held a screenshot, "restore my clipboard" was on, and the only way
# the app knew to keep an image safe was to avoid the clipboard entirely and
# type every character. The snapshot below captures every memory-backed
# format Windows exposes (text, DIB images, HTML, RTF, file lists, PNG), the
# paste goes through the clipboard as usual, and the snapshot is put back the
# moment the paste has settled. Typing remains the fallback for the formats
# that cannot be copied as memory (metafiles) or when the clipboard cannot be
# opened, so nothing that was safe before is less safe now.
GMEM_MOVEABLE = 0x0002
_SNAPSHOT_SYNTHESIZED = {2, 9}  # CF_BITMAP, CF_PALETTE: Windows rebuilds both from CF_DIB
_SNAPSHOT_HANDLE_ONLY = {3, 14, 0x80, 0x82, 0x83, 0x8E}  # metafiles, owner display, display variants
_SNAPSHOT_MAX_BYTES = 64 * 1024 * 1024


def snapshot_clipboard() -> list[tuple[int, bytes]] | None:
    """Every memory-backed clipboard format, or None when it cannot be kept faithfully."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.EnumClipboardFormats.argtypes = [ctypes.c_uint]
    user32.EnumClipboardFormats.restype = ctypes.c_uint
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    opened = False
    for _attempt in range(5):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.01)
    if not opened:
        return None
    formats: list[tuple[int, bytes]] = []
    total = 0
    try:
        current = 0
        while True:
            current = int(user32.EnumClipboardFormats(current))
            if not current:
                break
            if current in _SNAPSHOT_HANDLE_ONLY:
                return None
            if current in _SNAPSHOT_SYNTHESIZED or 0x0200 <= current <= 0x03FF:
                # Private and GDI-object ranges belong to the owning app and
                # cannot be re-issued from memory; the synthesized pair come
                # back on their own once CF_DIB is restored.
                continue
            handle = user32.GetClipboardData(current)
            if not handle:
                return None
            size = int(kernel32.GlobalSize(handle))
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return None
            try:
                data = ctypes.string_at(pointer, size)
            finally:
                kernel32.GlobalUnlock(handle)
            total += size
            if total > _SNAPSHOT_MAX_BYTES:
                return None
            formats.append((current, data))
        return formats
    except Exception:
        log.debug("clipboard snapshot failed; delivery will type instead", exc_info=True)
        return None
    finally:
        try:
            user32.CloseClipboard()
        except Exception:
            log.debug("clipboard snapshot could not close its handle", exc_info=True)


def restore_clipboard_snapshot(snapshot: list[tuple[int, bytes]], expected: str) -> bool:
    """Put a snapshot back, but only while Talk DAT! still owns the clipboard generation it wrote."""
    global _CLIPBOARD_OWNERSHIP
    if sys.platform != "win32" or not snapshot:
        return False
    with _EXTERNAL_DELIVERY_LOCK:
        ownership = _CLIPBOARD_OWNERSHIP
        if ownership is None or ownership[0] != expected or not ownership[1]:
            return False
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        opened = False
        for _attempt in range(5):
            if user32.OpenClipboard(None):
                opened = True
                break
            time.sleep(0.01)
        if not opened:
            _CLIPBOARD_OWNERSHIP = None
            return False
        try:
            if clipboard_sequence_number() != ownership[1]:
                # Somebody copied something newer. It is theirs now.
                _CLIPBOARD_OWNERSHIP = None
                return False
            if not user32.EmptyClipboard():
                return False
            restored = 0
            for format_id, data in snapshot:
                allocation = kernel32.GlobalAlloc(GMEM_MOVEABLE, max(1, len(data)))
                if not allocation:
                    continue
                pointer = kernel32.GlobalLock(allocation)
                if not pointer:
                    kernel32.GlobalFree(allocation)
                    continue
                try:
                    if data:
                        ctypes.memmove(pointer, data, len(data))
                finally:
                    kernel32.GlobalUnlock(allocation)
                if user32.SetClipboardData(int(format_id), allocation):
                    restored += 1
                else:
                    kernel32.GlobalFree(allocation)
            _CLIPBOARD_OWNERSHIP = None
            return restored > 0
        except Exception:
            log.debug("clipboard snapshot restore failed safely", exc_info=True)
            _CLIPBOARD_OWNERSHIP = None
            return False
        finally:
            try:
                user32.CloseClipboard()
            except Exception:
                log.debug("clipboard snapshot restore could not close its handle", exc_info=True)


def _mark_open_clipboard_private(*, transient: bool) -> None:
    """Add the local-only formats to a clipboard this process has open and filled."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.RegisterClipboardFormatW.argtypes = (ctypes.c_wchar_p,)
        user32.RegisterClipboardFormatW.restype = ctypes.c_uint
        kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
        kernel32.GlobalFree.argtypes = (ctypes.c_void_p,)
        zero = (0).to_bytes(4, "little")
        private = [("CanUploadToCloudClipboard", zero)]
        if transient:
            private += [("CanIncludeInClipboardHistory", zero),
                        ("ExcludeClipboardContentFromMonitorProcessing", bytes(1))]
        for name, data in private:
            registered = user32.RegisterClipboardFormatW(name)
            handle = kernel32.GlobalAlloc(0x0002, len(data)) if registered else None
            if not handle:
                continue
            pointer = kernel32.GlobalLock(handle)
            if pointer:
                ctypes.memmove(pointer, data, len(data))
                kernel32.GlobalUnlock(handle)
            if not pointer or not user32.SetClipboardData(registered, handle):
                kernel32.GlobalFree(handle)
    except Exception:
        log.debug("could not mark the clipboard local-only", exc_info=True)


def _copy_text_windows(text: str, *, transient: bool) -> bool:
    """X-604: CF_UNICODETEXT plus the formats that keep Talk DAT!'s copy local.

    Every copy carries CanUploadToCloudClipboard = 0: whatever Windows' cloud
    clipboard is set to, words Talk DAT! puts on the clipboard never leave this
    PC through it. A TRANSIENT copy -- the clipboard borrowed for a paste, a
    probe sentinel, the restore of what was there before -- also carries
    ExcludeClipboardContentFromMonitorProcessing and CanIncludeInClipboardHistory
    = 0, so it never lands in Win+V history or a clipboard manager. A copy the
    person asked for (Copy, auto-paste off) stays in their history as usual.

    Uses its own user32/kernel32 handles (never the shared ctypes.windll
    bindings). Returns False on any failure; the caller falls back to pyperclip.
    """
    if os.name != "nt" or os.environ.get("TALK_DAT_PLAIN_CLIPBOARD") == "1":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = (ctypes.c_void_p,)
    user32.OpenClipboard.restype = ctypes.c_int
    user32.CloseClipboard.restype = ctypes.c_int
    user32.EmptyClipboard.restype = ctypes.c_int
    user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.RegisterClipboardFormatW.argtypes = (ctypes.c_wchar_p,)
    user32.RegisterClipboardFormatW.restype = ctypes.c_uint
    kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalFree.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalFree.restype = ctypes.c_void_p

    def put(fmt: int, data: bytes) -> bool:
        handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(fmt, handle):
            kernel32.GlobalFree(handle)
            return False
        return True  # the system owns the memory now

    for _attempt in range(5):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return False
    try:
        if not user32.EmptyClipboard():
            return False
        if not put(13, (text + "\0").encode("utf-16-le")):  # CF_UNICODETEXT
            return False
        _mark_open_clipboard_private(transient=transient)  # best effort: the text is there
        return True
    finally:
        user32.CloseClipboard()


def copy_text(text: str, *, transient: bool = False) -> bool:
    global _CLIPBOARD_OWNERSHIP
    with _EXTERNAL_DELIVERY_LOCK:
        for _attempt in range(6):
            try:
                written = False
                try:
                    written = _copy_text_windows(text, transient=transient)
                except Exception:
                    log.debug("private clipboard write failed; using the plain one", exc_info=True)
                if not written:
                    pyperclip.copy(text)
            except Exception:
                time.sleep(0.04)
                continue
            written_sequence = clipboard_sequence_number()
            if not written_sequence:
                _CLIPBOARD_OWNERSHIP = None
                if sys.platform == "win32":
                    return False
                # No clipboard generation counter here (macOS: an NSPasteboard
                # changeCount token is the follow-up). Verify the write the way
                # this did before ownership tokens existed -- read it back --
                # and claim no ownership, since none can be proven. A False here
                # made every macOS paste and selection capture fail.
                time.sleep(0.025)
                return clipboard_text() == text
            # A successful clipboard write followed by a mismatch means the
            # user or another application copied something newer. Retrying
            # would steal the clipboard back from them. Retries are only for a
            # write/open failure before Talk DAT! ever owned it.
            time.sleep(0.025)
            if (
                clipboard_sequence_number() == written_sequence
                and clipboard_text() == text
                and clipboard_sequence_number() == written_sequence
            ):
                _CLIPBOARD_OWNERSHIP = (text, written_sequence)
                return True
            _CLIPBOARD_OWNERSHIP = None
            return False
        _CLIPBOARD_OWNERSHIP = None
        return False


def restore_clipboard_if_unchanged(expected: str, previous: str) -> bool:
    """Restore only while Talk DAT! still owns one exact clipboard generation."""

    global _CLIPBOARD_OWNERSHIP
    with _EXTERNAL_DELIVERY_LOCK:
        ownership = _CLIPBOARD_OWNERSHIP
        if ownership is None and sys.platform != "win32":
            # No clipboard generation counter here (macOS), so no ownership
            # token was ever claimed. The pre-token contract decides: the
            # value is still ours to put back while the text is unchanged.
            if clipboard_text() != expected:
                return False
            return copy_text(previous)
        if ownership is None or ownership[0] != expected:
            return False
        restored = _restore_windows_clipboard_text_if_owned(
            expected,
            previous,
            ownership[1],
        )
        if not restored:
            # The clipboard was changed, unavailable, or could not be proven.
            # Never retry a restore: retrying could overwrite the newer owner.
            _CLIPBOARD_OWNERSHIP = None
            return False
        sequence = clipboard_sequence_number()
        _CLIPBOARD_OWNERSHIP = (previous, sequence) if sequence else None
        return True


def needs_leading_space(text: str, left_context: str) -> bool:
    if not text or not left_context:
        return False
    first = text[0]
    left = left_context[-1]
    if first in NO_LEADING_SPACE_STARTS:
        return False
    if text.startswith(("- ", "* ", "1. ", "\n")):
        return False
    if left in NO_SPACE_AFTER_LEFT:
        return False
    return True


def should_prefix_space(text: str) -> bool:
    if not text:
        return False
    if text[0] in NO_LEADING_SPACE_STARTS:
        return False
    if text.startswith(("- ", "* ", "1. ", "\n")):
        return False
    # X-118: a bare word or short phrase with no sentence punctuation is an
    # INSERTION -- a search term, a field value, a name. A leading space
    # fights the field it lands in. Sentences keep their joining space.
    words = text.split()
    if len(words) <= 4 and not re.search(r"[.!?]", text):
        return False
    return True


def foreground_process_name() -> str:
    """Lowercased executable name of the window with focus, or "" if unknown."""
    return os.path.basename(foreground_process_path()).lower()


def foreground_process_path() -> str:
    """Full path to the executable of the window with focus, or "".

    The path rather than the name, because the name alone cannot answer "is
    this a Chromium browser" -- only the files sitting next to the executable
    can, and browser forks appear faster than any hardcoded list is updated.
    """
    if mac_support.IS_MAC:
        return mac_support.frontmost_app_path()
    if os.name != "nt":
        return ""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        process = kernel32.OpenProcess(0x1000, False, pid.value)
        if not process:
            return ""
        try:
            size = ctypes.c_ulong(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return ""
            return buffer.value
        finally:
            kernel32.CloseHandle(process)
    except Exception:
        return ""


def foreground_is_remote_client() -> bool:
    name = foreground_process_name()
    return bool(name and any(marker in name for marker in REMOTE_PROCESS_MARKERS))


# X-463: the keys the person is still holding when a hotkey fires.
#
# SendInput does not replace the keyboard state, it adds to it. A synthetic
# Ctrl+V sent while Shift and Alt are physically down arrives as
# Ctrl+Shift+Alt+V, which no app treats as paste, and a synthetic character
# sent while Shift is down arrives capitalised. Paste Last is bound to
# Shift+Alt+Z and delivers immediately, so it hit this every time; dictation
# never did, because its trigger is released a second before the text lands.
_MODIFIER_VKS = (
    0x10,  # VK_SHIFT
    0x11,  # VK_CONTROL
    0x12,  # VK_MENU (Alt)
    0x5B,  # VK_LWIN
    0x5C,  # VK_RWIN
)
_MODIFIER_KEY_NAMES = ("shift", "ctrl", "alt", "winleft", "winright")
# macOS has one Command key slot (physical_key_down already checks both the
# left and right keycodes), so there is no separate rwin entry to pair here.
_MAC_MODIFIER_VKS_AND_NAMES = (
    (0x10, "shift"),
    (0x11, "ctrl"),
    (0x12, "alt"),
    (0x5B, "cmd"),
)
# Long enough for a person letting go of a chord, short enough that a key
# genuinely stuck down cannot hang the paste behind it.
MODIFIER_RELEASE_TIMEOUT_MS = 700


def physical_modifiers_down() -> tuple[int, ...]:
    """Which modifier keys are currently held, asked of the OS directly.

    Windows via GetAsyncKeyState, macOS via the window server
    (mac_support.physical_key_down -- the counterpart built for exactly this).
    An empty tuple means "nothing held, go ahead". That is also what a failed
    read returns, because refusing to deliver text is worse than delivering it
    with a modifier down -- but the failure is logged, so a report of "it
    pasted the wrong thing" has something to read.
    """
    if mac_support.IS_MAC:
        try:
            return tuple(
                code
                for code, name in _MAC_MODIFIER_VKS_AND_NAMES
                if mac_support.physical_key_down(name)
            )
        except Exception:
            log.debug("could not read the modifier keys; treating them as released", exc_info=True)
            return ()
    try:
        user32 = ctypes.windll.user32
        return tuple(code for code in _MODIFIER_VKS if user32.GetAsyncKeyState(code) & 0x8000)
    except Exception:
        log.debug("could not read the modifier keys; treating them as released", exc_info=True)
        return ()


def settle_modifiers(timeout_ms: int = MODIFIER_RELEASE_TIMEOUT_MS) -> bool:
    """Wait for the person to let go of the hotkey, then force the issue.

    Returns True when the modifiers are clear by the end. Never raises: a
    delivery must not fail because this could not read the keyboard.
    """
    if not physical_modifiers_down():
        return True
    deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000
    while time.monotonic() < deadline:
        if not physical_modifiers_down():
            return True
        time.sleep(0.02)
    # Still leaning on the keys. Release them in the synthetic stream so the
    # chord we are about to send is at least composed correctly.
    log.info("modifiers still held after %dms; releasing them before the paste", timeout_ms)
    for name in _MODIFIER_KEY_NAMES:
        try:
            pyautogui.keyUp(name)
        except Exception:
            log.debug("could not release %s", name, exc_info=True)
    time.sleep(0.01)
    still_down = physical_modifiers_down()
    if still_down:
        log.warning("modifiers %s are still down; the paste may not reach the app", still_down)
    return not still_down


def left_context_char(previous_clipboard: str, timeout: float = 0.08) -> str:
    sentinel = f"__TALK_DAT_CONTEXT_{uuid.uuid4().hex}__"
    try:
        copy_text(sentinel, transient=True)
        pyautogui.hotkey("shift", "left")
        time.sleep(timeout)
        pyautogui.hotkey(EDIT_MODIFIER, "c")
        time.sleep(timeout)
        selected = clipboard_text()
        if not selected or selected == sentinel:
            return ""
        copy_text(selected, transient=True)
        time.sleep(timeout)
        pyautogui.hotkey(EDIT_MODIFIER, "v")
        time.sleep(timeout)
        return selected[-1]
    except Exception:
        return ""
    finally:
        copy_text(previous_clipboard, transient=True)


MESSENGER_PROCESSES = {
    "discord.exe", "slack.exe", "whatsapp.exe", "telegram.exe", "teams.exe",
    "ms-teams.exe", "signal.exe", "messenger.exe",
}


def strip_messenger_trailing_period(text: str, *, keep: bool = False) -> str:
    """X-118, the research-backed default the leaders all ship: in a chat app
    a single sentence loses its trailing period -- "sounds passive-aggressive"
    is the users' own description. Multi-sentence messages, questions, and
    everything outside a known messenger stay exactly as formatted.

    X-604 (commandment 76): ``keep`` is True when the speaker SAID the mark
    ("sounds good period"); a period somebody asked for is never taken off."""
    if keep:
        return text
    trimmed = text.rstrip()
    if not trimmed.endswith(".") or trimmed.endswith(".."):
        return text
    if len(re.findall(r"[.!?]", trimmed)) != 1 or chr(10) in trimmed:
        return text
    if foreground_process_name() not in MESSENGER_PROCESSES:
        return text
    return trimmed[:-1]


def apply_smart_leading_space(text: str, previous_clipboard: str) -> str:
    if should_prefix_space(text):
        return " " + text
    return text


def _delivery_is_allowed(can_deliver: Callable[[], bool] | None) -> bool:
    """Fail closed when a delivery flight has been cancelled or superseded."""

    if can_deliver is None:
        return True
    try:
        return bool(can_deliver())
    except Exception:
        log.warning("delivery authorization check failed; refusing external input", exc_info=True)
        return False


def _type_text(
    text: str,
    *,
    interval_ms: int = 2,
    can_deliver: Callable[[], bool] | None = None,
) -> bool:
    """Type the text key by key. Works in fields that block synthetic Ctrl+V.

    pyautogui pauses between every call -- 25ms here, set at the top of this
    module -- and this makes two calls per line, so a six line paragraph spent
    300ms doing nothing before a character was typed. Small, but this is the
    path every dictation takes in an application that refuses synthetic paste.

    The pause is suspended for the duration and restored in a finally, so a
    failure part-way cannot leave the rest of the application typing at full
    speed. `interval` still governs the gap between individual keystrokes,
    because some applications drop characters typed with no gap at all.
    """
    previous_pause = getattr(pyautogui, "PAUSE", 0.025)
    committed = False
    try:
        interval = max(0, int(interval_ms)) / 1000
        pyautogui.PAUSE = 0

        def authorize_first_input() -> bool:
            nonlocal committed
            if committed:
                return True
            if not _delivery_is_allowed(can_deliver):
                return False
            # Direct typing cannot be rolled back reliably across arbitrary
            # editors. Once its first key is committed, complete the text as one
            # transaction; stopping halfway would leave a stale fragment for a
            # Redo result to append to. Cancel can still refuse the transaction
            # before this point, and can suppress a trailing Enter afterwards.
            committed = True
            return True

        for line_index, line in enumerate(text.split("\n")):
            if line_index:
                if not authorize_first_input():
                    return False
                pyautogui.press("enter")
            if line:
                if not authorize_first_input():
                    return False
                pyautogui.typewrite(line, interval=interval)
        return True
    except Exception as exc:
        log.warning("typing delivery failed after %d characters", len(text), exc_info=True)
        if committed:
            # A prefix may already be visible. Never follow it with a second
            # automatic route, which would turn `ab` + `abcdef` into a corrupt
            # duplicate. The caller can preserve the complete result without
            # emitting another insertion.
            raise CommittedTypingError("direct typing failed after input began") from exc
        return False
    finally:
        pyautogui.PAUSE = previous_pause



def replace_by_undo(
    replacement: str,
    *,
    settle_ms: int = 45,
    can_deliver: Callable[[], bool] | None = None,
) -> UndoReplacementReceipt:
    """Undo the previous paste and paste the correction over it.

    This is the only way found to make replacement cost the same whatever the
    length. Editors group a paste into one undo step, so Ctrl+Z removes it in
    a single operation and the whole edit is two chords. Measured at 100, 300
    and 900 characters: 197ms, 196ms, 197ms, against 4.3ms per character for
    backspacing, which is 3.9 seconds at 900.

    Batching keystrokes was tried first and does not work -- a single Win32
    SendInput call carrying the whole edit measured slower than one call per
    key, because Windows throttles synthetic input per event. Length is only
    escapable by not sending one event per character, and undo is the way.

    **It is off by default and should stay off until it has been tried in the
    applications someone actually dictates into.** Two failure modes, both
    worse than a slow delete:

    - An application with no undo ignores Ctrl+Z, and the correction is
      pasted after the original instead of over it, so the text appears twice.
    - An application that groups undo more coarsely than one paste removes
      something the person wrote themselves.

    Neither can be detected from here, because there is no way to read the
    target's contents back. `should_replace` already refuses once the person
    has typed, which removes the most likely version of the second case.
    """
    if not replacement:
        return UndoReplacementReceipt(False, False)
    with _EXTERNAL_DELIVERY_LOCK:
        previous_clipboard = clipboard_text()
        previous_pause = getattr(pyautogui, "PAUSE", 0.025)
        undo_attempted = False
        replacement_committed = False
        try:
            # Stage and verify the correction BEFORE Ctrl+Z. A clipboard
            # failure must leave the original insertion completely untouched.
            if not _delivery_is_allowed(can_deliver) or not copy_text(replacement, transient=True):
                return UndoReplacementReceipt(False, False)
            if not _delivery_is_allowed(can_deliver):
                return UndoReplacementReceipt(False, False)
            pyautogui.PAUSE = 0
            pyautogui.hotkey(EDIT_MODIFIER, "z")
            undo_attempted = True
            # From this point the edit is committed. Finish the transaction
            # even if Cancel/Redo arrives; stopping between undo and paste
            # would strand the document with its original insertion removed.
            time.sleep(max(0, int(settle_ms)) / 1000)
            pyautogui.hotkey(EDIT_MODIFIER, "v")
            time.sleep(max(0, int(settle_ms)) / 1000)
            replacement_committed = True
            return UndoReplacementReceipt(True, True)
        except Exception:
            log.warning(
                "undo replacement failed after undo_attempted=%s; refusing any destructive fallback",
                undo_attempted,
                exc_info=True,
            )
            return UndoReplacementReceipt(False, undo_attempted)
        finally:
            pyautogui.PAUSE = previous_pause
            # If Ctrl+Z may have committed but Ctrl+V did not finish, the
            # document may now be empty. Leave the complete replacement on the
            # clipboard as the only non-destructive recovery route. Successful
            # replacement (or a failure before undo) may restore the prior copy.
            if not undo_attempted or replacement_committed:
                with suppress(Exception):
                    restore_clipboard_if_unchanged(replacement, previous_clipboard)


def foreground_window_id() -> int:
    """Handle of the window that currently has focus, or 0 if unknown.

    Used to prove that a speculative replacement is still aimed at the window
    the text was pasted into. Returning 0 on failure is deliberate: the caller
    compares two values, and 0 != 0 is false, so an unavailable handle refuses
    the replacement rather than permitting it.

    On macOS the frontmost application's pid stands in for the window handle:
    other applications' window ids are not readable without Screen Recording
    permission, and the pid answers the only question asked of this value --
    "is focus still where it was when the text was delivered".
    """
    if mac_support.IS_MAC:
        return mac_support.frontmost_window_id()
    try:
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def foreground_focus_window_id() -> int:
    """Focused child-control HWND in the foreground thread, or zero.

    A top-level browser or Word window can contain many independent editors.
    Delayed voice transforms must bind to the focused control that owned the
    original selection, not merely to the outer application window.
    """

    if os.name != "nt":
        return 0

    class _Rect(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class _GuiThreadInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("flags", ctypes.c_uint),
            ("hwndActive", ctypes.c_void_p),
            ("hwndFocus", ctypes.c_void_p),
            ("hwndCapture", ctypes.c_void_p),
            ("hwndMenuOwner", ctypes.c_void_p),
            ("hwndMoveSize", ctypes.c_void_p),
            ("hwndCaret", ctypes.c_void_p),
            ("rcCaret", _Rect),
        ]

    try:
        user32 = ctypes.windll.user32
        foreground = int(user32.GetForegroundWindow() or 0)
        if not foreground:
            return 0
        thread_id = int(user32.GetWindowThreadProcessId(foreground, None) or 0)
        if not thread_id:
            return 0
        info = _GuiThreadInfo()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return 0
        return int(info.hwndFocus or 0)
    except Exception:
        log.debug("foreground control identity unavailable", exc_info=True)
        return 0


def foreground_edit_target_signature() -> tuple[int, ...]:
    """Focused control, caret owner, and caret rectangle for a text target.

    Chromium and Electron often expose one focused renderer HWND for many DOM
    fields. A focused child HWND alone is therefore not an edit-target identity.
    Requiring the caret owner and rectangle closes the common same-renderer
    wrong-field path; when an application does not expose this information the
    caller must fail closed to copy/manual paste.
    """

    if os.name != "nt":
        return ()

    class _Rect(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class _GuiThreadInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("flags", ctypes.c_uint),
            ("hwndActive", ctypes.c_void_p),
            ("hwndFocus", ctypes.c_void_p),
            ("hwndCapture", ctypes.c_void_p),
            ("hwndMenuOwner", ctypes.c_void_p),
            ("hwndMoveSize", ctypes.c_void_p),
            ("hwndCaret", ctypes.c_void_p),
            ("rcCaret", _Rect),
        ]

    try:
        user32 = ctypes.windll.user32
        foreground = int(user32.GetForegroundWindow() or 0)
        if not foreground:
            return ()
        thread_id = int(user32.GetWindowThreadProcessId(foreground, None) or 0)
        if not thread_id:
            return ()
        info = _GuiThreadInfo()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return ()
        focus = int(info.hwndFocus or 0)
        caret = int(info.hwndCaret or 0)
        rect = (
            int(info.rcCaret.left),
            int(info.rcCaret.top),
            int(info.rcCaret.right),
            int(info.rcCaret.bottom),
        )
        if not focus or not caret or rect == (0, 0, 0, 0):
            return ()
        return (focus, caret, *rect)
    except Exception:
        log.debug("foreground edit-target signature unavailable", exc_info=True)
        return ()


def foreground_input_generation() -> int:
    """Windows session input tick, or zero when it cannot be proven.

    The value changes for keyboard, pointer, touch, and remote-session input.
    A speculative correction captures it after the original paste and refuses
    to edit if it changes, closing the same-window/different-field hole that a
    top-level window handle alone cannot detect.
    """

    if os.name != "nt":
        return 0

    class _LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    try:
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0
        return int(info.dwTime)
    except Exception:
        return 0


def activate_foreground_window(window_id: int, *, settle_ms: int = 90) -> bool:
    """Restore a user-chosen external target and prove it owns focus."""

    if os.name != "nt" or not int(window_id or 0):
        return False
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(int(window_id), 9)  # SW_RESTORE
        user32.SetForegroundWindow(int(window_id))
        time.sleep(max(0, int(settle_ms)) / 1000)
        return foreground_window_id() == int(window_id)
    except Exception:
        log.warning("could not restore the requested paste target", exc_info=True)
        return False


def _replace_typed_text_unlocked(backspaces: int, replacement: str, *, interval_ms: int = 2) -> bool:
    """Delete `backspaces` characters behind the cursor and put `replacement` there.

    The first version called pyautogui.press("backspace") in a Python loop.
    pyautogui pauses between every call -- 25ms, set at the top of this module
    -- so deletion ran at forty characters a second and the 900 character cap
    worked out to roughly twenty seconds of a paragraph visibly eating itself.
    Reported from real use as "literally 30 seconds", which matches.

    Two changes fix it. Passing `presses` lets pyautogui repeat the key
    internally and pay the pause once, and PAUSE is suspended for the duration.
    Measured end to end on a real 243 character paragraph: 0.54 seconds, which
    reads as a flicker rather than an animation.

    The replacement is typed rather than pasted. A clipboard paste measured
    marginally quicker, but typing never touches the clipboard -- so a
    correction landing a second later cannot overwrite something the person
    just copied, there is no write-then-read race, and it still works in the
    fields that refuse synthetic Ctrl+V. At about 1ms a character the
    difference is invisible.
    """
    if backspaces < 0:
        return False
    previous_pause = getattr(pyautogui, "PAUSE", 0.1)
    try:
        pyautogui.PAUSE = 0
        if backspaces:
            pyautogui.press("backspace", presses=backspaces, interval=0)
        if replacement:
            for index, line in enumerate(replacement.splitlines() or [replacement]):
                if index:
                    pyautogui.press("enter")
                if line:
                    pyautogui.typewrite(line, interval=0)
        return True
    except Exception:
        # Failing part-way through is the bad case: some backspaces have landed
        # and the replacement has not, so the person is looking at a truncated
        # sentence. Worth knowing about even though there is nothing to undo.
        log.warning(
            "replacement failed after %d backspaces and %d characters",
            backspaces, len(replacement), exc_info=True,
        )
        return False
    finally:
        pyautogui.PAUSE = previous_pause


def replace_typed_text(backspaces: int, replacement: str, *, interval_ms: int = 2) -> bool:
    """Serialize the legacy typed replacement helper with every paste/copy."""

    try:
        with _EXTERNAL_DELIVERY_LOCK:
            return _replace_typed_text_unlocked(
                backspaces,
                replacement,
                interval_ms=interval_ms,
            )
    except Exception:
        log.warning("serialized typed replacement failed", exc_info=True)
        return False


@_serialized_external_delivery
def paste_text_with_receipt(
    text: str,
    *,
    send_enter: bool = False,
    restore_clipboard: bool = False,
    smart_leading_space: bool = False,
    paste_mode: str = "auto",
    typing_interval_ms: int = 2,
    clipboard_paste_delay_ms: int = 10,
    can_deliver: Callable[[], bool] | None = None,
    keep_final_period: bool = False,
) -> PasteReceipt:
    if not text and not send_enter:
        return PasteReceipt(False, str(paste_mode or "auto"), "none", ())
    requested_mode = (paste_mode or "auto").strip().lower()
    mode = requested_mode
    attempts: list[str] = []
    # X-411: where the time goes. His two clipboard pastes on 2026-09-03 took 5.4 s
    # each for no reason the code could show; the log now says which step did.
    marks: dict[str, float] = {"start": time.perf_counter()}
    preserve_rich_clipboard = bool(
        text
        and restore_clipboard
        and requested_mode in {"auto", "clipboard", "shift_insert"}
        and clipboard_contains_non_text_formats()
    )

    rich_snapshot: list[tuple[int, bytes]] | None = None
    if preserve_rich_clipboard:
        # X-406: keep the image or rich selection by snapshotting it and
        # restoring it after the paste. Only when the snapshot cannot be
        # trusted does delivery fall back to typing every character.
        rich_snapshot = snapshot_clipboard()
        if rich_snapshot is not None:
            preserve_rich_clipboard = False

    def cancelled_receipt() -> PasteReceipt:
        if not attempts or attempts[-1] != "cancelled":
            attempts.append("cancelled")
        return PasteReceipt(False, requested_mode, "cancelled", tuple(attempts))

    if not _delivery_is_allowed(can_deliver):
        return cancelled_receipt()

    previous = clipboard_text()
    marks["read"] = time.perf_counter()
    if text and smart_leading_space:
        text = apply_smart_leading_space(text, previous)
    if text:
        text = strip_messenger_trailing_period(text, keep=keep_final_period)

    if mode == "auto":
        mode = "type" if foreground_is_remote_client() else "clipboard"
    elif mode not in {"clipboard", "shift_insert", "type", "copy_only"}:
        mode = "clipboard"
    if preserve_rich_clipboard:
        mode = "type"

    if text and mode == "copy_only":
        attempts.append("copy_only")
        if not _delivery_is_allowed(can_deliver):
            return cancelled_receipt()
        copied = copy_text(text)
        if copied and not _delivery_is_allowed(can_deliver):
            restore_clipboard_if_unchanged(text, previous)
            return cancelled_receipt()
        return PasteReceipt(copied, requested_mode, "copy_only" if copied else "none", tuple(attempts))

    if text and mode == "type":
        # X-463: a held Shift turns typed text into capitals.
        settle_modifiers()
        # Simulated typing avoids the clipboard entirely, for apps/fields that
        # reject programmatic paste. It is also the most reliable local-to-remote
        # path for VNC/RDP/Jump Desktop style clients.
        attempts.append("direct_type")
        type_options: dict[str, object] = {"interval_ms": typing_interval_ms}
        if can_deliver is not None:
            type_options["can_deliver"] = can_deliver
        try:
            typed = _type_text(text, **type_options)
        except CommittedTypingError:
            attempts.append("direct_type_partial")
            return PasteReceipt(False, requested_mode, "direct_type_partial", tuple(attempts))
        if typed:
            try:
                if send_enter and _delivery_is_allowed(can_deliver):
                    pyautogui.press("enter")
                elif send_enter:
                    attempts.append("enter_cancelled")
            except Exception:
                attempts.append("enter_failed")
            return PasteReceipt(True, requested_mode, "direct_type", tuple(attempts))
        if not _delivery_is_allowed(can_deliver):
            return cancelled_receipt()
        if preserve_rich_clipboard:
            attempts.append("protected_rich_clipboard")
            return PasteReceipt(
                False,
                requested_mode,
                "protected_rich_clipboard",
                tuple(attempts),
            )

    # Clipboard and Shift+Insert routes share a verified clipboard write. If the
    # clipboard is busy, or the synthetic paste chord itself fails, direct typing
    # provides a no-clipboard fallback instead of losing the transcript.
    clipboard_method = "shift_insert" if mode == "shift_insert" else "clipboard"
    attempts.append(clipboard_method)
    # X-463: a paste chord sent while the person still holds their hotkey
    # arrives with their modifiers added to it and does nothing.
    settle_modifiers()
    # Borrowed for the paste: transient unless the person keeps it there.
    copied = bool(text and _delivery_is_allowed(can_deliver)
                  and copy_text(text, transient=bool(restore_clipboard)))
    marks["copied"] = time.perf_counter()
    if copied:
        time.sleep(max(0, int(clipboard_paste_delay_ms)) / 1000)

    try:
        if copied:
            if not _delivery_is_allowed(can_deliver):
                return cancelled_receipt()
            try:
                if clipboard_method == "shift_insert":
                    # Apple keyboards have no Insert key. If pyautogui maps it to
                    # something inert the chord "succeeds" and the receipt claims
                    # "Inserted with Shift+Insert" while nothing arrived, so the
                    # Command chord is used instead of a silent no-op.
                    if mac_support.IS_MAC:
                        pyautogui.hotkey(EDIT_MODIFIER, "v")
                    else:
                        pyautogui.hotkey("shift", "insert")
                else:
                    pyautogui.hotkey(EDIT_MODIFIER, "v")
                marks["chord"] = time.perf_counter()
                time.sleep(max(0.01, int(clipboard_paste_delay_ms) / 1000))
            except Exception:
                # Ctrl+V may have committed before a key-release error surfaced.
                # A direct-typing fallback could therefore duplicate the whole
                # result. Keep the complete text on the clipboard and report
                # the commit as unknown; the caller can offer manual paste.
                attempts.append("clipboard_commit_unknown")
                return PasteReceipt(
                    False,
                    requested_mode,
                    "clipboard_commit_unknown",
                    tuple(attempts),
                    fallback_used=False,
                )
            else:
                try:
                    if send_enter and _delivery_is_allowed(can_deliver):
                        pyautogui.press("enter")
                    elif send_enter:
                        attempts.append("enter_cancelled")
                except Exception:
                    attempts.append("enter_failed")
                return PasteReceipt(
                    True,
                    requested_mode,
                    clipboard_method,
                    tuple(attempts),
                    fallback_used=attempts[0] != clipboard_method,
                )

        if text:
            if not _delivery_is_allowed(can_deliver):
                return cancelled_receipt()
            attempts.append("direct_type")
            type_options = {"interval_ms": typing_interval_ms}
            if can_deliver is not None:
                type_options["can_deliver"] = can_deliver
            try:
                typed = _type_text(text, **type_options)
            except CommittedTypingError:
                attempts.append("direct_type_partial")
                return PasteReceipt(
                    False,
                    requested_mode,
                    "direct_type_partial",
                    tuple(attempts),
                    fallback_used=len(attempts) > 2,
                )
            if typed:
                try:
                    if send_enter and _delivery_is_allowed(can_deliver):
                        pyautogui.press("enter")
                    elif send_enter:
                        attempts.append("enter_cancelled")
                except Exception:
                    attempts.append("enter_failed")
                return PasteReceipt(
                    True,
                    requested_mode,
                    "direct_type",
                    tuple(attempts),
                    fallback_used=True,
                )
            if not _delivery_is_allowed(can_deliver):
                return cancelled_receipt()
        elif send_enter:
            attempts.append("enter")
            if not _delivery_is_allowed(can_deliver):
                return cancelled_receipt()
            try:
                pyautogui.press("enter")
                return PasteReceipt(True, requested_mode, "enter", tuple(attempts))
            except Exception:
                pass
        return PasteReceipt(
            False,
            requested_mode,
            "none",
            tuple(attempts),
            fallback_used=len(attempts) > 1,
        )
    finally:
        cancelled = bool(attempts and attempts[-1] == "cancelled")
        commit_unknown = bool(attempts and attempts[-1] == "clipboard_commit_unknown")
        if copied and not commit_unknown and (restore_clipboard or cancelled):
            if restore_clipboard and not cancelled:
                time.sleep(0.2)
            marks["restore"] = time.perf_counter()
            if rich_snapshot is not None:
                restore_clipboard_snapshot(rich_snapshot, text)
            else:
                restore_clipboard_if_unchanged(text, previous)
        marks["end"] = time.perf_counter()
        _log_slow_paste(marks, attempts)


def _log_slow_paste(marks: dict[str, float], attempts: list[str]) -> None:
    """One INFO line per slow delivery, naming the step that took the time."""
    total_ms = (marks.get("end", marks["start"]) - marks["start"]) * 1000.0
    if total_ms < 1000.0:
        return
    order = [name for name in ("read", "copied", "chord", "restore", "end") if name in marks]
    previous = marks["start"]
    parts = []
    for name in order:
        parts.append(f"{name}={int(round((marks[name] - previous) * 1000.0))}ms")
        previous = marks[name]
    log.info("slow paste: total=%dms %s attempts=%s", int(round(total_ms)), " ".join(parts), ",".join(attempts))


def paste_text(
    text: str,
    *,
    send_enter: bool = False,
    restore_clipboard: bool = False,
    smart_leading_space: bool = False,
    paste_mode: str = "auto",
    typing_interval_ms: int = 2,
    clipboard_paste_delay_ms: int = 10,
    can_deliver: Callable[[], bool] | None = None,
) -> bool:
    """Compatibility wrapper for callers that only need success or failure."""

    return bool(
        paste_text_with_receipt(
            text,
            send_enter=send_enter,
            restore_clipboard=restore_clipboard,
            smart_leading_space=smart_leading_space,
            paste_mode=paste_mode,
            typing_interval_ms=typing_interval_ms,
            clipboard_paste_delay_ms=clipboard_paste_delay_ms,
            can_deliver=can_deliver,
        )
    )


def copy_selected_text(timeout: float = 0.18) -> tuple[str, str]:
    with _EXTERNAL_DELIVERY_LOCK:
        previous = clipboard_text()
        if clipboard_contains_non_text_formats():
            log.info(
                "selected-text capture skipped to preserve non-text clipboard formats"
            )
            return "", previous
        sentinel = f"__TALK_DAT_NO_SELECTION_{uuid.uuid4().hex}__"
        if not copy_text(sentinel, transient=True):
            return "", previous
        try:
            pyautogui.hotkey(EDIT_MODIFIER, "c")
            selection_sequence = clipboard_sequence_number()
            time.sleep(timeout)
            selected = clipboard_text()
        except Exception:
            log.warning("selected-text capture failed; refusing clipboard fallback", exc_info=True)
            restore_clipboard_if_unchanged(sentinel, previous)
            return "", previous
        if selected != sentinel:
            if (
                selection_sequence
                and clipboard_sequence_number() == selection_sequence
                and clipboard_text() == selected
                and clipboard_sequence_number() == selection_sequence
            ):
                global _CLIPBOARD_OWNERSHIP
                _CLIPBOARD_OWNERSHIP = (selected, selection_sequence)
            else:
                _CLIPBOARD_OWNERSHIP = None
        if selected == sentinel:
            restore_clipboard_if_unchanged(sentinel, previous)
            selected = ""
        return selected, previous


def restore_clipboard(text: str) -> None:
    copy_text(text, transient=True)
