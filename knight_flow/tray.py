from __future__ import annotations

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

    def _pause_label(self, _item: Any = None) -> str:
        return "Resume dictation" if self.paused else "Pause dictation"

    def _update_label(self, _item: Any = None) -> str:
        return f"Install update {self.update_available}" if self.update_available else "Check for updates"

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self._refresh_menu()

    def set_update_available(self, version: str) -> None:
        self.update_available = str(version or "")
        self._refresh_menu()

    def _refresh_menu(self) -> None:
        try:
            if self.icon is not None:
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

            # The redesigned menu. Ordered by how often a hand actually goes
            # there: the verbs first, then the places, then maintenance, and
            # the two you must never hit by accident (Panic, Quit) fenced at
            # the bottom. Rarely-used rooms live under More so the everyday
            # menu stays nine items tall. "Open Talk DAT!" is the DEFAULT
            # item: double-clicking the tray icon runs it without opening the
            # menu at all.
            more = pystray.Menu(
                pystray.MenuItem("Status", lambda _icon, _item: self._call("status")),
                pystray.MenuItem("Stats", lambda _icon, _item: self._call("stats")),
                pystray.MenuItem("Local models", lambda _icon, _item: self._call("local_models")),
                pystray.MenuItem("Hide overlay", lambda _icon, _item: self._call("hide")),
                pystray.MenuItem("Share an idea", lambda _icon, _item: self._call("feature_idea")),
                pystray.MenuItem("Restart Talk DAT!", lambda _icon, _item: self._call("restart")),
            )
            menu = pystray.Menu(
                pystray.MenuItem("Open Talk DAT!", lambda _icon, _item: self._call("show"),
                                 default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Hands-free dictation", lambda _icon, _item: self._call("hands_free")),
                pystray.MenuItem(self._pause_label, lambda _icon, _item: self._call("pause")),
                pystray.MenuItem("Cancel what's recording", lambda _icon, _item: self._call("cancel")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("History", lambda _icon, _item: self._call("history")),
                pystray.MenuItem("Scratchpad", lambda _icon, _item: self._call("scratchpad")),
                pystray.MenuItem("Translate", lambda _icon, _item: self._call("translation")),
                pystray.MenuItem("Settings", lambda _icon, _item: self._call("settings")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(self._update_label, lambda _icon, _item: self._call("install_update")),
                pystray.MenuItem("More", more),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Panic stop", lambda _icon, _item: self._call("panic")),
                # X-630: a fence between the two, so a slip off Panic stop
                # does not land on Quit.
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit Talk DAT!", lambda _icon, _item: self._call("quit")),
            )
            self.icon = pystray.Icon("Talk DAT!", make_tray_image(), "Talk DAT!", menu)
            self.icon.run()
        except Exception:
            return

    def _call(self, name: str) -> None:
        callback = self.callbacks.get(name)
        if not callback:
            return
        # Never run the callback on this (pystray's) thread when a dispatcher
        # exists: the callback is about to touch Tk, and Tk on the wrong
        # thread is the crash this class exists to prevent.
        if self.dispatch is not None:
            self.dispatch(callback)
        else:
            callback()
