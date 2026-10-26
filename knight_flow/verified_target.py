"""T1: the platform half of verified_replace -- UI Automation on Windows.

verified_replace.py decides; this reads and selects. It uses the same UI
Automation interfaces caret_context.py already reads text with, and adds three
things a replacement needs:

* the focused element's RUNTIME ID, so "the same field" means the same field,
  not merely the same window (two text boxes in one browser tab share it);
* a read bounded to the draft's length plus an anchor, not a fixed 32 chars;
* a SELECTION of exactly the characters before the caret, made by the text
  pattern itself (no keystrokes), read back, and a way to collapse it again.

The paste over the selection is the app's existing receipt-checked clipboard
paste. Everything here is best effort and fails to "not proved": a provider
that does not answer, answers late or answers oddly yields a read with
``ok=False``, and verified_replace keeps the polish as an alternative.

Pure functions over a provider object, so the tests drive a fake one; the
comtypes binding is at the bottom and is never reached by a test.
"""

from __future__ import annotations

from typing import Any

from .verified_replace import ANCHOR_CHARS, TargetRead

# UI Automation constants (UIAutomationClient.h).
UIA_EDIT = 50004
UIA_DOCUMENT = 50030
UIA_TEXT_PATTERN = 10014
ENDPOINT_START, ENDPOINT_END = 0, 1
UNIT_CHARACTER = 0


def read_target(automation: Any, uia: Any, window: int, left_chars: int) -> TargetRead:
    """One bounded read of the focused field, or ``TargetRead(ok=False)``."""
    try:
        element = automation.GetFocusedElement()
        if not element or not element.CurrentHasKeyboardFocus:
            return TargetRead(ok=False)
        if element.CurrentControlType not in (UIA_EDIT, UIA_DOCUMENT):
            return TargetRead(ok=False)
        password = bool(element.CurrentIsPassword)
        runtime = tuple(int(part) for part in (element.GetRuntimeId() or ()))
        pattern = element.GetCurrentPattern(UIA_TEXT_PATTERN)
        pattern = pattern.QueryInterface(uia.IUIAutomationTextPattern) if hasattr(pattern, "QueryInterface") else pattern
        selection = pattern.GetSelection()
        if selection.Length != 1:
            return TargetRead(ok=False)
        caret = selection.GetElement(0)
        collapsed = caret.CompareEndpoints(ENDPOINT_START, caret, ENDPOINT_END) == 0
        document = pattern.DocumentRange
        before, after = caret.Clone(), caret.Clone()
        # From the selection's START to the left and its END to the right, so
        # a non-collapsed read still reports the text around the selection.
        before.MoveEndpointByRange(ENDPOINT_END, caret, ENDPOINT_START)
        before.MoveEndpointByUnit(ENDPOINT_START, UNIT_CHARACTER, -int(left_chars))
        after.MoveEndpointByRange(ENDPOINT_START, caret, ENDPOINT_END)
        after.MoveEndpointByUnit(ENDPOINT_END, UNIT_CHARACTER, ANCHOR_CHARS)
        # X-605: a character move may walk out of the editor into the page.
        if before.CompareEndpoints(ENDPOINT_START, document, ENDPOINT_START) < 0:
            before.MoveEndpointByRange(ENDPOINT_START, document, ENDPOINT_START)
        if after.CompareEndpoints(ENDPOINT_END, document, ENDPOINT_END) > 0:
            after.MoveEndpointByRange(ENDPOINT_END, document, ENDPOINT_END)
        left, right = before.GetText(int(left_chars) + 8), after.GetText(ANCHOR_CHARS + 8)
        # The read is void if focus or selection moved while it ran.
        if not automation.CompareElements(element, automation.GetFocusedElement()):
            return TargetRead(ok=False)
        latest = pattern.GetSelection()
        if latest.Length != 1 or not caret.Compare(latest.GetElement(0)):
            return TargetRead(ok=False)
        return TargetRead(ok=True, window=int(window), element=runtime, left=str(left)[-int(left_chars):],
                          right=str(right)[:ANCHOR_CHARS], collapsed=collapsed, password=password)
    except Exception:
        return TargetRead(ok=False)


def select_before_caret(automation: Any, uia: Any, text: str) -> str | None:
    """Select the ``len(text)`` characters before the collapsed caret through
    the text pattern, and return the selection as read back."""
    try:
        element = automation.GetFocusedElement()
        pattern = element.GetCurrentPattern(UIA_TEXT_PATTERN)
        pattern = pattern.QueryInterface(uia.IUIAutomationTextPattern) if hasattr(pattern, "QueryInterface") else pattern
        selection = pattern.GetSelection()
        if selection.Length != 1:
            return None
        caret = selection.GetElement(0)
        if caret.CompareEndpoints(ENDPOINT_START, caret, ENDPOINT_END) != 0:
            return None
        target = caret.Clone()
        moved = target.MoveEndpointByUnit(ENDPOINT_START, UNIT_CHARACTER, -len(text))
        if moved != -len(text):
            return None
        target.Select()
        latest = pattern.GetSelection()
        if latest.Length != 1:
            return None
        return str(latest.GetElement(0).GetText(len(text) + 8))
    except Exception:
        return None


def collapse_selection(automation: Any, uia: Any) -> None:
    """Collapse the selection to its end: the caret goes back after the draft."""
    try:
        element = automation.GetFocusedElement()
        pattern = element.GetCurrentPattern(UIA_TEXT_PATTERN)
        pattern = pattern.QueryInterface(uia.IUIAutomationTextPattern) if hasattr(pattern, "QueryInterface") else pattern
        selection = pattern.GetSelection()
        if selection.Length != 1:
            return
        current = selection.GetElement(0)
        current.MoveEndpointByRange(ENDPOINT_START, current, ENDPOINT_END)
        current.Select()
    except Exception:
        return


class UiaTarget:
    """verified_replace.TargetAdapter over UI Automation, with the app's own
    paste. Construct it on a COM-initialized thread (see ``windows_target``)."""

    def __init__(self, automation: Any, uia: Any, window: Any, paste: Any) -> None:
        self._automation, self._uia, self._window, self._paste = automation, uia, window, paste

    def read(self, left_chars: int) -> TargetRead:
        return read_target(self._automation, self._uia, int(self._window() or 0), left_chars)

    def select_before_caret(self, text: str) -> str | None:
        return select_before_caret(self._automation, self._uia, text)

    def collapse_to(self, read: TargetRead) -> None:
        collapse_selection(self._automation, self._uia)

    def paste(self, text: str) -> bool:
        return bool(self._paste(text))


def in_com_worker(call: Any, *, timeout: float = 0.3, default: Any = None) -> Any:  # pragma: no cover - real UIA
    """Run ``call(automation, uia)`` on a short-lived COM worker thread, the way
    caret_context.py reads: UI Automation objects belong to the apartment that
    made them, and a provider that hangs must not hang the app. ``default`` on
    a timeout or an error."""
    import threading

    result: list[Any] = []

    def run() -> None:
        import comtypes
        from comtypes.client import CreateObject, GetModule

        comtypes.CoInitialize()
        try:
            uia = GetModule("UIAutomationCore.dll")
            automation = CreateObject(uia.CUIAutomation8, interface=uia.IUIAutomation2)
            automation.AutoSetFocus = False
            automation.ConnectionTimeout = 100
            automation.TransactionTimeout = 100
            result.append(call(automation, uia))
        except Exception:
            result.append(default)
        finally:
            comtypes.CoUninitialize()

    worker = threading.Thread(target=run, name="verified-target", daemon=True)
    worker.start()
    worker.join(timeout)
    return result[0] if result else default


class WindowsTarget:  # pragma: no cover - needs a real desktop
    """The real adapter: every read and selection on its own COM worker, the
    window from the foreground, the paste from the app's own clipboard route."""

    def __init__(self, paste: Any) -> None:
        from .paste import foreground_window_id

        self._window, self._paste = foreground_window_id, paste

    def read(self, left_chars: int) -> TargetRead:
        window = int(self._window() or 0)
        return in_com_worker(lambda automation, uia: read_target(automation, uia, window, left_chars),
                             default=TargetRead(ok=False))

    def select_before_caret(self, text: str) -> str | None:
        return in_com_worker(lambda automation, uia: select_before_caret(automation, uia, text))

    def collapse_to(self, read: TargetRead) -> None:
        in_com_worker(lambda automation, uia: collapse_selection(automation, uia))

    def paste(self, text: str) -> bool:
        return bool(self._paste(text))
