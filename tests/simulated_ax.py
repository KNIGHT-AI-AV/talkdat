"""A simulated macOS Accessibility (AX) provider over the simulated desktop.

knight_flow/verified_target_mac.py reaches AX through a small provider:
``focused``, ``attribute``, ``string_for_range``, ``set_selected_range``,
``same``, ``pid``, ``app_name``, ``retain`` and ``release``. This is that
provider for tests/simulated_editor.Desktop. The person still acts on the
Desktop (type, click, focus, submit); the adapter sees it the way AX reports it:

* ranges and lengths in UTF-16 code units, the selection as (location, length);
* a fresh element object on every focus read, so "the same field" can only be
  proved by ``same`` (CFEqual), never by Python identity;
* a password field whose text cannot be read at all.

It also models what real apps do that a careful adapter must survive: an app
that ignores a selection request, one that selects a different range than it
was asked for, one that refuses, AX calls that fail or answer a shorter range,
a read that races the person, a terminal or remote-desktop window, a field
with no window, and a role that is not a text field.

Nothing here touches a real program; it is plain Python over the Desktop.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from tests.simulated_editor import Desktop, Field


def units(text: str) -> bytes:
    return str(text).encode("utf-16-le", "surrogatepass")


def unit_len(text: str) -> int:
    return len(units(text)) // 2


@dataclass(frozen=True)
class Element:
    """What AX hands out for a field: equal (CFEqual) when it is the same field."""
    window: int
    key: tuple
    serial: int  # differs on every read, like a fresh AXUIElementRef


@dataclass(frozen=True)
class WindowElement:
    window: int
    serial: int


class SimulatedAX:
    def __init__(self, desktop: Desktop) -> None:
        self.desktop = desktop
        self.apps: dict[int, str] = {}          # window -> app bundle name
        self.roles: dict[tuple, str] = {}       # (window, key) -> AXRole
        self.windowless: set[int] = set()
        #: (window, key) -> "honor" | "ignore" | "refuse" | "other" | "clamp"
        self.selecting: dict[tuple, str] = {}
        self.failing: set[str] = set()          # provider methods that raise (an AX error)
        self.short_reads = False                # string_for_range answers one unit short
        self.delay = 0.0                        # every call sleeps this long (a hung app)
        self.delays: dict[str, float] = {}      # or only these calls (a slow write)
        self.calls: list[tuple] = []
        self.retained: dict[Any, int] = {}
        self._serial = 0
        #: method name -> [(nth call, action)]: the person acts right after that call
        self._hooks: dict[str, list[tuple[int, Callable[[], None]]]] = {}
        self._counts: dict[str, int] = {}

    # --- scripting the person mid-operation ----------------------------------------
    def after(self, method: str, nth: int, action: Callable[[], None]) -> None:
        self._hooks.setdefault(method, []).append((nth, action))

    def _called(self, method: str, *args: Any) -> None:
        pause = self.delays.get(method, self.delay)
        if pause:
            time.sleep(pause)
        self.calls.append((method, *args))
        if method in self.failing:
            raise RuntimeError(f"AX error in {method}")

    def _done(self, method: str) -> None:
        self._counts[method] = self._counts.get(method, 0) + 1
        for nth, action in list(self._hooks.get(method, [])):
            if nth == self._counts[method]:
                action()

    def _fresh(self) -> int:
        self._serial += 1
        return self._serial

    def _field(self, element: Element) -> Field:
        return self.desktop.windows[element.window][element.key]

    # --- the provider ----------------------------------------------------------
    def focused(self) -> Element | None:
        self._called("focused")
        try:
            if self.desktop.focus is None:
                return None
            window, key = self.desktop.focus
            return Element(window, key, self._fresh())
        finally:
            self._done("focused")

    def attribute(self, element: Any, name: str) -> Any:
        self._called("attribute", name, getattr(element, "window", None), getattr(element, "key", None))
        try:
            if isinstance(element, WindowElement):
                return None
            box = self._field(element)
            text = box.text
            start, end = box.selection if box.selection else (box.caret, box.caret)
            if name == "AXRole":
                return self.roles.get((element.window, element.key),
                                      "AXTextField" if box.single_line else "AXTextArea")
            if name == "AXSubrole":
                return "AXSecureTextField" if box.password else None
            if name == "AXWindow":
                return None if element.window in self.windowless else WindowElement(element.window, self._fresh())
            if name == "AXSelectedTextRange":
                return unit_len(text[:start]), unit_len(text[start:end])
            if box.password:
                return None  # a secure field answers nothing about its text
            if name == "AXNumberOfCharacters":
                return unit_len(text)
            if name == "AXSelectedText":
                return text[start:end]
            return None
        finally:
            self._done("attribute")

    def string_for_range(self, element: Element, location: int, length: int) -> str | None:
        self._called("string_for_range", element.window, element.key, location, length)
        try:
            box = self._field(element)
            if box.password or not box.readable:
                return None
            data = units(box.text)
            if location < 0 or length < 0 or 2 * (location + length) > len(data):
                return None  # kAXErrorIllegalArgument
            if self.short_reads and length:
                length -= 1
            return data[2 * location: 2 * (location + length)].decode("utf-16-le", "surrogatepass")
        finally:
            self._done("string_for_range")

    def _to_points(self, text: str, unit: int, *, up: bool) -> int:
        """A UTF-16 offset as a code-point index; an offset inside a surrogate
        pair snaps outward, as AppKit keeps a selection on whole characters."""
        count = 0
        for index, char in enumerate(text):
            if count >= unit:
                return index
            width = unit_len(char)
            if count + width > unit:
                return index + 1 if up else index
            count += width
        return len(text)

    def set_selected_range(self, element: Element, location: int, length: int) -> bool:
        self._called("set_selected_range", location, length)
        try:
            box = self._field(element)
            mode = self.selecting.get((element.window, element.key), "honor")
            if mode == "refuse":
                return False
            if mode == "ignore":
                return True
            if mode == "other":
                location += 1
            if mode == "clamp":
                length = max(0, length - 2)
            total = unit_len(box.text)
            location, end = max(0, min(location, total)), max(0, min(location + length, total))
            start_cp = self._to_points(box.text, location, up=False)
            end_cp = self._to_points(box.text, end, up=True)
            if start_cp == end_cp:
                box.selection, box.caret = None, start_cp
            else:
                box.selection, box.caret = (start_cp, end_cp), end_cp
            return True
        finally:
            self._done("set_selected_range")

    def same(self, a: Any, b: Any) -> bool:
        self._called("same")
        try:
            if isinstance(a, WindowElement) and isinstance(b, WindowElement):
                return a.window == b.window
            if isinstance(a, Element) and isinstance(b, Element):
                return (a.window, a.key) == (b.window, b.key)
            return False
        finally:
            self._done("same")

    def pid(self, element: Any) -> int:
        return 500 + element.window

    def app_name(self, pid: int) -> str:
        return self.apps.get(pid - 500, "TextEdit.app")

    def retain(self, element: Any) -> None:
        key = (type(element).__name__, element.window, getattr(element, "key", None))
        self.retained[key] = self.retained.get(key, 0) + 1

    def release(self, element: Any) -> None:
        key = (type(element).__name__, element.window, getattr(element, "key", None))
        self.retained[key] -= 1

    # --- what a test asks afterwards ---------------------------------------------
    def read_text_of(self, window: int, key: tuple) -> bool:
        """True when the adapter asked for any of that field's text (a slice, the
        selected text or even its length)."""
        for call in self.calls:
            if call[0] == "string_for_range" and call[1:3] == (window, key):
                return True
            if (call[0] == "attribute" and call[1] in ("AXSelectedText", "AXNumberOfCharacters")
                    and call[2:4] == (window, key)):
                return True
        return False
