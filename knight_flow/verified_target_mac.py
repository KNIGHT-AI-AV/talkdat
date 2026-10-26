"""T1: the platform half of verified_replace -- the Accessibility (AX) API on macOS.

verified_replace.py decides; this reads and selects, the way verified_target.py
does with UI Automation on Windows. Three Mac facts shape it:

* AX has no runtime id. "The same field" is proved by keeping a reference to
  the element the draft went into and comparing a fresh one with CFEqual, which
  compares the element itself, never its text. A TargetRead carries small
  numbers handed out by that comparison (``_IDENTITIES``), so two reads agree
  only when their elements -- and their windows -- are equal.
* AX ranges count UTF-16 code units; Python strings count code points. An emoji
  is two units and a family emoji with joiners is several. Every offset here is
  in units and every comparison is between Python strings; the two never mix.
* Selecting is a write into another program. It is made only after the exact
  draft has been read immediately before the caret, it is read back afterwards
  (the range AND the text), and it is checked once more just before the paste.
  Nothing is ever deleted by count, and nothing is pasted over a selection this
  module did not prove.

Terminals and remote-desktop clients are never targets: their text views answer
AX, but what they hold is not the person's document.

Pure functions over a provider object, so the tests drive a simulated one
(tests/simulated_ax.py); the ctypes binding is at the bottom and is never
reached by a test (tests/device_guard.py refuses the AX library outright).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from typing import Any, Callable

from .field_context import is_terminal_app
from .verified_replace import ANCHOR_CHARS, TargetRead

#: Roles whose text AX reads and selects by range.
TEXT_ROLES = frozenset({"AXTextField", "AXTextArea", "AXComboBox"})
SECURE_SUBROLE = "AXSecureTextField"

#: Remote-desktop clients and screen sharers on the Mac, by bundle file name.
#: Anything matching paste.REMOTE_PROCESS_MARKERS is refused as well.
REMOTE_APPS = frozenset({
    "microsoft remote desktop.app", "windows app.app", "screen sharing.app", "screens 5.app", "screens.app",
    "citrix workspace.app", "royal tsx.app", "chrome remote desktop host.app",
})

UNREAD = TargetRead(ok=False)


def utf16_len(text: str) -> int:
    """How many UTF-16 code units AX counts for ``text``."""
    return len(str(text).encode("utf-16-le", "surrogatepass")) // 2


def _is_low_surrogate(char: str) -> bool:
    return "\udc00" <= char <= "\udfff"


def _is_high_surrogate(char: str) -> bool:
    return "\ud800" <= char <= "\udbff"


def _is_range(value: Any) -> bool:
    return (isinstance(value, tuple) and len(value) == 2
            and all(isinstance(part, int) and not isinstance(part, bool) for part in value))


def unsupported_app(name: object) -> bool:
    """True for a terminal or a remote-desktop client (and for an app that
    cannot be named: a field nobody can attribute is not proved)."""
    if not isinstance(name, str) or not name.strip():
        return True
    lowered = name.strip().lower()
    if is_terminal_app(lowered) or lowered in REMOTE_APPS:
        return True
    from .paste import REMOTE_PROCESS_MARKERS

    return any(marker in lowered for marker in REMOTE_PROCESS_MARKERS)


class _Identities:
    """Small numbers for AX elements, equal exactly when the elements are.

    Holds a reference to each element it has numbered (the provider retains it)
    so a later read can be compared with CFEqual, the only identity AX offers.
    Bounded: the oldest is released, and an element seen again after that gets a
    new number, so a stale comparison can only refuse, never match wrongly."""

    def __init__(self, limit: int = 64) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[int, Any, Any]] = []
        self._next = 0
        self._limit = limit

    def number(self, provider: Any, element: Any) -> int:
        with self._lock:
            for serial, owner, known in self._items:
                if owner is provider and provider.same(known, element):
                    return serial
            self._next += 1
            provider.retain(element)
            self._items.append((self._next, provider, element))
            while len(self._items) > self._limit:
                _serial, owner, old = self._items.pop(0)
                owner.release(old)
            return self._next


_IDENTITIES = _Identities()


def _numbers(ax: Any, element: Any) -> tuple[int, tuple] | None:
    window = ax.attribute(element, "AXWindow")
    if window is None:
        return None
    pid = int(ax.pid(element))
    return _IDENTITIES.number(ax, window), ("ax", pid, _IDENTITIES.number(ax, element))


def read_target(ax: Any, left_chars: int) -> TargetRead:
    """One bounded read of the focused field, or ``TargetRead(ok=False)``."""
    try:
        left_chars = int(left_chars)
        element = ax.focused()
        if element is None or unsupported_app(ax.app_name(ax.pid(element))):
            return UNREAD
        if ax.attribute(element, "AXRole") not in TEXT_ROLES:
            return UNREAD
        numbers = _numbers(ax, element)
        if numbers is None:
            return UNREAD
        window, token = numbers
        if ax.attribute(element, "AXSubrole") == SECURE_SUBROLE:
            # Never read a password field: not its text, not its length.
            return TargetRead(ok=True, window=window, element=token, password=True)
        selected = ax.attribute(element, "AXSelectedTextRange")
        count = ax.attribute(element, "AXNumberOfCharacters")
        if not _is_range(selected) or not isinstance(count, int) or isinstance(count, bool):
            return UNREAD
        start, length = selected
        end = start + length
        if start < 0 or length < 0 or end > count:
            return UNREAD
        # Two units per code point always cover ``left_chars`` code points; the
        # extra two absorb a surrogate pair split at the far end of the read.
        reach = min(start, 2 * max(left_chars, 0) + 2)
        right_reach = min(count - end, 2 * ANCHOR_CHARS + 2)
        left = ax.string_for_range(element, start - reach, reach) if reach else ""
        right = ax.string_for_range(element, end, right_reach) if right_reach else ""
        if left is None or right is None:
            return UNREAD
        if utf16_len(left) != reach or utf16_len(right) != right_reach:
            return UNREAD  # the app answered a different range than the one asked for
        # The read is void if focus or the selection moved while it ran.
        latest = ax.focused()
        if latest is None or not ax.same(element, latest):
            return UNREAD
        if ax.attribute(element, "AXSelectedTextRange") != selected:
            return UNREAD
        if left and _is_low_surrogate(left[0]):
            left = left[1:]
        if right and _is_high_surrogate(right[-1]):
            right = right[:-1]
        return TargetRead(ok=True, window=window, element=token,
                          left=left[-left_chars:] if left_chars > 0 else "",
                          right=right[:ANCHOR_CHARS], collapsed=length == 0, password=False)
    except Exception:
        return UNREAD


@dataclass(frozen=True)
class Selection:
    """A selection this module asked for: where, where the caret was before it,
    and what the field reported right after (``landed``), so a restore can tell
    this module's selection from one the person made since."""

    element: tuple
    start: int
    length: int
    caret: int
    text: str
    landed: tuple | None = None

    def ours(self, current: object) -> bool:
        return current in ((self.start, self.length), self.landed)


def select_before_caret(ax: Any, text: str, record: Callable[[Selection], None] | None = None,
                        ) -> tuple[str | None, Selection | None]:
    """Select exactly ``text`` where it sits immediately before the collapsed
    caret, and return (the selection as read back, the Selection made).

    The Selection is returned as soon as a write was attempted, so a failed
    proof can still be undone, and handed to ``record`` BEFORE the write: a
    caller whose wait ran out still knows what may have been selected. The
    text is returned only when the range AND the selected text read back
    exactly as asked."""
    try:
        element = ax.focused()
        if element is None or unsupported_app(ax.app_name(ax.pid(element))):
            return None, None
        if ax.attribute(element, "AXSubrole") == SECURE_SUBROLE:
            return None, None
        selected = ax.attribute(element, "AXSelectedTextRange")
        if not _is_range(selected) or selected[1] != 0:
            return None, None
        numbers = _numbers(ax, element)
        if numbers is None:
            return None, None
        caret, units = selected[0], utf16_len(text)
        if units <= 0 or units > caret:
            return None, None
        # A selection is never made by count over text nobody has read: the
        # exact draft must be what sits before the caret first.
        if ax.string_for_range(element, caret - units, units) != text:
            return None, None
        made = Selection(element=numbers[1], start=caret - units, length=units, caret=caret, text=text)
        if record is not None:
            record(made)
        if not ax.set_selected_range(element, caret - units, units):
            return None, made
        latest = ax.focused()
        if latest is None or not ax.same(element, latest):
            return None, made
        landed = ax.attribute(element, "AXSelectedTextRange")
        made = replace(made, landed=landed if _is_range(landed) else None)
        if record is not None:
            record(made)
        if landed != (caret - units, units):
            return None, made
        back = ax.attribute(element, "AXSelectedText")
        if back != text:
            return None, made
        return back, made
    except Exception:
        return None, None


def selection_still(ax: Any, made: Selection | None) -> bool:
    """The focused field still holds exactly the selection this module made."""
    if made is None:
        return False
    try:
        element = ax.focused()
        if element is None:
            return False
        numbers = _numbers(ax, element)
        if numbers is None or numbers[1] != made.element:
            return False
        if ax.attribute(element, "AXSelectedTextRange") != (made.start, made.length):
            return False
        return ax.attribute(element, "AXSelectedText") == made.text
    except Exception:
        return False


def restore_caret(ax: Any, made: Selection | None, *, pasted: bool) -> bool:
    """Undo this module's selection, never the person's.

    Nothing of ours to undo when no selection was attempted, when focus is now
    in another field, or when the field's selection is no longer the one this
    module made (the person clicked or selected since: theirs stays). Otherwise,
    before a paste the caret goes back exactly where it was; after a paste that
    could not be proved, a selection still standing collapses to its end -- the
    caret after what the field now holds. True when the field reads as intended."""
    if made is None:
        return True
    try:
        element = ax.focused()
        if element is None:
            return False
        numbers = _numbers(ax, element)
        if numbers is None or numbers[1] != made.element:
            return True
        current = ax.attribute(element, "AXSelectedTextRange")
        if not _is_range(current):
            return False
        if not made.ours(current):
            return True
        if not pasted:
            target = made.caret
        elif current[1]:
            target = current[0] + current[1]
        else:
            return True
        if current == (target, 0):
            return True
        if not ax.set_selected_range(element, target, 0):
            return False
        return ax.attribute(element, "AXSelectedTextRange") == (target, 0)
    except Exception:
        return False


class MacTarget:
    """verified_replace.TargetAdapter over AX, with the app's own
    receipt-checked paste. Every AX call runs on a short-lived worker with a
    timeout, so an app that hangs cannot hang Talk DAT. ``provider`` defaults to
    the real AX binding; the tests pass a simulated one and ``inline=True``.

    A write (select, restore) that outlives its wait is not forgotten: the
    selection it may make is recorded before it is asked for, and a restore
    first lets a still-running write finish (``settle``), so a late selection
    can never be left standing over the draft for the next keystroke."""

    def __init__(self, paste: Callable[[str], bool], provider: Any = None, *, inline: bool = False,
                 timeout: float = 0.3, write_timeout: float = 1.0, settle: float = 2.0) -> None:
        self._paste, self._inline, self._timeout = paste, inline, timeout
        self._write_timeout, self._settle_timeout = write_timeout, settle
        self._provider = provider
        self._made: Selection | None = None
        self._pasted = False
        self._writer: threading.Thread | None = None

    @property
    def _ax(self) -> Any:
        # The real binding loads on first use, on the worker: building a
        # MacTarget costs nothing and touches no library.
        return self._provider if self._provider is not None else _core()

    def _run(self, call: Callable[[], Any], default: Any) -> Any:
        if self._inline:
            return call()
        return in_worker(call, timeout=self._timeout, default=default)

    def _write(self, call: Callable[[], Any], default: Any) -> Any:
        if self._inline:
            return call()
        result: list[Any] = []

        def run() -> None:
            try:
                result.append(call())
            except Exception:
                result.append(default)

        self._writer = threading.Thread(target=run, name="verified-target-mac-write", daemon=True)
        self._writer.start()
        self._writer.join(self._write_timeout)
        return result[0] if result else default

    def _settle(self) -> None:
        if self._writer is not None and self._writer.is_alive():
            self._writer.join(self._settle_timeout)

    def _record(self, made: Selection) -> None:
        self._made = made

    def read(self, left_chars: int) -> TargetRead:
        return self._run(lambda: read_target(self._ax, left_chars), UNREAD)

    def select_before_caret(self, text: str) -> str | None:
        back, made = self._write(lambda: select_before_caret(self._ax, text, self._record), (None, None))
        if made is not None:
            self._made = made
        return back

    def collapse_to(self, read: TargetRead) -> None:
        self._settle()  # a select still running may yet land; let it, then undo it
        self._write(lambda: restore_caret(self._ax, self._made, pasted=self._pasted), False)
        self._settle()  # and the restore itself, before anything else reads the field

    def paste(self, text: str) -> bool:
        # Never paste over a selection this module did not make and prove, or
        # one that moved since: the person may have clicked in between.
        if self._made is None or not self._run(lambda: selection_still(self._ax, self._made), False):
            return False
        self._pasted = True
        return bool(self._paste(text))


def in_worker(call: Callable[[], Any], *, timeout: float = 0.3, default: Any = None) -> Any:
    """``call()`` on a daemon thread; ``default`` on a timeout or an error."""
    result: list[Any] = []

    def run() -> None:
        try:
            result.append(call())
        except Exception:
            result.append(default)

    worker = threading.Thread(target=run, name="verified-target-mac", daemon=True)
    worker.start()
    worker.join(timeout)
    return result[0] if result else default


# --- the real binding: never reached by a test ---------------------------------

_CORE: Any = None
_CORE_LOCK = threading.Lock()


def _core() -> Any:  # pragma: no cover - real AX
    global _CORE
    with _CORE_LOCK:
        if _CORE is None:
            _CORE = _CoreAX()
        return _CORE


class _CoreAX:  # pragma: no cover - real AX
    """The provider over ApplicationServices and CoreFoundation, through ctypes
    with every signature declared. One instance per process, so element numbers
    (_IDENTITIES) persist between the read at insertion and the read at polish.
    It never asks for a permission: an untrusted process gets no element."""

    _RANGE_TYPE = 4  # kAXValueCFRangeType
    _UTF8 = 0x08000100

    def __init__(self) -> None:
        import ctypes as c

        ax = c.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        cf = c.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        ptr, index = c.c_void_p, c.c_long

        class CFRange(c.Structure):
            _fields_ = [("location", index), ("length", index)]

        assert c.sizeof(CFRange) == 16

        def bind(lib: Any, name: str, result: Any, *args: Any) -> Any:
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = result, list(args)
            return fn

        self._c, self._CFRange = c, CFRange
        self._trusted = bind(ax, "AXIsProcessTrusted", c.c_bool)
        self._system = bind(ax, "AXUIElementCreateSystemWide", ptr)
        self._timeout = bind(ax, "AXUIElementSetMessagingTimeout", c.c_int32, ptr, c.c_float)
        self._copy = bind(ax, "AXUIElementCopyAttributeValue", c.c_int32, ptr, ptr, c.POINTER(ptr))
        self._copy_param = bind(ax, "AXUIElementCopyParameterizedAttributeValue", c.c_int32, ptr, ptr, ptr,
                                c.POINTER(ptr))
        self._set = bind(ax, "AXUIElementSetAttributeValue", c.c_int32, ptr, ptr, ptr)
        self._get_pid = bind(ax, "AXUIElementGetPid", c.c_int32, ptr, c.POINTER(c.c_int32))
        self._value_create = bind(ax, "AXValueCreate", ptr, c.c_int32, ptr)
        self._value_get = bind(ax, "AXValueGetValue", c.c_bool, ptr, c.c_int32, ptr)
        self._value_type = bind(ax, "AXValueGetType", c.c_int32, ptr)
        self._str_create = bind(cf, "CFStringCreateWithCString", ptr, ptr, c.c_char_p, c.c_uint32)
        self._str_length = bind(cf, "CFStringGetLength", index, ptr)
        self._str_chars = bind(cf, "CFStringGetCharacters", None, ptr, CFRange, c.POINTER(c.c_uint16))
        self._str_type = bind(cf, "CFStringGetTypeID", c.c_ulong)
        self._num_type = bind(cf, "CFNumberGetTypeID", c.c_ulong)
        self._num_get = bind(cf, "CFNumberGetValue", c.c_bool, ptr, c.c_int, ptr)
        self._type_of = bind(cf, "CFGetTypeID", c.c_ulong, ptr)
        self._equal = bind(cf, "CFEqual", c.c_bool, ptr, ptr)
        self._retain = bind(cf, "CFRetain", ptr, ptr)
        self._release = bind(cf, "CFRelease", None, ptr)
        self._keys: dict[str, int] = {}
        self._root: int | None = None

    def _key(self, name: str) -> int:
        if name not in self._keys:
            self._keys[name] = self._str_create(None, name.encode("ascii"), self._UTF8)
        return self._keys[name]

    def _string(self, value: int) -> str | None:
        if not value or self._type_of(value) != self._str_type():
            return None
        length = self._str_length(value)
        buffer = (self._c.c_uint16 * max(length, 1))()
        self._str_chars(value, self._CFRange(0, length), buffer)
        return bytes(memoryview(buffer).cast("B")[: 2 * length]).decode("utf-16-le", "surrogatepass")

    def _copy_value(self, element: int, name: str) -> int | None:
        out = self._c.c_void_p()
        if self._copy(element, self._key(name), self._c.byref(out)) != 0 or not out.value:
            return None
        return out.value

    def focused(self) -> Any:
        if not self._trusted():
            return None
        if self._root is None:
            self._root = self._system()
            self._timeout(self._root, 0.1)
        value = self._copy_value(self._root, "AXFocusedUIElement")
        return _Owned(self, value) if value else None

    def attribute(self, element: Any, name: str) -> Any:
        value = self._copy_value(element.ref, name)
        if not value:
            return None
        owned = _Owned(self, value)
        if name in ("AXRole", "AXSubrole", "AXSelectedText"):
            return self._string(value)
        if name == "AXWindow":
            return owned
        if name == "AXSelectedTextRange":
            if self._value_type(value) != self._RANGE_TYPE:
                return None
            span = self._CFRange()
            if not self._value_get(value, self._RANGE_TYPE, self._c.byref(span)):
                return None
            return int(span.location), int(span.length)
        if name == "AXNumberOfCharacters":
            if self._type_of(value) != self._num_type():
                return None
            number = self._c.c_int64()
            return int(number.value) if self._num_get(value, 4, self._c.byref(number)) else None  # kCFNumberSInt64Type
        return None

    def string_for_range(self, element: Any, location: int, length: int) -> str | None:
        span = self._CFRange(int(location), int(length))
        param = _Owned(self, self._value_create(self._RANGE_TYPE, self._c.byref(span)))
        out = self._c.c_void_p()
        if self._copy_param(element.ref, self._key("AXStringForRange"), param.ref, self._c.byref(out)) != 0:
            return None
        if not out.value:
            return None
        text = _Owned(self, out.value)  # released when this read is done, not before
        return self._string(text.ref)

    def set_selected_range(self, element: Any, location: int, length: int) -> bool:
        span = self._CFRange(int(location), int(length))
        value = _Owned(self, self._value_create(self._RANGE_TYPE, self._c.byref(span)))
        return self._set(element.ref, self._key("AXSelectedTextRange"), value.ref) == 0

    def same(self, a: Any, b: Any) -> bool:
        return bool(a is not None and b is not None and self._equal(a.ref, b.ref))

    def pid(self, element: Any) -> int:
        pid = self._c.c_int32()
        if self._get_pid(element.ref, self._c.byref(pid)) != 0:
            return 0
        return int(pid.value)

    def app_name(self, pid: int) -> str:
        from AppKit import NSRunningApplication

        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
        url = app.bundleURL() if app is not None else None
        return str(url.lastPathComponent()) if url is not None else ""

    def retain(self, element: Any) -> None:
        element.keep()

    def release(self, element: Any) -> None:
        element.drop()


class _Owned:  # pragma: no cover - real AX
    """A CoreFoundation reference released when Python lets go of it, unless an
    identity number keeps it (``keep``/``drop``)."""

    def __init__(self, core: _CoreAX, ref: int | None) -> None:
        self.core, self.ref, self._kept = core, ref, 0

    def keep(self) -> None:
        if self.ref:
            self.core._retain(self.ref)
            self._kept += 1

    def drop(self) -> None:
        if self.ref and self._kept:
            self.core._release(self.ref)
            self._kept -= 1

    def __del__(self) -> None:
        if self.ref:
            try:
                self.core._release(self.ref)
            except Exception:
                pass
