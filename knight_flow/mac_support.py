"""macOS primitives behind the seams Windows fills with win32 calls.

Everything here is import-safe on Windows and Linux: the pyobjc frameworks are
imported lazily inside functions, so a Windows build that never calls them does
not need them installed and does not pay for the import. Each function returns
the same "unknown" value its Windows counterpart returns on failure ("" for
paths, None for screens) so callers keep their existing failure handling.

Why pyobjc rather than shelling out: the answers here are needed on the paste
hot path, where a subprocess spawn per dictation is a visible cost.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

IS_MAC = sys.platform == "darwin"

# The paste chord differs by platform and is the one substitution that has to
# reach every synthetic key send. On Windows the app sends Ctrl+V/C/Z; macOS
# uses Command for the same three.
PASTE_MODIFIER = "command" if IS_MAC else "ctrl"

# Tk on Aqua rejects "size_nw_se" outright -- a TclError, not a fallback -- and
# because the resize grip is built before a utility window's close button, that
# error left four windows blank and unclosable. "bottom_right_corner" is the
# diagonal grip cursor on Aqua and X11; Windows keeps the name it already had.
RESIZE_CORNER_CURSOR = "bottom_right_corner" if IS_MAC else "size_nw_se"


def application_support_dir(app_name: str) -> Path:
    """Where macOS expects per-user application data to live.

    Windows uses %APPDATA%\\TalkDat. The macOS equivalent is
    ~/Library/Application Support/TalkDat -- not ~/TalkDat, which is what the
    APPDATA fallback produces and which puts a 640MB model cache in the middle
    of the user's home folder.
    """
    return Path.home() / "Library" / "Application Support" / app_name


def frontmost_app_path() -> str:
    """Full filesystem path of the frontmost application's bundle, or "".

    The Windows counterpart returns the path to the .exe. Here it is the .app
    bundle path, which serves the same purpose: the caller inspects the files
    beside it to answer questions like "is this a Chromium browser".
    """
    if not IS_MAC:
        return ""
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return ""
        url = app.bundleURL()
        if url is None:
            executable = app.executableURL()
            return str(executable.path()) if executable is not None else ""
        return str(url.path())
    except Exception:
        return ""


def frontmost_app_name() -> str:
    """Lowercased bundle name of the frontmost app, or ""."""
    if not IS_MAC:
        return ""
    path = frontmost_app_path()
    if not path:
        return ""
    return os.path.basename(path).lower()


def frontmost_app_bundle_id() -> str:
    """Reverse-DNS bundle identifier of the frontmost app, or "".

    macOS has no stable equivalent of an .exe name -- two apps can ship the same
    binary name -- so the bundle id is the reliable key for per-app profiles.
    """
    if not IS_MAC:
        return ""
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return ""
        return str(app.bundleIdentifier() or "")
    except Exception:
        return ""


def frontmost_window_id() -> int:
    """A stable-per-focus integer identifying the focused app, or 0.

    Windows uses the HWND of the foreground window. macOS does not hand out
    window handles for other applications' windows without Screen Recording
    permission, so the frontmost application's pid stands in. The callers only
    ever compare this value to a previously captured one to ask "is focus still
    where it was when the dictation started", and the pid answers that.
    """
    if not IS_MAC:
        return 0
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return 0
        return int(app.processIdentifier())
    except Exception:
        return 0


def list_screens() -> list[dict[str, Any]]:
    """Screen geometry in Tk's coordinate space, or [] if unavailable.

    NSScreen's origin is bottom-left and Tk's is top-left, so y is flipped
    against the primary screen's height before returning. Coordinates are in
    points, which is what Tk geometry strings already use on macOS -- the
    Retina backing scale is applied by the window server, not by us.
    """
    if not IS_MAC:
        return []
    try:
        from AppKit import NSScreen

        screens = NSScreen.screens()
        if not screens:
            return []
        primary_height = float(screens[0].frame().size.height)
        out: list[dict[str, Any]] = []
        for index, screen in enumerate(screens):
            frame = screen.frame()
            visible = screen.visibleFrame()
            out.append(
                {
                    "index": index,
                    "primary": index == 0,
                    "x": int(frame.origin.x),
                    "y": int(primary_height - frame.origin.y - frame.size.height),
                    "width": int(frame.size.width),
                    "height": int(frame.size.height),
                    "work_x": int(visible.origin.x),
                    "work_y": int(primary_height - visible.origin.y - visible.size.height),
                    "work_width": int(visible.size.width),
                    "work_height": int(visible.size.height),
                }
            )
        return out
    except Exception:
        return []


def prepare_input_bridge() -> None:
    """Resolve PyObjC's lazy symbol before both pynput listener threads use it.

    Loading a function is not a permission check or permission request. The
    shared PyObjC metadata dictionary is consumed during first resolution;
    resolving on the startup thread avoids concurrent metadata removal.
    """
    if IS_MAC:
        from HIServices import AXIsProcessTrusted

        if not callable(AXIsProcessTrusted):
            raise RuntimeError("Mac input support could not load.")


def has_accessibility_permission(prompt: bool = False) -> bool:
    """Whether this process may post synthetic keystrokes.

    macOS gates synthetic input behind Accessibility (System Settings >
    Privacy & Security > Accessibility). Without it, paste and typed delivery
    fail silently -- CGEventPost returns success and nothing arrives -- so this
    must be checked and surfaced rather than discovered by a user whose
    dictation vanishes.

    Note this is separate from Input Monitoring, which is what *listening* for
    the global hotkey requires. A user can grant one and not the other.
    """
    if not IS_MAC:
        return True
    if prompt:
        # The prompting variant needs a real CFDictionary; handing pyobjc a bare
        # Python dict for that argument crashes the interpreter rather than
        # raising, so the dictionary is built through CoreFoundation itself.
        try:
            from ApplicationServices import (
                AXIsProcessTrustedWithOptions,
                kAXTrustedCheckOptionPrompt,
            )
            from CoreFoundation import (
                CFDictionaryCreate,
                kCFBooleanTrue,
                kCFTypeDictionaryKeyCallBacks,
                kCFTypeDictionaryValueCallBacks,
            )

            options = CFDictionaryCreate(
                None,
                [kAXTrustedCheckOptionPrompt],
                [kCFBooleanTrue],
                1,
                kCFTypeDictionaryKeyCallBacks,
                kCFTypeDictionaryValueCallBacks,
            )
            return bool(AXIsProcessTrustedWithOptions(options))
        except Exception:
            pass
    try:
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def microphone_permission() -> str:
    """"granted", "denied", "not asked", or "unknown".

    Deliberately not a bool. The first version of this returned one, could not
    import AVFoundation because pyobjc ships it separately and it is not a
    dependency, fell into its own except clause and answered True every time --
    a check that always passes is worse than no check, because it reads as
    evidence.

    "unknown" is therefore an honest answer and callers must handle it. The
    reliable signal when the framework is absent is the audio itself: see
    `audio_input.is_digitally_silent`.
    """
    if not IS_MAC:
        return "granted"
    try:
        import AVFoundation
    except Exception:
        return "unknown"
    try:
        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio
        )
    except Exception:
        return "unknown"
    return {0: "not asked", 1: "denied", 2: "denied", 3: "granted"}.get(int(status), "unknown")


def has_microphone_permission() -> bool:
    """True unless macOS has definitely refused.

    "not asked" counts as usable: the OS shows its own prompt on first capture,
    and reporting a refusal before the user has been asked would be wrong.
    """
    return microphone_permission() != "denied"


def open_privacy_settings(pane: str) -> bool:
    """Open a specific Privacy & Security pane so the user can grant access.

    pane is one of "Accessibility", "ListenEvent" (Input Monitoring),
    "Microphone".
    """
    if not IS_MAC:
        return False
    try:
        from AppKit import NSWorkspace
        from Foundation import NSURL

        url = NSURL.URLWithString_(
            f"x-apple.systempreferences:com.apple.preference.security?Privacy_{pane}"
        )
        return bool(NSWorkspace.sharedWorkspace().openURL_(url))
    except Exception:
        return False


def reveal_in_finder(path: str) -> bool:
    """Open a file or folder the way double-clicking it would. False on failure.

    The Windows call is os.startfile, which does not exist off Windows -- and it
    raises AttributeError, not OSError, so three buttons that caught OSError
    (Play, Open folder, Open full history) did nothing at all: no action, no
    error state, not even the clipboard fallback one of them has. `open` is the
    macOS equivalent and is always present.
    """
    if not IS_MAC:
        return False
    import subprocess

    try:
        return subprocess.run(["/usr/bin/open", str(path)], capture_output=True).returncode == 0
    except Exception:
        return False


def play_sound_file(path: str) -> bool:
    """Play a WAV, replacing winsound. False if it could not be started.

    Start and stop chimes are on by default and their Settings previews are
    wired to real buttons, but the only implementation was `import winsound`
    inside a `try: ... except Exception: return`. On macOS the whole feature was
    inaudible while looking completely functional -- the WAVs were even being
    rendered and written to disk first.

    afplay is part of macOS and is not waited on, because a chime must not hold
    up the dictation that triggered it.
    """
    if not IS_MAC:
        return False
    import subprocess

    try:
        subprocess.Popen(
            ["/usr/bin/afplay", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


# Fonts. Tk resolves an unknown family to the system font silently, and two of
# the three Windows families used here degrade in ways that are easy to miss and
# affect every screen:
#
#   "Segoe UI Semibold" -> .AppleSystemUIFont at weight=normal. The weight lives
#       in the family name, so it is simply dropped: 80 headings, buttons and
#       emphasised labels lost all contrast against body text.
#   "Consolas" -> .AppleSystemUIFont, which is *proportional*. The licence key
#       display, the redeem field and every text box were no longer aligned.
#
# "SF Pro Text Semibold" is the one that matters: it is a real family name that
# resolves to SF Pro Text at weight=bold, so the fix stays a string swap instead
# of rewriting every font tuple to carry an explicit weight.
FONT_UI = "SF Pro Text" if IS_MAC else "Segoe UI"
FONT_UI_SEMIBOLD = "SF Pro Text Semibold" if IS_MAC else "Segoe UI Semibold"
FONT_MONO = "Menlo" if IS_MAC else "Consolas"


# Where Homebrew and the Ollama.app installer put the binary. A GUI application
# launched from Finder inherits launchd's PATH -- /usr/bin:/bin:/usr/sbin:/sbin
# -- which contains none of these, so shutil.which("ollama") returns nothing
# even when Ollama is installed and running. The symptom is Settings reporting
# "Ollama is not installed" while it answers on localhost:11434.
OLLAMA_CANDIDATE_PATHS = (
    "/opt/homebrew/bin/ollama",      # Homebrew, Apple silicon
    "/usr/local/bin/ollama",         # Homebrew, Intel
    "/Applications/Ollama.app/Contents/Resources/ollama",
    "/Applications/Ollama.app/Contents/MacOS/ollama",
)

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download/mac"


def find_ollama() -> str:
    """Full path to the ollama binary, or "" -- searching where a Mac keeps it."""
    if not IS_MAC:
        return ""
    for candidate in OLLAMA_CANDIDATE_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return ""


def install_ollama_hint() -> str:
    """What to tell someone on macOS who does not have Ollama.

    Homebrew is not assumed to be present and the app must not install things
    behind someone's back, so this points at the download rather than running a
    package manager -- the Windows path shells out to winget, which does not
    exist here, and told Mac users their Windows Package Manager was missing.
    """
    return f"Download Ollama for macOS from {OLLAMA_DOWNLOAD_URL}, then reopen Settings."


# Names for things the two platforms call differently, in copy the user reads.
# Kept here so a Mac build cannot describe Windows machinery: the credential
# vault, the system default microphone, and the place the app's menu lives.
CREDENTIAL_VAULT_NAME = "your macOS Keychain" if IS_MAC else "Windows Credential Manager"
SYSTEM_DEFAULT_MIC_LABEL = "System default microphone" if IS_MAC else "Windows default microphone"
MENU_SURFACE_NAME = "the menu bar icon" if IS_MAC else "the tray"
APP_DATA_LABEL = "Application Support" if IS_MAC else "AppData"


def system_output_volume() -> float | None:
    """Current output volume as 0.0-1.0, or None if it cannot be read.

    osascript is used rather than CoreAudio because reading and setting the
    default device's volume through AudioObjectSetPropertyData means handling
    per-device channel layouts, and this runs twice per dictation. AppleScript's
    volume settings are the same thing the volume keys drive.
    """
    if not IS_MAC:
        return None
    import subprocess

    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", "output volume of (get volume settings)"],
            capture_output=True, timeout=2,
        )
        raw = result.stdout.decode("utf-8", "replace").strip()
        if not raw.isdigit():
            return None
        return max(0.0, min(1.0, int(raw) / 100.0))
    except Exception:
        return None


def set_system_output_volume(level: float) -> bool:
    """Set output volume from a 0.0-1.0 value. False if it could not be set."""
    if not IS_MAC:
        return False
    import subprocess

    percent = int(round(max(0.0, min(1.0, level)) * 100))
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", f"set volume output volume {percent}"],
            capture_output=True, timeout=2,
        )
        return result.returncode == 0
    except Exception:
        return False


def dock_magnification_headroom() -> int:
    """Extra points a magnifying Dock can occupy above its resting band.

    NSScreen.visibleFrame already excludes the Dock, but only at the size it is
    right now. With magnification on, icons grow *upward* past that band as the
    pointer crosses them, and a Pill sitting flush against the work area edge
    disappears behind them.

    largesize is the magnified icon size and tilesize the resting one, so their
    difference is how much further the Dock reaches at its largest. Someone with
    magnification off gets nothing extra, and a Dock configured to shrink on
    magnification (largesize below tilesize) also gets nothing rather than a
    negative margin.
    """
    if not IS_MAC:
        return 0
    import subprocess

    def read(key: str) -> float | None:
        try:
            result = subprocess.run(
                ["/usr/bin/defaults", "read", "com.apple.dock", key],
                capture_output=True, timeout=2,
            )
            if result.returncode != 0:
                return None
            return float(result.stdout.decode("utf-8", "replace").strip())
        except Exception:
            return None

    if not read("magnification"):
        return 0
    large = read("largesize")
    tile = read("tilesize")
    if large is None or tile is None:
        # Magnification is on but the sizes are unreadable. macOS caps largesize
        # at 128, so this is the worst case rather than a guess.
        return 48
    return max(0, int(round(large - tile)))


def dock_is_on_the_bottom() -> bool:
    """Whether the Dock occupies the bottom edge, where the Pill lives."""
    if not IS_MAC:
        return False
    import subprocess

    try:
        result = subprocess.run(
            ["/usr/bin/defaults", "read", "com.apple.dock", "orientation"],
            capture_output=True, timeout=2,
        )
        if result.returncode != 0:
            return True  # the key is absent until it is changed; bottom is the default
        return result.stdout.decode("utf-8", "replace").strip() == "bottom"
    except Exception:
        return True


# Virtual keycodes for the keys a hold chord can contain. From
# HIToolbox/Events.h (kVK_*). Only the keys that can be held are listed --
# anything absent falls back to trusting the event stream, which is what the
# Windows table does for the same reason.
_MAC_KEYCODES: dict[str, tuple[int, ...]] = {
    "cmd": (55, 54),        # kVK_Command, kVK_RightCommand
    "ctrl": (59, 62),       # kVK_Control, kVK_RightControl
    "alt": (58, 61),        # kVK_Option, kVK_RightOption
    "shift": (56, 60),      # kVK_Shift, kVK_RightShift
    "space": (49,),
    # The Globe/Fn key. kVK_Function -- the key Wispr Flow binds to
    # push-to-talk on the Mac (its config maps virtual keycode 63 to "ptt"),
    # and the reason a Mac dictation app can be driven one-handed.
    "fn": (63,),
    "enter": (36, 76),
    "tab": (48,),
    "esc": (53,),
    "delete": (117,),
    "backspace": (51,),
    "home": (115,), "end": (119,), "page_up": (116,), "page_down": (121,),
    "a": (0,), "s": (1,), "d": (2,), "f": (3,), "h": (4,), "g": (5,), "z": (6,),
    "x": (7,), "c": (8,), "v": (9,), "b": (11,), "q": (12,), "w": (13,),
    "e": (14,), "r": (15,), "y": (16,), "t": (17,), "1": (18,), "2": (19,),
    "3": (20,), "4": (21,), "6": (22,), "5": (23,), "9": (25,), "7": (26,),
    "8": (28,), "0": (29,), "o": (31,), "u": (32,), "i": (34,), "p": (35,),
    "l": (37,), "j": (38,), "k": (40,), "n": (45,), "m": (46,),
}


def physical_key_down(name: str) -> bool | None:
    """Whether a key is physically held, asked of the window server.

    The counterpart of GetAsyncKeyState, and the watchdog that recovers a hold
    whose key-release never arrived depends on it. Without this the watchdog
    falls back to trusting the same event stream it exists to distrust, which
    on macOS is the wrong stream to trust: Cocoa is known to withhold key-up
    events for other keys while Command is held, and Command is in the default
    push-to-talk chord.

    None means "no opinion" -- an unmapped key -- and the caller then trusts its
    own record, matching the Windows behaviour.
    """
    if not IS_MAC:
        return None
    codes = _MAC_KEYCODES.get(name)
    if codes is None:
        return None
    try:
        import Quartz

        # 0 = kCGEventSourceStateCombinedSessionState: the same view of the
        # keyboard the window server hands to applications. Needs no
        # Accessibility grant, unlike posting events.
        return any(bool(Quartz.CGEventSourceKeyState(0, code)) for code in codes)
    except Exception:
        return None


# What this build calls itself to the server. A Mac reporting TalkDat-Windows
# makes the platform column in the commerce data wrong in the one direction
# that matters: it hides that Mac users exist at all.
USER_AGENT = "TalkDat-Mac" if IS_MAC else "TalkDat-Windows"

# Fallback when the machine has no hostname. "Windows PC" on a Mac is shown back
# to the person in the device list on the website, next to the machines they
# recognise.
UNNAMED_DEVICE_LABEL = "Mac" if IS_MAC else "Windows PC"


# The gesture that opens the Pill's menu. Many Mac trackpads have secondary
# click off or set to a corner, and Control-click always works, so the phrasing
# says both rather than assuming a physical right button.
SECONDARY_CLICK_PHRASE = "Control-click or right-click" if IS_MAC else "Right-click"
SECONDARY_CLICK_PHRASE_LOWER = "control-click or right-click" if IS_MAC else "right-click"


def frontmost_window_is_fullscreen() -> bool:
    """Whether the frontmost application is showing a fullscreen window.

    The Windows guard hides the Pill over fullscreen apps so push-to-talk never
    draws a bar across a game or a film. Its implementation is entirely win32
    and returns False off Windows, so on macOS the guard did nothing and the
    setting that controls it -- on by default -- was inert.

    A macOS fullscreen window covers the whole display *including* the menu bar
    and Dock, which is what separates it from a merely maximised one, so the
    test is against the screen frame rather than the visible frame. Window
    bounds and owning pid are readable from CGWindowList without Screen
    Recording permission; only window titles require it, and none are read.

    False on any uncertainty. A wrongly-hidden Pill looks like the app has
    crashed, which is worse than a Pill visible over a video.
    """
    if not IS_MAC:
        return False
    try:
        import Quartz
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return False
        # Our own Pill is always on top; it must never count as the fullscreen
        # window and hide itself.
        import os

        pid = int(app.processIdentifier())
        if pid == os.getpid():
            return False

        screens = list_screens()
        if not screens:
            return False

        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for window in windows or ():
            if int(window.get("kCGWindowOwnerPID", -1)) != pid:
                continue
            # Layer 0 is normal application content. Panels and overlays sit
            # above it and are never the thing being watched fullscreen.
            if int(window.get("kCGWindowLayer", 0)) != 0:
                continue
            bounds = window.get("kCGWindowBounds") or {}
            width = int(bounds.get("Width", 0))
            height = int(bounds.get("Height", 0))
            left = int(bounds.get("X", 0))
            top = int(bounds.get("Y", 0))
            for screen in screens:
                # A tolerance of a couple of points: some apps inset their
                # fullscreen window very slightly, and an exact match would
                # miss them.
                if (
                    abs(width - screen["width"]) <= 2
                    and abs(height - screen["height"]) <= 2
                    and abs(left - screen["x"]) <= 2
                    and abs(top - screen["y"]) <= 2
                ):
                    return True
        return False
    except Exception:
        return False


# Virtual audio devices that expose system output as an input. macOS has no
# WASAPI-loopback equivalent: capturing what the speakers are playing needs
# either one of these installed, or ScreenCaptureKit -- and ScreenCaptureKit
# would demand Screen Recording permission, a third system prompt, for a
# feature most people never use. Detecting an installed device costs nothing
# and asks for nothing.
LOOPBACK_DEVICE_MARKERS = (
    "blackhole",
    "loopback audio",
    "soundflower",
    "existential audio",
    "aggregate",       # a user-built aggregate device including system output
    "multi-output",
)


def find_loopback_input_device() -> int | None:
    """Index of an installed system-audio capture device, or None.

    Returns the index rather than the name because sounddevice indexes shift
    when devices are plugged in, and the caller opens the stream immediately.
    """
    if not IS_MAC:
        return None
    try:
        import sounddevice as sd

        for index, device in enumerate(sd.query_devices()):
            if int(device.get("max_input_channels", 0)) <= 0:
                continue
            name = str(device.get("name", "")).lower()
            if any(marker in name for marker in LOOPBACK_DEVICE_MARKERS):
                return index
    except Exception:
        return None
    return None


def loopback_help() -> str:
    """What to tell someone whose meeting recording caught only their voice."""
    return (
        "macOS cannot capture system audio on its own. Install a free virtual "
        "audio device such as BlackHole and select it, and meeting mode will "
        "record both sides."
    )


# The privacy copy leans on one phrase -- "stays on this PC", "transcribed on
# this PC" -- and it is the strongest claim the product makes. Reading it on a
# Mac makes the sentence sound like it was written about somebody else's
# machine, which is the wrong feeling for a privacy promise.
# Re-exported, not defined. The definition moved to knight_flow/platform_copy.py
# on main, because living only here is what made it drift: main wrote "this PC"
# freely, this branch converted those strings after every merge, and the next
# merge brought them back. Keeping the names bound here means every existing
# `mac_support.THIS_COMPUTER` call site on the Mac port is untouched.
from .platform_copy import THIS_COMPUTER, THIS_COMPUTER_SENTENCE  # noqa: F401


# Per-pixel window transparency.
#
# Windows gets it by nominating a key colour with the -transparentcolor wm
# attribute. That attribute does not exist on Aqua -- it raises TclError, which
# the call site swallowed -- so the Pill's window kept the key colour as an
# ordinary opaque background and the "floating pill" rendered as a near-black
# rectangle with square corners, taking the context menu, tooltips and the
# hover panel with it.
#
# Aqua's equivalent is the -transparent attribute plus the systemTransparent
# background colour. With those the window shows only what is drawn into it
# with alpha, which is what the pill artwork already provides -- both sprite
# sheets carry an alpha channel and flow_pill_240.json declares
# transparent_background.
#
# It also removes the need for the hand-carved corner region: the rounded shape
# comes from the artwork's own alpha, and NSWindow supplies the shadow.
TRANSPARENT_WINDOW_BG = "systemTransparent" if IS_MAC else None


def make_window_transparent(window: Any, key_colour: str) -> bool:
    """Give a Tk window a transparent background. False if unsupported.

    `key_colour` is the Windows key colour, ignored on macOS.
    """
    try:
        if IS_MAC:
            window.configure(bg=TRANSPARENT_WINDOW_BG)
            window.attributes("-transparent", True)
            return True
        window.configure(bg=key_colour)
        window.attributes("-transparentcolor", key_colour)
        return True
    except Exception:
        return False


_frontmost_observer: Any = None
_frontmost_observer_class: Any = None


def _frontmost_observer_type() -> Any:
    """The Objective-C class that receives activation notifications.

    Defined once for the same reason as the menu bar's target: Objective-C
    registers classes globally by name, so defining this inside the function
    that installs the watch raises "overriding existing Objective-C class" on
    the second call -- which is every app restart, not just a second test.
    """
    global _frontmost_observer_class
    if _frontmost_observer_class is not None:
        return _frontmost_observer_class

    import AppKit
    import objc

    class _FrontmostObserver(AppKit.NSObject):
        @objc.python_method
        def bind(self, callback) -> None:
            self._callback = callback

        def appActivated_(self, _notification) -> None:  # noqa: N802 - ObjC selector
            callback = getattr(self, "_callback", None)
            if callback is None:
                return
            try:
                callback()
            except Exception:
                pass

    _frontmost_observer_class = _FrontmostObserver
    return _frontmost_observer_class


def watch_frontmost_app(callback: Any) -> bool:
    """Call `callback` whenever another application comes to the front.

    X-02's macOS counterpart to SetWinEventHook(EVENT_SYSTEM_FOREGROUND).
    Without it the Pill only re-evaluates its position when something else
    prompts a redraw, so it lags behind the window someone just clicked into --
    exactly the complaint the item was raised for.

    NSWorkspace delivers this on the main run loop, which on Aqua is the same
    loop Tk pumps, so the callback arrives on the Tk thread. The observer is
    held in a module global: NSNotificationCenter does not retain observers, and
    letting this be collected is the same class of bug as dropping a
    SetWinEventHook callback reference.
    """
    global _frontmost_observer
    if not IS_MAC:
        return False
    try:
        import AppKit

        if _frontmost_observer is not None:
            _frontmost_observer.bind(callback)
            return True
        observer = _frontmost_observer_type().alloc().init()
        observer.bind(callback)
        AppKit.NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
            observer,
            "appActivated:",
            AppKit.NSWorkspaceDidActivateApplicationNotification,
            None,
        )
        _frontmost_observer = observer
        return True
    except Exception:
        return False


def screen_for_frontmost_app() -> dict[str, Any] | None:
    """The screen showing the frontmost application's window, or None.

    Used so the Pill appears on the display someone is actually working on.
    Falls back to None -- meaning "use the primary" -- rather than guessing.
    """
    if not IS_MAC:
        return None
    try:
        import Quartz
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        pid = int(app.processIdentifier())
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for window in windows or ():
            if int(window.get("kCGWindowOwnerPID", -1)) != pid:
                continue
            if int(window.get("kCGWindowLayer", 0)) != 0:
                continue
            bounds = window.get("kCGWindowBounds") or {}
            return screen_containing(
                int(bounds.get("X", 0)) + int(bounds.get("Width", 0)) // 2,
                int(bounds.get("Y", 0)) + int(bounds.get("Height", 0)) // 2,
            )
        return None
    except Exception:
        return None


def screen_containing(x: int, y: int) -> dict[str, Any] | None:
    """The screen whose frame contains a point, or the primary if none does."""
    if not IS_MAC:
        return None
    screens = list_screens()
    if not screens:
        return None
    for screen in screens:
        if (screen["x"] <= x < screen["x"] + screen["width"]
                and screen["y"] <= y < screen["y"] + screen["height"]):
            return screen
    return next((s for s in screens if s["primary"]), screens[0])


def frontmost_window_title() -> str:
    """Title of the focused window of the frontmost app, or "".

    X-34 needs one string: what the window in front is called, so a reply to
    "Adaeze Okafor - RE: Contract" spells the name right. Windows asks
    GetWindowTextW.

    The obvious macOS route -- kCGWindowName from CGWindowList -- is the wrong
    one: window *titles* require Screen Recording permission, which would mean a
    third system prompt for a feature that reads a single string. The
    Accessibility API returns the same title and the app already holds that
    permission, because posting the paste keystroke needs it. No new prompt, and
    the title never leaves the machine.
    """
    if not IS_MAC:
        return ""
    try:
        from AppKit import NSWorkspace
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            kAXFocusedWindowAttribute,
            kAXTitleAttribute,
        )

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return ""
        import os

        if int(app.processIdentifier()) == os.getpid():
            # Our own Pill is never the context for a dictation.
            return ""
        element = AXUIElementCreateApplication(app.processIdentifier())
        error, window = AXUIElementCopyAttributeValue(element, kAXFocusedWindowAttribute, None)
        if error != 0 or window is None:
            return ""
        error, title = AXUIElementCopyAttributeValue(window, kAXTitleAttribute, None)
        if error != 0 or not title:
            return ""
        text = str(title)
        # Same bound the Windows path applies: a title this long is not a name,
        # it is a document dump.
        return text if len(text) <= 512 else ""
    except Exception:
        return ""


_url_handler: Any = None
_url_handler_class: Any = None


def _url_handler_type() -> Any:
    """The Objective-C class that receives talkdat:// opens. Defined once."""
    global _url_handler_class
    if _url_handler_class is not None:
        return _url_handler_class

    import AppKit
    import objc

    class _URLHandler(AppKit.NSObject):
        @objc.python_method
        def bind(self, callback) -> None:
            self._callback = callback

        def handleEvent_withReplyEvent_(self, event, _reply):  # noqa: N802 - ObjC selector
            callback = getattr(self, "_callback", None)
            if callback is None:
                return
            try:
                # keyDirectObject == 'derr'... the URL arrives as the direct
                # object of the GetURL event.
                descriptor = event.paramDescriptorForKeyword_(0x2D2D2D2D)  # '----'
                url = descriptor.stringValue() if descriptor is not None else None
                if url:
                    callback(str(url))
            except Exception:
                pass

    _url_handler_class = _URLHandler
    return _url_handler_class


def watch_url_scheme(callback: Any) -> bool:
    """Call `callback(uri)` when macOS hands this app a talkdat:// URL.

    X-11's macOS counterpart. Windows registers a per-user HKCU command and
    the browser launches a second process with the URI in argv. macOS does not
    work that way: the scheme is declared in the bundle's Info.plist, and when
    the app is ALREADY RUNNING the system delivers an Apple Event to it rather
    than starting anything -- so the argv branch, which is the whole Windows
    mechanism, never fires in the common case.

    PyInstaller's argv_emulation covers the cold-start half by turning the
    event into argv. This covers the half that matters more: the app is
    usually already open when someone signs in on the web.

    The handler is held in a module global because NSAppleEventManager does not
    retain it -- the same reason the menu bar target and the activation
    observer are held.
    """
    global _url_handler
    if not IS_MAC:
        return False
    try:
        from Foundation import NSAppleEventManager

        if _url_handler is not None:
            _url_handler.bind(callback)
            return True
        handler = _url_handler_type().alloc().init()
        handler.bind(callback)
        # kInternetEventClass / kAEGetURL
        NSAppleEventManager.sharedAppleEventManager().setEventHandler_andSelector_forEventClass_andEventID_(
            handler,
            "handleEvent:withReplyEvent:",
            0x4755524C,  # 'GURL'
            0x4755524C,  # 'GURL'
        )
        _url_handler = handler
        return True
    except Exception:
        return False


# --- X-23: the permissions macOS will ask about, and how to check each one ---
#
# Every entry here is a real TCC gate that silently disables a headline feature
# when it is missing. They are ordered the way onboarding walks them, which is
# the order the app itself will trip them: microphone before the level meter,
# Input Monitoring before the hotkey rehearsal, Accessibility before the first
# dictation is delivered.
PERMISSION_MICROPHONE = "microphone"
PERMISSION_ACCESSIBILITY = "accessibility"
PERMISSION_INPUT_MONITORING = "input_monitoring"

PERMISSION_ORDER = (
    PERMISSION_MICROPHONE,
    PERMISSION_ACCESSIBILITY,
    PERMISSION_INPUT_MONITORING,
)

# System Settings panes, for sending someone straight to the right list rather
# than describing a path through four levels of a window they have never opened.
_PRIVACY_PANES = {
    PERMISSION_MICROPHONE: "Privacy_Microphone",
    PERMISSION_ACCESSIBILITY: "Privacy_Accessibility",
    PERMISSION_INPUT_MONITORING: "Privacy_ListenEvent",
}

# IOHIDCheckAccess / IOHIDRequestAccess request types.
_HID_REQUEST_POST_EVENT = 0
_HID_REQUEST_LISTEN_EVENT = 1
# IOHIDAccessType
_HID_ACCESS = {0: "granted", 1: "denied", 2: "not asked"}


def _iokit():
    """IOKit through ctypes, because pyobjc's Quartz build does not export it.

    IOHIDCheckAccess is the only honest way to read Input Monitoring: there is
    no AX-style trusted check for it, and the failure mode without it is a
    global hotkey that never fires while everything reports success.
    """
    import ctypes
    import ctypes.util

    path = ctypes.util.find_library("IOKit")
    if not path:
        return None, None
    return ctypes, ctypes.CDLL(path)


def input_monitoring_permission() -> str:
    """"granted", "denied", "not asked", or "unknown".

    Same contract as microphone_permission, and unknown for the same reason:
    a check that cannot run must say so rather than answer True.
    """
    if not IS_MAC:
        return "granted"
    try:
        ctypes, iokit = _iokit()
        if iokit is None:
            return "unknown"
        check = getattr(iokit, "IOHIDCheckAccess", None)
        if check is None:
            # Pre-10.15 has no Input Monitoring gate at all, so nothing to grant.
            return "granted"
        check.argtypes = [ctypes.c_uint32]
        check.restype = ctypes.c_uint32
        return _HID_ACCESS.get(int(check(_HID_REQUEST_LISTEN_EVENT)), "unknown")
    except Exception:
        return "unknown"


def request_input_monitoring_permission() -> bool:
    """Fire the real Input Monitoring prompt. True if macOS says granted.

    Returns quickly and does not block on the user: macOS shows the dialog and
    answers with the state it had, so the checklist is what confirms the grant.
    """
    if not IS_MAC:
        return True
    try:
        ctypes, iokit = _iokit()
        if iokit is None:
            return False
        request = getattr(iokit, "IOHIDRequestAccess", None)
        if request is None:
            return True
        request.argtypes = [ctypes.c_uint32]
        request.restype = ctypes.c_bool
        return bool(request(_HID_REQUEST_LISTEN_EVENT))
    except Exception:
        return False


def request_microphone_permission(callback=None) -> str:
    """Fire the real microphone prompt.

    Returns the status as it stands at call time; `callback` receives a bool
    when the person answers. Asking when the state is already decided does
    nothing visible, which is what makes it safe to call from a page that may
    be revisited -- macOS shows its prompt exactly once per app signature and
    answers from its own record afterwards.
    """
    status = microphone_permission()
    if not IS_MAC:
        return status
    try:
        import AVFoundation

        AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            AVFoundation.AVMediaTypeAudio,
            (lambda granted: callback(bool(granted))) if callback else (lambda granted: None),
        )
    except Exception:
        return status
    return status


def request_accessibility_permission() -> bool:
    """Fire the real Accessibility prompt, via the checking call that prompts."""
    if not IS_MAC:
        return True
    return has_accessibility_permission(prompt=True)


def permission_state(name: str) -> str:
    """"granted", "denied", "not asked" or "unknown" for any PERMISSION_ORDER key."""
    if name == PERMISSION_MICROPHONE:
        return microphone_permission()
    if name == PERMISSION_INPUT_MONITORING:
        return input_monitoring_permission()
    if name == PERMISSION_ACCESSIBILITY:
        # AXIsProcessTrusted answers granted or not; macOS keeps no separate
        # "asked" record that is readable, so an ungranted state is reported as
        # "not asked" rather than "denied" -- the remedy is identical and
        # "denied" reads as a refusal the person may not have made.
        return "granted" if has_accessibility_permission() else "not asked"
    return "unknown"


def permission_report() -> dict[str, str]:
    """Every permission's state in one call, for the checklist page."""
    return {name: permission_state(name) for name in PERMISSION_ORDER}


def request_permission(name: str):
    """Ask for one permission, safely, from anywhere -- including a Tk callback.

    DO NOT route this to the prompting APIs. `AXIsProcessTrustedWithOptions`
    with the prompt option, and `IOHIDRequestAccess`, both put a system dialog
    on screen, and to do that macOS spins its own run loop *inside* the foreign
    call -- which pyobjc and ctypes enter with the GIL released and no Python
    thread state. Tk's event source fires a callback into that gap and the
    interpreter aborts on the spot:

        Fatal Python error: PyEval_RestoreThread: ... the GIL is released
        (the current Python thread state is NULL)

    There is no traceback and no crash dialog. From outside it is an app that
    asks for permission and then vanishes, which is exactly what it did.

    Opening the Settings pane instead is a subprocess. It cannot re-enter our
    event loop, it lands the person on the row they have to switch on, and the
    checklist notices the grant on its own when they come back. The prompting
    variants are kept below for callers that are provably not inside a Tk
    callback, and are not used by the app.
    """
    return open_privacy_settings(name)


def open_privacy_settings(name: str) -> bool:
    """Open System Settings on the pane that holds this permission's list.

    The deep link is what makes the checklist actionable. Told to "open System
    Settings, then Privacy & Security, then Accessibility", most people stop;
    landing on the list with the app already in it is a different task.
    """
    if not IS_MAC:
        return False
    pane = _PRIVACY_PANES.get(name)
    if not pane:
        return False
    try:
        import subprocess

        subprocess.run(
            ["/usr/bin/open", f"x-apple.systempreferences:com.apple.preference.security?{pane}"],
            check=False,
            timeout=5,
        )
        return True
    except Exception:
        return False



def fire_permission_prompts_via_helper() -> bool:
    """Show the real macOS permission dialogs, from a throwaway subprocess.

    The prompting APIs abort the interpreter when called inside Tk's event
    loop (Cocoa spins its own run loop mid-call), which is why the app itself
    never prompts. A subprocess of the bundled binary has no Tk to re-enter,
    and TCC attributes it to the app bundle, so the dialogs both appear and
    register the right rows in System Settings.
    """
    if not IS_MAC:
        return False
    try:
        import subprocess
        import sys as _sys

        if getattr(_sys, "frozen", False):
            command = [_sys.executable, "--fire-permission-prompts"]
        else:
            entry = Path(__file__).resolve().parents[1] / "talk_dat.py"
            command = [_sys.executable, str(entry), "--fire-permission-prompts"]
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:
        return False


def pin_to_dock_once(config: dict, save) -> None:
    """X-148: the app pins itself to the Dock on its first macOS launch.

    A Finder drag into /Applications runs no code, so the dmg cannot touch
    the Dock -- that is a macOS rule, not a gap. What the platform DOES
    allow is the running app adding its own tile: append a persistent-app
    entry to com.apple.dock and relaunch the Dock, once, stamped so a user
    who removes the tile is never fought. No-ops anywhere but macOS, when
    already stamped, when not running from /Applications (a dev checkout
    must not pin itself), or when the tile already exists.
    """
    if not IS_MAC:
        return
    ui = config.setdefault("ui", {})
    if ui.get("dock_pinned_once"):
        return
    try:
        import plistlib
        import subprocess

        # The reliable bundle path: executable lives at *.app/Contents/MacOS/...
        executable = Path(sys.executable).resolve()
        app_path = None
        for parent in executable.parents:
            if parent.suffix == ".app":
                app_path = parent
                break
        if app_path is None or not str(app_path).startswith("/Applications/"):
            return
        raw = subprocess.run(
            ["defaults", "export", "com.apple.dock", "-"],
            capture_output=True, timeout=10,
        ).stdout
        dock = plistlib.loads(raw) if raw else {}
        tiles = dock.get("persistent-apps", [])
        for tile in tiles:
            path = ((tile.get("tile-data") or {}).get("file-data") or {}).get("_CFURLString", "")
            if str(app_path) in path:
                ui["dock_pinned_once"] = True
                save(config)
                return
        tiles.append({
            "tile-data": {
                "file-data": {
                    "_CFURLString": f"file://{app_path}/",
                    "_CFURLStringType": 15,
                }
            }
        })
        dock["persistent-apps"] = tiles
        subprocess.run(["defaults", "import", "com.apple.dock", "-"], input=plistlib.dumps(dock), timeout=10)
        subprocess.run(["killall", "Dock"], timeout=10)
        ui["dock_pinned_once"] = True
        save(config)
    except Exception:
        import logging

        logging.getLogger(__name__).debug("dock pin skipped", exc_info=True)
