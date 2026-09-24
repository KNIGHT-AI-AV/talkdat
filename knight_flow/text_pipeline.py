from __future__ import annotations

import difflib
import json
import logging
import re
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import LOCAL_FORMATTER_MODEL
from .llm import llm_rewrite
from .plugins import plugin_text_filters, plugin_transform

log = logging.getLogger(__name__)


# "I mean" is deliberately not in this list. It is padding in "it's, I mean,
# quite good" and a retraction marker in "call mom, I mean call dad" -- a regex
# cannot tell those apart, and the model can. Stripping it here turned the
# second case into "call mom, call dad" before anything intelligent saw it,
# which destroyed the only evidence a correction had been made and left the
# model guessing which name was meant. It guessed right often enough to look
# fine and wrong often enough to fail an end-to-end test intermittently.
#
# The model removes it as filler where it is filler, so nothing is lost by
# leaving it in.
FILLER_RE = re.compile(
    # X-114: ooh/ohh/mmm/mhm joined the list -- recognizers keep real-word
    # interjections that trained-out fillers (um, uh) never survive, which is
    # why "and ooh" reached the founder's screen. "oh" alone stays: it
    # carries meaning ("oh no", "oh right") that "ooh" never does.
    #
    # X-602 (docs/DICTATION-COMMANDMENTS.md 14, 15): two classes left this
    # list. A hyphenated response word is a word: "uh-uh" means no, "uh-huh"
    # yes, "uh-oh" trouble, and the old \b let "uh" match inside each one, so
    # "uh-uh, that's not what I said" lost its answer. And "kind of", "kinda",
    # "sort of" and "sorta" are hedges: "it's kind of expensive" is a weaker
    # claim than "it's expensive", and deleting them changed what was said.
    # Whether a hedge is padding is a judgment the rules cannot make, so the
    # rules keep it (the validator refuses a finish that drops one).
    r"(?<![\w'-])(?:um+|uh+|erm+|ah+|hmm+|ooh+|ohh+|mmm+|mhm+|you know)(?![\w'-])[\s,]*",
    re.IGNORECASE,
)
SPACING_RE = re.compile(r"\s+")
# A hesitation sound between two commas: the commas are the recognizer
# marking the pause, and they go with the sound (commandment 9): "we need,
# um, three copies" is "we need three copies", not "we need, three copies".
_HESITATION_RE = r"(?:um+|uh+|erm+|ah+|hmm+|ooh+|ohh+|mmm+|mhm+)"
_PAUSE_COMMA_RE = re.compile(rf"(?<=\w)\s*,\s*(?={_HESITATION_RE}(?![\w'-])\s*,)", re.IGNORECASE)
# "um" is also a word: Portuguese "um dia" is "one day" (commandment 16; the
# field report was "um" deleted from Portuguese as a filler). It stays when
# what follows is Portuguese or Spanish. Two markers in the next three words,
# so an English "um the de facto standard" still loses its hesitation.
_ROMANCE_MARKERS = frozenset("""
dia dias cada vez de da do das dos uma um que com para por muito muita pouco mais bem bom boa obrigado
obrigada nao não sim hoje amanha amanhã noite tarde el la los las en es un una y muy gracias hola
""".split())


# 2026-09-23: "you know what i mean" became "What I mean." "you know" is a
# filler only when it is padding ("it was, you know, a long day"). With a
# subject-taking word before it ("do you know", "if you know", "I know you
# know") or an object after it ("you know what", "you know that", "you know
# it") it is the verb "know" and the sentence needs it.
_YOU_KNOW_GOVERNORS = frozenset(
    "do did does don't didn't doesn't if as whether that because since now unless when "
    "before until i we they know think hope guess bet sure believe glad what how".split()
)
_YOU_KNOW_OBJECTS = frozenset(
    "what how why where when who whom whose which whether if that it him her them me us "
    "everything nothing something anything everyone someone anyone exactly".split()
)
_FILLER_WORD_RE = re.compile(r"[A-Za-z']+")
# X-603 (commandment 10, C010): "like" between a copula and an intensifier is
# padding ("it was like really slow", "she's like so tired"). Everywhere else
# it may be the verb or a comparison ("I like it", "it was like a dream",
# "the effect is like so many others"), and the words stay.
_PADDING_LIKE_RE = re.compile(
    r"\b(?P<copula>is|was|were|are|am|be|been|it's|that's|he's|she's|we're|they're|i'm|you're)\s*,?\s+like\s*,?\s+"
    r"(?=(?:really|totally|so(?!\s+(?:many|much|few|little)\b)|very|super|literally|completely|absolutely|pretty|"
    r"kinda|kind of|sort of)\b)",
    re.IGNORECASE,
)


def remove_fillers(text: str) -> str:
    text = _PAUSE_COMMA_RE.sub(" ", text)

    def drop(match: re.Match[str]) -> str:
        word = match.group(0).lower()
        if word.startswith("um"):
            following = [w.lower() for w in _FILLER_WORD_RE.findall(text[match.end():])[:3]]
            if sum(w in _ROMANCE_MARKERS for w in following) >= 2:
                return match.group(0)
        if word.startswith("you know"):
            before = _FILLER_WORD_RE.findall(text[:match.start()])
            after = _FILLER_WORD_RE.match(text[match.end():].lstrip(" ,"))
            previous = before[-1].lower() if before else ""
            following = after.group(0).lower() if after else ""
            if previous in _YOU_KNOW_GOVERNORS or following in _YOU_KNOW_OBJECTS:
                return match.group(0)
        return ""

    text = FILLER_RE.sub(drop, text)
    return _PADDING_LIKE_RE.sub(lambda match: match["copula"] + " ", text)
PUNCT_SPACE_RE = re.compile(r"\s+([,.;:!?])")
END_PRESS_ENTER_RE = re.compile(r"(?:\s+|^)(?:press|hit)\s+enter[\s.!?]*$", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+|www\.\S+|\[[^\]]+\]\([^)]+\)|<a\s+[^>]*>.*?</a>", re.IGNORECASE)
COMMON_CORRECTIONS = [
    (re.compile(r"\btheir going to\b", re.IGNORECASE), "they're going to"),
    (re.compile(r"\bthere not\b", re.IGNORECASE), "they're not"),
    (re.compile(r"\btommorow\b", re.IGNORECASE), "tomorrow"),
]

_POINT_DECIMAL_PREFIX_RE = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
    r"billion|\d+)\s*$",
    re.IGNORECASE,
)


@dataclass
class ProcessedText:
    original: str
    text: str
    send_enter: bool = False
    route: str = "rules"
    notice: str = ""
    # The validator's reason code when a model answer was refused ("" else).
    rejection: str = ""
    # X-604: a spoken Enter that was NOT pressed because the take went into a
    # terminal, where Talk DAT! never runs a command for the person.
    held_enter: bool = False


def normalize_spaces(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = PUNCT_SPACE_RE.sub(r"\1", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [part.strip(" -\t") for part in parts if part.strip(" -\t")]


def capitalize_sentences(text: str) -> str:
    if not text:
        return text

    def cap(match: re.Match[str]) -> str:
        prefix, char = match.group(1), match.group(2)
        return f"{prefix}{char.upper()}"

    text = re.sub(r"(^|[.!?]\s+|\n+)([a-z])", cap, text)
    text = re.sub(r"\bi\b", "I", text)
    text = re.sub(r"\bai\b", "AI", text, flags=re.IGNORECASE)
    return text


def add_terminal_punctuation(text: str) -> str:
    if not text:
        return text
    if text.endswith((".", "!", "?", ":", ";", ")", "]", '"', "'")):
        return text
    if "\n" in text or len(text.split()) <= 3:
        return text
    return text + "."


def apply_smart_newlines(text: str) -> str:
    from .formatting import apply_spoken_punctuation
    from .spoken_commands import layout_command_stands_alone

    text = apply_spoken_punctuation(text)
    replacements = [
        (r"\bnew paragraph\b", "\n\n"),
        (r"\bnew line\b", "\n"),
        (r"\bnext line\b", "\n"),
        (r"\btab key\b", "\t"),
    ]
    for pattern, value in replacements:
        # X-602 (commandment 47): "she started a new paragraph in the
        # contract" is a sentence about a paragraph, not a layout command.
        text = re.sub(
            pattern,
            lambda match, value=value: value if layout_command_stands_alone(match.string, match.start(), match.end())
            else match.group(0),
            text,
            flags=re.IGNORECASE,
        )

    bullet_matches = list(re.finditer(r"\bbullet point\b", text, flags=re.IGNORECASE))
    if len(bullet_matches) >= 2:
        text = re.sub(r"\bbullet point\b\s*", "\n- ", text, flags=re.IGNORECASE)
    else:
        # A lone phrase such as "use a bullet point" is prose, not a command.
        # Single spoken commands are accepted only at the start of an utterance.
        text = re.sub(r"^\s*bullet point\b\s*", "\n- ", text, flags=re.IGNORECASE)
    for number, word in enumerate(
        ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"),
        start=1,
    ):
        text = re.sub(rf"\bnumber\s+{word}\b\s*", f"\n{number}. ", text, flags=re.IGNORECASE)

        def point_or_decimal(match: re.Match[str]) -> str:
            before = match.string[max(0, match.start() - 32):match.start()]
            if _POINT_DECIMAL_PREFIX_RE.search(before):
                return match.group(0)
            return f"\n{number}. "

        text = re.sub(
            rf"\bpoint\s+{word}\b\s*",
            point_or_decimal,
            text,
            flags=re.IGNORECASE,
        )
    return text


def remove_previous_phrase(text: str) -> str:
    text = text.rstrip()
    if not text:
        return ""

    sentence_boundaries = ".!?\n"
    stripped = text.rstrip(" \t")
    if stripped and stripped[-1] in sentence_boundaries:
        search_end = len(stripped) - 1
    else:
        search_end = len(stripped)

    boundary = max(stripped.rfind(mark, 0, search_end) for mark in sentence_boundaries)
    if boundary >= 0:
        return stripped[: boundary + 1].rstrip()
    return ""


def apply_backtrack(text: str) -> str:
    """Spoken correction commands, applied only where they ARE commands.

    2026-09-23: these were plain substring searches, so "please delete that
    file from the server" lost everything up to "file", "can you cancel that
    order" lost its request, and "my favorite song is scratch that by the band"
    became "By the band." -- before any model, with nothing able to restore
    the words. A command now acts only when it stands alone: nothing before it
    makes it part of a sentence ("please", "you", "to", "is"...), and it ends
    the take, meets a pause or another command, or is followed by a restarted
    clause ("scratch that send it to finance"). See spoken_commands.py.
    """
    from .spoken_commands import ERASE_COMMANDS, WIPE_COMMANDS, find_standalone

    # A wipe command discards everything before the LAST standalone one.
    last = None
    for phrase in WIPE_COMMANDS:
        position = 0
        while (match := find_standalone(text, phrase, position)) is not None:
            if last is None or match.end() > last.end():
                last = match
            position = match.end()
    if last is not None:
        text = text[last.end():].lstrip(" ,.;:-").strip()
    for phrase in ERASE_COMMANDS:
        # "delete last sentence" is never ordinary grammar, so only the word
        # before it is checked; the others must also be followed by a restart.
        strict = phrase != "delete last sentence"
        while (match := find_standalone(text, phrase, strict_after=strict)) is not None:
            before = remove_previous_phrase(text[:match.start()].rstrip())
            after = text[match.end():].lstrip(" ,.;:-")
            text = normalize_spaces(f"{before} {after}")
    # "delete last word" is followed by the replacement word, not a clause.
    while (match := find_standalone(text, "delete last word", strict_after=False)) is not None:
        before = re.sub(r"\s*\S+$", "", text[:match.start()].rstrip())
        after = text[match.end():].lstrip(" ,.;:-")
        text = normalize_spaces(f"{before} {after}")
    return text


def replace_phrase(text: str, source: str, target: str) -> str:
    if not source:
        return text
    pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
    return pattern.sub(target, text)


def apply_dictionary(text: str, config: dict[str, Any]) -> str:
    from .literal_text import map_prose

    replacements = config.get("dictionary", {}).get("replacements", [])
    for item in replacements:
        source = str(item.get("from", "")).strip()
        target = str(item.get("to", "")).strip()
        if source and target:
            text = map_prose(text, lambda prose: replace_phrase(prose, source, target))
    return text


def apply_vocabulary_terms(text: str, config: dict[str, Any]) -> str:
    """Repair names and brands the recognizer spelled as ordinary words.

    Runs after `apply_dictionary` and before formatting. After, because an
    explicit from/to the person wrote themselves is a stated intention and
    should not be second-guessed by a phonetic match. Before formatting, so the
    model and the heuristics see "Talk DAT!" rather than "talk that" and
    punctuate the real sentence instead of a plausible-looking wrong one.

    Silent on any failure. A dictionary entry that cannot be parsed must cost
    the person a missed correction, never their dictation.
    """
    dictionary = config.get("dictionary", {})
    # Two sources on purpose. `words` is the long-standing plain list that the
    # Settings tab renders as one word per line, and `terms` is what the pill's
    # add-words window writes, where an entry may also carry how it sounds.
    # Keeping them apart is what stops a structured entry from being rendered
    # into that text box as a dict repr and saved back as garbage.
    entries = list(dictionary.get("words") or []) + list(dictionary.get("terms") or [])
    try:
        from .vocabulary import Term, apply_vocabulary, parse_terms, with_brand_terms, with_default_terms

        # Defaults are merged even when the user's dictionary is empty -- an
        # empty dictionary is precisely the install that needs the product's
        # own name corrected. The user's terms come first and win; the brand
        # registry ranks last and can be switched off.
        terms = with_default_terms(parse_terms(entries))
        terms = with_brand_terms(terms, enabled=bool(dictionary.get("brand_names", True)))
        # X-34: names harvested from the foreground window's title at
        # dictation start ride in as transient terms -- this dictation only,
        # never stored, never uploaded. They rank BELOW the user's own
        # entries: a personal spelling always outranks a window title.
        screen_names = config.get("_screen_names") or []
        if screen_names and bool(dictionary.get("screen_context", True)):
            # Exclusion is by SOUND, not spelling: if the user taught any
            # spelling that answers to the same key, the screen name stays
            # out entirely -- two same-key terms veto each other inside the
            # matcher, which would cost the user the correction they set up.
            known_keys = {key for term in terms for key, _ in term.sources()}
            extra = []
            for name in screen_names:
                candidate = Term(str(name))
                if any(key in known_keys for key, _ in candidate.sources()):
                    continue
                extra.append(candidate)
            terms = list(terms) + extra
        return apply_vocabulary(text, terms)
    except Exception:
        log.warning("custom vocabulary could not be applied", exc_info=True)
        return text


def expand_snippet_variables(text: str) -> str:
    if "{" not in text:
        return text
    now = time.localtime()
    values = {
        "{date}": time.strftime("%Y-%m-%d", now),
        "{time}": time.strftime("%H:%M", now),
        "{datetime}": time.strftime("%Y-%m-%d %H:%M", now),
        "{day}": time.strftime("%A", now),
    }
    if "{clipboard}" in text:
        try:
            import pyperclip

            values["{clipboard}"] = str(pyperclip.paste() or "")
        except Exception:
            values["{clipboard}"] = ""
    for token, value in values.items():
        text = text.replace(token, value)
    return text


def apply_snippets(text: str, config: dict[str, Any]) -> str:
    snippets = config.get("snippets", [])
    ordered = sorted(snippets, key=lambda item: len(str(item.get("trigger", ""))), reverse=True)
    for item in ordered:
        if isinstance(item, dict) and item.get("enabled", True) is False:
            continue
        trigger = str(item.get("trigger", "")).strip()
        expansion = str(item.get("text", ""))
        if not trigger:
            continue
        stripped = re.sub(r"[.!?]+$", "", text.strip(), flags=re.IGNORECASE)
        if stripped.lower() == trigger.lower():
            return expand_snippet_variables(expansion)
        text = replace_phrase(text, trigger, expand_snippet_variables(expansion))
    return text


PII_PATTERNS = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[email]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[card]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
    (re.compile(r"\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b"), "[phone]"),
]

PROFANITY_RE = re.compile(
    r"\b(fuck\w*|shit\w*|bitch\w*|asshole\w*|bastard\w*|dick\w*|cunt\w*)\b",
    re.IGNORECASE,
)


def redact_sensitive(text: str, config: dict[str, Any]) -> str:
    privacy = config.get("privacy", {})
    if privacy.get("redact_pii", False):
        for pattern, token in PII_PATTERNS:
            text = pattern.sub(token, text)
    if config.get("cleanup", {}).get("censor_profanity", False):
        text = PROFANITY_RE.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), text)
    return text


def cleanup_text(text: str, config: dict[str, Any]) -> str:
    cleanup = config.get("cleanup", {})
    level = str(cleanup.get("level", "medium")).lower()
    if level == "none":
        return normalize_spaces(text)

    if cleanup.get("backtrack", True):
        text = apply_backtrack(text)
    if cleanup.get("smart_newlines", True):
        text = apply_smart_newlines(text)
    if cleanup.get("remove_fillers", True):
        text = remove_fillers(text)
    if cleanup.get("resolve_retractions", True):
        text = resolve_spoken_retractions(text)

    text = normalize_spaces(text)

    if level in {"light", "medium", "high"}:
        text = capitalize_sentences(text)

    if level in {"medium", "high"}:
        for pattern, replacement in COMMON_CORRECTIONS:
            text = pattern.sub(replacement, text)
        text = re.sub(r"\b(?:I think maybe|maybe we maybe|we maybe)\b", "I think", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:just wanted to|I just wanted to)\b", "I wanted to", text, flags=re.IGNORECASE)
        # "very very" and "really really" are emphasis the speaker chose, not
        # a stutter (2026-09-23); they are no longer collapsed here.
        text = add_terminal_punctuation(text)

    if level == "high":
        text = re.sub(r"\b(?:could you please|can you please)\b", "Please", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*,\s*", ", ", text)
        text = capitalize_sentences(text)

    return normalize_spaces(text)



# X-68 behaviors 1/2/7, made deterministic. The model's prompt already asks
# for these repairs, but a sampled model is a coin with provider-dependent
# odds -- measured 97% one week and near 50% another, with the SAME prompt.
# The three canonical spoken-retraction shapes carry their own evidence
# (a repeated clause head, or an exact repeated phrase), so they resolve
# here, deterministically, and the model can only polish the result.
#
# Deliberately narrow: nothing here deletes a bare "not X" -- a negation
# without a restart anchor is meaning, not a retraction.

# "how is, how is, not OpenRouter, how is Wispr Flow..." -> the restart
# after "not X," wins when it repeats the stuttered clause head.
_RETRACT_RESTART_RE = re.compile(
    r"\b([A-Za-z']+(?:\s+[A-Za-z']+){0,2}),\s+(?:\1,\s+)*not\s+[^,]{1,40},\s+(?=\1\b)",
    re.IGNORECASE,
)
# "call mom, I mean call dad" -> the phrase after "I mean" wins when it
# repeats the head word(s) of the phrase before it.
_I_MEAN_RE = re.compile(
    r"\b([A-Za-z']+(?:\s+[A-Za-z']+)?)\s+[^,]{1,40},\s*I mean,?\s+(?=\1\b)",
    re.IGNORECASE,
)
# "send the production report, no actually the revised report" carries an
# equally strong deterministic signal when the abandoned phrase and its
# replacement share the same head noun. Restricting the rule to that repeated
# head is what makes it safe: a free-standing "no, actually" still goes to the
# model because the rules cannot know how far back the correction reaches.
_NO_ACTUALLY_SHARED_HEAD_RE = re.compile(
    r"\b(?:the|a|an)\s+(?:[A-Za-z0-9'-]+\s+){0,3}(?P<head>[A-Za-z0-9'-]+)"
    r"\s*,?\s*no\s*,?\s*actually\s*,?\s*"
    r"(?P<replacement>(?:the|a|an)\s+(?:[A-Za-z0-9'-]+\s+){0,3}(?P=head)\b)",
    re.IGNORECASE,
)
# "we need to, we need to fix this" -> one take of an exactly repeated
# 2-6 word phrase.
_STUTTER_PHRASE_RE = re.compile(
    r"\b([A-Za-z']+(?:\s+[A-Za-z']+){1,5}),\s+(?=\1\b)",
    re.IGNORECASE,
)


# --- X-602: restarts the rules can settle without a model -------------------
#
# docs/DICTATION-COMMANDMENTS.md section 6.8 measured the 4B merging these the
# wrong way, and the validator accepting it: "all of the, some of the tests
# failed" became "All of the tests failed." and "we might, we will need the
# second server" became "We might need the second server." Both keep the
# ABANDONED word. Commandments 13, 21, 28, 29 and 35: the speaker's later
# words are the settled ones, and the negation, modal or quantifier in them
# is the meaning.
#
# The evidence is in the words, so the rules decide: a short fragment that
# opens a clause, a comma or dash (optionally a cue), and a restatement that
# repeats the fragment word for word except that ONE closed-class word was
# swapped for another of its class (a modal for a modal, a quantifier for a
# quantifier), or that simply extends it ("I can, sorry, I cannot..."). The
# restatement must run on past the fragment, and the fragment must start a
# clause, so "we can, we should, we must act" and "a plan, a real plan" stay.
_RESTART_SEPARATOR_RE = re.compile(
    r"\s*(?:,|\u2014|\u2013|--)\s*"
    r"(?:(?:no wait|wait no|sorry|no|i mean|i meant|or rather|actually)\s*(?:,|\u2014|\u2013|--)?\s*)?",
    re.IGNORECASE,
)
_RESTART_AUX = frozenset(
    "can could will would shall should may might must do does did is are was were am be have has had".split()
)
_RESTART_QUANTIFIERS = frozenset(
    "all some most many few none no every each any both several half much more less only".split()
)
_RESTART_APPROXIMATORS = frozenset(
    "about around roughly approximately exactly precisely nearly almost over under just".split()
)
_RESTART_CLASSES = (_RESTART_AUX, _RESTART_QUANTIFIERS, _RESTART_APPROXIMATORS)
# A fragment is visibly unfinished when it stops on one of these.
_RESTART_DANGLING = _RESTART_AUX | _RESTART_QUANTIFIERS | _RESTART_APPROXIMATORS | frozenset(
    "the a an to of in on at for with from by and or but this that these those my our your their his her its".split()
)
_RESTART_OPENERS = frozenset("and but so then because if when okay ok well yeah".split())
_RESTART_EXPANSIONS = {
    "don't": ("do", "not"), "doesn't": ("does", "not"), "didn't": ("did", "not"), "can't": ("can", "not"),
    "cannot": ("can", "not"), "won't": ("will", "not"), "wouldn't": ("would", "not"),
    "shouldn't": ("should", "not"), "couldn't": ("could", "not"), "mustn't": ("must", "not"),
    "isn't": ("is", "not"), "aren't": ("are", "not"), "wasn't": ("was", "not"), "weren't": ("were", "not"),
    "haven't": ("have", "not"), "hasn't": ("has", "not"), "hadn't": ("had", "not"),
    "it's": ("it", "is"), "that's": ("that", "is"), "there's": ("there", "is"), "what's": ("what", "is"),
    "i'm": ("i", "am"), "we're": ("we", "are"), "you're": ("you", "are"), "they're": ("they", "are"),
    "he's": ("he", "is"), "she's": ("she", "is"), "i'll": ("i", "will"), "we'll": ("we", "will"),
    "you'll": ("you", "will"), "they'll": ("they", "will"), "he'll": ("he", "will"), "she'll": ("she", "will"),
    "it'll": ("it", "will"), "i've": ("i", "have"), "we've": ("we", "have"), "you've": ("you", "have"),
    "they've": ("they", "have"),
}
_RESTART_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def _restart_expand(words: list[str]) -> list[str]:
    expanded: list[str] = []
    for word in words:
        expanded.extend(_RESTART_EXPANSIONS.get(word.lower(), (word.lower(),)))
    return expanded


def _is_restart(fragment: list[str], restatement: list[str]) -> bool:
    """Whether `restatement` re-says `fragment` with the settled wording."""
    said, again = _restart_expand(fragment), _restart_expand(restatement)
    if len(again) <= len(said):
        return False
    if again[:len(said)] == said:
        if len(fragment) == 1:
            # "don't, do not ship": only a contraction restated in full.
            return fragment[0].lower() in _RESTART_EXPANSIONS and len(said) == 2
        return fragment[-1].lower() in _RESTART_DANGLING or said[-1] == "not"
    if len(said) < 2:
        return False
    differing = [index for index, (one, two) in enumerate(zip(said, again)) if one != two]
    if len(differing) != 1:
        return False
    one, two = said[differing[0]], again[differing[0]]
    return any(one in group and two in group for group in _RESTART_CLASSES)


def resolve_restarts(text: str) -> str:
    """Keep the restatement of an abandoned clause opening, drop the opening.

    "we might, we will need the second server" -> "we will need the second
    server"; "all of the, some of the tests failed" -> "some of the tests
    failed"; "I can, sorry, I cannot approve that" -> "I cannot approve
    that"; "don't, do not ship" -> "do not ship"."""
    for _ in range(8):
        changed = False
        for separator in _RESTART_SEPARATOR_RE.finditer(text):
            before, after = text[:separator.start()], text[separator.end():]
            # The fragment opens a clause: the take's start, a sentence mark,
            # or a conjunction/discourse word -- never the middle of a list.
            boundary = max(before.rfind(mark) for mark in ".!?;:\n,\u2014\u2013")
            clause = before[boundary + 1:]
            words = list(_RESTART_WORD_RE.finditer(clause))
            opener = 0
            for index, word in enumerate(words):
                if word.group(0).lower() in _RESTART_OPENERS:
                    opener = index + 1
            fragment = words[opener:]
            if not 1 <= len(fragment) <= 4:
                continue
            if boundary >= 0 and before[boundary] == "," and opener == 0:
                # After a comma it may be one of a series ("we can, we
                # should, we must act"): a previous clause opening with the
                # same word says so, and the words stay.
                earlier = before[:boundary]
                previous = earlier[max(earlier.rfind(mark) for mark in ".!?;:\n,\u2014\u2013") + 1:]
                first = _RESTART_WORD_RE.search(previous)
                if first is None or first.group(0).lower() == fragment[0].group(0).lower():
                    continue
            # The restatement runs on past the fragment before the next mark.
            run = re.match(r"[^.!?;:,\n\u2014\u2013]*", after)
            restated = [w.group(0) for w in _RESTART_WORD_RE.finditer(run.group(0) if run else "")]
            if not _is_restart([w.group(0) for w in fragment], restated[:len(fragment) + 3]):
                continue
            if len(_restart_expand(restated)) <= len(_restart_expand([w.group(0) for w in fragment])):
                continue
            start = boundary + 1 + fragment[0].start()
            text = text[:start] + after
            changed = True
            break
        if not changed:
            break
    return text


# "don't send it today, actually, send it today": the correction restates the
# same verb and object, so it settles the clause, negation included (C28).
_CLAUSE_RESTATEMENT_RE = re.compile(
    r"(?:^|(?<=[.!?;:,]))\s*"
    r"(?P<old>(?:(?:don't|do not|never|not)\s+)?(?P<verb>[a-z]+)\s+(?P<obj>it|them|this|that|him|her|us)\b[^,.;!?\n]{0,40}?)"
    r"(?:\s*,\s*(?:actually|no|sorry|no wait|wait)|\s+(?:actually|sorry|no wait))\s*,?\s+"
    r"(?P<new>(?:(?:don't|do not|never)\s+)?(?P=verb)\s+(?P=obj)\b)",
    re.IGNORECASE,
)
# "can you check this, I mean merge this": the object repeats, the verb is
# the correction (C32).
_I_MEAN_SHARED_OBJECT_RE = re.compile(
    r"\b(?P<old>[a-z]+)\s+(?P<obj>this|that|it|them)\s*,\s*i mean\s*,?\s+(?P<new>[a-z]+)\s+(?P=obj)\b",
    re.IGNORECASE,
)


# --- X-603: open-slot corrections the words settle (commandments 18 to 20) ---
#
# "tell Alex I'll send it Friday. actually, don't promise Friday; say early
# next week": the correction NAMES what it replaces and supplies the
# replacement, so it may reach into the previous sentence (MIX06, spec case
# 6). Only when the named words appear earlier in the take, word for word,
# and the replacement is a phrase, not a new clause: "don't promise Friday,
# we can't commit to a day" is a new thought and every word stays.
_NAMED_SLOT_CORRECTION_RE = re.compile(
    r"(?:^|(?<=[.!?;,]))\s*(?:actually|no|no wait|wait|sorry)\s*,?\s+"
    r"(?:don't|do not)\s+(?:promise|say|write|put|use|mention|send|book|pick|choose)\s+"
    r"(?P<old>[^,.;:!?\n]{1,40}?)\s*[;,]\s*"
    r"(?:say|put|write|use|make it|go with|book|pick|choose|send)\s+"
    r"(?P<new>[^,.;:!?\n]{1,40}?)\s*(?:[.!?]+\s*)?$",
    re.IGNORECASE,
)
_CLAUSE_WORDS = frozenset(
    "i we you they he she it that this there is are was were will would can can't cannot could should "
    "must might may do does did don't doesn't didn't won't have has had am be been".split()
)


def _resolve_named_slot_corrections(text: str) -> str:
    match = _NAMED_SLOT_CORRECTION_RE.search(text)
    if not match:
        return text
    old, new = match["old"].strip(), match["new"].strip()
    words = [w.lower() for w in re.findall(r"[A-Za-z']+", new)]
    if not words or len(words) > 5 or any(word in _CLAUSE_WORDS for word in words):
        return text
    before = text[:match.start()]
    earlier = list(re.finditer(rf"(?<![\w'-]){re.escape(old)}(?![\w'-])", before, re.IGNORECASE))
    if not earlier:
        return text
    last = earlier[-1]
    return normalize_spaces(before[:last.start()] + new + before[last.end():])


# "please send the deck to marketing, actually legal, by friday": one word
# set off by commas and corrected by one word of the same kind (MIX17). The
# commas are the evidence: "I actually liked it", "we went, actually, on
# Monday" and "call sam, actually tomorrow, about it" (a time for a name)
# all keep their words.
_SLOT_WORD_CORRECTION_RE = re.compile(
    r"(?<![\w'-])(?P<old>[A-Za-z][A-Za-z'-]{2,}),\s*(?:actually|no wait|wait no|i mean)\s+"
    r"(?P<new>[A-Za-z][A-Za-z'-]{2,})(?P<end>\s*,\s*|\s*(?=[.!?]|$))",
    re.IGNORECASE,
)
_SLOT_FUNCTION_WORDS = frozenset((
    "the a an this that these those my your our their his her its me him them us you we they it "
    "and but or so because then than if when while with without from for to of on in at by about "
    "is are was were be been being am do does did have has had will would can could should must might may "
    "not no yes yeah okay ok well really very just still even again also too there here now once twice "
    "always never maybe probably actually basically literally like mean know think guess"
).split())
_SLOT_TIME_WORDS = frozenset((
    "today tonight tomorrow yesterday morning afternoon evening noon midnight later soon "
    "monday tuesday wednesday thursday friday saturday sunday weekend week month year"
).split())
# The closing comma was the correction's; it stays only where the sentence
# needs it anyway ("it was great, thanks"), not before the slot's own words
# ("legal by friday").
_SLOT_KEEPS_COMMA_BEFORE = frozenset(
    "thanks thank please cheers but so because which who although though since".split()
)


def _resolve_slot_word_corrections(text: str) -> str:
    from .number_text import contains_numeric_language

    def settle(match: re.Match[str]) -> str:
        old, new = match["old"].lower(), match["new"].lower()
        if old in _SLOT_FUNCTION_WORDS or new in _SLOT_FUNCTION_WORDS or new.endswith("ly"):
            return match[0]
        # "we invited the manager, actually Sam, to the meeting": the slot is
        # "the manager", and one word cannot say what replaces the article.
        before = re.findall(r"[A-Za-z']+", match.string[:match.start()])
        if before and before[-1].lower() in {"the", "a", "an", "my", "our", "your", "their", "his", "her", "its",
                                             "this", "that", "these", "those"}:
            return match[0]
        # Numbers have their own resolver, with units and currency.
        if contains_numeric_language(old) or contains_numeric_language(new):
            return match[0]
        if (old in _SLOT_TIME_WORDS) != (new in _SLOT_TIME_WORDS):
            return match[0]
        if not match["end"].strip():
            return match["new"] + match["end"]
        following = re.match(r"[A-Za-z']+", match.string[match.end():])
        keep = bool(following) and following[0].lower() in _SLOT_KEEPS_COMMA_BEFORE
        return match["new"] + (", " if keep else " ")

    return _SLOT_WORD_CORRECTION_RE.sub(settle, text)


def _resolve_clause_restatements(text: str) -> str:
    def restate(match: re.Match[str]) -> str:
        return match.group(0)[:match.start("old") - match.start()] + match.group("new")

    def swap(match: re.Match[str]) -> str:
        if match.group("old").lower() == match.group("new").lower():
            return match.group(0)
        return f"{match.group('new')} {match.group('obj')}"

    text = _CLAUSE_RESTATEMENT_RE.sub(restate, text)
    return _I_MEAN_SHARED_OBJECT_RE.sub(swap, text)


def resolve_spoken_retractions(text: str) -> str:
    from .number_text import contains_numeric_language

    # Only a terminal numeric correction with a repeated role is certain.
    # "at two actually three people came" is a different statement, not this.
    text = re.sub(r"\b(at\s+)\d+(?:\.\d+)?[, .]*\s+actually[, ]+(\d+(?:\.\d+)?)(?=\s*[.!?]*$)", r"\1\2", text, flags=re.I)
    text = _resolve_clause_restatements(resolve_restarts(text))
    text = _resolve_slot_word_corrections(_resolve_named_slot_corrections(text))
    for pattern in (_RETRACT_RESTART_RE, _I_MEAN_RE, _NO_ACTUALLY_SHARED_HEAD_RE):
        previous = None
        while previous != text:
            previous = text
            text = pattern.sub(
                (lambda match: match.group("replacement"))
                if pattern is _NO_ACTUALLY_SHARED_HEAD_RE
                else "",
                text,
            )
    previous = None
    while previous != text:
        previous = text
        text = _STUTTER_PHRASE_RE.sub(lambda m: m[0] if contains_numeric_language(m[1]) else "", text)
    return normalize_spaces(text)


def pre_clean_for_format(text: str, config: dict[str, Any]) -> str:
    """Deterministic content cleanup (voice edits, fillers, corrections) that runs
    before the formatting layer owns punctuation and structure."""
    cleanup = config.get("cleanup", {})
    if cleanup.get("backtrack", True):
        text = apply_backtrack(text)
    if cleanup.get("remove_fillers", True):
        text = remove_fillers(text)
    # X-83: this call is the whole point of the rules above. It was missing --
    # resolve_spoken_retractions existed with its own passing unit test while
    # NOTHING called it, so the end-to-end test kept passing on the model's
    # 97% coin instead of on the deterministic path, and only failed when the
    # provider had a bad night. A helper with no caller is not a feature.
    if cleanup.get("resolve_retractions", True):
        text = resolve_spoken_retractions(text)
    for pattern, replacement in COMMON_CORRECTIONS:
        text = pattern.sub(replacement, text)
    return normalize_spaces(text)


_SENTENCE_MARK_RE = re.compile(r"[.!?]")


def is_bare_fragment(raw: str, formatted: str) -> bool:
    """A name, a word, a short phrase -- an INSERTION, not a sentence.

    X-118 (his logic, verbatim intent): someone dictating "quarterly report"
    into a search box does not want "Quarterly report." -- the period and the
    leading space both fight the field they are inserting into. Four words
    or fewer, no dictated sentence punctuation, not a question: deliver the
    words bare.
    """
    words = formatted.split()
    if not words or len(words) > 4 or len(raw.split()) > 4:
        return False
    if _SENTENCE_MARK_RE.search(raw):
        return False
    trimmed = formatted.rstrip()
    if trimmed.endswith(("?", "!", ":")):
        return False
    return True


_DOTTED_ABBREVIATIONS = {
    "dr", "mr", "mrs", "ms", "jr", "sr", "st", "inc", "co", "corp", "ltd",
    "vs", "etc", "dept", "capt", "sgt", "lt", "col", "gen", "maj", "rev",
    "prof", "vol", "fig", "approx",
}


def strip_fragment_period(text: str) -> str:
    trimmed = text.rstrip()
    if not trimmed.endswith(".") or trimmed.endswith(".."):
        return text
    last_word = trimmed.rstrip(".").rsplit(None, 1)[-1] if trimmed.rstrip(".").split() else ""
    # Only a REAL abbreviation keeps its dot -- "Dr.", "Inc.", a single
    # initial. The first cut of this protected every short word, so "go."
    # and "OK." kept the exact period the rule exists to remove (his field
    # report: "still putting periods when I say a one word phrase").
    if len(last_word) == 1 or last_word.lower() in _DOTTED_ABBREVIATIONS or "." in last_word:
        return text
    return trimmed[:-1]


def _password_take(raw: str, original: str, config: dict[str, Any]) -> ProcessedText:
    """Commandment 78: the words as said, and nothing else runs.

    No model, snippets, dictionary, address composing, plugins or journal
    (complete_prepared_dictation returns at once for this route). A spoken
    Enter still submits the form: the person asked for it.
    """
    from .field_text import password_text
    from .spoken_commands import split_enter_command

    text, send_enter = original.strip(), False
    if config.get("dictation", {}).get("press_enter_command", True):
        text, send_enter = split_enter_command(text)
    return ProcessedText(original=original, text=password_text(text), send_enter=send_enter, route="password")


def process_dictation(raw: str, config: dict[str, Any], *, local_only: bool = False, _preparing: bool = False) -> ProcessedText:
    from .field_context import CONSOLE, PASSWORD, SINGLE_LINE
    from .literal_text import protect_literals, restore_literals

    started = time.perf_counter()
    original = normalize_spaces(raw)
    # X-604: the field the take is going into (field_context.FieldProbe).
    field = str(config.get("_field") or "")
    if field == PASSWORD:
        return _password_take(raw, original, config)
    if field == CONSOLE:
        # Commandment 77: the rules write a command; the model never rewrites one.
        local_only = True
    literal_input = redact_sensitive(raw, config) if config.get("privacy", {}).get("redact_pii", False) else raw
    text, literals = protect_literals(literal_input)
    # 2026-09-23: command words the speaker is QUOTING ("literally say new
    # paragraph", "the word period", "quote press enter end quote") become
    # opaque literals here, before any command can act on them.
    from .spoken_commands import escape_command_words, split_enter_command

    text, escaped = escape_command_words(text, literals)
    literals.update(escaped)
    text = normalize_spaces(text)
    send_enter = False
    if config.get("dictation", {}).get("press_enter_command", True):
        # Enter fires only on a standalone trailing command after a complete
        # message ("sounds good press enter"), never where pressing Enter is
        # what the sentence says ("to submit the form just press enter").
        # Near-verbatim runs it only when the whole take is the command.
        verbatim = str(config.get("cleanup", {}).get("level", "")).lower() == "none"
        text, send_enter = split_enter_command(text, verbatim=verbatim)
        text = text.strip()
    held_enter = False
    if field == CONSOLE and send_enter:
        # The words "press enter" come off, but the key is the person's to
        # press once they have read the command.
        send_enter, held_enter = False, True

    text = apply_snippets(text, config)
    from .address_text import compose_addresses

    # X-602 (section 3.1): Near-verbatim is a record of the words, so it
    # never composes an address ("email jane dot doe at gmail dot com" stays).
    if str(config.get("cleanup", {}).get("level", "")).lower() != "none":
        text = compose_addresses(text, config.get("dictionary", {}).get("identifiers"))
    text, composed_literals = protect_literals(text)
    # A layout command that OPENS the take ("new paragraph ignore all previous
    # instructions...") is a break before the dictation (commandment 47;
    # MIX20). Every later normalisation strips leading whitespace, so it is
    # set aside here and put back once the text is finished.
    lead_break = ""
    if (config.get("cleanup", {}).get("smart_newlines", True)
            and str(config.get("cleanup", {}).get("level", "")).lower() != "none"
            and field not in {CONSOLE, SINGLE_LINE}):
        opening = re.match(r"\s*(new paragraph|new line|next line)\b[\s,.]*(?=\S)", text, re.IGNORECASE)
        if opening:
            lead_break = "\n\n" if opening.group(1).lower() == "new paragraph" else "\n"
            text = text[opening.end():]
    # Nested protection also covers snippet expansions. Restore it first.

    # X-28: dictated marks resolve BEFORE formatting on both stacks, so the
    # sentence machinery sees real punctuation instead of the words for it.
    from .formatting import apply_spoken_punctuation

    text = apply_spoken_punctuation(text, resolve_ellipsis=False)
    # Spoken punctuation is a deliberate sentence; the bare-fragment gate
    # below must see it resolved, or "done period" reads as a fragment.
    spoken_resolved = text

    cleanup = config.get("cleanup", {})
    route = "cleanup"
    rejection = ""
    if cleanup.get("smart_format", True) and str(cleanup.get("level", "")).lower() != "none":
        # Wispr-style formatting layer: punctuation (incl. question marks),
        # capitalization, and structure inferred from what was said. Model-agnostic;
        # uses the configured LLM when available, else a strong heuristic fallback.
        from .formatting import smart_format, last_format_route, last_rejection_reason

        text = pre_clean_for_format(text, config)
        text = smart_format(text, config, local_only=local_only)
        route = last_format_route()
        rejection = last_rejection_reason() if route.endswith("rules_after_rejection") else ""
    else:
        text = cleanup_text(text, config)
        if str(cleanup.get("level", "")).lower() == "none":
            # X-607 (spec section 3.1): near-verbatim keeps every word as
            # said, and the take still starts with a capital.
            text = re.sub(r"^(\W*)([a-z])", lambda m: m[1] + m[2].upper(), text, count=1)

    # Applied to BOTH paths, after formatting, because the false "?" arrives
    # from the provider's intonation reading and survives every route --
    # rules, model, and cleanup alike.
    from .formatting import demote_false_questions

    text = demote_false_questions(text)
    if str(cleanup.get("level", "")).lower() != "none":
        # X-607 (commandment 96): a "press enter" that stayed in the text is
        # an instruction about the key, and the key is called Enter.
        text = re.sub(r"\b(press|hit|tap)\s+enter\b", lambda m: m[1] + " Enter", text, flags=re.I)

    # X-13, the real field bug: vocabulary used to run BEFORE formatting, so
    # the moment it produced "Talk DAT!" the sentence machinery read the
    # brand's exclamation mark as a terminal -- split the sentence there,
    # capitalized the next word, and swapped the bang for a period. That is
    # precisely the half-corrected text Mayowa photographed. The formatter
    # now works on the plain spoken words, and the vocabulary pass stamps
    # names onto FINISHED sentences, where nothing downstream can unspell
    # them.
    #
    # X-118, his architecture, stated and adopted: raw transcription ->
    # intelligent correction -> THEN dictionary replacement. The user's own
    # from->to dictionary moved here from before formatting for the same
    # reason vocabulary did -- the correction level judges the words the
    # person actually said, never pre-substituted ones.
    text = apply_dictionary(text, config)
    text = apply_vocabulary_terms(text, config)

    # X-118: a bare name or phrase is an insertion, not a sentence -- no
    # invented period. (Its leading space is refused in the paste layer.)
    if len(original.split()) <= 4 and not _SENTENCE_MARK_RE.search(original) and is_bare_fragment(spoken_resolved, text):
        text = strip_fragment_period(text)

    from .formatting import strip_em_dashes

    text = strip_em_dashes(text)

    text = restore_literals(text, composed_literals)
    text = restore_literals(text, literals)
    if field in {CONSOLE, SINGLE_LINE}:
        from .field_text import console_text, single_line_text

        text = console_text(text, raw) if field == CONSOLE else single_line_text(text, raw)
    if lead_break and text.strip():
        text = lead_break + text
    from .caret_context import apply_caret_context

    text = apply_caret_context(text, raw, config.get("_caret_context"), config)
    text = redact_sensitive(text, config)
    processed = ProcessedText(original=original, text=text, send_enter=send_enter, route=route,
                              rejection=rejection, held_enter=held_enter)
    if _preparing:
        return processed
    return complete_prepared_dictation(processed, config, local_only=local_only, started=started)


def prepare_dictation(raw: str, config: dict[str, Any], *, local_only: bool = False) -> ProcessedText:
    """Prepare text without plugins, journal writes or any delivery side effect.

    The progressive caller rejects snippets with dynamic variables before using
    this entry point, so it never reads the clipboard while speech is held.
    """
    from .formatting import take_local_finish_notice
    result = process_dictation(raw, config, local_only=local_only, _preparing=True)
    result.notice = take_local_finish_notice()
    return result


def complete_prepared_dictation(processed: ProcessedText, config: dict[str, Any], *,
                               local_only: bool = False, started: float | None = None) -> ProcessedText:
    """Run delivery hooks once, equally for prepared and freshly formatted text."""
    if processed.route == "password":
        # Commandment 78: no plugin sees a password and the journal keeps none.
        return processed
    started = time.perf_counter() if started is None else started
    text = processed.text
    if config.get("_asr_confidence") and str(config.get("_field") or "") != "console":
        # X-608 (commandments 6 and 7): a name the recognizer was unsure of,
        # put back from the dictionary or the screen. Here, on the finished
        # text, so the prepared and the fresh route both get it and the
        # progressive formatter's cache never has to know about confidence.
        # Never in a terminal: a command's arguments are not names.
        from .name_repair import repair_names

        text = repair_names(text, config)
    if processed.notice:
        from .formatting import note_local_finish_refusal
        note_local_finish_refusal(processed.notice)
    for text_filter in plugin_text_filters(config):
        try:
            text = str(text_filter(text, config))
        except Exception:
            continue
    # X-125: the opt-in local journal -- raw vs delivered, per pass, so a
    # formatting failure is a diff instead of an anecdote.
    try:
        from .format_journal import record_formatting

        record_formatting(
            config,
            raw=processed.original,
            final=text,
            stage="paste" if local_only else "refine",
            intensity=str(config.get("cleanup", {}).get("format_intensity", "standard")),
            route=processed.route,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            reason=processed.rejection,
        )
    except Exception:
        log.debug("formatting journal hook skipped", exc_info=True)
    processed.text = text
    return processed


def protect_urls(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        token = f"__TALK_DAT_URL_{len(protected)}__"
        protected[token] = match.group(0)
        return token

    return URL_RE.sub(repl, text), protected


def restore_urls(text: str, protected: dict[str, str]) -> str:
    for token, value in protected.items():
        text = text.replace(token, value)
    return text


def transform_with_ollama(text: str, instruction: str, config: dict[str, Any]) -> str | None:
    ollama = config.get("transforms", {}).get("ollama", {})
    if not ollama.get("enabled"):
        return None

    payload = {
        "model": ollama.get("model", LOCAL_FORMATTER_MODEL),
        "stream": False,
        "prompt": (
            "Rewrite the text according to the instruction. Return only the rewritten text.\n\n"
            f"Instruction: {instruction}\n\nText:\n{text}"
        ),
    }
    data = json.dumps(payload).encode("utf-8")
    try:
        from .net_fence import loopback_ipv4

        request = urllib.request.Request(
            loopback_ipv4(str(ollama.get("url", "http://localhost:11434/api/generate"))),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        output = str(body.get("response", "")).strip()
        return output or None
    except Exception:
        return None


def polish(text: str, config: dict[str, Any]) -> str:
    protected_text, urls = protect_urls(text)
    local_config = dict(config)
    local_config["cleanup"] = {**config.get("cleanup", {}), "level": "high"}
    output = cleanup_text(protected_text, local_config)
    return restore_urls(output, urls)


def make_concise(text: str) -> str:
    text = re.sub(r"\b(?:I wanted to|I am writing to)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:basically|honestly|actually|probably|maybe)\b[\s,]*", "", text, flags=re.IGNORECASE)
    return normalize_spaces(text)


def make_formal(text: str) -> str:
    replacements = {
        "hey": "Hello",
        "thanks": "Thank you",
        "got": "received",
        "thing": "item",
        "stuff": "details",
    }
    output = text
    for source, target in replacements.items():
        output = replace_phrase(output, source, target)
    output = capitalize_sentences(output)
    return add_terminal_punctuation(normalize_spaces(output))


def turn_to_list(text: str) -> str:
    pieces = split_sentences(text)
    if len(pieces) <= 1:
        pieces = [part.strip() for part in re.split(r"\s*(?:,|;|\band\b)\s*", text) if part.strip()]
    return "\n".join(f"- {capitalize_sentences(piece)}" for piece in pieces if piece)


def prompt_engineer(text: str) -> str:
    cleaned = normalize_spaces(text)
    return (
        "Task:\n"
        f"{cleaned}\n\n"
        "Context:\n"
        "- Use the available local project context.\n"
        "- Ask only if a missing detail blocks execution.\n\n"
        "Output:\n"
        "- Provide the completed work or a concise implementation plan.\n"
        "- Include verification steps."
    )


def empathize(text: str) -> str:
    text = normalize_spaces(text)
    if not text:
        return text
    return add_terminal_punctuation(
        "I hear you. " + text[0].lower() + text[1:] if text[0].isupper() else "I hear you. " + text
    )


TONE_INSTRUCTIONS = {
    "polish": "Fix grammar, punctuation, and dictation artifacts. Keep the meaning and voice unchanged.",
    "formal": "Rewrite in a professional, formal tone suitable for business email.",
    "friendly": "Rewrite in a warm, friendly, conversational tone.",
    "concise": "Rewrite as concisely as possible without losing meaning.",
    "turn_to_list": "Rewrite as a clean Markdown bullet list.",
    "empathize": "Rewrite with an empathetic, considerate tone.",
    "translate": "Translate to {target}. Return only the translation.",
}


def transform_text(text: str, transform_id: str, config: dict[str, Any], instruction: str | None = None) -> str:
    transform_id = transform_id.lower()
    plugin_output = plugin_transform(transform_id, text, config)
    if plugin_output is not None:
        return plugin_output

    if not instruction:
        instruction = TONE_INSTRUCTIONS.get(transform_id, transform_id.replace("_", " "))
        if transform_id == "translate":
            target = str(config.get("transforms", {}).get("translate_to", "English")) or "English"
            instruction = instruction.format(target=target)

    llm_output = llm_rewrite(text, instruction, config)
    if llm_output:
        return llm_output
    ollama_output = transform_with_ollama(text, instruction, config)
    if ollama_output:
        return ollama_output

    if transform_id in {"polish", "fix_grammar"}:
        return polish(text, config)
    if transform_id in {"prompt_engineer", "prompt"}:
        return prompt_engineer(text)
    if transform_id in {"turn_to_list", "list"}:
        return turn_to_list(text)
    if transform_id in {"formal", "make_formal"}:
        return make_formal(text)
    if transform_id in {"friendly"}:
        return empathize(text)
    if transform_id in {"concise", "make_concise"}:
        return make_concise(text)
    if transform_id in {"empathize", "empathetic"}:
        return empathize(text)
    if transform_id == "translate":
        return text
    return polish(text, config)


def command_to_transform(command: str) -> str:
    command = command.lower()
    if "prompt" in command:
        return "prompt_engineer"
    if "list" in command or "bullets" in command or "bullet" in command:
        return "turn_to_list"
    if "formal" in command or "professional" in command or "polite" in command:
        return "formal"
    if "concise" in command or "short" in command or "brief" in command:
        return "concise"
    if "empath" in command or "kind" in command:
        return "empathize"
    return "polish"


def unified_diff(before: str, after: str) -> str:
    before_lines = before.splitlines() or [before]
    after_lines = after.splitlines() or [after]
    return "\n".join(
        difflib.unified_diff(before_lines, after_lines, fromfile="before", tofile="after", lineterm="")
    )
