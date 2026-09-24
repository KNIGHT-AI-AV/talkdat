"""The text each kind of field can take (commandments 52, 77 and 78).

Pure functions; field_context.py decides which kind a take is going into.

- A password field gets the words as said: none of the recognizer's sentence
  capital or punctuation, no model, nothing else.
- A terminal gets command text: one line, no sentence capital, no final
  period, straight quotes, and a spoken correction applied to the command.
- A single-line field gets one line: an inferred list becomes an inline series
  ("milk, eggs, and bread") and any other line break becomes a space, because a
  pasted line break can cut the text off or submit the form.
"""
from __future__ import annotations

import re

_LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.*\S)\s*$")
_CORRECTION_CUE = r"(?:no|sorry|i mean|actually|wait|make that)"
_CURLY = {0x201C: '"', 0x201D: '"', 0x2018: "'", 0x2019: "'"}


def _series(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _said_in_lower_case(word: str, spoken: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(word.lower()) + r"(?!\w)", spoken))


def single_line_text(text: str, spoken: str) -> str:
    """One line: an inferred list becomes an inline series, breaks become spaces."""
    if "\n" not in text:
        return text
    parts: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if not items:
            return
        series = _series(items)
        if parts and parts[-1].endswith(":"):
            parts[-1] += " " + series
        else:
            parts.append(series)
        items.clear()

    for line in (line.strip() for line in text.splitlines()):
        if not line:
            continue
        item = _LIST_ITEM.match(line)
        if not item:
            flush()
            # "Hi Diane,\n\nCan you..." joins as "Hi Diane, can you...".
            first = line.split(" ", 1)[0]
            if (parts and parts[-1].endswith(",") and first[:1].isupper()
                    and first[1:] == first[1:].lower() and _said_in_lower_case(first, spoken)):
                line = line[0].lower() + line[1:]
            parts.append(line)
            continue
        words = item.group(1).rstrip(".;").split(" ")
        first = words[0]
        # The list layout capitalised an item the speaker said in lower case;
        # a name the recognizer capitalised keeps its capital.
        if first[:1].isupper() and first[1:] == first[1:].lower() and _said_in_lower_case(first, spoken):
            words[0] = first[0].lower() + first[1:]
        items.append(" ".join(words))
    flush()
    return " ".join(parts)


def console_text(text: str, spoken: str) -> str:
    """Command text: one line, no sentence capital or final period, straight quotes."""
    text = single_line_text(text, spoken).translate(_CURLY).strip()
    # A spoken correction inside a command: "origin main, no, origin develop"
    # restarts at the repeated word; "origin main, no, develop" replaces one.
    # Never inside quotes, where ", no, " can be the text itself.
    if '"' not in text and "'" not in text:
        restart = re.match(
            rf"^(?P<head>.*?)(?P<anchor>(?<!\S)\S+)[^,]*,\s*{_CORRECTION_CUE},?\s+(?P=anchor)(?=\s|$)(?P<new>.*)$",
            text, re.I,
        )
        single = None if restart else re.match(
            rf"^(?P<head>.*\s)\S+,\s*{_CORRECTION_CUE},?\s+(?P<new>\S+)$", text, re.I)
        if restart:
            text = restart["head"] + restart["anchor"] + restart["new"]
        elif single:
            text = single["head"] + single["new"]
    if text.endswith(".") and not text.endswith(".."):
        text = text[:-1]
    # The sentence capital only: "NODE_ENV" and "GIT" keep theirs.
    if re.match(r"[A-Z][a-z]", text):
        text = text[0].lower() + text[1:]
    return text


def password_text(raw: str) -> str:
    """The words as said: the recognizer's sentence capital and marks come off."""
    words = (word.strip(".,?!;:") for word in raw.split())
    text = " ".join(word for word in words if word)
    if re.match(r"[A-Z][a-z]", text):
        text = text[0].lower() + text[1:]
    return text
