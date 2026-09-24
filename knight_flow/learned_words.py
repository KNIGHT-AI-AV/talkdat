"""Notice the words somebody keeps having to fix, and learn them.

The observable moment is the copy. When a person corrects a dictated word by
hand, the one signal that reliably leaves their editor is the clipboard: they
select the fixed spelling, copy it, paste it where the wrong one landed. Talk
DAT! already watches nothing else outside itself, and it does not start now --
no accessibility hooks, no reading other windows. A single unusual word landing
on the clipboard while the app is running is the whole detection.

What makes a word worth learning is SHAPE, not frequency. "the" copied a
thousand times is prose; "SAHVVV" copied once is a spelling somebody fought
for. Internal capitals, digits mixed into letters, vowel-less runs, dotted
handles -- the shapes autocorrect and recognizers get wrong are the shapes
ordinary English never takes.

Everything here is reversible by design. The word is added first and the tiny
pop-over above the pill says so; "Don't save" strikes it through and removes
it. Adding-then-asking beats asking-then-adding because the person is mid-task
-- the correction should already be working on their very next dictation, and
undo is for the rare miss.

Pure functions only. The clipboard poll and the pop-over live in app and
overlay; nothing here touches Tk or the OS.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Words shorter than this carry too little shape to judge; longer than this is
# a sentence fragment, not a term.
MIN_LENGTH = 3
MAX_LENGTH = 32

# Ordinary English words that happen to trip the vowel-less test.
_SHAPELY_BUT_COMMON = frozenset({
    "why", "try", "dry", "fly", "shy", "sky", "spy", "cry", "fry", "ply",
    "gym", "myth", "hymn", "lynx", "rhythm", "tsk", "hmm", "shh", "pfft",
})

_WORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.@'+_-]*$")


def looks_like_a_secret(token: str) -> bool:
    """X-604: a generated password, key or code, not a spelling anybody fought for.

    Twelve or more characters mixing lower case, upper case and digits is a
    password generator's shape; sixteen or more mixing letters and digits is a
    key's or a recovery code's. Names, brands and initialisms are short. An
    address is never a secret here ("@" is its own rule).
    """
    token = str(token or "").strip()
    if "@" in token:
        return False
    has_lower = any(c.islower() for c in token)
    has_upper = any(c.isupper() for c in token)
    has_digit = any(c.isdigit() for c in token)
    has_letter = has_lower or has_upper
    return (len(token) >= 12 and has_lower and has_upper and has_digit) or (
        len(token) >= 16 and has_letter and has_digit)


def looks_learnable(text: str) -> bool:
    """Whether a clipboard capture is a spelling somebody fought for.

    The bar is deliberately high: a false add interrupts with a pop-over and
    pollutes the dictionary, while a miss costs nothing -- the person can add
    the word by hand in two clicks. So only shapes ordinary prose never takes
    qualify:

    - internal capitals after the first letter ("SAHVVV", "iPhone", "McRae")
    - digits mixed into letters ("B2B", "GPT4", "v2ray")
    - an email or handle ("build@knightaiav.com", "user.name")
    - a vowel-less consonant run long enough to be an initialism
    """
    token = str(text or "").strip()
    if not (MIN_LENGTH <= len(token) <= MAX_LENGTH):
        return False
    if not _WORD_RE.match(token):
        return False
    if looks_like_a_secret(token):
        return False
    if token.lower() in _SHAPELY_BUT_COMMON:
        return False

    letters = re.sub(r"[^A-Za-z]", "", token)
    has_digit = any(character.isdigit() for character in token)
    has_letter = bool(letters)
    internal_caps = any(character.isupper() for character in letters[1:])
    all_caps = len(letters) >= 3 and letters.isupper()
    vowelless = len(letters) >= 3 and not any(v in letters.lower() for v in "aeiou")
    handle_like = "@" in token or "." in token[1:-1]

    if has_letter and has_digit:
        return True
    if internal_caps or all_caps:
        return True
    if handle_like and has_letter:
        return True
    if vowelless:
        return True
    return False


def already_known(token: str, config: dict) -> bool:
    """Whether the dictionary -- user's or default -- already covers this word."""
    from .vocabulary import DEFAULT_TERMS, parse_terms

    dictionary = config.get("dictionary", {}) if isinstance(config, dict) else {}
    entries = list(dictionary.get("words") or []) + list(dictionary.get("terms") or [])
    lowered = token.strip().lower()
    for term in parse_terms(entries) + list(DEFAULT_TERMS):
        if term.text.lower() == lowered:
            return True
    return False


def remember(token: str, config: dict) -> bool:
    """Add the word to the live dictionary. Returns whether anything changed."""
    token = str(token or "").strip()
    if not token or already_known(token, config):
        return False
    terms = config.setdefault("dictionary", {}).setdefault("terms", [])
    terms.append({"text": token, "sounds_like": [], "learned": True})
    return True


def correction_candidate(before: str, after: str, instruction: str) -> tuple[str, str] | None:
    """A single explicit spelling repair, not a general model rewrite.

    Both strings are already owned by Fix That. This reads no other field or
    clipboard. Even a matching pair is only an offer, never implicit consent
    to remember the spelling across future dictations.
    """
    if not re.search(r"\b(?:spell(?:ing)?|spelled|misspelt|misspelled|typo)\b", instruction, re.I):
        return None
    if max(len(before), len(after), len(instruction)) > 2000:
        return None
    if any(character in before + after for character in "`/@\\"):
        return None
    tokenize = lambda text: re.findall(r"\w+(?:['-]\w+)*|[^\w\s]", text)
    old_tokens, new_tokens = tokenize(before), tokenize(after)
    changes = [part for part in SequenceMatcher(None, old_tokens, new_tokens, autojunk=False).get_opcodes()
               if part[0] != "equal"]
    if len(changes) != 1:
        return None
    kind, a, b, c, d = changes[0]
    if kind != "replace" or not 1 <= b - a <= 3 or d - c != 1:
        return None
    old, new = " ".join(old_tokens[a:b]), new_tokens[c]
    from .recognition_bias import clean_terms
    if not clean_terms((old,)) or not clean_terms((new,)) or old.casefold() == new.casefold():
        return None
    if new.casefold() not in instruction.casefold():
        return None
    return old, new


def remember_correction(misheard: str, spelling: str, config: dict) -> bool:
    """Persist an accepted spelling and its exact misheard alias."""
    from .recognition_bias import clean_terms
    if (not clean_terms((misheard,)) or not clean_terms((spelling,))
            or already_known(spelling, config) or tombstoned(spelling, config)
            or misheard.casefold() == spelling.casefold()):
        return False
    terms = config.setdefault("dictionary", {}).setdefault("terms", [])
    terms.append({"text": spelling, "sounds_like": [misheard], "learned": True})
    return True


def misheard_form(spelling: str, delivered: str, unsure: object) -> str:
    """X-608 (commandment 99): the word a hand-fix replaced, or "".

    The person copied `spelling` after a dictation that did not contain it.
    If that dictation held exactly one word that SOUNDS like it (name_repair's
    skeleton, three sounds or more) AND the recognizer was unsure of that
    word, the copy is a correction of it: remember_correction stores it as
    the spelling's sounds-like alias, so the same mishearing is fixed from
    then on. Confidence is what keeps an ordinary word out: "clean" sounds
    like Kaelyn, but the recognizer is sure of "clean", so it is never paired.
    """
    from .name_repair import MIN_SOUNDS, sound_skeleton, unsure_words

    doubtful = unsure_words(unsure)
    key = sound_skeleton(spelling)
    if not doubtful or len(key) < MIN_SOUNDS:
        return ""
    found = {word.lower() for word in re.findall(r"[A-Za-z][A-Za-z']*", delivered or "")
             if word.lower() in doubtful and word.lower() != spelling.lower()
             and sound_skeleton(word) == key}
    return found.pop() if len(found) == 1 else ""


def learn_spelling(spelling: str, config: dict, delivered: str = "", unsure: object = None) -> bool:
    """remember(), and when the fix names what it replaced, remember that too."""
    misheard = misheard_form(spelling, delivered, unsure)
    if misheard and remember_correction(misheard, spelling, config):
        return True
    return remember(spelling, config)


def forget(token: str, config: dict) -> bool:
    """Remove a word this feature added. Only 'learned' entries are touched --
    a hand-added term is a decision, and Don't-save on a pop-over must never
    reach into decisions."""
    lowered = str(token or "").strip().lower()
    add_tombstone(lowered, config)
    terms = config.get("dictionary", {}).get("terms", [])
    for entry in list(terms):
        if (
            isinstance(entry, dict)
            and entry.get("learned")
            and str(entry.get("text", "")).lower() == lowered
        ):
            terms.remove(entry)
            return True
    return False


# ---------------------------------------------------------------------------
# X-80, v2: evidence and tombstones.
#
# Shape (above) is instant proof. A PLAIN word -- "Mayowa", "Navorb" spelled
# to taste -- carries no shape, so the proof is repetition: the same fix
# copied twice inside two weeks is deliberate behavior, not noise. And a word
# the person told us NOT to save must never be offered again: that dismissal
# is recorded as a tombstone, which only a hand-add in Words & phrases
# overrides. Curated entries always win -- remember() refuses anything
# already_known, so a learned alias can never displace a curated one.

EVIDENCE_WINDOW_DAYS = 14
AUTO_LEARN_MODES = ("off", "offer", "auto-on-second")
_PLAIN_WORD_RE = re.compile(r"^[A-Za-z][a-z]+$|^[A-Z][a-z]+$")


def auto_learn_mode(config: dict) -> str:
    dictionary = config.get("dictionary", {}) if isinstance(config, dict) else {}
    if not bool(dictionary.get("auto_learn", True)):
        return "off"
    mode = str(dictionary.get("auto_learn_mode", "auto-on-second"))
    return mode if mode in AUTO_LEARN_MODES else "auto-on-second"


def tombstoned(token: str, config: dict) -> bool:
    dictionary = config.get("dictionary", {}) if isinstance(config, dict) else {}
    stones = dictionary.get("learn_tombstones", [])
    return str(token or "").strip().lower() in {str(s).lower() for s in stones}


def add_tombstone(token: str, config: dict) -> None:
    lowered = str(token or "").strip().lower()
    if not lowered:
        return
    stones = config.setdefault("dictionary", {}).setdefault("learn_tombstones", [])
    if lowered not in {str(s).lower() for s in stones}:
        stones.append(lowered)


def note_fix_evidence(token: str, config: dict, now_seconds: float) -> str:
    """Record one observed fix and answer what to do: "learn", "offer", or
    "ignore". Evidence lives on this PC only (the X-37 fence) under
    dictionary.learn_evidence, pruned to the two-week window."""
    token = str(token or "").strip()
    mode = auto_learn_mode(config)
    if not token or mode == "off":
        return "ignore"
    if tombstoned(token, config) or already_known(token, config):
        return "ignore"
    if looks_learnable(token):
        return "offer" if mode == "offer" else "learn"
    if not (MIN_LENGTH <= len(token) <= MAX_LENGTH and _PLAIN_WORD_RE.match(token)):
        return "ignore"
    evidence = config.setdefault("dictionary", {}).setdefault("learn_evidence", {})
    horizon = now_seconds - EVIDENCE_WINDOW_DAYS * 86400
    for key in list(evidence):
        record = evidence.get(key)
        if not isinstance(record, dict) or float(record.get("last", 0)) < horizon:
            evidence.pop(key, None)
    lowered = token.lower()
    record = evidence.setdefault(lowered, {"count": 0, "last": 0.0})
    record["count"] = int(record.get("count", 0)) + 1
    record["last"] = float(now_seconds)
    if record["count"] < 2:
        return "ignore"
    evidence.pop(lowered, None)
    # X-466, his report: "if a user copies something twice, it stores as a
    # new single word in the dictionary". Copying a word twice is what
    # people do with a name or an address all day; it is not evidence that
    # anybody corrected a spelling. A plain word is OFFERED and saved only
    # if he says yes. The shapely tokens above still learn on sight, which
    # is the case this feature was built for.
    return "offer"
