"""Make the recognizer's guess into the word the person actually meant.

A speech model writes what it hears using ordinary English spelling, so a name
or a brand it has never seen comes out as the nearest common words. "Talk DAT!"
arrives as "talk that". "Mayowa" arrives as "my yo wa", "maiowa", or "my other".
Nothing is wrong with the audio and nothing is wrong with the model; the word
simply is not in its vocabulary.

Two mechanisms exist and only one of them is under our control:

The provider's own hinting is the first. Deepgram takes a `keyterm` list and
biases decoding toward those strings, which fixes the problem before it happens.
It is strictly better when it works, it is already wired to `dictionary.words`,
and it is unavailable on the local models and unreliable for anything the
acoustic model has genuinely never encountered.

This module is the second: repair what still came through wrong. It runs on the
finished transcript, so it works identically on every provider and offline.

The matching is phonetic rather than textual, because the failure is phonetic.
"my yo wa" shares almost no letters with "Mayowa" -- edit distance on the raw
strings is enormous -- while the two are, to the ear, the same. Comparing what
the words SOUND like collapses that distance to nearly nothing.

The sound key here is a deliberately small thing: English digraphs folded to the
sound they make, voiced and unvoiced pairs merged so "dat" and "that" agree,
vowels dropped after the first letter, and runs collapsed. It is not Metaphone
and does not try to be. Metaphone exists to cluster surnames in a database,
where a false pair costs a wasted comparison. Here a false pair silently
rewrites somebody's words, so the key is chosen to be conservative and the
threshold does the rest.

Why not simply ask the person to type both spellings? Because they do not know
what the recognizer will produce -- "my yo wa" is not a spelling anyone would
predict -- and being asked to guess is the opposite of the feature. They type
the word they want; working out what it will be mistaken for is this module's
job. `sounds_like` exists for the case where somebody already knows, not as the
price of entry.

Pure functions over plain values. No I/O, no config reading, no Tk.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field

# Below this, a match is not trusted. Chosen against the real failures rather
# than tuned for elegance: "my yo wa"/"Mayowa" scores 1.00 and "talk that"/
# "Talk DAT!" scores 1.00 once voiced pairs merge, while the near-misses that
# must NOT match -- "market"/"marketing", "Dan"/"Dana" -- sit at 0.75 and below.
# The gap is wide, so the exact value matters less than staying inside it.
MIN_SIMILARITY = 0.86

# A key shorter than this carries too little information to match on. "Al"
# reduces to "l", which would collide with half the language.
MIN_KEY_LENGTH = 3

# How many spoken words a single term may span. A phrase longer than this is
# not something anybody adds to a dictionary, and every extra word multiplies
# the windows that have to be compared on a path with a 35ms budget.
MAX_TERM_WORDS = 5

# Digraphs folded to the sound they make, longest first so "tch" wins over "ch".
_DIGRAPHS = (
    ("tch", "t"), ("dge", "j"), ("ough", "f"), ("augh", "f"),
    ("sch", "sk"), ("sh", "s"), ("ch", "k"), ("ph", "f"), ("gh", ""),
    ("ck", "k"), ("th", "t"), ("wh", "w"), ("kn", "n"), ("gn", "n"),
    ("wr", "r"), ("mb", "m"), ("qu", "kw"), ("ce", "se"), ("ci", "si"),
)

# Consonants that differ only by voicing. English speech blurs these constantly
# and recognizers inherit the blur, which is exactly why "dat" is heard for
# "that" and "Mayowa" can arrive with a b where it wants a p.
_VOICING = str.maketrans({"d": "t", "b": "p", "v": "f", "z": "s", "g": "k", "j": "s"})

_VOWELS = set("aeiou")


@functools.lru_cache(maxsize=100_000)
def sound_key(text: str) -> str:
    """Reduce a word or phrase to a rough spelling of how it sounds.

    Cached: this is a pure function of its string, and the matcher asks for
    the same keys hundreds of thousands of times on a long dictation --
    field-measured at 7.6 SECONDS of formatting for an 800-word talk, nearly
    all of it recomputing sound keys for strings already seen. The cache
    turns that pass into milliseconds; 100k entries is bounded well above
    any real vocabulary times any real transcript.

    Vowels are dropped after the first character because they are the least
    reliable part of a recognizer's guess -- it is vowels that turn "Mayowa"
    into "my yo wa" -- while the consonant skeleton survives almost intact.
    The first character is kept whatever it is, since word-initial sounds are
    both reliable and the strongest signal that two words are unrelated.
    """
    # Folded PER WORD, never across the join. Concatenating first manufactures
    # digraphs no mouth ever produced: "knight chat" fused into "knightchat"
    # grows a phantom "tch" at the seam and the whole name collapses to two
    # letters, while "built the" merges into the same key as "Bluetooth". A
    # word boundary is a real acoustic event and the key respects it.
    def fold(word: str) -> str:
        for pattern, replacement in _DIGRAPHS:
            word = word.replace(pattern, replacement)
        word = word.translate(_VOICING)
        # An "i" wedged between two vowels is not doing a vowel's job, it is
        # the glide English usually spells "y" -- the difference between
        # "Mayowa" and "Maiowa" is orthography, not sound.
        word = re.sub(r"(?<=[aeiou])i(?=[aeiou])", "y", word)
        if not word:
            return ""
        head, tail = word[0], word[1:]
        skeleton = head + "".join(c for c in tail if c not in _VOWELS)
        # Collapse runs inside the word: "myyowa" and "mayowa" must not
        # differ over a doubled y.
        collapsed = []
        for character in skeleton:
            if not collapsed or collapsed[-1] != character:
                collapsed.append(character)
        return "".join(collapsed)

    words = re.findall(r"[a-z]+", text.lower())
    pieces = [fold(word) for word in words]
    # Across the JOIN, only glides merge. "my yo wa" and "Mayowa" share one y
    # -- the same sound continuing over the boundary -- but the t|t in
    # "built the" is two real stops, and merging them is exactly how that
    # phrase fell onto Bluetooth's key.
    key = ""
    for piece in pieces:
        if key and piece and key[-1] == piece[0] and piece[0] in "yw":
            piece = piece[1:]
        key += piece
    return key


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


@functools.lru_cache(maxsize=200_000)
def similarity(left: str, right: str) -> float:
    """1.0 for identical keys, 0.0 for nothing in common.

    Cached like sound_key and for the same reason: the matcher compares the
    same (window key, term key) pairs tens of thousands of times on a long
    transcript, and the edit distance underneath is the second-biggest cost
    in the whole formatting pass.
    """
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    longest = max(len(left), len(right))
    return 1.0 - (_edit_distance(left, right) / longest)


@dataclass(frozen=True)
class Term:
    """A word the person wants written their way, and what it may be heard as.

    `sounds_like` is optional and additive. The phonetic key already catches the
    ordinary mishearings; this is for the ones no algorithm would predict,
    where a recognizer lands on a genuinely different word.

    `not_before` is the context guard. "talk that" is the app's name in "I
    built talk that" and ordinary English in "let's talk that over" -- the
    words are identical and only the NEXT word tells them apart, because a
    pronoun object carries a continuation (over, through, out) and a name does
    not. Replacement is skipped when the following word is in this set.
    """

    text: str
    sounds_like: tuple[str, ...] = field(default=())
    not_before: tuple[str, ...] = field(default=())
    # `only_after` is the mirror guard: replacement happens ONLY when the
    # PREVIOUS word is in this set. Built for cloud/Claude vs "called" --
    # three words on one sound key, told apart by what stands before them:
    # the noun cloud follows the/to/on/my; the verb called never does.
    only_after: tuple[str, ...] = field(default=())

    @property
    def word_count(self) -> int:
        return max(1, len(self.text.split()))

    # The three derivation methods are cached: a frozen dataclass hashes by
    # value, every term is asked the same questions at every window of every
    # pass, and the answers never change. Bounded by distinct terms.
    @functools.lru_cache(maxsize=8192)
    def keys(self) -> tuple[str, ...]:
        candidates = [sound_key(self.text)]
        candidates.extend(sound_key(alias) for alias in self.sounds_like)
        return tuple(key for key in candidates if len(key) >= MIN_KEY_LENGTH)

    @functools.lru_cache(maxsize=8192)
    def sources(self) -> tuple[tuple[str, int], ...]:
        """Every spelling this term answers to, as (sound key, letter count).

        The letter count rides along because a sound key alone over-matches:
        vowel-dropping collapses "built" and "Bluetooth" onto the same key,
        and only the fact that one is five letters and the other nine tells
        them apart. Matching demands agreement on BOTH.
        """
        spellings = (self.text, *self.sounds_like)
        out = []
        for spelling in spellings:
            key = sound_key(spelling)
            if len(key) >= MIN_KEY_LENGTH:
                out.append((key, len(re.sub(r"[^A-Za-z]", "", spelling))))
        return tuple(out)

    def window_spans(self) -> set[int]:
        """How many spoken words a matching window may cover.

        Derived from every spelling, not just the canonical text: a term named
        "Tik Tok Consulting" that answers to the two-word "tik tok" must try
        two-word windows, and deriving spans from the three-word canonical
        alone silently never did.
        """
        spans: set[int] = set()
        for spelling in (self.text, *self.sounds_like):
            count = max(1, len(str(spelling).split()))
            spans.add(count)
            spans.add(count + 1)
            # Recognizers FUSE compounds: the shipped local model heard
            # "talk dat" as the single token "TalkDad", and a two-word term
            # that never tries one-word windows misses every fused hearing
            # ("paypal", "youtube", "knightchat"). The sound+size guards
            # still gate the match; this only lets it be attempted.
            if count in {2, 3}:
                spans.add(1)
            if count <= 2:
                spans.add(count + 2)
        return {span for span in spans if 1 <= span <= MAX_TERM_WORDS + 2}


# Every install corrects the product's own name, from the first dictation,
# without anybody adding it. The brand is "Talk DAT!" -- DAT capitalized in
# every context, it is Digital Audio Tape -- and a recognizer will write it as
# "talk that" or "talk dat" every single time, because to the ear that is what
# it is.
#
# The guard list is what makes shipping this on by default safe. "talk that"
# followed by over/through/out is a person discussing something, and rewriting
# it would put the product's name in the middle of their sentence -- the exact
# failure that makes people turn a feature off. Code-level rather than seeded
# into config, so it exists on every install, survives resets, and cannot be
# half-deleted; a user term with the same text still wins outright.
DEFAULT_TERMS: tuple[Term, ...] = (
    Term(
        "Talk DAT!",
        # X-72 (his order): every hearing a mouth actually produces for the
        # brand, chosen with intelligence rather than volume -- the spelled-
        # out letters, the fused compound, and the flat-vowel hearings. The
        # not_before guard below is what keeps ordinary "talk that over"
        # untouched by every one of these.
        sounds_like=("talk that", "talk dat", "talked at", "talk d a t",
                     "tock dat", "talk debt", "talkdat",
                     # 2026-09-22: these matched only by fuzzy key before the
                     # defaults were limited to their listed hearings.
                     "talkdad", "talk dad", "tokdat"),
        not_before=(
            "over", "through", "out", "about", "away", "up", "down",
            "later", "more", "again", "first", "now", "to", "with",
            "in", "at", "on", "before", "after", "tonight", "tomorrow",
        ),
    ),
    Term("Knight AI+AV", sounds_like=("night ai and av", "knight ai av", "night ai av")),
    # Deepgram hears "cloud" as "Claude" constantly for this product's users
    # (the word is everywhere in dictation about the app). The guard keeps
    # genuine Claude-talk intact: followed by AI-context words, the name
    # survives; bare "Claude" in product speech becomes the cloud it was.
    Term(
        "cloud",
        sounds_like=("claude",),
        only_after=(
            "the", "a", "your", "my", "our", "to", "on", "from",
            "in", "into", "onto", "via", "with",
        ),
        not_before=(
            "code", "agent", "agents", "ai", "model", "models", "opus",
            "sonnet", "haiku", "fable", "anthropic", "desktop", "app",
        ),
    ),
)


# Brands whose spelling is a fact, not a preference. A recognizer writes
# "you tube" and "git hub" because to the ear that is what they are; the
# canonical casing is public knowledge and correcting it should not require
# every user to teach it.
#
# Membership rules, because a false correction rewrites somebody's words:
# only names whose SOUND is distinctive enough that ordinary prose never
# produces it. "Excel" and "Word" are common English verbs and nouns -- they
# stay out no matter how big the trademark. Marks travel only where they are
# part of the name itself (Talk DAT!'s bang); prose does not decorate brands
# with (R) and neither do we.
#
# Knight AI+AV's own products lead the list. They are the names this product
# will hear most, and the ones it must never misspell.
BRAND_TERMS: tuple[Term, ...] = (
    # --- the house ---
    Term("NavOrb", sounds_like=("nav orb", "navorb")),
    Term("TaskRune", sounds_like=("task rune", "task ruin")),
    Term("Lift Wizard", sounds_like=("lift wizard",)),
    Term("Profile Paris", sounds_like=("profile paris",)),
    Term("Snip Wizard", sounds_like=("snip wizard",)),
    Term("KnightForge", sounds_like=("knight forge", "night forge")),
    Term("KnightChat", sounds_like=("knight chat", "night chat")),
    # --- the world ---
    Term("iPhone", sounds_like=("i phone",)),
    Term("iPad", sounds_like=("i pad",)),
    Term("iOS"),
    Term("macOS", sounds_like=("mac o s", "mac os")),
    Term("YouTube", sounds_like=("you tube",)),
    Term("TikTok", sounds_like=("tik tok", "tick tock")),
    Term("LinkedIn", sounds_like=("linked in",)),
    # X-602 (commandment 66): "we need to get hub caps for the van" became
    # "We need to GitHub caps". "get hub" is also the verb "get" and a wheel
    # hub, and the word after it says which: a hub part is never the site.
    Term("GitHub", sounds_like=("git hub", "get hub"),
         not_before=("caps", "cap", "capped", "motor", "motors", "bearing", "bearings", "assembly",
                     "assemblies", "nut", "nuts", "bolt", "bolts", "gear", "gears", "seal", "seals")),
    Term("GitLab", sounds_like=("git lab",)),
    Term("ChatGPT", sounds_like=("chat gpt", "chat g p t")),
    # OpenAI was cut 2026-08-08 (X-14) after corrupting a real dictation three
    # times in one message: its "open ai" alias shares a sound key with
    # "open a" -- one of the most common bigrams in English -- and slipped the
    # size guard at ratio 0.167. Same membership rule as Wi-Fi/wife: when a
    # brand's sound collides with everyday speech, the brand loses. People who
    # say "OpenAI" get it transcribed correctly by every provider anyway.
    Term("PayPal", sounds_like=("pay pal",)),
    Term("eBay", sounds_like=("e bay",)),
    # Wi-Fi is deliberately absent. Its sound key is two letters, and any
    # matching loose enough to admit "wifi" also rewrites "wife" -- a
    # catastrophic false positive. Membership rule, not a tuning problem.
    Term("Bluetooth", sounds_like=("blue tooth",)),
    Term("PowerPoint", sounds_like=("power point",)),
    Term("OneDrive", sounds_like=("one drive",)),
    Term("WhatsApp", sounds_like=("whats app", "what's app")),
    Term("PlayStation", sounds_like=("play station",)),
    Term("JavaScript", sounds_like=("java script",)),
    Term("TypeScript", sounds_like=("type script",)),
    Term("WordPress", sounds_like=("word press",)),
    Term("Photoshop", sounds_like=("photo shop",)),
    Term("Spotify"),
    Term("NVIDIA", sounds_like=("nvidia", "in vidia")),
    # X-602 (commandments 41 and 67): names no ordinary sentence produces.
    Term("Android"),
    Term("Figma"),
    Term("Okta"),
)


def with_default_terms(terms: list[Term]) -> list[Term]:
    """The user's terms, with the brand defaults appended where not overridden.

    Overridden is judged by SOUND, not by exact text. A user who teaches their
    own spelling of the name -- "talk dat", "TalkDat", whatever -- has claimed
    that sound, and appending the default anyway would put two terms on one
    key, where the exact-claim rule makes them deadlock and NEITHER fires. The
    user typed a spelling and the product's own default silenced it: the worst
    possible outcome for a defaults mechanism, found by the first test that
    tried an override.
    """
    user_keys: set[str] = set()
    for term in terms:
        user_keys.update(term.keys())
    kept = list(terms)
    for default in DEFAULT_TERMS:
        if any(key in user_keys for key in default.keys()):
            continue
        kept.append(default)
    return kept


def with_brand_terms(terms: list[Term], *, enabled: bool = True) -> list[Term]:
    """Append the brand registry, yielding to anything already claimed.

    Ranked below both the user's terms and the product defaults: a person who
    respells a brand on purpose -- their own startup called Tik Tok Consulting,
    whatever -- has made a decision, and a registry exists to fill silence.
    """
    if not enabled:
        return terms
    taken: set[str] = set()
    for term in terms:
        taken.update(term.keys())
    kept = list(terms)
    for brand in BRAND_TERMS:
        if any(key in taken for key in brand.keys()):
            continue
        kept.append(brand)
    return kept


def parse_terms(raw: object) -> list[Term]:
    """Read `dictionary.words` in every shape it has ever been written.

    Older releases stored a plain list of strings and people edit this file by
    hand, so a string, a dict, and a dict missing half its keys all have to mean
    something sensible rather than raise.
    """
    if not isinstance(raw, (list, tuple)):
        return []
    terms: list[Term] = []
    for entry in raw:
        if isinstance(entry, str):
            text = entry.strip()
            aliases: tuple[str, ...] = ()
        elif isinstance(entry, dict):
            text = str(entry.get("text") or entry.get("word") or "").strip()
            spoken = entry.get("sounds_like") or entry.get("sounds") or []
            if isinstance(spoken, str):
                spoken = [spoken]
            aliases = tuple(str(item).strip() for item in spoken if str(item).strip())
        else:
            continue
        if text and len(text.split()) <= MAX_TERM_WORDS:
            terms.append(Term(text=text, sounds_like=aliases))
    return terms


def _match_case(original: str, replacement: str) -> str:
    """Keep a sentence-initial capital without overriding the term's own casing.

    The stored spelling wins, because that is the entire point of storing it --
    "iPhone" and "Talk DAT!" are chosen, not accidental. The one thing worth
    preserving from context is a capital at the start of a sentence.
    """
    if original[:1].isupper() and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def apply_vocabulary(text: str, terms: list[Term]) -> str:
    from .literal_text import map_prose

    return map_prose(text, lambda prose: _apply_vocabulary_prose(prose, terms))


def _apply_vocabulary_prose(text: str, terms: list[Term]) -> str:
    """Rewrite anything that sounds like a known term into that term's spelling.

    Longest terms first, so "Talk Dat Pro" is not half-consumed by "Talk Dat".

    A window whose key already equals a DIFFERENT term's key is left alone: two
    dictionary entries that sound the same cannot both be right, and picking one
    would be a coin flip that silently changes somebody's words.
    """
    if not text.strip() or not terms:
        return text

    ordered = sorted(terms, key=lambda term: term.word_count, reverse=True)
    # Short sound keys are unsafe for fuzzy matching, but an exact spelling
    # still carries the user's chosen case (API, Api, OK, iOS).
    for term in ordered:
        if not term.keys():
            for alias in (term.text, *term.sounds_like):
                text = re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", lambda m: term.text, text, flags=re.I)
    # Split into words while remembering the exact separators, so rebuilding the
    # sentence cannot quietly normalise the person's spacing or line breaks.
    tokens = re.split(r"(\s+)", text)
    words = [(index, token) for index, token in enumerate(tokens) if token.strip()]

    replaced: set[int] = set()
    # X-142 (benchmarked): keying a window is regex-heavy, and the SAME
    # window was re-keyed once per term -- 155ms of a 153ms local pipeline
    # on a 300-word dictation was this loop. Windows never change unless a
    # replacement lands inside them, and replaced indices are skipped before
    # lookup, so one shared cache across terms is semantics-free. Measured:
    # ~10x on the whole matcher.
    window_cache: dict[tuple[int, int], tuple[str, str, str, int] | None] = {}
    for term in ordered:
        term_keys = term.keys()
        if not term_keys:
            continue
        brand_spellings = None
        # 2026-09-22: the product's own defaults too. They already list every
        # hearing they answer to (X-72), and a fuzzy match on top of that list
        # turned "the ticket is ten dollars" into "the Talk DAT! is $10": the
        # key and length of "ticket" sit inside the tolerance of "talk dat".
        # A person's own dictionary entries keep phonetic matching.
        if any(term is brand for brand in (*BRAND_TERMS, *DEFAULT_TERMS)):
            brand_spellings = {re.sub(r"[^a-z0-9]", "", alias.lower()) for alias in (term.text, *term.sounds_like)}
        # Widths come from every spelling the term answers to, each padded for
        # the recognizer splitting or joining a word -- "Mayowa" may come back
        # as one token or as three.
        for width in sorted(term.window_spans()):
            position = 0
            while position + width <= len(words):
                indices = [words[position + offset][0] for offset in range(width)]
                if any(index in replaced for index in indices):
                    position += 1
                    continue
                cached = window_cache.get((position, width), False)
                if cached is False:
                    window = " ".join(words[position + offset][1] for offset in range(width))
                    stripped = window.strip(".,;:!?\"'()[]")
                    if not stripped:
                        cached = None
                    else:
                        cached = (
                            window,
                            stripped,
                            sound_key(stripped),
                            len(re.sub(r"[^A-Za-z]", "", stripped)),
                        )
                    window_cache[(position, width)] = cached
                if cached is None:
                    position += 1
                    continue
                window, stripped, window_key, window_letters = cached
                # Public names only match their spelling and declared aliases.
                # "Launched in" shares LinkedIn's phonetic key, but it is a verb.
                # Personal terms keep phonetic matching for unfamiliar names.
                if brand_spellings is not None:
                    spelling = re.sub(r"[^a-z0-9]", "", stripped.lower())
                    if spelling not in brand_spellings:
                        position += 1
                        continue
                if len(window_key) < MIN_KEY_LENGTH:
                    position += 1
                    continue
                # Already written the way it wants to be. Compared both with and
                # without surrounding punctuation, because a term may carry its
                # own -- "Talk DAT!" against the window "Talk DAT!" matches only
                # on the raw form, and against "Talk Dat" only on the stripped.
                # EXACT case: a brand's casing IS part of its correction, so
                # "github" must still become "GitHub" -- only a window already
                # letter-for-letter identical is left alone.
                if term.text in {stripped, window.strip()}:
                    position += 1
                    continue
                best = 0.0
                for key, source_letters in term.sources():
                    # Sound AND size must agree. Vowel-dropping collapses
                    # "built" and "Bluetooth" onto one key; five letters
                    # against nine is what tells them apart.
                    longest = max(window_letters, source_letters, 1)
                    if abs(window_letters - source_letters) / longest > 0.20:
                        continue
                    best = max(best, similarity(window_key, key))
                if best >= MIN_SIMILARITY and term.only_after:
                    # The mirror guard: this term fires ONLY after one of its
                    # named openers. Built for cloud/Claude vs "called" --
                    # identical sound keys, separated entirely by the word
                    # standing BEFORE them.
                    previous = words[position - 1][1].strip(".,;:!?\"'()[]").lower() if position > 0 else ""
                    if previous not in term.only_after:
                        position += 1
                        continue
                if best >= MIN_SIMILARITY and term.not_before:
                    follower_index = position + width
                    if follower_index < len(words):
                        follower = words[follower_index][1].strip(".,;:!?\"'()[]").lower()
                        if follower in term.not_before:
                            # The next word says the match is ordinary English,
                            # not the name -- "talk that over" is a
                            # conversation, whatever it sounds like.
                            position += 1
                            continue
                if best >= MIN_SIMILARITY and not _claimed_by_another(window_key, term, ordered):
                    trailing = window[len(window.rstrip(".,;:!?\"')]")):] if window != stripped else ""
                    # A term that ends in punctuation brings its own. Appending
                    # the window's as well produced "Talk DAT!!".
                    if trailing and term.text[-1:] in ".,;:!?":
                        trailing = ""
                    leading = window[:len(window) - len(window.lstrip("\"'(["))]
                    tokens[indices[0]] = leading + _match_case(stripped, term.text) + trailing
                    for index in indices[1:]:
                        tokens[index] = ""
                    # Blank the separators the removed words carried with them.
                    for index in range(indices[0] + 1, indices[-1] + 1):
                        if not tokens[index].strip():
                            tokens[index] = ""
                    replaced.update(indices)
                    position += width
                    continue
                position += 1
    result = "".join(tokens)
    # A name that carries its own terminal mark (Talk DAT!) lands at
    # sentence end next to the formatter's period -- collapse the
    # stray dot so the bang IS the terminal.
    return re.sub(r"([!?])\.(\s|$)", r"\1\2", result)

def _claimed_by_another(window_key: str, term: Term, ordered: list[Term]) -> bool:
    """True when some other term is an exact phonetic match for this window.

    An exact key match beats a fuzzy one. Without this, adding both "Dat" and
    "Dot" makes whichever sorts first swallow the other's occurrences.
    """
    for other in ordered:
        if other is term:
            continue
        if window_key in other.keys():
            return True
    return False
