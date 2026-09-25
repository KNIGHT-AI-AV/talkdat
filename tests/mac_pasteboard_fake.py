"""A stand-in for NSPasteboard, so the Mac clipboard logic runs on Windows.

Find-more P0-5 and P1-4 are Mac bugs, and the suite that can run them is on
Windows. This models the parts of AppKit the paste layer uses: items that
carry several types each, data providers (promises) that are asked for their
data only when a reader reads, the pasteboard's changeCount, and the
current-host-only option. `mac_simulation()` then makes the paste layer take
its Mac branches, with every Windows clipboard call disabled so nothing on
this PC's real clipboard can be touched, and pyperclip (what the old Mac code
used) bound to the same fake board.

Not a test module (no `test` prefix): imported by the Mac pasteboard tests.
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import patch

PLAIN = "public.utf8-plain-text"
PNG = "public.png"
RTF = "public.rtf"
FILE_URL = "public.file-url"
TRANSIENT = "org.nspasteboard.TransientType"
CONCEALED = "org.nspasteboard.ConcealedType"
CURRENT_HOST_ONLY = 1
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8


class FakeItem:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.order: list[str] = []
        self.provider = None
        self.promised: list[str] = []
        self.board: FakePasteboard | None = None
        self.clear_option: object = None

    def _set(self, kind: str, payload: bytes) -> None:
        if kind not in self.order:
            self.order.append(kind)
        self.data[kind] = bytes(payload)

    def types(self) -> list[str]:
        return list(self.order)

    def setData_forType_(self, data, kind) -> bool:  # noqa: N802 - AppKit selector
        self._set(str(kind), bytes(data))
        return True

    def setString_forType_(self, text, kind) -> bool:  # noqa: N802
        self._set(str(kind), str(text).encode("utf-8"))
        return True

    def setDataProvider_forTypes_(self, provider, kinds) -> bool:  # noqa: N802
        self.provider = provider
        for kind in kinds:
            if kind not in self.order:
                self.order.append(kind)
            self.promised.append(kind)
        return True

    def dataForType_(self, kind):  # noqa: N802
        kind = str(kind)
        if kind in self.data:
            return self.data[kind]
        if kind in self.promised and self.provider is not None and self.board is not None:
            # What the pasteboard server does for a promise: ask the owner now.
            self.board.promise_reads += 1
            self.provider.pasteboard_item_provideDataForType_(self.board, self, kind)
            return self.data.get(kind)
        return None

    def stringForType_(self, kind):  # noqa: N802
        data = self.dataForType_(kind)
        return None if data is None else data.decode("utf-8")


class FakePasteboard:
    def __init__(self) -> None:
        self.count = 40
        self.items: list[FakeItem] = []
        self.clears: list[object] = []  # the option given with each clear
        self.written: list[FakeItem] = []  # every item ever written, in order
        self.promise_reads = 0
        self.lock = threading.RLock()

    # -- AppKit ----------------------------------------------------------------
    def changeCount(self) -> int:  # noqa: N802
        return self.count

    def _clear(self, option) -> int:
        with self.lock:
            for item in self.items:
                finished = getattr(item.provider, "pasteboardFinishedWithDataProvider_", None)
                if finished is not None:
                    finished(self)
            self.items = []
            self.count += 1
            self.clears.append(option)
            return self.count

    def clearContents(self) -> int:  # noqa: N802
        return self._clear(None)

    def prepareForNewContentsWithOptions_(self, option) -> int:  # noqa: N802
        return self._clear(option)

    def writeObjects_(self, objects) -> bool:  # noqa: N802
        with self.lock:
            for item in objects:
                item.board = self
                # The option the pasteboard was cleared with for this write.
                item.clear_option = self.clears[-1] if self.clears else None
                self.items.append(item)
                self.written.append(item)
            return True

    def pasteboardItems(self) -> list[FakeItem]:  # noqa: N802
        return list(self.items)

    def types(self) -> list[str]:
        seen: list[str] = []
        for item in self.items:
            seen.extend(kind for kind in item.types() if kind not in seen)
        return seen

    def stringForType_(self, kind):  # noqa: N802
        for item in list(self.items):
            if str(kind) in item.types():
                return item.stringForType_(kind)
        return None

    # -- the person and the other apps -------------------------------------------
    def hold(self, *items: list[tuple[str, bytes]]) -> None:
        """Another app copies: the board holds exactly these items."""
        self._clear(None)
        written = []
        for pairs in items:
            item = FakeItem()
            for kind, payload in pairs:
                item._set(kind, payload)
            written.append(item)
        self.writeObjects_(written)

    def contents(self) -> list[list[tuple[str, bytes | None]]]:
        return [[(kind, item.data.get(kind)) for kind in item.types()] for item in self.items]

    def plain_text(self) -> str:
        return self.stringForType_(PLAIN) or ""


def fake_modules(board: FakePasteboard) -> dict[str, types.ModuleType]:
    appkit = types.ModuleType("AppKit")

    class NSObject:
        def __init_subclass__(cls, **_kwargs) -> None:  # accepts pyobjc's protocols=
            super().__init_subclass__()

        @classmethod
        def alloc(cls):
            return cls.__new__(cls)

        def init(self):
            return self

    appkit.NSObject = NSObject
    appkit.NSPasteboard = SimpleNamespace(generalPasteboard=lambda: board)
    appkit.NSPasteboardItem = SimpleNamespace(alloc=lambda: SimpleNamespace(init=FakeItem))
    appkit.NSData = SimpleNamespace(dataWithBytes_length_=lambda payload, length: bytes(payload)[:length])
    appkit.NSPasteboardTypeString = PLAIN
    appkit.NSPasteboardContentsCurrentHostOnly = CURRENT_HOST_ONLY
    objc = types.ModuleType("objc")
    objc.python_method = lambda function: function
    objc.protocolNamed = lambda name: name
    return {"AppKit": appkit, "objc": objc}


class _NoWindowsClipboard:
    """Any WinDLL the old code opens fails, so the real clipboard is never touched."""

    def __init__(self, *_args, **_kwargs) -> None:
        raise OSError("the Mac simulation has no Windows clipboard")


@contextlib.contextmanager
def mac_simulation(board: FakePasteboard):
    """The paste layer on a pretend Mac whose pasteboard is `board`."""
    from knight_flow import mac_support, paste

    try:
        from knight_flow import mac_pasteboard
    except ImportError:  # the code before P0-5, run to show these tests fail on it
        mac_pasteboard = None

    paste._pyautogui()  # imported now: its import reads sys.platform
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, fake_modules(board)))
        # tests/__init__.py turns native clipboard code off for the whole
        # package; here every native call lands on the fake board, so it is
        # turned back on (the Windows DLLs below stay unreachable).
        stack.enter_context(patch.dict(os.environ, {"TALK_DAT_PLAIN_CLIPBOARD": ""}))
        stack.enter_context(patch.object(mac_support, "IS_MAC", True))
        stack.enter_context(patch.object(sys, "platform", "darwin"))
        stack.enter_context(patch.object(ctypes, "windll", None, create=True))
        stack.enter_context(patch.object(ctypes, "WinDLL", _NoWindowsClipboard, create=True))
        stack.enter_context(patch.object(paste, "_CLIPBOARD_OWNERSHIP", None))
        if mac_pasteboard is not None:
            # The promise class is built once per process; the fake's must not outlive the test.
            stack.enter_context(patch.object(mac_pasteboard, "_PROVIDER_CLASS", None))
        # What the old Mac code wrote with: pyperclip's AppKit backend declares
        # the string type (a plain clear) and puts the text there.
        stack.enter_context(patch.object(paste.pyperclip, "copy", lambda text: board.hold([(PLAIN, str(text).encode("utf-8"))])))
        stack.enter_context(patch.object(paste.pyperclip, "paste", board.plain_text))
        stack.enter_context(patch.object(paste, "settle_modifiers", return_value=True))
        yield


def run_in_worker(function, *args, **kwargs):
    """Deliveries run on the speech thread in the app, never the main thread."""
    result: list[object] = []
    failure: list[BaseException] = []

    def work() -> None:
        try:
            result.append(function(*args, **kwargs))
        except BaseException as error:  # noqa: BLE001 - re-raised on the test thread
            failure.append(error)

    worker = threading.Thread(target=work, name="TalkDatSpeechStandIn")
    worker.start()
    worker.join(10.0)
    if failure:
        raise failure[0]
    return result[0] if result else None
