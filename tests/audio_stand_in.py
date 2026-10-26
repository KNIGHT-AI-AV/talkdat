"""The audio libraries the product can load, replaced before any product import
(coordinator RULING 2026-10-22T02:22:41Z, under the protection order of
2026-10-20: a test's fake-device isolation covers device ENUMERATION as well as
streams).

`import sounddevice` starts PortAudio, and so does building a
pyaudiowpatch.PyAudio. Either one lists every audio device on the computer that
runs the suite, while the person's audio work runs on it; device_guard.py stopped
only the streams. While PortAudio started, sounddevice also pointed this
process's stderr at devnull, which swallowed three tests' lines in full suite r2.

refuse_real_audio() is the floor: a finder in front of every other one, so a real
    audio library never executes, and a check at the end of every unittest run that
    no PortAudio module is loaded in the process. One that is fails the run.
install() puts the stand-ins in place: `sounddevice` and `pyaudiowpatch` over one
    fixed device list, so the product's device lists, defaults and rate checks
    still work. The guard's stream rules apply to them as they did to the real
    modules: building a stream still refuses.
winmm's device counts and XInput are answered by the guard (FOREIGN_STAND_INS).
A child process that runs no unittest reports the same check with check_line()
or report_at_exit(), and its parent test asserts it (tests/child_isolation.py).
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
import sys
import time
import types
import unittest.result
import unittest.suite
from typing import Any, Iterable

from tests import device_guard

#: Every module whose import or construction starts PortAudio.
REAL_AUDIO_MODULES = frozenset({
    "sounddevice", "_sounddevice", "_sounddevice_data", "pyaudiowpatch", "_portaudiowpatch", "pyaudio",
    "_portaudio",
})

# One host API and three devices: a microphone, a headset (in and out), speakers.
_LATENCY = {"default_low_input_latency": 0.01, "default_low_output_latency": 0.01,
            "default_high_input_latency": 0.08, "default_high_output_latency": 0.08}
DEVICES = (
    {"name": "Test microphone (stand-in)", "index": 0, "hostapi": 0, "max_input_channels": 1,
     "max_output_channels": 0, "default_samplerate": 48000.0, **_LATENCY},
    {"name": "Test headset (stand-in)", "index": 1, "hostapi": 0, "max_input_channels": 1,
     "max_output_channels": 2, "default_samplerate": 44100.0, **_LATENCY},
    {"name": "Test speakers (stand-in)", "index": 2, "hostapi": 0, "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 48000.0, **_LATENCY},
)
DEFAULT_INPUT, DEFAULT_OUTPUT = 0, 2
#: pyaudiowpatch also lists a loopback twin of the default output.
LOOPBACK = {**DEVICES[DEFAULT_OUTPUT], "index": len(DEVICES), "max_input_channels": 2, "max_output_channels": 0,
            "name": f"{DEVICES[DEFAULT_OUTPUT]['name']} [Loopback]"}
_NO_PORTAUDIO = "none: tests/audio_stand_in.py"


# --- sounddevice ---------------------------------------------------------------

class PortAudioError(Exception):
    """As sounddevice raises it."""


class CallbackStop(Exception):
    """As sounddevice defines it."""


class CallbackAbort(Exception):
    """As sounddevice defines it."""


class CallbackFlags:
    """As sounddevice defines it: no flag is ever set, because no stream runs."""

    def __init__(self, flags: int = 0) -> None:
        self._flags = int(flags)

    def __bool__(self) -> bool:
        return bool(self._flags)


class DeviceList(tuple):
    """What sounddevice.query_devices() returns: every device, in order."""


class _InputOutputPair(list):
    @property
    def input(self) -> Any:
        return self[0]

    @property
    def output(self) -> Any:
        return self[1]


class _Default:
    """sounddevice.default: the settings a stream would use."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.device = _InputOutputPair([DEFAULT_INPUT, DEFAULT_OUTPUT])
        self.channels = _InputOutputPair([None, None])
        self.dtype = _InputOutputPair(["float32", "float32"])
        self.latency = _InputOutputPair(["high", "high"])
        self.extra_settings = _InputOutputPair([None, None])
        self.samplerate = None
        self.blocksize = 0
        self.clip_off = self.dither_off = self.never_drop_input = False
        self.prime_output_buffers_using_stream_callback = False
        self.hostapi = 0


def _find_device(device: Any) -> dict:
    if isinstance(device, int) and not isinstance(device, bool):
        if 0 <= device < len(DEVICES):
            return dict(DEVICES[device])
        raise PortAudioError(f"Error querying device {device}")
    if isinstance(device, str):
        matches = [entry for entry in DEVICES if device.lower() in entry["name"].lower()]
        if len(matches) == 1:
            return dict(matches[0])
        raise ValueError(f"{'Multiple devices' if matches else 'No device'} matching {device!r}")
    raise ValueError(f"Invalid device: {device!r}")


def _sounddevice() -> types.ModuleType:
    module = types.ModuleType("sounddevice", "Stand-in for sounddevice (tests/audio_stand_in.py): no PortAudio.")
    module.__spec__ = importlib.machinery.ModuleSpec("sounddevice", None, origin=__file__)
    module.__stand_in__ = True
    module.__version__ = "0.0 (stand-in)"
    default = _Default()

    def query_devices(device: Any = None, kind: str | None = None) -> Any:
        if kind not in ("input", "output", None):
            raise ValueError(f"Invalid kind: {kind!r}")
        if device is None and kind is None:
            return DeviceList(dict(entry) for entry in DEVICES)
        if device is None:
            device = default.device[0 if kind == "input" else 1]
        info = _find_device(device)
        if kind and info[f"max_{kind}_channels"] < 1:
            raise ValueError(f"Not an {kind} device: {info['name']!r}")
        return info

    def checker(kind: str):
        def check(device: Any = None, channels: Any = None, dtype: Any = None, extra_settings: Any = None,
                  samplerate: Any = None) -> None:
            info = query_devices(device, kind)
            if channels is not None and int(channels) > info[f"max_{kind}_channels"]:
                raise PortAudioError(f"Error opening {kind} stream: Invalid number of channels [PaErrorCode -9998]")

        check.__name__ = f"check_{kind}_settings"
        return check

    def query_hostapis(index: int | None = None) -> Any:
        hostapi = {"name": "Stand-in host API", "devices": [entry["index"] for entry in DEVICES],
                   "default_input_device": DEFAULT_INPUT, "default_output_device": DEFAULT_OUTPUT}
        if index is None:
            return (hostapi,)
        if index != 0:
            raise PortAudioError(f"Error querying host API {index}")
        return hostapi

    def no_stream(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("play()/rec()/playrec() was not called yet")

    # Streams and the one-call helpers: the guard's MODULE_RULES replace these
    # names with its own refusal; each refuses by itself as well.
    def refusing(name: str):
        def refuse(*_args: Any, **_kwargs: Any) -> None:
            device_guard._refuse(f"sounddevice.{name} (stand-in)")

        refuse.__name__ = name
        return refuse

    module.__dict__.update(
        PortAudioError=PortAudioError, CallbackStop=CallbackStop, CallbackAbort=CallbackAbort,
        CallbackFlags=CallbackFlags, DeviceList=DeviceList, default=default, query_devices=query_devices,
        check_input_settings=checker("input"), check_output_settings=checker("output"),
        query_hostapis=query_hostapis, get_portaudio_version=lambda: (0, _NO_PORTAUDIO),
        wait=lambda ignore_errors=True: None, stop=lambda ignore_errors=True: None,
        sleep=lambda msec: time.sleep(max(0, msec) / 1000.0), get_stream=no_stream, get_status=no_stream,
    )
    for name in ("InputStream", "OutputStream", "Stream", "RawInputStream", "RawOutputStream", "RawStream",
                 "rec", "play", "playrec"):
        setattr(module, name, refusing(name))
    return module


# --- pyaudiowpatch -------------------------------------------------------------

paFloat32, paInt32, paInt24, paInt16, paInt8, paUInt8 = 1, 2, 4, 8, 16, 32
paContinue, paComplete, paAbort = 0, 1, 2
paWASAPI = 13
_SAMPLE_SIZES = {paFloat32: 4, paInt32: 4, paInt24: 3, paInt16: 2, paInt8: 1, paUInt8: 1}


def _pyaudio_info(entry: dict, *, loopback: bool = False) -> dict:
    return {
        "index": entry["index"], "structVersion": 2, "name": entry["name"], "hostApi": 0,
        "maxInputChannels": entry["max_input_channels"], "maxOutputChannels": entry["max_output_channels"],
        "defaultLowInputLatency": entry["default_low_input_latency"],
        "defaultLowOutputLatency": entry["default_low_output_latency"],
        "defaultHighInputLatency": entry["default_high_input_latency"],
        "defaultHighOutputLatency": entry["default_high_output_latency"],
        "defaultSampleRate": entry["default_samplerate"], "isLoopbackDevice": loopback,
    }


class PyAudio:
    """pyaudiowpatch.PyAudio over the fixed list. open() is the guard's to refuse."""

    def __init__(self) -> None:
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def get_device_count(self) -> int:
        return len(DEVICES) + 1

    def get_device_info_by_index(self, device_index: int) -> dict:
        if device_index == LOOPBACK["index"]:
            return _pyaudio_info(LOOPBACK, loopback=True)
        if 0 <= int(device_index) < len(DEVICES):
            return _pyaudio_info(DEVICES[int(device_index)])
        raise OSError(-9996, "Invalid device index")

    def get_default_input_device_info(self) -> dict:
        return self.get_device_info_by_index(DEFAULT_INPUT)

    def get_default_output_device_info(self) -> dict:
        return self.get_device_info_by_index(DEFAULT_OUTPUT)

    def get_host_api_count(self) -> int:
        return 1

    def get_host_api_info_by_index(self, host_api_index: int) -> dict:
        if host_api_index != 0:
            raise OSError(-9978, "Invalid host api info")
        return {"index": 0, "structVersion": 1, "type": paWASAPI, "name": "Windows WASAPI (stand-in)",
                "deviceCount": self.get_device_count(), "defaultInputDevice": DEFAULT_INPUT,
                "defaultOutputDevice": DEFAULT_OUTPUT}

    def get_host_api_info_by_type(self, host_api_type: int) -> dict:
        if host_api_type != paWASAPI:
            raise OSError(-9979, "Invalid host api type")
        return self.get_host_api_info_by_index(0)

    def get_default_host_api_info(self) -> dict:
        return self.get_host_api_info_by_index(0)

    def get_default_wasapi_loopback(self) -> dict:
        return _pyaudio_info(LOOPBACK, loopback=True)

    def get_loopback_device_info_generator(self):
        yield _pyaudio_info(LOOPBACK, loopback=True)

    def get_sample_size(self, format: int) -> int:
        return _SAMPLE_SIZES[format]

    def open(self, *_args: Any, **_kwargs: Any) -> Any:
        device_guard._refuse("pyaudiowpatch.PyAudio.open (stand-in)")


def _pyaudiowpatch() -> types.ModuleType:
    module = types.ModuleType("pyaudiowpatch", "Stand-in for pyaudiowpatch (tests/audio_stand_in.py): no PortAudio.")
    module.__spec__ = importlib.machinery.ModuleSpec("pyaudiowpatch", None, origin=__file__)
    module.__stand_in__ = True
    module.__version__ = "0.0 (stand-in)"
    module.__dict__.update(
        PyAudio=PyAudio, paFloat32=paFloat32, paInt32=paInt32, paInt24=paInt24, paInt16=paInt16, paInt8=paInt8,
        paUInt8=paUInt8, paContinue=paContinue, paComplete=paComplete, paAbort=paAbort, paWASAPI=paWASAPI,
        get_sample_size=lambda format: _SAMPLE_SIZES[format],
        get_portaudio_version=lambda: 0, get_portaudio_version_text=lambda: _NO_PORTAUDIO,
    )
    return module


# --- install -------------------------------------------------------------------

STAND_INS: dict[str, types.ModuleType] = {}


def install() -> dict[str, types.ModuleType]:
    """Put the stand-ins in sys.modules, with the guard's rules applied to them."""
    if not STAND_INS:
        STAND_INS.update(sounddevice=_sounddevice(), pyaudiowpatch=_pyaudiowpatch())
        for name, module in STAND_INS.items():
            device_guard.patch_module(module, name)
    for name, module in STAND_INS.items():
        sys.modules[name] = module
    return STAND_INS


class RealAudioLibraryRefused(ImportError):
    """An import of a real audio library. In this suite one never runs."""


class _RefuseRealAudio(importlib.abc.MetaPathFinder):
    """In front of every other finder. sys.modules answers a stood-in name first,
    so this only meets a test that removed a stand-in, or a run without them: the
    real library is refused before any of it executes. A library that is not
    installed stays not installed."""

    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        if fullname.partition(".")[0] not in REAL_AUDIO_MODULES:
            return None
        if importlib.machinery.PathFinder.find_spec(fullname, path) is None:
            return None
        try:
            device_guard._refuse(f"importing the real {fullname} (PortAudio starts on import)")
        except device_guard.DeviceAccessBlocked as error:
            raise RealAudioLibraryRefused(str(error), name=fullname) from None


def loaded_modules() -> list[str]:
    """The path of every module (DLL, .pyd, .exe) mapped into this process. Windows only."""
    import ctypes
    from ctypes import wintypes

    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.EnumProcessModules.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD))
    psapi.EnumProcessModules.restype = wintypes.BOOL
    kernel32.GetModuleFileNameW.argtypes = (wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
    kernel32.GetModuleFileNameW.restype = wintypes.DWORD
    process = kernel32.GetCurrentProcess()
    count = 512
    while True:
        handles = (wintypes.HMODULE * count)()
        needed = wintypes.DWORD(0)
        if not psapi.EnumProcessModules(process, handles, ctypes.sizeof(handles), ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        if needed.value <= ctypes.sizeof(handles):
            break
        count = needed.value // ctypes.sizeof(wintypes.HMODULE) + 64
    buffer = ctypes.create_unicode_buffer(32768)
    paths = []
    for handle in handles[: needed.value // ctypes.sizeof(wintypes.HMODULE)]:
        if handle and kernel32.GetModuleFileNameW(handle, buffer, len(buffer)):
            paths.append(buffer.value)
    return paths


def portaudio_modules(paths: Iterable[str]) -> list[str]:
    """The PortAudio modules among ``paths``: sounddevice's DLL, or the extension
    PyAudio and pyaudiowpatch link it into."""
    return [path for path in paths if "portaudio" in os.path.basename(str(path)).lower()]


def portaudio_check() -> tuple[list[str] | None, int]:
    """(the PortAudio modules loaded in this process, how many modules were read);
    (None, 0) where the module list is not read (not Windows)."""
    if os.name != "nt":
        return None, 0
    paths = loaded_modules()
    return portaudio_modules(paths), len(paths)


_FAILED = "portaudio check: FAILED: "


def check_line() -> str:
    """This process's PortAudio check, in the words every report uses: clean,
    not run (not Windows), or FAILED with the reason."""
    try:
        found, total = portaudio_check()
    except Exception as error:  # an unreadable list is a failed check, never a pass
        return f"{_FAILED}the module list could not be read: {type(error).__name__}: {error}"
    if found is None:
        return "portaudio check: not run (the module list is read on Windows only)"
    if found:
        return f"{_FAILED}PortAudio is loaded in this test process: {'; '.join(found)}"
    return f"portaudio check: clean ({total} modules loaded, none is PortAudio)"


def report_at_exit() -> None:
    """For a process that runs no unittest (a test's `python -c` child): print
    check_line() to stderr as it exits, for the parent test to assert."""
    import atexit

    atexit.register(lambda: print(check_line(), file=sys.stderr, flush=True))


def _check_at_the_end_of_each_run() -> None:
    real_stop = unittest.result.TestResult.stopTestRun
    if getattr(real_stop, "__talkdat_portaudio_check__", False):
        return

    def stop_test_run(self: Any) -> None:
        line = check_line()
        print(line, file=sys.stderr)
        if line.startswith(_FAILED):
            self.addError(unittest.suite._ErrorHolder("portaudio check (tests/audio_stand_in.py)"),
                          (RuntimeError, RuntimeError(line[len(_FAILED):]), None))
        real_stop(self)

    stop_test_run.__talkdat_portaudio_check__ = True
    unittest.result.TestResult.stopTestRun = stop_test_run


def refuse_real_audio() -> None:
    """The floor under the stand-ins: the finder, and the end-of-run check."""
    if not any(isinstance(finder, _RefuseRealAudio) for finder in sys.meta_path):
        sys.meta_path.insert(0, _RefuseRealAudio())
    _check_at_the_end_of_each_run()
