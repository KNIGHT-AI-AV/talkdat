"""Small local counts of habits in saved text for manual rewrites.

Counts cover contractions, known openers/connectors and sentence length. No
dictated prose is stored in this profile. A compact instruction may accompany
a manual rewrite through the selected local or user-key text provider.
"""

from __future__ import annotations

import re
from typing import Any

MAX_PHRASES = 5
# Votes decay by halving once the ledger is full, so a style CHANGE wins
# within weeks instead of fighting a year of history.
LEDGER_CAP = 400

_CONTRACTIONS = re.compile(r"\b(?:i'm|it's|don't|can't|won't|we're|you're|that's|i've|isn't|didn't)\b", re.IGNORECASE)
_EXPANSIONS = re.compile(r"\b(?:i am|it is|do not|cannot|will not|we are|you are|that is|i have|is not|did not)\b", re.IGNORECASE)
_OPENER = re.compile(r"^\s*(hey|hi|hello|yo|good morning|good afternoon|okay|ok|so|alright)\b[\s,!]*", re.IGNORECASE)
_CONNECTORS = ("also", "basically", "honestly", "anyway", "literally", "actually")


def _count(value):
    if type(value) is int:
        return min(1_000_000_000, max(0, value))
    if type(value) is str and len(value) <= 12 and value.isascii() and value.isdigit():
        return min(1_000_000_000, int(value))
    return 0


def _normalised(profile):
    if not isinstance(profile, dict):
        profile = {}
    result = {key: _count(profile.get(key)) for key in
              ('votes', 'contractions', 'expansions', 'word_total', 'sentence_total')}
    for bucket, allowed in [('openers', ('hey', 'hi', 'hello', 'yo', 'good morning', 'good afternoon', 'okay', 'ok', 'so', 'alright')),
                            ('connectors', _CONNECTORS)]:
        values = profile.get(bucket)
        result[bucket] = {key: _count(values.get(key)) for key in allowed if _count(values.get(key))} if isinstance(values, dict) else {}
    return result


def observe(profile: dict[str, Any], text: str) -> dict[str, Any]:
    """Count one accepted dictation's style votes into the profile dict."""
    body = str(text or "").strip()
    if len(body.split()) < 4:
        return profile
    profile.update(_normalised(profile))
    profile.setdefault("votes", 0)
    profile.setdefault("contractions", 0)
    profile.setdefault("expansions", 0)
    profile.setdefault("openers", {})
    profile.setdefault("connectors", {})
    profile.setdefault("word_total", 0)
    profile.setdefault("sentence_total", 0)

    profile["votes"] += 1
    profile["contractions"] += len(_CONTRACTIONS.findall(body))
    profile["expansions"] += len(_EXPANSIONS.findall(body))
    opener = _OPENER.match(body)
    if opener:
        key = opener.group(1).lower()
        profile["openers"][key] = int(profile["openers"].get(key, 0)) + 1
    lowered = body.lower()
    for connector in _CONNECTORS:
        if re.search(rf"\b{connector}\b", lowered):
            profile["connectors"][connector] = int(profile["connectors"].get(connector, 0)) + 1
    sentences = max(1, len(re.findall(r"[.!?]+", body)) or 1)
    profile["word_total"] += len(body.split())
    profile["sentence_total"] += sentences

    if profile["votes"] >= LEDGER_CAP:
        # Halve everything: recency wins without a timestamp in sight.
        for key in ("votes", "contractions", "expansions", "word_total", "sentence_total"):
            profile[key] = int(profile[key]) // 2
        for bucket in ("openers", "connectors"):
            profile[bucket] = {k: v // 2 for k, v in profile[bucket].items() if v // 2 > 0}
    return profile


def render_instruction(profile: dict[str, Any]) -> str:
    """The profile as ONE compact style line for the rewrite's system slot.

    Empty until ~20 votes: guessing a style from three sentences produces a
    parody, and no instruction is better than a wrong one.
    """
    profile = _normalised(profile)
    votes = profile["votes"]
    if votes < 20:
        return ""
    parts: list[str] = []
    contractions = int(profile.get("contractions", 0))
    expansions = int(profile.get("expansions", 0))
    if contractions >= 3 * max(1, expansions):
        parts.append("uses contractions naturally")
    elif expansions >= 3 * max(1, contractions):
        parts.append("avoids contractions")
    openers = sorted((profile.get("openers") or {}).items(), key=lambda item: item[1], reverse=True)
    if openers and openers[0][1] >= 5:
        parts.append(f'often opens with "{openers[0][0]}"')
    connectors = [
        word for word, count in sorted((profile.get("connectors") or {}).items(), key=lambda item: item[1], reverse=True)
        if count >= 5
    ][:MAX_PHRASES]
    if connectors:
        parts.append("favorite connectors: " + ", ".join(connectors))
    words = int(profile.get("word_total", 0))
    sentences = int(profile.get("sentence_total", 0))
    if sentences:
        average = words / sentences
        if average <= 11:
            parts.append("keeps sentences short and punchy")
        elif average >= 22:
            parts.append("writes long, flowing sentences")
    if not parts:
        return ""
    return "Match this writer's own voice: " + "; ".join(parts) + "."
