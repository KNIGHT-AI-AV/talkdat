"""No test starts PortAudio or reaches the person's audio devices (coordinator
RULING 2026-10-22T02:22:41Z). The Settings microphone list shows the stand-in
devices of tests/audio_stand_in.py; a real audio library is refused before any
of it runs; winmm and XInput find no device; and no PortAudio module is loaded
in this process. Nothing here loads a real audio library: the control that
needs the real import path meets a sentinel instead.
"""
from __future__ import annotations

import importlib.abc
import io
import os
import sys
import time
import unittest
from unittest import mock

from knight_flow.audio_input import list_input_devices
from knight_flow.web_shell.shell_devices import InputDevices
from tests import audio_stand_in, device_guard

# What the Settings list must show: the stand-in's inputs, as "index: name".
STAND_IN_MICROPHONES = ["0: Test microphone (stand-in)", "1: Test headset (stand-in)"]


class _Sentinel(importlib.abc.MetaPathFinder):
    """Stands where the real sounddevice would be found: records the import and
    refuses it, so the real module, and PortAudio with it, never runs."""

    def __init__(self) -> None:
        self.reached: list[str] = []

    def find_spec(self, fullname, path, target=None):
        if fullname != "sounddevice":
            return None
        self.reached.append(fullname)
        raise ImportError("sentinel: the real sounddevice would be imported here", name=fullname)


def _settled(devices: InputDevices, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while devices.snapshot()["status"] == "loading" and time.monotonic() < deadline:
        time.sleep(0.01)
    return devices.snapshot()


class TheSettingsMicrophoneListShowsTheStandIn(unittest.TestCase):
    def test_the_settings_list_shows_the_stand_in_microphones(self) -> None:
        devices = InputDevices()
        devices.refresh()
        snapshot = _settled(devices)
        self.assertEqual(snapshot["status"], "ready")
        self.assertEqual(snapshot["devices"], STAND_IN_MICROPHONES)
        self.assertEqual(list_input_devices(), STAND_IN_MICROPHONES)

    def test_without_the_stand_in_the_list_would_reach_the_real_library(self) -> None:
        # The control: the stand-in, not luck, keeps PortAudio out. Without it the
        # same call reaches the real import -- answered here by a sentinel.
        sentinel = _Sentinel()
        with mock.patch.dict(sys.modules):
            sys.modules.pop("sounddevice", None)
            sys.meta_path.insert(0, sentinel)
            try:
                names = list_input_devices()
            finally:
                sys.meta_path.remove(sentinel)
            self.assertNotIn("sounddevice", sys.modules)
        self.assertEqual(sentinel.reached, ["sounddevice"])
        self.assertEqual(names, [])


class TheRealAudioLibrariesNeverLoad(unittest.TestCase):
    def test_sounddevice_is_the_stand_in_and_a_stream_still_refuses(self) -> None:
        import sounddevice

        self.assertIs(sounddevice, audio_stand_in.STAND_INS["sounddevice"])
        self.assertEqual(sounddevice.query_devices(kind="input")["name"], "Test microphone (stand-in)")
        with self.assertRaises(device_guard.DeviceAccessBlocked):
            sounddevice.RawInputStream(samplerate=16000)

    def test_pyaudiowpatch_is_the_stand_in_and_open_still_refuses(self) -> None:
        import pyaudiowpatch

        self.assertIs(pyaudiowpatch, audio_stand_in.STAND_INS["pyaudiowpatch"])
        manager = pyaudiowpatch.PyAudio()
        self.assertTrue(manager.get_default_wasapi_loopback()["isLoopbackDevice"])
        with self.assertRaises(device_guard.DeviceAccessBlocked):
            manager.open(format=pyaudiowpatch.paInt16, channels=2, rate=48000, input=True)

    def test_the_real_library_is_refused_if_a_stand_in_is_removed(self) -> None:
        with mock.patch.dict(sys.modules):
            sys.modules.pop("sounddevice", None)
            with self.assertRaises(audio_stand_in.RealAudioLibraryRefused):
                import sounddevice  # noqa: F401
            self.assertNotIn("sounddevice", sys.modules)
        self.assertIn("importing the real sounddevice (PortAudio starts on import)", device_guard.REPORT)

    @unittest.skipUnless(os.name == "nt", "winmm is Windows")
    def test_winmm_finds_no_device_and_never_opens_a_midi_input(self) -> None:
        import ctypes

        winmm = ctypes.WinDLL("winmm")
        for name in ("midiInGetNumDevs", "midiOutGetNumDevs", "waveInGetNumDevs", "waveOutGetNumDevs"):
            self.assertEqual(getattr(winmm, name)(), 0, name)
        with self.assertRaises(device_guard.DeviceAccessBlocked):
            winmm.midiInOpen(ctypes.byref(ctypes.c_void_p()), 0, None, None, 0)

    def test_a_game_controller_is_never_polled(self) -> None:
        # Not loaded here: the stand-in answers without the real function.
        polled = []
        stand_in = device_guard._foreign_replacement(lambda *args: polled.append(args) or 0, "xinput1_4",
                                                     "XInputGetState")
        self.assertEqual(stand_in(0, None), 1167)  # ERROR_DEVICE_NOT_CONNECTED
        self.assertEqual(polled, [])

    @unittest.skipUnless(os.name == "nt", "the module list is read on Windows")
    def test_no_portaudio_module_is_loaded_in_this_process(self) -> None:
        found, total = audio_stand_in.portaudio_check()
        self.assertGreater(total, 10, "the module list was not read")
        self.assertEqual(found, [])

    def test_the_check_names_every_portaudio_module(self) -> None:
        paths = [r"C:\Python\python313.dll", r"C:\x\_sounddevice_data\portaudio-binaries\libportaudio64bit.dll",
                 r"C:\x\_portaudiowpatch.cp313-win_amd64.pyd", r"C:\Windows\System32\winmm.dll"]
        self.assertEqual(audio_stand_in.portaudio_modules(paths), paths[1:3])

    def test_a_loaded_portaudio_fails_the_run(self) -> None:
        result = unittest.TestResult()
        loaded = ([r"C:\x\libportaudio64bit.dll"], 300)
        with (
            mock.patch.object(audio_stand_in, "portaudio_check", return_value=loaded),
            mock.patch("sys.stderr", new_callable=io.StringIO) as log,
        ):
            result.stopTestRun()
        self.assertFalse(result.wasSuccessful())
        self.assertIn("libportaudio64bit.dll", result.errors[0][1])
        self.assertIn("portaudio check: FAILED", log.getvalue())


if __name__ == "__main__":
    unittest.main()
