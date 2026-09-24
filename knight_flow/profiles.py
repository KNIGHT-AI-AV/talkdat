"""Per-app dictation profiles.

config["profiles"] is a list of dicts:
{"match": "slack", "cleanup_level": "light", "tone": "", "language": "",
 "auto_enter": false, "enabled": true}

`match` is a case-insensitive substring of the foreground process executable
name (for example "slack" matches slack.exe). The first enabled match wins.
"""

from __future__ import annotations

import copy
import ctypes
import sys
from typing import Any

from . import mac_support


def foreground_process_name() -> str:
    if mac_support.IS_MAC:
        # "slack.app" here where Windows reports "slack.exe", so a user's
        # existing substring matches ("slack", "chrome") keep working.
        return mac_support.frontmost_app_name()
    if sys.platform != "win32":
        return ""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        process_query_limited_information = 0x1000
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid.value)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(len(buffer))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value.replace("\\", "/").rsplit("/", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""
    return ""


def active_profile(config: dict[str, Any], process_name: str | None = None) -> dict[str, Any]:
    profiles = config.get("profiles", [])
    if not isinstance(profiles, list) or not profiles:
        return {}
    name = process_name if process_name is not None else foreground_process_name()
    if not isinstance(name, str):
        return {}
    name = name.lower()
    if not name:
        return {}
    for profile in profiles:
        if not isinstance(profile, dict) or profile.get("enabled", True) is not True:
            continue
        match = profile.get("match", "")
        if not isinstance(match, str):
            continue
        match = match.strip().lower()
        if match and match in name:
            return profile
    return {}


def apply_profile(config: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Return a config copy with the profile's overrides applied."""
    if not isinstance(profile, dict) or not profile:
        return config
    merged = copy.deepcopy(config)
    level = profile.get("cleanup_level", "")
    level = level.strip().lower() if isinstance(level, str) else ""
    if level in {"none", "light", "medium", "high"}:
        merged.setdefault("cleanup", {})["level"] = level
    tone = profile.get("tone", "")
    tone = tone.strip().lower() if isinstance(tone, str) else ""
    if tone:
        # The formatter applies profile tone in its existing bounded pass. A
        # separate rewrite here used to double latency after every dictation.
        merged.setdefault("cleanup", {})["tone"] = tone
    language = profile.get("language", "")
    language = language.strip() if isinstance(language, str) else ""
    if language:
        merged.setdefault("deepgram", {})["language"] = language
        from .stt_registry import selected_provider_id
        providers = merged.setdefault("stt", {}).setdefault("providers", {})
        providers.setdefault(selected_provider_id(merged), {})["language"] = language
    if type(profile.get("auto_enter")) is bool:
        merged.setdefault("dictation", {})["press_enter_command"] = bool(profile.get("auto_enter"))
    return merged
