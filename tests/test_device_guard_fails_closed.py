"""The device guard refuses every planted reach for a real device, and refuses it
BEFORE the device.

The planted calls are chosen so that a broken guard still harms nothing, which
is what lets this module run on a machine somebody is using -- and lets its
sabotage twins (the guard with one rule removed) run there too:

* Where a real call would be harmless if it got through, it is real: SendInput
  with zero events, `taskkill /?`, `Stop-Process -WhatIf` on an impossible
  process, a signal to an impossible process, a connection to TEST-NET-1
  (192.0.2.1, which routes nowhere), a function lookup that is never called.
* Where a real call would not be harmless -- opening the microphone or the
  loopback, writing the clipboard, synthesizing a key, playing a sound -- the
  library itself is replaced by a stand-in of the SAME NAME that only writes
  down that it was reached. The guard's import hook cannot tell the difference,
  so the stand-in proves the hook; if the guard fails, the stand-in is what
  gets reached, never the hardware.
* The app's own mute and loopback entry points are never called here at all:
  the proof is that they were replaced.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
import webbrowser
from pathlib import Path

from tests import device_guard as guard

ROOT = Path(guard.__file__).resolve().parents[1]
WINDOWS = os.name == "nt"

# One stand-in per library. Each records into standin_log.REACHED when any of
# its device entry points runs, and does nothing else.
_STANDINS = {
    "standin_log.py": "REACHED = []\n",
    "sounddevice.py": """
        import standin_log
        class _Stream:
            def __init__(self, *a, **k):
                standin_log.REACHED.append(type(self).__name__)
        class InputStream(_Stream): pass
        class OutputStream(_Stream): pass
        class RawInputStream(_Stream): pass
        class RawOutputStream(_Stream): pass
        class Stream(_Stream): pass
        class RawStream(_Stream): pass
        def rec(*a, **k): standin_log.REACHED.append("rec")
        def play(*a, **k): standin_log.REACHED.append("play")
        def playrec(*a, **k): standin_log.REACHED.append("playrec")
        def query_devices(*a, **k): return []
    """,
    "pyaudiowpatch/__init__.py": """
        import standin_log
        class PyAudio:
            def open(self, *a, **k): standin_log.REACHED.append("PyAudio.open (loopback)")
            def terminate(self): pass
    """,
    "winsound.py": """
        import standin_log
        SND_FILENAME = 0x20000
        SND_ASYNC = 1
        def PlaySound(*a, **k): standin_log.REACHED.append("PlaySound")
        def Beep(*a, **k): standin_log.REACHED.append("Beep")
        def MessageBeep(*a, **k): standin_log.REACHED.append("MessageBeep")
    """,
    "pyperclip.py": """
        import standin_log
        def copy(text): standin_log.REACHED.append("pyperclip.copy")
        def paste(): standin_log.REACHED.append("pyperclip.paste"); return ""
    """,
    "pyautogui.py": """
        import standin_log
        def hotkey(*a, **k): standin_log.REACHED.append("pyautogui.hotkey")
        def typewrite(*a, **k): standin_log.REACHED.append("pyautogui.typewrite")
        def moveTo(*a, **k): standin_log.REACHED.append("pyautogui.moveTo")
        def screenshot(*a, **k): standin_log.REACHED.append("pyautogui.screenshot")
    """,
    "pynput/__init__.py": "",
    "pynput/keyboard/__init__.py": """
        import standin_log
        class Controller:
            def __init__(self, *a, **k): standin_log.REACHED.append("keyboard.Controller")
        class Listener:
            def __init__(self, *a, **k): standin_log.REACHED.append("keyboard.Listener (global hook)")
    """,
    "pynput/mouse/__init__.py": """
        import standin_log
        class Controller:
            def __init__(self, *a, **k): standin_log.REACHED.append("mouse.Controller")
        class Listener:
            def __init__(self, *a, **k): standin_log.REACHED.append("mouse.Listener (global hook)")
    """,
    "PIL/__init__.py": "",
    "PIL/ImageGrab.py": """
        import standin_log
        def grab(*a, **k): standin_log.REACHED.append("ImageGrab.grab")
        def grabclipboard(*a, **k): standin_log.REACHED.append("ImageGrab.grabclipboard")
    """,
    # Windows: a planted window must never be a REAL one, because whoever is at
    # the console would see it if the window rule failed.
    "tkinter/__init__.py": """
        import standin_log
        class Misc:
            def clipboard_append(self, *a, **k): standin_log.REACHED.append("Tk clipboard_append")
            def clipboard_get(self, *a, **k): standin_log.REACHED.append("Tk clipboard_get")
            def clipboard_clear(self, *a, **k): standin_log.REACHED.append("Tk clipboard_clear")
            def selection_get(self, *a, **k): standin_log.REACHED.append("Tk selection_get")
        class Tk(Misc):
            def __init__(self, *a, **k): standin_log.REACHED.append("WINDOW tkinter.Tk")
    """,
    "webview/__init__.py": """
        import standin_log
        def create_window(*a, **k): standin_log.REACHED.append("WINDOW webview.create_window")
        def start(*a, **k): standin_log.REACHED.append("WINDOW webview.start")
    """,
}

# label -> code run in the child after the guard is installed.
_PLANTED = {
    "microphone (sounddevice.RawInputStream)": "import sounddevice; sounddevice.RawInputStream(samplerate=16000)",
    "microphone (sounddevice.rec)": "import sounddevice; sounddevice.rec(16000)",
    "speaker (sounddevice.play)": "import sounddevice; sounddevice.play(b'')",
    "loopback (pyaudiowpatch.PyAudio.open)": "import pyaudiowpatch; pyaudiowpatch.PyAudio().open(rate=48000)",
    "speaker (winsound.PlaySound)": "import winsound; winsound.PlaySound('x', winsound.SND_ASYNC)",
    "speaker (winsound.Beep)": "import winsound; winsound.Beep(660, 110)",
    "clipboard write (pyperclip.copy)": "import pyperclip; pyperclip.copy('planted')",
    "clipboard read (pyperclip.paste)": "import pyperclip; pyperclip.paste()",
    "key synthesis (pyautogui.hotkey)": "import pyautogui; pyautogui.hotkey('ctrl', 'v')",
    "mouse synthesis (pyautogui.moveTo)": "import pyautogui; pyautogui.moveTo(0, 0)",
    "key synthesis (pynput Controller)": "from pynput import keyboard; keyboard.Controller()",
    "global keyboard hook (pynput Listener)": "from pynput import keyboard; keyboard.Listener()",
    "global mouse hook (pynput Listener)": "from pynput import mouse; mouse.Listener()",
    "screen capture (ImageGrab.grab)": "from PIL import ImageGrab; ImageGrab.grab()",
    "clipboard write (Tk clipboard_append)": "import tkinter; tkinter.Misc().clipboard_append('planted')",
    "clipboard read (Tk clipboard_get)": "import tkinter; tkinter.Misc().clipboard_get()",
}

# Refused on the person's input desktop; allowed (and so REACHED, harmlessly,
# in the stand-in) on a hidden desktop or a private station.
_PLANTED_WINDOWS = {
    "window (tkinter.Tk)": "import tkinter; tkinter.Tk()",
    "window (webview.create_window)": "import webview; webview.create_window('planted', 'about:blank')",
    "window (webview.start)": "import webview; webview.start()",
}

_CHILD = """
import json, sys
sys.path.insert(1, {standins!r})
import tests
from tests import device_guard as guard
import standin_log
results = {{}}
for label, code in {planted!r}.items():
    before = len(standin_log.REACHED)
    try:
        exec(code, {{}})
        results[label] = "reached" if len(standin_log.REACHED) > before else "returned"
    except guard.DeviceAccessBlocked:
        results[label] = "blocked"
    except Exception as error:
        results[label] = "other: %s: %s" % (type(error).__name__, error)
print("RESULT " + json.dumps({{"results": results, "reached": standin_log.REACHED, "on": guard.installed()}}))
"""


def _write_standins(folder: Path) -> None:
    for relative, body in _STANDINS.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")


def _child_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if key not in (guard.ESCAPE_ENV, guard.WINDOWS_ENV)}
    # The tests package's own root first; then whatever located the product for
    # this run (the sabotage twins run a copied tests package against it).
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(ROOT), os.environ.get("PYTHONPATH", ""))))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class TheGuardIsOn(unittest.TestCase):
    def test_installed_with_no_escape_set(self):
        self.assertTrue(guard.installed())
        self.assertNotEqual(os.environ.get(guard.ESCAPE_ENV), "1")
        self.assertNotEqual(os.environ.get(guard.WINDOWS_ENV), "1")

    def test_a_refusal_is_recorded_even_when_it_is_caught(self):
        before = len(guard.REPORT)
        with self.assertRaises(guard.DeviceAccessBlocked):
            guard._audit("os.startfile", ("C:/planted.txt", "open"))
        self.assertEqual(len(guard.REPORT), before + 1)

    def test_a_refusal_names_the_test_that_made_it(self):
        with self.assertRaises(guard.DeviceAccessBlocked):
            guard._audit("os.startfile", ("C:/planted.txt", "open"))
        self.assertEqual(guard.BY_TEST[-1], (self.id(), "os.startfile"))


class PlantedDeviceCallsFailClosed(unittest.TestCase):
    """Real library names, stand-in libraries, the real import hook."""

    def _run_planted(self) -> dict:
        with tempfile.TemporaryDirectory() as folder:
            _write_standins(Path(folder))
            code = _CHILD.format(standins=folder, planted={**_PLANTED, **_PLANTED_WINDOWS})
            done = subprocess.run([sys.executable, "-B", "-c", code], cwd=str(Path(guard.__file__).parents[1]),
                                  env=_child_env(), capture_output=True, text=True, timeout=120)
        lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
        self.assertTrue(lines, f"no result from the child:\n{done.stdout}\n{done.stderr}")
        report = json.loads(lines[-1][len("RESULT "):])
        self.assertTrue(report["on"], "the guard was not on in the child")
        self.assertEqual(set(report["results"]), set(_PLANTED) | set(_PLANTED_WINDOWS))
        return report

    def test_every_planted_device_call_is_blocked_before_the_device(self):
        report = self._run_planted()
        devices = [entry for entry in report["reached"] if not entry.startswith("WINDOW ")]
        self.assertEqual(devices, [], "a stand-in device was reached")
        not_blocked = {label: outcome for label, outcome in report["results"].items()
                       if label in _PLANTED and outcome != "blocked"}
        self.assertEqual(not_blocked, {})

    def test_a_planted_window_follows_the_desktop(self):
        # The child runs on this process's desktop; on the person's input
        # desktop every planted window is refused, on a hidden one it is allowed
        # and only the stand-in records it.
        report = self._run_planted()
        expected = "blocked" if guard.console_desktop() else "reached"
        outcomes = {label: report["results"][label] for label in _PLANTED_WINDOWS}
        self.assertEqual(outcomes, {label: expected for label in _PLANTED_WINDOWS})
        windows = [entry for entry in report["reached"] if entry.startswith("WINDOW ")]
        self.assertEqual(bool(windows), expected == "reached")


class TheAppsOwnDeviceEntryPointsAreReplaced(unittest.TestCase):
    """Never called: a broken guard would mute the speakers of whoever is working."""

    def test_system_mute_and_volume_writes(self):
        from knight_flow import windows_audio

        for name in ("set_default_output_muted", "_set_muted", "_set_scalar_volume", "_default_endpoint_volume"):
            self.assertTrue(getattr(getattr(windows_audio, name), "__talkdat_blocked__", None), name)

    def test_the_mac_loopback_helper_may_not_start(self):
        from knight_flow import mac_system_audio

        helper = mac_system_audio.MacLoopbackStream(lambda *_: None).helper
        self.assertEqual(guard._program_of([str(helper)], None), "talkdatsystemaudio")
        with self.assertRaises(guard.DeviceAccessBlocked):
            guard._audit("subprocess.Popen", (None, [str(helper)], None, None))

    def test_tk_clipboard_and_console_windows(self):
        import tkinter

        for name in ("clipboard_append", "clipboard_clear", "clipboard_get", "selection_get"):
            self.assertTrue(getattr(getattr(tkinter.Misc, name), "__talkdat_blocked__", None), name)
        # tests/gui_offscreen.py wraps Tk.__init__ again (every window born
        # hidden) and calls the guarded one inside: the guard must still be in
        # the call path, whoever wrapped it last.
        def reachable(fn, depth=0):
            yield fn
            for cell in (getattr(fn, "__closure__", None) or ()) if depth < 4 else ():
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if callable(value):
                    yield from reachable(value, depth + 1)

        self.assertTrue(any(getattr(fn, "__talkdat_blocked__", None) for fn in reachable(tkinter.Tk.__init__)),
                        "Tk.__init__ no longer reaches the guard")

    def test_openers(self):
        for name in ("open", "open_new", "open_new_tab"):
            self.assertTrue(getattr(getattr(webbrowser, name), "__talkdat_blocked__", None), name)
        if hasattr(os, "startfile"):
            self.assertTrue(getattr(os.startfile, "__talkdat_blocked__", None))


@unittest.skipUnless(WINDOWS, "the foreign-function layer is Windows")
class RealHarmlessCallsAreRefused(unittest.TestCase):
    def test_send_input_with_zero_events(self):
        import ctypes

        with self.assertRaises(guard.DeviceAccessBlocked):
            ctypes.windll.user32.SendInput(0, None, 0)

    def test_a_fresh_loader_is_guarded_too(self):
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        for name in ("SendInput", "keybd_event", "mouse_event", "OpenClipboard", "SetClipboardData",
                     "GetClipboardData", "EmptyClipboard", "SetWindowsHookExW", "SetCursorPos", "MessageBeep"):
            self.assertIsInstance(getattr(user32, name), guard._GuardedForeignFunction, name)
        winmm = ctypes.WinDLL("winmm")
        for name in ("waveInOpen", "waveOutOpen", "PlaySoundW", "mciSendStringW"):
            self.assertIsInstance(getattr(winmm, name), guard._GuardedForeignFunction, name)
        self.assertIsInstance(ctypes.WinDLL("kernel32").TerminateProcess, guard._GuardedForeignFunction)

    def test_a_refused_call_still_rejects_a_wrong_argument_like_ctypes(self):
        # A fresh loader, so the argtypes set here touch no shared function.
        import ctypes
        from ctypes import wintypes

        send_input = ctypes.WinDLL("user32", use_last_error=True).SendInput
        send_input.argtypes = (wintypes.UINT, ctypes.c_void_p, ctypes.c_int)
        with self.assertRaises(ctypes.ArgumentError):
            send_input("not a count", None, 0)
        with self.assertRaises(guard.DeviceAccessBlocked):
            send_input(0, None, 0)

    def test_a_prototype_built_around_the_guard_is_refused_at_lookup(self):
        import ctypes

        prototype = ctypes.WINFUNCTYPE(ctypes.c_uint)
        with self.assertRaises(guard.DeviceAccessBlocked):
            prototype(("SendInput", ctypes.WinDLL("user32")))

    def test_ordinary_functions_are_untouched(self):
        import ctypes

        self.assertNotIsInstance(ctypes.windll.user32.GetSystemMetrics, guard._GuardedForeignFunction)
        self.assertGreater(ctypes.windll.user32.GetSystemMetrics(0), -1)

    def test_a_kill_tool(self):
        with self.assertRaises(guard.DeviceAccessBlocked):
            subprocess.run(["taskkill", "/?"], capture_output=True, timeout=30)

    def test_an_inline_stop_process(self):
        with self.assertRaises(guard.DeviceAccessBlocked):
            subprocess.run(["powershell", "-NoProfile", "-Command", "Stop-Process -Id 999999999 -WhatIf"],
                           capture_output=True, timeout=60)


class RealHarmlessCallsAreRefusedEverywhere(unittest.TestCase):
    def test_a_signal_to_a_process_this_run_did_not_start(self):
        with self.assertRaises(guard.DeviceAccessBlocked):
            os.kill(999999999, 0)

    def test_a_connection_beyond_this_machine(self):
        with self.assertRaises(guard.DeviceAccessBlocked):
            socket.create_connection(("192.0.2.1", 9), timeout=0.2)

    def test_a_name_lookup_beyond_this_machine(self):
        with self.assertRaises(guard.DeviceAccessBlocked):
            socket.getaddrinfo("example.invalid", 80)

    def test_a_raw_connect_that_needs_no_lookup(self):
        # An address literal reaches connect() without any getaddrinfo, so this
        # is the connect rule alone.
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(0.2)
        try:
            with self.assertRaises(guard.DeviceAccessBlocked):
                raw.connect(("192.0.2.1", 9))
        finally:
            raw.close()

    def test_loopback_still_works(self):
        self.assertTrue(socket.getaddrinfo("localhost", 0))
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            client = socket.create_connection(server.getsockname(), timeout=2)
            client.close()
        finally:
            server.close()

    def test_a_browser_open(self):
        class Recorder(webbrowser.BaseBrowser):
            opened: list[str] = []

            def open(self, url, new=0, autoraise=True):
                Recorder.opened.append(url)
                return True

        webbrowser.register("talkdat-proof", None, Recorder("talkdat-proof"), preferred=True)
        with self.assertRaises(guard.DeviceAccessBlocked):
            webbrowser.open("https://example.invalid/planted")
        self.assertEqual(Recorder.opened, [])

    def test_the_audit_layer_alone_refuses_openers(self):
        for event, args in (("webbrowser.open", ("https://example.invalid",)),
                            ("os.startfile", ("C:/planted.txt", "open"))):
            with self.assertRaises(guard.DeviceAccessBlocked):
                guard._audit(event, args)

    def test_a_child_this_run_started_may_be_signalled(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.assertIn(child.pid, guard._children)
            guard._audit("os.kill", (child.pid, 0))  # no refusal
        finally:
            child.kill()
            child.wait(timeout=30)


class WhereThisRunsDecidesWindowsAndTheClipboard(unittest.TestCase):
    def test_the_rules(self):
        if WINDOWS:
            self.assertTrue(guard.shared_station("WinSta0"))
            self.assertTrue(guard.shared_station(""))
            self.assertFalse(guard.shared_station("Service-0x0-3e7$"))
            self.assertTrue(guard.console_desktop("WinSta0", "Default"))
            self.assertTrue(guard.console_desktop("WinSta0", ""))
            self.assertFalse(guard.console_desktop("WinSta0", "talkdat-tests-1234"))
            self.assertFalse(guard.console_desktop("talkdat-station", "Default"))
        else:
            self.assertTrue(guard.shared_station())
            self.assertFalse(guard.console_desktop())

    def test_the_window_policy_follows_the_desktop(self):
        self.assertEqual(guard._on_console(), guard.console_desktop())

    def test_program_names(self):
        self.assertEqual(guard._program_of('"C:\\Windows\\System32\\taskkill.exe" /F /IM x.exe', None), "taskkill")
        self.assertEqual(guard._program_of("taskkill /?", None), "taskkill")
        self.assertEqual(guard._program_of(["/usr/bin/pkill", "x"], None), "pkill")
        self.assertEqual(guard._program_of("ignored", "C:/Windows/explorer.exe"), "explorer")
        self.assertTrue(guard._is_start_command(["cmd", "/c", "start", "notepad"]))
        self.assertFalse(guard._is_start_command(["cmd", "/c", "exit 0"]))
        self.assertTrue(guard._powershell_stops_something("powershell -Command Stop-Process -Name Ableton"))
        self.assertFalse(guard._powershell_stops_something(
            "powershell -Command function Stop-Process { param($Id) } ; Stop-Process -Id 1"))


class TheEscapeTurnsItOff(unittest.TestCase):
    def test_a_person_can_choose_real_devices(self):
        code = ("import os; os.environ['TALK_DAT_REAL_DEVICES'] = '1'; "
                "import tests; from tests import device_guard as g; print('ON' if g.installed() else 'OFF')")
        done = subprocess.run([sys.executable, "-B", "-c", code], cwd=str(Path(guard.__file__).parents[1]),
                              env=_child_env(), capture_output=True, text=True, timeout=120)
        self.assertEqual(done.stdout.strip().splitlines()[-1:], ["OFF"], done.stderr)


if __name__ == "__main__":
    unittest.main()
