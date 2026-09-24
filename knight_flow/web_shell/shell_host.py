"""Separate-process native host for bundled Talk DAT chrome.

The existing app owns state and actions. This host exposes only a JSON request
boundary over an inherited pipe. It never opens a control port or loads a URL.
"""
from __future__ import annotations
import base64
import contextlib
import json
import multiprocessing
from pathlib import Path
import secrets
import sys
import threading
import time

MAX_MESSAGE = 1_048_576
#: error_code on an answer the window never got from the app: the link itself
#: failed (no reply, a closed pipe, a send that could not go out). The page
#: says so in the sidebar; an ordinary refusal from the app never carries it.
DISCONNECTED = 'disconnected'


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
                            for name in ('workspaces.js','home.js','notes.js','recovery.js','words.js','translation.js','ramble.js','scribe.js','stats.js','mic-check.js','app-profiles.js','feedback.js','setup.js','reset.js')) + '\n' + javascript
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
    for name in ('workspaces.js','home.js','notes.js','recovery.js','words.js','translation.js','ramble.js','scribe.js','stats.js','mic-check.js','app-profiles.js','feedback.js','setup.js','reset.js'):
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
            self._window.hide()
            return {'ok': True, 'result': None}
        if method == 'close':
            if self._mode == 'menu' and self._close_token is None:
                self._window.hide()
                return {'ok': True, 'result': None}
            self._close_event(True)
            self._force_close = True
            threading.Timer(0.1, self._window.destroy).start()
            return {'ok': True, 'result': None}
        if method not in {'state', 'save', 'action', 'menu_layout', 'workspace'} or not isinstance(payload, dict):
            return {'ok': False, 'error': 'This action is unavailable.'}
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
            if method == 'action' and self._mode == 'menu' and answer and answer.get('ok'):
                if not str(payload.get('name', '')).startswith('route:') and payload.get('name') != 'menu:toggle_intensity':
                    self._window.hide()
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
            self._window.show()

    def _place_menu(self, bounds):
        if not isinstance(bounds, list) or len(bounds) != 4 or not all(type(v) is int for v in bounds):
            return
        x, y, width, height = bounds
        if width <= 0 or height <= 0:
            return
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            # Tk's anchor and monitor rectangles are physical pixels. pywebview's
            # move/resize multiply by monitor DPI, so apply these bounds directly.
            hwnd = int(self._window.native.Handle.ToInt64())
            position = ctypes.WinDLL('user32', use_last_error=True).SetWindowPos  # private: argtypes below
            position.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT)
            position.restype = wintypes.BOOL
            if not position(hwnd, None, x, y, width, height, 0x0014):
                raise OSError('Could not position the Pill menu')
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
                    self._window.hide()
                    continue
                if message.get('command') == 'resize' and self._mode == 'menu':
                    self._place_menu(message.get('bounds'))
                    continue
                if message.get('command') == 'navigate':
                    page = message.get('page', 'general')
                    if isinstance(page, str) and len(page) <= 40 and self._ready.wait(20):
                        if self._mode == 'menu':
                            self._place_menu(message.get('bounds'))
                        self._window.evaluate_js('window.TalkDat.navigate(' + json.dumps(page) + ');true')
                        self._show()
                        if self._mode == 'menu':
                            # Whatever showing did, the menu ends on the Pill.
                            self._place_menu(message.get('bounds'))
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


def _run_window(connection, html, page, hidden=False, mode='settings', bounds=None):
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
        options = {'width': 304, 'height': 552, 'min_size': (240, 200),
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
        api._guard_ready = True
    window.events.before_show += protect_navigation
    window.events.closing += api._closing
    def ready():
        window.evaluate_js('window.TalkDat.navigate(' + json.dumps(page) + ');true')
        if mode == 'menu':
            api._place_menu(bounds)
            if not hidden:
                api._show()
                api._place_menu(bounds)
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

    def open(self, page='general', *, hidden=False, bounds=None):
        with self.open_lock:
            if self.process is not None and self.process.is_alive():
                _send(self.connection, self.send_lock, {'command': 'navigate', 'page': page, 'bounds': bounds})
                return
            self._intentional_close = False
            context = multiprocessing.get_context('spawn')
            parent, child = context.Pipe(duplex=True)
            self.connection = parent
            self.process = context.Process(target=_window_process, args=(child, bundled_html(self.assets), page, hidden, self.mode, bounds),
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
                if type(request_id) is not int or method not in {'state', 'save', 'action', 'menu_layout', 'workspace'} or not isinstance(payload, dict):
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
        if self.process is not None and self.process.is_alive():
            with contextlib.suppress(OSError, ValueError):
                _send(self.connection, self.send_lock, {'command': 'hide'})

    def resize(self, bounds):
        if self.mode == 'menu' and self.process is not None and self.process.is_alive():
            _send(self.connection, self.send_lock, {'command':'resize', 'bounds':list(bounds)})

    def close(self):
        self._intentional_close = True
        if self.connection is not None:
            with contextlib.suppress(OSError, ValueError):
                _send(self.connection, self.send_lock, {'command': 'close'})
