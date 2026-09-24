"""The writing-style choice after the third real dictation, on the web Writing page.

X-137 asks once more, at the third real dictation, with the person's own words
finished both ways. That prompt was the one full window a new user met that
still drew in square Tk panes (overlay.open_finish_chooser). X-610 draws it at
the top of the web shell's Writing page instead; the Tk window stays as the
fallback when the renderer is unavailable. The choice itself is saved by the
same code either way (App.choose_finish).
"""
from __future__ import annotations

from collections.abc import Callable

#: format_intensity values: "standard" is the Chill finish.
CHOICES = ("standard", "executive")


class FinishChoice:
    def __init__(self, choose: Callable[[str], str]) -> None:
        self._choose = choose
        self.pending: dict[str, str] | None = None

    def offer(self, chill: str, executive: str) -> None:
        self.pending = {"chill": str(chill or ""), "executive": str(executive or "")}

    def snapshot(self) -> dict[str, str] | None:
        return dict(self.pending) if self.pending else None

    def act(self, operation: str) -> str:
        """Commit or dismiss the offer; the answer is the confirmation to show."""
        if self.pending is None:
            raise ValueError("That choice has already been made.")
        if operation not in (*CHOICES, "later"):
            raise ValueError("This action is not available from this window.")
        self.pending = None
        if operation == "later":
            return "Kept your current finish. You can change it here any time."
        return self._choose(operation)
