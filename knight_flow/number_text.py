"""Conservative English inverse text normalization, with explicit context anchors."""
from __future__ import annotations

import re

from .literal_text import map_prose

UNITS = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(20),
))
TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
SCALES = {"thousand": 1000, "million": 1000000, "billion": 1000000000, "trillion": 1000000000000}
ORDINALS = dict(zip(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth".split(),
    range(1, 21),
)) | {"thirtieth": 30}
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_WORD = r"(?:" + "|".join(sorted(UNITS.keys() | TENS.keys() | SCALES.keys() | {"hundred"}, key=len, reverse=True)) + r")"
# A grammatical quantity through trillions fits within 32 words. Bound the
# candidate grammar so an unrelated suffix cannot make a long digit recital
# retry every possible suffix. Digit identifiers are handled separately.
_RUN = rf"{_WORD}(?:[ -]+(?:and[ -]+)?{_WORD}){{0,31}}"
_RUN_RE = re.compile(rf"\b{_RUN}\b", re.IGNORECASE)
_AMOUNT = rf"(?:\d+(?:\.\d+)?|{_RUN})"
_DIGIT = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|[0-9])"
_DIGIT_TOKEN = rf"(?:(?:double|triple)[ \t]+)?{_DIGIT}"
_DIGIT_RUN_RE = re.compile(rf"\b(?:{_DIGIT_TOKEN}|[0-9]+)(?:[ \t]+(?:{_DIGIT_TOKEN}|[0-9]+))*\b", re.I)
_NUMBER_CUE = re.compile(
    r"\b(?P<ssn>social security(?: number)?|ssn)\b"
    r"|\b(?P<card>(?:credit|debit|bank) card(?: number)?|card number)\b"
    r"|\b(?P<phone>phone(?: number)?|telephone|mobile|cell|dial|call|reach|text me(?: at)?"
    r"|(?:my|his|her|their|your|our) number)\b"
    r"|\b(?P<identifier>code|pin|otp|zip|postcode|account(?: number)?|serial(?: number)?|id|extension|room|page|version)\b"
    r"|\b(?P<list>scores?|numbers|list|countdown)\b", re.I,
)


def _number_context(before: str, *, direct: bool = False) -> str | None:
    # Cues belong to this clause, and the closest explicit label wins.
    clause = re.split(r"[.!?;\n]", before[-160:])[-1]
    cues = list(_NUMBER_CUE.finditer(clause))
    if cues and direct and not re.fullmatch(r'[ \t:]*(?:(?:is|was|equals|number|extension|of)[ \t:]*)?', clause[cues[-1].end():], re.I):
        return None
    return cues[-1].lastgroup if cues else None


def contains_numeric_language(text: str) -> bool:
    return bool(re.search(rf"\d|\b(?:{_WORD}|oh|{'|'.join(ORDINALS)})\b", text, re.I))


def _under_hundred(words: list[str]) -> int | None:
    if len(words) == 1:
        return UNITS.get(words[0], TENS.get(words[0]))
    if len(words) == 2 and words[0] in TENS and 0 < UNITS.get(words[1], 100) < 10:
        return TENS[words[0]] + UNITS[words[1]]
    return None


def _under_thousand(words: list[str]) -> int | None:
    if "hundred" not in words:
        return _under_hundred(words)
    index = words.index("hundred")
    # "four hundred", and X-602: "twelve hundred" and "twenty five hundred",
    # which is how people say 1,100 to 9,900 ("the invoice came to twelve
    # hundred dollars and fifty cents" stayed in words on every lane).
    head = _under_hundred(words[:index]) if 1 <= index <= 2 else None
    if head is None or not 0 < head < 100:
        return None
    tail = words[index + 1:]
    if tail[:1] == ["and"]:
        tail = tail[1:]
    rest = _under_hundred(tail) if tail else 0
    return head * 100 + rest if rest is not None else None


def cardinal(spoken: str) -> int | None:
    """Parse grammatical cardinals; never add together an arbitrary digit run."""
    if spoken.isdigit():
        return int(spoken)
    words = spoken.lower().replace("-", " ").split()
    if not words:
        return None
    total, previous, start = 0, 10**15, 0
    for index, word in enumerate(words):
        if word not in SCALES:
            continue
        scale = SCALES[word]
        value = _under_thousand(words[start:index])
        if scale >= previous or value is None or value == 0:
            return None
        total += value * scale
        previous, start = scale, index + 1
    tail = words[start:]
    if total and tail[:1] == ["and"]:
        tail = tail[1:]
    remainder = _under_thousand(tail) if tail else 0
    return total + remainder if remainder is not None else None


def _amount(spoken: str) -> str | None:
    if re.fullmatch(r"\d+(?:\.\d+)?", spoken):
        return spoken
    value = cardinal(spoken)
    return str(value) if value is not None else None


def _ordinal_suffix(day: int) -> str:
    return "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def _dates(text: str) -> str:
    ordinal = "|".join(ORDINALS)
    pattern = re.compile(rf"\b({MONTHS})\s+(?:the\s+)?((?:twenty[ -]|thirty[ -])?(?:{ordinal}))\b", re.IGNORECASE)

    def render(match: re.Match[str]) -> str:
        if match[1].lower() == "may":
            before, after = text[:match.start()], text[match.end():]
            if (re.search(r"\b(?:i|we|you|he|she|it|they|this|that|someone|anyone|everyone)\s+$", before, re.I)
                    or re.match(r"\s+(?:check|send|try|need|want|take|make|choose|use|review|have|be)\b", after, re.I)):
                return match[0]
        words = match[2].lower().replace("-", " ").split()
        day = ORDINALS[words[-1]] + (TENS[words[0]] if len(words) == 2 else 0)
        if not 1 <= day <= 31:
            return match[0]
        return f"{match[1].capitalize()} {day}{_ordinal_suffix(day)}"

    return pattern.sub(render, text)


def _years(text: str) -> str:
    def render(match: re.Match[str]) -> str:
        century = cardinal(match[2])
        tail = match[3].lower()
        rest = cardinal(tail.removeprefix("oh "))
        if rest is None or not 0 <= rest < 100 or (rest < 10 and not tail.startswith("oh ")):
            return match[0]
        return f"{match[1]}{century * 100 + rest}"

    return re.sub(
        rf"\b((?:in|since|during|before|after|by|year)\s+)(eighteen|nineteen|twenty)\s+(oh\s+{_DIGIT}|{_RUN})\b",
        render, text, flags=re.IGNORECASE,
    )


def _digit_runs(text: str) -> str:
    def render(match: re.Match[str]) -> str:
        raw = match[0]
        words = raw.lower().split()
        before = text[max(0, match.start() - 160):match.start()]
        after = text[match.end():match.end() + 30]
        context = _number_context(before)
        # An interjection before one measured count is ordinary prose, unlike
        # a bare "oh five" identifier or a longer recital such as "oh five two".
        if (len(words) == 2 and words[0] == 'oh' and context is None
                and re.match(r'\s+(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?|people|items?)\b', after, re.I)):
            return raw
        # A digit embedded in a written decimal or grouped identifier is final.
        if (re.search(r"\d[.,:/-]$", before) or re.match(r"[.,:/-]\d", after)):
            return raw
        if len(words) > 1 and all(word.isdigit() for word in words):
            return raw
        # Do not detach a unit from a cardinal, fraction, clock or measurement.
        if re.match(r"[ -]+(?:hundred|thousand|million|billion|trillion|half|third|quarter|dollars?|pounds?|euros?|percent)\b", after, re.I):
            return raw
        isolated = not text[:match.start()].strip() and not text[match.end():].strip(' .!?\t\n')
        if len(words) == 1 and not context and not isolated:
            return raw
        if len(words) == 1 and not words[0].isdigit() and not isolated:
            if not _number_context(before, direct=True) or re.match(r'\s+(?:of|on|or|way|another)\b', after, re.I):
                return raw
        digits = []
        repeat = 1
        for word in words:
            if word in {'double', 'triple'}:
                repeat = 2 if word == 'double' else 3
                continue
            digits.append((word if word.isdigit() else str(0 if word == 'oh' else UNITS[word])) * repeat)
            repeat = 1
        digits = ''.join(digits)
        if context == 'phone':
            # A seven-digit local number is written 555-1234, like the
            # ten-digit form it abbreviates. Any other length stays intact.
            if len(digits) == 7:
                return f"{digits[:3]}-{digits[3:]}"
            if len(digits) == 10:
                return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
            if len(digits) == 11 and digits[0] == "1":
                return f"1-{digits[1:4]}-{digits[4:7]}-{digits[7:]}"
        if context == 'ssn' and len(digits) == 9:
            return f'{digits[:3]}-{digits[3:5]}-{digits[5:]}'
        if context == 'card':
            if len(digits) == 16:
                return ' '.join(digits[i:i + 4] for i in range(0, 16, 4))
            if len(digits) == 15 and digits.startswith(('34', '37')):
                return f'{digits[:4]} {digits[4:10]} {digits[10:]}'
        if context == 'list' and len(words) > 1:
            return ', '.join(digits)
        return digits

    # Explicit commas mark an enumeration rather than one identifier. Keep the
    # speaker's conjunction and punctuation; only convert the numeric tokens.
    enumeration = re.compile(rf"\b{_DIGIT}(?:[ \t]*,[ \t]*(?:and[ \t]+)?{_DIGIT})+\b", re.I)
    text = enumeration.sub(lambda m: re.sub(_DIGIT, lambda d: d[0] if d[0].isdigit() else str(0 if d[0].lower() == 'oh' else UNITS[d[0].lower()]), m[0], flags=re.I), text)
    return _DIGIT_RUN_RE.sub(render, text)


def _decimals(text: str) -> str:
    def render(match: re.Match[str]) -> str:
        whole = cardinal(match[1])
        parts = match[2].lower().split()
        if whole is None:
            return match[0]
        decimal = "".join("0" if word == "oh" else str(UNITS[word]) if word in UNITS else word for word in parts)
        return f"{whole}.{decimal}"

    return re.sub(rf"\b({_AMOUNT})\s+point\s+({_DIGIT}(?:\s+{_DIGIT})*)\b", render, text, flags=re.IGNORECASE)


def _money(text: str) -> str:
    if not re.search(r'\b(?:dollars?|pounds?|euros?)\b|[$\u00a3\u20ac]', text, re.I):
        return text
    currencies = {"dollar": "$", "pound": chr(163), "euro": chr(8364)}

    def render(match: re.Match[str]) -> str:
        if match[2].lower().startswith("pound"):
            cues = re.findall(r"\b(weighs?|weighing|weight|heavy|costs?|price|pay|paid|charge)\b",
                              text[max(0, match.start() - 80):match.start()], re.I)
            if (cues and cues[-1].lower() in {"weigh", "weighs", "weighing", "weight", "heavy"}
                    or re.match(r"\s+of\b", text[match.end():], re.I)):
                return match[0]
        value = _amount(match[1])
        if value is None:
            return match[0]
        cents = cardinal(match[3]) if match[3] else None
        if match[3] and (cents is None or not 0 <= cents <= 99 or "." in value):
            return match[0]
        # House style 3: money takes digit-group commas from 1,000 ("$1,200.50").
        if "." not in value and int(value) >= 1000:
            value = f"{int(value):,}"
        if cents is not None:
            value += f".{cents:02d}"
        return currencies[match[2].lower().rstrip("s")] + value

    text = re.sub(
        rf"\b({_AMOUNT})\s+(dollars?|pounds?|euros?)(?:\s+and\s+({_AMOUNT})\s+(?:cents?|pence))?\b",
        render, text, flags=re.IGNORECASE,
    )

    def implicit(match: re.Match[str]) -> str:
        # A previous explicit currency in this sentence supplies the unit.
        before = text[:match.start()]
        currency = re.search(r"([$\u00a3\u20ac])\d+(?:\.\d+)?[^.!?]*$", before)
        if not currency or not re.search(r"\b(?:is|costs?|price|priced|pay|paid)\s*$", before, re.I):
            return match[0]
        words = match[0].lower().split()
        if cardinal(match[0]) is not None:
            return match[0]
        for split in range(len(words) - 1, 0, -1):
            major, minor = cardinal(" ".join(words[:split])), cardinal(" ".join(words[split:]))
            if major is not None and minor is not None and 10 <= minor < 100:
                return f"{currency[1]}{major}.{minor:02d}"
        return match[0]

    return _RUN_RE.sub(implicit, text)


_SCALED_MONEY_RE = re.compile(
    rf"\b(\d+(?:\.\d+)?|{_RUN})\s+(thousand|million|billion|trillion)\s+(dollars?|pounds?|euros?)\b",
    re.IGNORECASE,
)


def _scaled_money(text: str) -> str:
    """"one point two million dollars" -> "$1.2 million", the written form.

    Runs after decimals, so the amount is already "1.2". A whole amount under
    a thousand ("two million dollars") keeps its scale word as well: "$2
    million" is what a person types, "$2000000" is not.
    """
    currencies = {"dollar": "$", "pound": chr(163), "euro": chr(8364)}

    def render(match: re.Match[str]) -> str:
        value = _amount(match[1])
        if value is None or ("." not in value and not 0 < int(value) < 1000):
            return match[0]
        sign = currencies[match[3].lower().rstrip('s')]
        # X-602: whole thousands are written out, as house style 3 and the
        # scaled ranges already do: "fifteen thousand dollars" is "$15,000",
        # not "$15 thousand". Millions, billions and a fractional thousand
        # ("$2.5 thousand") keep the word.
        if match[2].lower() == "thousand" and "." not in value:
            return f"{sign}{int(value) * 1000:,}"
        return f"{sign}{value} {match[2].lower()}"

    return _SCALED_MONEY_RE.sub(render, text)


# "q three" is the third quarter. A spoken letter q has no other common
# reading directly before a number one to four, so this one is deterministic.
_QUARTER_RE = re.compile(r"\bq\s*(one|two|three|four|[1-4])\b", re.IGNORECASE)


def _quarters(text: str) -> str:
    values = {"one": "1", "two": "2", "three": "3", "four": "4"}
    return _QUARTER_RE.sub(lambda m: "Q" + values.get(m[1].lower(), m[1]), text)


def _fractions(text: str) -> str:
    return re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine)\s+(half|halves|thirds?|quarters?|fourths?|fifths?|sixths?|eighths?|tenths?)\b", r"\1-\2", text, flags=re.I)


def _cardinals(text: str) -> str:
    def render(match: re.Match[str]) -> str:
        words = match[0].lower().replace("-", " ").split()
        before, after = text[:match.start()], text[match.end():]
        # A fractional quantity with a scale is readable as "0.6 billion".
        if match[0].lower() in SCALES and re.search(r"\d(?:\.\d+)?\s+$", before):
            return match[0]
        value = cardinal(match[0])
        if value is None:
            # "the first two fifty" is an ordinal quantity, not a price.
            if re.search(r"\b(?:first|last|next)\s+$", before, re.I) and len(words) == 2 and words[0] in UNITS and words[1] in TENS:
                return str(UNITS[words[0]] * 100 + TENS[words[1]])
            if all(word in UNITS or word in TENS for word in words) and any(UNITS.get(word, 10) >= 10 for word in words):
                # Spoken groups such as "forty nine ninety nine" are data, but
                # without a price cue they must never acquire a decimal/currency.
                groups, index = [], 0
                while index < len(words):
                    word = words[index]
                    if word in TENS and index + 1 < len(words) and 0 < UNITS.get(words[index + 1], 100) < 10:
                        groups.append(str(TENS[word] + UNITS[words[index + 1]]))
                        index += 2
                    else:
                        groups.append(str(UNITS.get(word, TENS.get(word))))
                        index += 1
                # X-607 (commandment 55): straight after a price word, two
                # spoken groups are one price: "the price is nineteen ninety
                # nine" -> 19.99. No symbol, because no currency was said.
                if (len(groups) == 2 and len(groups[1]) == 2 and 10 <= int(groups[1]) <= 99
                        and re.search(r"\b(?:prices?|priced|costs?|costing|charges?|fee)\b"
                                      r"(?:\s+(?:is|was|are|were|at|of|comes to|came to))?\s*$", before, re.I)):
                    return f"{groups[0]}.{groups[1]}"
                context = _number_context(before)
                separator = '' if context in {'identifier', 'ssn', 'card', 'phone'} else ', ' if context == 'list' else ' '
                return separator.join(groups)
            return match[0]
        if value < 10 and len(words) == 1:
            # Small counts remain words unless a label or clock anchor requests digits.
            if not re.search(r"\b(?:at|version|page|room|table|group|chapter|section|step)\s+$", before, re.I):
                return match[0]
            if re.match(r"\s+(?:point|half|third|quarter)", after, re.I):
                return match[0]
        if re.match(r"-(?:half|third|quarter|fourth|fifth|sixth|eighth|tenth)", after, re.I):
            return match[0]
        # "in nineteen hundred" is a year, written without a digit comma.
        if (1000 <= value < 2100 and len(words) == 2 and words[1] == "hundred"
                and re.search(r"\b(?:in|since|during|by|before|after|until|year|circa)\s+$", before, re.I)):
            return str(value)
        if value >= 1000 and _number_context(before) not in {'identifier', 'ssn', 'card', 'phone'}:
            return f'{value:,}'
        return str(value)

    return _RUN_RE.sub(render, text)


# --- 2026-09-23: magnitude, sign and version numbers ---------------------------
#
# The assessment measured three ways a number changed its meaning:
# "three to four thousand dollars" became "$3 to $4 thousand" (three dollars,
# not three thousand), "negative five degrees" stayed in words, and "version
# two point ten" became "2 point 10" in the rules lane.

_SMALL_CARDINAL = (
    r"(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?"
    r"|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
    r"|one|two|three|four|five|six|seven|eight|nine)"
)
_TWO_DIGIT_CARDINAL = (
    r"(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?"
    r"|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"
)
_SCALED_RANGE_RE = re.compile(
    rf"\b(?P<a>{_SMALL_CARDINAL}|\d{{1,3}})\s+(?P<conj>to|or|through)\s+(?P<b>{_SMALL_CARDINAL}|\d{{1,3}})\s+"
    rf"(?P<scale>hundred|thousand|million|billion)\b(?!\s+(?:and\s+)?{_WORD}\b)"
    r"(?:\s+(?P<currency>dollars?|pounds?|euros?))?",
    re.IGNORECASE,
)
_SCALE_VALUES = {"hundred": 100, "thousand": 1000, "million": 1000000, "billion": 1000000000}
_CURRENCY_SIGNS = {"dollar": "$", "pound": chr(163), "euro": chr(8364)}


def _scaled_ranges(text: str) -> str:
    """"three to four thousand dollars" -> "$3,000 to $4,000".

    A scale said once at the end of a range belongs to both ends; otherwise
    the first number reads as three dollars. Hundreds and thousands are
    written out ("3,000"), millions and billions keep the word ("$2 million
    to $3 million"), matching how the single amounts are written."""
    def render(match: re.Match[str]) -> str:
        before = re.findall(r"[A-Za-z0-9]+", text[:match.start()])
        if before and (before[-1].lower() in UNITS or before[-1].lower() in TENS
                       or before[-1].lower() in SCALES or before[-1].lower() == "hundred"):
            return match[0]
        low, high = _amount(match["a"]), _amount(match["b"])
        if low is None or high is None or not 0 < int(low) < int(high) < 1000:
            return match[0]
        scale = match["scale"].lower()
        sign = _CURRENCY_SIGNS[match["currency"].lower().rstrip("s")] if match["currency"] else ""
        if scale in {"hundred", "thousand"}:
            first = f"{sign}{int(low) * _SCALE_VALUES[scale]:,}"
            second = f"{sign}{int(high) * _SCALE_VALUES[scale]:,}"
        else:
            first, second = f"{sign}{low} {scale}", f"{sign}{high} {scale}"
        return f"{first} {match['conj'].lower()} {second}"

    return _SCALED_RANGE_RE.sub(render, text)


_SIGNED_RE = re.compile(
    rf"\b(?P<sign>negative|minus)\s+(?P<num>[$£€]?\d+(?:\.\d+)?%?|{_RUN})\b(?P<after>\s+[A-Za-z°%]+)?",
    re.IGNORECASE,
)
_SIGNED_UNITS_RE = re.compile(r"\s+(?:degrees?|°|percent|points?|celsius|fahrenheit|kelvin)\b", re.I)
# "minus" is also subtraction ("ten minus five"); as a sign it follows a word
# that introduces a value, or it is measured in a unit.
_MINUS_AS_SIGN_BEFORE = frozenset(
    "is was it's at to of hit reached around about from be been stays stayed feels felt drops dropped "
    "fell falls sits sat hovering hovers".split()
)


def _signed_numbers(text: str) -> str:
    """"negative five degrees" -> "-5 degrees"; "ten minus five" is left alone."""
    def render(match: re.Match[str]) -> str:
        number, after = match["num"], match["after"] or ""
        unit = bool(_SIGNED_UNITS_RE.match(after))
        before = re.findall(r"[A-Za-z0-9'$%]+", text[:match.start()])
        previous = before[-1].lower() if before else ""
        if previous and (previous[-1].isdigit() or previous in UNITS or previous in TENS or previous in SCALES):
            return match[0]
        if match["sign"].lower() == "minus" and not unit and previous not in _MINUS_AS_SIGN_BEFORE:
            return match[0]
        if not re.match(r"[$£€]?\d", number):
            value = cardinal(number)
            # "the negative one" is a pronoun, not a number.
            if value is None or (number.lower() == "one" and not unit):
                return match[0]
            number = f"{value:,}" if value >= 1000 else str(value)
        return "-" + number + after

    return _SIGNED_RE.sub(render, text)


_VERSION_CUE = (
    r"(?:version|v|release|build|python|node|ios|macos|android|windows|java|php|ruby|swift|kotlin|"
    r"chrome|firefox|sdk|ubuntu|django|react|typescript|kernel|rust)"
)
_VERSION_RE = re.compile(
    rf"\b(?P<cue>{_VERSION_CUE})\s+(?P<major>{_SMALL_CARDINAL}|\d{{1,3}})\s+point\s+(?P<minor>{_TWO_DIGIT_CARDINAL})\b"
    rf"(?!\s+(?:point\b|{_DIGIT}\b))",
    re.IGNORECASE,
)


def _versions(text: str) -> str:
    """"version two point ten" -> "version 2.10", as spoken: never "2.1".

    A version's minor number is a whole number ("ten"), unlike a decimal's
    digits ("two point one two" is 2.12, handled by _decimals). Only after a
    version cue, where "point ten" cannot be a decimal fraction."""
    def render(match: re.Match[str]) -> str:
        major, minor = _amount(match["major"]), _amount(match["minor"])
        if major is None or minor is None:
            return match[0]
        return f"{match['cue']} {major}.{minor}"

    def paired(match: re.Match[str]) -> str:
        major, minor = _amount(match["major"]), _amount(match["minor"])
        if major is None or minor is None:
            return match[0]
        return f"{match['conj']} {major}.{minor}"

    text = _VERSION_RE.sub(render, text)
    # X-602 (MIX22): "version two point one and two point ten" -- the second
    # version shares the first one's cue, so it is 2.10, never "two point 10".
    if _VERSION_CUE_NEAR_RE.search(text):
        text = _PAIRED_VERSION_RE.sub(paired, text)
    return text


_VERSION_CUE_NEAR_RE = re.compile(rf"\b{_VERSION_CUE}\s+(?:\d|{_SMALL_CARDINAL}\b)", re.IGNORECASE)
_PAIRED_VERSION_RE = re.compile(
    rf"\b(?P<conj>and|or|to|vs|versus|from|than)\s+(?P<major>{_SMALL_CARDINAL}|\d{{1,3}})\s+point\s+"
    rf"(?P<minor>{_TWO_DIGIT_CARDINAL})\b(?!\s+(?:point\b|{_DIGIT}\b))",
    re.IGNORECASE,
)
# The year said after a spoken date: "september eighteenth twenty twenty
# seven" is "September 18th, 2027" (C058; it came out "18th 20 27").
_DATE_YEAR_RE = re.compile(
    rf"\b(?P<date>(?:{MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th))\s*,?\s+(?P<century>eighteen|nineteen|twenty)\s+"
    rf"(?P<tail>oh\s+{_DIGIT}|{_TWO_DIGIT_CARDINAL})\b",
    re.IGNORECASE,
)


def _date_years(text: str) -> str:
    def render(match: re.Match[str]) -> str:
        century = cardinal(match["century"])
        tail = match["tail"].lower()
        rest = cardinal(tail.removeprefix("oh ").replace("-", " "))
        if century is None or rest is None or not 0 <= rest < 100 or (rest < 10 and not tail.startswith("oh ")):
            return match[0]
        return f"{match['date']}, {century * 100 + rest}"

    return _DATE_YEAR_RE.sub(render, text)


_IDIOMS = (
    # Idiomatic numbers are written the way people write them (commandment
    # 61): 24/7, 50/50, one-on-one. X-607, owner's call 2026-09-24: the spec
    # wins over the older pinned "one on one".
    (re.compile(r"\btwenty[ -]four[ -]seven\b", re.IGNORECASE), "24/7"),
    (re.compile(r"\bfifty[ -]fifty\b", re.IGNORECASE), "50/50"),
    (re.compile(r"\bone[ -]on[ -]one\b", re.IGNORECASE), lambda m: "One-on-one" if m[0][0] == "O" else "one-on-one"),
)


def normalize_numbers(text: str) -> str:
    def normalize(prose: str) -> str:
        for pattern, idiom in _IDIOMS:
            prose = pattern.sub(idiom, prose)
        if re.search(r'\bpoint\b', prose, re.I):
            prose = _decimals(_versions(prose))
        prose = _date_years(_dates(_years(prose)))
        prose = _quarters(prose)
        prose = _scaled_ranges(prose)
        prose = _scaled_money(prose)
        prose = _money(prose)
        if re.search(r'\b(?:percent|per\s+cent)\b', prose, re.I):
            prose = re.sub(rf"\b({_AMOUNT})\s+per\s+cent\b|\b({_AMOUNT})\s+percent\b", lambda m: (_amount(m[1] or m[2]) + "%") if _amount(m[1] or m[2]) is not None else m[0], prose, flags=re.I)
        if re.search(r'\b(?:negative|minus)\b', prose, re.I):
            prose = _signed_numbers(prose)
        prose = _cardinals(_fractions(prose))
        prose = _digit_runs(prose)
        # Adjectival compounds have singular units; plural predicate phrases stay spaced.
        prose = re.sub(r"\b(\d+)\s+(year|month|day|hour|minute|second)\s+old\b", r"\1-\2-old", prose, flags=re.I)
        return prose

    return map_prose(text, normalize)
