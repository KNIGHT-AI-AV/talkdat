"""The keyboard and mouse hooks, in a small process of their own (field report 2026-11-05).

A low-level hook's callback runs in the process that installed it, and Windows holds every key and
mouse event on the machine until that callback returns. In the app's own process the callback needs
the interpreter, and loading the speech model locks every other thread out of it for seconds: measured
2026-11-05, 7.1 s of a 7.4 s load, 5.6 s in one stretch. That was the whole PC freezing while Talk DAT
started. Here the hooks run in a process that does nothing else. Each callback only hands a name to a
queue and returns; a sender thread puts the names on the pipe, and the app reads them in order whenever
it can. Windows never waits for the app.
"""
from __future__ import annotations

import contextlib
import importlib
import logging
import multiprocessing
import queue
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


def serve(connection: Any, mouse_on: bool, listeners: str = "pynput") -> None:
    """The helper process: hooks in, key names out, until the app says stop or goes away.

    `listeners` names the package whose keyboard and mouse modules supply the Listener classes.
    """
    keyboard = importlib.import_module(listeners + ".keyboard")
    mouse = importlib.import_module(listeners + ".mouse")
    from .hotkeys import key_name, mouse_name

    outbox: "queue.SimpleQueue[tuple[str, str] | None]" = queue.SimpleQueue()

    # Each callback runs inside Windows' wait for this hook: it names the key and returns.
    # Nothing may escape it, since an exception ends pynput's listener thread.
    def on_press(key: Any) -> None:
        with contextlib.suppress(Exception):
            name = key_name(key)
            if name:
                outbox.put(("down", name))

    def on_release(key: Any) -> None:
        with contextlib.suppress(Exception):
            name = key_name(key)
            if name:
                outbox.put(("up", name))

    def on_click(_x: int, _y: int, button: Any, pressed: bool) -> None:
        with contextlib.suppress(Exception):
            name = mouse_name(button)
            if name:
                outbox.put(("down" if pressed else "up", name))

    def send_all() -> None:
        while True:
            item = outbox.get()
            if item is None:
                return
            try:
                connection.send(item)
            except (OSError, EOFError):
                return

    sender = threading.Thread(target=send_all, name="TalkDatInputSend", daemon=True)
    sender.start()
    keys = keyboard.Listener(on_press=on_press, on_release=on_release)
    keys.start()
    buttons: Any = None

    def set_mouse(on: bool) -> None:
        nonlocal buttons
        if on and buttons is None:
            buttons = mouse.Listener(on_click=on_click)
            buttons.start()
        elif not on and buttons is not None:
            buttons.stop()
            buttons = None

    set_mouse(mouse_on)
    outbox.put(("ready", ""))
    try:
        while True:
            try:
                command = connection.recv()
            except (EOFError, OSError):
                break
            if command == "stop":
                break
            if command in ("mouse_on", "mouse_off"):
                set_mouse(command == "mouse_on")
    finally:
        keys.stop()
        set_mouse(False)
        outbox.put(None)
        sender.join(timeout=1.0)


class InputHelper:
    """The app's end of the helper process.

    on_event(kind, name) runs on a reader thread for each "down"/"up". on_lost() runs once if the
    helper ends without being asked to, so the caller can put the hooks back in its own process.
    """

    def __init__(self, on_event: Callable[[str, str], None], on_lost: Callable[[], None], *,
                 listeners: str = "pynput") -> None:
        self.on_event = on_event
        self.on_lost = on_lost
        self.listeners = listeners
        self.mouse = False
        self.ready = threading.Event()
        self.process: Any = None
        self.connection: Any = None
        self._stopping = False
        self._send_lock = threading.Lock()

    def start(self, *, mouse: bool) -> None:
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe(duplex=True)
        self.mouse = bool(mouse)
        # A daemon child ends with the app; if the app is killed, the child's recv() sees EOF and unhooks.
        self.process = context.Process(target=serve, args=(child, self.mouse, self.listeners),
                                       name="TalkDatInput", daemon=True)
        self.process.start()
        child.close()
        threading.Thread(target=self._read, name="TalkDatInputRead", daemon=True).start()

    def _read(self) -> None:
        try:
            while True:
                kind, name = self.connection.recv()
                if kind == "ready":
                    self.ready.set()
                    log.info("keyboard hook running in its own process (pid %s)", self.process.pid)
                    continue
                self.on_event(kind, name)
        except (EOFError, OSError):
            pass
        except Exception:
            log.exception("reading the input helper failed")
        if not self._stopping:
            self.on_lost()

    def set_mouse(self, on: bool) -> None:
        self.mouse = bool(on)
        self._send("mouse_on" if on else "mouse_off")

    def _send(self, message: str) -> None:
        with self._send_lock:
            try:
                self.connection.send(message)
            except (OSError, EOFError, AttributeError):
                pass  # the reader reports a lost helper

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self._send("stop")
        if self.process is not None:
            self.process.join(timeout=2.0)
            if self.process.is_alive():
                self.process.terminate()  # our own child, by its own handle
                self.process.join(timeout=2.0)
        with contextlib.suppress(Exception):
            self.connection.close()
