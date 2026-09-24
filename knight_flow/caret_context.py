"""Small, ephemeral accessibility reads for sentence-aware insertion.

No selection, clipboard, focus change, document scan, disk write or network call.
Unsupported, secure and busy editors simply retain standalone formatting.
"""
from __future__ import annotations

import re
import sys
import threading
from collections.abc import Mapping
from typing import Any

CONTEXT_CHARS = 32
_READ_LOCK = threading.Lock()
_LOWERABLE = frozenset((
    "a an the and but or so yet because although while since unless until if when "
    "we you he she they it this that these those there here then now also still "
    "please send put make take get give keep let use add update check look see "
    "with without from for to of on in at by as about after before into over "
    "my your our their his her its all any some more less each every both "
    "can could will would shall should may might must do does did have has had "
    "is are was were be been being not no yes thanks okay"
).split())


def usable_context(context: object) -> bool:
    return bool(isinstance(context, Mapping)
                and not context.get("password") and not context.get("selected")
                and isinstance(context.get("left"), str)
                and isinstance(context.get("right"), str))


def apply_caret_context(text: str, spoken: str, context: object,
                       config: dict[str, Any]) -> str:
    """Adapt only inferred sentence edges; never copy surrounding words."""
    if not text or not usable_context(context) or "\n" in text:
        return text
    left = context["left"][-CONTEXT_CHARS:]
    right = context["right"][:CONTEXT_CHARS]
    previous = left.rstrip(" \t\"'\u201d\u2019)]}")
    continuation = bool(previous and previous[-1] not in ".!?\n\r:")
    if continuation:
        # The standalone formatter may have treated an initial conjunction as
        # verbal padding. Here it joins real prose, so preserve that exact word.
        first = re.match(r"([\"'(]*)([A-Z][a-z]+)\b", text)
        if first and first[2].lower() in _LOWERABLE:
            from .vocabulary import parse_terms

            terms = parse_terms(config.get("dictionary", {}).get("words", []))
            preserved = {term.text.split()[0] for term in terms if term.text}
            if first[2] not in preserved:
                start = first.start(2)
                text = text[:start] + text[start].lower() + text[start + 1:]
        lead = re.match(r"^(and|but|or)\s+(\w+)", spoken.strip(), re.I)
        if lead and re.match(re.escape(lead[2]) + r"\b", text, re.I):
            text = lead[1].lower() + " " + text
    # A dictated full stop is intentional; an ASR/model full stop is inferred.
    explicit_terminal = re.search(
        r"\b(?:period|full stop|question mark|exclamation(?: mark| point)?|ellipsis)\s*[.!?]*$",
        spoken, re.I,
    )
    if right and not right.startswith(("\n", "\r")) and not explicit_terminal:
        if text.endswith(".") and not text.endswith(".."):
            text = text[:-1]
    return text


# Marks a word follows after exactly one space: "Done." + "Next" is "Done. Next".
_SPACE_AFTER = frozenset(".,;:!?)]}\"'”’")
# What a take may start with and still be a word that needs its space.
_WORD_START = frozenset("\"'(“‘$#@")


def join_at_caret(text: str, context: object) -> str:
    """Use actual adjacent characters instead of a blanket leading space.

    Exactly one space, never two and never none (commandment 83). X-602: a
    caret after a period or comma used to get NO space ("Done.Next we test
    the installer"), because only a letter or digit on the left earned one.
    A newline, a space already there, or an opening bracket gets none.
    """
    if not text or not usable_context(context):
        return text
    left, right = context["left"], context["right"]
    starts_word = text[0].isalnum() or text[0] in _WORD_START
    closes = bool(left) and left[-1] in _SPACE_AFTER
    if closes and left[-1] in "\"'" and (len(left) < 2 or left[-2].isspace()):
        closes = False  # an opening quote: the dictation goes inside it
    if left and (left[-1].isalnum() or closes) and starts_word:
        text = " " + text
    if right and right[0].isalnum() and (text[-1].isalnum() or text[-1] in ".,;:!?"):
        text += " "
    return text


def _read_uia(automation: Any, uia: Any) -> dict[str, str] | None:
    element = automation.GetFocusedElement()
    if (not element or element.CurrentIsPassword or not element.CurrentHasKeyboardFocus
            or element.CurrentControlType not in (uia.UIA_EditControlTypeId, uia.UIA_DocumentControlTypeId)):
        return None
    pattern = element.GetCurrentPattern(uia.UIA_TextPatternId).QueryInterface(uia.IUIAutomationTextPattern)
    selected = pattern.GetSelection()
    if selected.Length != 1:
        return None
    caret = selected.GetElement(0)
    if caret.CompareEndpoints(uia.TextPatternRangeEndpoint_Start, caret, uia.TextPatternRangeEndpoint_End):
        return None
    before, after = caret.Clone(), caret.Clone()
    before.MoveEndpointByUnit(uia.TextPatternRangeEndpoint_Start, uia.TextUnit_Character, -CONTEXT_CHARS)
    after.MoveEndpointByUnit(uia.TextPatternRangeEndpoint_End, uia.TextUnit_Character, CONTEXT_CHARS)
    left, right = before.GetText(CONTEXT_CHARS), after.GetText(CONTEXT_CHARS)
    if not automation.CompareElements(element, automation.GetFocusedElement()):
        return None
    # A caret/selection move inside the same editor also invalidates the read.
    latest = pattern.GetSelection()
    if latest.Length != 1 or not caret.Compare(latest.GetElement(0)):
        return None
    return {"left": left[-CONTEXT_CHARS:], "right": right[:CONTEXT_CHARS]}


def _read_windows() -> dict[str, str] | None:
    import comtypes
    from comtypes.client import CreateObject, GetModule

    # comtypes initializes the importing thread as STA. Match that apartment
    # when its first import happens in this short-lived worker.
    comtypes.CoInitialize()
    try:
        uia = GetModule("UIAutomationCore.dll")
        automation = CreateObject(uia.CUIAutomation8, interface=uia.IUIAutomation2)
        automation.AutoSetFocus = False
        automation.ConnectionTimeout = 100
        automation.TransactionTimeout = 100
        return _read_uia(automation, uia)
    finally:
        comtypes.CoUninitialize()


def _read_macos() -> dict[str, str] | None:
    # Native AX functions avoid an additional Objective-C bridge dependency.
    import ctypes as c
    from contextlib import ExitStack

    ax = c.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    cf = c.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    ptr = c.c_void_p
    outptr = c.POINTER(ptr)

    class CFRange(c.Structure):
        _fields_ = [("location", c.c_long), ("length", c.c_long)]

    def bind(lib, name, result, *args):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, args
        return fn

    trusted = bind(ax, "AXIsProcessTrusted", c.c_bool)
    if not trusted():
        return None  # This read never prompts for a new permission.
    system = bind(ax, "AXUIElementCreateSystemWide", ptr)
    timeout = bind(ax, "AXUIElementSetMessagingTimeout", c.c_int, ptr, c.c_float)
    attribute = bind(ax, "AXUIElementCopyAttributeValue", c.c_int, ptr, ptr, outptr)
    parameterized = bind(ax, "AXUIElementCopyParameterizedAttributeValue", c.c_int, ptr, ptr, ptr, outptr)
    make_value = bind(ax, "AXValueCreate", ptr, c.c_int, ptr)
    read_value = bind(ax, "AXValueGetValue", c.c_bool, ptr, c.c_int, ptr)
    value_type = bind(ax, "AXValueGetType", c.c_int, ptr)
    make_string = bind(cf, "CFStringCreateWithCString", ptr, ptr, c.c_char_p, c.c_uint32)
    string_type = bind(cf, "CFStringGetTypeID", c.c_ulong)
    type_id = bind(cf, "CFGetTypeID", c.c_ulong, ptr)
    string = bind(cf, "CFStringGetCString", c.c_bool, ptr, ptr, c.c_long, c.c_uint32)
    equal = bind(cf, "CFEqual", c.c_bool, ptr, ptr)
    release = bind(cf, "CFRelease", None, ptr)
    utf8 = 0x08000100
    with ExitStack() as refs:
        def owned(value):
            if value:
                refs.callback(release, value)
            return value

        def key(name):
            return owned(make_string(None, name.encode("ascii"), utf8))

        def get(element, name):
            value = ptr()
            if attribute(element, key(name), c.byref(value)) != 0:
                return None
            return owned(value.value)

        def as_string(value):
            if not value or type_id(value) != string_type():
                return ""
            buffer = c.create_string_buffer(CONTEXT_CHARS * 4 + 32)
            return buffer.value.decode("utf-8") if string(value, buffer, len(buffer), utf8) else ""

        root = owned(system())
        timeout(root, 0.1)
        element = get(root, "AXFocusedUIElement")
        if not element:
            return None
        if as_string(get(element, "AXSubrole")) == "AXSecureTextField":
            return None
        if as_string(get(element, "AXRole")) not in {"AXTextField", "AXTextArea", "AXComboBox"}:
            return None
        selected = get(element, "AXSelectedTextRange")
        position = CFRange()
        if not selected or value_type(selected) != 4 or not read_value(selected, 4, c.byref(position)) or position.length:
            return None

        def slice_text(start, length):
            if not length:
                return ""
            requested = CFRange(start, length)
            range_value = owned(make_value(4, c.byref(requested)))
            result = ptr()
            if parameterized(element, key("AXStringForRange"), range_value, c.byref(result)) != 0:
                return None
            return as_string(owned(result.value))

        left_size = min(CONTEXT_CHARS, position.location)
        left = slice_text(position.location - left_size, left_size)
        # One right-hand character is enough to distinguish a suffix from EOF.
        # An out-of-range parameter at EOF is expected and reads as no suffix.
        right = slice_text(position.location, 1) or ""
        latest_element, latest_selection = get(root, "AXFocusedUIElement"), get(element, "AXSelectedTextRange")
        if left is None or not latest_element or not latest_selection:
            return None
        if not equal(element, latest_element) or not equal(selected, latest_selection):
            return None
        return {"left": left, "right": right}


def read_caret_context(*, timeout: float = 0.08) -> dict[str, str] | None:
    """Bound total waiting; a hung accessibility provider cannot grow workers."""
    if sys.platform not in {"win32", "darwin"} or not _READ_LOCK.acquire(blocking=False):
        return None
    done = threading.Event()
    result: list[dict[str, str] | None] = []

    def read():
        try:
            result.append(_read_windows() if sys.platform == "win32" else _read_macos())
        except Exception:
            result.append(None)
        finally:
            _READ_LOCK.release()
            done.set()

    threading.Thread(target=read, name="caret-context", daemon=True).start()
    if not done.wait(max(0.0, min(timeout, 0.15))):
        return None
    return result[0] if result else None
