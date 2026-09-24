from __future__ import annotations

from . import mac_support

import ctypes
import logging
import sys
import threading
import time
import uuid
from ctypes import wintypes


log = logging.getLogger(__name__)

_WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_HRESULT = ctypes.c_long
_CLSCTX_ALL = 0x17
_COINIT_APARTMENTTHREADED = 0x2
_RPC_E_CHANGED_MODE = 0x80010106
_E_RENDER = 0
_E_CONSOLE = 0


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(value: str) -> GUID:
    item = uuid.UUID(value)
    return GUID(
        item.time_low,
        item.time_mid,
        item.time_hi_version,
        (ctypes.c_ubyte * 8)(*item.bytes[8:]),
    )


_CLSID_MM_DEVICE_ENUMERATOR = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
_IID_IMM_DEVICE_ENUMERATOR = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
_IID_IAUDIO_ENDPOINT_VOLUME = _guid("5CDF2C82-841E-4546-9722-0CF74078229A")


def _failed(hr: int) -> bool:
    return ctypes.c_int32(int(hr)).value < 0


def _hr_text(hr: int) -> str:
    return f"0x{ctypes.c_uint32(int(hr)).value:08X}"


def _check(hr: int, label: str) -> None:
    if _failed(hr):
        raise OSError(f"{label} failed with HRESULT {_hr_text(hr)}")


def _method(ptr: ctypes.c_void_p, index: int, restype: object, *argtypes: object) -> object:
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = _WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(vtable[index])


def _release(ptr: ctypes.c_void_p | None) -> None:
    if not ptr or not ptr.value:
        return
    try:
        release = _method(ptr, 2, ctypes.c_ulong)
        release(ptr)
    except Exception:
        pass


def _require_windows() -> None:
    """Fail loudly rather than with AttributeError from ctypes.windll.

    Nothing should reach the COM helpers off Windows -- the fade is only
    scheduled from the win32 branch -- but "should" is doing a lot of work in a
    module whose failures land on a daemon thread inside a broad except.
    """
    if sys.platform != "win32":
        raise RuntimeError("the WASAPI endpoint volume API is Windows-only")


def _co_initialize() -> bool:
    _require_windows()
    ole32 = ctypes.windll.ole32
    hr = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    code = ctypes.c_uint32(int(hr)).value
    if code == _RPC_E_CHANGED_MODE:
        return False
    _check(hr, "CoInitializeEx")
    return True


def _default_endpoint_volume() -> tuple[ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]:
    _require_windows()
    ole32 = ctypes.windll.ole32
    enumerator = ctypes.c_void_p()
    device = ctypes.c_void_p()
    volume = ctypes.c_void_p()

    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = _HRESULT
    hr = ole32.CoCreateInstance(
        ctypes.byref(_CLSID_MM_DEVICE_ENUMERATOR),
        None,
        _CLSCTX_ALL,
        ctypes.byref(_IID_IMM_DEVICE_ENUMERATOR),
        ctypes.byref(enumerator),
    )
    _check(hr, "CoCreateInstance(IMMDeviceEnumerator)")

    get_default_audio_endpoint = _method(
        enumerator,
        4,
        _HRESULT,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    )
    hr = get_default_audio_endpoint(enumerator, _E_RENDER, _E_CONSOLE, ctypes.byref(device))
    _check(hr, "GetDefaultAudioEndpoint")

    activate = _method(
        device,
        3,
        _HRESULT,
        ctypes.POINTER(GUID),
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    hr = activate(device, ctypes.byref(_IID_IAUDIO_ENDPOINT_VOLUME), _CLSCTX_ALL, None, ctypes.byref(volume))
    _check(hr, "Activate(IAudioEndpointVolume)")
    return enumerator, device, volume


def get_default_output_muted() -> bool:
    if sys.platform != "win32":
        return False
    initialized = _co_initialize()
    enumerator: ctypes.c_void_p | None = None
    device: ctypes.c_void_p | None = None
    volume: ctypes.c_void_p | None = None
    try:
        enumerator, device, volume = _default_endpoint_volume()
        muted = wintypes.BOOL()
        get_mute = _method(volume, 15, _HRESULT, ctypes.POINTER(wintypes.BOOL))
        hr = get_mute(volume, ctypes.byref(muted))
        _check(hr, "GetMute")
        return bool(muted.value)
    finally:
        _release(volume)
        _release(device)
        _release(enumerator)
        if initialized:
            ctypes.windll.ole32.CoUninitialize()


def set_default_output_muted(muted: bool) -> None:
    if sys.platform != "win32":
        return
    initialized = _co_initialize()
    enumerator: ctypes.c_void_p | None = None
    device: ctypes.c_void_p | None = None
    volume: ctypes.c_void_p | None = None
    try:
        enumerator, device, volume = _default_endpoint_volume()
        set_mute = _method(volume, 14, _HRESULT, wintypes.BOOL, ctypes.c_void_p)
        hr = set_mute(volume, wintypes.BOOL(1 if muted else 0), None)
        _check(hr, "SetMute")
    finally:
        _release(volume)
        _release(device)
        _release(enumerator)
        if initialized:
            ctypes.windll.ole32.CoUninitialize()


def _get_scalar_volume(volume: ctypes.c_void_p) -> float:
    level = ctypes.c_float()
    get_scalar = _method(volume, 9, _HRESULT, ctypes.POINTER(ctypes.c_float))
    _check(get_scalar(volume, ctypes.byref(level)), "GetMasterVolumeLevelScalar")
    return float(level.value)


def _set_scalar_volume(volume: ctypes.c_void_p, level: float) -> None:
    level = max(0.0, min(1.0, float(level)))
    set_scalar = _method(volume, 7, _HRESULT, ctypes.c_float, ctypes.c_void_p)
    _check(set_scalar(volume, ctypes.c_float(level), None), "SetMasterVolumeLevelScalar")


def _get_muted(volume: ctypes.c_void_p) -> bool:
    muted = wintypes.BOOL()
    get_mute = _method(volume, 15, _HRESULT, ctypes.POINTER(wintypes.BOOL))
    _check(get_mute(volume, ctypes.byref(muted)), "GetMute")
    return bool(muted.value)


def _set_muted(volume: ctypes.c_void_p, muted: bool) -> None:
    set_mute = _method(volume, 14, _HRESULT, wintypes.BOOL, ctypes.c_void_p)
    _check(set_mute(volume, wintypes.BOOL(1 if muted else 0), None), "SetMute")


class OutputMuteGuard:
    """Fades the default output volume down while recording and back up on release.

    All audio work runs on a background thread so triggering dictation never
    blocks the UI (the old synchronous COM mute added activation lag). Fades are
    superseded cleanly when start/stop interleave, and the user's original volume
    and mute state are always restored.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active = False
        self._generation = 0
        self._original_volume: float | None = None
        self._original_mute: bool | None = None

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation


    def _start_mac(self, target: float) -> None:
        """Duck the system output while recording, on a worker thread.

        No fade. The Windows path ramps the volume through WASAPI; the macOS
        equivalent is one osascript call per step, and a 180ms fade would be a
        dozen subprocess spawns on the path that has to feel instant. A single
        step is what the mute this replaces did anyway.

        Devices that expose no software volume -- audio interfaces, most USB
        DACs -- report nothing, and the guard then does nothing rather than
        pretending. That is why the original volume is only remembered when it
        was actually readable: restoring a value that was never read would set a
        volume the person never chose.
        """
        with self._lock:
            if self._active:
                return
            self._active = True
            self._generation += 1
            generation = self._generation

        def worker() -> None:
            current = mac_support.system_output_volume()
            if current is None:
                return
            with self._lock:
                if generation != self._generation:
                    return
                self._original_volume = current
            mac_support.set_system_output_volume(target)

        threading.Thread(target=worker, name="TalkDatAudioDuck", daemon=True).start()

    def _stop_mac(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            self._generation += 1
            generation = self._generation
            original = self._original_volume
            self._original_volume = None
        if original is None:
            return

        def worker() -> None:
            with self._lock:
                if generation != self._generation:
                    return
            mac_support.set_system_output_volume(original)

        threading.Thread(target=worker, name="TalkDatAudioRestore", daemon=True).start()

    def start(self, *, enabled: bool = True, fade_ms: int = 180, target: float = 0.0) -> None:
        if not enabled:
            return
        if sys.platform == "darwin":
            self._start_mac(max(0.0, float(target)))
            return
        if sys.platform != "win32":
            return
        with self._lock:
            if self._active:
                return
            self._active = True
            self._generation += 1
            generation = self._generation
        threading.Thread(
            target=self._fade, args=(generation, "down", max(1, int(fade_ms)), max(0.0, float(target))),
            name="TalkDatAudioDuck", daemon=True,
        ).start()

    def stop(self, *, fade_ms: int = 240) -> None:
        if sys.platform == "darwin":
            self._stop_mac()
            return
        with self._lock:
            if not self._active:
                return
            self._active = False
            self._generation += 1
            generation = self._generation
        threading.Thread(
            target=self._fade, args=(generation, "up", max(1, int(fade_ms)), 0.0),
            name="TalkDatAudioRestore", daemon=True,
        ).start()

    def _fade(self, generation: int, direction: str, fade_ms: int, target: float) -> None:
        initialized = _co_initialize()
        enumerator = device = volume = None
        try:
            enumerator, device, volume = _default_endpoint_volume()
            if direction == "down":
                with self._lock:
                    if self._original_volume is None:
                        self._original_volume = _get_scalar_volume(volume)
                        self._original_mute = _get_muted(volume)
                    start_level = _get_scalar_volume(volume)
                    end_level = target
                if _get_muted(volume):
                    _set_muted(volume, False)  # unmute so the fade is audible, restore later
            else:
                with self._lock:
                    original = self._original_volume
                    original_mute = self._original_mute
                if original is None:
                    return
                start_level = _get_scalar_volume(volume)
                end_level = original

            steps = max(1, fade_ms // 16)
            for index in range(1, steps + 1):
                if not self._is_current(generation):
                    return
                level = start_level + (end_level - start_level) * (index / steps)
                _set_scalar_volume(volume, level)
                time.sleep(fade_ms / 1000.0 / steps)

            if direction == "up" and self._is_current(generation):
                with self._lock:
                    original_mute = self._original_mute
                    self._original_volume = None
                    self._original_mute = None
                if original_mute:
                    _set_muted(volume, True)
        except Exception as exc:
            log.warning("audio duck (%s) failed: %s", direction, exc)
        finally:
            _release(volume)
            _release(device)
            _release(enumerator)
            if initialized:
                ctypes.windll.ole32.CoUninitialize()
