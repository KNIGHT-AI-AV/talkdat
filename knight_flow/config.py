from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import mac_support
from .audio_input import low_confidence_input_name
from .credentials import config_for_persistence, hydrate_config_secrets
from .licensing import DEFAULT_COMMERCE_API_URL
from .version import APP_VERSION


log = logging.getLogger(__name__)

APP_NAME = "TalkDat"
LEGACY_APP_NAME = APP_NAME + "".join(chr(value) for value in (83, 104, 105))
LOCAL_FORMATTER_MODEL = "qwen3:1.7b"
LEGACY_LOCAL_FORMATTER_MODELS = {"", "llama3.1", "qwen3:0.6b"}


# X-165: three pill sizes a person can choose, instead of migrations quietly
# resizing the pill under them. That is what "it fluctuates in size" was: the
# 0.3 migration took it 320x58 -> 160x29, a later one took it 160x29 -> 192x35,
# and each update moved it again. `small` is deliberately the 160x29 shape,
# which is the one he called "more luxurious".
#
# Stored as complete geometry sets, not a scale factor. Scaling a single number
# drifts the proportions; these three were each shipped and each looked right.
PILL_SCALE_PRESETS: dict[str, dict[str, int]] = {
    "small": {
        "width": 160, "height": 29,
        "active_pill_width": 160, "active_pill_height": 29,
        "active_width": 160, "active_height": 29,
        "compact_width": 75, "compact_height": 22,
    },
    "medium": {
        "width": 192, "height": 35,
        "active_pill_width": 192, "active_pill_height": 35,
        "active_width": 192, "active_height": 35,
        "compact_width": 92, "compact_height": 26,
    },
    "large": {
        "width": 232, "height": 42,
        "active_pill_width": 232, "active_pill_height": 42,
        "active_width": 232, "active_height": 42,
        "compact_width": 111, "compact_height": 31,
    },
}

PILL_SCALE_LABELS: tuple[tuple[str, str], ...] = (
    ("small", "Small"),
    ("medium", "Medium"),
    ("large", "Large"),
)


def pill_scale_of(overlay: dict[str, Any]) -> str:
    """Which preset the current geometry matches, or "custom".

    Read from the numbers rather than a stored flag, so a config edited by hand
    or carried from an older build still shows the right selection instead of
    claiming a size it is not.
    """
    for name, preset in PILL_SCALE_PRESETS.items():
        if all(int(overlay.get(key, -1)) == value for key, value in preset.items()):
            return name
    return "custom"


def apply_pill_scale(overlay: dict[str, Any], scale: str) -> bool:
    """Write one preset's whole geometry set. True if anything changed."""
    preset = PILL_SCALE_PRESETS.get(str(scale).strip().lower())
    if preset is None:
        return False
    changed = False
    for key, value in preset.items():
        if int(overlay.get(key, -1)) != value:
            overlay[key] = value
            changed = True
    return changed


DEFAULT_CONFIG: dict[str, Any] = {
    "deepgram": {
        "api_key": "",
        "model": "nova-3",
        "language": "en-US",
        "sample_rate": 16000,
        "channels": 1,
        "encoding": "linear16",
        "smart_format": True,
        "punctuate": True,
        "interim_results": True,
        "endpointing": 300,
        "utterance_end_ms": 1000,
        "vad_events": True,
        "filler_words": False,
        "dictation": True,
        "numerals": True,
        "mip_opt_out": True,
        "extra": {},
    },
    "stt": {
        # X-480: a new install starts LOCAL, because that is what the product
        # is. The two routes we offer are the machine and the person's own
        # key; there is no managed service in between to start on.
        #
        # X-85 set this to the managed cloud and justified it as "the faster
        # and more accurate path". Both halves have since been measured and
        # neither survived. Local formatting came in at 880 ms against the
        # cloud's 978 ms on his own machine, and the speed probe (X-478) put
        # the on-device engine at 8.8x realtime. The comment outlived the
        # measurement, which is the only reason it stood this long.
        "provider": "local",
        "auto_download_local_model": True,
        # X-416: growing words in the Pill while the trigger is held, from the
        # on-device model. Off until the person asks; the release path is the
        # same either way.
        "local_live_captions": False,
        "providers": {
            "deepgram": {"api_key": "", "model": "nova-3", "variant": "streaming", "extra": {}},
            "openai": {"api_key": "", "model": "gpt-4o-transcribe", "variant": "json", "extra": {}},
            "elevenlabs": {"api_key": "", "model": "scribe_v2", "variant": "default", "extra": {}},
            "xai": {"api_key": "", "model": "grok-transcribe", "variant": "default", "extra": {}},
            "smallest": {"api_key": "", "model": "pulse-pro", "variant": "default", "extra": {}},
            "soniox": {"api_key": "", "model": "stt-async-v5", "variant": "default", "extra": {}},
            "groq": {"api_key": "", "model": "whisper-large-v3", "variant": "json", "extra": {}},
            "mistral": {"api_key": "", "model": "voxtral-mini-2602", "variant": "json", "extra": {}},
            "assemblyai": {"api_key": "", "model": "universal-3-pro", "variant": "default", "extra": {}},
            "google_gemini": {"api_key": "", "model": "gemini-3.6-flash", "variant": "default", "extra": {}},
            "custom_openai": {"api_key": "", "api_base": "", "model": "custom-model", "variant": "json", "extra": {}},
            # custom_models: models the person added themselves. Each entry is
            # either a Hugging Face CTranslate2 Whisper repo id ("owner/name")
            # or a path to a converted model folder -- both are what
            # faster-whisper takes directly, which is why no adapter is needed
            # per model. Anything unusable is dropped when the list is built.
            "local": {"api_key": "", "model": "parakeet-tdt-0.6b-v3", "variant": "auto",
                      "custom_models": [], "extra": {}},
        },
    },
    "hotkeys": {
        # macOS: hold the Globe/Fn key, exactly the trigger Mac users already
        # know from Wispr Flow and from Apple's own dictation. One key, one
        # hand. Windows keeps Ctrl+Win.
        "push_to_talk": [["fn"]] if sys.platform == "darwin" else [["ctrl", "cmd"]],
        "hands_free": [["ctrl", "cmd", "space"]],
        "command_mode": [["ctrl", "cmd", "alt"]],
        "cancel": [["esc"]],
        "panic": [["ctrl", "cmd", "esc"]],
        # X-42: hold, speak the instruction, release -- the selection
        # rewrites in place. A main feature; onboarding teaches the chord.
        "fix_that": [["ctrl", "alt", "f"]],
        # X-38: hear the last dictation read back before you send it.
        "read_back": [],
        "paste_last": [["shift", "alt", "z"]],
        # X-42: hold, speak the instruction, release -- the selection
        # rewrites in place. A main feature; onboarding teaches the chord.
        "fix_that": [["ctrl", "alt", "f"]],
        # X-38: hear the last dictation read back before you send it.
        "read_back": [],
        "copy_last": [["shift", "alt", "x"]],
        "polish": [["cmd", "alt", "1"]],
        "prompt_engineer": [["cmd", "alt", "2"]],
        "turn_to_list": [["cmd", "alt", "3"]],
        "view_diff": [["cmd", "alt", "o"]],
        "scratchpad": [],
        "pin_last": [],
        "meeting_mode": [],
        "translate_last": [],
        # Flips automatic dictation translation on and off without opening
        # Settings. Unbound by default like the other optional actions -- a
        # default chord would collide with somebody's muscle memory; the person
        # who wants a translation switch assigns one in two clicks.
        "translate_toggle": [],
    },
    "meeting": {
        "chunk_seconds": 25,
    },
    "dictation": {
        "max_seconds": 5 * 60,
        "no_speech_timeout_seconds": 15,
        "silence_timeout_seconds": 45,
        "hold_max_seconds": 30 * 60,
        "hold_no_speech_timeout_seconds": 120,
        "hold_silence_timeout_seconds": 300,
        # Paste the rules-only result immediately and let the model's
        # version replace it. Formatting is ~35ms locally and ~950ms
        # through the model, and the words do not have to wait for it.
        "speculative_paste": True,
        "tail_capture_ms": 520,
        "min_capture_ms": 900,
        "hold_debounce_ms": 35,
        "auto_paste": True,
        "smart_leading_space": True,
        # X-72 (his order, the Wispr behavior, THE DEFAULT): copy a link, dictate
        # "here's the link", hit Ctrl+V -- you get the LINK. The dictation
        # never steals the clipboard. Turn this off in Settings to keep the
        # dictation on the clipboard instead.
        "restore_clipboard_after_paste": True,
        "press_enter_command": True,
        "play_sounds": True,
        "sound_on": "felted_halo",
        "sound_off": "wood_block",
        "mute_output_while_recording": True,
        "mute_fade_ms": 180,
        "mute_fade_in_ms": 240,
        "paste_mode": "auto",
        "typing_interval_ms": 2,
        "clipboard_paste_delay_ms": 10,
        "retry_failed_capture": True,
        "safety_recordings_enabled": True,
        # Undo the paste and paste the correction over it, rather than
        # backspacing character by character. Constant time whatever the
        # length -- measured 197ms at 100, 300 and 900 characters, against
        # 4.3ms per character for backspacing.
        #
        # "auto" uses it in the applications whose undo grouping was actually
        # measured (paste.UNDO_VERIFIED_PROCESSES) and backspaces everywhere
        # else, because an application without undo pastes the correction
        # after the original instead of over it, and text appearing twice is
        # worse than text appearing late. "always" and "never" override it.
        "undo_replacement": "auto",
        "safety_recording_limit": 5,
    },
    "diagnostics": {
        # X-125/X-136: the local formatting journal. In DEFAULT_CONFIG so the
        # section always exists and a merge or save can never orphan the flag
        # -- the founder's enabled journal silently vanished once (observed
        # 2026-08-16, between builds; exact writer unidentified) and an
        # anchored default is the guard that outlives the mystery.
        "formatting_journal": False,
    },
    "cleanup": {
        "level": "high",
        "auto_rewrite": True,
        "remove_fillers": True,
        "backtrack": True,
        "smart_newlines": True,
        "censor_profanity": False,
        "smart_format": True,
        "format_mode": "auto",
        # X-602: a NEW install starts on Chill, the faithful finish
        # (docs/DICTATION-COMMANDMENTS.md section 3.1: faithful cleanup is the
        # default, a rewrite is an explicit choice). Measured on the
        # commandment cases and the parity battery (docs/COMMANDMENT-RESULTS.md),
        # Chill keeps the speaker's words where Executive rewrites them.
        # Existing installs keep what their config.json already says: the file
        # is written in full on first run, so this default reaches only a
        # config that has never been saved.
        "format_intensity": "standard",
        "intensity_default_migrated": True,
        "max_ai_format_ms": 1200,
        "preserve_meaning": True,
    },
    "audio": {
        "input_device": "",
        "gain_boost": 1.0,
        "quiet_mode": False,
        "quiet_mode_boost": 3.0,
    },
    "profiles": [],
    "plugins": {
        "enabled": False,
    },
    "wake_word": {
        "enabled": False,
        "model": "hey_jarvis",
        "threshold": 0.55,
    },
    "remote": {
        "enabled": False,
        "port": 4670,
        "token": "",
    },
    "dictionary": {
        "words": [
            "Deepgram",
            "OpenAI",
            "AssemblyAI",
        ],
        "replacements": [],
    },
    "snippets": [
        {"trigger": "my email signature", "text": "Best regards,\nYour Name", "enabled": True},
        {"trigger": "meeting link", "text": "Join the meeting: ", "enabled": True},
    ],
    "transforms": {
        "enabled": True,
        "translate_to": "English",
        "llm": {
            # X-114: "auto" = Talk DAT! Managed on an activated PC, the local
            # engine when signed out. The best formatter each install is
            # entitled to, with no configuration.
            "provider": "auto",
            "model": LOCAL_FORMATTER_MODEL,
            "api_key": "",
            "api_base": "http://localhost:11434",
            "timeout": 8,
            "auto_install": True,
            "balanced_default_migrated": True,
            "auto_formatter_migrated": True,
        },
        "ollama": {
            "enabled": True,
            "url": "http://localhost:11434/api/generate",
            "model": LOCAL_FORMATTER_MODEL,
        },
        "custom": [],
    },
    "translation": {
        "enabled": False,
        "auto_translate_dictation": False,
        # X-30: opt-in; its only power is skipping a translation when the
        # utterance is already in the target language.
        "bilingual_auto_detect": False,
        "engine": "local",
        "source_language": "auto",
        "target_language": "es",
        "model": "translategemma:4b",
        "api_base": "http://localhost:11434",
        "timeout_seconds": 120,
        "formality": "natural",
        "preserve_formatting": True,
        "glossary": [],
    },
    "overlay": {
        "show_on_start": True,
        "opacity": 0.94,
        "hover_fade_delay_ms": 2000,
        "hover_fade_opacity": 0.38,
        "width": 192,
        "height": 35,
        "active_pill_width": 192,
        "active_pill_height": 35,
        "active_width": 192,
        "active_height": 35,
        "compact_width": 92,
        "compact_height": 26,
        "wave_loop_start": 0,
        "wave_loop_end": 50,
        "active_frame_ms": 16,
        "idle_frame_ms": 33,
        "resize_frame_ms": 8,
        "resize_steps": 22,
        "active_loop_seconds": 2.6,
        "idle_loop_seconds": 8.0,
        "bottom_margin": 24,
        "half_scale_migrated": True,
        "balanced_scale_migrated": True,
        "result_hold_ms": 900,
        "error_hold_ms": 5200,
        "fixed_position": True,
        "position": "bottom-center",
        "follow_active_monitor": True,
        "no_activate": True,
        "hide_over_fullscreen_media": True,
        "show_session_over_fullscreen": True,
        "fullscreen_activation_visibility_migrated": True,
        "fullscreen_poll_ms": 450,
        "fullscreen_tolerance_px": 8,
        # X-642: the Pill is presented with per-pixel alpha on Windows (X-641).
        # False forces the old colour-key path, for a machine where layered
        # windows misbehave; read at start. A failing layered window falls
        # back by itself, so this is the manual override, not the safety net.
        "pill_per_pixel_alpha": True,
    },
    "privacy": {
        # X-465, his order: every capability runs on this machine. Sign-in,
        # licence and update checks are the only things that use the network,
        # and none of them carries what you said or wrote. Turning this off is
        # a deliberate choice a person makes, never something the app does for
        # them when a local part is missing.
        "local_only": True,
        # Owner decision 2026-09-23: the anonymous usage counts (first open,
        # first dictation, still in use, day 7) have their OWN switch, separate
        # from local_only, which governs audio and text. On by default; an
        # official build honours it, a source build never sends them
        # (official_build.activation_api_base).
        "share_usage_counts": True,
        "save_audio": False,
        "save_history": True,
        "history_limit": 0,
        "history_backend": "jsonl",
        "redact_pii": False,
    },
    "ui": {
        "theme": "dark",
        "settings_theme": "Flow Dark",
        "reduce_motion": False,
    },
    "onboarding": {
        "completed": False,
        "version": 0,
    },
    "licensing": {
        "api_base": DEFAULT_COMMERCE_API_URL,
        "product_url": "https://www.talkdat.app",
        "device_id": "",
        "device_name": "",
    },
    "updates": {
        "check_on_start": True,
        "auto_download": False,
        "channel": "beta",
        "prerelease_channel_migrated": True,
        "check_interval_hours": 24,
        "skip_version": "",
        "current_version": APP_VERSION,
        "last_checked_at": 0,
        "latest_version": "",
        "latest_release_url": "",
    },
}


def _apply_macos_defaults(defaults: dict[str, Any]) -> None:
    """Replace the Windows chords that mean something else on a Mac.

    "cmd" is the Windows key on Windows and Command on macOS, so most chords
    carry over unchanged and land somewhere sensible: push-to-talk stays Ctrl
    plus that key, which is unclaimed on both. The exceptions are the two that
    collide with a system shortcut, where leaving the default alone would mean
    the first thing a new user tries opens a macOS panel instead:

    - Ctrl+Cmd+Space is the macOS Character Viewer.
    - Cmd+Alt+O is taken in enough editors to be a poor default; the other
      Cmd+Alt chords are free.

    Anyone who has already chosen their own chords keeps them -- this only
    changes what a fresh install starts with.
    """
    hotkeys = defaults["hotkeys"]
    hotkeys["hands_free"] = [["ctrl", "cmd", "d"]]
    hotkeys["view_diff"] = [["cmd", "alt", "d"]]


if sys.platform == "darwin":
    _apply_macos_defaults(DEFAULT_CONFIG)


def _copy_missing_items(source_root: Path, destination_root: Path) -> list[str]:
    """Copy what is missing, and RETURN what could not be copied.

    X-238: this used to `except OSError: pass`. The items in here are
    config.json, history.db and the audio spool -- someone's settings and
    everything they have ever dictated. A locked file or a full disk meant the
    app came up looking factory-fresh, with no error, no log line and nothing
    to search for. "Talk DAT! lost my settings after an update" would have been
    unanswerable.

    Still soft: a file that will not copy must not stop the app from starting,
    because the alternative is an app that will not open at all. But soft is
    not the same as silent.
    """
    destination_root.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    for item in source_root.iterdir():
        destination = destination_root / item.name
        if destination.exists():
            continue
        try:
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)
        except OSError:
            failed.append(item.name)
            log.warning("could not migrate %s from the previous profile", item.name, exc_info=True)
    return failed


def _rename_legacy_root(legacy_root: Path) -> Path | None:
    backup = legacy_root.with_name(f"{APP_NAME}LegacyBackup")
    candidate = backup
    index = 2
    while candidate.exists():
        candidate = backup.with_name(f"{backup.name}{index}")
        index += 1
    try:
        legacy_root.rename(candidate)
        return candidate
    except OSError:
        # Harmless but not nothing: the old directory stays, so every launch
        # re-runs the migration and the person is left with two profile folders
        # and no idea which one is live.
        log.warning("could not set the previous profile aside at %s", candidate, exc_info=True)
        return None


def _migrate_legacy_app_dir(app_data: Path, root: Path) -> None:
    legacy_root = app_data / LEGACY_APP_NAME
    if not legacy_root.exists():
        return
    if not root.exists():
        try:
            legacy_root.rename(root)
            log.info("moved the previous profile into place")
            return
        except OSError:
            log.info("could not move the previous profile; copying instead", exc_info=True)
    failed = _copy_missing_items(legacy_root, root)
    kept = _rename_legacy_root(legacy_root)
    if failed:
        # One line naming every item, so a support reply can be specific about
        # what to recover and from where.
        log.warning(
            "migrated the previous profile but left %d item(s) behind: %s (original kept at %s)",
            len(failed), ", ".join(sorted(failed)), kept or legacy_root,
        )
    else:
        log.info("migrated the previous profile; original kept at %s", kept or legacy_root)


def _portable_root() -> Path | None:
    try:
        import sys

        base = Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).resolve().parent
        if (base / "portable.flag").exists():
            return base / "TalkDatData"
    except Exception:
        return None
    return None


def _restrict_to_owner(target: Path, mode: int) -> None:
    """Narrow a local data path to this user, on POSIX only.

    X-221: on macOS and Linux there is NO credential backend at all --
    credential_store() returns UnavailableCredentialStore for anything that is
    not Windows -- so every provider API key stays in config.json in plaintext.
    That fallback is deliberate and is pinned by a test; without it those
    platforms could not hold a key anywhere.

    What was NOT deliberate is the mode. A macOS home directory is 0755, so
    those keys were readable by every other account on the machine and by
    anything that walks the home tree: a sync client, a backup agent, a `find`
    on a shared box. The file mode is the ONLY thing protecting them there, and
    it was never set.

    This is a floor, not a keychain. Any process running as this user still
    reads the file freely, and the real fix is a Keychain Services backend --
    which is a bigger change that can DESTROY a key if the keychain refuses a
    write, so it does not go out unproven on hardware.

    A failure is swallowed on purpose: a filesystem that cannot express the
    mode, an exFAT stick or a mounted share, must not stop the app saving.
    """
    if os.name == "nt":
        return
    try:
        os.chmod(target, mode)
    except OSError:
        pass


def app_dir() -> Path:
    override = os.environ.get("TALK_DAT_HOME")
    portable = _portable_root()
    if override:
        root = Path(override).expanduser()
    elif portable is not None:
        root = portable
    elif sys.platform == "darwin":
        # Without this branch the APPDATA fallback below lands on ~/TalkDat and
        # drops the model cache in the middle of the user's home folder.
        root = mac_support.application_support_dir(APP_NAME)
        _migrate_legacy_app_dir(Path.home(), root)
    else:
        app_data = Path(os.environ.get("APPDATA", Path.home()))
        root = app_data / APP_NAME
        _migrate_legacy_app_dir(app_data, root)
    root.mkdir(parents=True, exist_ok=True)
    # 0700 covers everything inside too: config.json, history.jsonl, history.db,
    # the formatting journal and the audio spool are all under here.
    _restrict_to_owner(root, 0o700)
    return root


def config_path() -> Path:
    return app_dir() / "config.json"


def history_path() -> Path:
    return app_dir() / "history.jsonl"


def history_db_path() -> Path:
    return app_dir() / "history.db"


def full_history_path() -> Path:
    return app_dir() / "full-transcript-history.txt"


def live_draft_path() -> Path:
    return app_dir() / "live-transcript-draft.txt"


def recovered_draft_path() -> Path:
    return app_dir() / "recovered-draft.txt"


def preserve_live_draft_for_recovery(*, save_history: bool) -> Path | None:
    """X-544: keep the words a crash interrupted, out of the next dictation's way.

    The live draft is what holds a transcript when the app dies before History
    is written -- and delivery, the step most likely to kill the process, runs
    BEFORE that write. It did on 2026-09-14: heap corruption inside the
    clipboard snapshot took the process down mid-paste, the protected audio was
    recovered at the next launch, and the transcript was not.

    The draft had it. The problem is that the draft is a single rolling file:
    the first interim update of the next dictation overwrites it. The founder's
    words survived the crash by 63 seconds and were erased by the next sentence
    he spoke, with nothing having told him they were there.

    One fixed slot, deliberately, rather than a timestamped pile. The harm is
    "the next dictation destroys it", which one slot closes; a growing set of
    plaintext transcripts on disk is the artifact X-222 and X-195 exist to
    prevent, and a fixed name is one string in every erase path instead of a
    glob those paths cannot express.

    Honours `save_history` both ways. Off means off, and it means anything
    already kept goes too -- a switch that only stops the NEXT crash leaves the
    last one's words sitting in the clear.
    """
    target = recovered_draft_path()
    if not save_history:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            log.debug("recovered draft could not be removed", exc_info=True)
        return None
    try:
        text = live_draft_path().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.strip():
        return None
    try:
        target.write_text(text, encoding="utf-8")
    except OSError:
        # Best-effort, like the draft write itself. Never let this block a
        # launch: the app starting is worth more than the copy.
        log.exception("recovered draft could not be written")
        return None
    return target


def scratchpad_path() -> Path:
    return app_dir() / "scratchpad.md"


def scratchpad_tabs_path() -> Path:
    return app_dir() / "scratchpad-tabs.json"


def load_project_env(start: Path | None = None) -> None:
    root = start or Path.cwd()
    candidates = [root / ".env", root / ".env.local", root / ".env.example"]
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ and "put-your" not in value.lower():
                os.environ[key] = value


def deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_shortcuts(config: dict[str, Any]) -> dict[str, Any]:
    hotkeys = config.setdefault("hotkeys", {})
    for action, shortcuts in list(hotkeys.items()):
        if not isinstance(shortcuts, list):
            hotkeys[action] = []
            continue
        normalized: list[list[str]] = []
        for shortcut in shortcuts:
            if isinstance(shortcut, str):
                keys = [part.strip().lower() for part in shortcut.replace("+", " ").split()]
            elif isinstance(shortcut, list):
                keys = [str(part).strip().lower() for part in shortcut]
            else:
                continue
            keys = [key for key in keys if key]
            if keys:
                normalized.append(keys[:3])
        hotkeys[action] = normalized[:4]
    return config


# X-407: a config activated before the Railway move still names a host that
# died with the Google Cloud project (a generated *.run.app name, or the old
# knightaiav.com subdomain). Every managed-cloud call it makes answers 503
# from a Google error page, which the app reports as "model formatting
# unavailable" and the customer reads as "Executive does nothing". No dead
# name is spelled out here on purpose: tests scan the shipping tree for them.
RETIRED_HOST_SUFFIXES = (".run.app", ".knightaiav.com")


def _migrate_legacy_hosts(config: dict[str, Any]) -> bool:
    """Point a config at talkdat.app when it still names a retired host."""
    licensing = config.get("licensing")
    if not isinstance(licensing, dict):
        return False
    changed = False
    # Lazy: licensing imports this module. The defaults live there so the two
    # halves of the product can never disagree on the address (test_commerce_endpoint_agreement).
    from .licensing import DEFAULT_COMMERCE_API_URL, DEFAULT_PRODUCT_URL

    for key, default in (("api_base", DEFAULT_COMMERCE_API_URL), ("product_url", DEFAULT_PRODUCT_URL)):
        value = str(licensing.get(key) or "").strip()
        host = value.split("//", 1)[-1].split("/", 1)[0].lower()
        if host and host.endswith(RETIRED_HOST_SUFFIXES):
            licensing[key] = default
            changed = True
    return changed


def _migrate_overlay_sizes(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    """Move untouched legacy geometry to the smaller, lower anchored Pill."""
    overlay = config.setdefault("overlay", {})
    loaded_overlay = loaded.get("overlay", {}) if isinstance(loaded.get("overlay"), dict) else {}
    if bool(loaded_overlay.get("half_scale_migrated", False)):
        return
    # X-165: a size the person CHOSE is never resized again. Two migrations have
    # already moved this pill (320x58 -> 160x29, then 160x29 -> 192x35), which is
    # exactly what "it currently fluctuates in size" meant: each update picked a
    # new size for him. Once he has picked one, updates leave it alone.
    if bool(loaded_overlay.get("pill_scale_chosen", False)):
        return

    legacy_active = (
        int(loaded_overlay.get("active_width", loaded_overlay.get("width", 320))),
        int(loaded_overlay.get("active_height", loaded_overlay.get("height", 58))),
    )
    if legacy_active == (320, 58):
        for key, value in {
            "width": 160,
            "height": 29,
            "active_pill_width": 160,
            "active_pill_height": 29,
            "active_width": 160,
            "active_height": 29,
        }.items():
            overlay[key] = value

    current = (int(loaded_overlay.get("compact_width", 110)), int(loaded_overlay.get("compact_height", 38)))
    if current in {(110, 38), (150, 44), (188, 44)}:
        overlay["compact_width"] = 75
        overlay["compact_height"] = 22
    if int(loaded_overlay.get("bottom_margin", 68)) == 68:
        overlay["bottom_margin"] = 24
    overlay["half_scale_migrated"] = True


def _migrate_overlay_balanced_scale(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    """Slightly enlarge only the untouched 0.3.25 compact geometry."""
    overlay = config.setdefault("overlay", {})
    loaded_overlay = loaded.get("overlay", {}) if isinstance(loaded.get("overlay"), dict) else {}
    if bool(loaded_overlay.get("balanced_scale_migrated", False)):
        return
    # X-165: a size the person CHOSE is never resized again. Two migrations have
    # already moved this pill (320x58 -> 160x29, then 160x29 -> 192x35), which is
    # exactly what "it currently fluctuates in size" meant: each update picked a
    # new size for him. Once he has picked one, updates leave it alone.
    if bool(loaded_overlay.get("pill_scale_chosen", False)):
        return

    active = (int(overlay.get("active_width", 192)), int(overlay.get("active_height", 35)))
    compact = (int(overlay.get("compact_width", 92)), int(overlay.get("compact_height", 26)))
    if active == (160, 29) and compact == (75, 22):
        for key, value in {
            "width": 192,
            "height": 35,
            "active_pill_width": 192,
            "active_pill_height": 35,
            "active_width": 192,
            "active_height": 35,
            "compact_width": 92,
            "compact_height": 26,
        }.items():
            overlay[key] = value
    overlay["balanced_scale_migrated"] = True


# Find-more P1-1: the paste-delay and animation migrations below ran on EVERY
# load with no done-stamp, so a paste delay of 30 or 80 ms (the one fix
# Settings offers for apps that miss the paste) and two animation settings
# went back to the default at every launch. They now run once. They shipped
# on 2026-07-09 and every launch since has saved their result, so a config
# last run after that holds either the migrated value or the person's own
# choice, and only older ones are migrated.
_LOAD_MIGRATIONS_SHIPPED_AT = 1783641600  # 2026-07-10 00:00 UTC


def _already_migrated(loaded: dict[str, Any], section: str, stamp: str) -> bool:
    loaded_section = loaded.get(section) if isinstance(loaded.get(section), dict) else {}
    if loaded_section.get(stamp):
        return True
    updates = loaded.get("updates") if isinstance(loaded.get("updates"), dict) else {}
    try:
        return float(updates.get("last_run_at") or 0) >= _LOAD_MIGRATIONS_SHIPPED_AT
    except (TypeError, ValueError):
        return False


def _migrate_overlay_animation(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    """Move older defaults onto the deterministic trigger animation, once (P1-1)."""
    overlay = config.setdefault("overlay", {})
    loaded_overlay = loaded.get("overlay", {}) if isinstance(loaded.get("overlay"), dict) else {}
    migrated = _already_migrated(loaded, "overlay", "animation_defaults_migrated")
    overlay["animation_defaults_migrated"] = True
    if migrated:
        return
    if int(loaded_overlay.get("resize_frame_ms", 12)) in {10, 12, 14, 16}:
        overlay["resize_frame_ms"] = 8
    if int(loaded_overlay.get("resize_steps", 60)) in {18, 28, 36, 60}:
        overlay["resize_steps"] = 22


def _migrate_fullscreen_activation_visibility(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    """Show recording feedback over fullscreen once, then preserve user choice."""
    overlay = config.setdefault("overlay", {})
    loaded_overlay = loaded.get("overlay", {}) if isinstance(loaded.get("overlay"), dict) else {}
    if bool(loaded_overlay.get("fullscreen_activation_visibility_migrated", False)):
        return
    overlay["show_session_over_fullscreen"] = True
    overlay["fullscreen_activation_visibility_migrated"] = True


def _migrate_paste_latency_default(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    """Move older untouched paste-delay defaults to the faster current default, once (P1-1)."""
    loaded_dictation = loaded.get("dictation", {}) if isinstance(loaded.get("dictation"), dict) else {}
    migrated = _already_migrated(loaded, "dictation", "paste_delay_default_migrated")
    config.setdefault("dictation", {})["paste_delay_default_migrated"] = True
    if migrated:
        return
    try:
        delay = int(loaded_dictation.get("clipboard_paste_delay_ms", 80) or 80)
    except (TypeError, ValueError):
        return
    if delay in {30, 80}:
        config.setdefault("dictation", {})["clipboard_paste_delay_ms"] = 10

def _migrate_mac_fn_default(config: dict[str, Any]) -> None:
    """One-time move to the Globe/Fn hold on macOS.

    The trigger Mac users already hold in muscle memory -- Wispr Flow binds
    virtual keycode 63 (the Globe key) to push-to-talk, and Apple's own
    dictation lives on the same key. Only configs still carrying the old
    cross-platform default move; a chord anyone chose on purpose is kept.
    """
    if sys.platform != "darwin":
        return
    hotkeys = config.setdefault("hotkeys", {})
    flags = config.setdefault("migrations", {})
    if flags.get("mac_fn_default"):
        return
    flags["mac_fn_default"] = True
    if hotkeys.get("push_to_talk") == [["ctrl", "cmd"]]:
        hotkeys["push_to_talk"] = [["fn"]]


def _migrate_macos_system_chord_clashes(config: dict[str, Any]) -> None:
    """Move chords that mean something else on a Mac, but only untouched ones.

    Changing the default in DEFAULT_CONFIG reaches new installs and nobody else,
    and every installation that has ever opened Settings has the old chord
    written on disk. On macOS that leaves hands-free on Ctrl+Cmd+Space, which is
    the system Character Viewer: pressing it opens Apple's emoji panel and does
    not dictate.

    Only the exact Windows default is rewritten. Anyone who chose Ctrl+Cmd+Space
    deliberately would have had to pick it in Settings, and this cannot tell
    those apart -- so the bar is "identical to what we shipped", and anything
    else is left alone.
    """
    if sys.platform != "darwin":
        return
    hotkeys = config.get("hotkeys")
    if not isinstance(hotkeys, dict):
        return
    clashes = {
        "hands_free": ([["ctrl", "cmd", "space"]], [["ctrl", "cmd", "d"]]),
        "view_diff": ([["cmd", "alt", "o"]], [["cmd", "alt", "d"]]),
    }
    for action, (windows_default, mac_default) in clashes.items():
        if hotkeys.get(action) == windows_default:
            hotkeys[action] = [list(chord) for chord in mac_default[0:1]]


def _migrate_undo_replacement_default(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    """Move the old always-off undo setting onto the per-application default.

    `save_config` writes the whole merged config, so every installation that
    has ever opened Settings has a literal `false` on disk. Changing the
    default alone would reach new installs and nobody else -- which is the
    wrong half of the audience, since the slow correction is the thing being
    complained about by people already using it.

    Rewriting a saved value is normally the wrong move, and it is safe here for
    one specific reason: until this release the setting had no UI, so a `false`
    on disk is the old default rather than a decision anyone made. Anyone who
    did turn it off by hand and wants it to stay off can write "never", which
    is left alone, and the Settings toggle now writes that too.
    """
    loaded_dictation = loaded.get("dictation", {}) if isinstance(loaded.get("dictation"), dict) else {}
    if loaded_dictation.get("undo_replacement") is False:
        config.setdefault("dictation", {})["undo_replacement"] = "auto"


def _migrate_local_formatter_default(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    """Move blank or legacy formatter settings onto the local on-device model."""
    transforms = config.setdefault("transforms", {})
    llm = transforms.setdefault("llm", {})
    legacy_ollama = transforms.setdefault("ollama", {})
    loaded_transforms = loaded.get("transforms", {}) if isinstance(loaded.get("transforms"), dict) else {}
    loaded_llm = loaded_transforms.get("llm", {}) if isinstance(loaded_transforms.get("llm"), dict) else {}
    loaded_ollama = loaded_transforms.get("ollama", {}) if isinstance(loaded_transforms.get("ollama"), dict) else {}

    provider = str(loaded_llm.get("provider", "")).strip().lower()
    model = str(loaded_llm.get("model", "")).strip().lower()
    base = str(loaded_llm.get("api_base", "")).strip()
    default_already_migrated = bool(loaded_llm.get("balanced_default_migrated", False))
    if (
        not default_already_migrated
        and provider in {"", "none", "ollama"}
        and model in LEGACY_LOCAL_FORMATTER_MODELS
    ):
        llm["provider"] = "ollama"
        llm["model"] = LOCAL_FORMATTER_MODEL
        llm["api_base"] = base or "http://localhost:11434"
    if not default_already_migrated:
        llm["balanced_default_migrated"] = True

    legacy_model = str(loaded_ollama.get("model", "")).strip().lower()
    if not default_already_migrated and legacy_model in LEGACY_LOCAL_FORMATTER_MODELS:
        legacy_ollama["model"] = LOCAL_FORMATTER_MODEL
    if str(llm.get("provider", "")).strip().lower() == "ollama":
        legacy_ollama["enabled"] = True
        try:
            loaded_timeout = int(loaded_llm.get("timeout", 20) or 20)
        except (TypeError, ValueError):
            loaded_timeout = 20
        if loaded_timeout in {20, 30}:
            llm["timeout"] = 8
        llm.setdefault("auto_install", True)


def _migrate_blank_cloud_default_to_local(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    """New/blank installs should work without a cloud key."""
    stt = config.get("stt", {}) if isinstance(config.get("stt"), dict) else {}
    deepgram = config.get("deepgram", {}) if isinstance(config.get("deepgram"), dict) else {}
    providers = stt.get("providers", {}) if isinstance(stt.get("providers"), dict) else {}
    deepgram_provider = providers.get("deepgram", {}) if isinstance(providers.get("deepgram"), dict) else {}
    provider = str(stt.get("provider", "")).strip().lower()
    has_deepgram_key = bool(
        str(deepgram.get("api_key", "")).strip()
        or str(deepgram_provider.get("api_key", "")).strip()
        or os.environ.get("DEEPGRAM_API_KEY", "").strip()
    )
    if provider in {"", "deepgram"} and not has_deepgram_key:
        config.setdefault("stt", {})["provider"] = "local"


def _migrate_prerelease_update_channel(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    updates = config.setdefault("updates", {})
    loaded_updates = loaded.get("updates", {}) if isinstance(loaded.get("updates"), dict) else {}
    current_is_prerelease = any(marker in APP_VERSION.lower() for marker in ("-alpha", "-beta", "-rc"))
    was_prerelease = any(
        marker in str(loaded_updates.get("current_version", "")).lower()
        for marker in ("-alpha", "-beta", "-rc")
    )
    already_migrated = bool(loaded_updates.get("prerelease_channel_migrated", False))
    if current_is_prerelease and was_prerelease and not already_migrated:
        if str(loaded_updates.get("channel", "stable")).strip().lower() == "stable":
            updates["channel"] = "beta"
        updates["prerelease_channel_migrated"] = True


def _migrate_audio_device_label(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    """Upgrade older numeric mic selections to the safer "index: name" form."""
    loaded_audio = loaded.get("audio", {}) if isinstance(loaded.get("audio"), dict) else {}
    raw = str(loaded_audio.get("input_device", "")).strip()
    if not raw or ":" in raw or not raw.lstrip("-").isdigit():
        return
    try:
        import sounddevice as sd

        devices = list(sd.query_devices())
        index = int(raw)
        if index < 0 or index >= len(devices):
            return
        device = devices[index]
        if int(device.get("max_input_channels", 0)) <= 0:
            return
        name = str(device.get("name", "")).strip()
    except Exception:
        return
    if name:
        if low_confidence_input_name(name):
            config.setdefault("audio", {})["input_device"] = ""
            return
        config.setdefault("audio", {})["input_device"] = f"{index}: {name}"


def _migrate_licensing_enforcement(config: dict[str, Any]) -> None:
    """Drop the retired paywall switch from saved configs.

    `licensing.enforcement` chose whether the entitlement gate blocked
    dictation or only logged. 2026-09-22: Talk DAT! is free and there is no
    gate left to enforce, so the key is removed rather than left behind for
    someone to wire back up. Sign-in state in `licensing` is untouched.
    """
    licensing = config.get("licensing")
    if isinstance(licensing, dict):
        licensing.pop("enforcement", None)


RETIRED_MANAGED_PROVIDER = "talk_dat_cloud"
RETIRED_ROUTE_MODES = ("cloud", "auto")
RETIRED_TRANSLATION_ENGINES = ("managed", "cloud", RETIRED_MANAGED_PROVIDER)


def _names_retired_managed_host(value: Any) -> bool:
    """Does this URL point at the dead managed-cloud service?

    Narrower than RETIRED_HOST_SUFFIXES on purpose. That tuple is right for
    `licensing`, which only ever named OUR service. A provider's `api_base` is
    different: a person running their own OpenAI-compatible server on Cloud
    Run has a perfectly good *.run.app address, and rewriting it would break a
    working setup to fix one that is not theirs. So only our generated service
    names (`talk-dat-...run.app`) and the old knightaiav.com subdomain match.
    """
    text = str(value or "").strip().lower()
    host = text.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if not host:
        return False
    if host.endswith(".run.app") and host.startswith("talk-dat-"):
        return True
    return host.endswith(".knightaiav.com") and "talkdat" in host


def _migrate_retired_managed_cloud(config: dict[str, Any]) -> list[str]:
    """Scrub the retired managed cloud out of a saved config. 2026-09-22.

    Talk DAT! is free and runs on the machine; the managed service behind
    "talk_dat_cloud" is gone. The READ side already routes around every
    leftover (route_mode, byok_provider, llm_configured, the app's legacy
    fallback), but the file kept naming it: the owner's own config.json still
    carried `stt.cloud_provider = "talk_dat_cloud"` and a providers entry
    pointing at the dead Cloud Run host. Every reader that ever forgets one of
    those guards dials a service that answers with a Google error page.

    What is removed or rewritten, and nothing else:
      * stt.cloud_provider / stt.provider naming the managed service
      * stt.providers.talk_dat_cloud and transforms.providers.talk_dat_cloud
      * any other provider's api_base naming OUR dead host (a person's own
        server, including their own *.run.app one, is left alone)
      * transforms.llm.provider "talk_dat_cloud" -> the shipped "auto"
      * translation.engine "managed"/"cloud" -> "local" (it raises
        engine_invalid otherwise)
      * stt.route_mode "auto"/"cloud" -> whatever `route_mode()` already
        resolves it to: local, or byok when the person's own key is set. The
        stored value is made to say what the app was doing anyway, so no one
        is moved.

    Every BYOK key is untouched. The only key cleared is transforms.llm's when
    its provider WAS the managed service: that credential was ours, not
    theirs, and leaving it would file it under the "auto" vault slot.

    Runs after the vault is hydrated, because the byok half of the route
    decision needs to see a key that lives only in Credential Manager.
    Idempotent: a second run finds nothing and returns [].
    """
    changes: list[str] = []
    stt = config.get("stt")
    if isinstance(stt, dict):
        for field in ("cloud_provider", "provider"):
            if str(stt.get(field, "") or "").strip().lower() == RETIRED_MANAGED_PROVIDER:
                if field == "cloud_provider":
                    stt.pop(field, None)
                else:
                    stt[field] = "local"
                changes.append(f"stt.{field}")
        providers = stt.get("providers")
        if isinstance(providers, dict):
            if RETIRED_MANAGED_PROVIDER in providers:
                providers.pop(RETIRED_MANAGED_PROVIDER, None)
                changes.append(f"stt.providers.{RETIRED_MANAGED_PROVIDER}")
            for provider_id, settings in providers.items():
                if isinstance(settings, dict) and _names_retired_managed_host(settings.get("api_base")):
                    settings["api_base"] = ""
                    changes.append(f"stt.providers.{provider_id}.api_base")
        raw_route = str(stt.get("route_mode", "") or "").strip().lower()
        if raw_route in RETIRED_ROUTE_MODES:
            from .stt_registry import route_mode

            stt["route_mode"] = route_mode(config)
            changes.append("stt.route_mode")

    transforms = config.get("transforms")
    if isinstance(transforms, dict):
        providers = transforms.get("providers")
        if isinstance(providers, dict) and RETIRED_MANAGED_PROVIDER in providers:
            providers.pop(RETIRED_MANAGED_PROVIDER, None)
            changes.append(f"transforms.providers.{RETIRED_MANAGED_PROVIDER}")
        llm = transforms.get("llm")
        if isinstance(llm, dict):
            default_llm = DEFAULT_CONFIG["transforms"]["llm"]
            if str(llm.get("provider", "") or "").strip().lower() == RETIRED_MANAGED_PROVIDER:
                llm["provider"] = default_llm["provider"]
                llm["api_key"] = ""
                changes.append("transforms.llm.provider")
            if _names_retired_managed_host(llm.get("api_base")):
                provider = str(llm.get("provider", "") or "").strip().lower()
                base = default_llm["api_base"]
                if provider not in {"auto", "ollama"}:
                    try:
                        from .llm import PROVIDER_DEFAULTS

                        base = str(PROVIDER_DEFAULTS.get(provider, {}).get("api_base", ""))
                    except Exception:  # pragma: no cover - defensive; llm always imports
                        base = ""
                llm["api_base"] = base
                changes.append("transforms.llm.api_base")

    translation = config.get("translation")
    if isinstance(translation, dict):
        if str(translation.get("engine", "") or "").strip().lower() in RETIRED_TRANSLATION_ENGINES:
            translation["engine"] = "local"
            changes.append("translation.engine")
        if _names_retired_managed_host(translation.get("api_base")):
            translation["api_base"] = DEFAULT_CONFIG["translation"]["api_base"]
            changes.append("translation.api_base")

    if changes:
        # Field names only. Never a value: an api_base or key is not log material.
        log.info("scrubbed retired managed-cloud settings: %s", ", ".join(changes))
    return changes


def _migrate_formatter_off_haiku(config: dict[str, Any]) -> None:
    """Move saved configs off the OpenRouter Haiku formatter.

    A default change reaches only fresh installs. Every machine that has run
    the app since 2026-08-04 has `anthropic/claude-haiku-4.5` written into its
    saved config, so without this the owner's own machine would keep using the
    model the measurements rejected while new installs got the fast one.

    Only the exact string is rewritten. Somebody who deliberately chose a
    different model, including a different Anthropic one, keeps it -- a
    migration that overrides real choices is worse than the stale default it
    was meant to fix.
    """
    llm_settings = config.get("transforms", {}).get("llm", {})
    if not isinstance(llm_settings, dict):
        return
    stale = {"anthropic/claude-haiku-4.5", "anthropic/claude-haiku-4-5"}
    if str(llm_settings.get("model", "")).strip().lower() in stale:
        llm_settings["model"] = "google/gemini-3.5-flash-lite"


def _migrate_default_formatter_to_auto(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    """Move OUR ollama default onto "auto" so entitled installs format on cloud.

    X-114, from the founder's own log: the shipped local default (qwen3:1.7b,
    CPU) timed out into the rules formatter 284 times, and when it did answer
    inside the budget it returned the transcript essentially untouched --
    measured 1.10s to change nothing. "auto" resolves to Talk DAT! Managed on an
    activated PC (where the speech already goes) and back to the local engine
    when signed out.

    Decided from the LOADED file, never the merged config: DEFAULT_CONFIG now
    carries the done-stamp for fresh installs, so reading the merged view
    would see "already migrated" on every machine and no-op forever -- the
    exact trap every other migration here takes `loaded` to avoid.

    Only the configuration WE wrote is rewritten: provider ollama, on our
    model, at the local default base, carrying the balanced_default_migrated
    stamp our earlier migration left. A hand-picked backend -- any other
    provider, model, or base -- is a real choice and keeps working untouched.
    """
    llm = config.setdefault("transforms", {}).setdefault("llm", {})
    loaded_transforms = loaded.get("transforms", {}) if isinstance(loaded.get("transforms"), dict) else {}
    loaded_llm = loaded_transforms.get("llm", {}) if isinstance(loaded_transforms.get("llm"), dict) else {}
    if bool(loaded_llm.get("auto_formatter_migrated", False)):
        return
    provider = str(loaded_llm.get("provider", "")).strip().lower()
    model = str(loaded_llm.get("model", "")).strip().lower()
    base = str(loaded_llm.get("api_base", "")).strip().rstrip("/").lower()
    ours = (
        provider == "ollama"
        and model == LOCAL_FORMATTER_MODEL
        and base in {"", "http://localhost:11434", "http://127.0.0.1:11434"}
        and bool(loaded_llm.get("balanced_default_migrated", False))
    )
    if ours or not loaded_llm:
        llm["provider"] = "auto"
    llm["auto_formatter_migrated"] = True


def _migrate_intensity_default_to_executive(config: dict[str, Any], loaded: dict[str, Any]) -> None:
    """The founder's order, verbatim: "Make the best formatting the default."

    Executive -- the full-logic, boardroom-grade pass -- becomes the default
    formatting level. Decided from the LOADED file, never the merged view
    (DEFAULT_CONFIG now carries the done-stamp for fresh installs, the same
    trap every migration here takes `loaded` to avoid). The intensity
    setting shipped one release before this flip, so a loaded "standard"
    without the stamp is OUR old default, not a person's choice. Anyone who
    picks Standard in Settings afterwards keeps it: the save writes the
    stamp into their file and this never runs again.
    """
    cleanup = config.setdefault("cleanup", {})
    loaded_cleanup = loaded.get("cleanup", {}) if isinstance(loaded.get("cleanup"), dict) else {}
    if bool(loaded_cleanup.get("intensity_default_migrated", False)):
        return
    if str(loaded_cleanup.get("format_intensity", "standard")).strip().lower() == "standard":
        cleanup["format_intensity"] = "executive"
    cleanup["intensity_default_migrated"] = True


# X-169: modes that must never survive a restart.
#
# He reported it twice, the second time in a message that was itself translated
# into Spanish on the way out: "why does it translate by default? This is
# critical... It should require manual activation for each use."
#
# It was never a wrong default. `DEFAULT_CONFIG["translation"]` ships both flags
# False. What happened is that the Translate workspace opens with a full-width
# hero bar reading "Auto-translate  English -> Spanish  ·  OFF, tap to turn on",
# and one click on it wrote `auto_translate_dictation: true` to config.json --
# permanently, silently, for every dictation from then on. Nothing ever turned
# it back off, and nothing in the dictation flow says which language it is
# about to hand you.
#
# So the switch stops being a setting and becomes session state. Turning it on
# still works exactly as before and lasts as long as the app is open; closing
# Talk DAT! always returns to off. An accidental click now costs one dictation
# instead of every dictation forever.
#
# Every path in and out of disk goes through here -- `load_config` forces these
# back to their shipped default on the way in, `save_config` refuses to write
# them on the way out -- so a future toggle cannot persist by accident even if
# it calls save_settings. A sweep of the other five mode toggles (pause, meeting,
# scribe, captions, hands-free) found they were ALL already session-only; this
# one was the lone deviation.
SESSION_ONLY_SETTINGS: tuple[tuple[str, str], ...] = (
    ("translation", "auto_translate_dictation"),
)


def _reset_session_only_settings(config: dict[str, Any]) -> None:
    """Force every session-only key back to its shipped default, in place."""
    for section, key in SESSION_ONLY_SETTINGS:
        shipped = DEFAULT_CONFIG.get(section, {}).get(key, False)
        target = config.get(section)
        if isinstance(target, dict):
            target[key] = shipped


# P0-7 (find-more sweep): every word, snippet, profile and setting lives in
# config.json. A read or parse failure used to carry on with the defaults, and
# the first save of the launch (stamp_first_run, the startup save, any
# Settings change) wrote those defaults over the file, silently. A file that
# will not parse is now moved aside and kept; a file that cannot be opened at
# all stays where it is and no save touches it until the next launch.
_UNREADABLE_CONFIG_ROOTS: set[Path] = set()
# ERROR_SHARING_VIOLATION and ERROR_LOCK_VIOLATION: another process (a backup
# or sync client, antivirus) has the file open. It hit the model marker on this
# PC on 2026-09-22, and it passes, so it is worth a few short retries.
_SHARING_VIOLATIONS = {32, 33}
_READ_ATTEMPTS = 5


def _read_config_file(path: Path) -> tuple[dict[str, Any], str]:
    """The parsed file and "", or {} and why it could not be used.

    "locked" means the bytes could not be read; "damaged" means they were read
    and are not a settings object (bad JSON, bad UTF-8, or not an object).
    """
    raw = b""
    for attempt in range(_READ_ATTEMPTS):
        try:
            raw = path.read_bytes()
            break
        except FileNotFoundError:
            return {}, ""
        except OSError as error:
            transient = isinstance(error, PermissionError) or getattr(error, "winerror", None) in _SHARING_VIOLATIONS
            if not transient or attempt == _READ_ATTEMPTS - 1:
                log.warning("config.json could not be read: %s", error)
                return {}, "locked"
            time.sleep(0.1 * (attempt + 1))
    try:
        # ValueError covers both a JSON error and bad UTF-8; the old read let
        # UnicodeDecodeError escape and the app failed to start.
        loaded = json.loads(raw.decode("utf-8-sig"))
    except ValueError as error:
        log.warning("config.json is not valid settings: %s", error)
        return {}, "damaged"
    if not isinstance(loaded, dict):
        log.warning("config.json holds %s, not settings", type(loaded).__name__)
        return {}, "damaged"
    return loaded, ""


def _keep_unreadable_config(path: Path, problem: str) -> None:
    """Move a damaged file aside, or fence saves when it cannot be moved."""
    from . import launch_notices

    kept: Path | None = None
    if problem == "damaged":
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for suffix in range(100):
            candidate = path.with_name(f"{path.name}.unreadable-{stamp}" + (f"-{suffix}" if suffix else ""))
            if candidate.exists():
                continue
            try:
                os.replace(path, candidate)
                kept = candidate
            except OSError as error:
                log.warning("config.json could not be moved aside: %s", error)
            break
    if kept is not None:
        log.warning("config.json could not be read; it was kept as %s and defaults are in use", kept.name)
        launch_notices.notice(
            "config",
            f"Your settings file could not be read, so Talk DAT! started with default settings. "
            f"The old file was kept as {kept.name} in {path.parent}.",
            message="Your settings could not be read. Talk DAT! started with default settings.",
        )
        return
    _UNREADABLE_CONFIG_ROOTS.add(path.parent.resolve())
    log.warning("config.json could not be read; defaults are in use and nothing is saved this session")
    launch_notices.notice(
        "config",
        "Your settings file could not be opened, so Talk DAT! started with default settings. "
        "Changes are not saved until you restart Talk DAT!, so your saved settings stay as they were.",
        message="Your settings could not be opened. Restart Talk DAT! to load them.",
    )


def load_config(project_root: Path | None = None) -> dict[str, Any]:
    load_project_env(project_root)
    path = config_path()
    if not path.exists():
        save_config(DEFAULT_CONFIG)

    loaded, problem = _read_config_file(path)
    if problem:
        _keep_unreadable_config(path, problem)

    config = normalize_shortcuts(deep_merge(DEFAULT_CONFIG, loaded if isinstance(loaded, dict) else {}))
    _migrate_licensing_enforcement(config)
    _migrate_formatter_off_haiku(config)
    _migrate_macos_system_chord_clashes(config)
    _migrate_mac_fn_default(config)
    _migrate_overlay_sizes(config, loaded if isinstance(loaded, dict) else {})
    _migrate_overlay_balanced_scale(config, loaded if isinstance(loaded, dict) else {})
    _migrate_legacy_hosts(config)
    _migrate_overlay_animation(config, loaded if isinstance(loaded, dict) else {})
    _migrate_fullscreen_activation_visibility(config, loaded if isinstance(loaded, dict) else {})
    _migrate_paste_latency_default(config, loaded if isinstance(loaded, dict) else {})
    _migrate_undo_replacement_default(config, loaded if isinstance(loaded, dict) else {})
    _migrate_local_formatter_default(config, loaded if isinstance(loaded, dict) else {})
    _migrate_default_formatter_to_auto(config, loaded if isinstance(loaded, dict) else {})
    _migrate_intensity_default_to_executive(config, loaded if isinstance(loaded, dict) else {})
    _migrate_prerelease_update_channel(config, loaded if isinstance(loaded, dict) else {})
    _migrate_audio_device_label(config, loaded if isinstance(loaded, dict) else {})
    # X-169. Unconditional, not a one-time migration: these keys are session
    # state, so a value on disk is stale by definition however it got there.
    _reset_session_only_settings(config)
    env_key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if env_key and not str(config.get("deepgram", {}).get("api_key", "")).strip():
        config["deepgram"]["api_key"] = env_key
    stt = config.setdefault("stt", {})
    providers = stt.setdefault("providers", {})
    deepgram_settings = providers.setdefault("deepgram", {})
    if str(config.get("deepgram", {}).get("api_key", "")).strip() and not str(deepgram_settings.get("api_key", "")).strip():
        deepgram_settings["api_key"] = config["deepgram"]["api_key"]
    if str(config.get("deepgram", {}).get("model", "")).strip() and not str(deepgram_settings.get("model", "")).strip():
        deepgram_settings["model"] = config["deepgram"]["model"]
    env_map = {
        "OPENAI_API_KEY": "openai",
        "ELEVENLABS_API_KEY": "elevenlabs",
        "XAI_API_KEY": "xai",
        "GROQ_API_KEY": "groq",
        "MISTRAL_API_KEY": "mistral",
        "ASSEMBLYAI_API_KEY": "assemblyai",
        "GEMINI_API_KEY": "google_gemini",
    }
    for env_name, provider_id in env_map.items():
        value = os.environ.get(env_name, "").strip()
        settings = providers.setdefault(provider_id, {})
        if value and not str(settings.get("api_key", "")).strip():
            settings["api_key"] = value
    hydrate_config_secrets(config)
    _migrate_retired_managed_cloud(config)
    _migrate_blank_cloud_default_to_local(config, loaded if isinstance(loaded, dict) else {})
    dictation = config.setdefault("dictation", {})
    dictation["safety_recordings_enabled"] = True
    try:
        dictation["safety_recording_limit"] = max(5, int(dictation.get("safety_recording_limit", 5)))
    except (TypeError, ValueError):
        dictation["safety_recording_limit"] = 5
    return config


# X-548: one writer at a time, for the whole read-merge-write below.
#
# The app fires two anonymous beacons from two daemon threads at startup
# (`report_install` and `report_heartbeat`), each stamping its own flag and
# calling save_config. On a fresh install neither guard is satisfied yet, so
# both fire together -- the live HTTP log shows the resulting pair of
# POST /v1/activation landing 2-11ms apart. The carry-forward READ is part of
# the critical section, not just the write: two threads that both read before
# either writes would each merge a pre-edit view of the file.
_SAVE_LOCK = threading.RLock()
# A restored file must survive the OLD process's exit-time config save.
# Restart creates a fresh process and clears this in-memory fence.
_RESTORED_CONFIG_ROOTS: set[Path] = set()


def save_config(config: dict[str, Any], *, forget_sections: tuple[str, ...] = (), credential_backend=None) -> bool:
    """Persist the config.

    `forget_sections` names top-level sections the caller deliberately removed
    and does NOT want carried forward from disk. It exists for exactly one
    caller -- the reset dialog -- and it is a keyword rather than a default
    because X-196 showed what happens when deletion is inferred from absence
    instead of stated.
    """
    path = config_path()
    # X-169: `config_for_persistence` deep-copies, so stripping here leaves the
    # caller's live config untouched -- auto-translate stays on for the rest of
    # THIS session and simply never reaches the file. Doing it at the write
    # boundary rather than in each caller is what makes it airtight: the
    # Translate workspace's own save path writes this key too, and it is
    # neutralised without knowing anything about it.
    # X-140: a save must never ERASE a top-level section it simply never
    # loaded. The founder's diagnostics flag was wiped twice by exactly this
    # class -- a process holding pre-edit memory flushing over a newer file.
    # Sections present on disk but absent from memory are carried forward;
    # sections the caller DOES hold are written as held, so a deliberate
    # change (or a deliberate empty) still lands.
    #
    # X-196: which meant ABSENCE MEANT "I did not load this", and a reset had
    # no way to say "I removed this on purpose". `reset.prune_config` deletes
    # the section, save_config found it on disk and put it straight back, and
    # so every config-backed reset category -- App settings, Onboarding, Custom
    # words and phrases, Snippets -- was a no-op that reported success. The
    # founder could have run "Everything, start completely over" and kept every
    # word he had ever taught it.
    #
    # Deletion is now STATED rather than inferred. X-140's protection is
    # unchanged for every caller that does not name a section.
    forgotten = set(forget_sections)
    with _SAVE_LOCK:
        if path.parent.resolve() in _RESTORED_CONFIG_ROOTS:
            raise ValueError("Restart Talk DAT to use the restored settings before making more changes.")
        if path.parent.resolve() in _UNREADABLE_CONFIG_ROOTS:
            # P0-7: the file on disk could not be opened at launch and is
            # still there. What this process holds is the defaults, so any
            # write would replace the person's settings with them. Refused
            # quietly, because startup and the beacons save unasked; the
            # launch notice already said changes are not kept, and the
            # Settings page turns False into an error.
            log.warning("settings not saved: config.json could not be read at launch")
            return False
        persisted = config_for_persistence(config, store=credential_backend)
        _reset_session_only_settings(persisted)
        try:
            on_disk = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(on_disk, dict):
                for key, value in on_disk.items():
                    if key not in persisted and key not in forgotten:
                        persisted[key] = value
        except (OSError, json.JSONDecodeError):
            pass
        # X-548: never write into config.json itself. `Path.write_text` opens
        # for truncation, so anything that interrupts it between the truncate
        # and the write -- a crash, a kill, a full disk, the OS closing the app
        # down -- leaves the file empty or half a JSON document, and the next
        # launch reads a config that will not parse. Every setting, every
        # custom word and every snippet is in this one file.
        #
        # X-140's comment above records that this class already wiped the
        # founder's diagnostics flag twice. That fix made the MERGE safe; the
        # WRITE stayed truncating. A temporary file plus os.replace makes the
        # swap atomic, so a reader sees either the whole old file or the whole
        # new one and never a partial write. Same pattern the audio spool and
        # app.py already use.
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_text(json.dumps(persisted, indent=2, sort_keys=True), encoding="utf-8")
            # X-221 applies to the temporary too: it holds the same plaintext
            # keys, so it must never exist at a looser mode even briefly.
            _restrict_to_owner(temporary, 0o600)
            try:
                handle = os.open(temporary, os.O_RDWR)
                try:
                    os.fsync(handle)
                finally:
                    os.close(handle)
            except OSError:
                # Durability is a bonus here; atomicity is the fix. A
                # filesystem that refuses fsync must not fail the save.
                pass
            os.replace(temporary, path)
        except BaseException:
            # A failed save must not leave litter next to the config.
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
    # X-221: on macOS and Linux this file holds the provider API keys in
    # plaintext, because those platforms have no credential backend. The
    # directory is 0700 already; this narrows the file itself, so a key cannot
    # be read by another local account even if the directory mode is ever
    # loosened by a restore, a sync client or a careless chmod -R.
    _restrict_to_owner(path, 0o600)
    return True


def deepgram_params(config: dict[str, Any]) -> dict[str, Any]:
    dg = config.get("deepgram", {})
    deepgram_stt = config.get("stt", {}).get("providers", {}).get("deepgram", {})
    params = {
        "model": deepgram_stt.get("model") or dg.get("model", "nova-3"),
        "language": dg.get("language", "en-US"),
        "encoding": dg.get("encoding", "linear16"),
        "sample_rate": int(dg.get("sample_rate", 16000)),
        "channels": int(dg.get("channels", 1)),
        "smart_format": bool(dg.get("smart_format", True)),
        "punctuate": bool(dg.get("punctuate", True)),
        "interim_results": bool(dg.get("interim_results", True)),
        "endpointing": dg.get("endpointing", 300),
        "utterance_end_ms": dg.get("utterance_end_ms", 1000),
        "vad_events": bool(dg.get("vad_events", True)),
        "filler_words": bool(dg.get("filler_words", False)),
        "dictation": bool(dg.get("dictation", True)),
        "numerals": bool(dg.get("numerals", True)),
        "mip_opt_out": bool(dg.get("mip_opt_out", True)),
    }
    # Deepgram biases decoding toward these, which fixes a name before it is
    # ever mis-heard -- strictly better than repairing the transcript after.
    # Both stores feed it: the plain Settings list and the structured entries
    # from the pill's add-words window. A term is only worth sending as its
    # canonical spelling; the "sounds like" variants are our own repair hints
    # and would bias the recognizer toward the wrong word.
    dictionary = config.get("dictionary", {})
    spoken: list[str] = []
    for entry in list(dictionary.get("words") or []) + list(dictionary.get("terms") or []):
        if isinstance(entry, dict):
            entry = entry.get("text") or entry.get("word") or ""
        word = str(entry).strip()
        if word and word not in spoken:
            spoken.append(word)
    # The brand defaults ride along as recognition hints too, so the name is
    # more often heard right in the first place rather than repaired after.
    from .vocabulary import DEFAULT_TERMS

    for term in DEFAULT_TERMS:
        if term.text not in spoken:
            spoken.append(term.text)
    if spoken:
        params["keyterm"] = spoken
    extra = dg.get("extra", {})
    if isinstance(extra, dict):
        for key, value in extra.items():
            clean_key = str(key).strip()
            if clean_key:
                params[clean_key] = value
    return params


def engine_recording_ceiling(cloud_engine: bool) -> int:
    """X-41: how long one recording may run, by WHAT engine runs.

    2026-09-22: Talk DAT! is free, so there is no plan to consult. Everyone
    gets the generous ceiling that used to be the paid one: the on-device
    engine runs to 10 hours, and a bring-your-own-key cloud engine stops at
    1 hour, because the person's own provider bills that time by the minute
    and most of them refuse a longer upload anyway. A person's own smaller
    setting is still respected by the caller; this is only the ceiling.
    """
    return 3600 if cloud_engine else 36000
