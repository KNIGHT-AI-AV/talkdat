"""X-164: test windows must never appear on a human's screen.

Importing this module makes every Tk window created afterwards open fully
transparent and positioned far outside the desktop.

Why it exists: the GUI suite builds REAL windows, and it was run on the
founder's machine while he was gaming. Settings panels and pill overlays
flashed over a full-screen game. A test that steals the screen is a test
people stop running, and the ones here are the only cover several widgets have.

Layout still works. The windows are mapped and sized exactly as before, so
`winfo_width`, geometry maths and `update_idletasks` behave identically; only
their opacity and position change. That matters: withdrawing them instead
would zero every measurement and quietly turn the geometry tests into no-ops.

There is a second, sharper reason to be off-desktop. A visible test window sits
under the real cursor, and a synthesized click on one can enter Windows' modal
move loop (WM_NCLBUTTONDOWN), which spins in native code and killed the whole
suite with a fatal GIL error. Being nowhere near the pointer removes the
opportunity as well as the annoyance.

Usage, one line at the top of any GUI test module:

    from tests import gui_offscreen  # noqa: F401
"""

from __future__ import annotations

import sys
import tkinter as tk

# Far outside any monitor arrangement, including the one mounted ABOVE the
# primary on this machine, which is why the Y is very negative rather than
# merely off to the right.
_PARK_X = -32000
_PARK_Y = -32000

_PATCHED_FLAG = "_talkdat_offscreen_patched"


def _hide(window: tk.Misc) -> None:
    """Park and blank one window. Never raises: a test must not fail here."""
    try:
        window.wm_geometry(f"+{_PARK_X}+{_PARK_Y}")
    except Exception:
        pass
    try:
        # Fully transparent rather than withdrawn, so geometry still resolves.
        window.attributes("-alpha", 0.0)
    except Exception:
        pass
    try:
        # Never take focus from whatever the person is actually doing.
        window.attributes("-topmost", False)
    except Exception:
        pass


def install() -> None:
    """Patch Tk and Toplevel so every future window is born hidden.

    WINDOWS ONLY, and that is not laziness. The problem this solves is a person
    at a desk: test windows appearing over his game on his own machine. The Mac
    is a build box nobody is sitting at, and its Aqua tests READ REAL SCREEN
    PIXELS to prove what is actually rendered rather than what `cget` claims.
    An invisible window has no pixels, so installing this there would turn
    those tests from a real check into a lie that passes.
    """
    if sys.platform != "win32":
        return
    if getattr(tk, _PATCHED_FLAG, False):
        return

    original_tk_init = tk.Tk.__init__
    original_toplevel_init = tk.Toplevel.__init__

    def tk_init(self, *args, **kwargs):
        original_tk_init(self, *args, **kwargs)
        _hide(self)

    def toplevel_init(self, *args, **kwargs):
        original_toplevel_init(self, *args, **kwargs)
        _hide(self)

    tk.Tk.__init__ = tk_init
    tk.Toplevel.__init__ = toplevel_init
    setattr(tk, _PATCHED_FLAG, True)


install()
