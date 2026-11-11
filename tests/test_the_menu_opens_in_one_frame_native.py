"""The Pill menu on the REAL renderer (pywebview + WebView2, the bundled page), on a hidden desktop (0.4.178).

FINDINGS-0478 measured, at 0.4.177: a cold open shown at the app's 288 px guess and resized to the measured 347 px 83 ms
after it appeared; a taskbar app window (WS_EX_APPWINDOW) at every open; a second right-click that hid the menu and
showed it again 7 ms later; no submenu window, so a rest on Speech replaced the whole menu and resized the window. A warm
open was visible 8.8 to 10.4 ms after the right-click (median 9.6 ms, one frame is 16.7 ms).

This proves, in the real renderer:
- the window never changes its rectangle after it first appears, cold or warm;
- a warm open is visible within one frame (median of five at most 20 ms, none past 60 ms: the frame plus room for a
  busy machine);
- it is a tool window (no taskbar button), before and after opens;
- a second open request while it is open closes it, and it stays closed;
- Speech's submenu opens BESIDE the menu, in a window of its own, and the menu does not move or resize;
- Esc in the page closes it.

Run through scripts/run_tests_offscreen.py.
"""
from __future__ import annotations

import copy
import ctypes
import json
import multiprocessing
import queue
import statistics
import sys
import threading
import time
import unittest
from ctypes import wintypes
from unittest.mock import Mock

MENU_TITLE = "Talk DAT!"


def probe_window(connection, commands, html, page, hidden=False, mode="settings", bounds=None, side=None, menu=None):
    """The renderer process: shell_host._run_window, plus a pump that runs the test's scripts in the menu page."""
    user32 = ctypes.windll.user32
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    name = ctypes.create_unicode_buffer(256)
    needed = wintypes.DWORD()
    desktop = user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
    assert user32.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed))
    assert name.value.startswith("talkdat-tests-"), "run through scripts/run_tests_offscreen.py"
    import webview

    from knight_flow.web_shell.shell_host import _run_window

    create, made = webview.create_window, []

    def instrument(*args, **kwargs):
        window = create(*args, **kwargs)
        made.append(window)
        if len(made) == 1:
            def pump():
                while True:
                    script = commands.get()
                    try:
                        window.evaluate_js(script)
                    except Exception:  # noqa: BLE001
                        pass
            window.events.loaded += lambda: threading.Thread(target=pump, daemon=True).start()
        return window

    webview.create_window = instrument
    if menu is None:
        _run_window(connection, html, page, hidden, mode, bounds, side)
    else:
        _run_window(connection, html, page, hidden, mode, bounds, side, menu)


def windows_of(pid):
    """Top-level windows of a process: [(hwnd, visible, (x, y, w, h), exstyle)]."""
    user32 = ctypes.WinDLL("user32")
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
    user32.SetThreadDpiAwarenessContext.argtypes = (wintypes.HANDLE,)
    previous = user32.SetThreadDpiAwarenessContext(wintypes.HANDLE(-4))
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _param):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(hwnd, title, 64)
            if title.value == MENU_TITLE:
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                found.append((int(hwnd), bool(user32.IsWindowVisible(hwnd)),
                              (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
                              int(user32.GetWindowLongPtrW(hwnd, -20)) & 0xFFFFFFFF))
        return True

    try:
        user32.EnumWindows(visit, 0)
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)
    return found


@unittest.skipUnless(sys.platform == "win32", "WebView2 renderer")
class TheMenuOpensInOneFrame(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        from knight_flow.config import DEFAULT_CONFIG
        from knight_flow.overlay import Overlay
        from knight_flow.ui_scale import enable_dpi_awareness
        from knight_flow.web_shell.shell_app import AppShell
        from knight_flow.web_shell.shell_host import ShellController, bundled_html

        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.geometry("200x48+860+980")
        self.root.update()
        self.commands = multiprocessing.get_context("spawn").Queue()
        commands = self.commands

        class Probe(ShellController):
            def open(self, page="general", *, hidden=False, bounds=None, side=None, anchor=None, fresh=None, target=0):
                extra = {key: value for key, value in (("anchor", anchor), ("fresh", fresh), ("target", target)) if value}
                if self.process and self.process.is_alive():
                    return super().open(page, hidden=hidden, bounds=bounds, side=side, **extra)
                context = multiprocessing.get_context("spawn")
                parent, child = context.Pipe(duplex=True)
                self.connection = parent
                menu = self._menu_message(hidden, anchor, fresh, target) if hasattr(self, "_menu_message") else None
                self.process = context.Process(target=probe_window, args=(child, commands, bundled_html(self.assets), page,
                                                                          hidden, self.mode, bounds, side, menu), daemon=True)
                self.process.start()
                child.close()
                threading.Thread(target=self._listen, args=(parent,), daemon=True).start()

        overlay = Mock()
        overlay.root = self.root
        overlay._flag_view = None
        overlay._settings_palette = object.__new__(Overlay)._settings_palette
        source = object.__new__(Overlay)
        rows = source._context_menu_default_rows()
        overlay._context_menu_rows.return_value = rows
        overlay._context_menu_default_rows.return_value = rows
        overlay._context_menu_access_rows.return_value = source._context_menu_default_rows(include_feature_actions=True)
        overlay._context_menu_feature_rows.return_value = source._context_menu_feature_rows()
        overlay.MENU_SAFETY_ZONE_ACTIONS = Overlay.MENU_SAFETY_ZONE_ACTIONS
        overlay._logical_work_area.return_value = (0, 0, 1920, 1080)
        overlay._foreground_target_window.return_value = 0
        overlay.context_menu_target_hwnd = 0
        app = Mock()
        app.config = copy.deepcopy(DEFAULT_CONFIG)
        app.overlay = overlay
        app.pending_update = None
        app.paused = False
        app._cross_thread_calls = queue.Queue()
        self.app = app
        self.shell = AppShell(app, controller_factory=Probe)

    def tearDown(self):
        self.shell.close()
        for controller in (self.shell.menu_controller, self.shell.settings_controller):
            if controller.process:
                controller.process.join(5)
                if controller.process.is_alive():
                    controller.process.terminate()
                    controller.process.join(3)
        self.root.destroy()

    def pump(self, seconds, watch=None):
        """Run the app's 40 ms drain for `seconds`; with `watch`, read the menu's windows every millisecond."""
        timeline, deadline, last_drain = [], time.monotonic() + seconds, 0.0
        pid = self.shell.menu_controller.process.pid if self.shell.menu_controller.process else 0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now - last_drain >= 0.04:
                last_drain = now
                self.root.update()
                while True:
                    try:
                        self.app._cross_thread_calls.get_nowait()()
                    except queue.Empty:
                        break
            if watch is not None and pid:
                timeline.append((now, windows_of(pid)))
            time.sleep(0.001)
        return timeline

    @staticmethod
    def menu_states(timeline):
        """[(t, visible, rect)] of the main menu window (the first window seen visible, else the first listed).

        pywebview starts a hidden window by showing it at opacity 0 and hiding it again (WinForms Opacity makes it a
        layered window for that moment): visible to IsWindowVisible, never to an eye. A layered state is not a frame.
        """
        states, menu = [], None
        seen = lambda visible, style: visible and not style & 0x80000
        for at, found in timeline:
            if menu is None:
                menu = next((hwnd for hwnd, visible, _r, style in found if seen(visible, style)), None)
            entry = next(((seen(visible, style), rect) for hwnd, visible, rect, style in found if hwnd == menu), None)
            if entry is not None:
                states.append((at, entry[0], entry[1]))
        return states, menu

    def open_and_watch(self, seconds=0.7):
        started = time.monotonic()
        self.assertTrue(self.shell.open_menu(960, 1004))
        timeline = self.pump(seconds, watch=True)
        states, menu = self.menu_states(timeline)
        shown = next((at for at, visible, _rect in states if visible), None)
        self.assertIsNotNone(shown, "the menu never appeared")
        after = {rect for at, visible, rect in states if visible and at >= shown}
        return shown - started, after, menu, timeline

    def escape(self):
        self.commands.put("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));true")
        self.pump(0.6)

    def test_the_menu_opens_whole_fast_as_a_tool_window_and_toggles(self):
        # Cold: the renderer starts with the open (no prewarm). Its window appears once, at its final rectangle.
        self.assertTrue(self.shell.open_menu(960, 1004))
        timeline = self.pump(12, watch=True)
        states, menu = self.menu_states(timeline)
        shown = [rect for _at, visible, rect in states if visible]
        self.assertTrue(shown, "the cold menu never appeared")
        self.assertEqual(len(set(shown)), 1, f"the cold menu moved or resized after it appeared: {sorted(set(shown))}")
        self.escape()

        # Warm: five opens, each visible within one frame (with room) and never moved after it appeared.
        delays = []
        for _ in range(5):
            delay, after, menu, timeline = self.open_and_watch()
            delays.append(delay * 1000)
            self.assertEqual(len(after), 1, f"a warm menu moved or resized after it appeared: {sorted(after)}")
            self.escape()
        self.assertLessEqual(statistics.median(delays), 20.0, delays)
        self.assertLessEqual(max(delays), 60.0, delays)

        # A tool window: no taskbar button, no Alt+Tab entry; still so after the opens.
        styles = {style for hwnd, _v, _r, style in windows_of(self.shell.menu_controller.process.pid) if hwnd == menu}
        self.assertEqual(len(styles), 1)
        for style in styles:
            self.assertTrue(style & 0x80, f"WS_EX_TOOLWINDOW missing: {style:#x}")
            self.assertFalse(style & 0x40000, f"WS_EX_APPWINDOW present: {style:#x}")

        # A second right-click (the app asked to open while it is open) closes it, and it stays closed.
        self.assertTrue(self.shell.open_menu(960, 1004))
        self.pump(0.6)
        self.assertTrue(getattr(self.shell, 'menu_is_open', lambda: None)())
        self.assertTrue(self.shell.open_menu(960, 1004))
        timeline = self.pump(0.8, watch=True)
        states, _menu = self.menu_states(timeline)
        self.assertTrue(states and not states[-1][1], "the second right-click left it open")
        self.assertFalse(any(visible for at, visible, _r in states if at > states[0][0] + 0.4),
                         "it came back after closing")
        self.assertFalse(getattr(self.shell, 'menu_is_open', lambda: True)())

        # Speech's submenu opens beside the menu, in its own window; the menu keeps its rectangle.
        _delay, before, menu, _t = self.open_and_watch(0.5)
        self.commands.put("document.querySelector('.menu-row[aria-label=\"Speech\"]').dispatchEvent("
                          "new PointerEvent('pointerenter',{pointerType:'mouse'}));true")
        timeline = self.pump(1.2, watch=True)
        found = timeline[-1][1]
        menu_now = next(rect for hwnd, visible, rect, _s in found if hwnd == menu)
        beside = [rect for hwnd, visible, rect, style in found if hwnd != menu and visible and not style & 0x80000]
        for hwnd, visible, _rect, style in found:
            if hwnd != menu and visible:
                self.assertTrue(style & 0x80 and not style & 0x40000, f"the submenu is not a tool window: {style:#x}")
        self.assertEqual({menu_now}, before, "the menu changed size or place when its submenu opened")
        self.assertEqual(len(beside), 1, f"no submenu window beside the menu: {found}")
        mx, my, mw, mh = menu_now
        sx, sy, sw, sh = beside[0]
        self.assertTrue(mx + mw - 4 * 3 <= sx <= mx + mw or sx + sw <= mx + 4 * 3, (menu_now, beside[0]))
        self.escape()  # the submenu first
        self.escape()  # then the menu
        shown = [rect for hwnd, visible, rect, style in windows_of(self.shell.menu_controller.process.pid)
                 if visible and not style & 0x80000]
        self.assertEqual(shown, [], "Esc left the menu or its submenu open")


if __name__ == "__main__":
    unittest.main()
