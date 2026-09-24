"""X-35: the pronunciation trainer. Say it three times; it works forever.

Mayowa's requirement, and the trick that makes it survive engine switches:
the correction layer is DOWNSTREAM of transcription, so what the trainer
really needs is "what does the current model hear when this person says the
word". So the app keeps the person's three tiny recordings LOCALLY, runs
them through whatever engine is active to harvest its actual mishearings as
sounds-like aliases -- and whenever the engine changes, silently re-runs the
same clips through the new one and refreshes the aliases. Any model,
automatically, no cloud required, nothing ever uploaded.
"""

from __future__ import annotations

import json
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("talkdat.pronunciation")

CLIPS_PER_TERM = 3
MAX_ALIASES = 6


def term_slug(text: str) -> str:
    canonical = str(text or '').strip().casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", canonical).strip("-")[:36] or 'term'
    return slug + '-' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]


def clips_root(config: dict[str, Any]) -> Path:
    from .config import config_path

    return config_path().parent / "pronunciation"


def clips_dir(config: dict[str, Any], term_text: str) -> Path:
    root = clips_root(config)
    current = root / term_slug(term_text)
    if current.exists(): return current
    # Existing recordings remain readable. Reuse an old ambiguous slug only
    # when its metadata proves that it belongs to this exact spelling.
    old_slug = re.sub(r'[^a-z0-9]+', '-', str(term_text or '').lower()).strip('-')[:48] or 'term'
    legacy = root / old_slug
    try:
        spelling = json.loads((legacy / 'term.json').read_text(encoding='utf-8'))['text']
        if str(spelling).strip().casefold() == str(term_text).strip().casefold(): return legacy
    except (OSError, ValueError, KeyError, TypeError): pass
    return current


def store_clip(config: dict[str, Any], term_text: str, index: int, wav_bytes: bytes) -> Path:
    folder = clips_dir(config, term_text)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"take-{int(index)}.wav"
    path.write_bytes(wav_bytes)
    # The canonical spelling rides beside the audio, so a slugged folder can
    # always be traced back to the exact dictionary entry it trains.
    (folder / "term.json").write_text(
        json.dumps({"text": str(term_text)}), encoding="utf-8"
    )
    return path


def stored_terms(config: dict[str, Any]) -> list[str]:
    root = clips_root(config)
    if not root.exists():
        return []
    out = []
    for folder in sorted(root.iterdir()):
        meta = folder / "term.json"
        if meta.is_file():
            try:
                out.append(str(json.loads(meta.read_text(encoding="utf-8"))["text"]))
            except Exception:
                continue
    return out


def harvest_aliases(
    config: dict[str, Any],
    term_text: str,
    transcribe: Callable[[Path], str],
) -> list[str]:
    """What the current engine hears for each stored take.

    Distinct, lowercased, never the correct spelling itself (a heard-right
    take teaches nothing), never empty, capped. The transcribe callable is
    whatever engine is active -- that indirection is the whole feature.
    """
    folder = clips_dir(config, term_text)
    if not folder.exists():
        return []
    heard: list[str] = []
    seen: set[str] = set()
    correct = str(term_text).lower().strip()
    for take in sorted(folder.glob("take-*.wav")):
        try:
            text = str(transcribe(take) or "").strip().lower()
        except Exception:
            log.debug("pronunciation take failed to transcribe", exc_info=True)
            continue
        text = ''.join(character for character in text if character.isalnum() or character.isspace() or character in "'-").strip()
        if not text or text == correct or text in seen:
            continue
        seen.add(text)
        heard.append(text)
    return heard[:MAX_ALIASES]


def refresh_term_aliases(
    config: dict[str, Any],
    transcribe: Callable[[Path], str],
) -> int:
    """Re-derive sounds_like for every trained term -- the engine-switch hook.

    Trained aliases REPLACE previously trained ones but merge with anything
    the user typed by hand before the trainer existed; hand-typed entries are
    not ours to delete. Returns how many terms changed.
    """
    dictionary = config.setdefault("dictionary", {})
    terms = dictionary.setdefault("terms", [])
    trained = {term_slug(text): text for text in stored_terms(config)}
    if not trained:
        return 0
    changed = 0
    by_slug = {term_slug(str(entry.get("text", ""))): entry for entry in terms if isinstance(entry, dict)}
    for slug, text in trained.items():
        from .learned_words import tombstoned
        if tombstoned(text, config): continue
        fresh = harvest_aliases(config, text, transcribe)
        entry = by_slug.get(slug)
        if entry is None:
            entry = {"text": text, "sounds_like": []}
            terms.append(entry)
            by_slug[slug] = entry
        existing = entry.get("sounds_like") or []
        if isinstance(existing,str):existing=[existing]
        existing = [str(v) for v in existing]
        hand_typed = [v for v in existing if not entry.get("trained_aliases") or v not in entry.get("trained_aliases", [])]
        merged = list(dict.fromkeys(hand_typed + fresh))[: MAX_ALIASES + 2]
        if merged != existing or entry.get("trained_aliases") != fresh:
            entry["sounds_like"] = merged
            entry["trained_aliases"] = fresh
            changed += 1
    return changed
