"""The suite never touches the machine's people: no microphone, no speaker, no
clipboard, no keyboard or mouse, no screen, no other program and no network.

Why this exists, in the owner's own terms (2026-10-20): someone else is using
this computer while agents work on it, Ableton must keep running, and "no test
that plays or grabs audio". The suite already isolates its data folder, the
credential vault, the clipboard's private write and the field read (see
tests/__init__.py), and scripts/run_tests_offscreen.py keeps its windows off the
person's desktop. None of that stops a test that forgot a fake. One unfaked
``sounddevice.RawInputStream`` opens the real microphone; one unfaked
``windows_audio.set_default_output_muted(True)`` mutes the speakers of whoever
is working; one ``pyperclip.copy`` replaces their clipboard. Nothing fails at
the time, which is exactly why a fake was forgotten.

So the guard is installed before any test imports the product, and every one of
those reaches is refused at the last Python-visible point before the device:

* **Audio, always.** Input and output streams, recording and playback
  (sounddevice, PyAudio, WASAPI loopback, winsound, winmm), the app's system
  mute and volume writes, and both loopback captures. Audio devices are shared
  by every desktop and every window station, so no isolation makes them safe.
* **Clipboard, while it is shared.** The clipboard belongs to the window
  STATION, and every desktop in WinSta0 -- the hidden one the offscreen runner
  creates included -- shares the person's. tests/clipboard_station.py makes a
  window station of its own for that reason; inside one, the clipboard is
  private and allowed. Everywhere else (and on a Mac, always) it is refused.
* **Input, while the station is shared.** Synthetic keys and mouse, cursor
  moves, input blocking and global hooks. A global keyboard hook would read the
  person's keystrokes; a synthetic Ctrl+V would land in their document.
* **Screen capture, always.** PIL's ImageGrab and the Mac capture tools.
* **Windows on the person's desktop.** A Tk or web window may open on a hidden
  desktop or a private station, never on the input desktop someone is using.
  The Windows offscreen runner is the way to run GUI tests.
* **Other programs.** No kill or session tool (taskkill, shutdown, logoff,
  pkill), no opener (explorer, os.startfile, webbrowser, open, osascript), no
  signal to a process this run did not start.
* **The network beyond this machine.** Loopback is this machine and stays
  allowed; anything else is refused before a name is even resolved.

Every refusal raises ``DeviceAccessBlocked`` and is also recorded, because
product code often catches ``Exception`` to stay alive: a swallowed refusal
must still show up, so the run prints the list at exit.

``TALK_DAT_REAL_DEVICES=1`` turns all of it off, for a person at their own desk
who chose real hardware. ``TALK_DAT_ALLOW_CONSOLE_WINDOWS=1`` allows only the
windows. No agent unit sets either.
"""

from __future__ import annotations

import atexit
import importlib.abc
import os
import sys
import threading
from typing import Any, Callable

ESCAPE_ENV = "TALK_DAT_REAL_DEVICES"
WINDOWS_ENV = "TALK_DAT_ALLOW_CONSOLE_WINDOWS"

#: Every refusal this process made, in order. The proof reads it; the run
#: prints it at exit.
REPORT: list[str] = []
#: The same refusals with the test that was running when each was made, so a
#: refusal product code swallowed can still be traced to the test behind it.
BY_TEST: list[tuple[str, str]] = []
_report_lock = threading.Lock()
_current_test = [""]


class DeviceAccessBlocked(RuntimeError):
    """A test reached a real device, another program or the network."""


def _refuse(what: str) -> None:
    with _report_lock:
        REPORT.append(what)
        BY_TEST.append((_current_test[0] or "(outside a test)", what))
    raise DeviceAccessBlocked(
        f"{what} was blocked: the test suite never touches a real microphone, speaker, "
        "clipboard, keyboard, mouse, screen, another program or the network (tests/device_guard.py)."
    )


# --- where this process runs -------------------------------------------------

def _windows_object_name(handle: int, user32: Any) -> str:
    import ctypes
    from ctypes import wintypes

    needed = wintypes.DWORD(0)
    buffer = ctypes.create_unicode_buffer(256)
    # UOI_NAME = 2
    if not user32.GetUserObjectInformationW(wintypes.HANDLE(handle), 2, buffer, ctypes.sizeof(buffer),
                                            ctypes.byref(needed)):
        return ""
    return buffer.value


def _read_station_and_desktop() -> tuple[str, str]:
    """(window station, desktop) of this process, read once before anything is
    patched. An unreadable answer is "" and every rule below treats "" as the
    shared, visible case: when in doubt, the person's."""
    if os.name != "nt":
        return "", ""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetProcessWindowStation.restype = wintypes.HANDLE
        user32.GetThreadDesktop.argtypes = (wintypes.DWORD,)
        user32.GetThreadDesktop.restype = wintypes.HANDLE
        user32.GetUserObjectInformationW.argtypes = (
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
        user32.GetUserObjectInformationW.restype = wintypes.BOOL
        station = user32.GetProcessWindowStation() or 0
        desktop = user32.GetThreadDesktop(kernel32.GetCurrentThreadId()) or 0
        return (_windows_object_name(station, user32) if station else "",
                _windows_object_name(desktop, user32) if desktop else "")
    except Exception:
        return "", ""


_STATION, _DESKTOP = "", ""


def shared_station(station: str | None = None) -> bool:
    """Whether the clipboard and input belong to the person (WinSta0, or unknown).

    On a Mac there is one pasteboard and one event stream for everyone, so the
    answer there is always yes.
    """
    if os.name != "nt":
        return True
    name = _STATION if station is None else station
    return not name or name.lower() == "winsta0"


def console_desktop(station: str | None = None, desktop: str | None = None) -> bool:
    """Whether a window opened here would appear in front of the person.

    The interactive desktop of WinSta0 is "Default". The offscreen runner's
    desktop ("talkdat-tests-<pid>") and any private station are not.
    """
    if os.name != "nt":
        return False
    station_name = _STATION if station is None else station
    desktop_name = _DESKTOP if desktop is None else desktop
    if not shared_station(station_name):
        return False
    return not desktop_name or desktop_name.lower() == "default"


def _always() -> bool:
    return True


def _while_shared() -> bool:
    return shared_station()


def _on_console() -> bool:
    return console_desktop() and os.environ.get(WINDOWS_ENV) != "1"


# --- Python-level replacements ------------------------------------------------

def blocked(what: str, policy: Callable[[], bool] = _always, real: Callable[..., Any] | None = None):
    """A stand-in for a device entry point. Refuses while ``policy()`` holds;
    otherwise (a private station, say) calls through to ``real``."""

    def guarded(*args: Any, **kwargs: Any) -> Any:
        if policy() or real is None:
            _refuse(what)
        return real(*args, **kwargs)

    guarded.__talkdat_blocked__ = what
    guarded.__name__ = what.rsplit(".", 1)[-1]
    return guarded


class _RefusingClass:
    """Stands in for a device CLASS used through its class methods
    (``NSPasteboard.generalPasteboard()``): any member or call refuses."""

    def __init__(self, what: str) -> None:
        object.__setattr__(self, "__talkdat_blocked__", what)

    def __getattr__(self, attribute: str) -> Any:
        _refuse(f"{self.__talkdat_blocked__}.{attribute}")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        _refuse(self.__talkdat_blocked__)


def _blocked_init(what: str, policy: Callable[[], bool], real_init: Callable[..., Any]):
    def guarded_init(self: Any, *args: Any, **kwargs: Any) -> None:
        if policy():
            _refuse(what)
        real_init(self, *args, **kwargs)

    guarded_init.__talkdat_blocked__ = what
    return guarded_init


# module name -> [(attribute path, policy)]. A dotted attribute ("PyAudio.open")
# patches a class member. Missing attributes are skipped: the table covers
# several library versions and two platforms.
MODULE_RULES: dict[str, list[tuple[str, Callable[[], bool]]]] = {
    # Audio: microphone, speakers, loopback.
    "sounddevice": [(name, _always) for name in (
        "InputStream", "OutputStream", "Stream", "RawInputStream", "RawOutputStream", "RawStream",
        "rec", "play", "playrec")],
    "pyaudiowpatch": [("PyAudio.open", _always)],
    "pyaudio": [("PyAudio.open", _always)],
    "winsound": [("PlaySound", _always), ("Beep", _always), ("MessageBeep", _always)],
    # The app's own mute and volume WRITES -- the leaves, so a test that fakes the
    # COM layer above them keeps working. The loopback captures are guarded below
    # them instead: pyaudiowpatch here, the Mac helper program in the audit hook.
    # 2026-10-22: and the device-enumerator lookup every read and write starts
    # from, so not even a read reaches the person's speakers (coordinator RULING
    # 2026-10-22T02:22:41Z: isolation covers enumeration, not just streams).
    "knight_flow.windows_audio": [("set_default_output_muted", _always), ("_set_muted", _always),
                                  ("_set_scalar_volume", _always), ("_default_endpoint_volume", _always)],
    # Clipboard.
    "pyperclip": [("copy", _while_shared), ("paste", _while_shared)],
    "win32clipboard": [(name, _while_shared) for name in (
        "OpenClipboard", "EmptyClipboard", "SetClipboardData", "GetClipboardData", "SetClipboardText")],
    # Input synthesis and global hooks.
    "pyautogui": [(name, _while_shared) for name in (
        "hotkey", "press", "keyDown", "keyUp", "typewrite", "write", "click", "doubleClick", "tripleClick",
        "rightClick", "middleClick", "mouseDown", "mouseUp", "moveTo", "moveRel", "move", "dragTo", "dragRel",
        "drag", "scroll", "hscroll", "vscroll", "screenshot")],
    "pynput.keyboard": [("Controller", _while_shared), ("Listener", _while_shared),
                        ("Events", _while_shared), ("GlobalHotKeys", _while_shared)],
    "pynput.mouse": [("Controller", _while_shared), ("Listener", _while_shared), ("Events", _while_shared)],
    "keyboard": [(name, _while_shared) for name in (
        "send", "press", "release", "write", "hook", "on_press", "on_release", "add_hotkey", "record",
        "block_key", "press_and_release", "hook_key")],
    # Screen capture.
    "PIL.ImageGrab": [("grab", _always), ("grabclipboard", _while_shared)],
    "mss": [("mss", _always)],
    # macOS: events, the pasteboard, the screen.
    "Quartz": [(name, _always) for name in (
        "CGEventPost", "CGEventPostToPid", "CGEventPostToPSN", "CGEventTapCreate", "CGWindowListCreateImage",
        "CGDisplayCreateImage")],
    "AppKit": [("NSPasteboard", _always)],
    # Windows that would appear in front of the person.
    "webview": [("create_window", _on_console), ("start", _on_console)],
}

# Classes reached through class methods rather than construction.
_CLASS_STAND_INS: dict[str, tuple[str, ...]] = {"AppKit": ("NSPasteboard",)}

# Constructors are wrapped at __init__ so the class itself survives
# (isinstance checks, subclassing) and only building one is refused.
_INIT_RULES: dict[str, list[tuple[str, Callable[[], bool]]]] = {
    "tkinter": [("Tk", _on_console)],
}

# Methods of an object the suite builds freely (a Tk root on a hidden desktop),
# whose single job is the shared clipboard.
_METHOD_RULES: dict[str, list[tuple[str, Callable[[], bool]]]] = {
    "tkinter": [("Misc.clipboard_append", _while_shared), ("Misc.clipboard_clear", _while_shared),
                ("Misc.clipboard_get", _while_shared), ("Misc.selection_get", _while_shared)],
}

_patched_modules: set[str] = set()


def patch_module(module: Any, name: str) -> list[str]:
    """Apply every rule for ``name`` to ``module``. Returns what was replaced."""
    done: list[str] = []
    for attribute, policy in MODULE_RULES.get(name, ()):
        owner, _, leaf = attribute.rpartition(".")
        target = module
        try:
            for part in filter(None, owner.split(".")):
                target = getattr(target, part)
            current = getattr(target, leaf)
        except Exception:
            continue
        if getattr(current, "__talkdat_blocked__", None):
            continue
        real = None if policy is _always else current
        try:
            if attribute in _CLASS_STAND_INS.get(name, ()):
                setattr(target, leaf, _RefusingClass(f"{name}.{attribute}"))
            else:
                setattr(target, leaf, blocked(f"{name}.{attribute}", policy, real))
            done.append(attribute)
        except Exception:
            continue
    for attribute, policy in _INIT_RULES.get(name, ()):
        cls = getattr(module, attribute, None)
        if cls is None or getattr(cls.__init__, "__talkdat_blocked__", None):
            continue
        cls.__init__ = _blocked_init(f"{name}.{attribute}()", policy, cls.__init__)
        done.append(f"{attribute}.__init__")
    for attribute, policy in _METHOD_RULES.get(name, ()):
        owner, _, leaf = attribute.rpartition(".")
        cls = getattr(module, owner, None)
        current = getattr(cls, leaf, None) if cls is not None else None
        if current is None or getattr(current, "__talkdat_blocked__", None):
            continue

        def method(self: Any, *args: Any, __real=current, __what=f"{name}.{attribute}", __policy=policy,
                   **kwargs: Any) -> Any:
            if __policy():
                _refuse(__what)
            return __real(self, *args, **kwargs)

        method.__talkdat_blocked__ = f"{name}.{attribute}"
        setattr(cls, leaf, method)
        done.append(attribute)
    _patched_modules.add(name)
    return done


class _PatchingLoader(importlib.abc.Loader):
    """Runs the real loader, then applies the rules before anyone sees the module."""

    def __init__(self, loader: Any, name: str) -> None:
        self._loader = loader
        self._name = name

    def create_module(self, spec: Any) -> Any:
        create = getattr(self._loader, "create_module", None)
        return create(spec) if create is not None else None

    def exec_module(self, module: Any) -> None:
        self._loader.exec_module(module)
        patch_module(module, self._name)

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self._loader, attribute)


class _PatchAfterImport(importlib.abc.MetaPathFinder):
    """Intercepts the guarded module names only; every other import is untouched."""

    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        if fullname not in MODULE_RULES and fullname not in _INIT_RULES and fullname not in _METHOD_RULES:
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            find = getattr(finder, "find_spec", None)
            if find is None:
                continue
            spec = find(fullname, path, target)
            if spec is not None:
                break
        else:
            return None
        if spec.loader is not None and not isinstance(spec.loader, _PatchingLoader):
            spec.loader = _PatchingLoader(spec.loader, fullname)
        return spec


# --- the foreign-function layer (Windows) ------------------------------------

#: dll base name -> {function: policy}. Looked up at the first attribute access
#: on ANY loader instance (ctypes.windll.user32 or a fresh WinDLL("user32")).
FOREIGN_RULES: dict[str, dict[str, Callable[[], bool]]] = {
    "user32": {
        **{name: _while_shared for name in (
            "SendInput", "keybd_event", "mouse_event", "SetCursorPos", "BlockInput",
            "SetWindowsHookExA", "SetWindowsHookExW", "RegisterHotKey",
            "OpenClipboard", "EmptyClipboard", "SetClipboardData", "GetClipboardData",
            "AddClipboardFormatListener", "SetClipboardViewer", "ChangeClipboardChain")},
        "MessageBeep": _always,
    },
    "winmm": {name: _always for name in (
        "PlaySound", "PlaySoundA", "PlaySoundW", "sndPlaySoundA", "sndPlaySoundW", "waveInOpen", "waveOutOpen",
        "mciSendStringA", "mciSendStringW", "mciSendCommandA", "mciSendCommandW", "midiOutOpen",
        # The MIDI hotkey opens every MIDI input it finds (hotkeys.py), and a
        # MIDI input is often one program's at a time: the person's controller.
        "midiInOpen", "midiInStart")},
    "kernel32": {"TerminateProcess": _always, "Beep": _always},
    # macOS Accessibility: reading another program's text, or selecting in it
    # (T1, knight_flow/verified_target_mac.py). Tests drive tests/simulated_ax.py.
    "applicationservices": {name: _always for name in (
        "AXIsProcessTrusted", "AXIsProcessTrustedWithOptions", "AXUIElementCreateSystemWide",
        "AXUIElementCreateApplication", "AXUIElementCopyAttributeValue", "AXUIElementCopyAttributeValues",
        "AXUIElementCopyParameterizedAttributeValue", "AXUIElementSetAttributeValue",
        "AXUIElementPerformAction", "AXUIElementGetPid", "AXUIElementSetMessagingTimeout", "AXObserverCreate")},
}

#: dll base name -> {function: what a call answers}. Device LISTINGS the suite
#: answers itself (coordinator RULING 2026-10-22T02:22:41Z): no MIDI or wave
#: device and no game controller is ever found, so nothing is opened or read.
_NO_DEVICES, _BAD_DEVICE_ID, _NOT_CONNECTED = 0, 2, 1167  # MMSYSERR_BADDEVICEID, ERROR_DEVICE_NOT_CONNECTED
FOREIGN_STAND_INS: dict[str, dict[str, int]] = {
    "winmm": {
        **{name: _NO_DEVICES for name in (
            "midiInGetNumDevs", "midiOutGetNumDevs", "waveInGetNumDevs", "waveOutGetNumDevs")},
        **{name: _BAD_DEVICE_ID for name in (
            "midiInGetDevCapsA", "midiInGetDevCapsW", "midiOutGetDevCapsA", "midiOutGetDevCapsW",
            "waveInGetDevCapsA", "waveInGetDevCapsW", "waveOutGetDevCapsA", "waveOutGetDevCapsW")},
    },
    **{dll: {"XInputGetState": _NOT_CONNECTED, "XInputGetCapabilities": _NOT_CONNECTED}
       for dll in ("xinput1_4", "xinput1_3", "xinput9_1_0")},
}

_inside_guard = threading.local()


def _dll_base(dll: Any) -> str:
    name = str(getattr(dll, "_name", "") or "")
    base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return base[:-4] if base.endswith(".dll") else base


class _GuardedForeignFunction:
    """A foreign function whose every call is judged first. argtypes, restype
    and errcheck pass through to the real pointer, so a setup that configures
    the function keeps working; only the call is refused."""

    def __init__(self, real: Any, what: str, policy: Callable[[], bool]) -> None:
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_what", what)
        object.__setattr__(self, "_policy", policy)
        object.__setattr__(self, "__talkdat_blocked__", what)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._policy():
            # ctypes refuses an argument that does not fit argtypes before any
            # native call; a refused call keeps that answer, so a test whose
            # premise is "ctypes rejects this argument" still proves it.
            argtypes = getattr(self._real, "argtypes", None) or ()
            for index, (kind, value) in enumerate(zip(argtypes, args), start=1):
                from_param = getattr(kind, "from_param", None)
                if from_param is None:
                    continue
                try:
                    from_param(value)
                except Exception as error:
                    import ctypes

                    raise ctypes.ArgumentError(f"argument {index}: {type(error).__name__}: {error}") from None
            _refuse(self._what)
        return self._real(*args, **kwargs)

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self._real, attribute)

    def __setattr__(self, attribute: str, value: Any) -> None:
        setattr(self._real, attribute, value)


class _StandInForeignFunction:
    """A foreign function the suite answers itself (FOREIGN_STAND_INS): the real
    one is never called. argtypes, restype and errcheck still reach the real
    pointer, as with _GuardedForeignFunction."""

    def __init__(self, real: Any, what: str, answer: int) -> None:
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_answer", answer)
        object.__setattr__(self, "__talkdat_blocked__", f"{what} (stand-in)")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._answer

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self._real, attribute)

    def __setattr__(self, attribute: str, value: Any) -> None:
        setattr(self._real, attribute, value)


def _foreign_replacement(func: Any, dll: str, name: str) -> Any:
    answer = FOREIGN_STAND_INS.get(dll, {}).get(name)
    if answer is not None:
        return _StandInForeignFunction(func, f"{dll}.{name}", answer)
    policy = FOREIGN_RULES.get(dll, {}).get(name)
    if policy is not None:
        return _GuardedForeignFunction(func, f"{dll}.{name}", policy)
    return func


def _install_foreign_guard() -> None:
    import ctypes

    if getattr(ctypes.CDLL.__getitem__, "__talkdat_blocked__", None):
        return
    real_getitem = ctypes.CDLL.__getitem__

    def guarded_getitem(self: Any, name_or_ordinal: Any) -> Any:
        _inside_guard.active = True
        try:
            func = real_getitem(self, name_or_ordinal)
        finally:
            _inside_guard.active = False
        if isinstance(name_or_ordinal, str):
            return _foreign_replacement(func, _dll_base(self), name_or_ordinal)
        return func

    guarded_getitem.__talkdat_blocked__ = "ctypes.CDLL.__getitem__"
    ctypes.CDLL.__getitem__ = guarded_getitem
    # Loaders already built and functions already looked up before this ran.
    for loader in (getattr(ctypes, "windll", None), getattr(ctypes, "cdll", None), getattr(ctypes, "oledll", None)):
        for dll in list(getattr(loader, "__dict__", {}).values()) if loader is not None else ():
            if not isinstance(dll, ctypes.CDLL):
                continue
            base = _dll_base(dll)
            for name in (*FOREIGN_RULES.get(base, {}), *FOREIGN_STAND_INS.get(base, {})):
                cached = dll.__dict__.get(name)
                if cached is not None and not isinstance(cached, (_GuardedForeignFunction, _StandInForeignFunction)):
                    dll.__dict__[name] = _foreign_replacement(cached, base, name)


# --- programs, signals, openers and the network: the audit hook --------------

#: Programs a test may never start: they end other people's work, end the
#: session, or open something in front of the person.
FORBIDDEN_PROGRAMS = frozenset({
    "taskkill", "tskill", "shutdown", "logoff", "tsdiscon", "rundll32", "pkill", "killall", "kill", "xkill",
    "explorer", "osascript", "afplay", "say", "screencapture", "open", "xdg-open", "nircmd", "powercfg",
    # The Mac system-audio (loopback) helper that knight_flow.mac_system_audio starts.
    "talkdatsystemaudio",
})

_children: set[int] = set()
_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})


def _program_of(args: Any, executable: Any) -> str:
    """Base name of the program a Popen would start, without .exe."""
    text = executable if executable else args
    if isinstance(text, (list, tuple)):
        text = text[0] if text else ""
    text = os.fspath(text) if not isinstance(text, (str, bytes)) else text
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    text = str(text).strip()
    if not executable:
        # On Windows the audit event carries the command LINE.
        if text.startswith('"'):
            text = text[1:].split('"', 1)[0]
        else:
            text = text.split(" ", 1)[0]
    base = text.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def _command_line(args: Any) -> str:
    return " ".join(map(str, args)) if isinstance(args, (list, tuple)) else str(args)


def _is_start_command(args: Any) -> bool:
    """`cmd /c start ...` opens a window or a program in front of the person."""
    lowered = f" {_command_line(args).lower()} "
    return " /c start " in lowered or " /k start " in lowered


_POWERSHELL_STOPS = ("stop-process", "stop-computer", "restart-computer", "logoff", "stop-service")


def _powershell_stops_something(args: Any) -> bool:
    """An inline PowerShell command that stops a process, a service or the
    session. The installer tests define their OWN ``function Stop-Process`` that
    only records the call; a command that defines the name it uses is theirs.
    A script passed by -File cannot be read here and is the test's to own."""
    lowered = _command_line(args).lower()
    for verb in _POWERSHELL_STOPS:
        if verb in lowered and f"function {verb}" not in lowered:
            return True
    return False


def loopback_host(host: Any) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    text = str(host).strip().lower().strip("[]")
    if text in ("", "::1", "0:0:0:0:0:0:0:1") or text in _LOOPBACK_NAMES or text.endswith(".localhost"):
        return True
    return text.startswith("127.")


def _audit(event: str, args: tuple) -> None:
    if event == "socket.connect" or event == "socket.sendto":
        address = args[1] if len(args) > 1 else None
        if isinstance(address, tuple) and address and not loopback_host(address[0]):
            _refuse(f"{event} to {address[0]}")
    elif event == "socket.getaddrinfo":
        if args and not loopback_host(args[0]):
            _refuse(f"socket.getaddrinfo for {args[0]}")
    elif event == "subprocess.Popen":
        executable, command = (args[0], args[1]) if len(args) > 1 else (None, args[0] if args else "")
        program = _program_of(command, executable)
        if program in FORBIDDEN_PROGRAMS or (program == "cmd" and _is_start_command(command)):
            _refuse(f"starting {program}")
        if program in ("powershell", "pwsh") and _powershell_stops_something(command):
            _refuse(f"a {program} command that stops a process, a service or the session")
    elif event == "os.kill":
        pid = args[0] if args else None
        if pid != os.getpid() and pid not in _children:
            _refuse(f"a signal to process {pid}, which this run did not start")
    elif event == "os.startfile":
        _refuse("os.startfile")
    elif event == "webbrowser.open":
        _refuse("webbrowser.open")
    elif event == "ctypes.dlsym":
        # A prototype built straight from (name, dll) skips CDLL.__getitem__.
        if len(args) > 1 and isinstance(args[1], str) and not getattr(_inside_guard, "active", False):
            dll = args[0]
            base = _dll_base(dll)
            if FOREIGN_RULES.get(base, {}).get(args[1]) is not None or args[1] in FOREIGN_STAND_INS.get(base, {}):
                _refuse(f"{base}.{args[1]} looked up outside the guard")


_AUDITED = frozenset({"socket.connect", "socket.sendto", "socket.getaddrinfo", "subprocess.Popen", "os.kill",
                      "os.startfile", "webbrowser.open", "ctypes.dlsym"})


def _hook(event: str, args: tuple) -> None:
    if event in _AUDITED and _state["on"]:
        _audit(event, args)


def _track_children() -> None:
    import subprocess

    if getattr(subprocess.Popen.__init__, "__talkdat_blocked__", None):
        return
    real_init = subprocess.Popen.__init__

    def tracking_init(self: Any, *args: Any, **kwargs: Any) -> None:
        real_init(self, *args, **kwargs)
        pid = getattr(self, "pid", None)
        if isinstance(pid, int):
            _children.add(pid)

    tracking_init.__talkdat_blocked__ = "subprocess.Popen (tracked)"
    subprocess.Popen.__init__ = tracking_init


def _guard_openers() -> None:
    import webbrowser

    for name in ("open", "open_new", "open_new_tab"):
        current = getattr(webbrowser, name, None)
        if current is not None and not getattr(current, "__talkdat_blocked__", None):
            setattr(webbrowser, name, blocked(f"webbrowser.{name}"))
    if hasattr(os, "startfile") and not getattr(os.startfile, "__talkdat_blocked__", None):
        os.startfile = blocked("os.startfile")


# --- install -----------------------------------------------------------------

_state = {"on": False, "hooked": False}


def _report_at_exit() -> None:
    if REPORT:
        unique = sorted(set(REPORT))
        print(f"device guard: {len(REPORT)} refusal(s), {len(unique)} distinct: " + "; ".join(unique[:40]),
              file=sys.stderr)
        counts: dict[tuple[str, str], int] = {}
        for entry in BY_TEST:
            counts[entry] = counts.get(entry, 0) + 1
        for (test, what), count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:80]:
            print(f"device guard: by test: {test}: {what} x{count}", file=sys.stderr)


def _track_tests() -> None:
    """Name the test that is running, for the by-test report."""
    import unittest

    run = unittest.TestCase.run
    if getattr(run, "__talkdat_blocked__", None):
        return

    def tracked_run(self: Any, result: Any = None) -> Any:
        previous = _current_test[0]
        _current_test[0] = self.id()
        try:
            return run(self, result)
        finally:
            _current_test[0] = previous

    tracked_run.__talkdat_blocked__ = "unittest.TestCase.run (tracked)"
    unittest.TestCase.run = tracked_run


def installed() -> bool:
    return _state["on"]


def status() -> dict[str, Any]:
    """What the guard did here, for the proof and the unit's log."""
    return {"on": _state["on"], "station": _STATION, "desktop": _DESKTOP,
            "shared_station": shared_station(), "console_desktop": console_desktop(),
            "patched_modules": sorted(_patched_modules), "refusals": len(REPORT)}


def install() -> bool:
    """Install once, before any test imports the product. Returns whether the
    guard is on (False only when a person chose real devices)."""
    global _STATION, _DESKTOP
    if os.environ.get(ESCAPE_ENV) == "1":
        return False
    if _state["on"]:
        return True
    _STATION, _DESKTOP = _read_station_and_desktop()
    finder = _PatchAfterImport()
    sys.meta_path.insert(0, finder)
    for name in set(MODULE_RULES) | set(_INIT_RULES) | set(_METHOD_RULES):
        module = sys.modules.get(name)
        if module is not None:
            patch_module(module, name)
    if os.name == "nt":
        _install_foreign_guard()
    _track_children()
    _guard_openers()
    _track_tests()
    _state["on"] = True
    if not _state["hooked"]:
        sys.addaudithook(_hook)
        _state["hooked"] = True
        atexit.register(_report_at_exit)
    return True
