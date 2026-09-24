"""Shared dictionary/snippet packs and settings backup.

Packs are plain JSON ({"name", "dictionary": {"words", "replacements"}, "snippets"})
so teams can share vocabulary without any server. Backups are ZIP files of the
local AppData content; they contain API keys, so treat them like secrets.
"""

from __future__ import annotations

import json
import copy
import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from .config import app_dir, config_path


PACK_VERSION = 1
from .backups import BACKUP_FILES, export_backup, inspect_backup, restore_backup

# A diagnostics ZIP is something a user emails to support, so the redaction has to
# cover any field that could hold a secret rather than only the names in use today.
SECRET_FIELD_MARKERS = (
    "key",
    "token",
    "secret",
    "password",
    "passphrase",
    "credential",
    "auth",
    "bearer",
    "signature",
    "private",
)


# Names that contain a marker as a substring but never hold a credential. Without
# this, "hotkeys" matches "key" and the hotkey configuration -- the single most
# useful thing in a support bundle -- gets blanked out.
SAFE_FIELDS = frozenset(
    {"hotkeys", "hotkey", "keys", "keyboard", "keymap", "keyterm", "keyterms", "keywords", "author"}
)


def is_secret_field(name: str) -> bool:
    """True when a config field name suggests it holds a credential."""
    lowered = str(name).lower()
    if lowered in SAFE_FIELDS:
        return False
    return any(marker in lowered for marker in SECRET_FIELD_MARKERS)


def export_pack(config: dict[str, Any], path: Path | str) -> Path:
    path = Path(path)
    pack = {
        "talkdat_pack": PACK_VERSION,
        "name": path.stem,
        "exported_at": time.strftime("%Y-%m-%d %H:%M"),
        "dictionary": {
            "words": list(config.get("dictionary", {}).get("words", [])),
            "terms": copy.deepcopy(config.get("dictionary", {}).get("terms", [])),
            "replacements": list(config.get("dictionary", {}).get("replacements", [])),
        },
        "snippets": list(config.get("snippets", [])),
    }
    encoded = json.dumps(pack, indent=2, ensure_ascii=False, allow_nan=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def import_pack(config: dict[str, Any], path: Path | str) -> dict[str, int]:
    path = Path(path)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('Choose a vocabulary pack smaller than 8 MB.')
    with path.open('rb') as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Choose a vocabulary pack smaller than 8 MB.')
    def invalid_constant(value):raise ValueError('The vocabulary pack contains an invalid number.')
    data = json.loads(raw.decode('utf-8-sig'), parse_constant=invalid_constant)
    if not isinstance(data, dict) or "talkdat_pack" not in data:
        raise ValueError("Not a Talk DAT! pack file.")
    if type(data['talkdat_pack']) is not int or data['talkdat_pack'] != PACK_VERSION:
        raise ValueError('This vocabulary pack uses an unsupported version.')
    source = data.get('dictionary', {})
    if type(source) is not dict:
        raise ValueError('The vocabulary pack has an invalid dictionary.')
    for values in (source.get('words', []), source.get('terms', []), source.get('replacements', []), data.get('snippets', [])):
        if type(values) is not list or len(values) > 5000:
            raise ValueError('The vocabulary pack has an invalid or oversized collection.')
    # Validate and merge in isolation. A malformed later collection cannot leave
    # an earlier collection half imported in the live configuration.
    candidate = copy.deepcopy(config)
    dictionary = candidate.setdefault("dictionary", {})
    words = dictionary.setdefault("words", [])
    terms = dictionary.setdefault('terms', [])
    replacements = dictionary.setdefault("replacements", [])
    snippets = candidate.setdefault("snippets", [])

    added = {"words": 0, "replacements": 0, "snippets": 0}
    known_words = {str(word).strip().casefold() for word in words}
    known_words.update(str(item.get('text', '')).strip().casefold() for item in terms if isinstance(item, dict))
    incoming_terms = {item['text'].strip().casefold() for item in source.get('terms', [])
                      if isinstance(item,dict) and isinstance(item.get('text'),str)}
    for word in data.get("dictionary", {}).get("words", []):
        if type(word) is not str or len(word) > 512 or '\x00' in word:
            raise ValueError('The vocabulary pack contains an invalid word.')
        if word.strip() and word.strip().casefold() not in known_words and word.strip().casefold() not in incoming_terms:
            words.append(word.strip())
            known_words.add(word.strip().casefold())
            added["words"] += 1
    for item in source.get('terms', []):
        if type(item) is not dict or type(item.get('text')) is not str or not item['text'].strip() or len(item['text']) > 512 or '\x00' in item['text']:
            raise ValueError('The vocabulary pack contains an invalid pronunciation.')
        aliases = item.get('sounds_like', [])
        if type(aliases) is str: aliases = [aliases]
        if type(aliases) is not list or len(aliases) > 8 or any(type(alias) is not str or len(alias) > 512 or '\x00' in alias for alias in aliases):
            raise ValueError('The vocabulary pack contains invalid sounds-like spellings.')
        trained = item.get('trained_aliases', [])
        if type(trained) is not list or len(trained) > 8 or any(type(alias) is not str or len(alias) > 512 for alias in trained):
            raise ValueError('The vocabulary pack contains invalid trained spellings.')
        if item['text'].strip().casefold() not in known_words:
            terms.append({**copy.deepcopy(item), 'text':item['text'].strip(), 'sounds_like':aliases})
            known_words.add(item['text'].strip().casefold()); added['words'] += 1
    known_sources = {str(item.get("from", "")).lower() for item in replacements if isinstance(item, dict)}
    for item in data.get("dictionary", {}).get("replacements", []):
        if isinstance(item, dict) and (type(item.get('from', '')) is not str or type(item.get('to', '')) is not str or len(item.get('from', '')) > 512 or len(item.get('to', '')) > 32000):
            raise ValueError('The vocabulary pack contains an invalid replacement.')
        if isinstance(item,dict) and ('\x00' in item.get('from','') or '\x00' in item.get('to','')):
            raise ValueError('The vocabulary pack contains an invalid replacement.')
        if isinstance(item, dict) and str(item.get("from", "")).strip() and str(item.get("from", "")).lower() not in known_sources:
            replacements.append({**copy.deepcopy(item), "from": str(item.get("from")), "to": str(item.get("to", ""))})
            added["replacements"] += 1
    known_triggers = {str(item.get("trigger", "")).lower() for item in snippets if isinstance(item, dict)}
    for item in data.get("snippets", []):
        if isinstance(item, dict) and (type(item.get('trigger', '')) is not str or type(item.get('text', '')) is not str or len(item.get('trigger', '')) > 512 or len(item.get('text', '')) > 32000):
            raise ValueError('The vocabulary pack contains an invalid snippet.')
        if isinstance(item,dict) and ('\x00' in item.get('trigger','') or '\x00' in item.get('text','') or type(item.get('enabled',True)) is not bool):
            raise ValueError('The vocabulary pack contains an invalid snippet.')
        if isinstance(item, dict) and str(item.get("trigger", "")).strip() and str(item.get("trigger", "")).lower() not in known_triggers:
            snippets.append(
                {
                    **copy.deepcopy(item),
                    "trigger": str(item.get("trigger")),
                    "text": str(item.get("text", "")),
                    "enabled": bool(item.get("enabled", True)),
                }
            )
            added["snippets"] += 1
    if len(words) + len(terms) > 5000 or len(replacements) > 5000 or len(snippets) > 5000:
        raise ValueError('This pack would exceed 5,000 entries in a collection. Remove unused entries first.')
    config.clear(); config.update(candidate)
    return added


def export_diagnostics() -> Path:
    """Diagnostics ZIP with a key-redacted config and basic environment info."""
    import platform
    import sys

    from .version import APP_VERSION

    root = app_dir()
    diagnostics = root / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    path = diagnostics / time.strftime("talk-dat-diagnostics-%Y%m%d-%H%M%S.zip")

    redacted = "{}"
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8-sig"))

        def scrub(node: Any) -> Any:
            if isinstance(node, dict):
                return {
                    key: ("[redacted]" if is_secret_field(key) else scrub(value))
                    for key, value in node.items()
                }
            if isinstance(node, list):
                return [scrub(item) for item in node]
            return node

        redacted = json.dumps(scrub(raw), indent=2)
    except (OSError, json.JSONDecodeError):
        pass

    info = "\n".join(
        [
            f"Talk DAT! v{APP_VERSION}",
            f"Python {sys.version}",
            f"Platform {platform.platform()}",
            f"AppData {root}",
            f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')}",
        ]
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("config.redacted.json", redacted)
        archive.writestr("environment.txt", info)
        log_path = root / "talk-dat.log"
        if log_path.exists():
            archive.write(log_path, "talk-dat.log")
    return path
