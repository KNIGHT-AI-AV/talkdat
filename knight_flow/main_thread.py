"""Marshal work onto the Tk thread safely, from any thread.

`root.after(0, callback)` is the idiom this codebase uses to get back onto the
UI thread from a worker -- 58 call sites of it. It is also not safe to call from
a worker, which is not widely known and which tkinter does nothing to prevent:
`Misc.after` runs `tk.createcommand` and `tk.call` against the interpreter, on
the calling thread. Doing that from a worker corrupts the saved Python thread
state.

The corruption is silent. The abort happens later, on the main thread, inside
whatever timer or binding happens to run next:

    PyEval_RestoreThread <- PythonCmd <- TclNRRunCallbacks <- Tk_BindEvent

That signature accounted for 21 of 25 crash reports on this Mac, roughly one
every fifteen minutes from the moment the app was installed, and none of them
named the thread responsible -- the stack only ever shows the innocent callback
that ran afterwards. It was found by wrapping `tkapp.call` and recording which
thread each call came from.

So `after` is replaced on the root with a version that keeps the real behaviour
on the main thread and routes everything else through a queue this module drains
from a main-thread timer. Fixing it here rather than at each of the 58 call
sites is deliberate: the bug is not that any one of them is written wrongly --
they all look correct and match every tutorial -- so a sweep would leave the
next one to be written just as broken.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)

# How often the main thread looks for work posted by other threads. Small enough
# that a status message still feels immediate, large enough to be free.
POLL_MS = 25

# Returned in place of a Tcl timer id for work posted from another thread, where
# no real id can be obtained. after_cancel tolerates it: cancelling a callback
# that is already queued to run immediately has no meaning anyway.
CROSS_THREAD_TOKEN = "main_thread_post"

_main = threading.main_thread()
_queue: queue.SimpleQueue = queue.SimpleQueue()
_root: Any = None
_pump: str | None = None
# X-141: the Tcl command name for _drain, registered ONCE per root. The
# previous code called root.register(_drain) on EVERY pump pass -- and
# register() mints a brand-new Tcl command each call, appended forever to
# root._tclCommands. At 40 passes a second that list reached hundreds of
# thousands of entries within hours, and tkinter cleans every expired
# after-callback with a LINEAR list.remove() over it -- the founder's
# "Talk DAT! is using 12% CPU" was one full core spent scanning that list,
# growing with uptime. One command, reused, keeps the list flat.
_drain_command: str | None = None


def on_main_thread() -> bool:
    return threading.current_thread() is _main


def post(callback: Callable[[], Any]) -> None:
    """Run `callback` on the Tk thread. Safe to call from anywhere."""
    _queue.put(callback)


def bind(root: Any) -> None:
    """Take over `after` on this root and start draining the queue.

    Idempotent, and safe to call again for a new root: the tests build many
    overlays against one shared root, and macOS cannot create a second root at
    all, so rebinding has to be harmless rather than merely unlikely.
    """
    global _root, _pump, _drain_command
    if root is None:
        return
    if root is not _root:
        # A pending Tcl ``after`` outlives ``destroy .``.  If its registered
        # Python command is then retired by tkinter, the next event pass emits
        # ``invalid command name ..._drain``.  Retire the old interpreter's
        # pump before handing ownership to a new root.
        if _root is not None:
            stop(_root)
        # A new root is a new Tcl interpreter; the old command name means
        # nothing there. Register fresh on first pump against this root.
        _drain_command = None
    _root = root
    if getattr(root, "_main_thread_after_installed", False):
        _schedule_pump()
        return

    original = root.after

    def guarded_after(ms: Any = 0, func: Callable[..., Any] | None = None, *args: Any) -> Any:
        if func is None or on_main_thread():
            return original(ms, func, *args) if func is not None else original(ms)
        # A worker asked for UI work. The delay is dropped on purpose: every
        # cross-thread use of this in the codebase passes 0, meaning "as soon as
        # you can", and honouring a real delay would need a Tcl timer, which is
        # the very thing that cannot be created from here.
        _queue.put(lambda: func(*args))
        return CROSS_THREAD_TOKEN

    original_cancel = root.after_cancel

    def guarded_cancel(identifier: Any) -> Any:
        if identifier == CROSS_THREAD_TOKEN or not on_main_thread():
            return None
        return original_cancel(identifier)

    root.after = guarded_after  # type: ignore[method-assign]
    root.after_cancel = guarded_cancel  # type: ignore[method-assign]
    root._main_thread_after_installed = True

    # ``Tk.destroy`` deletes every registered Python Tcl command, but Tcl does
    # not cancel the corresponding timers first.  Put the pump's teardown in
    # the same lifecycle path as the root so raw test roots and utility hosts
    # receive the same protection as FlowOverlay's higher-level shutdown.
    original_destroy = root.destroy

    def guarded_destroy() -> Any:
        stop(root)
        return original_destroy()

    root.destroy = guarded_destroy  # type: ignore[method-assign]
    _schedule_pump()


def _schedule_pump() -> None:
    global _pump, _drain_command
    if _root is None:
        return
    try:
        # The real `after`, not the guard: this always runs on the main thread
        # and must produce a cancellable timer. The drain command is
        # registered exactly once per root -- see _drain_command above.
        if _drain_command is None:
            _drain_command = _root.register(_drain)
        # ``bind`` is deliberately idempotent.  Rebinding the same root must
        # not leave a second timer armed with the same command, because only
        # the newest receipt would otherwise be cancellable during teardown.
        if _pump is not None:
            try:
                _root.tk.call("after", "cancel", _pump)
            except Exception:
                pass
        _pump = _root.tk.call("after", POLL_MS, _drain_command)
    except Exception:
        _pump = None


def _drain() -> None:
    """Run everything other threads have posted, then arm the next pass."""
    if _root is None:
        return
    while True:
        try:
            callback = _queue.get_nowait()
        except queue.Empty:
            break
        try:
            callback()
        except Exception:
            # One bad callback must not stop the pump; a stopped pump means
            # every later cross-thread update is silently dropped.
            log.debug("posted callback failed", exc_info=True)
    _schedule_pump()


def stop(root: Any | None = None) -> None:
    """Cancel and retire the current root's pump before its Tcl commands die.

    ``root`` is an ownership guard for destroy wrappers left on older roots.
    A stale root must never cancel a newer root's live dispatcher.
    """
    global _root, _pump, _drain_command
    if root is not None and root is not _root:
        return
    owned_root = _root
    pump = _pump
    drain_command = _drain_command
    _root = None
    _pump = None
    _drain_command = None
    if owned_root is None:
        return
    if pump is not None:
        try:
            owned_root.tk.call("after", "cancel", pump)
        except Exception:
            pass
    if drain_command is not None:
        try:
            # ``deletecommand`` also removes the name from _tclCommands, so
            # tkinter's later Misc.destroy pass does not delete it twice.
            owned_root.deletecommand(drain_command)
        except Exception:
            pass
