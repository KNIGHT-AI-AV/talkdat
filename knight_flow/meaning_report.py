"""T2: what a cleanup changed that carries meaning, shown instead of assumed.

The formatter already refuses a model's answer that changes a number, a
negation, a hedge, a quote or a name (formatting.formatter_rejection_reason)
and falls back to the built-in rules, so the person's words survive. What the
person never sees is the evidence: which of their names, dates, quantities,
units, negations and commitments came through, and what -- if anything --
moved. "Trust me" is the whole interface.

This module is that evidence, as data. Given what was said and what was
finished, it lists the meaning-bearing items of each kind that were KEPT, and
every one that was dropped or appeared. It reuses the gate's own extractors so
the report and the gate can never disagree about what a number is, and adds
the classes the gate reads only indirectly: dates (weekdays, months, relative
days), units after a quantity, and terms the person protected.

It decides nothing and rewrites nothing. A report with changes is `material`;
the caller shows it and offers the words as said. Uncertain means material:
an item that cannot be matched counts as changed.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

#: The kinds, in the order a person reads them.
KINDS = ("name", "date", "number", "unit", "negation", "commitment", "certainty", "quote", "protected")

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")
_MONTH_SHORT = {"jan": "january", "feb": "february", "mar": "march", "apr": "april", "jun": "june",
                "jul": "july", "aug": "august", "sep": "september", "sept": "september", "oct": "october",
                "nov": "november", "dec": "december"}
_RELATIVE_DAYS = ("today", "tonight", "tomorrow", "yesterday", "this morning", "this afternoon",
                  "this evening", "next week", "last week", "this week", "next month", "last month",
                  "next year", "last year", "end of day", "end of week", "end of month")
_DATE_RE = re.compile(
    r"\b(?:" + "|".join(_WEEKDAYS + _MONTHS) + r"|" + "|".join(sorted(_MONTH_SHORT, key=len, reverse=True))
    + r"|" + "|".join(sorted(_RELATIVE_DAYS, key=len, reverse=True)) + r")\b\.?", re.IGNORECASE)

# Units, each with its spellings, so "15 km" and "fifteen kilometers" are one
# measurement and "15 miles" is a different one.
_UNITS = {
    "km": ("km", "kms", "kilometer", "kilometers", "kilometre", "kilometres"),
    "mi": ("mi", "mile", "miles"),
    "m": ("meter", "meters", "metre", "metres"),
    "cm": ("cm", "centimeter", "centimeters", "centimetre", "centimetres"),
    "mm": ("mm", "millimeter", "millimeters", "millimetre", "millimetres"),
    "ft": ("ft", "foot", "feet"),
    "in": ("inch", "inches"),
    "kg": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"),
    "g": ("gram", "grams"),
    "lb": ("lb", "lbs", "pound", "pounds"),
    "oz": ("oz", "ounce", "ounces"),
    "l": ("liter", "liters", "litre", "litres"),
    "ml": ("ml", "milliliter", "milliliters", "millilitre", "millilitres"),
    "%": ("%", "percent", "per cent", "percentage points"),
    "usd": ("$", "dollar", "dollars", "usd", "bucks"),
    "eur": ("€", "euro", "euros", "eur"),
    "gbp": ("£", "pound sterling", "gbp", "quid"),
    "ngn": ("₦", "naira", "ngn"),
    "s": ("sec", "secs", "second", "seconds"),
    "min": ("min", "mins", "minute", "minutes"),
    "h": ("hr", "hrs", "hour", "hours"),
    "day": ("day", "days"),
    "week": ("week", "weeks"),
    "month": ("month", "months"),
    "year": ("yr", "yrs", "year", "years"),
    "gb": ("gb", "gig", "gigs", "gigabyte", "gigabytes"),
    "mb": ("mb", "megabyte", "megabytes"),
    "tb": ("tb", "terabyte", "terabytes"),
    "x": ("x", "times"),
}
_UNIT_OF = {spelling: unit for unit, spellings in _UNITS.items() for spelling in spellings}
_UNIT_WORDS = "|".join(sorted((re.escape(spelling) for spelling in _UNIT_OF if spelling not in "$€£₦%"),
                              key=len, reverse=True))
_QUANTITY_UNIT_RE = re.compile(rf"(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?P<u>%|(?:{_UNIT_WORDS})\b)", re.IGNORECASE)
_CURRENCY_FIRST_RE = re.compile(r"(?P<u>[$€£₦])\s*(?P<n>\d[\d,]*(?:\.\d+)?)")

_COMMITMENT_RE = re.compile(
    r"\b(?:will|won't|shall|would|wouldn't|can|can't|cannot|could|couldn't|must|mustn't|should|shouldn't|"
    r"may|might|need(?:s|ed)? to|have to|has to|had to|got to|gotta|going to|gonna|promise[sd]?|"
    r"agree[sd]?|commit(?:s|ted)?)\b", re.IGNORECASE)
# One name per commitment, so a rewording keeps it and a change of strength does
# not: "need to", "have to", "gotta" and "must" are the same obligation, and
# "might" is not "will". Negation is counted on its own, so "won't" is "will".
_COMMITMENT_SAME = {
    "won't": "will", "shall": "will", "wouldn't": "would", "can't": "can", "cannot": "can",
    "couldn't": "could", "shouldn't": "should", "mustn't": "obligation", "must": "obligation",
    "need to": "obligation", "needs to": "obligation", "needed to": "obligation", "have to": "obligation",
    "has to": "obligation", "had to": "obligation", "got to": "obligation", "gotta": "obligation",
    "gonna": "going to", "promises": "promise", "promised": "promise", "agrees": "agree", "agreed": "agree",
    "commits": "commit", "committed": "commit",
}
_FILLERS = frozenset("so yeah yes um uh er erm like okay ok well oh hmm alright right basically actually "
                     "anyway now and but also then hey hi".split())


@dataclass(frozen=True)
class Change:
    kind: str
    said: tuple[str, ...]      # in what was said, missing from the finish
    written: tuple[str, ...]   # in the finish, never said


@dataclass(frozen=True)
class MeaningReport:
    kept: dict[str, int]
    changes: tuple[Change, ...]

    @property
    def material(self) -> bool:
        return bool(self.changes)

    def kinds_changed(self) -> tuple[str, ...]:
        return tuple(change.kind for change in self.changes)

    def as_dict(self) -> dict:
        """For the take's History entry: plain values only."""
        return {"material": self.material, "kept": dict(self.kept),
                "changes": [{"kind": change.kind, "said": list(change.said), "written": list(change.written)}
                            for change in self.changes]}


def _numbers(text: str) -> Counter[str]:
    from .formatting import _ordered_meaning_anchors

    return Counter(_ordered_meaning_anchors(text))


def _spoken_numbers_as_digits(text: str) -> str:
    """"fifteen kilometers" -> "15 kilometers", with the gate's own converter."""
    from .formatting import _compose_spoken_numbers, _convert_spoken_times

    try:
        return _compose_spoken_numbers(_convert_spoken_times(text))
    except Exception:
        return text


def _units(text: str) -> Counter[str]:
    canonical = _spoken_numbers_as_digits(text)
    found: Counter[str] = Counter()
    for match in _QUANTITY_UNIT_RE.finditer(canonical):
        unit = _UNIT_OF.get(match.group("u").lower())
        if unit:
            found[f"{match.group('n').replace(',', '')} {unit}"] += 1
    for match in _CURRENCY_FIRST_RE.finditer(canonical):
        found[f"{match.group('n').replace(',', '')} {_UNIT_OF[match.group('u')]}"] += 1
    return found


def _dates(text: str) -> Counter[str]:
    found: Counter[str] = Counter()
    for match in _DATE_RE.finditer(text):
        word = " ".join(match.group(0).lower().rstrip(".").split())
        if word == "may" and not re.search(r"\bmay\s+\d|\d(?:st|nd|rd|th)?\s+(?:of\s+)?may\b|\bin\s+may\b",
                                           text[max(0, match.start() - 12): match.end() + 6], re.IGNORECASE):
            continue  # "may" the modal, not the month
        if word == "march" and not re.search(r"\bmarch\s+\d|\bin\s+march\b|\d\s+march\b",
                                             text[max(0, match.start() - 12): match.end() + 6], re.IGNORECASE):
            continue  # "march" the verb
        found[_MONTH_SHORT.get(word, word)] += 1
    return found


def _stance(text: str) -> tuple[Counter[str], Counter[str], Counter[str]]:
    """(negation, commitment, certainty) as the gate counts them."""
    from .formatting import _CERTAINTY_RE, _meaning_words

    words = _meaning_words(text)
    negation = Counter({"negation": words.get("negation", 0)}) if words.get("negation") else Counter()
    commitment: Counter[str] = Counter()
    for match in _COMMITMENT_RE.finditer(text):
        word = " ".join(match.group(0).lower().split())
        commitment[_COMMITMENT_SAME.get(word, word)] += 1
    certainty = Counter(" ".join(m.group(0).lower().split()) for m in _CERTAINTY_RE.finditer(text))
    return negation, commitment, certainty


def _letters(word: str) -> str:
    return "".join(ch for ch in word.lower() if ch.isalpha())


def _date_or_unit(token: str) -> bool:
    word = token.lower().rstrip(".")
    return bool(_DATE_RE.fullmatch(word)) or word in _UNIT_OF or word in _MONTH_SHORT


def _name_tokens(text: str) -> list[tuple[str, bool]]:
    """Capitalised tokens, and whether each one opens a sentence."""
    tokens = []
    for match in re.finditer(r"[A-Z][A-Za-z'\-]*", text):
        before = text[: match.start()].rstrip()
        tokens.append((match.group(0), not before or before.endswith((".", "!", "?", ":"))))
    return tokens


def _said_forms(text: str) -> set[str]:
    """Every word of ``text`` and every run of two or three, as letters, so
    "deep gram" counts as having said Deepgram (the gate's own rule)."""
    words = [_letters(word) for word in re.findall(r"[A-Za-z][A-Za-z'\-]*", text)]
    words = [word for word in words if word]
    forms = set(words)
    forms.update(a + b for a, b in zip(words, words[1:]))
    forms.update(a + b + c for a, b, c in zip(words, words[1:], words[2:]))
    return forms


def _ordinary_opener(token: str, opens: bool) -> bool:
    """A sentence's first word that is an ordinary or filler word ("Do" from
    "don't", "It's", "So"): capitalised by position, not a name."""
    from .ordinary_words import COMMON_WORDS

    ordinary = COMMON_WORDS | _FILLERS
    return opens and (token.lower() in ordinary or _letters(token) in ordinary)


def _names_said(text: str) -> list[str]:
    """Names in what was said: capitalised words, except a sentence's first
    word when it is an ordinary or filler word."""
    return [token for token, opens in _name_tokens(text)
            if not _date_or_unit(token) and not _ordinary_opener(token, opens)]


def _names(said: str, finished: str) -> Change | None:
    """A name is kept when its letters appear in the other text as a word or a
    run of words. Dates and units are not names here: they have kinds of their
    own, and "October" for "oct" is not an invented person."""
    said_forms, finished_forms = _said_forms(said), _said_forms(finished)
    written = tuple(token for token, opens in _name_tokens(finished)
                    if not _date_or_unit(token) and not _ordinary_opener(token, opens)
                    and _letters(token) and _letters(token) not in said_forms)
    dropped = tuple(token for token in _names_said(said)
                    if _letters(token) and _letters(token) not in finished_forms)
    if written or dropped:
        return Change("name", dropped, written)
    return None


def _quotes(text: str) -> Counter[str]:
    from .formatting import _quoted_literals

    return _quoted_literals(text)


def _protected(said: str, finished: str, protected: Iterable[str]) -> Change | None:
    lost = []
    for term in protected:
        term = str(term or "").strip()
        if not term:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        exact = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)")
        if pattern.search(said) and len(exact.findall(finished)) < len(pattern.findall(said)):
            lost.append(term)
    return Change("protected", tuple(lost), ()) if lost else None


def _diff(kind: str, said: Counter[str], finished: Counter[str], kept: dict[str, int]) -> Change | None:
    kept[kind] = sum((said & finished).values())
    missing, extra = said - finished, finished - said
    if missing or extra:
        return Change(kind, tuple(sorted(missing.elements())), tuple(sorted(extra.elements())))
    return None


def meaning_report(said: str, finished: str, *, protected: Iterable[str] = ()) -> MeaningReport:
    said, finished = str(said or ""), str(finished or "")
    kept: dict[str, int] = {}
    changes: list[Change] = []
    names = _names(said, finished)
    kept["name"] = len(_names_said(said)) - (len(names.said) if names else 0)
    if names:
        changes.append(names)
    for kind, extract in (("date", _dates), ("number", _numbers), ("unit", _units)):
        change = _diff(kind, extract(said), extract(finished), kept)
        if change:
            changes.append(change)
    said_stance, finished_stance = _stance(said), _stance(finished)
    for kind, said_count, finished_count in zip(("negation", "commitment", "certainty"), said_stance,
                                                finished_stance):
        change = _diff(kind, said_count, finished_count, kept)
        if change:
            changes.append(change)
    change = _diff("quote", _quotes(said), _quotes(finished), kept)
    if change:
        changes.append(change)
    change = _protected(said, finished, protected)
    kept["protected"] = sum(1 for term in protected if str(term or "").strip()
                            and re.search(rf"(?<!\w){re.escape(str(term).strip())}(?!\w)", said, re.IGNORECASE))
    if change:
        changes.append(change)
        kept["protected"] -= len(change.said)
    order = {kind: index for index, kind in enumerate(KINDS)}
    return MeaningReport(kept, tuple(sorted(changes, key=lambda change: order[change.kind])))
