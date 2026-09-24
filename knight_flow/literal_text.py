"""Keep code and written identifiers opaque while prose is being edited."""
from __future__ import annotations

import re
from collections.abc import Callable


_LITERAL_RE = re.compile(
    r"```[\s\S]*?(?:```|$)|`[^`\n]+`"
    r'|"(?:[a-zA-Z]:\\|\\\\|\.{1,2}/|~/)[^"\n]+"'
    r"|\b(?:https?://|www\.)[^\s<>\"`]+"
    r"|(?<![\w@])[\w.+%-]+@[\w.-]+\.[a-zA-Z]{2,63}\b"
    r"|(?<!\w)(?:[a-zA-Z]:\\|\\\\|\.{1,2}/|~/)[^\s<>\"`]+"
    # 2026-09-23: an absolute POSIX path ("open /users/alex") and a long
    # command-line switch ("npm install --save-dev") are written forms too.
    r"|(?<![\w/.~:])/[\w.-]+(?:/[\w.-]+)*"
    r"|(?<![\w-])--[a-zA-Z][\w-]*"
    r"|(?<!\w)(?:[\w.-]+/)+[\w.\-]+"
    r"|(?<!\w)[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io|app|ai|dev|edu|gov|co|uk|us|me|info|biz)\b(?:/[^\s<>\"`]*)?"
    r"|\b[\w-]+\.(?:py|js|ts|tsx|jsx|json|yaml|yml|toml|md|txt|csv|html|css|exe|dll|sh|ps1)\b"
    # X-602: a dotfile ("the .env file") is a written name too (commandment 71).
    r"|(?<![\w.])\.(?:env|gitignore|gitattributes|gitmodules|bashrc|bash_profile|zshrc|npmrc|nvmrc|dockerignore"
    r"|editorconfig|prettierrc|eslintrc|babelrc|vimrc|htaccess)(?:\.[a-z]+)?\b"
    r"|\b\w+_\w+\b|\bTDLITERAL\d+TOKEN\b",
    re.IGNORECASE,
)


def literal_spans(text: str):
    for match in _LITERAL_RE.finditer(text):
        end = match.end()
        if not match.group().startswith("`"):
            # Sentence marks belong to the surrounding prose, not the address.
            while end > match.start() and text[end - 1] in ".,;!?":
                end -= 1
            while end > match.start() and text[end - 1] in ")]}" and text[match.start():end].count(text[end - 1]) > text[match.start():end].count({")": "(", "]": "[", "}": "{"}[text[end - 1]]):
                end -= 1
        yield match.start(), end


def map_prose(text: str, transform: Callable[[str], str]) -> str:
    """Apply a transform only between complete literal spans, preserving spacing."""
    result: list[str] = []
    cursor = 0
    for start, end in literal_spans(text):
        result.extend((transform(text[cursor:start]), text[start:end]))
        cursor = end
    result.append(transform(text[cursor:]))
    return "".join(result)


def protect_literals(text: str) -> tuple[str, dict[str, str]]:
    """Use stable opaque words so sentence formatting can still see the whole text."""
    saved: dict[str, str] = {}
    result: list[str] = []
    cursor = 0
    for start, end in literal_spans(text):
        index = len(saved)
        token = f"TDLITERAL{index}TOKEN"
        while token.lower() in text.lower() or token in saved:
            index += 1
            token = f"TDLITERAL{index}TOKEN"
        saved[token] = text[start:end]
        result.extend((text[cursor:start], token))
        cursor = end
    result.append(text[cursor:])
    return "".join(result), saved


def restore_literals(text: str, saved: dict[str, str]) -> str:
    # One substitution, so a literal containing another placeholder is opaque.
    if not saved:
        return text
    pattern = re.compile("|".join(re.escape(token) for token in saved))
    return pattern.sub(lambda match: saved[match.group()], text)
