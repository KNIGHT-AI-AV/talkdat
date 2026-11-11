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
from .menu_geometry import menu_height, menu_width, pill_menu_bounds, pill_menu_side
from .. import menu_anchor
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
        # 0.4.177 IA phase 3: the width the page measured the menu needs (CSS px at 100%); None until it has.
        self._menu_width = None
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
        from .update_offer import UpdateOffer
        self.finish_choice = FinishChoice(app.choose_finish)
        self.update_offer = UpdateOffer(
            notify=lambda kind, message: app._cross_thread_calls.put(
                lambda: self.overlay.set_state(kind, message, "")),
            open_url=self._open_release_page, count_dismissal=self._count_update_dismissal)
        self.backend = ShellBackend(app.config, self.assets, self._persist, self._applied,
                                    self.overlay._settings_palette, actions=actions, menu=self._menu, update=self._update_state, menu_fit=self._fit_menu,
                                    commands=self._commands,
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
        from knight_flow.stt_registry import local_only, route_mode
        apply_app_family(self.app.config)
        self.overlay.apply_runtime_config()
        self.app.save_settings(persist=False)
        # X-338: the rule the launch and the Pill's switch apply. route_mode() reads a legacy "auto" (or a "cloud"
        # with no key) as Local; comparing the saved string lowered the fence for them.
        local = local_only(self.app.config) or route_mode(self.app.config) == 'local'
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
            'status_report': self._status_report, 'panic': app.panic_stop,
            'open_permissions': self._open_permissions,
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
            # 2026-10-09: the menu's update row installs the release the last
            # check found (pending_update); it never starts a new network check.
            'menu:install_update': self._install_from_menu,
            # 0.4.177 IA phase 3: what the command palette runs (AppShell._commands). It lives in Talk DAT's own
            # window, so nothing first gives the focus back to the window the Pill's menu opened over: the app runs
            # each as the tray does. A paste aimed at Talk DAT's own window copies, the Pill menu's rule there
            # (_paste_from_menu). Restart and Quit asked twice in the page before they get here.
            'palette:hands_free': lambda: app.toggle_hands_free(), 'palette:cancel': lambda: app.cancel(),
            'palette:paste_last': lambda: app.copy_last(), 'palette:copy_last': lambda: app.copy_last(),
            'palette:pause': lambda: app.toggle_pause(), 'palette:toggle_pill': lambda: app.toggle_pill(),
            'palette:restart': lambda: app.restart(), 'palette:quit': lambda: app.quit(source='palette'),
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
        # 0.4.177 IA phase 2: Speech's submenu ends on its settings row, as Writing style's does.
        actions['menu:speech_settings'] = lambda: self._open_menu_destination('speech')
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
        """The Pill menu's rows for the page: the overlay's one row list (the Tk menu draws the same list).

        0.4.177 IA phase 2 (IA-SCHEMATIC.md section 1): each row names its group, so the page draws the daily block
        (the person's Menu layout order; 'fixed' False) and then the fixed groups behind separators: the switches
        (Speech and Writing style, which the page draws from the app's state, then Pause listening), the places and
        the lifecycle pair. The main action is the 'default' row and shows the live binding of its 'shortcut'; Pause
        listening is a 'check' row, 'checked' while the app is paused. The Tk menu's own update row is left out: the
        page draws its update row from the release the last check found.
        """
        from knight_flow.overlay import Overlay
        defaults = [row[0] for row in self.overlay._context_menu_default_rows()]
        paused = getattr(self.app, 'paused', False) is True
        result = []
        for identifier, label, description, _icon in self.overlay._context_menu_rows():
            group = Overlay.menu_row_group(identifier)
            if group == 'status':
                continue
            row = {'id':identifier, 'action':'menu:'+identifier, 'label':label, 'description':description,
                   'default_index':defaults.index(identifier), 'fixed':group != 'daily', 'group':group}
            if identifier == 'more_features':
                row.pop('action')
                row['children'] = [{'action':'menu:'+key, 'label':title, 'description':detail}
                                   for key,title,detail,_ in self.overlay._context_menu_feature_rows()]
            if identifier == 'hands_free':
                row.update(default=True, shortcut='hands_free')
                # 0.4.178: its live binding rides with the row, so an open never shows a binding the menu page last
                # read from a whole-state answer it no longer asks for at each open (R13: the saved binding).
                config = getattr(self.app, 'config', None)
                keys = (config.get('hotkeys') or {}).get('hands_free') if isinstance(config, dict) else None
                if isinstance(keys, list):
                    row['keys'] = copy.deepcopy(keys)
            if identifier == 'pause':
                row.update(check=True, checked=paused)
            result.append(row)
        return result

    #: 0.4.177 IA phase 3: the palette's run for a Pill row the Pill's menu runs through the overlay (the rest run
    #: the action named by their id, which opens their page in this window), and the hotkey whose live binding each
    #: row shows (R13; a row with none shows none).
    COMMAND_RUNS = {'hands_free': 'palette:hands_free', 'paste_last': 'palette:paste_last', 'pause': 'palette:pause',
                    'restart_app': 'palette:restart', 'quit_app': 'palette:quit'}
    COMMAND_SHORTCUTS = {'hands_free': 'hands_free', 'cancel': 'cancel', 'paste_last': 'paste_last',
                         'copy_last': 'copy_last', 'scratchpad': 'scratchpad'}

    def _commands(self):
        """The command palette's actions (0.4.177 IA phase 3: IA-SCHEMATIC.md section 4, rules R32, R33 and R8).

        In the Pill's daily order: the daily block in the person's Menu layout order, the main action with Cancel
        what's recording beside it, Paste last with Copy last, and Tools' four rows in place of Tools; then the
        switches (the speech route and the writing style as choices, Pause listening and Show the Pill as check
        rows), Check for updates, and Restart and Quit, which ask twice. One name for each action
        (tests/test_one_name_for_each_place.py): a Pill row's label is read from the Pill's own row list;
        Cancel what's recording and Show the Pill are the tray's words, the four choices the Pill submenus' and
        Check for updates Home's and Help's. The checks read the app's state as the Pill's menu does.
        """
        from knight_flow.config import DEFAULT_CONFIG
        from knight_flow.overlay import Overlay
        config = getattr(self.app, 'config', None)
        config = config if isinstance(config, dict) else {}
        rows = [row for row in self.overlay._context_menu_rows() if Overlay.menu_row_group(row[0]) != 'status']
        labels = {identifier: label for identifier, label, _description, _icon in rows}
        result = []

        def add(identifier, label, action, **extra):
            row = {'id': identifier, 'label': label, 'action': action, **extra}
            if identifier in AppShell.COMMAND_SHORTCUTS:
                row['shortcut'] = AppShell.COMMAND_SHORTCUTS[identifier]
            result.append(row)

        for identifier, label, _description, _icon in rows:
            if Overlay.menu_row_group(identifier) != 'daily':
                continue
            if identifier == 'more_features':
                for key, title, _detail, _draw in self.overlay._context_menu_feature_rows():
                    add(key, title, key)
                continue
            add(identifier, label, AppShell.COMMAND_RUNS.get(identifier, identifier))
            if identifier == 'hands_free':
                add('cancel', "Cancel what's recording", 'palette:cancel')
            elif identifier == 'paste_last':
                add('copy_last', 'Copy last transcript', 'palette:copy_last')
        route = str((config.get('stt') or {}).get('route_mode', 'local'))
        intensity = str((config.get('cleanup') or {}).get('format_intensity', DEFAULT_CONFIG['cleanup']['format_intensity']))
        local, executive = route == 'local', intensity == 'executive'
        add('route_local', 'Local speech', 'route:local', choice=True, checked=local, group='Speech')
        add('route_byok', 'Your key', 'route:byok', choice=True, checked=not local, group='Speech')
        add('style_chill', 'Chill', 'menu:toggle_intensity', choice=True, checked=not executive, group='Writing style')
        add('style_executive', 'Executive', 'menu:toggle_intensity', choice=True, checked=executive, group='Writing style')
        # Only rows the Pill has: a row list without one (a test double's) leaves it out here too.
        if 'pause' in labels:
            add('pause', labels['pause'], AppShell.COMMAND_RUNS['pause'], check=True,
                checked=getattr(self.app, 'paused', False) is True)
        add('toggle_pill', 'Show the Pill', 'palette:toggle_pill', check=True,
            checked=getattr(self.app, '_pill_hidden', False) is not True)
        add('check_updates', 'Check for updates', 'check_updates')
        for identifier in Overlay.MENU_SAFETY_ZONE_ACTIONS:
            if identifier in labels:
                add(identifier, labels[identifier], AppShell.COMMAND_RUNS[identifier], confirm=True)
        return result

    def _menu_content_height(self):
        """Home's height at 100%: the menu opens on Home, and every other view then asks
        for its own height (menu_fit), so no view sits in a window sized for another."""
        rows = self._menu()
        update = self._update_state()
        # 0.4.177 IA phase 2: every row, plus the Speech and Writing style rows the page adds to the switches; each
        # fixed group the page draws sits behind one separator (the switches always do).
        groups = {'switches'} | {row.get('group') for row in rows if row.get('fixed')}
        return menu_height(len(rows) + 2, update=bool(update and not update.get('skipped')), separators=len(groups))

    def _install_from_menu(self):
        """The update row's Install, in one click (2026-10-09).

        The release goes to Home exactly as before (App.install_or_check_update offers
        pending_update there), and its install starts at once through the same
        verified path Home's own Install button uses, so Home shows the download and
        the checks. A release that cannot be verified stays on Home, blocked, with the
        reason. With nothing pending the row was stale: no check is started from here,
        and the Pill says nothing is waiting.
        """
        if self._update_state() is None:
            # Review B9 (2026-10-10): the menu closes on every action, so an answer
            # returned to the page was never seen. The Pill says it instead.
            self.app._cross_thread_calls.put(
                lambda: self.overlay.set_state('captured', 'No update is waiting.', ''))
            return {}
        self.app.install_or_check_update()
        offer = self.update_offer.snapshot()
        if offer is not None and offer.get('phase') == 'ready':
            self.update_offer.act('install')
        return {}

    def _fit_menu(self, height, width=None):
        """The menu window takes the height of the view the page shows (2026-10-09).

        It opened at Home's height, and a submenu replaces Home in place, so App
        controls (five rows) sat in a window sized for nine: the half-empty panel the
        owner called "misshapen". The page asks for each view's height; the window
        keeps the edge that faces the Pill (pill_menu_bounds puts it there) and moves
        the far one, so the content, anchored to that edge, never jumps.

        0.4.177 IA phase 3 (PHASE2-REVIEW-0477.md decision 1): and as wide as its widest row needs, which the page
        measures too (288 to 360 px). The width is kept, so a fit that sends only a height keeps it, and the next
        open starts at it: the hidden prewarm draws the menu before any Pill asked for it.
        """
        if width is not None:
            self._menu_width = menu_width(width)
        pill = getattr(self, '_menu_pill', None)
        if pill is None:
            return {'bounds': list(self._menu_bounds)}
        bounds = pill_menu_bounds(pill, self._menu_work_area, self._menu_scale, height=height,
                                  side=getattr(self, '_menu_side', None), width=getattr(self, '_menu_width', None))
        if bounds != list(self._menu_bounds):
            self._menu_bounds = bounds
            self.menu_controller.resize(bounds)
        return {'bounds': list(bounds)}

    def _update_state(self):
        """What the Pill menu says about updates, from the last check only (2026-10-09).

        `pending_update` is set by app.check_updates only after it confirmed a newer
        release and cleared when it finds none, so the menu never claims an update
        the check did not find, and reading it costs no network call.
        """
        info = getattr(self.app, 'pending_update', None)
        version = getattr(info, 'latest_version', '') if info is not None else ''
        if not isinstance(version, str) or not version.strip():
            return None
        version = version.strip()
        updates = self.app.config.get('updates', {}) if isinstance(self.app.config, dict) else {}
        return {'version': version, 'required': bool(getattr(info, 'forced', False)),
                'skipped': version == str(updates.get('skip_version', '') or '')}

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
        """The Pill's own rectangle, its monitor's work area and that monitor's scale.

        Windows: physical pixels read from the Pill's window (knight_flow.menu_anchor),
        measuring the Pill and not a message's envelope around it (X-742). If Windows
        cannot answer, the monitor under the pointer: never the foreground app's
        monitor, which is how the menu ended up on the wrong screen (2026-10-09).
        """
        root = self.overlay.root
        view = getattr(self.overlay, '_flag_view', None)
        if sys.platform == 'win32':
            try:
                reading = menu_anchor.read_pill_window(root)
                body = menu_anchor.pill_body_in_window(
                    reading.rect, getattr(view, 'envelope', None), getattr(view, 'pill', None))
                return body, reading.work, reading.scale
            except (AttributeError, OSError, TypeError, ValueError):
                point = menu_anchor.cursor_position(physical=True) or (int(x), int(y))
                found = menu_anchor.work_area_at_point(*point, physical=True)
                if found is not None:
                    return (int(point[0]), int(point[1]), 0, 0), found[0], found[1]
                return (int(x), int(y), 0, 0), self.overlay._logical_work_area(), 1.0
        try:
            pill = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height())
            if not all(type(value) is int for value in pill):
                raise ValueError('Pill geometry is not ready')
            return pill, self.overlay._logical_work_area(), 1.0
        except (AttributeError, TypeError, ValueError):
            return (int(x), int(y), 0, 0), self.overlay._logical_work_area(), 1.0

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

    def offer_update(self, data, install, skip):
        """X-611: a release ready to install, shown on Home."""
        if self._legacy:
            return False
        if not self.update_offer.offer(data, install, skip):
            # An install is already running there: bring it forward.
            return self.open_settings("home")
        if self.open_settings("home"):
            return True
        self.update_offer.withdraw()  # Home did not open: the Tk window takes it
        return False

    @staticmethod
    def _open_release_page(url):
        import webbrowser
        webbrowser.open(url)

    def _count_update_dismissal(self):
        # X-47: the Update window's Later spent one of three reminder strikes.
        updates = self.app.config.setdefault("updates", {})
        updates["dialog_dismissals"] = int(updates.get("dialog_dismissals", 0) or 0) + 1
        self.app.save_settings()

    def offer_finish_choice(self, chill, executive):
        """X-610: the third-dictation finish choice, on the Writing page."""
        if self._legacy:
            return False
        self.finish_choice.offer(chill, executive)
        if self.open_settings("formatting"):
            return True
        self.finish_choice.pending = None
        return False

    def menu_is_open(self):
        """Whether the Pill menu is showing (0.4.178): the overlay asks before a right-click opens it."""
        return not self._legacy and getattr(self.menu_controller, 'menu_open', False) is True

    def open_menu(self, x, y):
        if self._legacy:
            return False
        if self.menu_is_open():
            # 0.4.178: a second right-click on the Pill closes its menu, as a second click on a menu's button does;
            # before, it hid the menu and showed it again 7 ms later (FINDINGS-0478 section 2.4).
            self.menu_controller.dismiss()
            return True
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
        self._menu_pill, self._menu_scale = pill, scale
        home = self._menu_content_height()
        # The side is chosen once, here, for Home; every view keeps it (review B2).
        self._menu_side = pill_menu_side(pill, self._menu_work_area, scale, height=home)
        self._menu_bounds = pill_menu_bounds(pill, self._menu_work_area, scale, height=home, side=self._menu_side,
                                             width=self._menu_width)
        # 0.4.178 (FINDINGS-0478 section 2): the open carries the Pill (the renderer sizes the window from what the
        # page measures, before the first frame), what the menu draws (no whole-state answer, 86 ms on this thread,
        # and no redraw 130 to 260 ms after it appeared), and the window it opened over (the focus goes back to it).
        anchor = {'pill': [int(value) for value in pill], 'work': [int(value) for value in self._menu_work_area],
                  'scale': float(scale), 'side': self._menu_side}
        fresh = None
        with contextlib.suppress(Exception):
            fresh = self.backend.menu_state()
        target = self.overlay.context_menu_target_hwnd
        try:
            self.menu_controller.open('menu', bounds=self._menu_bounds, side=self._menu_side, anchor=anchor,
                                      fresh=fresh, target=target if type(target) is int and target > 0 else 0)
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

    def _status_report(self):
        """X-613: the tray's Status window, as data for the Help page."""
        from knight_flow.mic_registry import microphone_registry
        data = self.app.status_snapshot()
        data = data if isinstance(data, dict) else {}

        def value(item):
            if isinstance(item, bool):
                return 'Yes' if item else 'No'
            return str(item) if item not in (None, '') else 'None'

        rows = [[str(key).replace('_', ' ').capitalize(), value(item)] for key, item in sorted(data.items())]
        microphone = list(microphone_registry().describe())
        microphone.append('Panic stop (the button below, or the tray menu) releases every one of them.')
        return {'status_report': {'rows': rows, 'microphone': microphone, 'permissions': self._permissions()}}

    @staticmethod
    def _permissions():
        """X-613 on a Mac: the macOS permissions checklist the Tk Status window kept
        (X-23). These grants are bound to the app's signature, so replacing the
        app clears them, and the symptom is never an error: dictation records
        silence or delivers nothing. None anywhere but macOS, and None on a build
        without the Mac helpers (main; mac-port carries them)."""
        try:
            from knight_flow import mac_support
            from knight_flow.onboarding import permission_is_satisfied, permission_pages, permissions_outstanding
        except ImportError:
            return None
        if not getattr(mac_support, 'IS_MAC', False):
            return None
        report = mac_support.permission_report()
        missing = permissions_outstanding(report)
        rows = []
        for page in permission_pages():
            state = report.get(page.key, 'unknown')
            rows.append({'label': page.label, 'state': state, 'granted': permission_is_satisfied(state),
                         'breaks': page.breaks if page.key in missing else '', 'where': page.settings_path})
        return {'rows': rows, 'missing': len(missing)}

    def _open_permissions(self):
        """Open System Settings on the first missing permission (the Tk window's button)."""
        opener = getattr(self.overlay, '_open_permission_settings_for_first_gap', None)
        if not callable(opener):
            raise ValueError('There are no system permissions to set on this computer.')
        opener(lambda: None)
        return {'message': 'System Settings is open on the first permission Talk DAT! still needs.'}

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
        self.app._cross_thread_calls.put(lambda: self.app.quit(settings_confirmed=True, source="restore"))
        return {'message': f'Restored {len(restored)} files. Open Talk DAT again to use them.'}
