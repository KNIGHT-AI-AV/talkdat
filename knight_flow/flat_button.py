"""A button whose colours actually render on macOS.

On Aqua, tk.Button is drawn by the native theme: whatever bg= is configured,
the face renders as the system's white button chrome, while fg= IS honoured.
This UI configures dark faces with near-white text everywhere, so on a Mac
every tk.Button came out as near-white text on a white native face -- the
primary controls of onboarding were white slabs with invisible labels. cget()
still reports the configured colours, which is exactly how a colour audit
passed while the screen was unreadable: the check read what was asked for,
the pixels showed what Aqua painted instead.

tk.Label has no native face and paints exactly the colours it is given, so on
macOS this is a Label wearing tk.Button's API: command, active colours,
invoke(), disabled state, keyboard activation. On every other platform it IS
tk.Button, untouched.
"""

from __future__ import annotations

import sys
import tkinter as tk

IS_MAC = sys.platform == "darwin"

if not IS_MAC:
    FlatButton = tk.Button
else:

    class FlatButton(tk.Label):  # type: ignore[no-redef]
        _BUTTON_ONLY = {"command", "activebackground", "activeforeground",
                        "default", "overrelief", "repeatdelay", "repeatinterval"}

        def __init__(self, master=None, **kwargs):
            self._command = kwargs.pop("command", None)
            self._active_bg = kwargs.pop("activebackground", None)
            self._active_fg = kwargs.pop("activeforeground", None)
            for name in ("default", "overrelief", "repeatdelay", "repeatinterval"):
                kwargs.pop(name, None)
            # tk.Button participates in keyboard traversal; a Label does not
            # unless told to.
            kwargs.setdefault("takefocus", 1)
            super().__init__(master, **kwargs)
            self._pressed = False
            self._rest_bg: str | None = None
            self._rest_fg: str | None = None
            self.bind("<ButtonPress-1>", self._on_press, add="+")
            self.bind("<ButtonRelease-1>", self._on_release, add="+")
            self.bind("<Return>", lambda _e: self.invoke(), add="+")
            self.bind("<space>", lambda _e: self.invoke(), add="+")

        # --- behaviour -----------------------------------------------------
        def _disabled(self) -> bool:
            try:
                return str(self.cget("state")) == "disabled"
            except Exception:
                return False

        def _on_press(self, _event) -> None:
            if self._disabled():
                return
            self._pressed = True
            if self._active_bg or self._active_fg:
                self._rest_bg = str(super().cget("bg"))
                self._rest_fg = str(super().cget("fg"))
                if self._active_bg:
                    super().configure(bg=self._active_bg)
                if self._active_fg:
                    super().configure(fg=self._active_fg)

        def _on_release(self, event) -> None:
            if not self._pressed:
                return
            self._pressed = False
            if self._rest_bg is not None:
                super().configure(bg=self._rest_bg)
                self._rest_bg = None
            if self._rest_fg is not None:
                super().configure(fg=self._rest_fg)
                self._rest_fg = None
            inside = (0 <= event.x < self.winfo_width()
                      and 0 <= event.y < self.winfo_height())
            if inside and not self._disabled():
                self.invoke()

        def invoke(self):
            if self._disabled():
                return None
            if self._command is not None:
                return self._command()
            return None

        def flash(self) -> None:  # tk.Button API; nothing needs the blink
            return None

        # --- option plumbing ----------------------------------------------
        def configure(self, cnf=None, **kwargs):
            if isinstance(cnf, dict):
                kwargs = {**cnf, **kwargs}
                cnf = None
            if "command" in kwargs:
                self._command = kwargs.pop("command")
            if "activebackground" in kwargs:
                self._active_bg = kwargs.pop("activebackground")
            if "activeforeground" in kwargs:
                self._active_fg = kwargs.pop("activeforeground")
            for name in ("default", "overrelief", "repeatdelay", "repeatinterval"):
                kwargs.pop(name, None)
            if cnf is None and not kwargs:
                return super().configure()
            return super().configure(**kwargs)

        config = configure

        def cget(self, key):
            if key == "command":
                return self._command
            if key == "activebackground":
                return self._active_bg
            if key == "activeforeground":
                return self._active_fg
            return super().cget(key)

        def __setitem__(self, key, value):
            self.configure(**{key: value})

        def __getitem__(self, key):
            return self.cget(key)
