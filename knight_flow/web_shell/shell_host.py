"""Separate-process native host for bundled Talk DAT chrome.

The existing app owns state and actions. This host exposes only a JSON request
boundary over an inherited pipe. It never opens a control port or loads a URL.
"""
from __future__ import annotations
import base64
from collections import namedtuple
import contextlib
import json
import multiprocessing
from pathlib import Path
import queue
import secrets
import sys
import threading
import time

from .menu_geometry import pill_menu_bounds

MAX_MESSAGE = 1_048_576
#: error_code on an answer the window never got from the app: the link itself
#: failed (no reply, a closed pipe, a send that could not go out). The page
#: says so in the sidebar; an ordinary refusal from the app never carries it.
DISCONNECTED = 'disconnected'
#: X-682: the Pill menu's page fades for one exit (--t-exit, 140 ms, in shell.css)
#: before its window hides. Hiding at once cut every close to a single frame.
MENU_EXIT_SECONDS = 0.14
#: 0.4.178 (his report of 2026-11-09: the menu "won't disappear when I click away from it or hover away from it in a
#: skillful way over time"): once the pointer has left the menu, its submenu and the Pill, the menu closes after this
#: grace, and the pointer coming back cancels it. Native menus stay open while the pointer is away; he asked for a
#: forgiving close. 1.5 s is well past Windows' 400 ms submenu delay, so a deliberate move to a submenu or back never
#: trips it, and short enough that a menu left behind is gone before his next action.
MENU_HOVER_GRACE_SECONDS = 1.5
#: How often the renderer reads the pointer, its buttons, Esc and the foreground while the menu is shown: about a
#: display frame. Reads only; nothing is hooked or captured.
MENU_WATCH_SECONDS = 0.016
#: The virtual keys the watch reads: the mouse buttons (left, right, middle, X1, X2) and Esc.
MENU_BUTTON_KEYS = (0x01, 0x02, 0x04, 0x05, 0x06)
VK_ESCAPE = 0x1B
#: 0.4.178 (FINDINGS-0478 section 5): the menu window's WinForms minimum (240 x 200) clamped an in-place submenu view of
#: 157 px to 200 px, computed for 157, so the menu's bottom sat over the Pill. A menu is as small as its rows.
MENU_MIN_SIZE = (120, 40)
#: The page's requests the host forwards to the app; the rest (theme_asset,
#: cancel_close, dismiss, close) it answers itself. One list, read by both
#: checkpoints (the renderer's Api.request and the app's listener):
#: menu_fit was missing from both copies and every resize would have been
#: refused (tests/test_the_host_forwards_what_the_page_asks.py).
FORWARDED_METHODS = frozenset({'state', 'save', 'action', 'menu_layout', 'menu_fit', 'workspace'})


#: X-684: the menu window class's drop shadow. A frameless WinForms window has no
#: DWM shadow, so the Pill menu was a flat slab with four hard edges.
CS_DROPSHADOW = 0x00020000
GCL_STYLE = -26


class _HwndWindow:
    """Lets win32_chrome's Tk-shaped helpers take a WinForms form's HWND."""

    def __init__(self, hwnd):
        self._hwnd = int(hwnd)

    def winfo_id(self):
        return self._hwnd


class _ClassStyle:
    """GCL_STYLE through a private user32 handle (never ctypes.windll's shared one, X-605)."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        self._get = getattr(user32, 'GetClassLongPtrW', None) or user32.GetClassLongW
        self._set = getattr(user32, 'SetClassLongPtrW', None) or user32.SetClassLongW
        self._get.argtypes = (wintypes.HWND, ctypes.c_int)
        self._get.restype = ctypes.c_size_t
        self._set.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        self._set.restype = ctypes.c_size_t

    def get(self, hwnd):
        return int(self._get(hwnd, GCL_STYLE))

    def set(self, hwnd, style):
        import ctypes
        ctypes.set_last_error(0)
        return bool(self._set(hwnd, GCL_STYLE, style)) or ctypes.get_last_error() == 0


def _apply_menu_chrome(hwnd, *, chrome_api=None, windows_build=None, class_style=None):
    """Rounded corners on Windows 11 and the menu drop shadow on 10 and 11.

    X-684 (polish audit P0-4). Windows 11 rounds in the compositor, anti-aliased;
    Windows 10 cannot (a window region is a one-bit clip, the Pill's black stair
    edge), so there the menu stays square and keeps only the shadow. Both are set
    before the first show, so the first frame is already the final shape. A window-
    level fade would need a layered window, where WebView2 renders blank, so the
    page's own entrance does the motion instead. Returns (corners, shadow).
    """
    from knight_flow import win32_chrome
    receipt = win32_chrome.apply_window_chrome(_HwndWindow(hwnd), win32_chrome.UTILITY_CHROME, api=chrome_api,
                                               platform_name='win32', windows_build=windows_build)
    shadow = False
    with contextlib.suppress(Exception):
        styles = class_style or _ClassStyle()
        style = styles.get(hwnd)
        shadow = bool(style & CS_DROPSHADOW) or styles.set(hwnd, style | CS_DROPSHADOW)
    return receipt.mode, shadow


WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
GWL_EXSTYLE = -20


def _make_tool_window(hwnd, *, user32=None):
    """The menu and its submenu are tool windows: no taskbar button, no Alt+Tab entry (0.4.178).

    FINDINGS-0478 section 2.6: the menu window carried WS_EX_APPWINDOW (extended style 0x50008), so every open put a
    "Talk DAT!" button on the taskbar, flashing because Windows refused the window the foreground. Set before the first
    show (a shown window's taskbar entry is not re-read), with SWP_FRAMECHANGED so the system applies it.
    """
    import ctypes
    from ctypes import wintypes
    if user32 is None:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, wintypes.UINT)
        user32.SetWindowPos.restype = wintypes.BOOL
    style = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
    wanted = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    if wanted != style:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, wanted)
    # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
    return bool(user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020))


#: One reading of what the menu has to know while it is shown (0.4.178): the pointer (physical pixels, None when it
#: cannot be read), the mouse buttons down (virtual keys), Esc down, the foreground window, the rectangles that count
#: as "in the menu" (x, y, width, height: the menu, its submenu while shown, the Pill), and the menu's own windows.
MenuReading = namedtuple('MenuReading', 'point buttons escape foreground regions own')


def _inside(point, regions):
    if point is None:
        return True  # never close on a pointer that cannot be read
    x, y = point
    return any(left <= x < left + width and top <= y < top + height for left, top, width, height in regions)


class MenuWatch:
    """When the open Pill menu closes by itself (0.4.178, FINDINGS-0478 sections 3, 4 and 7).

    Pure: it is handed each reading and the time, so the rules are tested without Windows. A step answers None, or why
    the menu closes: "outside" (a mouse button pressed outside the menu, its submenu and the Pill), "hover" (the
    pointer has been outside them for the grace, with no button down and the keyboard not in use), "escape" (Esc
    pressed while the menu does not have the keyboard; the page decides what Esc closes) or "focus" (the foreground
    moved to a window that is not the menu's).
    """

    def __init__(self, grace=MENU_HOVER_GRACE_SECONDS):
        self.grace = grace
        #: Set by the page when a key is used in the menu: the grace waits until the pointer comes back.
        self.keyboard = False
        self._down = frozenset()
        self._escape = False
        self._foreground = 0
        self._outside_since = None

    def start(self, reading):
        # What is already down when the menu shows (the right-click that opened it) is not a press.
        self._down = frozenset(reading.buttons)
        self._escape = bool(reading.escape)
        self._foreground = reading.foreground if reading.foreground not in reading.own else 0
        self._outside_since = None
        self.keyboard = False

    def step(self, now, reading):
        inside = _inside(reading.point, reading.regions)
        pressed = frozenset(reading.buttons) - self._down
        self._down = frozenset(reading.buttons)
        escape = bool(reading.escape) and not self._escape
        self._escape = bool(reading.escape)
        if pressed and not inside:
            return 'outside'
        active = reading.foreground in reading.own
        if escape and not active:
            return 'escape'
        if reading.foreground and not active:
            if not self._foreground:
                self._foreground = reading.foreground
            elif reading.foreground != self._foreground:
                return 'focus'
        if inside:
            self._outside_since = None
            self.keyboard = False
            return None
        if self._down or self.keyboard:
            self._outside_since = None
            return None
        if self._outside_since is None:
            self._outside_since = now
            return None
        if now - self._outside_since >= self.grace - 1e-9:
            return 'hover'
        return None


def _menu_anchor(value):
    """The Pill the menu opened from, as the app measured it, or None: {pill, work, scale, side} validated."""
    if not isinstance(value, dict):
        return None
    try:
        pill = tuple(int(v) for v in value['pill'])
        work = tuple(int(v) for v in value['work'])
        scale = float(value['scale'])
    except (KeyError, TypeError, ValueError):
        return None
    side = value.get('side')
    if len(pill) != 4 or len(work) != 4 or not 0.5 <= scale <= 4.0 or side not in ('above', 'below'):
        return None
    return {'pill': pill, 'work': work, 'scale': scale, 'side': side}


def menu_origin(bounds, cursor):
    """The side of the menu that faces the Pill, as a transform-origin, and the rise.

    X-684: the menu opens from a right-click ON the Pill, so the pointer marks it.
    The page grows from there (Things 3: things grow from where they live): up out
    of a Pill below the menu, down out of a Pill above it.
    """
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise ValueError('menu bounds')
    x, y, width, height = (int(value) for value in bounds)
    if width <= 0 or height <= 0:
        raise ValueError('menu bounds')
    across = min(1.0, max(0.0, (float(cursor[0]) - x) / width))
    below = float(cursor[1]) >= y + height / 2
    return f'{across * 100:.0f}% {100 if below else 0}%', '8px' if below else '-8px'


def _cursor_position():
    import ctypes
    from ctypes import wintypes
    point = wintypes.POINT()
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    user32.GetCursorPos.restype = wintypes.BOOL
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise OSError('GetCursorPos')
    return point.x, point.y


def _menu_origin_js(bounds, side=None):
    """Script that tells the page where the Pill is, or nothing if that is unknown.

    `side` is the side of the Pill the app chose at open ('above' or 'below'). When it
    is given it decides the facing edge, so a keyboard open (the pointer anywhere) is
    right too (review B2); the pointer then only places the growth across the menu.
    """
    try:
        origin, rise = menu_origin(bounds, _cursor_position())
    except (OSError, ValueError, TypeError, AttributeError):
        if side not in ('above', 'below'):
            return ''
        origin, rise = '50% 0%', '-8px'
    if side in ('above', 'below'):
        across = origin.split(' ')[0]
        origin, rise = (across + ' 100%', '8px') if side == 'above' else (across + ' 0%', '-8px')
    # The edge that faces the Pill stays put when a view changes the window's height
    # (2026-10-09); the page anchors its content to it.
    anchor = 'bottom' if origin.endswith(' 100%') else 'top'
    return ('document.documentElement.style.setProperty("--menu-origin",' + json.dumps(origin) + ');'
            'document.documentElement.style.setProperty("--menu-rise",' + json.dumps(rise) + ');'
            'document.documentElement.dataset.menuAnchor=' + json.dumps(anchor) + ';')


#: X-688: the WebView2 context-menu items the Settings window keeps. Everything a
#: browser adds (Back, Reload, Save as, Print, Share, Inspect) goes.
EDIT_MENU_ITEMS = frozenset({'emoji', 'undo', 'redo', 'cut', 'copy', 'paste', 'pasteAndMatchStyle', 'selectAll'})


def _keep_edit_items(_sender, args):
    """ContextMenuRequested: keep the editing commands; open nothing if none are left."""
    items = args.MenuItems
    for index in range(items.Count - 1, -1, -1):
        item = items[index]
        if str(item.Kind) != 'Separator' and str(item.Name) not in EDIT_MENU_ITEMS:
            items.RemoveAt(index)
    kinds = [str(items[index].Kind) for index in range(items.Count)]
    if all(kind == 'Separator' for kind in kinds):
        args.Handled = True


def _allow_edit_menu(control):
    """Cut, Copy and Paste in the Settings window's text fields (interaction grid, build 24).

    pywebview turns WebView2's own context menu off (debug off) in its
    initialization handler, so a right-click in the search box, a note title or a
    provider key offered nothing. This subscribes after it and turns the menu back
    on, trimmed to the editing commands; the page keeps it shut outside text fields
    and selected reader text (shell.js).
    """
    def enable(sender, _args):
        core = sender.CoreWebView2
        core.Settings.AreDefaultContextMenusEnabled = True
        core.ContextMenuRequested += _keep_edit_items
    control.CoreWebView2InitializationCompleted += enable


def trusted_document(url, bundled_uri=None):
    return (url is None or url == 'about:blank' or str(url).startswith('about:blank#')
            or (bundled_uri is not None and url == bundled_uri))


def bundled_html(directory):
    directory = Path(directory)
    html = (directory / 'index.html').read_text(encoding='utf-8')
    css = (directory / 'shell.css').read_text(encoding='utf-8')
    javascript = (directory / 'shell.js').read_text(encoding='utf-8')
    css += '\n' + (directory / 'workspaces.css').read_text(encoding='utf-8')
    javascript = '\n'.join((directory / name).read_text(encoding='utf-8')
                            for name in ('workspaces.js','home.js','notes.js','recovery.js','words.js','translation.js','ramble.js','scribe.js','stats.js','mic-check.js','app-profiles.js','feedback.js','setup.js','reset.js','account.js')) + '\n' + javascript
    font = base64.b64encode((directory / 'fonts/KnightDisplay.ttf').read_bytes()).decode('ascii')
    css = css.replace('fonts/KnightDisplay.ttf', 'data:font/ttf;base64,' + font)
    atlas = base64.b64encode((directory / 'icons/line-art-atlas.png').read_bytes()).decode('ascii')
    css = css.replace('icons/line-art-atlas.png', 'data:image/png;base64,' + atlas)
    nonce = secrets.token_urlsafe(24)
    start = html.index('  <meta http-equiv="Content-Security-Policy"')
    end = html.index('\n', start)
    # pywebview 6.2.1 creates its bound JS functions with Function() and
    # returns native replies through eval(). WKWebView enforces this even
    # for native injection. Script sources still require our fresh nonce;
    # navigation is refused and all user strings are rendered as text nodes.
    policy = ("default-src 'none'; script-src 'nonce-" + nonce + "' 'unsafe-eval'; style-src 'unsafe-inline'; "
              "font-src data:; img-src data:; connect-src 'none'; object-src 'none'; "
              "base-uri 'none'; form-action 'none'; frame-src 'none'")
    html = html[:start] + '<meta http-equiv="Content-Security-Policy" content="' + policy + '">' + html[end:]
    html = html.replace('<link rel="stylesheet" href="shell.css">', '<style>' + css + '</style>')
    html = html.replace('<script src="shell.js" defer></script>', '')
    html = html.replace('<link rel="stylesheet" href="workspaces.css">', '')
    for name in ('workspaces.js','home.js','notes.js','recovery.js','words.js','translation.js','ramble.js','scribe.js','stats.js','mic-check.js','app-profiles.js','feedback.js','setup.js','reset.js','account.js'):
        html = html.replace('<script src="'+name+'" defer></script>', '')
    html = html.replace('</body>', '<script nonce="' + nonce + '">' + javascript + '</script></body>')
    if len(html.encode('utf-8')) >= 2 * 1024 * 1024:
        raise ValueError('The bundled settings document exceeds the native renderer limit')
    return html


def _send(connection, lock, message):
    data = json.dumps(message, ensure_ascii=True, allow_nan=False).encode('utf-8')
    if len(data) > MAX_MESSAGE:
        raise ValueError('The interface message is too large')
    with lock:
        connection.send_bytes(data)


def _receive(connection):
    value = json.loads(connection.recv_bytes(MAX_MESSAGE).decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Invalid interface message')
    return value


class _RendererApi:
    def __init__(self, connection, mode='settings'):
        self._connection = connection
        self._send_lock = threading.Lock()
        self._requests_lock = threading.Lock()
        self._pending = {}
        self._sequence = 0
        self._window = None
        self._guard_ready = False
        self._dirty = False
        self._force_close = False
        self._bundled_uri = None
        self._mode = mode
        self._close_token = None
        self._ready = threading.Event()
        self._materials = None
        self._menu_hide_lock = threading.Lock()
        self._menu_hide_generation = 0
        # The Pill menu's submenu window (2026-11-05), made with the menu in the same process; None elsewhere.
        self._submenu_window = None
        self._submenu_shown = False
        # 0.4.178: the open the app numbered (it learns when that open closed), the window the menu opened over (the
        # focus goes back to it), the Pill the menu opened from (the renderer sizes the window itself), and the watch.
        self._open_id = 0
        self._target = 0
        self._anchor = None
        self._show_on_fit = False
        self._watch = None
        self._watch_lock = threading.Lock()
        self._watch_generation = 0

    def _hide_menu_after_exit(self):
        """Hide the menu once its page has faded; a show in between cancels it."""
        with self._menu_hide_lock:
            self._menu_hide_generation += 1
            generation = self._menu_hide_generation

        def hide():
            with self._menu_hide_lock:
                if generation != self._menu_hide_generation:
                    return
            self._hide_menu_now()

        timer = threading.Timer(MENU_EXIT_SECONDS, hide)
        timer.daemon = True
        timer.start()

    def _hide_menu_now(self):
        """Hide the menu and its submenu at once, stop watching, and tell the app which open closed (0.4.178)."""
        self._stop_menu_watch()
        self._show_on_fit = False
        self._hide_submenu()
        self._window.hide()
        if self._mode == 'menu':
            with contextlib.suppress(OSError, ValueError, AttributeError):
                _send(self._connection, self._send_lock, {'event': 'menu_closed', 'open': self._open_id})

    # 0.4.178: the watch (FINDINGS-0478 section 3). The menu window never becomes active when it opens from the Pill
    # (Windows refuses the renderer process the foreground), so neither WinForms' Deactivate nor the page's blur ever
    # fired and nothing closed it. While it is shown, the renderer reads the pointer, its buttons, Esc and the
    # foreground about once a frame (MenuWatch decides), with no hook and no capture.
    def _menu_reading(self):
        return _read_menu(_hwnd_of(self._window), _hwnd_of(self._submenu_window),
                          self._anchor['pill'] if self._anchor else None)

    def _start_menu_watch(self):
        if self._mode != 'menu' or sys.platform != 'win32' or _hwnd_of(self._window) is None:
            return  # the readings are Win32's (the Mac's port is the lead's, FINDINGS-0478 section 8), of a real window
        watch = MenuWatch()
        with contextlib.suppress(OSError, ValueError, AttributeError):
            watch.start(self._menu_reading())
        with self._watch_lock:
            self._watch_generation += 1
            generation = self._watch_generation
            self._watch = watch
        threading.Thread(target=self._run_menu_watch, args=(generation,), name='TalkDatMenuWatch', daemon=True).start()

    def _stop_menu_watch(self):
        with self._watch_lock:
            self._watch_generation += 1
            self._watch = None

    def _run_menu_watch(self, generation):
        while True:
            time.sleep(MENU_WATCH_SECONDS)
            with self._watch_lock:
                if generation != self._watch_generation:
                    return
            try:
                if self._menu_watch_tick(time.monotonic()) is not None:
                    return
            except (OSError, ValueError, AttributeError):
                continue

    def _menu_watch_tick(self, now, reading=None):
        """One look at the pointer: what MenuWatch decided, acted on. Returns the decision."""
        watch = self._watch
        if watch is None:
            return None
        decision = watch.step(now, reading if reading is not None else self._menu_reading())
        if decision is None:
            return None
        if decision == 'escape':
            # The page decides what Esc closes: the submenu first, then the menu (WinUI). It asks "close" for the menu.
            self._window.evaluate_js('window.TalkDat.menuEscape();true')
            return decision
        self._stop_menu_watch()
        self._window.evaluate_js('window.TalkDat.leaveMenu();true')
        if decision == 'hover':
            # Nobody else took the focus: if the menu held it, his app gets it back.
            self._give_focus_back()
        self._hide_menu_after_exit()
        return decision

    def _give_focus_back(self):
        """If the menu (or its submenu) holds the foreground, give it back to the window it opened over."""
        own = {_hwnd_of(self._window), _hwnd_of(self._submenu_window)} - {None}
        with contextlib.suppress(OSError, ValueError, AttributeError):
            if self._target and _foreground_window() in own:
                _restore_foreground(self._target)

    def _cancel_menu_hide(self):
        with self._menu_hide_lock:
            self._menu_hide_generation += 1

    def _close_event(self, confirmed):
        if self._close_token is not None:
            _send(self._connection, self._send_lock, {
                'event': 'close_confirmed' if confirmed else 'close_cancelled',
                'token': self._close_token,
            })
            self._close_token = None

    def _trusted(self):
        return self._guard_ready and self._window is not None and trusted_document(self._window.get_current_url(), self._bundled_uri)

    def draft_changed(self, dirty):
        if self._trusted() and type(dirty) is bool:
            self._dirty = dirty

    def request(self, method, payload=None):
        if not self._trusted():
            return {'ok': False, 'error': 'This page cannot control Talk DAT.'}
        if method == 'theme_asset':
            if not isinstance(payload, dict) or set(payload) != {'theme', 'size'}:
                return {'ok': False, 'error': 'This theme material is unavailable.'}
            try:
                if self._materials is None:
                    from .theme_assets import MaterialLibrary
                    self._materials = MaterialLibrary()
                uri = self._materials.read(payload['theme'], payload['size'])
                return {'ok': True, 'result': {'uri': uri}}
            except (OSError, ValueError):
                return {'ok': False, 'error': 'This theme material is unavailable.'}
        if method == 'cancel_close':
            self._close_event(False)
            return {'ok': True, 'result': None}
        if method == 'dismiss' and self._mode == 'menu':
            self._hide_menu_after_exit()
            return {'ok': True, 'result': None}
        if method == 'submenu' and self._mode == 'menu':
            return self._submenu_request(payload)
        if method == 'menu_input' and self._mode == 'menu':
            # 0.4.178: a key was used in the menu; the hover grace waits until the pointer comes back.
            if not isinstance(payload, dict) or payload != {'keyboard': True}:
                return {'ok': False, 'error': 'This action is unavailable.'}
            watch = self._watch
            if watch is not None:
                watch.keyboard = True
            return {'ok': True, 'result': None}
        if method == 'close':
            if self._mode == 'menu' and self._close_token is None:
                # Esc or Close in the page: the menu had the keyboard, so his app gets the focus back (0.4.178).
                self._stop_menu_watch()
                self._give_focus_back()
                self._hide_menu_after_exit()
                return {'ok': True, 'result': None}
            self._close_event(True)
            self._force_close = True
            threading.Timer(0.1, self._window.destroy).start()
            return {'ok': True, 'result': None}
        if method not in FORWARDED_METHODS or not isinstance(payload, dict):
            return {'ok': False, 'error': 'This action is unavailable.'}
        if method == 'menu_fit' and self._mode == 'menu' and self._anchor is not None:
            # 0.4.178: the renderer sizes the window itself from the Pill the app measured, at once; the app still hears
            # the fit (it keeps the width for the next open) but its resize would only repeat this one.
            self._fit_menu_here(payload)
        return self._forward(method, payload)

    def _fit_bounds(self, size):
        """The window for a view of `size` ({width, height}, CSS px at 100%) beside the Pill, or None."""
        anchor = self._anchor
        if anchor is None or not isinstance(size, dict):
            return None
        sane = lambda value: type(value) in (int, float) and 100 <= value <= 2000
        height, width = size.get('height'), size.get('width')
        if not sane(height) or (width is not None and not sane(width)):
            return None
        return pill_menu_bounds(anchor['pill'], anchor['work'], anchor['scale'], height=height, side=anchor['side'],
                                width=width)

    def _fit_menu_here(self, size):
        bounds = self._fit_bounds(size)
        if bounds is None:
            return
        self._place_menu(bounds)
        if self._show_on_fit:
            # A cold open: the window waited for the page's first measured view, so its first frame is its last size.
            self._show_on_fit = False
            self._show()
            self._place_menu(bounds)
            self._start_menu_watch()

    def _forward(self, method, payload):
        with self._requests_lock:
            if len(self._pending) >= 32:
                return {'ok': False, 'error': 'Talk DAT is busy. Please try again.'}
            self._sequence += 1
            request_id = self._sequence
            pending = {'event': threading.Event(), 'answer': None}
            self._pending[request_id] = pending
        try:
            _send(self._connection, self._send_lock, {'id': request_id, 'method': method, 'payload': payload})
            picker = method == 'workspace' and payload.get('area') == 'scratchpad' and payload.get('operation') in {'import','export'}
            if not pending['event'].wait(300 if picker else 20):
                return {'ok': False, 'error': 'Talk DAT did not respond. Your draft is still here.', 'error_code': DISCONNECTED}
            answer = pending['answer']
            # Failed actions must remain visible. In particular, opening Settings
            # can fail during renderer startup; hiding first loses the error.
            # Field report 2026-11-05: every successful action closes the menu, a Speech or
            # Formatting choice included, as WinUI closes every menu when an item is invoked.
            if method == 'action' and self._mode == 'menu' and answer and answer.get('ok'):
                self._hide_menu_after_exit()
            return answer
        except (OSError, ValueError) as error:
            if isinstance(error, ValueError) and 'too large' in str(error):
                # An oversized request is this page's mistake, not a lost link.
                return {'ok': False, 'error': 'That request is too large to send. Your draft is still here.'}
            return {'ok': False, 'error': 'Talk DAT is reconnecting. Your draft is still here.', 'error_code': DISCONNECTED}
        finally:
            with self._requests_lock:
                self._pending.pop(request_id, None)

    def _show(self):
        self._cancel_menu_hide()
        if sys.platform == 'darwin':
            from PyObjCTools import AppHelper
            from webview.platforms.cocoa import BrowserView
            def activate_then_show():
                BrowserView.app.setActivationPolicy_(1)
                self._window.show()
            AppHelper.callAfter(activate_then_show)
        else:
            if self._mode != 'menu':
                self._window.restore()
            elif sys.platform == 'win32':
                # 0.4.178: WinForms rewrites the extended style from its own CreateParams whenever it updates styles
                # (pywebview's hidden start toggles Opacity), so the tool-window style is set again before each show.
                with contextlib.suppress(Exception):
                    _make_tool_window(int(self._window.native.Handle.ToInt64()))
            self._window.show()

    def _native_menu_deactivated(self, _sender=None, _args=None):
        # WebView's DOM blur does not reliably follow WinForms activation.
        # Outside clicks must also dismiss at the native window boundary.
        if self._mode == 'menu' and self._window.native.Visible:
            self._dismiss_unless_partner()

    def _submenu_deactivated(self, _sender=None, _args=None):
        # 0.4.178: only a submenu that is showing speaks for the pair. Its hidden start (pywebview shows a hidden window
        # at opacity 0 and hides it) and its own closing also deactivate it, and those must not close the menu.
        if self._mode == 'menu' and self._submenu_shown:
            self._dismiss_unless_partner()

    def _dismiss_unless_partner(self):
        """The menu and its submenu dismiss as one (2026-11-05): focus moving from one to the other keeps both;
        anywhere else hides both. Read once the activation has settled."""
        def check():
            pair = {_hwnd_of(self._window), _hwnd_of(self._submenu_window)} - {None}
            with contextlib.suppress(Exception):
                if _foreground_window() in pair:
                    return
            self._hide_menu_after_exit()

        timer = threading.Timer(0.05, check)
        timer.daemon = True
        timer.start()

    def _hide_submenu(self):
        self._submenu_shown = False
        hwnd = _hwnd_of(self._submenu_window)
        if hwnd is not None:
            with contextlib.suppress(Exception):
                _hide_window(hwnd)

    def _submenu_request(self, payload):
        """Open, place or close the submenu window for the menu page (never forwarded to the app)."""
        unavailable = {'ok': False, 'error': 'This menu is unavailable.'}
        if not isinstance(payload, dict) or self._submenu_window is None:
            return unavailable
        if payload.get('op') == 'close':
            self._hide_submenu()
            if payload.get('refocus') is True:
                self._window.show()
            return {'ok': True, 'result': None}
        if payload.get('op') != 'open':
            return unavailable
        values = _submenu_values(payload)
        if values is None:
            return unavailable
        rows, (x, y, width, height), (sub_width, sub_height), scale, keyboard, theme = values
        from .menu_geometry import submenu_bounds
        try:
            parent, child = _hwnd_of(self._window), _hwnd_of(self._submenu_window)
            left, top, _right, _bottom = _window_rect(parent)
            row = (left + round(x * scale), top + round(y * scale), round(width * scale), round(height * scale))
            bounds = submenu_bounds(row, (round(sub_width * scale), round(sub_height * scale)), _work_area_of(parent), scale)
            _position_menu_window(child, bounds)
            with contextlib.suppress(Exception):
                _make_tool_window(child)
            self._submenu_window.evaluate_js('window.TalkDat.showSubmenu(' + json.dumps(
                {'rows': rows, 'keyboard': keyboard, 'theme': theme}) + ');true')
            self._submenu_shown = True
            if keyboard:
                self._submenu_window.show()
            else:
                _show_without_activating(child)
        except (OSError, ValueError):
            return unavailable
        # 0.4.178: where it opened in the menu page's own pixels, for the page's menu-aim triangle.
        local = [round((bounds[0] - left) / scale, 1), round((bounds[1] - top) / scale, 1),
                 round(bounds[2] / scale, 1), round(bounds[3] / scale, 1)]
        return {'ok': True, 'result': {'bounds': bounds, 'local': local}}

    def _place_menu(self, bounds):
        if not isinstance(bounds, list) or len(bounds) != 4 or not all(type(v) is int for v in bounds):
            return
        x, y, width, height = bounds
        if width <= 0 or height <= 0:
            return
        if sys.platform == 'win32':
            # Tk's anchor and monitor rectangles are physical pixels. pywebview's
            # move/resize multiply by monitor DPI, so apply these bounds directly.
            hwnd = int(self._window.native.Handle.ToInt64())
            _position_menu_window(hwnd, bounds)
        else:
            self._window.resize(width, height)
            self._window.move(x, y)

    def _closing(self):
        if session_is_ending():
            # Never veto Windows: the window closes with the session.
            self._force_close = True
            self._close_event(True)
            return True
        if self._mode == 'menu' and not self._force_close:
            threading.Timer(0.01, self._window.hide).start()
            return False
        if self._ready.is_set() and not self._force_close:
            # Closing is synchronous on the native UI thread. JS evaluation
            # marshals there, so request it from a worker instead of deadlocking.
            threading.Thread(target=lambda: self._window.evaluate_js('window.TalkDat.requestClose()'), daemon=True).start()
            return False
        self._close_event(True)
        return True

    def _take_menu_open(self, message):
        """The open's number, the window it opened over and the Pill it opened from (0.4.178)."""
        number, target = message.get('open'), message.get('target')
        self._open_id = number if type(number) is int else 0
        self._target = target if type(target) is int and target > 0 else 0
        self._anchor = _menu_anchor(message.get('anchor'))

    def _open_menu(self, message):
        """Open the Pill menu whole (0.4.178, FINDINGS-0478 section 2).

        One call into the page draws the menu from what the app sent with the open (no whole-state answer to wait
        for, no redraw 130 to 260 ms later) and answers the size it drew; the window is placed at that size beside the
        Pill and only then shown, so nothing moves after the first frame. Then the watch starts.
        """
        self._cancel_menu_hide()
        self._stop_menu_watch()
        self._take_menu_open(message)
        bounds, side = message.get('bounds'), message.get('side')
        fresh = message.get('fresh') if isinstance(message.get('fresh'), dict) else None
        origin = _menu_origin_js(bounds, side)
        size = None
        with contextlib.suppress(Exception):
            answer = self._window.evaluate_js(origin + 'JSON.stringify(window.TalkDat.openMenu(' + json.dumps(fresh)
                                              + ')||null)')
            size = json.loads(answer) if isinstance(answer, str) else None
        fitted = self._fit_bounds(size)
        if fitted is not None:
            bounds = fitted
        self._place_menu(bounds)
        self._show()
        # Whatever showing did, the menu ends on the Pill.
        self._place_menu(bounds)
        self._start_menu_watch()

    def _read(self):
        try:
            while True:
                message = _receive(self._connection)
                if message.get('command') == 'close':
                    self._force_close = True
                    self._window.destroy()
                    return
                if message.get('command') == 'request_close':
                    token = message.get('token')
                    if isinstance(token, str) and len(token) <= 64 and self._ready.wait(20):
                        self._close_token = token
                        self._show()
                        self._window.evaluate_js('window.TalkDat.requestClose();true')
                    continue
                if message.get('command') == 'hide':
                    if self._mode == 'menu':
                        self._hide_menu_now()
                    else:
                        self._window.hide()
                    continue
                if message.get('command') == 'dismiss' and self._mode == 'menu':
                    # 0.4.178: the second right-click on the Pill: the page plays its exit, then the window hides.
                    self._stop_menu_watch()
                    with contextlib.suppress(Exception):
                        self._window.evaluate_js('window.TalkDat.leaveMenu();true')
                    self._hide_menu_after_exit()
                    continue
                if message.get('command') == 'resize' and self._mode == 'menu':
                    if self._anchor is None:
                        self._place_menu(message.get('bounds'))
                    continue
                if message.get('command') == 'navigate' and self._mode == 'menu' and _menu_anchor(message.get('anchor')):
                    if self._ready.wait(20):
                        self._open_menu(message)
                    continue
                if message.get('command') == 'navigate':
                    page = message.get('page', 'general')
                    if isinstance(page, str) and len(page) <= 40 and self._ready.wait(20):
                        origin = ''
                        if self._mode == 'menu':
                            self._take_menu_open(message)
                            self._place_menu(message.get('bounds'))
                            origin = _menu_origin_js(message.get('bounds'), message.get('side'))
                        self._window.evaluate_js(origin + 'window.TalkDat.navigate(' + json.dumps(page) + ');true')
                        self._show()
                        if self._mode == 'menu':
                            # Whatever showing did, the menu ends on the Pill.
                            self._place_menu(message.get('bounds'))
                            self._start_menu_watch()
                    continue
                with self._requests_lock:
                    pending = self._pending.get(message.get('id'))
                if pending is not None:
                    pending['answer'] = message.get('answer', {'ok': False, 'error': 'Invalid app response.'})
                    pending['event'].set()
        except (OSError, EOFError, ValueError):
            with self._requests_lock:
                for pending in self._pending.values():
                    pending['answer'] = {'ok': False, 'error': 'Talk DAT closed. Your changes were not saved.', 'error_code': DISCONNECTED}
                    pending['event'].set()


def _install_mac_policy():
    from webview.platforms.cocoa import BrowserView
    class TalkDatBundledDelegate(BrowserView.BrowserDelegate):
        def webView_decidePolicyForNavigationAction_decisionHandler_(self, webview, action, handler):
            url = str(action.request().URL().absoluteString())
            handler(1 if trusted_document(url) else 0)
        def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(self, webview, config, action, features):
            return None
    BrowserView.BrowserDelegate = TalkDatBundledDelegate


def _position_menu_window(hwnd, bounds, *, user32=None):
    """Apply physical monitor coordinates without virtualizing this worker."""
    import ctypes
    from ctypes import wintypes
    if user32 is None:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
    context = user32.SetThreadDpiAwarenessContext
    context.argtypes = (wintypes.HANDLE,)
    context.restype = wintypes.HANDLE
    position = user32.SetWindowPos
    position.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, ctypes.c_int, wintypes.UINT)
    position.restype = wintypes.BOOL
    # The renderer's reply/loaded workers do not necessarily inherit the
    # native UI thread's DPI context. Match the physical anchor reader here,
    # including negative coordinates and monitors with different scaling.
    previous = context(wintypes.HANDLE(-4))
    try:
        if not position(hwnd, None, *bounds, 0x0014):
            raise OSError('Could not position the Pill menu')
    finally:
        if previous:
            context(previous)


def _physical_user32(user32=None):
    """user32 with the calls the submenu makes typed, and this thread set to physical pixels (per-monitor v2)."""
    import ctypes
    from ctypes import wintypes
    user32 = user32 or ctypes.WinDLL('user32', use_last_error=True)
    user32.SetThreadDpiAwarenessContext.argtypes = (wintypes.HANDLE,)
    user32.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
    return user32


def _window_rect(hwnd, *, user32=None):
    """A window's rectangle, physical pixels: (left, top, right, bottom)."""
    import ctypes
    from ctypes import wintypes
    user32 = _physical_user32(user32)
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    rect = wintypes.RECT()
    previous = user32.SetThreadDpiAwarenessContext(wintypes.HANDLE(-4))
    try:
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise OSError('Could not read the menu window')
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)
    return rect.left, rect.top, rect.right, rect.bottom


def _work_area_of(hwnd, *, user32=None):
    """The work area of the monitor a window is on, physical pixels: (left, top, right, bottom)."""
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT),
                    ('dwFlags', wintypes.DWORD)]

    user32 = _physical_user32(user32)
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MONITORINFO))
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    previous = user32.SetThreadDpiAwarenessContext(wintypes.HANDLE(-4))
    try:
        if not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):  # MONITOR_DEFAULTTONEAREST
            raise OSError('Could not read the monitor')
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)
    work = info.rcWork
    return work.left, work.top, work.right, work.bottom


def _show_without_activating(hwnd, *, user32=None):
    """Show a window on top without taking the focus: a hover opens a submenu, and the menu keeps the keyboard."""
    from ctypes import wintypes
    user32 = _physical_user32(user32)
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, wintypes.INT, wintypes.INT, wintypes.INT, wintypes.INT,
                                    wintypes.UINT)
    # HWND_TOPMOST; SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW
    if not user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040):
        raise OSError('Could not show the submenu')


def _hide_window(hwnd, *, user32=None):
    from ctypes import wintypes
    user32 = _physical_user32(user32)
    user32.ShowWindow.argtypes = (wintypes.HWND, wintypes.INT)
    user32.ShowWindow(hwnd, 0)  # SW_HIDE


def _foreground_window(*, user32=None):
    user32 = _physical_user32(user32)
    return int(user32.GetForegroundWindow() or 0)


def _restore_foreground(hwnd, *, user32=None):
    """Give the foreground back to the window the menu opened over (the renderer holds it, so Windows allows it)."""
    from ctypes import wintypes
    user32 = _physical_user32(user32)
    user32.IsWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    if user32.IsWindow(hwnd):
        user32.SetForegroundWindow(hwnd)


_WATCH_USER32 = None


def _read_menu(menu, submenu, pill, *, user32=None):
    """One MenuReading on Windows (0.4.178): reads only (GetCursorPos, GetAsyncKeyState, GetForegroundWindow, the
    windows' rectangles), in physical pixels, as the Pill's anchor and the menu's bounds are."""
    import ctypes
    from ctypes import wintypes
    global _WATCH_USER32
    if user32 is None:
        # One typed handle for the whole watch (about sixty readings a second).
        _WATCH_USER32 = _WATCH_USER32 or _physical_user32()
        user32 = _WATCH_USER32
    user32 = _physical_user32(user32)
    user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    previous = user32.SetThreadDpiAwarenessContext(wintypes.HANDLE(-4))
    try:
        cursor = wintypes.POINT()
        point = (cursor.x, cursor.y) if user32.GetCursorPos(ctypes.byref(cursor)) else None
        buttons = frozenset(key for key in MENU_BUTTON_KEYS if user32.GetAsyncKeyState(key) & 0x8000)
        escape = bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)
        foreground = int(user32.GetForegroundWindow() or 0)
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)
    regions = []
    for hwnd in (menu, submenu):
        if hwnd and user32.IsWindowVisible(hwnd):
            left, top, right, bottom = _window_rect(hwnd, user32=user32)
            regions.append((left, top, right - left, bottom - top))
    if pill:
        regions.append(tuple(int(value) for value in pill))
    return MenuReading(point=point, buttons=buttons, escape=escape, foreground=foreground, regions=tuple(regions),
                       own=frozenset(hwnd for hwnd in (menu, submenu) if hwnd))


def _hwnd_of(window):
    if window is None:
        return None
    with contextlib.suppress(Exception):
        return int(window.native.Handle.ToInt64())
    return None


#: The submenu's request, read by _RendererApi._submenu_request: at most this many rows, these keys per row.
SUBMENU_ROWS = 16
SUBMENU_ROW_KEYS = {'label': str, 'icon': str, 'kind': str, 'checked': bool, 'value': str, 'disabled': bool,
                    'description': str}


def _submenu_values(payload):
    """The validated parts of an "open" request, or None: rows, anchor, size, scale, keyboard, theme."""
    def number(value, low, high):
        return type(value) in (int, float) and low <= value <= high

    rows = payload.get('rows')
    if not isinstance(rows, list) or not 1 <= len(rows) <= SUBMENU_ROWS:
        return None
    kept = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('label'), str) or not row['label'] or len(row['label']) > 80:
            return None
        entry = {}
        for key, value in row.items():
            want = SUBMENU_ROW_KEYS.get(key)
            if want is None or type(value) is not want or (want is str and len(value) > 160):
                return None
            entry[key] = value
        kept.append(entry)
    anchor, size = payload.get('anchor'), payload.get('size')
    if not isinstance(anchor, dict) or not isinstance(size, dict):
        return None
    box = [anchor.get(key) for key in ('x', 'y', 'width', 'height')]
    if not all(number(value, -10000, 10000) for value in box) or box[2] <= 0 or box[3] <= 0:
        return None
    extent = [size.get(key) for key in ('width', 'height')]
    if not all(number(value, 1, 4000) for value in extent):
        return None
    scale, keyboard = payload.get('scale'), payload.get('keyboard', False)
    if not number(scale, 0.5, 4.0) or type(keyboard) is not bool:
        return None
    theme = payload.get('theme')
    if theme is not None and not (isinstance(theme, dict) and len(theme) <= 64
                                  and all(isinstance(k, str) and isinstance(v, (str, int, float, bool)) and len(str(v)) <= 300
                                          for k, v in theme.items())):
        return None
    return kept, box, extent, float(scale), keyboard, theme


class _SubmenuApi:
    """The submenu window's js_api (2026-11-05): its page reports pointer and click events, and they go to the menu
    page in order. It asks for nothing else; the menu page keeps every decision."""

    EVENTS = frozenset({'enter', 'leave', 'invoke', 'close', 'ready'})

    def __init__(self, menu_api):
        self._menu = menu_api
        self._window = None
        self._bundled_uri = None
        self._guard_ready = False
        self._outbox = queue.SimpleQueue()
        threading.Thread(target=self._relay, name='TalkDatSubmenuRelay', daemon=True).start()

    def _trusted(self):
        return self._guard_ready and self._window is not None and trusted_document(self._window.get_current_url(), self._bundled_uri)

    def event(self, kind, index=-1):
        if kind not in self.EVENTS or type(index) is not int or not -1 <= index < SUBMENU_ROWS or not self._trusted():
            return False
        self._outbox.put({'kind': kind, 'index': index})
        return True

    def _relay(self):
        while True:
            message = self._outbox.get()
            window = self._menu._window
            if window is not None:
                with contextlib.suppress(Exception):
                    window.evaluate_js('window.TalkDat.submenuEvent(' + json.dumps(message) + ');true')


#: Set when Windows announces the session is ending (SystemEvents.SessionEnding).
_SESSION_ENDING = threading.Event()


def session_is_ending():
    """Windows is signing out, restarting or shutting down.

    X-606, 2026-09-24: the owner's PC restarted and Windows logged "Talk Dat!.exe
    attempted to veto the shutdown". _closing cancels a close to hide the menu
    or to let Settings ask about a draft, and a cancelled close during shutdown
    IS a veto. Two independent signals, because the order in which Windows
    asks each window is not defined: SM_SHUTTINGDOWN, and the session-ending
    event this process subscribed to.
    """
    if _SESSION_ENDING.is_set():
        return True
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        return bool(ctypes.WinDLL('user32').GetSystemMetrics(0x2000))  # SM_SHUTTINGDOWN
    except Exception:
        return False


def _watch_session_end():
    """Flag the session end the moment Windows announces it (pythonnet only)."""
    if sys.platform != 'win32':
        return
    with contextlib.suppress(Exception):
        from Microsoft.Win32 import SystemEvents
        SystemEvents.SessionEnding += lambda _sender, _args: _SESSION_ENDING.set()


def _make_submenu_window(webview, api, html):
    """The submenu's own window, beside the menu (0.4.177's design; 0.4.178 creates it, FINDINGS-0478 section 5).

    Parts 1-2 of 0.4.177 built the request, _SubmenuApi, the geometry and the page side and left the window itself for
    part 3, and no part made it: _submenu_window stayed None, every Windows submenu opened in place, and a rest on
    Speech replaced the whole menu and resized its window. Same page, same process; hidden until a submenu opens.
    """
    submenu_api = _SubmenuApi(api)
    submenu_api._bundled_uri = api._bundled_uri
    submenu = webview.create_window('Talk DAT!', html=html, js_api=submenu_api, hidden=True, background_color='#061012',
                                    zoomable=False, width=288, height=120, min_size=MENU_MIN_SIZE, frameless=True,
                                    easy_drag=False, on_top=True, resizable=False, x=0, y=0)
    submenu_api._window = submenu
    api._submenu_window = submenu

    def guard():
        native = submenu.native.browser.webview

        def refuse_external(_sender, args):
            if not trusted_document(str(args.Uri), submenu_api._bundled_uri):
                args.Cancel = True
        native.NavigationStarting += refuse_external
        submenu_api._navigation_handler = refuse_external
        submenu.native.Deactivate += api._submenu_deactivated
        with contextlib.suppress(Exception):
            _apply_menu_chrome(int(submenu.native.Handle.ToInt64()))
        with contextlib.suppress(Exception):
            _make_tool_window(int(submenu.native.Handle.ToInt64()))
        submenu_api._guard_ready = True
    submenu.events.before_show += guard
    return submenu


def _run_window(connection, html, page, hidden=False, mode='settings', bounds=None, side=None, menu=None):
    """The renderer process. `menu` (the Pill menu's first open, 0.4.178): the open's number, the window it opened
    over and the Pill it opened from, as ShellController sends them with every later open."""
    import webview
    webview.settings['ALLOW_DOWNLOADS'] = False
    webview.settings['ALLOW_FILE_URLS'] = False
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
    webview.settings['OPEN_DEVTOOLS_IN_DEBUG'] = False
    if sys.platform == 'darwin':
        _install_mac_policy()
        from webview.platforms.cocoa import BrowserView
        # pywebview activates even hidden windows on its first event loop.
        # Prewarming must not take focus; explicit open restores accessory mode.
        BrowserView.app.setActivationPolicy_(2 if hidden else 1)
    api = _RendererApi(connection, mode=mode)
    api._bundled_uri = 'data:text/html;charset=utf-8;base64,' + base64.b64encode(html.encode('utf-8')).decode('ascii')
    options = {'width': 1120, 'height': 760, 'min_size': (720, 500)}
    if mode == 'menu':
        options = {'width': 304, 'height': 552, 'min_size': MENU_MIN_SIZE,
                   'frameless': True, 'easy_drag': False, 'on_top': True, 'resizable': False}
        if bounds is not None and sys.platform != 'win32':
            options.update(zip(('x', 'y', 'width', 'height'), bounds))
        elif sys.platform == 'win32':
            # X-605: with no position pywebview starts the form CenterScreen,
            # and WinForms applies that on the FIRST Show() -- after
            # _place_menu had already put the window on the Pill. The first
            # menu after every launch opened centred somewhere else, often on
            # another monitor. A manual start keeps _place_menu's position.
            options.update(x=0, y=0)
    window = webview.create_window('Talk DAT!', html=html, js_api=api, hidden=hidden or mode == 'menu',
                                   background_color='#061012', zoomable=mode != 'menu', **options)
    api._window = window
    _watch_session_end()
    def protect_navigation():
        if sys.platform == 'win32':
            native = window.native.browser.webview
            def refuse_external(_sender, args):
                if not trusted_document(str(args.Uri), api._bundled_uri):
                    args.Cancel = True
            native.NavigationStarting += refuse_external
            api._navigation_handler = refuse_external
            if mode == 'menu':
                if not hasattr(api, '_deactivate_handler'):
                    api._deactivate_handler = api._native_menu_deactivated
                    window.native.Deactivate += api._deactivate_handler
                # X-684: corners and shadow before the first frame; never fatal.
                with contextlib.suppress(Exception):
                    _apply_menu_chrome(int(window.native.Handle.ToInt64()))
                # 0.4.178: a menu is a tool window (no taskbar button); _show sets it again before every show.
                with contextlib.suppress(Exception):
                    _make_tool_window(int(window.native.Handle.ToInt64()))
            if mode != 'menu':
                # X-688: Cut, Copy and Paste in text fields; never fatal.
                with contextlib.suppress(Exception):
                    _allow_edit_menu(native)
        api._guard_ready = True
    window.events.before_show += protect_navigation
    window.events.closing += api._closing
    if mode == 'menu' and sys.platform == 'win32':
        _make_submenu_window(webview, api, html)
    def ready():
        origin = _menu_origin_js(bounds, side) if mode == 'menu' and bounds is not None else ''
        cold = mode == 'menu' and not hidden and isinstance(menu, dict) and _menu_anchor(menu.get('anchor')) is not None
        if cold:
            # 0.4.178: a cold open waits for the page's first measured view (it has no state yet), so its first frame
            # is its final size and place (FINDINGS-0478 section 2.3: shown at 288 px, resized to 347 px 83 ms later).
            api._take_menu_open(menu)
            api._show_on_fit = True
        window.evaluate_js(origin + 'window.TalkDat.navigate(' + json.dumps(page) + ');true')
        if mode == 'menu':
            api._place_menu(bounds)
            if cold:
                def late():
                    if api._show_on_fit:  # the page never measured (it could not reach the app): show it as it is
                        api._show_on_fit = False
                        api._show()
                        api._start_menu_watch()
                timer = threading.Timer(2.0, late)
                timer.daemon = True
                timer.start()
            elif not hidden:
                api._show()
                api._place_menu(bounds)
                api._start_menu_watch()
        api._ready.set()
    window.events.loaded += ready
    threading.Thread(target=api._read, name='TalkDatShellReplies', daemon=True).start()
    # The process wrapper owns the pipe lifetime so startup failures can
    # still reach the parent and restore the existing settings window.
    webview.start(gui='edgechromium' if sys.platform == 'win32' else 'cocoa',
                  debug=False, http_server=False, private_mode=True)


def _window_process(connection, *args):
    try:
        _run_window(connection, *args)
    except Exception as error:
        with contextlib.suppress(Exception):
            _send(connection, threading.Lock(), {'event':'renderer_failed', 'reason':type(error).__name__})
    finally:
        connection.close()


class ShellController:
    def __init__(self, assets, dispatch, handler, *, mode='settings', on_failure=None):
        self.assets = Path(assets)
        self.dispatch = dispatch
        self.handler = handler
        self.process = None
        self.connection = None
        self.send_lock = threading.Lock()
        # X-172b: open() is called from the Tk thread AND from the startup
        # prewarm thread. Without this, both could see `process is None` and
        # spawn a second renderer.
        self.open_lock = threading.RLock()
        self.capacity = threading.BoundedSemaphore(32)
        self.mode = mode
        self.on_failure = on_failure
        self._close_request = None
        self._intentional_close = False
        #: 0.4.178: whether the Pill menu is showing (a second right-click closes it), and the number of its last open,
        #: so a close the renderer reports for an older open changes nothing.
        self.menu_open = False
        self._open_id = 0

    def _menu_message(self, hidden, anchor, fresh, target):
        """What a shown Pill menu's open carries besides its page (0.4.178), or None for a hidden prewarm."""
        if self.mode != 'menu' or hidden:
            return None
        self._open_id += 1
        self.menu_open = True
        return {'open': self._open_id, 'anchor': anchor, 'fresh': fresh, 'target': int(target or 0)}

    def open(self, page='general', *, hidden=False, bounds=None, side=None, anchor=None, fresh=None, target=0):
        with self.open_lock:
            menu = self._menu_message(hidden, anchor, fresh, target)
            if self.process is not None and self.process.is_alive():
                message = {'command': 'navigate', 'page': page, 'bounds': bounds, 'side': side}
                if menu is not None:
                    message.update(menu)
                _send(self.connection, self.send_lock, message)
                return
            self._intentional_close = False
            context = multiprocessing.get_context('spawn')
            parent, child = context.Pipe(duplex=True)
            self.connection = parent
            self.process = context.Process(target=_window_process, args=(child, bundled_html(self.assets), page, hidden, self.mode, bounds, side, menu),
                                           name='TalkDatSettings', daemon=True)
            self.process.start()
            child.close()
            threading.Thread(target=self._listen, args=(parent,), name='TalkDatShellRequests', daemon=True).start()

    def _listen(self, connection):
        try:
            while True:
                message = _receive(connection)
                if 'event' in message:
                    self.accept_event(message)
                    continue
                request_id, method, payload = message.get('id'), message.get('method'), message.get('payload')
                if type(request_id) is not int or method not in FORWARDED_METHODS or not isinstance(payload, dict):
                    raise ValueError('Invalid shell request')
                if not self.capacity.acquire(blocking=False):
                    _send(connection, self.send_lock, {'id': request_id, 'answer': {'ok': False, 'error': 'Talk DAT is busy.'}})
                    continue
                def perform(request_id=request_id, method=method, payload=payload):
                    try:
                        answer = {'ok': True, 'result': self.handler(method, payload)}
                    except ValueError as error:
                        answer = {'ok': False, 'error': str(error)}
                        if type(error).__name__ == 'SettingsConflict':
                            answer['error_code'] = 'settings_conflict'
                    except Exception:
                        answer = {'ok': False, 'error': 'This action could not finish. Your draft is still here.'}
                    try:
                        _send(connection, self.send_lock, {'id': request_id, 'answer': answer})
                    except (OSError, ValueError):
                        pass
                    finally:
                        self.capacity.release()
                self.dispatch(perform)
        except (OSError, EOFError, ValueError):
            pass
        finally:
            connection.close()

    def confirm_close(self, continuation):
        if self.process is None or not self.process.is_alive():
            return False
        if self._close_request is not None:
            return True
        token = secrets.token_hex(16)
        self._close_request = (token, continuation)
        try:
            _send(self.connection, self.send_lock, {'command': 'request_close', 'token': token})
        except (OSError, ValueError):
            self._close_request = None
            return False
        return True

    def accept_event(self, message):
        if message.get('event') == 'menu_closed':
            if message.get('open') == self._open_id:
                self.menu_open = False
            return True
        if message.get('event') == 'renderer_failed' and not self._intentional_close:
            self._close_request = None
            if self.on_failure:
                self.dispatch(self.on_failure)
            return True
        pending = self._close_request
        if pending is None or message.get('token') != pending[0]:
            return False
        if message.get('event') not in {'close_confirmed', 'close_cancelled'}:
            return False
        self._close_request = None
        if message['event'] == 'close_confirmed':
            self.dispatch(pending[1])
        return True

    def hide(self):
        self.menu_open = False
        if self.process is not None and self.process.is_alive():
            with contextlib.suppress(OSError, ValueError):
                _send(self.connection, self.send_lock, {'command': 'hide'})

    def dismiss(self):
        """Close the Pill menu with its exit (0.4.178: the second right-click on the Pill)."""
        self.menu_open = False
        if self.mode == 'menu' and self.process is not None and self.process.is_alive():
            with contextlib.suppress(OSError, ValueError):
                _send(self.connection, self.send_lock, {'command': 'dismiss'})

    def resize(self, bounds):
        if self.mode == 'menu' and self.process is not None and self.process.is_alive():
            _send(self.connection, self.send_lock, {'command':'resize', 'bounds':list(bounds)})

    def close(self):
        self._intentional_close = True
        if self.connection is not None:
            with contextlib.suppress(OSError, ValueError):
                _send(self.connection, self.send_lock, {'command': 'close'})
