"""On-device speech-to-text: model catalog, downloader, and inference engines.

Engines are optional pip dependencies, imported lazily:
- onnx-asr (Parakeet, Canary, GigaAM) for the best CPU speed/accuracy.
- faster-whisper (Whisper + Distil-Whisper families) for deep multilingual coverage.

Models download once into %APPDATA%/TalkDat/models/<model-id> and never leave the machine.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import logging
import json
import os
import shutil
import sys
import threading
import time
import re

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import app_dir


StatusCallback = Callable[[str], None]

READY_MARKER = ".talkdat-ready"
# About 1.5 s of retries in total before a busy marker is left as it is.
READY_MARKER_RETRIES = 10
READY_SCHEMA_VERSION = 1
MIN_PAYLOAD_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class LocalModel:
    id: str
    label: str
    engine: str  # "onnx_asr" | "faster_whisper"
    engine_id: str
    size_mb: int
    languages: str
    recommended: bool = False
    notes: str = ""


CUSTOM_MODEL_PREFIX = "custom:"

# A Hugging Face repo id: owner/name, the characters the Hub actually permits.
# Deliberately strict -- this string is handed to a downloader, and a lax
# pattern here is the difference between a typo and a path traversal.
_HF_REPO_RE = re.compile(r"^[A-Za-z0-9][\w.-]{0,95}/[A-Za-z0-9][\w.-]{0,95}$")


def custom_model_from(entry: Any) -> "LocalModel | None":
    """Build a LocalModel from one entry of `stt.providers.local.custom_models`.

    Accepts either a Hugging Face CTranslate2 Whisper repo id, or a directory
    on this machine holding an already-converted model. Both are what
    faster-whisper takes directly, which is the whole reason this feature is
    possible without an adapter per model.

    Returns None for anything unusable rather than raising: this runs while
    building the model list for a settings panel, and one bad entry must not
    take the list down with it.
    """
    if isinstance(entry, str):
        entry = {"id": entry}
    if not isinstance(entry, dict):
        return None
    reference = str(entry.get("id") or entry.get("path") or "").strip()
    if not reference:
        return None

    looks_like_path = ("\\" in reference or "/" in reference and Path(reference).drive) or Path(reference).is_absolute()
    if looks_like_path:
        folder = Path(reference)
        if not folder.is_dir():
            return None
        label = str(entry.get("label") or folder.name).strip() or folder.name
        size = 0
    elif _HF_REPO_RE.match(reference):
        label = str(entry.get("label") or reference.split("/")[-1]).strip() or reference
        size = int(entry.get("size_mb") or 0)
    else:
        return None

    return LocalModel(
        id=f"{CUSTOM_MODEL_PREFIX}{reference}",
        label=f"{label} (yours)",
        engine="faster_whisper",
        engine_id=reference,
        size_mb=size,
        languages=str(entry.get("languages") or "as published"),
        notes="Added by you. Loaded through faster-whisper, which takes a "
              "CTranslate2 Whisper repo id or a converted folder.",
    )


def custom_models(config: dict[str, Any]) -> tuple["LocalModel", ...]:
    """Every usable custom model in the config, in the order they were added."""
    stt = config.get("stt", {}) if isinstance(config.get("stt"), dict) else {}
    providers = stt.get("providers", {}) if isinstance(stt.get("providers"), dict) else {}
    local = providers.get("local", {}) if isinstance(providers.get("local"), dict) else {}
    entries = local.get("custom_models", [])
    if not isinstance(entries, list):
        return ()
    built = [custom_model_from(entry) for entry in entries]
    seen: set[str] = set()
    unique: list[LocalModel] = []
    for model in built:
        if model is None or model.id in seen:
            continue
        seen.add(model.id)
        unique.append(model)
    return tuple(unique)


RECOMMENDED_SUFFIX = " (recommended)"


def model_display_name(label: str) -> str:
    """A model's name without the catalogue's "(recommended)" note.

    The note is advice for someone choosing, so it belongs in a list of
    choices. A status line ("Speech runs on this computer ...") or a closed
    select that has room for about twenty characters reads better with the
    name alone; the Speech page says which model is recommended in its own
    words.
    """
    text = str(label or "").strip()
    return text[: -len(RECOMMENDED_SUFFIX)].rstrip() if text.endswith(RECOMMENDED_SUFFIX) else text


def available_local_models(config: dict[str, Any] | None = None) -> tuple["LocalModel", ...]:
    """The packaged catalogue plus whatever the person added themselves."""
    if not config:
        return LOCAL_MODELS
    return LOCAL_MODELS + custom_models(config)


DEFAULT_LOCAL_MODEL_ID = "parakeet-tdt-0.6b-v3"

LOCAL_MODELS: tuple[LocalModel, ...] = (
    LocalModel(
        "parakeet-tdt-0.6b-v3",
        "Parakeet TDT 0.6B v3 (recommended)",
        "onnx_asr",
        "nemo-parakeet-tdt-0.6b-v3",
        640,
        "25 European languages, auto-detect",
        recommended=True,
        notes="Best speed/accuracy on plain CPU. CC-BY-4.0.",
    ),
    LocalModel(
        "parakeet-tdt-0.6b-v2",
        "Parakeet TDT 0.6B v2",
        "onnx_asr",
        "nemo-parakeet-tdt-0.6b-v2",
        640,
        "English",
        notes="Slightly better English WER than v3. CC-BY-4.0.",
    ),
    # X-474: the two NVIDIA Canary entries were REMOVED here on 2026-09-05
    # after measuring them. Both raise the same ONNX error on this runtime --
    # "Non-zero status code returned while running Reshape node" -- on
    # DirectML and on CPU, quantized and unquantized, on a fresh download. The
    # picker downloads about a gigabyte before the first run, so offering one
    # that crashes afterwards spends bandwidth and patience to reach an error.
    # onnx-asr 0.12.0 is the suspect. If a later version fixes it, MEASURE it
    # and put them back deliberately; the guard test names what to re-check.
    LocalModel(
        "gigaam-v3-e2e-ctc",
        "GigaAM v3",
        "onnx_asr",
        "gigaam-v3-e2e-ctc",
        160,
        "Russian",
    ),
    LocalModel(
        "whisper-large-v3-turbo",
        "Whisper Large v3 Turbo",
        "faster_whisper",
        "large-v3-turbo",
        1600,
        "99 languages",
        notes="Best broad multilingual coverage. MIT.",
    ),
    LocalModel(
        "distil-large-v3.5",
        "Distil-Whisper Large v3.5",
        "faster_whisper",
        "distil-large-v3.5",
        1500,
        "English",
        notes="Newest distil release. MIT.",
    ),
    LocalModel(
        "whisper-large-v3",
        "Whisper Large v3",
        "faster_whisper",
        "large-v3",
        3100,
        "99 languages",
        notes="Maximum Whisper accuracy; heavy on CPU.",
    ),
    LocalModel("whisper-medium", "Whisper Medium", "faster_whisper", "medium", 1500, "99 languages"),
    LocalModel("whisper-medium.en", "Whisper Medium EN", "faster_whisper", "medium.en", 1500, "English"),
    LocalModel("whisper-small", "Whisper Small", "faster_whisper", "small", 480, "99 languages"),
    LocalModel("whisper-small.en", "Whisper Small EN", "faster_whisper", "small.en", 480, "English"),
    LocalModel("distil-medium.en", "Distil-Whisper Medium EN", "faster_whisper", "distil-medium.en", 750, "English"),
    LocalModel("distil-small.en", "Distil-Whisper Small EN", "faster_whisper", "distil-small.en", 330, "English"),
    LocalModel("whisper-base", "Whisper Base", "faster_whisper", "base", 145, "99 languages"),
    LocalModel("whisper-base.en", "Whisper Base EN", "faster_whisper", "base.en", 145, "English"),
    LocalModel("whisper-tiny", "Whisper Tiny", "faster_whisper", "tiny", 75, "99 languages"),
    LocalModel("whisper-tiny.en", "Whisper Tiny EN", "faster_whisper", "tiny.en", 75, "English"),
)

LOCAL_MODEL_BY_ID = {model.id: model for model in LOCAL_MODELS}

# X-237: the exact Hugging Face commit each bundled Whisper model is fetched at.
#
# Without a revision, faster-whisper downloads whatever `main` points to right
# now. That is a moving target owned by somebody else: a repo owner -- or
# anyone who takes over the account -- can rewrite the branch and every Talk
# DAT! install silently picks up different weights on its next download. The
# model files are CTranslate2 binaries rather than pickles, so this is a
# "you get different software than you audited" problem rather than a remote
# code execution one, but the download should still be reproducible.
#
# Keyed by faster-whisper's short name, which is what the catalogue stores.
# Regenerate with: python scripts/refresh_model_pins.py
#
# NOT COVERED, deliberately and stated rather than implied:
#   - the five onnx_asr models. `onnx_asr.load_model()` takes no revision
#     argument, so there is nowhere to put one. Pretending otherwise by
#     listing them here would be worse than the gap.
#   - custom models the user adds themselves. They chose the repo; we have no
#     basis for pinning it and no way to know which commit they meant.
_PINNED_REVISIONS: dict[str, str] = {
    "large-v3-turbo": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",  # mobiuslabsgmbh/faster-whisper-large-v3-turbo
    "distil-large-v3.5": "9793ccc07920e0f830e1dba0343efcdf0ef8c903",  # distil-whisper/distil-large-v3.5-ct2
    "large-v3": "edaa852ec7e145841d8ffdb056a99866b5f0a478",  # Systran/faster-whisper-large-v3
    "medium": "08e178d48790749d25932bbc082711ddcfdfbc4f",  # Systran/faster-whisper-medium
    "medium.en": "a29b04bd15381511a9af671baec01072039215e3",  # Systran/faster-whisper-medium.en
    "small": "536b0662742c02347bc0e980a01041f333bce120",  # Systran/faster-whisper-small
    "small.en": "d1d751a5f8271d482d14ca55d9e2deeebbae577f",  # Systran/faster-whisper-small.en
    "distil-medium.en": "80ddfce281f77766d8943d63109199fc8145dfa5",  # Systran/faster-distil-whisper-medium.en
    "distil-small.en": "ef77d90526ccd62cde3808ee70626a01e5cf83e4",  # Systran/faster-distil-whisper-small.en
    "base": "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",  # Systran/faster-whisper-base
    "base.en": "3d3d5dee26484f91867d81cb899cfcf72b96be6c",  # Systran/faster-whisper-base.en
    "tiny": "d90ca5fe260221311c53c58e660288d3deb8d356",  # Systran/faster-whisper-tiny
    "tiny.en": "0d3d19a32d3338f10357c0889762bd8d64bbdeba",  # Systran/faster-whisper-tiny.en
}


def pinned_revision(model: LocalModel) -> str | None:
    """The commit a bundled model must be downloaded at, or None if unpinned."""
    return _PINNED_REVISIONS.get(model.engine_id)


_ENGINES: dict[str, Any] = {}
_ENGINE_LOCK = threading.Lock()


class LocalSTTError(RuntimeError):
    pass


def models_dir() -> Path:
    root = app_dir() / "models"
    root.mkdir(parents=True, exist_ok=True)
    return root


# Characters a model id may contain that a Windows path component may not.
# `custom:owner/repo` has two of them, and the colon is the worst: it is the
# drive separator, so the folder is not merely oddly named, it cannot be
# created at all.
_UNSAFE_IN_PATH = str.maketrans({c: "_" for c in r':/\<>"|?*'})


def model_dir(model: LocalModel) -> Path:
    """Where a model's payload is *written*.

    The id is sanitised rather than used raw, because a custom model's id
    carries a Hugging Face reference and those contain a slash and a colon.
    Every packaged model id is already free of these characters, so this is a
    no-op for them and cannot orphan an existing download.
    """
    return models_dir() / model.id.translate(_UNSAFE_IN_PATH)


def bundled_models_dir() -> Path | None:
    """Where a model shipped with the installer lives, if there is one.

    Beside the executable, never inside it. A PyInstaller onefile build
    unpacks its whole payload to a temporary directory on every launch, so
    burying several hundred megabytes of weights in there would add that copy
    to every single start.

    Read-only by design. Nothing writes here: the directory belongs to the
    installer, and under MSIX the install root is not writable at all.
    """
    try:
        base = Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).resolve().parent
    except Exception:
        return None
    candidates = [base / "models"]
    if sys.platform == "darwin" and base.name == "MacOS" and base.parent.name == "Contents":
        # In a .app the executable lives in Contents/MacOS, so "beside the
        # executable" is a directory nobody would ever put models in. Resources
        # is where a bundle keeps read-only payload, and PyInstaller's COLLECT
        # output sits in Frameworks -- both are checked so a bundled model can
        # actually be found instead of silently redownloaded.
        contents = base.parent
        candidates += [contents / "Resources" / "models", contents / "Frameworks" / "models"]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def bundled_model_dir(model: LocalModel) -> Path | None:
    root = bundled_models_dir()
    if root is None:
        return None
    candidate = root / model.id.translate(_UNSAFE_IN_PATH)
    return candidate if candidate.is_dir() else None


def resolved_model_dir(model: LocalModel) -> Path:
    """Where a model's payload should be *read* from.

    A downloaded copy wins over the bundled one. Someone who re-downloaded a
    model did so for a reason -- usually because the shipped copy was damaged
    -- and silently preferring the installer's copy would make that repair do
    nothing.
    """
    downloaded = model_dir(model)
    if _is_complete_at(model, downloaded):
        return downloaded
    bundled = bundled_model_dir(model)
    if bundled is not None and _is_complete_at(model, bundled):
        return bundled
    return downloaded


def local_model_for_id(model_id: str, config: dict[str, Any] | None = None) -> LocalModel:
    """Resolve a model id, including one the person added themselves.

    A custom id carries its own reference -- `custom:owner/repo` -- so it
    resolves without the config in the common case. The config is still
    accepted and preferred when available, because that is where a custom
    entry's label and languages live, and falling back to a reconstructed one
    would show "(yours)" with none of the detail they typed.

    Anything unrecognised still falls back to the default. Silently dictating
    with the wrong model is bad; refusing to dictate at all is worse.
    """
    wanted = str(model_id).strip()
    model = LOCAL_MODEL_BY_ID.get(wanted)
    if model is not None:
        return model
    if wanted.startswith(CUSTOM_MODEL_PREFIX):
        if config:
            for candidate in custom_models(config):
                if candidate.id == wanted:
                    return candidate
        rebuilt = custom_model_from(wanted[len(CUSTOM_MODEL_PREFIX):])
        if rebuilt is not None:
            return rebuilt
    return LOCAL_MODEL_BY_ID[DEFAULT_LOCAL_MODEL_ID]


def selected_local_model(config: dict[str, Any]) -> LocalModel | None:
    """The local model this config would dictate with, or None if it would not."""
    stt = config.get("stt", {}) if isinstance(config.get("stt"), dict) else {}
    if str(stt.get("provider", "")).strip().lower() != "local":
        return None
    providers = stt.get("providers", {}) if isinstance(stt.get("providers"), dict) else {}
    settings = providers.get("local", {}) if isinstance(providers.get("local"), dict) else {}
    return local_model_for_id(str(settings.get("model") or DEFAULT_LOCAL_MODEL_ID), config)


def model_to_prefetch(config: dict[str, Any]) -> LocalModel | None:
    """The local model that still needs downloading, if any.

    This used to return None for anyone dictating through a cloud provider,
    which is the default and what a trial hands you. The consequence was that
    the offline promise had no substance: a cloud user had no local weights on
    disk at all, so the first time the Wi-Fi dropped there was nothing to fall
    back to and the dictation was simply lost.

    So the fallback model is fetched regardless of which provider is selected.
    It costs one background download, once, on a machine that is by definition
    online at the time, and it is what makes "it runs on your machine" true for
    every install rather than only for the ones that opted in.

    Downloading is not loading. The engine is still only warmed when a local
    model is actually selected, so this cost is disk, not several hundred
    megabytes of resident memory.
    """
    stt = config.get("stt", {}) if isinstance(config.get("stt"), dict) else {}
    if not bool(stt.get("auto_download_local_model", True)):
        return None
    model = selected_local_model(config)
    if model is None:
        # A cloud provider is selected. Fetch what the rescue path would reach
        # for, unless the person has switched the rescue off -- in which case
        # the weights would never be used and the download would be waste.
        if not bool(stt.get("local_fallback", True)):
            return None
        providers = stt.get("providers", {}) if isinstance(stt.get("providers"), dict) else {}
        settings = providers.get("local", {}) if isinstance(providers.get("local"), dict) else {}
        try:
            model = local_model_for_id(
                str(settings.get("model") or DEFAULT_LOCAL_MODEL_ID), config
            )
        except Exception:
            return None
    return None if is_downloaded(model) else model


def machine_ram_gb() -> float:
    """Installed memory in GB, or 0 when it cannot be read (never a guess)."""
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_uint32),
                ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / (1024 ** 3)
    except Exception:
        pass
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3)
    except Exception:
        return 0.0


# X-413: a cloud route quietly becomes the local rescue model the moment the
# cloud is unreachable (the founder's own evening: a dead host, every take on
# Parakeet), and until now that engine was built inside the first dictation
# that needed it, 11 to 14 s of session creation plus the GPU's shape
# compilation. A machine that can carry the engine warms it at launch.
WARM_RESCUE_MIN_RAM_GB = 12.0


def model_to_warm(config: dict[str, Any]) -> LocalModel | None:
    """The local model whose engine should be loaded before the first dictation.

    Downloading the weights and loading them are different costs and only the
    first was ever paid ahead of time. `model_to_prefetch` returns None once the
    model is on disk, so from the second launch onwards nothing prepared
    anything, and building the ONNX session happened inside the first
    dictation -- measured at 7.9 seconds against 0.9-1.6 seconds for every
    dictation after it, on the same machine and the same clip.

    That cost lands on the first thing a person does after opening the app,
    which is the worst place for it and the reason it reads as "this is slow"
    rather than "this is loading".

    A config that dictates locally warms its model. A config on a cloud route
    warms the rescue model instead, but only where the engine is cheap to hold:
    a usable GPU, or at least WARM_RESCUE_MIN_RAM_GB of memory. A small laptop
    on the cloud keeps its RAM, exactly as before.
    """
    model = selected_local_model(config)
    if model is None:
        from . import local_fallback  # lazy: local_fallback imports this module

        if not local_fallback.enabled(config):
            return None
        if not (gpu_available() or machine_ram_gb() >= WARM_RESCUE_MIN_RAM_GB):
            return None
        model = local_fallback.fallback_model(config)
    if model is None:
        return None
    return model if is_downloaded(model) else None


def warm_engine(model: LocalModel) -> bool:
    """Build the inference session now so the first dictation does not.

    Returns whether it worked. A failure here is not worth surfacing -- the
    model will simply load on first use, which is what happened before this
    existed -- but it is worth logging, because a model that cannot load at
    idle will not load under a dictation either.
    """
    try:
        engine = ensure_loaded(model, gpu=gpu_available())
        if is_gpu_engine(engine) and model.engine == "onnx_asr":
            # X-408: DirectML compiles per shape, so the short buckets are
            # compiled here rather than inside somebody's first dictation, and
            # the second pass is the honest speed of this GPU.
            import numpy as np

            sample_rate = 16000
            for bucket in (GPU_BUCKETS_S[0], GPU_BUCKETS_S[1]):
                _recognize_onnx(engine, np.zeros(bucket * sample_rate, dtype=np.float32), sample_rate)
            started = time.perf_counter()
            _recognize_onnx(engine, np.zeros(GPU_BUCKETS_S[0] * sample_rate, dtype=np.float32), sample_rate)
            warm_seconds = time.perf_counter() - started
            _GPU_STATE["warm_seconds"] = warm_seconds
            if warm_seconds > GPU_SLOW_WARM_SECONDS:
                _GPU_STATE["slow"] = True
                log.warning("GPU path is slow here (%.2fs for a %ds clip); dictation stays on the CPU", warm_seconds, GPU_BUCKETS_S[0])
                ensure_loaded(model)
            else:
                log.info("GPU path warm: %.2fs for a %ds clip", warm_seconds, GPU_BUCKETS_S[0])
        return True
    except Exception:
        log.warning("could not warm %s ahead of first use; it will load on demand",
                    model.id, exc_info=True)
        return False


def is_downloaded(model: LocalModel) -> bool:
    """Whether this model is usable right now, from anywhere.

    Either the person downloaded it or the installer shipped it. The caller
    only ever wants to know "can I transcribe with this without a network",
    and where the bytes came from does not change that answer.
    """
    if _is_complete_at(model, model_dir(model)):
        return True
    bundled = bundled_model_dir(model)
    return bundled is not None and _is_complete_at(model, bundled)


def _is_complete_at(model: LocalModel, target: Path) -> bool:
    marker = target / READY_MARKER
    if not marker.is_file() or not _payload_looks_complete(model, target):
        return False
    try:
        manifest = json.loads(marker.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        # Older releases wrote a plain `ok` marker. Accept it only when the
        # model payload itself is present; the next load upgrades the marker.
        return True
    if not isinstance(manifest, dict):
        return False
    if (
        int(manifest.get("schema_version", 0)) != READY_SCHEMA_VERSION
        or str(manifest.get("model_id", "")) != model.id
        or str(manifest.get("engine", "")) != model.engine
        or str(manifest.get("engine_id", "")) != model.engine_id
    ):
        return False
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, dict) or not manifest_files:
        return False
    for relative, expected_size in manifest_files.items():
        path = target / str(relative)
        try:
            if not path.is_file() or path.stat().st_size != int(expected_size):
                return False
        except (OSError, TypeError, ValueError):
            return False
    payload_bytes, file_count = _payload_stats(target)
    return (
        payload_bytes >= int(manifest.get("payload_bytes", 0)) >= MIN_PAYLOAD_BYTES
        and file_count >= int(manifest.get("file_count", 0)) > 0
    )


def _payload_stats(target: Path) -> tuple[int, int]:
    inventory = _payload_inventory(target)
    return sum(inventory.values()), len(inventory)


def _payload_inventory(target: Path) -> dict[str, int]:
    inventory: dict[str, int] = {}
    if not target.is_dir():
        return inventory
    for path in target.rglob("*"):
        # The marker and every temporary copy of it (one per writer) are
        # bookkeeping, not payload.
        if not path.is_file() or path.name.startswith(READY_MARKER):
            continue
        relative = path.relative_to(target)
        if ".cache" in relative.parts:
            continue
        try:
            inventory[relative.as_posix()] = path.stat().st_size
        except OSError:
            continue
    return inventory


def _payload_looks_complete(model: LocalModel, target: Path) -> bool:
    payload_bytes, _file_count = _payload_stats(target)
    if payload_bytes < MIN_PAYLOAD_BYTES:
        return False
    if model.engine == "onnx_asr":
        onnx_files = [path for path in target.rglob("*.onnx") if path.is_file()]
        text_assets = [
            path
            for pattern in ("*.txt", "config.json", "config.yaml")
            for path in target.rglob(pattern)
            if path.is_file()
        ]
        return bool(onnx_files and text_assets)
    if model.engine == "faster_whisper":
        return any(path.is_file() for path in target.rglob("model.bin"))
    return False


def _write_ready_manifest(model: LocalModel, target: Path) -> None:
    payload_bytes, file_count = _payload_stats(target)
    manifest = {
        "schema_version": READY_SCHEMA_VERSION,
        "model_id": model.id,
        "engine": model.engine,
        "engine_id": model.engine_id,
        "payload_bytes": payload_bytes,
        "file_count": file_count,
        "files": _payload_inventory(target),
        "verified_at": int(time.time()),
    }
    marker = target / READY_MARKER
    # 0.4.151 startup, owner's PC: warming Parakeet failed with WinError 32
    # on the rename, because Windows refuses to replace a file another handle
    # has open -- a second loader, a Settings probe reading the marker, an
    # antivirus scan. Three changes make the write safe to lose that race:
    # 1. An unchanged manifest is not rewritten at all (every normal launch).
    # 2. Each writer has its own temporary name, so two never share one.
    # 3. The replace is retried briefly, and a marker that still cannot be
    #    replaced is logged, not raised: the engine is already loaded, and the
    #    marker is only a cache of "this download was complete".
    try:
        existing = json.loads(marker.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        existing = None
    if isinstance(existing, dict):
        unchanged = {k: v for k, v in existing.items() if k != "verified_at"}
        if unchanged == {k: v for k, v in manifest.items() if k != "verified_at"}:
            return
    temporary = target / f"{READY_MARKER}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as error:
        log.warning("could not write the ready marker for %s: %s", model.id, error)
        return
    delay = 0.02
    for attempt in range(READY_MARKER_RETRIES):
        try:
            os.replace(temporary, marker)
            return
        except PermissionError:
            if attempt == READY_MARKER_RETRIES - 1:
                break
            time.sleep(delay)
            delay = min(delay * 2, 0.25)
        except OSError:
            break
    log.warning("the ready marker for %s is in use; keeping the previous one", model.id)
    with contextlib.suppress(OSError):
        temporary.unlink()


def downloaded_size_mb(model: LocalModel) -> int:
    root = model_dir(model)
    if not root.exists():
        return 0
    total = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    return int(total / (1024 * 1024))


def delete_model(model: LocalModel) -> None:
    with _ENGINE_LOCK:
        _ENGINES.pop(model.id, None)
        _ENGINES.pop(f"{model.id}:gpu", None)
    root = model_dir(model)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


def _gpu_providers() -> list[str]:
    try:
        import onnxruntime

        available = set(onnxruntime.get_available_providers())
    except Exception:
        return []
    # CoreML is the Apple-silicon accelerator and belongs in this list. It was
    # already doing the work by accident: with no CUDA or DirectML present this
    # returned [], the caller then passed no providers at all, and onnxruntime's
    # default order on macOS happens to put CoreML first. Measured on this
    # machine, it takes 1,528 of Parakeet's 3,249 nodes. Naming it means the
    # "use GPU" setting reports and controls what is actually happening instead
    # of being a no-op that looks like one.
    preferred = [
        name
        for name in ("CUDAExecutionProvider", "DmlExecutionProvider", "CoreMLExecutionProvider")
        if name in available
    ]
    return preferred + ["CPUExecutionProvider"] if preferred else []

# X-408: DirectML (any DirectX 12 GPU, no CUDA install) or CUDA when present.
# The int8 graph already on disk is what runs there: measured on the founder's
# RTX 3090, 2.25 s for a 70-second take against 18 s on the CPU, with ONNX
# Runtime keeping only shape-handling nodes on the CPU. DirectML compiles
# kernels per input shape, so audio is padded to a few fixed lengths (below)
# and those lengths are warmed once; and it allows one Run at a time per
# session, so GPU runs are serialised behind a lock.
GPU_BUCKETS_S = (5, 10, 15, 20, 25)
GPU_SLOW_WARM_SECONDS = 2.5
_GPU_STATE: dict[str, Any] = {"slow": False, "warm_seconds": None}
_GPU_ENGINE_IDS: set[int] = set()
_GPU_RUN_LOCK = threading.Lock()


def gpu_available() -> bool:
    """Whether the GPU path is worth using on this machine right now."""
    return bool(_gpu_providers()) and not _GPU_STATE["slow"]


def gpu_default(extra: dict[str, Any] | None) -> bool:
    """The session's GPU choice: an explicit `gpu` setting wins, otherwise the machine decides."""
    value = (extra or {}).get("gpu")
    if value is None:
        return gpu_available()
    return bool(value)


def padded_seconds(seconds: float) -> float:
    """The bucket a clip is padded to on the GPU, so shapes repeat and kernels stay compiled."""
    for bucket in GPU_BUCKETS_S:
        if seconds <= bucket:
            return float(bucket)
    return float(seconds)


def is_gpu_engine(engine: Any) -> bool:
    return id(engine) in _GPU_ENGINE_IDS


log = logging.getLogger(__name__)


def _prepare_model_download() -> None:
    # Frozen windowed apps have no stderr stream. Hugging Face's terminal progress
    # bar otherwise crashes before a first-run model download can begin.
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    with contextlib.suppress(Exception):
        from huggingface_hub.utils import disable_progress_bars

        disable_progress_bars()


def download_progress_mb(model: LocalModel) -> tuple[float, float]:
    """(megabytes fetched so far, megabytes expected) for a running download.

    Read from Hugging Face's own partial files rather than from its progress
    bar. The bar is deliberately switched off in `_prepare_model_download`
    because a frozen windowed build has no stderr and printing to it crashed
    the first-run download outright -- so hooking it back up is not available.

    Polling `.incomplete` files costs a directory walk and touches nothing the
    download depends on. It matters because the alternative is what shipped:
    640 MB with the word "Downloading" and no number, on a first run, which is
    indistinguishable from a hang and is the most likely moment for someone to
    decide the product is broken and close it.

    Returns (0, expected) when nothing is in flight, so a caller can show the
    size before anything starts.
    """
    expected = float(getattr(model, "size_mb", 0) or 0)
    try:
        from huggingface_hub.constants import HF_HUB_CACHE

        cache = Path(HF_HUB_CACHE)
        if not cache.is_dir():
            return 0.0, expected
        # Every partial in the cache, not just this model's. Filtering by repo
        # was tried and does not work: `engine_id` is "nemo-parakeet-tdt-0.6b-v3"
        # while the cache folder is "models--istupakov--parakeet-tdt-0.6b-v3-onnx",
        # so the filter matched nothing and the progress stayed at zero.
        #
        # Counting everything is right for the case this exists to serve -- one
        # model downloading on first run. Two at once would over-report, which
        # is a bar that moves too fast rather than one that looks stuck, and the
        # second is the failure worth avoiding.
        fetched = 0
        for part in cache.rglob("*.incomplete"):
            try:
                fetched += part.stat().st_size
            except OSError:
                continue
        return fetched / 1048576.0, expected
    except Exception:
        log.debug("could not read download progress", exc_info=True)
        return 0.0, expected


def _load_onnx_asr(model: LocalModel, gpu: bool = False) -> Any:
    _prepare_model_download()
    try:
        import onnx_asr
    except importlib.metadata.PackageNotFoundError as exc:
        raise LocalSTTError(
            "The packaged local-speech runtime is incomplete. Update Talk DAT! and try the model download again."
        ) from exc
    except ImportError as exc:
        raise LocalSTTError(
            "Local models need the onnx-asr package. Install with: pip install \"onnx-asr[cpu,hub]\""
        ) from exc
    target = resolved_model_dir(model)
    target.parent.mkdir(parents=True, exist_ok=True)
    quantization = "int8" if model.engine_id.startswith(("nemo-", "istupakov/")) else None
    providers = _gpu_providers() if gpu else None
    if providers:
        # X-408: the same graph, on the GPU. Loading fails on a machine whose
        # driver cannot host it; the CPU path below is the answer then.
        try:
            import onnxruntime

            session_options = onnxruntime.SessionOptions()
            session_options.intra_op_num_threads = cpu_inference_budget()
            engine = onnx_asr.load_model(
                model.engine_id,
                str(target),
                quantization=quantization,
                providers=providers,
                sess_options=session_options,
            )
            _GPU_ENGINE_IDS.add(id(engine))
            log.info("local model %s loaded on %s", model.id, providers[0])
            return engine
        except Exception:
            log.warning("GPU load of %s failed; using the CPU", model.id, exc_info=True)
            providers = None
    kwargs: dict[str, Any] = {"quantization": quantization}
    if providers:
        kwargs["providers"] = providers
    try:
        import onnxruntime

        # X-107: onnxruntime defaults intra-op threads to EVERY core, which is
        # the "freezes up people's CPU" complaint verbatim. Same budget as the
        # Whisper engines: half the machine, capped at 4.
        session_options = onnxruntime.SessionOptions()
        session_options.intra_op_num_threads = cpu_inference_budget()
        kwargs["sess_options"] = session_options
    except Exception:
        log.debug("could not cap onnx inference threads", exc_info=True)
    try:
        return onnx_asr.load_model(model.engine_id, str(target), **kwargs)
    except Exception:
        if providers:
            kwargs.pop("providers", None)
            return onnx_asr.load_model(model.engine_id, str(target), **kwargs)
        raise


def _nvidia_library_dirs() -> list[str]:
    """The bin directories inside the nvidia-* pip wheels, if they are here.

    Returns nothing on the overwhelming majority of installs, which never
    carry them, and that is the quiet path.
    """
    found: list[str] = []
    # X-476: the app's own copy first. A frozen build has no site-packages, so
    # this is where a person who asked for the CUDA runtime actually has it.
    try:
        from . import cuda_runtime
        found.extend(cuda_runtime.library_dirs())
    except Exception:
        log.debug("cuda_runtime unavailable", exc_info=True)
    try:
        import nvidia
    except Exception:
        return found
    # A namespace package: no __file__, and possibly several roots.
    for root in getattr(nvidia, "__path__", []) or []:
        for name in ("cublas", "cudnn"):
            candidate = Path(root) / name / "bin"
            if candidate.is_dir():
                found.append(str(candidate))
    return found


def make_cuda_libraries_reachable() -> None:
    """Put the CUDA wheel directories on PATH before an engine loads.

    X-475, and the reason is pure Windows. `nvidia-cublas-cu12` and
    `nvidia-cudnn-cu12` are ordinary pip wheels that drop cublas64_12.dll into
    site-packages, which is on no DLL search path. `os.add_dll_directory()` is
    the obvious answer and DOES NOT WORK: it only helps a loader that opts in
    with LOAD_LIBRARY_SEARCH_USER_DIRS, and CTranslate2 asks for cuBLAS by bare
    name. So 98 MB of DLL sits on disk while the error reads "not found or
    cannot be loaded". PATH is what works; verified on the real engine.

    Timing matters: CTranslate2 resolves cuBLAS on the FIRST INFERENCE and
    reads PATH then, so this runs before the model is built.

    Idempotent, because it runs before every GPU load and PATH has a length
    limit that enough dictations would otherwise find.
    """
    directories = _nvidia_library_dirs()
    if not directories:
        return
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    added = [d for d in directories if d not in parts]
    if not added:
        return
    os.environ["PATH"] = os.pathsep.join(added + parts) if parts else os.pathsep.join(added)
    # Registered as well, for any loader that DOES opt into user directories.
    # Harmless where it is not enough, which is the case that started this.
    for directory in added:
        try:
            os.add_dll_directory(directory)
        except (OSError, AttributeError):
            pass


def _load_faster_whisper(model: LocalModel, gpu: bool = False) -> Any:
    _prepare_model_download()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise LocalSTTError(
            "Local Whisper models need the faster-whisper package. Install with: pip install faster-whisper"
        ) from exc
    target = resolved_model_dir(model)
    target.mkdir(parents=True, exist_ok=True)
    # "auto" was the default here and it broke every Whisper-family model on
    # any machine without the CUDA runtime -- which is most Windows PCs.
    #
    # The trap is that auto-detection LIES and the lie surfaces late.
    # `ctranslate2.get_cuda_device_count()` returns 1 on this hardware (an
    # Intel iGPU, no CUDA at all), so "auto" selects cuda, the model LOADS
    # without complaint, and the failure only arrives at the first
    # transcription as `RuntimeError: Library cublas64_12.dll is not found`.
    # The try/except below never fired because loading was never what failed.
    #
    # So the device is now explicit: CPU unless GPU was actually asked for.
    # A machine with working CUDA loses nothing -- it turns GPU on in
    # Settings and takes the branch above -- and a machine without it gets a
    # model that runs instead of one that raises.
    # X-451: CTranslate2 has no Metal backend, so on a Mac "gpu" can only mean
    # a CUDA request that fails with a traceback in the log at every warm
    # ("This CTranslate2 package was not compiled with CUDA support") before
    # the CPU fallback below runs. Ask for the CPU there in the first place.
    device = "cuda" if gpu and sys.platform != "darwin" else "cpu"
    if device == "cuda":
        # X-475: before the model is built, because CTranslate2 resolves
        # cuBLAS on first inference and reads PATH at that moment.
        make_cuda_libraries_reachable()
    # X-237: download the exact commit, not whatever `main` says today.
    # None for a custom model the user added -- see _PINNED_REVISIONS.
    revision = pinned_revision(model)
    try:
        return WhisperModel(
            model.engine_id,
            device=device,
            compute_type="int8",
            download_root=str(target),
            cpu_threads=cpu_inference_budget(),
            num_workers=1,
            revision=revision,
        )
    except Exception:
        if gpu:
            # Asked for GPU, could not have it. CPU is slower and correct;
            # refusing to transcribe is neither.
            log.warning("GPU load failed for %s; falling back to CPU", model.id, exc_info=True)
            return WhisperModel(
                model.engine_id,
                device="cpu",
                compute_type="int8",
                download_root=str(target),
                cpu_threads=cpu_inference_budget(),
                num_workers=1,
                revision=revision,
            )
        raise


def ensure_loaded(model: LocalModel, status_cb: StatusCallback | None = None, *, gpu: bool = False) -> Any:
    cache_key = f"{model.id}:gpu" if gpu else model.id
    with _ENGINE_LOCK:
        engine = _ENGINES.get(cache_key)
        if engine is not None and is_downloaded(model):
            return engine
        if engine is not None:
            _ENGINES.pop(cache_key, None)
        target = model_dir(model)
        payload_present = (target / READY_MARKER).is_file() and _payload_looks_complete(model, target)
        ready = is_downloaded(model)
        if status_cb:
            status_cb("loading_model" if ready or payload_present else "downloading_model")
        # onnx-asr treats every existing directory as offline-only. Remove an
        # empty or interrupted payload so its resolver can create the directory
        # and perform a real Hub download on this attempt.
        if target.exists() and not payload_present:
            shutil.rmtree(target, ignore_errors=True)
        if model.engine == "onnx_asr":
            engine = _load_onnx_asr(model, gpu)
        elif model.engine == "faster_whisper":
            engine = _load_faster_whisper(model, gpu)
        else:
            raise LocalSTTError(f"Unknown local engine: {model.engine}")
        if status_cb:
            status_cb("verifying_model")
        target = model_dir(model)
        if not _payload_looks_complete(model, target):
            raise LocalSTTError(
                f"{model.label} did not finish downloading. Check the connection and choose Download again."
            )
        _write_ready_manifest(model, target)
        _ENGINES[cache_key] = engine
        if status_cb:
            status_cb("model_ready")
        return engine


def download_model(model: LocalModel, status_cb: StatusCallback | None = None) -> None:
    ensure_loaded(model, status_cb)


def _pcm16_to_float32(pcm16: bytes, channels: int) -> Any:
    import numpy as np

    audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        usable = len(audio) - (len(audio) % channels)
        audio = audio[:usable].reshape(-1, channels).mean(axis=1)
    return audio


# X-409: Parakeet v3 transcribes 24 minutes in one call (model card), and a
# minute of speech through the old 25 s VAD chain cost 16 to 20 s on the GPU
# against 2.25 s in one call, because onnx-asr's defaults cut it into 2.4 s
# fragments and every fragment is a full encoder launch. Above this many
# seconds the VAD chain still takes over, asked for long segments; it is also
# the window size of the chunked fallback when the VAD chain fails.
_ONNX_UTTERANCE_CAP_S = 150


# Segments of up to a minute, closed on real pauses: the same run of speech
# reaches the model in a handful of calls instead of dozens.
_VAD_OPTIONS = {"max_speech_duration_s": 60, "min_silence_duration_ms": 600}


def _run(engine: Any, call: Callable[[], Any]) -> Any:
    """One GPU run at a time; the CPU engines need no gate."""
    if not is_gpu_engine(engine):
        return call()
    with _GPU_RUN_LOCK:
        return call()


def word_confidence(result: Any) -> dict[str, float]:
    """X-608: how sure the recognizer was of each word it wrote.

    onnx_asr's timestamped result carries one log-probability per token. A
    token that begins with a space begins a word; a word's confidence is its
    least certain letter-bearing token (a trailing "?" is not the word). Keys
    are the word in lower case, letters and apostrophes only, and a word said
    twice keeps its lower score. Numbers are left out: nothing repairs them.
    """
    import math

    tokens = list(getattr(result, "tokens", None) or [])
    logprobs = list(getattr(result, "logprobs", None) or [])
    words: dict[str, float] = {}
    spelled, lowest = "", 1.0

    def close() -> None:
        key = "".join(ch for ch in spelled.lower() if ch.isalpha() or ch == "'").strip("'")
        if key:
            words[key] = min(lowest, words.get(key, lowest))

    for token, logprob in zip(tokens, logprobs):
        token = str(token)
        if token.startswith((" ", "▁")):
            close()
            spelled, lowest = "", 1.0
        spelled += token
        if any(ch.isalpha() for ch in token):
            try:
                lowest = min(lowest, math.exp(float(logprob)))
            except (TypeError, ValueError, OverflowError):
                pass
    close()
    return words


def _merge_confidence(into: dict[str, float] | None, heard: dict[str, float]) -> None:
    if into is not None:
        for word, value in heard.items():
            into[word] = min(value, into.get(word, value))


def _recognize_once(engine: Any, audio: Any, sample_rate: int, confidence: dict[str, float] | None) -> str:
    """One recognition; with `confidence`, also how sure it was of each word.

    The timestamped call is the same decode asking for log-probabilities as
    well, so it costs nothing measurable (2026-09-24: 0.26 s either way once
    warm). An engine without it -- a test double, an older onnx_asr -- answers
    the plain way and simply reports no confidence.
    """
    stamped = getattr(engine, "with_timestamps", None) if confidence is not None else None
    if callable(stamped):
        result = stamped().recognize(audio, sample_rate=sample_rate)
        _merge_confidence(confidence, word_confidence(result))
        return result if isinstance(result, str) else str(getattr(result, "text", "") or "")
    result = engine.recognize(audio, sample_rate=sample_rate)
    return result if isinstance(result, str) else str(getattr(result, "text", "") or "")


def _recognize_onnx(engine: Any, audio: Any, sample_rate: int,
                    confidence: dict[str, float] | None = None) -> str:
    # Models cap out around 20-30s per utterance; chain VAD for longer takes.
    if len(audio) > sample_rate * _ONNX_UTTERANCE_CAP_S:
        try:
            import onnx_asr

            vad = onnx_asr.load_vad("silero")
            chain = engine.with_vad(vad, **_VAD_OPTIONS)
            if confidence is not None and callable(getattr(chain, "with_timestamps", None)):
                chain = chain.with_timestamps()
            results = _run(engine, lambda: list(chain.recognize(audio, sample_rate=sample_rate)))
            parts = []
            for result in results:
                if confidence is not None:
                    _merge_confidence(confidence, word_confidence(result))
                text = getattr(result, "text", result)
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            if parts:
                return " ".join(parts)
        except Exception:
            # This used to be contextlib.suppress plus one bare recognize of
            # the whole recording. The bare call does receive the full audio,
            # but the model truncates past its ~25s cap -- the exact reason
            # the VAD chain exists -- so a long dictation silently kept only
            # its head, with nothing in the log. Log the failure and chunk
            # the fallback so every second of audio reaches the engine.
            log.warning(
                "VAD chain failed for a %.1fs recording; falling back to fixed %ds chunks",
                len(audio) / sample_rate,
                _ONNX_UTTERANCE_CAP_S,
                exc_info=True,
            )
            return _recognize_onnx_chunked(engine, audio, sample_rate, confidence)
    if is_gpu_engine(engine) and len(audio):
        import numpy as np

        seconds = len(audio) / sample_rate
        target = int(padded_seconds(seconds) * sample_rate)
        if target > len(audio):
            audio = np.pad(audio, (0, target - len(audio)))
    return _run(engine, lambda: _recognize_once(engine, audio, sample_rate, confidence))


def _recognize_onnx_chunked(engine: Any, audio: Any, sample_rate: int,
                            confidence: dict[str, float] | None = None) -> str:
    """Fallback for long recordings when the VAD chain is unavailable.

    Fixed windows can split a word at a boundary; losing everything past the
    model's utterance cap loses the entire tail. The former is the far
    smaller harm, and this path only runs after the VAD chain has already
    failed (and been logged).
    """
    window = sample_rate * _ONNX_UTTERANCE_CAP_S
    parts = []
    for start in range(0, len(audio), window):
        text = _recognize_once(engine, audio[start : start + window], sample_rate, confidence)
        if text.strip():
            parts.append(text.strip())
    return " ".join(parts)


def _recognize_faster_whisper(
    engine: Any, audio: Any, language: str, task: str = "", *, vocabulary: tuple[str, ...] = (),
) -> str:
    lang = language.split("-")[0].lower() if language else None
    kwargs: dict[str, Any] = {"language": lang or None, "vad_filter": True}
    if vocabulary:
        from .recognition_bias import clean_terms
        terms = clean_terms(vocabulary)
        if terms:
            kwargs["hotwords"] = ", ".join(terms)
    if task == "translate":
        kwargs["task"] = "translate"
        kwargs["language"] = None
    segments, _info = engine.transcribe(audio, **kwargs)
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip())


def cpu_inference_budget() -> int:
    """How many cores on-device transcription is ALLOWED to take.

    X-107: a local fallback saturated every core the moment it started --
    "it should not freeze up people's CPU". Half the machine's threads is
    the ceiling that keeps the machine usable.

    X-338, his order: local was "extraordinarily slow ... almost
    unusable". The cap rises to 6 (a 12-thread desktop now gets 6 instead
    of 4) -- still half, still bounded, roughly 1.5x the throughput on the
    machines that need it most.
    """
    return max(2, min(6, (os.cpu_count() or 4) // 2))


def _yield_cpu_to_the_foreground() -> None:
    """Run THIS thread below normal priority while it does inference.

    The thread cap bounds how much CPU transcription can take; priority
    bounds who wins when it and the person's actual work want the same
    cores. Windows-only by design; elsewhere it is a no-op.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        THREAD_PRIORITY_BELOW_NORMAL = -1
        kernel32 = ctypes.windll.kernel32
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL)
    except Exception:
        log.debug("could not lower inference thread priority", exc_info=True)


_CUDA_IS_A_LIE = False


def _remember_broken_cuda() -> None:
    """Record that this machine's CUDA cannot actually run inference.

    Session-scoped on purpose. A person who installs the CUDA runtime and
    restarts gets the GPU back without us having written anything to their
    disk about it, and a wrong guess costs one dictation rather than a
    permanent downgrade written into their config.
    """
    global _CUDA_IS_A_LIE
    _CUDA_IS_A_LIE = True


def forget_broken_cuda() -> None:
    """Clear that memory. For tests, and for a deliberate re-probe."""
    global _CUDA_IS_A_LIE
    _CUDA_IS_A_LIE = False


def cuda_is_known_broken() -> bool:
    return _CUDA_IS_A_LIE


def transcribe(
    *,
    model_id: str,
    pcm16: bytes,
    sample_rate: int,
    channels: int,
    language: str,
    gpu: bool = False,
    task: str = "",
    status_cb: StatusCallback | None = None,
    vocabulary: tuple[str, ...] = (),
    word_confidence: dict[str, float] | None = None,
) -> str:
    """Local speech to text. With `word_confidence` (a dict to fill), the
    Parakeet path also records how sure it was of each word (X-608)."""
    model = local_model_for_id(model_id)
    # X-473: once CUDA has proved it cannot run here, stop paying for it. The
    # attempt costs a model load and a failure on every dictation otherwise.
    if gpu and model.engine == "faster_whisper" and cuda_is_known_broken():
        gpu = False
    engine = ensure_loaded(model, status_cb, gpu=gpu)
    if status_cb:
        status_cb("transcribing")
    # X-338: NO below-normal priority for a user-invoked dictation. The
    # person is actively waiting for these words -- this IS the foreground
    # work. Under real desktop load, below-normal threads starve for whole
    # seconds, which read as "the local model is unusable". The thread cap
    # above remains the machine-stays-usable guarantee (X-107); priority
    # is no longer sacrificed on top of it.
    audio = _pcm16_to_float32(pcm16, max(1, channels))
    if model.engine == "onnx_asr":
        from .recognition_bias import with_transducer_bias
        adapted = with_transducer_bias(engine, vocabulary)
        registered = adapted is not engine and is_gpu_engine(engine)
        if registered:
            _GPU_ENGINE_IDS.add(id(adapted))
        try:
            return _recognize_onnx(adapted, audio, sample_rate, word_confidence)
        finally:
            if registered:
                _GPU_ENGINE_IDS.discard(id(adapted))
    hints = {"vocabulary": vocabulary} if vocabulary else {}
    try:
        return _recognize_faster_whisper(engine, audio, language, task, **hints)
    except Exception:
        # X-473: THE CUDA FALLBACK, in the only place it can work.
        #
        # `_load_faster_whisper` already tries CUDA and falls back to CPU, and
        # that guard has never once fired. CTranslate2 loads lazily:
        # `get_cuda_device_count()` returns 1 on any machine with an NVIDIA
        # card, and WhisperModel(device="cuda") CONSTRUCTS there whether or not
        # the CUDA runtime libraries exist. The failure arrives on the first
        # inference -- "Library cublas64_12.dll is not found" -- by which point
        # the guard is long past.
        #
        # A CUDA DEVICE IS NOT A CUDA RUNTIME, and the gap is not exotic: it is
        # everyone who owns an NVIDIA card and has never installed the toolkit.
        # They turn GPU on expecting speed and every Whisper dictation fails.
        # Parakeet is untouched because onnx-asr goes through DirectML, which
        # is why this survived so long behind the default engine.
        if not gpu:
            raise
        _remember_broken_cuda()
        log.warning(
            "GPU inference failed for %s; retrying on the CPU and staying there",
            model.id, exc_info=True,
        )
        if status_cb:
            status_cb("transcribing")
        engine = ensure_loaded(model, status_cb, gpu=False)
        return _recognize_faster_whisper(engine, audio, language, task, **hints)
