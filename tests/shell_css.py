"""Read the web shell's stylesheets as rules, for the tests that hold them to one scale.

A small reader, not a CSS engine: comments and data: URIs are blanked, at-rules
(@media, @supports, @starting-style, @keyframes) nest, and every rule comes back
as (at-rule stack, selector, declarations). That is enough to ask "which rules set
border-radius, and to what", which is the question these tests ask.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "knight_flow" / "web_shell" / "shell_assets"
SHEETS = ("shell.css", "workspaces.css")


def source(name: str) -> str:
    text = (ASSETS / name).read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r'url\("data:[^"]*"\)', 'url("data:")', text)


def rules(text: str) -> list[tuple[tuple[str, ...], str, str]]:
    found: list[tuple[tuple[str, ...], str, str]] = []

    def walk(start: int, stack: tuple[str, ...]) -> int:
        index, head = start, start
        while index < len(text):
            char = text[index]
            if char in "\"'":
                index = text.index(char, index + 1) + 1
                continue
            if char == "{":
                prelude = text[head:index].strip()
                if prelude.startswith("@") and not prelude.startswith(("@font-face", "@page")):
                    index = walk(index + 1, stack + (prelude,))
                else:
                    end = index + 1
                    while text[end] != "}":
                        end = text.index(text[end], end + 1) + 1 if text[end] in "\"'" else end + 1
                    found.append((stack, prelude, text[index + 1:end]))
                    index = end
                head = index + 1
            elif char == "}":
                return index
            elif char == ";" and text[head:index].strip().startswith("@"):
                head = index + 1
            index += 1
        return index

    walk(0, ())
    return found


def all_rules() -> list[tuple[str, tuple[str, ...], str, str]]:
    return [(name, stack, selector, body) for name in SHEETS for stack, selector, body in rules(source(name))]


def declarations(body: str) -> list[tuple[str, str]]:
    result = []
    for part in re.split(r";(?![^(]*\))", body):
        if ":" in part:
            name, value = part.split(":", 1)
            result.append((name.strip().lower(), value.strip()))
    return result


def values(prop: str) -> list[tuple[str, tuple[str, ...], str, str]]:
    """(sheet, at-rules, selector, value) for every declaration of one property."""
    return [(name, stack, selector, value) for name, stack, selector, body in all_rules()
            for key, value in declarations(body) if key == prop]


def defined_properties() -> set[str]:
    names = set()
    for _name, _stack, _selector, body in all_rules():
        names.update(key for key, _value in declarations(body) if key.startswith("--"))
    return names


def used_properties() -> set[str]:
    names = set()
    for name in SHEETS:
        names.update(re.findall(r"var\(\s*(--[\w-]+)", source(name)))
    return names


def tokens_block() -> str:
    """The body of the :root rule that defines the scale (the one holding --r-md)."""
    for _name, stack, selector, body in all_rules():
        if selector == ":root" and not stack and "--r-md" in body:
            return body
    return ""
