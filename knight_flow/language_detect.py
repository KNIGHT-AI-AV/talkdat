"""X-30: bilingual auto-detect -- conservative, off by default.

Mayowa's rule, verbatim: "we do not want spanish to pop up when people are
obviously speaking english." So this detector only ever earns the right to
SKIP a translation: with auto-translate on and this option enabled, an
utterance that is already decisively in the TARGET language is delivered
as-is instead of being translated twice. It never adds a language nobody
chose, and anything short or ambiguous keeps the configured behaviour.

Detection is stopword scoring -- tiny, offline, and honest about its limits.
Decisive means one language's everyday function words clearly dominate
across the WHOLE utterance; a single borrowed phrase does not flip it.
"""

from __future__ import annotations

import re

_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        "the and is are was were you your this that with from have has not "
        "for they will would could should there what when where how why "
        "about into just been being does did doing".split()
    ),
    "es": frozenset(
        "el la los las es son era eran tu su esto eso con desde tiene tienen "
        "no para ellos ellas que cuando donde como por qué sobre solo hay "
        "está estás estamos pero también muy más".split()
    ),
    "fr": frozenset(
        "le la les est sont était vous votre ce cette avec de avoir pas pour "
        "ils elles que quand où comment pourquoi sur juste été très mais "
        "aussi plus dans une des".split()
    ),
    "de": frozenset(
        "der die das ist sind war waren du dein dies mit von haben hat nicht "
        "für sie werden würde könnte wenn wo wie warum über nur sehr aber "
        "auch mehr ein eine und".split()
    ),
    "pt": frozenset(
        "o a os as é são era eram você seu isto isso com de tem têm não para "
        "eles elas que quando onde como por sobre só muito mas também mais "
        "uma um está".split()
    ),
    "it": frozenset(
        "il la i le è sono era erano tu tuo questo quello con da avere non "
        "per loro che quando dove come perché su solo molto ma anche più "
        "una un sta".split()
    ),
}

# Below this many words, pitch a coin -- so we never do. Matches the
# question-demoter's philosophy: on short utterances the configured
# behaviour is the best evidence there is.
_MIN_WORDS = 5


def detect_language(text: str, candidates: tuple[str, ...] = ("en", "es")) -> str:
    """The decisively dominant language code among candidates, or ""."""
    words = re.findall(r"[a-zà-ÿ']+", str(text or "").lower())
    if len(words) < _MIN_WORDS:
        return ""
    scores: dict[str, int] = {}
    for code in candidates:
        stops = _STOPWORDS.get(str(code).lower())
        if not stops:
            continue
        scores[code] = sum(1 for word in words if word in stops)
    if not scores:
        return ""
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_code, best = ranked[0]
    runner = ranked[1][1] if len(ranked) > 1 else 0
    # Decisive: real evidence, and clear daylight over the runner-up.
    if best >= 3 and best >= 2 * max(1, runner):
        return best_code
    return ""


def should_skip_translation(text: str, *, source: str, target: str, enabled: bool) -> bool:
    """True only when the utterance is already decisively in the TARGET.

    The one action bilingual auto-detect may take. enabled=False (the
    default) means never."""
    if not enabled:
        return False
    source_code = str(source or "").lower()[:2]
    target_code = str(target or "").lower()[:2]
    if not target_code or source_code == target_code:
        return False
    detected = detect_language(text, (source_code, target_code))
    return detected == target_code
