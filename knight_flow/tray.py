from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from typing import Any

from .icon import make_tray_image


Callback = Callable[[], None]


class TrayController:
    """The system tray icon and its right-click menu.

    X-284, AND THIS IS A CRASH FIX BEFORE IT IS A REDESIGN. pystray runs its
    own win32 message loop on a background thread, so every menu click used
    to invoke the app callback ON THAT THREAD -- and most tray items open Tk
    windows (Settings, History, Translate...). Tk is single-threaded;
    touching it from pystray's thread is the access-violation in
    crash-traceback.log (tray thread live in `pystray\\_win32.py _mainloop`
    while the fault hit the Tk mainloop) and the freeze-and-abort class
    reported on 2026-08-20. The tell that this was already half-known: the
    `feature_idea` callback alone was wrapped in `root.after(0, ...)` at the
    call site. One patched menu item is a symptom log, not a fix -- the
    marshalling belongs HERE, once, for every item.

    `dispatch` is that marshal: the app injects `root.after(0, fn)` and every
    click crosses to the Tk thread before any callback runs. Without a
    dispatcher (tests, headless), calls stay direct.
    """

    def __init__(self, callbacks: dict[str, Callback],
                 dispatch: Callable[[Callback], None] | None = None) -> None:
        self.callbacks = callbacks
        self.dispatch = dispatch
        self.icon: Any = None
        self.thread: threading.Thread | None = None
        self.paused = False
        self.update_available = ""
        # Show the Pill's check: the person's own choice (Show the Pill, Open Talk DAT!). The app tells the tray.
        self.pill_shown = True

    # 0.4.177 IA phase 2 (R6): the options are check items whose labels never
    # flip. Pause listening used to read "Pause dictation" or "Resume dictation".
    def _is_paused(self, _item: Any = None) -> bool:
        return self.paused

    def _pill_is_shown(self, _item: Any = None) -> bool:
        return self.pill_shown

    def _update_label(self, _item: Any = None) -> str:
        return f"Install update {self.update_available}"

    def _update_waiting(self, _item: Any = None) -> bool:
        # Shown only while an update waits: Check for updates is on Home and Help.
        return bool(self.update_available)

    def status_text(self) -> str:
        """The icon's tooltip (R18: the icon names the state). "More > Status" is gone; the full Status is on Help."""
        return "Talk DAT!: paused" if self.paused else "Talk DAT!: ready"

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self._refresh_menu()

    def set_pill_shown(self, shown: bool) -> None:
        self.pill_shown = bool(shown)
        self._refresh_menu()

    def set_update_available(self, version: str) -> None:
        self.update_available = str(version or "")
        self._refresh_menu()

    def _refresh_menu(self) -> None:
        try:
            if self.icon is not None:
                self.icon.title = self.status_text()
                self.icon.update_menu()
        except Exception:
            pass

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, name="TalkDatTray", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass

    def _run(self) -> None:
        try:
            import pystray

            # 0.4.177 IA phase 2 (the owner, 2026-11-06: an industry-standard
            # menu; IA-SCHEMATIC.md section 2, rules R14-R18). Five groups:
            # Open (the DEFAULT item: a click on the icon runs it) and the
            # dictation verbs; the places; the Pill and the app's own places;
            # the update, only while one waits; then the lifecycle, with Quit
            # fenced last. The More submenu is dissolved (R5: no catch-all):
            # Status is the icon's tooltip and Help's Status panel, Stats and
            # Local models are Settings pages, Share an idea is on Help, Hide
            # overlay became Show the Pill. Cancel what's recording stays
            # visible at all times: the tray holds no recording state (a row
            # shown only while recording is phase 4 if wanted).
            menu = pystray.Menu(
                pystray.MenuItem("Open Talk DAT!", lambda _icon, _item: self._call("show"),
                                 default=True),
                pystray.MenuItem("Start hands-free dictation", lambda _icon, _item: self._call("hands_free")),
                pystray.MenuItem("Pause listening", lambda _icon, _item: self._call("pause"),
                                 checked=self._is_paused),
                pystray.MenuItem("Cancel what's recording", lambda _icon, _item: self._call("cancel")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("History", lambda _icon, _item: self._call("history")),
                pystray.MenuItem("Scratchpad", lambda _icon, _item: self._call("scratchpad")),
                pystray.MenuItem("Translate", lambda _icon, _item: self._call("translation")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Show the Pill", lambda _icon, _item: self._call("toggle_pill"),
                                 checked=self._pill_is_shown),
                pystray.MenuItem("Settings", lambda _icon, _item: self._call("settings")),
                pystray.MenuItem("Help", lambda _icon, _item: self._call("help")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(self._update_label, lambda _icon, _item: self._call("install_update"),
                                 visible=self._update_waiting),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Restart Talk DAT!", lambda _icon, _item: self._call("restart")),
                pystray.MenuItem("Panic stop", lambda _icon, _item: self._call("panic")),
                # X-630: a fence between the two, so a slip off Panic stop
                # does not land on Quit.
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit Talk DAT!", lambda _icon, _item: self._call("quit", source="tray")),
            )
            self.icon = pystray.Icon("Talk DAT!", make_tray_image(), self.status_text(), menu)
            self.icon.run()
        except Exception:
            return

    def _call(self, name: str, **kwargs: Any) -> None:
        callback = self.callbacks.get(name)
        if not callback:
            return
        if kwargs:
            # Quit says it came from the tray (2026-10-28); the dispatcher
            # still receives one callable that takes no arguments.
            callback = functools.partial(callback, **kwargs)
        # Never run the callback on this (pystray's) thread when a dispatcher
        # exists: the callback is about to touch Tk, and Tk on the wrong
        # thread is the crash this class exists to prevent.
        if self.dispatch is not None:
            self.dispatch(callback)
        else:
            callback()
