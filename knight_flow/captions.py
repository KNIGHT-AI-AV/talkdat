"""X-32: live captions of your own speech, for streams and calls.

The display logic lives here, pure and tested: partials arrive word by
word, finals replace them, and the strip shows a steady two-line window
that never jumps backwards. The overlay owns the pixels; caption_stream owns
the separate, local microphone and rolling speech-model work. This display
buffer is a short tail, not a saved transcript.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_LINE_CHARS = 56
LINES = 2


@dataclass
class CaptionBuffer:
    committed: list[str] = field(default_factory=list)
    partial: str = ""

    def update(self, text: str, is_final: bool) -> None:
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return
        if is_final:
            self.committed.extend(_wrap(cleaned))
            self.partial = ""
            # Keep a small tail; captions are a window, not a transcript.
            self.committed = self.committed[-8:]
        else:
            self.partial = cleaned

    def lines(self) -> list[str]:
        rows = list(self.committed)
        if self.partial:
            rows.extend(_wrap(self.partial))
        return rows[-LINES:] if rows else []

    def clear(self) -> None:
        self.committed = []
        self.partial = ""


def _wrap(text: str) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > MAX_LINE_CHARS:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines
