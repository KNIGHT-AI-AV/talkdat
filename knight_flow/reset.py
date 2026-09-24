"""Start over, deliberately, and only as far as you meant to.

A reset button is easy to write and easy to get wrong, and the two failure
modes are not symmetric. Failing to delete something costs a second attempt.
Deleting more than was asked for costs work nobody can get back -- a dictionary
somebody spent months adding names to, or four gigabytes of models on a metered
connection.

So this module is built around three rules:

**Nothing is a single click.** Every category is opt-in, the destructive ones
start unchecked, and the caller has to ask for a preview before it will do
anything. The preview is the same code path as the deletion, so what it lists is
exactly what goes.

**The expensive-to-replace things are not "data".** Downloaded speech models are
gigabytes and re-downloading them can take an hour; the signed licence means
re-activating a PC and, on a one-device plan, possibly waiting for support. Both
are separated from ordinary settings and default to off, because "clear my
settings" almost never means "and make me set the machine up again".

**Say what it costs before it happens.** Each category reports its real size on
disk, so "Downloaded speech models (3.8 GB)" is a decision rather than a
checkbox.

Pure functions and plain paths. The confirmation dialog lives in overlay.py; the
only thing here that touches the disk is `perform`, and it is the last thing in
the file so it is easy to audit.
"""

from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import dataclass, field
from . import platform_copy
from pathlib import Path

from . import mac_support
from .credentials import delete_all_credentials
from typing import Callable

# How hard a category is to get back. Presets and the UI both key off this
# rather than off a hand-maintained list of names.
ORDINARY = "ordinary"          # settings and preferences; seconds to redo
PERSONAL = "personal"          # things the person authored; cannot be recreated
EXPENSIVE = "expensive"        # correct but slow or awkward to restore


@dataclass(frozen=True)
class ResetCategory:
    """One thing that can be cleared, and what clearing it actually costs.

    `paths` are deleted outright. `config_keys` are dotted paths pruned from
    config.json, because several of these -- dictionary, snippets, shortcuts --
    live inside the settings file rather than beside it, and a person asking to
    clear their snippets does not expect their hotkeys to go with them.
    """

    key: str
    label: str
    consequence: str
    weight: str
    paths: tuple[str, ...] = field(default=())
    config_keys: tuple[str, ...] = field(default=())

    @property
    def default_checked(self) -> bool:
        """Only the cheap-to-redo things are pre-selected."""
        return self.weight == ORDINARY


CATEGORIES: tuple[ResetCategory, ...] = (
    ResetCategory(
        "settings", "App settings",
        "Voice, writing, appearance, privacy and automation return to defaults. Saved provider keys are removed.",
        ORDINARY,
        # "deepgram" and "remote" are here because of what happens AFTER the
        # prune: any secret still sitting in the config in plaintext is written
        # back into the credential vault on save. Leave those two sections and
        # the reset deletes the legacy Deepgram key and the control-API token
        # from the vault, then immediately puts them both back.
        config_keys=(
            "cleanup", "dictation", "overlay", "hotkeys",
            "transforms", "stt", "audio", "deepgram", "remote",
            "ui", "privacy", "plugins", "wake_word", "meeting",
            "translation.enabled", "translation.auto_translate_dictation",
            "translation.bilingual_auto_detect", "translation.engine",
            "translation.source_language", "translation.target_language",
            "translation.model", "translation.api_base", "translation.timeout_seconds",
            "translation.formality", "translation.preserve_formatting",
            "diagnostics", "updates", "export", "telemetry",
        ),
    ),
    ResetCategory(
        "onboarding", "Onboarding progress",
        "The setup walkthrough runs again next launch.",
        ORDINARY,
        config_keys=("onboarding",),
    ),
    ResetCategory(
        "dictionary", "Custom words and phrases",
        "Every name, brand and pronunciation you taught it is forgotten.",
        PERSONAL,
        paths=("pronunciation",),
        config_keys=("dictionary", "translation.glossary"),
    ),
    ResetCategory(
        "snippets", "Snippets",
        "Saved snippets and their shortcuts are removed.",
        PERSONAL,
        config_keys=("snippets",),
    ),
    ResetCategory(
        "history", "Dictation history",
        "Past transcripts and the searchable history are erased.",
        PERSONAL,
        # X-195: this listed three of the six files that hold dictated text.
        # history.db is the SEARCHABLE history this category's own sentence
        # promises to erase; pinned.json is every transcript the user thought
        # worth keeping; formatting-journal.jsonl stores the raw AND finished
        # text of each dictation and had no delete path anywhere in the app.
        # A factory reset reported success and left all three on the disk.
        paths=(
            "history.jsonl",
            "history.db", "history.db-wal", "history.db-shm", "history.db-journal",
            "pinned.json",
            "formatting-journal.jsonl", "formatting-journal.jsonl.1",
            "full-transcript-history.txt",
            "live-transcript-draft.txt",
            # X-544: the crash-recovered copy of the live draft. Same words,
            # same category; a file the erase paths cannot see is X-195 again.
            "recovered-draft.txt",
        ),
    ),
    ResetCategory(
        "scratchpad", "Scratchpad notes",
        "All scratchpad tabs and their contents are deleted.",
        PERSONAL,
        # scratchpad.md is the pre-tabs single-note file. Installs that predate
        # tabs still carry it, and it still has the user's notes in it.
        paths=("scratchpad-tabs.json", "scratchpad.md"),
    ),
    ResetCategory(
        "voice_sessions", "Protected voice sessions",
        "Local recovery recordings are deleted. Copies you saved elsewhere are kept.",
        PERSONAL,
        paths=("audio-spool",),
    ),
    ResetCategory(
        "scribe", "Scribe recordings and notes",
        "Saved conversations, their audio and drafts, and older meeting notes are erased.",
        PERSONAL, paths=("scribe-recordings", "meetings"),
    ),
    ResetCategory(
        "profiles", "App preferences and learned style",
        "App-specific writing choices and learned style counts are removed.",
        PERSONAL, config_keys=("profiles", "style_profile"),
    ),
    ResetCategory(
        "exports", "Exports saved inside Talk DAT",
        "Exports in the app's own folder are erased. Copies saved elsewhere are kept.",
        PERSONAL, paths=("exports",),
    ),
    ResetCategory(
        "plugin_files", "Installed plugin files",
        "Local extension source files are removed. Plugin preferences are a separate setting.",
        PERSONAL, paths=("plugins",),
    ),
    ResetCategory(
        "models", "Downloaded speech models",
        "Offline dictation stops working until they download again, which can "
        "take a while on a slow connection.",
        EXPENSIVE,
        paths=("models",),
    ),
    ResetCategory(
        "account", "Sign-in and licence",
        f"{platform_copy.THIS_COMPUTER_SENTENCE} is signed out and must sign in again to sync preferences. "
        "Your account is not deleted -- it lives online, not on this machine. Dictation keeps working.",
        EXPENSIVE,
    ),
)

CATEGORY_BY_KEY = {category.key: category for category in CATEGORIES}

# Named starting points, because "everything except the slow bits" is what
# almost everybody actually wants and nobody wants to assemble from checkboxes.
PRESETS: dict[str, tuple[str, ...]] = {
    "settings_only": tuple(c.key for c in CATEGORIES if c.weight == ORDINARY),
    "keep_models_and_account": tuple(c.key for c in CATEGORIES if c.weight != EXPENSIVE),
    "everything_but_account": tuple(c.key for c in CATEGORIES if c.key != "account"),
    "everything": tuple(c.key for c in CATEGORIES),
}

PRESET_LABELS = {
    "settings_only": "Settings only",
    "keep_models_and_account": "All listed data, keep models and sign-in",
    "everything_but_account": "Everything except my sign-in",
    "everything": "All listed categories",
}


_DIRECTORIES = frozenset({"pronunciation", "audio-spool", "models",
    "scribe-recordings", "meetings", "exports", "plugins"})
_MAX_ENTRIES = 50_000
_SCAN_SECONDS = 8.0


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _stamp(path, relative):
    info = path.lstat()
    if _linked(info) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError("Reset cannot follow linked or special files. Restore regular local files first.")
    return (relative, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_mode, getattr(info, "st_file_attributes", 0))


def _inventory(path, root, deadline, entries):
    if time.monotonic() > deadline or len(entries) >= _MAX_ENTRIES:
        raise ValueError("There are too many files to preview safely. Clear a smaller category first.")
    try:
        entry = _stamp(path, str(path.relative_to(root)))
    except FileNotFoundError:
        return 0
    entries.append(entry)
    if stat.S_ISREG(entry[5]):
        return entry[3]
    total = 0
    with os.scandir(path) as children:
        for child in children:
            total += _inventory(Path(child.path), root, deadline, entries)
    return total


def _size_of(path):
    entries = []
    return _inventory(path, path.parent, time.monotonic() + _SCAN_SECONDS, entries)


def human_size(total: int) -> str:
    """Sizes people can act on. 3.8 GB is a decision; 4081745920 is not."""
    for unit, cutoff in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if total >= cutoff:
            return f"{total / cutoff:.1f} {unit}"
    return f"{total} bytes"


@dataclass(frozen=True)
class ResetPlan:
    """Exactly what would go, before anything does."""

    categories: tuple[ResetCategory, ...]
    files: tuple[Path, ...]
    config_keys: tuple[str, ...]
    bytes_freed: int
    root: Path
    root_identity: tuple
    entries: tuple

    @property
    def touches_account(self) -> bool:
        return any(category.key == "account" for category in self.categories)

    @property
    def is_empty(self) -> bool:
        return not self.categories


def plan(selected: list[str] | tuple[str, ...], data_dir: Path) -> ResetPlan:
    """Work out what clearing these categories would remove.

    Unknown keys are ignored rather than raising. A stale preset or a renamed
    category should cost a missing checkbox, never a crash in the one dialog
    somebody opened because something was already wrong.
    """
    if not isinstance(selected, (list, tuple)) or any(type(key) is not str for key in selected):
        raise ValueError("Choose the reset categories again.")
    root = Path(data_dir).absolute()
    root_info = root.lstat()
    if _linked(root_info) or not stat.S_ISDIR(root_info.st_mode):
        raise ValueError("Reset needs a regular local app folder.")
    chosen = [CATEGORY_BY_KEY[key] for key in dict.fromkeys(selected) if key in CATEGORY_BY_KEY]
    files, keys, entries = [], [], []
    total = 0
    deadline = time.monotonic() + _SCAN_SECONDS
    for category in chosen:
        for name in category.paths:
            path = root / name
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if _linked(info) or (stat.S_ISDIR(info.st_mode) != (name in _DIRECTORIES)):
                raise ValueError("A reset item is linked or has an unexpected file type. Nothing was erased.")
            files.append(path)
            total += _inventory(path, root, deadline, entries)
        keys.extend(category.config_keys)
    return ResetPlan(tuple(chosen), tuple(files), tuple(dict.fromkeys(keys)), total,
                     root, (root_info.st_dev, root_info.st_ino), tuple(sorted(entries)))


def category_size(key: str, data_dir: Path) -> int:
    """What one category occupies, for the label beside its checkbox."""
    return plan([key], data_dir).bytes_freed


def prune_config(config: dict, keys: tuple[str, ...]) -> dict:
    """Remove the selected sections so defaults are re-applied on next load.

    Returns a new dict. The original is left alone because the caller may still
    need it if writing the pruned copy fails -- a half-cleared settings file is
    worse than an uncleared one.
    """
    remaining = json.loads(json.dumps(config))
    for key in keys:
        node = remaining
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.get(part) if isinstance(node.get(part), dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(parts[-1], None)
    return remaining


def _check_parents(path, intended):
    root = intended.root
    info = root.lstat()
    if _linked(info) or (info.st_dev, info.st_ino) != intended.root_identity:
        raise ValueError("The app folder changed. Preview the reset again.")
    for parent in reversed(path.relative_to(root).parents):
        if str(parent) == ".":
            continue
        info = (root / parent).lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("A reset folder changed. Preview the reset again.")


def perform(
    selected: list[str] | tuple[str, ...],
    data_dir: Path,
    *,
    read_config: Callable[[], dict],
    write_config: Callable[[dict, tuple[str, ...]], None],
    forget_license: Callable[[], bool] | None = None,
    expected: ResetPlan | None = None,
) -> dict:
    """Delete only a freshly checked preview, reporting actual successful removals.

    The UI stops capture and writers before calling this. Selected categories
    are fixed here; new or replaced files invalidate a supplied preview. Directory
    removal uses only its enumerated entries and refuses new children rather
    than recursively deleting data that was not in that preview.
    """
    intended = plan(selected, data_dir)
    if expected is not None and intended != expected:
        raise ValueError("The selected data changed. Preview the reset again.")
    removed, failed = [], []
    freed = 0
    entries = {entry[0]: entry for entry in intended.entries}
    for path in intended.files:
        name = str(path.relative_to(intended.root))
        members = [value for key, value in entries.items()
                   if key == name or Path(name) in Path(key).parents]
        members.sort(key=lambda item: len(Path(item[0]).parts), reverse=True)
        complete = True
        for entry in members:
            target = intended.root / entry[0]
            try:
                _check_parents(target, intended)
                actual = _stamp(target, entry[0])
                # A directory mtime changes as its own children are removed.
                if stat.S_ISDIR(entry[5]):
                    if actual[1:3] != entry[1:3] or not stat.S_ISDIR(actual[5]):
                        raise ValueError("The reset folder changed.")
                    target.rmdir()
                else:
                    if actual != entry:
                        raise ValueError("The reset file changed.")
                    target.unlink()
                    freed += entry[3]
            except FileNotFoundError:
                continue
            except Exception:
                complete = False
        (removed if complete else failed).append(path.name)

    if intended.config_keys:
        try:
            current = read_config()
            forget = tuple(key for key in intended.config_keys if "." not in key)
            write_config(prune_config(current, intended.config_keys), forget)
            removed.extend(intended.config_keys)
            if any(category.key == "settings" for category in intended.categories):
                try:
                    if not delete_all_credentials(current, include_license=intended.touches_account):
                        failed.append("saved keys")
                except Exception:
                    failed.append("saved keys")
        except Exception:
            failed.extend(intended.config_keys)

    if intended.touches_account:
        try:
            if forget_license is not None and forget_license():
                removed.append("sign-in")
            else:
                failed.append("sign-in")
        except Exception:
            failed.append("sign-in")

    return {"removed": removed, "failed": failed, "bytes_freed": freed,
            "restart_required": bool(intended.config_keys) or intended.touches_account}
