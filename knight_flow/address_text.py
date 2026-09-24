"""Compose explicitly spoken addresses before punctuation and brand correction."""
from __future__ import annotations

import re

from .literal_text import map_prose

_TLD = r"(?:com|org|net|io|app|ai|dev|edu|gov|co|uk|us|me|info|biz)"
_PART = r"(?:(?!at\b|dot\b|slash\b|underscore\b|dash\b)[a-z0-9]+)"
_LABEL = rf"{_PART}(?:\s+{_PART}){{0,4}}"
_DOMAIN_LABEL = rf"{_LABEL}(?:\s+(?:dash|underscore)\s+{_LABEL})*"
_CONNECTORS = {"dot": ".", "at": "@", "slash": "/", "underscore": "_", "dash": "-"}
_BOUNDARIES = {"at", "to", "is", "are", "visit", "open", "browse", "website", "url", "address", "on", "from"}
# This is the package's real identifier, not a rule that guesses underscores
# for every pair of words. Owners can add their own explicit path aliases.
_IDENTIFIER_ALIASES = {"knight flow": "knight_flow"}
# Extensions a spoken "name dot ext" is composed for. Kept to the ones the
# literal guard in literal_text.py also protects once written.
_FILE_EXTENSIONS = r"(?:py|js|ts|tsx|jsx|json|yaml|yml|toml|md|txt|csv|html|css|exe|dll|sh|ps1)"


def _joined(spoken: str) -> str:
    return "".join(_CONNECTORS.get(word, word) for word in spoken.lower().split())


# --- Command lines, absolute paths and language names (2026-09-23) ----------
#
# "run npm install dash dash save dev" came out "Run npm install, save dev."
# because "dash" was always a comma, and "open slash users slash alex" came
# out "Open/users/alex" because a spoken slash always glued to the word
# before it. Both are composed here, where the other spoken addresses are,
# and then protected as literals like them.

# A single spoken "dash x" is a command-line switch only in a command line:
# a tool named earlier in the same clause ("git commit dash m", "docker run
# dash it", "rm dash rf"). "I went for a run dash it was great" names no
# tool, so its dash stays the pause it was.
_TOOLS = frozenset("""
npm npx yarn pnpm pip pip3 python python3 node deno bun git gh docker kubectl
brew apt sudo ls rm cp mv mkdir grep curl wget ssh scp tar unzip chmod chown
ps cargo javac dotnet gem rails pytest ffmpeg
""".split())
# Well-known flags spoken as two words. Anything else takes the one word
# after "dash dash"; a "no" flag always takes its next word ("--no-edit").
_COMPOUND_FLAGS = {
    "save dev": "save-dev", "save exact": "save-exact", "save optional": "save-optional",
    "save peer": "save-peer", "dry run": "dry-run", "force with lease": "force-with-lease",
    "set upstream": "set-upstream", "global": "global", "legacy peer deps": "legacy-peer-deps",
    "ignore scripts": "ignore-scripts", "frozen lockfile": "frozen-lockfile", "no cache dir": "no-cache-dir",
}
_FLAG_WORD = r"[a-z][a-z0-9]*"
_DOUBLE_FLAG_RE = re.compile(rf"\bdash\s+dash\s+({_FLAG_WORD}(?:\s+(?:dash\s+)?{_FLAG_WORD}){{0,3}})", re.I)
_SINGLE_FLAG_RE = re.compile(r"(?<=\s)dash\s+([a-z]{1,3})\b", re.I)
# Words that introduce an absolute path: "open slash users", "in slash var".
_PATH_CUES = r"(?:open|in|into|to|at|from|under|inside|cd|is|see|check|find|save|saved|move|copy|edit|browse|navigate|path|folder|directory)"
_PATH_SEGMENT = r"[a-z0-9]+(?:\s+(?:dot|underscore|dash)\s+[a-z0-9]+)*"
_ABSOLUTE_PATH_RE = re.compile(
    rf"(?:(?P<start>^\s*)|(?P<cue>\b{_PATH_CUES}\s+))slash\s+(?P<path>{_PATH_SEGMENT}(?:\s+slash\s+{_PATH_SEGMENT})*)\b",
    re.I,
)


def _flag_name(tokens: list[str]) -> tuple[str, list[str]]:
    """(flag name, words left over) for the words after a spoken "dash dash"."""
    lowered = [token.lower() for token in tokens]
    # Explicit joins win: "dash dash dry dash run" is --dry-run.
    parts, index = [lowered[0]], 1
    while index + 1 < len(lowered) and lowered[index] == "dash":
        parts.append(lowered[index + 1])
        index += 2
    if len(parts) > 1:
        return "-".join(parts), tokens[index:]
    for size in (3, 2):
        if len(lowered) >= size and " ".join(lowered[:size]) in _COMPOUND_FLAGS:
            return _COMPOUND_FLAGS[" ".join(lowered[:size])], tokens[size:]
    if lowered[0] == "no" and len(lowered) > 1 and lowered[1] != "dash":
        return "no-" + lowered[1], tokens[2:]
    return lowered[0], tokens[1:]


def _compose_flags(prose: str) -> str:
    def double(match: re.Match[str]) -> str:
        name, rest = _flag_name(match.group(1).split())
        return "--" + name + ("" if not rest else " " + " ".join(rest))

    prose = _DOUBLE_FLAG_RE.sub(double, prose)

    def applies(match: re.Match[str]) -> bool:
        clause = re.split(r"[.!?;,\n]", prose[:match.start()])[-1]
        words = [word.lower() for word in re.findall(r"[\w.+-]+", clause)][-6:]
        return any(word in _TOOLS for word in words)

    # One at a time, so a chain ("rm dash r dash f") sees the switch before it.
    while True:
        match = next((m for m in _SINGLE_FLAG_RE.finditer(prose) if applies(m)), None)
        if match is None:
            return prose
        prose = prose[:match.start()] + "-" + match.group(1).lower() + prose[match.end():]


def _compose_absolute_paths(prose: str) -> str:
    """"open slash users slash alex" -> "open /users/alex".

    Only after a word that introduces a location ("open", "in", "cd"...) or
    at the very start of the take with at least two segments. A slash after
    anything else keeps its old meaning ("and slash or" is "and/or", and
    "example dot com slash docs" is a URL the domain rule composes)."""
    def render(match: re.Match[str]) -> str:
        segments = re.split(r"\s+slash\s+", match.group("path"), flags=re.I)
        if match.group("cue") is None and len(segments) < 2:
            return match.group(0)
        lead = match.group("cue") or match.group("start") or ""
        return lead + "/" + "/".join(_joined(segment) for segment in segments)

    return _ABSOLUTE_PATH_RE.sub(render, prose)


# X-602 (commandment 71): "check the dot env file" is the file ".env". A
# spoken "dot" before a well-known dotfile name is its leading dot when the
# word before it cannot be a file-name stem (an article, a possessive, a verb
# or the start of the take); "config dot env" stays as said.
_DOTFILE_NAMES = (
    r"(?:env|gitignore|gitattributes|gitmodules|bashrc|bash_profile|zshrc|npmrc|nvmrc|dockerignore|"
    r"editorconfig|prettierrc|eslintrc|babelrc|vimrc|htaccess)"
)
_DOTFILE_RE = re.compile(
    r"(?P<lead>^\s*|\b(?:the|a|an|my|our|your|his|her|their|its|this|that|and|or|to|in|on|of|from|into|"
    r"open|edit|check|add|update|create|copy|read|commit|ignore|delete|source|load)\s+)"
    rf"dot\s+(?P<name>{_DOTFILE_NAMES})(?:\s+dot\s+(?P<suffix>local|example|sample|production|development|test))?\b",
    re.I,
)


def _compose_dotfiles(prose: str) -> str:
    def render(match: re.Match[str]) -> str:
        suffix = f".{match['suffix'].lower()}" if match["suffix"] else ""
        return match["lead"] + "." + match["name"].lower() + suffix

    return _DOTFILE_RE.sub(render, prose)


def _compose_language_names(prose: str) -> str:
    # "c plus plus" is a name, not a stutter the repeat collapser may halve.
    prose = re.sub(r"\bc\s+plus\s+plus\b", "C++", prose, flags=re.I)
    return re.sub(r"\bc\s+sharp\b", "C#", prose, flags=re.I)


def _split_prefix(spoken: str) -> tuple[str, str]:
    words = spoken.split()
    boundary = max((i for i, word in enumerate(words) if word.lower() in _BOUNDARIES), default=-1)
    prefix = " ".join(words[:boundary + 1])
    return (prefix + " " if prefix else ""), " ".join(words[boundary + 1:])


def compose_addresses(text: str, aliases: dict[str, str] | None = None) -> str:
    provided = aliases if isinstance(aliases, dict) else {}
    path_aliases = _IDENTIFIER_ALIASES | {str(k).lower(): str(v) for k, v in provided.items()}

    def compose(prose: str) -> str:
        prose = _compose_dotfiles(_compose_language_names(_compose_absolute_paths(_compose_flags(prose))))
        email = re.compile(rf"\b([a-z0-9]+(?:\s+(?:dot|underscore|dash)\s+[a-z0-9]+)*)\s+at\s+({_LABEL}(?:\s+(?:dot|dash)\s+{_LABEL})*)\s+dot\s+({_TLD})\b", re.I)

        def email_match(match: re.Match[str]) -> str:
            before = prose[:match.start()]
            if before.strip() and not re.search(r"\b(?:email|mail|send|contact|address|write|reach)\b", before, re.I):
                return match[0]
            return _joined(match[1]) + "@" + _joined(match[2]) + "." + match[3].lower()

        prose = email.sub(email_match, prose)

        def domain_match(match: re.Match[str]) -> str:
            if re.search(r"\b(?:words?|phrase|literal|spelling)\s*$", match[1], re.I):
                return match[0]
            prefix, label = _split_prefix(match[1])
            cue_before = re.search(r"\b(?:" + "|".join(_BOUNDARIES) + r")\s+$", prose[:match.start()], re.I)
            if not prefix and not cue_before:
                # Without "open/visit/at...", there is no evidence that prior
                # prose is part of a multiword domain. Keep it as prose.
                words = label.split()
                first_connector = next((i for i, word in enumerate(words) if word.lower() in _CONNECTORS), len(words))
                if first_connector > 1:
                    prefix = " ".join(words[:first_connector - 1]) + " "
                    label = " ".join(words[first_connector - 1:])
            if not label or label.lower() in {"a", "an", "the"}:
                return match[0]
            return prefix + _joined(label) + "." + match[2].lower()

        domain = re.compile(rf"\b({_DOMAIN_LABEL}(?:\s+dot\s+{_DOMAIN_LABEL})*)\s+dot\s+({_TLD})\b", re.I)
        # Existing addresses, including the email we just composed, are opaque.
        prose = map_prose(prose, lambda gap: domain.sub(domain_match, gap))
        # A slash suffix can only attach to a domain/path already present.
        prose = re.sub(rf"(\b[\w.-]+\.{_TLD}(?:/[\w.-]+)*)((?:\s+slash\s+[a-z0-9]+(?:\s+(?:underscore|dash|dot)\s+[a-z0-9]+)*)+)", lambda m: m[1] + _joined(m[2]), prose, flags=re.I)

        def file_match(match: re.Match[str]) -> str:
            prefix, root = _split_prefix(match[1])
            if not root:
                return match[0]
            key = root.lower()
            # Without an alias or explicit underscore, a spaced directory
            # name stays ambiguous. Do not silently choose its spelling.
            if " " in key and key not in path_aliases and not re.search(r"\b(?:underscore|dash)\b", key):
                return match[0]
            root = path_aliases.get(key, _joined(root))
            return prefix + root + "/" + _joined(match[2]) + "." + match[3].lower()

        file_pattern = re.compile(rf"\b({_LABEL}(?:\s+(?:underscore|dash)\s+{_LABEL})*)\s+slash\s+([a-z0-9]+(?:\s+(?:underscore|dash)\s+[a-z0-9]+)*)\s+dot\s+(py|js|ts|json|yaml|md|txt|csv|html|css)\b", re.I)
        prose = map_prose(prose, lambda gap: file_pattern.sub(file_match, gap))
        # A bare file name: "config dot json" is config.json. Only the one
        # word before "dot" (plus explicit underscore/dash joins) is taken,
        # and only before a known file extension, so ordinary prose that
        # says "dot" is never glued together.
        bare_file = re.compile(
            rf"\b((?!(?:the|a|an|my|our|your|this|that|and|or|to|in|on|at|of)\b)[a-z0-9]+"
            rf"(?:\s+(?:underscore|dash)\s+[a-z0-9]+)*)\s+dot\s+({_FILE_EXTENSIONS})\b",
            re.I,
        )
        def bare_file_match(match: re.Match[str], gap: str) -> str:
            # "my project slash main dot py" is a path whose directory
            # spelling is ambiguous (see file_match); composing only the file
            # part would leave "slash main.py" behind.
            if re.search(r"\b(?:slash|underscore|dash)\s+$", gap[:match.start()], re.I):
                return match[0]
            return _joined(match[1]) + "." + match[2].lower()

        return map_prose(prose, lambda gap: bare_file.sub(lambda m: bare_file_match(m, gap), gap))

    return map_prose(text, compose)
