"""A small cascade for the web shell's own stylesheets, so tests can ask which rule wins.

The polish audit's button bug was a cascade bug: `button:hover` came before
`button.primary` at equal specificity, so a hovered primary button kept its
resting fill. A test that only greps for a rule cannot see that; this module
resolves one property for one described element the way a browser does for the
selectors the shell actually writes: type, #id, .class, [attr], [attr=value],
:hover/:active/:focus-visible/:disabled and friends as element states, :not(),
:where(), :is(), descendant and child combinators, ::before/::after/::backdrop,
specificity, source order and !important. Media queries are evaluated against a
described environment (window width, reduced motion, forced colours).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from tests import shell_css

STATES = {"hover", "active", "focus", "focus-visible", "focus-within", "disabled", "checked", "open",
          "first-of-type", "last-child", "first-child", "empty", "placeholder"}


@dataclass
class Element:
    tag: str
    classes: tuple[str, ...] = ()
    attrs: dict = field(default_factory=dict)
    states: frozenset = frozenset()
    id: str = ""
    parent: "Element | None" = None


@dataclass
class Environment:
    width: int = 1120
    reduced_motion: bool = False
    forced_colors: bool = False
    reduced_transparency: bool = False
    starting_style: bool = False


def split_top(text: str, separator: str = ",") -> list[str]:
    parts, depth, current = [], 0, ""
    for char in text:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == separator and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def _compounds(selector: str) -> list[tuple[str, str]]:
    """[(combinator, compound)] from left to right; the first combinator is ''."""
    result, current, depth, combinator = [], "", 0, ""
    index = 0
    while index < len(selector):
        char = selector[index]
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if depth == 0 and (char in " >+~"):
            if current.strip():
                result.append((combinator, current.strip()))
                current = ""
                combinator = " "
            if char in ">+~":
                combinator = char
            index += 1
            continue
        current += char
        index += 1
    if current.strip():
        result.append((combinator, current.strip()))
    return result


TOKEN = re.compile(r"::?[\w-]+(?:\((?:[^()]|\([^()]*\))*\))?|\[[^\]]*\]|#[\w-]+|\.[\w-]+|\*|[\w-]+")


def _parts(compound: str) -> list[str]:
    return TOKEN.findall(compound)


def compound_specificity(compound: str) -> tuple[int, int, int]:
    a = b = c = 0
    for part in _parts(compound):
        if part.startswith("#"):
            a += 1
        elif part.startswith((".", "[")):
            b += 1
        elif part.startswith("::"):
            c += 1
        elif part.startswith(":"):
            name = part[1:].split("(", 1)[0]
            if name == "where":
                continue
            if name in {"not", "is"}:
                inner = part[part.index("(") + 1:-1]
                best = max((specificity(item) for item in split_top(inner)), default=(0, 0, 0))
                a, b, c = a + best[0], b + best[1], c + best[2]
            else:
                b += 1
        elif part != "*":
            c += 1
    return a, b, c


def specificity(selector: str) -> tuple[int, int, int]:
    total = (0, 0, 0)
    for _combinator, compound in _compounds(selector):
        s = compound_specificity(compound)
        total = (total[0] + s[0], total[1] + s[1], total[2] + s[2])
    return total


def _match_part(part: str, element: Element) -> bool:
    if part == "*":
        return True
    if part.startswith("#"):
        return element.id == part[1:]
    if part.startswith("."):
        return part[1:] in element.classes
    if part.startswith("["):
        body = part[1:-1]
        if "=" in body:
            name, value = body.split("=", 1)
            operator = name[-1] if name[-1] in "~^$*|" else ""
            name = name.rstrip("~^$*|").strip()
            value = value.strip().strip("\"'")
            actual = element.attrs.get(name)
            if actual is None:
                return False
            actual = str(actual)
            return {"": actual == value, "~": value in actual.split(), "^": actual.startswith(value),
                    "$": actual.endswith(value), "*": value in actual}.get(operator, False)
        return body.strip() in element.attrs
    if part.startswith("::"):
        return True  # pseudo-elements are matched by resolve()
    if part.startswith(":"):
        name = part[1:].split("(", 1)[0]
        if name in {"not", "is", "where"}:
            inner = split_top(part[part.index("(") + 1:-1])
            hit = any(matches(item, element) for item in inner)
            return not hit if name == "not" else hit
        if name == "disabled":
            return "disabled" in element.attrs or "disabled" in element.states
        if name == "root":
            return element.tag == "html"
        return name in element.states
    return element.tag == part


def _match_compound(compound: str, element: Element) -> bool:
    return all(_match_part(part, element) for part in _parts(compound))


def matches(selector: str, element: Element) -> bool:
    chain = _compounds(selector)

    def walk(index: int, node: Element | None) -> bool:
        if node is None:
            return False
        combinator, compound = chain[index]
        if not _match_compound(compound, node):
            return False
        if index == 0:
            return True
        if combinator == ">":
            return walk(index - 1, node.parent)
        ancestor = node.parent
        while ancestor is not None:
            if walk(index - 1, ancestor):
                return True
            ancestor = ancestor.parent
        return False

    return bool(chain) and walk(len(chain) - 1, element)


def media_applies(prelude: str, env: Environment) -> bool:
    text = prelude.replace(" ", "").lower()
    if text.startswith("@keyframes") or text.startswith("@font-face"):
        return False
    if text.startswith("@starting-style"):
        return env.starting_style
    if text.startswith("@container") or text.startswith("@supports"):
        return True
    if not text.startswith("@media"):
        return False
    result = True
    for condition in re.findall(r"\(([^()]*)\)", text):
        key, _, value = condition.partition(":")
        if key == "max-width":
            result &= env.width <= int(re.sub(r"\D", "", value))
        elif key == "min-width":
            result &= env.width >= int(re.sub(r"\D", "", value))
        elif key == "prefers-reduced-motion":
            result &= (value == "reduce") == env.reduced_motion
        elif key == "forced-colors":
            result &= (value == "active") == env.forced_colors
        elif key == "prefers-reduced-transparency":
            result &= (value == "reduce") == env.reduced_transparency
    return result


SHORTHANDS = {
    "background-color": ("background",),
    "background-image": ("background",),
    "transition-duration": ("transition",),
    "transition-property": ("transition",),
    "transition-timing-function": ("transition",),
    "animation-name": ("animation",),
    "outline-color": ("outline",),
    "outline-width": ("outline",),
    "border-color": ("border",),
}


def resolve(element: Element, prop: str, env: Environment | None = None, pseudo: str = "") -> str | None:
    """The winning declared value of `prop` for `element` (or its ::pseudo), or None."""
    env = env or Environment()
    names = (prop,) + SHORTHANDS.get(prop, ())
    best = None
    order = 0
    for _sheet, stack, selector_list, body in shell_css.all_rules():
        order += 1
        if not all(media_applies(prelude, env) for prelude in stack):
            continue
        declared = [(name, value) for name, value in shell_css.declarations(body) if name in names]
        if not declared:
            continue
        for selector in split_top(selector_list):
            chain = _compounds(selector)
            if not chain:
                continue
            last = chain[-1][1]
            found = re.search(r"::([\w-]+)", last)
            if (found.group(1) if found else "") != pseudo:
                continue
            if not matches(selector, element):
                continue
            for index, (name, value) in enumerate(declared):
                important = value.endswith("!important")
                key = (important, specificity(selector), order, index)
                if best is None or key >= best[0]:
                    best = (key, name, value.replace("!important", "").strip())
    if best is None:
        return None
    return best[2]


def button(*classes: str, states=(), attrs=None, parent: Element | None = None, tag: str = "button") -> Element:
    return Element(tag, tuple(classes), dict(attrs or {}), frozenset(states), parent=parent)
