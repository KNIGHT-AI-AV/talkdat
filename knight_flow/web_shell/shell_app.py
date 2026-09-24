"""Connect the bundled web shell to existing Talk DAT actions on the Tk thread."""
from __future__ import annotations
import contextlib
import importlib.util
import logging
import os
import copy
from pathlib import Path
import sys
import threading

from .shell_persistence import save_settings_config as save_config
from .shell_backend import ShellBackend
from .shell_host import ShellController
from .shell_models import ModelManager
from .menu_geometry import pill_menu_bounds
from .shell_devices import InputDevices
from .workspace_adapter import Workspaces

log = logging.getLogger(__name__)


def renderer_available():
    return (sys.platform in {'win32', 'darwin'}
            and os.environ.get('TALKDAT_LEGACY_SETTINGS') != '1'
            and importlib.util.find_spec('webview') is not None)


class AppShell:
    def __init__(self, app, *, assets=None, controller_factory=ShellController):
        self.app, self.overlay = app, app.overlay
        self.assets = Path(assets or Path(__file__).with_name('shell_assets'))
        self._legacy = False
        self._last_page = 'general'
        self._last_menu_position = (0, 0)
        self._menu_requested = False
        self._menu_bounds = [0, 0, 380, 600]
        self._menu_work_area = (0, 0, 1920, 1080)
        self._menu_order = copy.deepcopy(app.config.get('overlay', {}).get('menu_order', []))
        self._mac_paste_target = None
        self.devices = InputDevices()
        self.models = ModelManager(app.config, self._capture_busy, serialize_delete=self._serialize_model_delete)
        self.workspaces = Workspaces(app, self._persist, self._capture_busy)
        from .reset_adapter import ResetActions
        self.reset_actions = ResetActions(self)
        self.workspaces.reset_actions = self.reset_actions
        actions = self._actions()
        from knight_flow.smart_formatting import shared as smart_formatting
        from .finish_choice import FinishChoice
        self.finish_choice = FinishChoice(app.choose_finish)
        self.backend = ShellBackend(app.config, self.assets, self._persist, self._applied,
                                    self.overlay._settings_palette, actions=actions, menu=self._menu,
                                    system_preferences=self._preferences, models=self.models,
                                    menu_layout=self._menu_layout, microphones=self.devices.snapshot, workspaces=self.workspaces,
                                    formatting=smart_formatting(app.config), finish_choice=self.finish_choice)
        self.settings_controller = controller_factory(self.assets, app._cross_thread_calls.put,
                                                     self.backend.handle, on_failure=self._settings_failed)
        self.menu_controller = controller_factory(self.assets, app._cross_thread_calls.put,
                                                 self.backend.handle, mode='menu', on_failure=self._menu_failed)

    @staticmethod
    def _preferences():
        from knight_flow.ui.system_prefs import animations_are_switched_off, high_contrast_is_on
        return {'reduce_motion': animations_are_switched_off(), 'high_contrast': high_contrast_is_on()}

    def _persist(self, candidate):
        save_config(candidate)

    def _applied(self):
        from knight_flow.brand_font import apply_app_family
        from knight_flow import net_fence
        from knight_flow.stt_registry import local_only
        apply_app_family(self.app.config)
        self.overlay.apply_runtime_config()
        self.app.save_settings(persist=False)
        local = local_only(self.app.config) or str(self.app.config.get('stt', {}).get('route_mode', 'local')) == 'local'
        net_fence.set_local_only(local)
        self.app._auto_local_sticky = False
        self.overlay.refresh_route_paint()
        order = self.app.config.get('overlay', {}).get('menu_order', [])
        if order != self._menu_order:
            self._menu_order = copy.deepcopy(order)
            push = self.overlay.callbacks.get('push_menu_order')
            if callable(push):
                with contextlib.suppress(Exception):
                    push(list(order))

    def _capture_busy(self):
        if getattr(self.app, "_reset_in_progress", False) is True: return True
        with self.app.lock:
            check = getattr(self.app, '_microphone_check', None)
            meeting = getattr(self.app, 'meeting', None)
            return self.app.session is not None or self.app.session_token is not None or (check is not None and not check.finished.is_set()) or bool(getattr(self.app, "_scribe_busy", lambda: False)()) or (meeting is not None and meeting.running)

    def _serialize_model_delete(self, operation):
        with self.app.lock:
            if self._capture_busy():
                raise ValueError('Finish the current dictation or check before removing a speech model.')
            operation()

    def _actions(self):
        overlay, app = self.overlay, self.app
        actions = {
            'history': lambda: {'page':'history'}, 'scratchpad': lambda: {'page':'scratchpad'},
            'words': lambda: {'page':'words'}, 'translation': lambda: {'page':'translation'},
            'scribe': lambda: {'page':'scribe'}, 'ramble': lambda: {'page':'ramble'}, 'captions': app.toggle_captions,
            'mic_doctor': lambda: {'page':'mic-doctor'}, 'race': lambda: {'page':'speech-check'},
            'recovery': lambda: {'page':'recovery'}, 'stats': lambda: {'page':'stats'},
            'account': overlay.open_account, 'feedback': lambda: {'page':'feedback'},
            'language_request': lambda: {'page':'language-request'},
            'check_updates': app.check_updates, 'diagnostics': self._diagnostics,
            'reset': lambda: {'page':'reset'}, 'backup': self._backup, 'restore_backup': self._restore_backup,
            'restore_backup_confirm': self._restore_backup_confirm,
            'restore_backup_cancel': self._restore_backup_cancel,
            'getting_started': lambda: {'page':'setup'},
            'model_guide': lambda: self.open_settings('model-guide'),
            'local_models': lambda: self.open_settings('models'),
            'menu_order': lambda: self.open_settings('menu-order'),
            'refresh_microphones': lambda: {'microphones':self.devices.refresh()},
            'shortcut_begin': self._shortcut_begin,
            'shortcut_end': lambda: self.app.hotkeys.record_shortcut(False),
            'route:local': lambda: app.set_route_mode('local'),
            'route:byok': lambda: app.set_route_mode('byok'),
            'menu:toggle_intensity': self._toggle_menu_intensity,
        }
        for identifier, _label, _description, _icon in overlay._context_menu_access_rows():
            actions['menu:'+identifier] = lambda identifier=identifier: overlay._activate_context_menu_action(identifier)
        actions['menu:paste_last'] = self._paste_from_menu
        actions['menu:local_models'] = lambda: self.open_settings('models')
        for page in ('history','scratchpad','stats'):
            actions['menu:'+page] = lambda page=page: self.open_settings(page)
        actions['menu:add_words'] = lambda: self.open_settings('words')
        actions['menu:translation'] = lambda: self.open_settings('translation')
        actions['menu:ramble'] = lambda: self.open_settings('ramble')
        actions['menu:scribe'] = lambda: self.open_settings('scribe')
        # Menu destinations open the settings host directly. Going through the
        # legacy popup dispatcher raises/focuses the Pill during the handoff.
        actions['menu:settings'] = lambda: self._open_menu_destination('general')
        actions['menu:help'] = lambda: self._open_menu_destination('help')
        actions['menu:formatting'] = lambda: self._open_menu_destination('formatting')
        for identifier, page in {'settings':'general', 'history':'history', 'stats':'stats',
                                 'scratchpad':'scratchpad', 'add_words':'words', 'translation':'translation',
                                 'ramble':'ramble', 'scribe':'scribe', 'local_models':'models'}.items():
            actions['menu:'+identifier] = lambda page=page: self._open_menu_destination(page)
        from knight_flow.chimes import SOUND_BANK, play_sound_named
        for name in SOUND_BANK:
            actions['sound_preview:'+name] = lambda name=name: play_sound_named(name, enabled=True)
        return actions

    def _shortcut_begin(self):
        from knight_flow.mic_registry import microphone_registry
        if self._capture_busy() or microphone_registry().is_active():
            raise ValueError('Finish recording before changing a shortcut.')
        self.app.hotkeys.record_shortcut(True)

    def _menu(self):
        defaults = [row[0] for row in self.overlay._context_menu_default_rows()]
        result = []
        for identifier, label, description, _icon in self.overlay._context_menu_rows():
            row = {'id':identifier, 'action':'menu:'+identifier, 'label':label, 'description':description,
                   'default_index':defaults.index(identifier), 'fixed':identifier in self.overlay.MENU_SAFETY_ZONE_ACTIONS}
            if identifier == 'more_features':
                row.pop('action')
                row['children'] = [{'action':'menu:'+key, 'label':title, 'description':detail}
                                   for key,title,detail,_ in self.overlay._context_menu_feature_rows()]
            result.append(row)
        return result

    def _menu_layout(self, expanded):
        return {'side':'replace' if expanded else 'closed', 'expanded':expanded}

    def _open_menu_destination(self, page):
        if not self.open_settings(page):
            raise ValueError('Settings could not open. Please try again.')
        return {}

    def _toggle_menu_intensity(self):
        from knight_flow.config import DEFAULT_CONFIG
        current = self.app.config.get('cleanup', {}).get('format_intensity', DEFAULT_CONFIG['cleanup']['format_intensity'])
        result = self.backend.handle('save', {'revision': self.backend.snapshot()['revision'],
                                     'changes': {'cleanup.format_intensity': 'standard' if current == 'executive' else 'executive'}})
        return {'state': result}

    def _pill_anchor(self, x, y):
        root = self.overlay.root
        restore_context = None
        previous_context = None
        try:
            pill = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height())
            if not all(type(value) is int for value in pill):
                raise ValueError('Pill geometry is not ready')
            area = self.overlay._logical_work_area()
            scale = 1.0
            if sys.platform == 'win32':
                import ctypes
                from ctypes import wintypes
                # X-605: a PRIVATE handle. Setting argtypes on the shared
                # ctypes.windll.user32 changed GetMonitorInfoW for the whole
                # app: after the first menu, overlay and monitors.py passed
                # their own MONITORINFO and got ArgumentError, so the Pill lost
                # track of which monitor it was on.
                user32 = ctypes.WinDLL('user32', use_last_error=True)
                # The Pill is system-DPI aware; WebView2 is per-monitor aware.
                # Read both rectangles in physical pixels even on a second monitor.
                restore_context = user32.SetThreadDpiAwarenessContext
                restore_context.argtypes = (wintypes.HANDLE,)
                restore_context.restype = wintypes.HANDLE
                previous_context = restore_context(wintypes.HANDLE(-4))
                user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
                user32.GetAncestor.restype = wintypes.HWND
                hwnd = user32.GetAncestor(root.winfo_id(), 2)
                rect = wintypes.RECT()
                user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    raise OSError('Pill window is unavailable')
                pill = (rect.left, rect.top, rect.right-rect.left, rect.bottom-rect.top)
                class MonitorInfo(ctypes.Structure):
                    _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT), ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
                user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
                user32.MonitorFromWindow.restype = wintypes.HANDLE
                monitor = user32.MonitorFromWindow(hwnd, 2)
                info = MonitorInfo(); info.size = ctypes.sizeof(info)
                user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
                if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    area = (info.work.left, info.work.top, info.work.right, info.work.bottom)
                user32.GetDpiForWindow.argtypes = (wintypes.HWND,)
                scale = (user32.GetDpiForWindow(hwnd) or 96) / 96
                factor = ctypes.c_int()
                get_factor = ctypes.WinDLL('shcore').GetScaleFactorForMonitor
                get_factor.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_int))
                if get_factor(monitor, ctypes.byref(factor)) == 0 and 100 <= factor.value <= 500:
                    scale = factor.value / 100
            return pill, area, scale
        except (AttributeError, OSError, TypeError, ValueError):
            return (int(x), int(y), 0, 0), self.overlay._logical_work_area(), 1.0
        finally:
            if restore_context is not None and previous_context:
                restore_context(previous_context)

    def _own_processes(self):
        processes = {os.getpid()}
        for controller in (self.settings_controller, self.menu_controller):
            pid = getattr(getattr(controller, 'process', None), 'pid', None)
            if type(pid) is int:
                processes.add(pid)
        return processes

    def _target_is_shell(self, hwnd):
        if sys.platform != 'win32' or not hwnd:
            return False
        import ctypes
        from ctypes import wintypes
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return pid.value in self._own_processes()

    def _paste_from_menu(self):
        target = self.overlay.context_menu_target_hwnd
        copy_only = sys.platform == 'win32' and (not target or self._target_is_shell(target))
        if sys.platform == 'darwin':
            copy_only = self._mac_paste_target is None
            if not copy_only:
                try:
                    copy_only = not self._mac_paste_target.activateWithOptions_(0)
                except Exception:
                    copy_only = True
        if copy_only:
            callback = self.overlay.callbacks.get('copy_last')
            if callable(callback):
                callback()
            return {}
        return self.overlay._activate_context_menu_action('paste_last')

    def open_settings(self, destination=None):
        if self._legacy:
            return False
        page = self._last_page
        if isinstance(destination, tuple) and destination:
            section = str(destination[0]).lower()
            page = {'home':'home', 'general':'general', 'speech':'speech', 'formatting':'formatting',
                    'advanced':'privacy', 'appearance':'appearance', 'dictation':'dictation',
                    'words & phrases':'words', 'translation':'translation', 'account':'account'}.get(section, 'general')
            if len(destination) > 1 and str(destination[1]).lower() == 'local models':
                page = 'models'
        elif isinstance(destination, str):
            page = destination
        if getattr(self.app, "_reset_in_progress", False) is True: page = "reset"
        self._last_page = page
        try:
            self.settings_controller.open(page)
            return True
        except Exception as error:
            log.warning('Web settings could not open (%s)', type(error).__name__)
            return False

    def offer_finish_choice(self, chill, executive):
        """X-610: the third-dictation finish choice, on the Writing page."""
        if self._legacy:
            return False
        self.finish_choice.offer(chill, executive)
        if self.open_settings("formatting"):
            return True
        self.finish_choice.pending = None
        return False

    def open_menu(self, x, y):
        if self._legacy:
            return False
        self._last_menu_position = (int(x), int(y))
        self._menu_requested = True
        self.overlay.context_menu_target_hwnd = self.overlay._foreground_target_window()
        if self._target_is_shell(self.overlay.context_menu_target_hwnd):
            self.overlay.context_menu_target_hwnd = 0
        if sys.platform == 'darwin':
            from AppKit import NSWorkspace
            target = NSWorkspace.sharedWorkspace().frontmostApplication()
            self._mac_paste_target = target if target and target.processIdentifier() not in self._own_processes() else None
        pill, self._menu_work_area, scale = self._pill_anchor(x, y)
        self._menu_bounds = pill_menu_bounds(pill, self._menu_work_area, scale)
        try:
            self.menu_controller.open('menu', bounds=self._menu_bounds)
            return True
        except Exception as error:
            log.warning('Web menu could not open (%s)', type(error).__name__)
            return False

    def prewarm(self):
        """Warm the pill menu's renderer, OFF the UI thread.

        X-172b: this is scheduled with root.after(), so it used to spawn a
        frozen Python process while sitting on Tk's own thread -- measured as a
        ~2s freeze of the pill during launch, which is part of what he called
        "massively laggy". Nothing in ShellController.open() touches Tk, and it
        takes its own lock, so a thread is safe here.
        """
        if self._legacy:
            return

        def warm():
            with contextlib.suppress(Exception):
                self.menu_controller.open('menu', hidden=True)

        threading.Thread(target=warm, name='TalkDatPrewarmMenu', daemon=True).start()

    def prewarm_settings(self):
        """Bring the settings renderer up hidden, on 'home'.

        X-172: opening it cold spawns a Python process and parses a ~1.2 MB
        inlined document, and until now nothing prewarmed it -- only the pill
        menu was. That whole cost landed on the launch he was waiting through.
        Warmed, opening Home is a navigate on a renderer that is already up.
        """
        if self._legacy:
            return False
        with contextlib.suppress(Exception):
            self.settings_controller.open('home', hidden=True)
            self._last_page = 'home'
            return True
        return False

    def confirm_exit(self, continuation):
        if getattr(self.app, "_reset_finished", False) is True:
            return False
        return self.settings_controller.confirm_close(continuation)

    def close(self):
        self.workspaces.close()
        self.app.hotkeys.record_shortcut(False)
        self.settings_controller.close()
        self.menu_controller.close()

    def _settings_failed(self):
        self.workspaces.close()
        self._legacy = True
        self.overlay.open_settings()

    def _menu_failed(self):
        self._legacy = True
        if self._menu_requested:
            self.overlay._open_context_menu(*self._last_menu_position)

    def _diagnostics(self):
        from knight_flow.packs import export_diagnostics
        path = export_diagnostics()
        return {'message': 'Diagnostics saved to '+str(path)}

    def _backup(self):
        from tkinter import filedialog
        from knight_flow.packs import export_backup
        from knight_flow.mic_registry import microphone_registry
        if self._capture_busy() or microphone_registry().is_active():
            raise ValueError('Finish the current dictation before backing up your data.')
        target = filedialog.asksaveasfilename(parent=self.overlay.root, defaultextension='.zip',
                                             filetypes=[('ZIP', '*.zip')], initialfile='talk-dat-backup.zip')
        if target:
            export_backup(target)
            return {'message': 'Settings, notes and history backup saved.'}
        return {}

    def _restore_backup_cancel(self):
        self._pending_backup = None
        return {}

    def _restore_backup(self):
        from tkinter import filedialog
        from knight_flow.packs import inspect_backup
        from knight_flow.mic_registry import microphone_registry
        import time
        self._pending_backup = None
        if self._capture_busy() or microphone_registry().is_active():
            raise ValueError('Finish the current dictation before restoring a backup.')
        source = filedialog.askopenfilename(parent=self.overlay.root, filetypes=[('ZIP', '*.zip')])
        if not source:
            return {}
        preview = inspect_backup(source)
        self._pending_backup = (source, preview['digest'], time.monotonic())
        return {'backup_preview': {'files': preview['files'], 'bytes': preview['bytes']}}

    def _restore_backup_confirm(self):
        from knight_flow.packs import restore_backup
        from knight_flow.mic_registry import microphone_registry
        import time
        pending = getattr(self, '_pending_backup', None)
        if pending is None or not 0 <= time.monotonic() - pending[2] < 300:
            self._pending_backup = None
            raise ValueError('Choose the backup again before restoring it.')
        if self._capture_busy() or microphone_registry().is_active():
            raise ValueError('Finish the current dictation before restoring a backup.')
        restored = restore_backup(pending[0], expected_digest=pending[1])
        self._pending_backup = None
        # The confirmation explicitly says Restore and quit. The renderer gets
        # its reply before the existing UI queue performs the normal shutdown.
        self.app._cross_thread_calls.put(lambda: self.app.quit(settings_confirmed=True))
        return {'message': f'Restored {len(restored)} files. Open Talk DAT again to use them.'}
