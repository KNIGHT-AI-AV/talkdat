"""What kind of field a dictation is going into, read once as the take starts.

Commandments 52, 77 and 78 (docs/DICTATION-COMMANDMENTS.md): a password field
gets the words exactly as said and nothing about the take is kept; a terminal
gets command text; a single-line field never gets a line break. The kind is
read when the recording starts, while the person's focus is still on the
target, through the same accessibility interfaces caret_context.py uses: UI
Automation on Windows, the AX API on a Mac. It reads the control's TYPE only,
never its text, shares the caret reader's lock, and gives up quickly.

A terminal is known by its app, not its control: consoles do not describe
themselves consistently to accessibility clients, but their executables and
app bundles are few and stable.
"""
from __future__ import annotations

import os
import sys
import threading

PASSWORD = "password"
CONSOLE = "console"
SINGLE_LINE = "single-line"
MULTI_LINE = "multi-line"
UNKNOWN = ""

#: Foreground executables (Windows) and app bundles (macOS, as
#: mac_support.frontmost_app_name reports them) that are terminals.
TERMINAL_APPS = frozenset({
    "windowsterminal.exe", "openconsole.exe", "conhost.exe", "cmd.exe", "powershell.exe",
    "pwsh.exe", "powershell_ise.exe", "wsl.exe", "wslhost.exe", "bash.exe", "mintty.exe",
    "alacritty.exe", "wezterm-gui.exe", "tabby.exe", "hyper.exe", "warp.exe", "kitty.exe",
    "putty.exe", "kitty_portable.exe", "conemu.exe", "conemu64.exe", "cmder.exe", "rio.exe",
    "ghostty.exe", "fluentterminal.app.exe",
    "terminal.app", "iterm.app", "iterm2.app", "warp.app", "ghostty.app", "kitty.app",
    "alacritty.app", "wezterm.app", "hyper.app", "tabby.app", "rio.app",
})

_ES_MULTILINE = 0x0004
_GWL_STYLE = -16


def is_terminal_app(name: object) -> bool:
    return isinstance(name, str) and name.strip().lower() in TERMINAL_APPS


def _win32_edit_is_multiline(hwnd: int) -> bool | None:
    """A classic Win32 edit or rich edit states it in its own window style."""
    import ctypes

    user32 = ctypes.windll.user32
    name = ctypes.create_unicode_buffer(64)
    if not user32.GetClassNameW(hwnd, name, 64):
        return None
    klass = name.value.lower()
    if klass != "edit" and not klass.startswith("richedit"):
        return None
    return bool(user32.GetWindowLongW(hwnd, _GWL_STYLE) & _ES_MULTILINE)


def _kind_from_aria(properties: object) -> str:
    """Chromium and Firefox name a text box's line mode in its ARIA properties."""
    for item in str(properties or "").lower().split(";"):
        key, _, value = item.partition("=")
        if key.strip() == "multiline":
            return MULTI_LINE if value.strip() == "true" else SINGLE_LINE
    return UNKNOWN


def _kind_uia(automation, uia) -> str:
    element = automation.GetFocusedElement()
    if not element:
        return UNKNOWN
    if element.CurrentIsPassword:
        return PASSWORD
    control = element.CurrentControlType
    if control == uia.UIA_DocumentControlTypeId:
        return MULTI_LINE
    if control != uia.UIA_EditControlTypeId:
        return UNKNOWN
    hwnd = element.CurrentNativeWindowHandle
    if hwnd:
        multi = _win32_edit_is_multiline(hwnd)
        if multi is not None:
            return MULTI_LINE if multi else SINGLE_LINE
    return _kind_from_aria(element.CurrentAriaProperties)


def _read_windows() -> str:
    import comtypes
    from comtypes.client import CreateObject, GetModule

    comtypes.CoInitialize()
    try:
        uia = GetModule("UIAutomationCore.dll")
        automation = CreateObject(uia.CUIAutomation8, interface=uia.IUIAutomation2)
        automation.AutoSetFocus = False
        automation.ConnectionTimeout = 100
        automation.TransactionTimeout = 100
        return _kind_uia(automation, uia)
    finally:
        comtypes.CoUninitialize()


def _kind_from_ax(role: str, subrole: str) -> str:
    if subrole == "AXSecureTextField":
        return PASSWORD
    if role == "AXTextArea":
        return MULTI_LINE
    if role in {"AXTextField", "AXComboBox"}:
        return SINGLE_LINE
    return UNKNOWN


def _read_macos() -> str:
    import ctypes as c
    from contextlib import ExitStack

    ax = c.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    cf = c.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    ptr = c.c_void_p

    def bind(lib, name, result, *args):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, args
        return fn

    trusted = bind(ax, "AXIsProcessTrusted", c.c_bool)
    if not trusted():
        return UNKNOWN  # This read never prompts for a new permission.
    system = bind(ax, "AXUIElementCreateSystemWide", ptr)
    timeout = bind(ax, "AXUIElementSetMessagingTimeout", c.c_int, ptr, c.c_float)
    attribute = bind(ax, "AXUIElementCopyAttributeValue", c.c_int, ptr, ptr, c.POINTER(ptr))
    make_string = bind(cf, "CFStringCreateWithCString", ptr, ptr, c.c_char_p, c.c_uint32)
    string_type = bind(cf, "CFStringGetTypeID", c.c_ulong)
    type_id = bind(cf, "CFGetTypeID", c.c_ulong, ptr)
    string = bind(cf, "CFStringGetCString", c.c_bool, ptr, ptr, c.c_long, c.c_uint32)
    release = bind(cf, "CFRelease", None, ptr)
    utf8 = 0x08000100
    with ExitStack() as refs:
        def owned(value):
            if value:
                refs.callback(release, value)
            return value

        def get(element, name):
            value = ptr()
            key = owned(make_string(None, name.encode("ascii"), utf8))
            if attribute(element, key, c.byref(value)) != 0:
                return None
            return owned(value.value)

        def as_string(value):
            if not value or type_id(value) != string_type():
                return ""
            buffer = c.create_string_buffer(128)
            return buffer.value.decode("utf-8") if string(value, buffer, len(buffer), utf8) else ""

        root = owned(system())
        timeout(root, 0.1)
        element = get(root, "AXFocusedUIElement")
        if not element:
            return UNKNOWN
        return _kind_from_ax(as_string(get(element, "AXRole")), as_string(get(element, "AXSubrole")))


def read_field_kind(app_name: str | None = None) -> str:
    """The focused field's kind, or UNKNOWN. Never raises, never waits on a lock."""
    if app_name is None:
        try:
            from .profiles import foreground_process_name

            app_name = foreground_process_name()
        except Exception:
            app_name = ""
    if is_terminal_app(app_name):
        return CONSOLE
    if sys.platform not in {"win32", "darwin"} or os.environ.get("TALK_DAT_FIELD_READ_OFF") == "1":
        return UNKNOWN
    from .caret_context import _READ_LOCK

    if not _READ_LOCK.acquire(blocking=False):
        return UNKNOWN
    try:
        return _read_windows() if sys.platform == "win32" else _read_macos()
    except Exception:
        return UNKNOWN
    finally:
        _READ_LOCK.release()


class FieldProbe:
    """One field read, started with the take and collected when it ends.

    Starting costs nothing on the caller's thread. Until the read answers,
    ``pending`` is True, and anything that would put the words on screen
    treats the take as possibly secure.
    """

    def __init__(self, kind: str | None = None) -> None:
        self._kind = UNKNOWN if kind is None else kind
        self._done = threading.Event()
        if kind is not None:
            self._done.set()

    @classmethod
    def start(cls, reader=read_field_kind) -> "FieldProbe":
        probe = cls()

        def run() -> None:
            try:
                probe._kind = reader() or UNKNOWN
            except Exception:
                probe._kind = UNKNOWN
            finally:
                probe._done.set()

        threading.Thread(target=run, name="field-kind", daemon=True).start()
        return probe

    @property
    def pending(self) -> bool:
        return not self._done.is_set()

    def result(self, timeout: float = 0.25) -> str:
        """The kind; UNKNOWN if the read has not answered within timeout."""
        self._done.wait(max(0.0, timeout))
        return self._kind if self._done.is_set() else UNKNOWN

    def secure_or_pending(self) -> bool:
        return self.pending or self._kind == PASSWORD
