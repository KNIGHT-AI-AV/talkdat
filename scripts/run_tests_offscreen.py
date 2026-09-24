"""Run the test suite on its own Windows desktop, so it never appears on his.

His words, mid-session, while a GUI test was being re-run to chase a flake:
"Get this shit off my screen. It keeps going crazy popping up over and over
again. Put it in the second screen or something. Second desktop."

He is right, and Windows has the exact primitive for it. A DESKTOP is a
separate window surface inside a window station: windows created there are
real, interactive to the process that owns them, and invisible on the desktop
a person is looking at. It is what the service host uses, and it costs one
CreateDesktopW call plus one field in STARTUPINFO.

This is not a headless mode. Tk still runs, still creates real windows, still
measures real fonts -- so the GUI tests keep proving what they prove. They
simply do it somewhere nobody is trying to work.

    python scripts/run_tests_offscreen.py                  # the whole suite
    python scripts/run_tests_offscreen.py tests.test_ui_scale
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
from pathlib import Path
from ctypes import wintypes

GENERIC_ALL = 0x10000000
#: No console at all. A console would be created on the hidden desktop and
#: therefore be invisible anyway, but not creating one is simpler and means
#: the output has exactly one destination: the log file below.
CREATE_NO_WINDOW = 0x08000000
#: Per-invocation, because two runs at once would otherwise share a desktop
#: AND a log file: the second clobbers the first's output and the first's
#: CloseDesktop pulls the surface from under the second. Found by probing
#: the exit code while a full suite happened to be running, which reported
#: a passing module as a failure.
DESKTOP_NAME = f"talkdat-tests-{os.getpid()}"


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


def main() -> int:
    if not sys.platform.startswith("win"):
        print("Windows only; run the suite directly elsewhere.", file=sys.stderr)
        return 2

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.CreateDesktopW.restype = wintypes.HANDLE

    desktop = user32.CreateDesktopW(DESKTOP_NAME, None, None, 0, GENERIC_ALL, None)
    if not desktop:
        print(f"could not create the desktop: {ctypes.get_last_error()}", file=sys.stderr)
        return 3

    argv = sys.argv[1:] or ["discover", "-s", "tests"]
    log = Path(tempfile.gettempdir()) / f"talkdat-offscreen-{os.getpid()}.log"
    # cmd does the redirection, because a process on another desktop has no
    # console of ours to inherit. The whole command is wrapped in one more pair
    # of quotes, which is how cmd /c wants a quoted program plus redirection.
    inner = f'"{sys.executable}" scripts/run_isolated_tests.py ' + " ".join(argv) + f' > "{log}" 2>&1'
    # cmd /c "<the whole thing>". The doubled quote at the front is correct and
    # is how cmd wants a quoted program followed by redirection: it strips the
    # outer pair and runs the rest verbatim.
    command = 'cmd /c "' + inner + '"'

    startup = STARTUPINFOW()
    startup.cb = ctypes.sizeof(startup)
    # The one line that does the work. Every window the child creates -- and
    # every window Tk creates inside it -- belongs to that desktop.
    # "WinSta0" + backslash + the desktop name, spelled without a backslash
    # literal so no editor, heredoc or shell on the way in can eat it.
    startup.lpDesktop = "WinSta0" + chr(92) + DESKTOP_NAME
    info = PROCESS_INFORMATION()

    # A new console, because a child on another desktop cannot share this one.
    # Output is written to the file below rather than inherited.
    if not kernel32.CreateProcessW(
        None, ctypes.create_unicode_buffer(command), None, None, False,
        CREATE_NO_WINDOW, None, None, ctypes.byref(startup), ctypes.byref(info),
    ):
        print(f"could not start the suite: {ctypes.get_last_error()}", file=sys.stderr)
        user32.CloseDesktop(desktop)
        return 4

    print(f"running on desktop '{DESKTOP_NAME}' (pid {info.dwProcessId}); "
          "nothing appears on your screen.")
    print(f"output: {log}")
    kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(info.hThread)
    kernel32.CloseHandle(info.hProcess)
    user32.CloseDesktop(desktop)
    if log.exists():
        # Bytes, not text: a cp1252 console cannot encode U+FFFD, and a crash
        # here used to swallow the whole suite result (2026-09-22).
        sys.stdout.flush()
        sys.stdout.buffer.write(log.read_bytes())
        sys.stdout.buffer.flush()
        log.unlink(missing_ok=True)
    return int(code.value)


if __name__ == "__main__":
    raise SystemExit(main())
