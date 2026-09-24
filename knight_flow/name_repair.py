"""Put back a name the recognizer was unsure of (commandments 6 and 7).

The speech model writes what it heard. A name it has not learned comes out as
the nearest spelling it can build -- "Kalen" for Kaelyn, "shivon" for Siobhan --
and the formatter cannot know better from the text alone. Two pieces of
evidence together make the repair safe:

1. The recognizer's own confidence in that word was low. local_stt records the
   probability of every word it writes; the pipeline receives the unsure ones
   as config["_asr_confidence"]. A word it heard clearly is never touched, so
   "we launched in 2026" never becomes "LinkedIn". Measured on this model
   (2026-09-24): misheard names score 0.33-0.55, ordinary words 0.99-1.0.
2. The word SOUNDS like a name the person gave us: a dictionary term, or a
   name on screen when screen context is on. "Sounds like" is a consonant
   skeleton after a few spelling-to-sound rules (Irish bh -> v and sio -> sh,
   ph -> f, a soft c -> s), so siobhan and shivon both read sh-v-n.

A skeleton of fewer than three sounds is never matched: "Loop" was measured
unsure (0.38) and a two-sound name like Lupe would have taken it. Two names
with one skeleton veto each other rather than one winning at random. Without
all of that, the text is left exactly as the recognizer and formatter wrote it.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

#: A word whose recognizer probability is below this is "unsure".
UNSURE = 0.6
#: Fewer sounds than this collide with half the language (vocabulary.py agrees).
MIN_SOUNDS = 3

_WORD = re.compile(r"\b([A-Za-z][A-Za-z'’-]*[A-Za-z]|[A-Za-z])\b")
_SOUND_RULES = (
    ("sio", "sh"), ("sch", "sh"), ("bh", "v"), ("mh", "v"), ("ph", "f"),
    ("ck", "k"), ("q", "k"), ("x", "ks"), ("z", "s"), ("y", "i"),
)


def sound_skeleton(word: str) -> str:
    """The consonants a name is heard by, in order, doubles collapsed."""
    text = re.sub(r"[^a-z]", "", word.lower())
    for spelled, sound in _SOUND_RULES:
        text = text.replace(spelled, sound)
    text = re.sub(r"c(?=[eiy])", "s", text).replace("c", "k")
    skeleton: list[str] = []
    for index, char in enumerate(text):
        if char in "aeiou":
            continue
        # An h after a consonant other than s/t is silent here (bh/mh are gone).
        if char == "h" and index and text[index - 1] not in "st":
            continue
        if skeleton and skeleton[-1] == char:
            continue
        skeleton.append(char)
    return "".join(skeleton)


def _names(config: Mapping[str, Any]) -> list[str]:
    dictionary = config.get("dictionary")
    dictionary = dictionary if isinstance(dictionary, Mapping) else {}
    found: list[str] = []
    for entry in list(dictionary.get("words") or []) + list(dictionary.get("terms") or []):
        text = entry.get("text", "") if isinstance(entry, Mapping) else entry
        if isinstance(text, str):
            found.extend(text.split())
    # The same switch and default apply_vocabulary_terms reads.
    if dictionary.get("screen_context", True):
        for name in config.get("_screen_names") or []:
            if isinstance(name, str):
                found.extend(name.split())
    return [name for name in dict.fromkeys(found)
            if name[:1].isupper() and len(sound_skeleton(name)) >= MIN_SOUNDS]


def unsure_words(confidence: Any) -> set[str]:
    if not isinstance(confidence, Mapping):
        return set()
    return {str(word).lower() for word, value in confidence.items()
            if isinstance(value, (int, float)) and value < UNSURE}


def repair_names(text: str, config: Mapping[str, Any]) -> str:
    unsure = unsure_words(config.get("_asr_confidence"))
    if not unsure or not text:
        return text
    by_sound: dict[str, str | None] = {}
    for name in _names(config):
        key = sound_skeleton(name)
        known = by_sound.get(key, name)
        by_sound[key] = name if known is not None and known.lower() == name.lower() else None
    names = {name for name in by_sound.values() if name}
    if not names:
        return text

    def swap(match: re.Match[str]) -> str:
        word, possessive = match[1], ""
        if re.search(r"['’]s$", word):
            word, possessive = word[:-2], word[-2:]
        if word.lower() not in unsure or word in names:
            return match[0]
        name = by_sound.get(sound_skeleton(word))
        return name + possessive if name else match[0]

    return _WORD.sub(swap, text)
