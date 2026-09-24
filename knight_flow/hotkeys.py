from __future__ import annotations

import ctypes
import logging
import queue
import sys
import re
import sys
import threading
import time

from . import mac_support
from collections.abc import Callable
from typing import Any

from pynput import keyboard, mouse


log = logging.getLogger(__name__)

Callback = Callable[[], None]


def apply_trigger_style(hotkeys: dict[str, Any], style: str) -> dict[str, Any]:
    """X-118, his spec: one button or two, chosen plainly.

    - "both" (default): the shipped layout -- a hold chord plus a separate
      tap-to-toggle chord.
    - "hold": ONE button. Hold it while you speak; the separate toggle chord
      is off (the pill click still toggles hands-free).
    - "toggle": ONE button. Tap starts, tap stops; no hold behaviour.
    """
    normalized = dict(hotkeys or {})
    key = str(style or "both").strip().lower()
    if key == "hold":
        normalized["hands_free"] = []
    elif key == "toggle":
        normalized["hands_free"] = list(normalized.get("push_to_talk") or [])
        normalized["push_to_talk"] = []
    return normalized


ALIASES = {
    "win": "cmd",
    "windows": "cmd",
    "super": "cmd",
    "command": "cmd",
    "option": "alt",
    "opt": "alt",
    "escape": "esc",
    "return": "enter",
    "mouse4": "mouse4",
    "x1": "mouse4",
    "mouse5": "mouse5",
    "x2": "mouse5",
    "middle_click": "middle",
    "middleclick": "middle",
}


TAP_ACTIONS = [
    "read_back",
    "translate_toggle",
    "cancel",
    "panic",
    "hands_free",
    "paste_last",
    "copy_last",
    "polish",
    "prompt_engineer",
    "turn_to_list",
    "view_diff",
    "scratchpad",
    # X-178: these three were advertised and dead.
    #
    # Each has a shortcut slot in DEFAULT_CONFIG and a real callback wired in
    # app.py (pin_last:217, meeting_mode:218, translate_last:219), and each has a
    # row in the Settings shortcut editor. What none of them had was a place in
    # this list, and this list is what HotkeyController actually listens for. So
    # a person could open Settings, see the action, record a chord, save it
    # successfully, and press it forever with nothing happening.
    #
    # A shortcut that saves and then does nothing is worse than one that is
    # missing: the missing one sends you looking for another way, and this one
    # makes you doubt your own keyboard.
    "translate_last",
    "pin_last",
    "meeting_mode",
]
HOLD_ACTIONS = ["command_mode", "push_to_talk", "fix_that"]
WATCHDOG_INTERVAL_SECONDS = 0.025

ACTION_TITLES = {
    "push_to_talk": "Hold to talk",
    "hands_free": "Hands-free toggle",
    "command_mode": "Command mode",
    "fix_that": "Fix that",
    "cancel": "Cancel",
    "panic": "Panic stop",
    "paste_last": "Paste last",
    "copy_last": "Copy last",
    "read_back": "Read back",
    "translate_toggle": "Translate toggle",
    "polish": "Polish",
    "prompt_engineer": "Prompt engineer",
    "turn_to_list": "Turn to list",
    "view_diff": "View diff",
    "scratchpad": "Scratchpad",
}


def _chord_words(chord: frozenset[str]) -> str:
    order = {"ctrl": 0, "cmd": 1, "alt": 2, "shift": 3}
    names = {"cmd": "Win", "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "esc": "Esc", "space": "Space"}
    keys = sorted(chord, key=lambda k: (order.get(k, 9), k))
    return "+".join(names.get(key, key.upper() if len(key) == 1 else key.title()) for key in keys)


def chord_conflicts(hotkeys: dict[str, Any]) -> list[str]:
    """X-118, his rule set, made executable: the DIRECTION of nesting decides.

    A hold chord that is a SUBSET of a tap chord is deliberate layering and
    works -- hold Ctrl+Win to talk, add Space to go hands-free; the hold
    debounce absorbs the pass-through. The reverse is broken by physics: keys
    go down one at a time, so reaching a 3-key hold must pass THROUGH a
    2-key tap, and the tap fires before the hold exists. Same-keys across
    two actions is always ambiguous. Each finding is one plain sentence the
    onboarding and Settings can show as-is.
    """
    normalized = normalize_hotkeys(hotkeys)

    def chords(action: str) -> list[frozenset[str]]:
        return [frozenset(chord) for chord in normalized.get(action, []) if chord]

    def title(action: str) -> str:
        return ACTION_TITLES.get(action, action.replace("_", " ").title())

    conflicts: list[str] = []
    taps = [(action, chord) for action in TAP_ACTIONS for chord in chords(action)]
    holds = [(action, chord) for action in HOLD_ACTIONS for chord in chords(action)]

    for tap_action, tap_chord in taps:
        for hold_action, hold_chord in holds:
            if tap_chord == hold_chord:
                conflicts.append(
                    f"Shortcut conflict: {title(tap_action)} and {title(hold_action)} both use {_chord_words(tap_chord)}. Choose a different shortcut for one action."
                )
            elif tap_chord < hold_chord:
                conflicts.append(
                    f"{title(hold_action)} cannot start with {_chord_words(hold_chord)} because {title(tap_action)} activates at {_chord_words(tap_chord)} first. Change either shortcut."
                )

    for index, (action_a, chord_a) in enumerate(taps):
        for action_b, chord_b in taps[index + 1:]:
            if action_a == action_b:
                continue
            if chord_a == chord_b:
                conflicts.append(
                    f"Shortcut conflict: {title(action_a)} and {title(action_b)} both use {_chord_words(chord_a)}. Choose a different shortcut for one action."
                )
            elif chord_a < chord_b:
                conflicts.append(
                    f"{title(action_b)} conflicts with {title(action_a)}: {_chord_words(chord_a)} activates before {_chord_words(chord_b)} is complete. Change either shortcut."
                )
            elif chord_b < chord_a:
                conflicts.append(
                    f"{title(action_a)} conflicts with {title(action_b)}: {_chord_words(chord_b)} activates before {_chord_words(chord_a)} is complete. Change either shortcut."
                )

    for index, (action_a, chord_a) in enumerate(holds):
        for action_b, chord_b in holds[index + 1:]:
            if action_a != action_b and chord_a == chord_b:
                conflicts.append(
                    f"Shortcut conflict: {title(action_a)} and {title(action_b)} both use {_chord_words(chord_a)}. Choose a different shortcut for one action."
                )
    return conflicts


VK_BY_NAME = {
    "ctrl": (0x11, 0xA2, 0xA3),
    "alt": (0x12, 0xA4, 0xA5),
    "shift": (0x10, 0xA0, 0xA1),
    "cmd": (0x5B, 0x5C),
    "space": (0x20,),
    "esc": (0x1B,),
    "enter": (0x0D,),
    "tab": (0x09,),
    "backspace": (0x08,),
    "delete": (0x2E,),
    "home": (0x24,),
    "end": (0x23,),
    "page_up": (0x21,),
    "page_down": (0x22,),
    "middle": (0x04,),
    "mouse4": (0x05,),
    "mouse5": (0x06,),
}


def physical_key_down(name: str) -> bool | None:
    if sys.platform == "darwin":
        return mac_support.physical_key_down(name)
    try:
        user32 = ctypes.windll.user32
    except Exception:
        return None

    codes = VK_BY_NAME.get(name)
    if codes is None and len(name) == 1 and name.isalnum():
        codes = (ord(name.upper()),)
    elif codes is None and name.startswith("f") and name[1:].isdigit():
        number = int(name[1:])
        if 1 <= number <= 24:
            codes = (0x70 + number - 1,)
    elif codes is None and name.isdigit():
        codes = (int(name),)
    if codes is None:
        return None

    return any(bool(user32.GetAsyncKeyState(code) & 0x8000) for code in codes)


def canonical(name: str) -> str:
    name = name.strip().lower().replace(" ", "_")
    return ALIASES.get(name, name)


def key_name(key: keyboard.Key | keyboard.KeyCode) -> str | None:
    special = {
        keyboard.Key.ctrl_l: "ctrl",
        keyboard.Key.ctrl_r: "ctrl",
        keyboard.Key.ctrl: "ctrl",
        keyboard.Key.alt_l: "alt",
        keyboard.Key.alt_r: "alt",
        keyboard.Key.alt: "alt",
        keyboard.Key.shift_l: "shift",
        keyboard.Key.shift_r: "shift",
        keyboard.Key.shift: "shift",
        keyboard.Key.cmd_l: "cmd",
        keyboard.Key.cmd_r: "cmd",
        keyboard.Key.cmd: "cmd",
        keyboard.Key.space: "space",
        keyboard.Key.esc: "esc",
        keyboard.Key.enter: "enter",
        keyboard.Key.tab: "tab",
        keyboard.Key.backspace: "backspace",
        keyboard.Key.delete: "delete",
        keyboard.Key.home: "home",
        keyboard.Key.end: "end",
        keyboard.Key.page_up: "page_up",
        keyboard.Key.page_down: "page_down",
    }
    if key in special:
        return special[key]
    if isinstance(key, keyboard.KeyCode):
        if key.char:
            return canonical(key.char)
        if key.vk is not None:
            return str(key.vk)
    name = getattr(key, "name", None)
    return canonical(name) if name else None


def mouse_name(button: mouse.Button) -> str | None:
    if button == mouse.Button.middle:
        return "middle"
    if getattr(mouse.Button, "x1", None) is not None and button == mouse.Button.x1:
        return "mouse4"
    if getattr(mouse.Button, "x2", None) is not None and button == mouse.Button.x2:
        return "mouse5"
    return None


def normalize_hotkeys(hotkeys: dict[str, Any]) -> dict[str, list[set[str]]]:
    normalized: dict[str, list[set[str]]] = {}
    for action, shortcuts in hotkeys.items():
        action_shortcuts: list[set[str]] = []
        for shortcut in shortcuts or []:
            if not isinstance(shortcut, list):
                continue
            chord = {canonical(str(key)) for key in shortcut if str(key).strip()}
            if chord:
                action_shortcuts.append(chord)
        normalized[action] = action_shortcuts
    return normalized


# Tk keysyms -> the canonical names the pynput dispatcher produces. The two
# systems name keys differently -- Tk says Control_L and Prior where pynput
# says ctrl and page_up -- and a captured chord is only worth anything if it is
# spelled exactly the way the dispatcher will spell the keys at match time.
_TK_KEYSYMS = {
    "control_l": "ctrl", "control_r": "ctrl",
    "alt_l": "alt", "alt_r": "alt", "meta_l": "alt", "meta_r": "alt",
    "shift_l": "shift", "shift_r": "shift",
    "win_l": "cmd", "win_r": "cmd", "super_l": "cmd", "super_r": "cmd",
    "space": "space", "return": "enter", "tab": "tab", "escape": "esc",
    "prior": "page_up", "next": "page_down", "home": "home", "end": "end",
    "delete": "delete", "backspace": "backspace",
    # comma is deliberately absent: the saved-text format uses "," to separate
    # alternate chords, so a captured comma would be reparsed as a chord break
    # and the binding would silently lose the key. Ignoring it beats mangling it.
    "minus": "-", "equal": "=", "period": ".", "slash": "/",
    "backslash": "\\", "semicolon": ";", "apostrophe": "'", "grave": "`",
    "bracketleft": "[", "bracketright": "]",
}

# Aqua names the modifiers differently, and the difference is not cosmetic:
# Tk reports Command as Meta_L/Meta_R and Option as Alt_L/Alt_R. With the
# Windows table above, capturing Control+Command in the settings field stored
# "ctrl+alt" -- a chord that renders correctly, saves cleanly, and then only
# ever fires on Control+Option. The capture UI exists precisely to stop a
# shortcut being recorded as something it is not.
#
# Command must also stop meaning "the Windows key", or the same field would map
# two different physical keys to "cmd".
if sys.platform == "darwin":
    _TK_KEYSYMS.update({
        "meta_l": "cmd", "meta_r": "cmd",
        "command_l": "cmd", "command_r": "cmd",
        "alt_l": "alt", "alt_r": "alt",
        "option_l": "alt", "option_r": "alt",
    })
    for _win_key in ("win_l", "win_r", "super_l", "super_r"):
        _TK_KEYSYMS.pop(_win_key, None)


_FKEY_RE = re.compile(r"^f([1-9]|1\d|2[0-4])$")


def tk_keysym_to_canonical(keysym: str) -> str | None:
    """The dispatcher's name for a Tk key event, or None for keys it cannot hold.

    None means "ignore this press entirely" -- numpad keysyms, IME artifacts,
    media keys. Recording an unknown name would produce a chord that renders in
    the settings field but can never fire, which is worse than not recording
    the key: the person watched themselves set it.
    """
    lowered = keysym.lower()
    if lowered in _TK_KEYSYMS:
        return _TK_KEYSYMS[lowered]
    if len(lowered) == 1 and lowered.isprintable():
        return canonical(lowered)
    if _FKEY_RE.fullmatch(lowered):
        return lowered
    return None


def shortcut_conflicts(hotkeys: dict[str, Any]) -> list[tuple[str, tuple[str, ...]]]:
    """Actions that share a chord, and would therefore not all fire.

    Two actions on one chord is the quiet way a configurable shortcut stops
    working: the dispatcher matches the pressed set against each action in turn
    and the first one wins, so the other simply never happens. Nothing errors,
    nothing is logged, and the person concludes the feature is broken rather
    than that they assigned the same keys twice.

    Chords are compared as SETS, because ctrl+alt+1 and alt+ctrl+1 are the same
    physical thing to press and storing them in a different order does not make
    them different. Order-sensitive comparison would report no conflict for the
    exact case people hit -- rebinding one action and forgetting another already
    uses those keys.

    Returns `[(rendered chord, (action, action, ...))]` sorted for a stable
    message, so the UI can name both sides of the clash rather than say
    something vague about a conflict existing.
    """
    owners: dict[frozenset[str], list[str]] = {}
    for action, chords in normalize_hotkeys(hotkeys).items():
        for chord in chords:
            owners.setdefault(frozenset(chord), []).append(action)

    clashes = []
    for chord, actions in owners.items():
        if len(actions) > 1:
            clashes.append((render_chord(chord), tuple(sorted(actions))))
    return sorted(clashes)


def render_chord(chord: set[str] | frozenset[str]) -> str:
    """A chord as somebody would say it out loud, with modifiers first.

    Sorting alphabetically would produce "1+alt+cmd", which nobody recognises as
    the thing they pressed.
    """
    order = ("ctrl", "cmd", "alt", "shift")
    modifiers = [key for key in order if key in chord]
    rest = sorted(key for key in chord if key not in order)
    return "+".join(modifiers + rest)


class HotkeyController:
    def __init__(
        self,
        hotkeys: dict[str, Any],
        callbacks: dict[str, Callback],
        *,
        hold_debounce_ms: int = 140,
    ) -> None:
        self.hotkeys = normalize_hotkeys(hotkeys)
        self.callbacks = callbacks
        self.hold_debounce_ms = hold_debounce_ms
        self.pressed: set[str] = set()
        self.latched: set[str] = set()
        self.active_hold: str | None = None
        self.pending_hold: str | None = None
        self.pending_timer: threading.Timer | None = None
        self.lock = threading.RLock()
        self._dispatch_queue: "queue.SimpleQueue[tuple[str, Callback]] | None" = None
        self.keyboard_listener: keyboard.Listener | None = None
        self.mouse_listener: mouse.Listener | None = None
        self.watchdog_stop = threading.Event()
        self.watchdog_thread: threading.Thread | None = None
        self._shortcut_recording_until = 0.0

    def record_shortcut(self, active: bool) -> None:
        """A renewable capture lease cannot leave shortcuts disabled after a UI crash."""
        with self.lock:
            if active and self.active_hold:
                raise ValueError("Finish the current dictation before recording a shortcut.")
            was_recording = time.monotonic() < self._shortcut_recording_until
            self._shortcut_recording_until = time.monotonic() + 15 if active else 0.0
            self._cancel_pending()
            if not active or not was_recording:
                self.pressed.clear()
                self.latched.clear()

    def start(self) -> None:
        mac_support.prepare_input_bridge()
        self.keyboard_listener = keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self.mouse_listener = mouse.Listener(on_click=self._on_mouse_click)
        self.keyboard_listener.start()
        self.mouse_listener.start()
        self.watchdog_stop.clear()
        self.watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self.watchdog_thread.start()
        if sys.platform == "darwin":
            # The Globe/Fn key never reaches pynput: macOS reports it as a
            # modifier-flags change, not a key event, so the listener above is
            # blind to the one key Mac dictation lives on (Wispr Flow's
            # push-to-talk, Apple's own dictation). It is polled instead --
            # CGEventSourceKeyState sees it without any grant beyond the ones
            # the app already needs.
            self.fn_thread = threading.Thread(target=self._fn_loop, daemon=True)
            self.fn_thread.start()
        self._start_gamepad_poller()
        self._start_midi_listener()

    # --- MIDI devices as trigger sources (X-120, his order) -----------------
    #
    # winmm via ctypes: zero dependencies, present on every Windows. Unlike
    # the gamepad this is CALLBACK-driven -- no polling, no idle cost -- so
    # every present MIDI input is opened at start and its notes join the
    # pressed-set as midi_note_<n> (note-on = press, note-off = release).
    # A pad or key on a MIDI controller then works in chords, trigger styles
    # and conflict rules exactly like a keyboard key, and the capture window
    # sees it with nothing special. The ctypes callback objects are kept on
    # self for the process lifetime: a garbage-collected callback is a
    # use-after-free inside winmm.
    def _start_midi_listener(self) -> None:
        if sys.platform != "win32" or getattr(self, "_midi_handles", None) is not None:
            return
        try:
            import ctypes as _ctypes

            winmm = _ctypes.WinDLL("winmm")
            device_count = int(winmm.midiInGetNumDevs())
            if device_count <= 0:
                self._midi_handles = []
                return
            CALLBACK_FUNCTION = 0x00030000
            MIM_DATA = 0x3C3
            MidiInProc = _ctypes.WINFUNCTYPE(
                None,
                _ctypes.c_void_p,
                _ctypes.c_uint,
                _ctypes.c_void_p,
                _ctypes.c_void_p,
                _ctypes.c_void_p,
            )

            def on_midi(_handle, message, _instance, param1, _param2):
                if message != MIM_DATA:
                    return
                data = int(param1 or 0)
                status = data & 0xF0
                note = (data >> 8) & 0x7F
                velocity = (data >> 16) & 0x7F
                key = f"midi_note_{note}"
                if status == 0x90 and velocity > 0:
                    self._on_key_press_name(key)
                elif status == 0x80 or (status == 0x90 and velocity == 0):
                    self._on_key_release_name(key)

            callback = MidiInProc(on_midi)
            self._midi_callback_keepalive = callback
            handles: list[object] = []
            for device in range(device_count):
                handle = _ctypes.c_void_p()
                if winmm.midiInOpen(_ctypes.byref(handle), device, callback, None, CALLBACK_FUNCTION) == 0:
                    winmm.midiInStart(handle)
                    handles.append(handle)
            self._midi_handles = handles
            if handles:
                log.info("MIDI trigger sources: %d input device(s) listening", len(handles))
        except Exception:
            log.debug("MIDI listener unavailable", exc_info=True)
            self._midi_handles = []

    def _on_key_press_name(self, key: str) -> None:
        with self.lock:
            already = key in self.pressed
            self.pressed.add(key)
        if not already:
            self._evaluate_press()

    def _on_key_release_name(self, key: str) -> None:
        with self.lock:
            self.pressed.discard(key)
        self._evaluate_release()

    # --- Game controllers as trigger sources (X-120, his order) --------------
    #
    # XInput via ctypes: zero dependencies, present on every Windows since 7.
    # Buttons register in chords as pad_a, pad_b, pad_x, pad_y, pad_lb,
    # pad_rb, pad_back, pad_start, pad_ls, pad_rs, pad_up/down/left/right --
    # the same pressed-set the keyboard feeds, so chords, trigger styles and
    # conflict rules apply unchanged. The poller only spins while a chord
    # actually names a pad_* key; everyone else pays nothing.
    _XINPUT_BUTTONS = (
        (0x1000, "pad_a"), (0x2000, "pad_b"), (0x4000, "pad_x"), (0x8000, "pad_y"),
        (0x0100, "pad_lb"), (0x0200, "pad_rb"), (0x0020, "pad_back"), (0x0010, "pad_start"),
        (0x0040, "pad_ls"), (0x0080, "pad_rs"),
        (0x0001, "pad_up"), (0x0002, "pad_down"), (0x0004, "pad_left"), (0x0008, "pad_right"),
    )

    def _pad_keys_in_use(self) -> bool:
        with self.lock:
            return any(
                key.startswith("pad_")
                for chords in self.hotkeys.values()
                for chord in chords
                for key in chord
            )

    def _start_gamepad_poller(self) -> None:
        if getattr(self, "_gamepad_thread", None) is not None:
            return
        try:
            import ctypes as _ctypes

            xinput = None
            for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
                try:
                    xinput = _ctypes.WinDLL(name)
                    break
                except OSError:
                    continue
            if xinput is None:
                return
        except Exception:
            return

        class _XINPUT_GAMEPAD(_ctypes.Structure):
            _fields_ = [
                ("wButtons", _ctypes.c_ushort), ("bLeftTrigger", _ctypes.c_ubyte),
                ("bRightTrigger", _ctypes.c_ubyte), ("sThumbLX", _ctypes.c_short),
                ("sThumbLY", _ctypes.c_short), ("sThumbRX", _ctypes.c_short),
                ("sThumbRY", _ctypes.c_short),
            ]

        class _XINPUT_STATE(_ctypes.Structure):
            _fields_ = [("dwPacketNumber", _ctypes.c_uint), ("Gamepad", _XINPUT_GAMEPAD)]

        def poll() -> None:
            state = _XINPUT_STATE()
            down: set[str] = set()
            while not self.watchdog_stop.is_set():
                # A connected pad is polled at 60Hz only while a chord uses
                # it; otherwise one lazy probe per second.
                if not self._pad_keys_in_use():
                    self.watchdog_stop.wait(1.0)
                    continue
                buttons = 0
                for index in range(4):
                    if xinput.XInputGetState(index, _ctypes.byref(state)) == 0:
                        buttons |= state.Gamepad.wButtons
                now_down = {name for mask, name in self._XINPUT_BUTTONS if buttons & mask}
                if now_down != down:
                    with self.lock:
                        for name in now_down - down:
                            self.pressed.add(name)
                        for name in down - now_down:
                            self.pressed.discard(name)
                        if now_down - down:
                            self._evaluate_press()
                        if down - now_down:
                            self._evaluate_release()
                    down = now_down
                self.watchdog_stop.wait(1 / 60)

        self._gamepad_thread = threading.Thread(target=poll, name="TalkDatGamepad", daemon=True)
        self._gamepad_thread.start()

    def update_config(self, hotkeys: dict[str, Any], *, hold_debounce_ms: int | None = None) -> None:
        stop_action: str | None = None
        with self.lock:
            if self.active_hold:
                stop_action = f"{self.active_hold}_stop"
            self.hotkeys = normalize_hotkeys(hotkeys)
            if hold_debounce_ms is not None:
                self.hold_debounce_ms = hold_debounce_ms
            self.latched.clear()
            self.active_hold = None
            self._cancel_pending()
        if stop_action:
            self._trigger(stop_action)

    def stop(self) -> None:
        self.watchdog_stop.set()
        self._cancel_pending()
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        if self.mouse_listener:
            self.mouse_listener.stop()
        if self.watchdog_thread and self.watchdog_thread.is_alive():
            self.watchdog_thread.join(timeout=0.2)
        with self.lock:
            self.pressed.clear()
            self.latched.clear()
            self.active_hold = None
            self.pending_hold = None

    def _matches(self, action: str) -> bool:
        return any(chord.issubset(self.pressed) for chord in self.hotkeys.get(action, []))

    def _physically_matches(self, action: str) -> bool:
        for chord in self.hotkeys.get(action, []):
            if not chord.issubset(self.pressed):
                continue
            if all(self._pressed_key_is_physically_down(name) for name in chord):
                return True
        return False

    def _pressed_key_is_physically_down(self, name: str) -> bool:
        physical = physical_key_down(name)
        if physical is None:
            return name in self.pressed
        return physical

    def _hold_key_names(self) -> set[str]:
        names: set[str] = set()
        for action in (self.active_hold, self.pending_hold):
            if not action:
                continue
            for chord in self.hotkeys.get(action, []):
                names.update(chord)
        return names

    def _matching_chord_size(self, action: str) -> int:
        matches = [len(chord) for chord in self.hotkeys.get(action, []) if chord.issubset(self.pressed)]
        return max(matches, default=0)

    def _best_tap_action(self) -> str | None:
        candidates: list[tuple[int, int, str]] = []
        for priority, action in enumerate(TAP_ACTIONS):
            if action in self.latched:
                continue
            chord_size = self._matching_chord_size(action)
            if chord_size:
                candidates.append((chord_size, -priority, action))
        if not candidates:
            return None
        return max(candidates)[2]

    def _trigger(self, action: str) -> None:
        """Queue the action for the dispatch worker, never run it here.

        X-118, from a field crash on a Ctrl+Win misclick: this used to CALL
        the handler on pynput's listener thread -- the same thread Windows'
        low-level keyboard hook waits on. A slow handler (session start does
        network warm-up and a licence check) stalls the hook, and past its
        timeout Windows silently REMOVES the hook: every hotkey goes dead at
        once, which a person reports as a crash. The queue keeps press and
        release strictly ordered while the hook thread returns immediately.
        """
        blocked = self.callbacks.get("_actions_blocked")
        if callable(blocked) and blocked():
            return
        callback = self.callbacks.get(action)
        if not callback:
            return
        if self._dispatch_queue is None:
            self._dispatch_queue = queue.SimpleQueue()
            worker = threading.Thread(target=self._drain_dispatch, name="TalkDatHotkeyDispatch", daemon=True)
            worker.start()
        self._dispatch_queue.put((action, callback))

    def _drain_dispatch(self) -> None:
        while True:
            action, callback = self._dispatch_queue.get()
            try:
                blocked = self.callbacks.get("_actions_blocked")
                if callable(blocked) and blocked():
                    continue
                callback()
            except Exception:
                log.exception("hotkey action %s failed", action)

    def _on_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        # An exception escaping into pynput kills its listener thread and
        # every hotkey with it -- silently. Nothing may escape.
        try:
            name = key_name(key)
            if not name:
                return
            with self.lock:
                self.pressed.add(name)
                self._evaluate_press()
        except Exception:
            log.exception("key press handling failed")

    def _on_key_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        try:
            self._on_key_release_inner(key)
        except Exception:
            log.exception("key release handling failed")

    def _on_key_release_inner(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        name = key_name(key)
        if not name:
            return
        with self.lock:
            self.pressed.discard(name)
            self._evaluate_release()

    def _on_mouse_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        name = mouse_name(button)
        if not name:
            return
        with self.lock:
            if pressed:
                self.pressed.add(name)
                self._evaluate_press()
            else:
                self.pressed.discard(name)
                self._evaluate_release()

    def _evaluate_press(self) -> None:
        if time.monotonic() < self._shortcut_recording_until:
            if self._matches('panic') and 'panic' not in self.latched:
                self.latched.add('panic')
                self._trigger('panic')
            return
        tap_action = self._best_tap_action()
        if tap_action:
            self._cancel_pending()
            stop_action: str | None = None
            if self.active_hold:
                stop_action = f"{self.active_hold}_stop"
                self.active_hold = None
            self.latched.add(tap_action)
            if stop_action:
                self._trigger(stop_action)
            self._trigger(tap_action)
            return

        if self.active_hold:
            return

        for action in HOLD_ACTIONS:
            if self._matches(action):
                self._schedule_hold(action)
                return

    def _evaluate_release(self) -> None:
        for action in list(self.latched):
            if not self._matches(action):
                self.latched.discard(action)

        if self.pending_hold and not self._matches(self.pending_hold):
            self._cancel_pending()

        if self.active_hold and not self._matches(self.active_hold):
            action = self.active_hold
            self.active_hold = None
            self._trigger(f"{action}_stop")

    def _schedule_hold(self, action: str) -> None:
        if self.pending_hold == action:
            return
        self._cancel_pending()
        self.pending_hold = action
        self.pending_timer = threading.Timer(self.hold_debounce_ms / 1000, self._start_hold_if_still_down)
        self.pending_timer.daemon = True
        self.pending_timer.start()

    def _start_hold_if_still_down(self) -> None:
        with self.lock:
            action = self.pending_hold
            self.pending_hold = None
            self.pending_timer = None
            if time.monotonic() < self._shortcut_recording_until:
                return
            if not action or self.active_hold or not self._physically_matches(action):
                return
            for tap_action in TAP_ACTIONS:
                if tap_action != "cancel" and self._matches(tap_action):
                    return
            self.active_hold = action
            self._trigger(action)

    def _cancel_pending(self) -> None:
        if self.pending_timer:
            self.pending_timer.cancel()
        self.pending_timer = None
        self.pending_hold = None

    # How long the Globe key must be held before it is OURS. A tap stays the
    # system's (emoji picker, input-source switch, Apple dictation -- whatever
    # the person has bound); a hold is dictation. Wispr trains exactly this
    # muscle memory, which is why it is the default here.
    FN_HOLD_ARM_MS = 140
    FN_POLL_MS = 25

    def _fn_loop(self) -> None:
        from .mac_support import physical_key_down as _fn_state

        down_since: float | None = None
        injected = False
        while not self.watchdog_stop.wait(self.FN_POLL_MS / 1000.0):
            with self.lock:
                bound = any(
                    "fn" in chord
                    for chords in self.hotkeys.values()
                    for chord in chords
                )
            if not bound:
                down_since = None
                if injected:
                    injected = False
                    with self.lock:
                        self.pressed.discard("fn")
                        self._evaluate_release()
                continue
            state = _fn_state("fn")
            now = time.monotonic()
            if state:
                if down_since is None:
                    down_since = now
                if not injected and (now - down_since) * 1000.0 >= self.FN_HOLD_ARM_MS:
                    injected = True
                    with self.lock:
                        self.pressed.add("fn")
                        self._evaluate_press()
            else:
                down_since = None
                if injected:
                    injected = False
                    with self.lock:
                        self.pressed.discard("fn")
                        self._evaluate_release()

    def _watchdog_loop(self) -> None:
        while not self.watchdog_stop.wait(WATCHDOG_INTERVAL_SECONDS):
            stop_action: str | None = None
            with self.lock:
                if not self.active_hold and not self.pending_hold:
                    continue

                for name in list(self._hold_key_names() & self.pressed):
                    physical = physical_key_down(name)
                    if physical is False:
                        self.pressed.discard(name)

                for action in list(self.latched):
                    if not self._matches(action):
                        self.latched.discard(action)

                if self.pending_hold and not self._physically_matches(self.pending_hold):
                    self._cancel_pending()

                if self.active_hold and not self._physically_matches(self.active_hold):
                    action = self.active_hold
                    self.active_hold = None
                    stop_action = f"{action}_stop"

            if stop_action:
                self._trigger(stop_action)
