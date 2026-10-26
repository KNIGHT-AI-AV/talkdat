"""A simulated desktop of text fields, for testing insertion without real input.

It behaves the way an editor does where it matters to a replacement: one caret
and an optional selection per field, typing and pasting replace the selection,
a click moves the caret, focus belongs to one field in one window, Enter on a
single-line field submits and clears it. Reads are bounded the way the
accessibility readers are, and a field may transform what is pasted into it
(autocorrect, smart quotes) or refuse to be read at all.

It is also the TargetAdapter for knight_flow.verified_replace, so the same
object is what the person acts on and what the app reads and writes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from knight_flow.verified_replace import ANCHOR_CHARS, TargetRead


@dataclass
class Field:
    element: tuple
    text: str = ""
    caret: int = 0
    selection: tuple[int, int] | None = None
    password: bool = False
    readable: bool = True
    single_line: bool = False
    #: Applied to text the APP pastes (not to what the person types).
    paste_transform: Callable[[str], str] | None = None
    #: When False, the app's paste silently does nothing (a busy target).
    accepts_paste: bool = True
    #: When True, the app's paste reports it was delivered and nothing arrives
    #: (a chord the target dropped after the clipboard was set).
    drops_paste: bool = False
    #: When set, select_before_caret selects this many characters too few.
    select_short_by: int = 0
    sent: list[str] = field(default_factory=list)


class Desktop:
    def __init__(self) -> None:
        self.windows: dict[int, dict[tuple, Field]] = {}
        self.focus: tuple[int, tuple] | None = None
        self.log: list[str] = []

    # --- building ----------------------------------------------------------
    def add(self, window: int, element: tuple, text: str = "", **options) -> Field:
        box = Field(element=element, text=text, caret=len(text), **options)
        self.windows.setdefault(window, {})[element] = box
        if self.focus is None:
            self.focus = (window, element)
        return box

    @property
    def field(self) -> Field:
        window, element = self.focus
        return self.windows[window][element]

    # --- the person ----------------------------------------------------------
    def _replace_selection(self, box: Field, text: str) -> None:
        start, end = box.selection if box.selection else (box.caret, box.caret)
        box.text = box.text[:start] + text + box.text[end:]
        box.caret = start + len(text)
        box.selection = None

    def type(self, text: str) -> None:
        self.log.append(f"type {text!r}")
        self._replace_selection(self.field, text)

    def backspace(self, count: int = 1) -> None:
        box = self.field
        for _ in range(count):
            if box.selection:
                self._replace_selection(box, "")
            elif box.caret:
                box.text = box.text[: box.caret - 1] + box.text[box.caret:]
                box.caret -= 1

    def move(self, delta: int) -> None:
        box = self.field
        box.selection = None
        box.caret = max(0, min(len(box.text), box.caret + delta))

    def click(self, position: int) -> None:
        box = self.field
        box.selection = None
        box.caret = max(0, min(len(box.text), position))

    def select(self, start: int, end: int) -> None:
        box = self.field
        box.selection = (max(0, start), min(len(box.text), end))
        box.caret = box.selection[1]

    def focus_on(self, window: int, element: tuple) -> None:
        self.focus = (window, element)

    def submit(self) -> None:
        box = self.field
        box.sent.append(box.text)
        box.text, box.caret, box.selection = "", 0, None

    # --- the app (verified_replace.TargetAdapter) -------------------------------
    def read(self, left_chars: int = ANCHOR_CHARS) -> TargetRead:
        window, element = self.focus
        box = self.field
        if not box.readable:
            return TargetRead(ok=False)
        return TargetRead(
            ok=True, window=window, element=element,
            left=box.text[max(0, box.caret - left_chars): box.caret],
            right=box.text[box.caret: box.caret + ANCHOR_CHARS],
            collapsed=box.selection is None, password=box.password,
        )

    def app_paste(self, text: str) -> bool:
        box = self.field
        if not box.accepts_paste:
            return False
        if box.drops_paste:
            return True
        if box.paste_transform is not None:
            text = box.paste_transform(text)
        self._replace_selection(box, text)
        return True

    def paste(self, text: str) -> bool:
        self.log.append(f"app paste {text!r}")
        return self.app_paste(text)

    def select_before_caret(self, text: str) -> str | None:
        box = self.field
        length = len(text) - box.select_short_by
        if box.selection is not None or box.caret < length or length <= 0:
            return None
        box.selection = (box.caret - length, box.caret)
        return box.text[box.selection[0]: box.selection[1]]

    def collapse_to(self, read: TargetRead) -> None:
        box = self.field
        if box.selection is not None:
            box.caret = box.selection[1]
        box.selection = None

    def everything(self) -> dict[tuple[int, tuple], str]:
        return {(window, element): box.text for window, fields in self.windows.items()
                for element, box in fields.items()}
