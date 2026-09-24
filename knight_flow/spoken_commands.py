"""Spoken commands act only when they stand alone (2026-09-23).

The assessment of that date measured the command words firing inside
ordinary sentences, before any model, with nothing downstream able to put
the words back:

- "please delete that file from the server" became "File from the server."
- "my favorite song is scratch that by the band" became "By the band."
- "to submit the form just press enter" became "To submit the form just."
  AND pressed Enter, which in a chat app sends the truncated message.
- "the subject line should literally say new paragraph" lost its last words.

The rule this module enforces, for every command: it acts only when it is a
command. That means it is the whole utterance, or it ends the utterance, or
a clear boundary (a pause the recognizer wrote as punctuation, or a restart)
follows it; and in every case the word before it does not make it part of a
sentence ("please delete that", "you press enter", "we need to start over").
"delete that file" is a verb and its object, so it is content. When in doubt
the words are kept: a missed command costs the speaker one manual delete, a
wrong one costs them words they meant to write.
"""
from __future__ import annotations

import re

# A word right before a command phrase that makes the phrase part of the
# sentence: a request ("please", "can you"), a subject ("you", "we", "I"),
# an infinitive or auxiliary ("to", "will", "should"), a copula ("is"), a
# conjunction or sequencing word ("and", "then", "just"), or a verb of saying
# ("says", "type", "literally") that introduces the words as a quotation.
_GOVERNORS = frozenset("""
please pls kindly you i we he she they it someone somebody anyone everyone who
to can could would will shall should must might may cannot can't won't
wouldn't couldn't shouldn't don't doesn't didn't do does did not never
i'll we'll you'll they'll he'll she'll it'll i'd we'd you'd they'd let's let me
us them him her gonna wanna gotta need needs needed want wants wanted try tried
trying going have has had been be is was are were am being isn't wasn't aren't
and or but nor then just simply also still only even so first finally next now
and/or or/and
says said say saying type typed typing write writes wrote read reads spell
spells called named titled labeled labelled literally word words phrase text
button key command option menu the a an this that these those my our your
their his its whose which what when where why how if unless whether because
""".split())

# Words that start a fresh clause after a command: the speaker restarting.
# A word that could be the object of "delete that ___" (a noun) is NOT here,
# which is exactly what keeps "delete that file" as content.
_RESTART_STARTERS = frozenset("""
i i'm i'll i've i'd we we're we'll we've we'd you you're you'll he he's she
she's it it's they they're they'll there there's let's let the a an my our
your his her their this these those actually instead rather no wait sorry ok
okay so make send add put tell ask use write say go give get take bring
invite keep try book schedule meet call email text
""".split())

# "scratch that and then ..." restarts; a bare "and" usually continues the
# object ("delete that and the backup").
_RESTART_PHRASES = ("and then", "i mean", "let me", "what i meant")

# Correction commands, longest first so "scratch that last part" wins over
# "scratch that". The wipe commands discard everything before them.
WIPE_COMMANDS = ("never mind all that", "scratch all that", "delete all that", "forget all that", "start over")
ERASE_COMMANDS = (
    "scratch that last part", "delete that last part", "delete last sentence",
    "scratch that", "strike that", "delete that", "remove that",
    "ignore that", "cancel that", "undo that",
)
WORD_COMMANDS = ("delete last word",)
CORRECTION_COMMANDS = WIPE_COMMANDS + ERASE_COMMANDS + WORD_COMMANDS
_COMMAND_START_RE = re.compile(
    r"\s*(?:" + "|".join(re.escape(p) for p in sorted(CORRECTION_COMMANDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

_BOUNDARY_PUNCT = ".!?;:,\n" + chr(0x2014) + chr(0x2013)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'/]*")


def _last_word(text: str) -> str:
    words = _WORD_RE.findall(text)
    return words[-1].lower() if words else ""


def _first_word(text: str) -> str:
    match = _WORD_RE.match(text.lstrip())
    return match.group(0).lower() if match else ""


def preceded_by_governor(before: str) -> bool:
    """True when the text before a command makes the command grammar.

    A sentence boundary (the start of the take, or punctuation the recognizer
    wrote for a pause) means nothing governs it."""
    stripped = before.rstrip()
    if not stripped or stripped[-1] in _BOUNDARY_PUNCT:
        return False
    return _last_word(stripped) in _GOVERNORS


def command_stands_alone(before: str, after: str, *, strict_after: bool = True) -> bool:
    """Whether a correction command between `before` and `after` is a command.

    It must not be governed by the word before it, and what follows must be
    nothing, a boundary mark, another command, or a restarted clause. A noun,
    a preposition or anything else means the phrase is doing grammatical work
    ("delete that file", "scratch that by the band", "start over on it").
    `strict_after=False` skips the second test for phrases that are never
    ordinary grammar ("delete last word" is followed by its replacement).
    """
    if preceded_by_governor(before):
        return False
    if not strict_after:
        return True
    rest = after.lstrip(" \t")
    if not rest.strip(" \t.!?,;:-" + _BOUNDARY_PUNCT[-2:]):
        return True
    if rest[0] in _BOUNDARY_PUNCT or rest.startswith(("--", " - ")):
        return True
    if _COMMAND_START_RE.match(rest):
        return True
    lowered = rest.lower()
    if any(re.match(rf"{re.escape(phrase)}\b", lowered) for phrase in _RESTART_PHRASES):
        return True
    return _first_word(rest) in _RESTART_STARTERS


# A word after a layout phrase that makes it a noun phrase: "a new paragraph
# IN the contract", "the new line OF code".
_LAYOUT_NOUN_FOLLOWERS = frozenset("of in on about for to at with from into that which is was were has had".split())


def layout_command_stands_alone(text: str, start: int, end: int) -> bool:
    """Whether "new paragraph" / "new line" at text[start:end] is a command.

    X-602 (commandment 47): "she started a new paragraph in the contract"
    became "She started a.\\n\\nIn the contract." Layout commands work only in
    command position: nothing before them governs them ("a", "the", "this",
    "add a"...), and what follows is not a preposition that makes the phrase
    a noun. "i went to the store new paragraph i bought milk" still breaks.
    """
    if preceded_by_governor(text[:start]):
        return False
    return _first_word(text[end:]) not in _LAYOUT_NOUN_FOLLOWERS


def find_standalone(text: str, phrase: str, start: int = 0, *, strict_after: bool = True) -> re.Match[str] | None:
    """The first occurrence of `phrase` at or after `start` that stands alone."""
    pattern = re.compile(rf"(?<![\w'-]){re.escape(phrase)}(?![\w'-])", re.IGNORECASE)
    for match in pattern.finditer(text, start):
        if command_stands_alone(text[:match.start()], text[match.end():], strict_after=strict_after):
            return match
    return None


# --- Enter -------------------------------------------------------------------

_ENTER_RE = re.compile(r"(?:^|(?<=[\s.,!?;:]))(?:press|hit)\s+(?:the\s+)?enter(?:\s+key)?[\s.!?]*$", re.IGNORECASE)
_WHOLE_ENTER_RE = re.compile(r"^\s*(?:press|hit)\s+(?:the\s+)?enter(?:\s+key)?[\s.!?]*$", re.IGNORECASE)
# A clause that cannot stand as the whole message: its main verb is still to
# come, so "press enter" after it is that verb, not a command.
_SUBORDINATE_OPENERS = re.compile(
    r"^(?:to|when|whenever|if|once|after|before|until|till|while|as soon as|so that|in order to|unless)\b",
    re.IGNORECASE,
)
# Words a complete message never ends on: it is still mid-phrase.
_DANGLING_ENDINGS = frozenset("""
the a an to of in on at for with from by and or but so then just simply
please can could would will should must you i we they he she it is are was
were be my our your their his her this that these those
""".split())


def split_enter_command(text: str, *, verbatim: bool = False) -> tuple[str, bool]:
    """(text without the command, whether Enter is pressed).

    The whole take "press enter" is always the command. A trailing one is a
    command only when what precedes it is a complete message on its own:
    not "to submit the form just press enter", "then press enter", "you
    press enter" or "when you are done press enter", where pressing Enter is
    what the sentence is ABOUT. Near-verbatim never runs a trailing command.
    """
    if _WHOLE_ENTER_RE.match(text):
        return "", True
    if verbatim:
        return text, False
    match = _ENTER_RE.search(text)
    if not match:
        return text, False
    before = text[:match.start()]
    if not before.strip():
        return "", True
    if preceded_by_governor(before):
        return text, False
    # The last sentence before the command must be complete.
    sentences = re.split(r"(?<=[.!?;])\s+|\n+", before.strip())
    last = sentences[-1].strip() if sentences else ""
    body = last.rstrip(" ,;:")
    if not body:
        return before.rstrip(" ,"), True
    if _last_word(body) in _DANGLING_ENDINGS:
        return text, False
    ended = last.rstrip()[-1:] in ".!?"
    if not ended and _SUBORDINATE_OPENERS.match(body):
        return text, False
    return before.rstrip(" ,"), True


# --- Literal escapes -----------------------------------------------------------

# Everything the rules lane would otherwise execute. Longest first.
_COMMAND_WORDS = (
    "press enter", "hit enter", "new paragraph", "new line", "next line", "tab key", "bullet point",
    *CORRECTION_COMMANDS,
    "full stop", "question mark", "exclamation point", "exclamation mark", "open parenthesis",
    "close parenthesis", "open paren", "close paren", "open bracket", "close bracket", "semicolon",
    "colon", "comma", "period", "ellipsis", "dash", "hyphen", "slash", "end quote", "close quote",
    "unquote", "open quote", "quote",
)
# After "the word(s)" the address words are words too.
_WORD_ONLY = ("dot", "underscore", "at sign")
_COMMAND_ALT = "|".join(re.escape(word) for word in sorted(_COMMAND_WORDS, key=len, reverse=True))
_WORD_ALT = "|".join(re.escape(word) for word in sorted(_COMMAND_WORDS + _WORD_ONLY, key=len, reverse=True))

_LITERALLY_RE = re.compile(
    r"\bliterally\s+(?:(?:say|says|said|type|types|typed|write|writes|wrote|read|reads|spell|spells|is|was|"
    r"means|mean|called)\s+)?(?P<command>" + _COMMAND_ALT + r")(?![\w'])",
    re.IGNORECASE,
)
# "the word period", "the words new line". The article is required: "in
# other words comma" is the speaker asking for the comma.
_THE_WORD_RE = re.compile(
    r"\bthe\s+(?:word|words|phrase)\s+(?P<command>" + _WORD_ALT + r")(?![\w'])",
    re.IGNORECASE,
)
_SPOKEN_QUOTE_SPAN_RE = re.compile(
    r"\b(?:open\s+)?quote\b(?P<inner>.+?)\b(?:end quote|close quote|unquote)\b", re.IGNORECASE | re.DOTALL
)
_WRITTEN_QUOTE_SPAN_RE = re.compile(r'"(?P<inner>[^"\n]+)"|“(?P<curly>[^”\n]+)”')
_INNER_COMMAND_RE = re.compile(r"(?<![\w'])(?:" + _COMMAND_ALT + r")(?![\w'])", re.IGNORECASE)


def escape_command_words(text: str, taken: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """Keep command words the speaker is quoting, not giving.

    "literally say new paragraph", "the word period", "quote press enter end
    quote" and a command inside written quotes are the words themselves. They
    are swapped for the same opaque literal tokens code and addresses use, so
    no command, punctuation or model pass can act on them, and restored
    verbatim at the end. The escape cue itself ("literally", "the word") is
    the speaker's own word and stays.
    """
    taken = dict(taken or {})
    spans: list[tuple[int, int]] = []
    for pattern in (_LITERALLY_RE, _THE_WORD_RE):
        for match in pattern.finditer(text):
            spans.append(match.span("command"))
    for match in _SPOKEN_QUOTE_SPAN_RE.finditer(text):
        base = match.start("inner")
        for inner in _INNER_COMMAND_RE.finditer(match.group("inner")):
            spans.append((base + inner.start(), base + inner.end()))
    for match in _WRITTEN_QUOTE_SPAN_RE.finditer(text):
        group = "inner" if match.group("inner") is not None else "curly"
        base = match.start(group)
        for inner in _INNER_COMMAND_RE.finditer(match.group(group)):
            spans.append((base + inner.start(), base + inner.end()))
    if not spans:
        return text, {}
    # Merge overlaps; keep the earliest, longest span.
    spans.sort(key=lambda span: (span[0], -span[1]))
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start < merged[-1][1]:
            continue
        merged.append((start, end))
    saved: dict[str, str] = {}
    pieces: list[str] = []
    cursor = 0
    index = len(taken)
    for start, end in merged:
        while True:
            token = f"TDLITERAL{index}TOKEN"
            index += 1
            if token not in taken and token not in saved and token.lower() not in text.lower():
                break
        saved[token] = text[start:end]
        pieces.extend((text[cursor:start], token))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), saved
