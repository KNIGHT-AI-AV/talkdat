from __future__ import annotations

import unittest

import tkinter as tk
from tkinter import ttk

# The shared probe: a private tk.Tk() probe at import time condemns
# every later root on Tk 9 aqua (create-destroy-create segfaults).
from tests.tk_support import probe_error as _ROOT_ERROR

from knight_flow.config import load_config
from knight_flow.overlay import Overlay
from tests import gui_offscreen  # noqa: F401  (X-164: never show on a real screen)

# Every surface a user can reach, opened with representative arguments.
SURFACES = (
    ("settings", "open_settings", ()),
    ("account", "open_account", ()),
    ("history", "open_history", ()),
    ("scratchpad", "open_scratchpad", ()),
    ("translation", "open_translation", ()),
    ("stats", "open_stats", ()),
    ("local_models", "open_local_models", ()),
    ("model_guide", "open_model_guide", ()),
    ("add_words", "open_add_words", ()),
    ("mic_doctor", "open_mic_doctor", ()),
    ("taste_race", "open_taste_race", ()),
    ("feedback_feature", "open_feedback_form", ("feature",)),
    ("feedback_bug", "open_feedback_form", ("bug",)),
    ("status", "open_status", ()),
    ("reset", "open_reset", ()),
)


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class EveryButtonIsWiredTests(unittest.TestCase):
    """A button whose command is not a live Tcl command does nothing when
    clicked, and Tk raises no error -- the exact failure that shipped as the
    invisible Send button on Share an idea. This walks every reachable
    surface and asserts every Button resolves to a registered command, so a
    handler dropped in a refactor fails the build instead of a customer.
    """

    def setUp(self) -> None:
        # macOS: one Tk root per process, ever -- the shared-root pattern
        # every other window test here uses (see tests/tk_support).
        from tests.tk_support import acquire_root
        self.overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(self._destroy)

    def _destroy(self) -> None:
        from tests.tk_support import release_root
        try:
            release_root(self.overlay._tk_root)
        except Exception:
            pass

    def _dead_buttons(self, win: tk.Misc) -> list[str]:
        dead: list[str] = []
        stack: list[tk.Misc] = [win]
        while stack:
            widget = stack.pop()
            try:
                stack.extend(widget.winfo_children())
            except Exception:
                continue
            if not isinstance(widget, (tk.Button, ttk.Button)):
                continue
            try:
                command = str(widget.cget("command"))
            except Exception:
                command = ""
            live = False
            if command:
                try:
                    live = bool(widget.tk.call("info", "commands", command))
                except Exception:
                    live = False
            if not live:
                try:
                    label = " ".join(str(widget.cget("text")).split())
                except Exception:
                    label = widget.winfo_class()
                dead.append(label or widget.winfo_class())
        return dead

    def test_every_button_on_every_surface_has_a_live_handler(self) -> None:
        failures: list[str] = []
        for name, opener_name, args in SURFACES:
            opener = getattr(self.overlay, opener_name, None)
            if not callable(opener):
                failures.append(f"{name}: opener {opener_name} missing")
                continue
            before = set(self.overlay.root.winfo_children())
            try:
                opener(*args)
                self.overlay.root.update()
            except Exception as error:
                failures.append(f"{name}: {type(error).__name__}: {error}")
                continue
            opened = [
                child for child in self.overlay.root.winfo_children()
                if child not in before and isinstance(child, tk.Toplevel)
            ]
            target = opened[-1] if opened else getattr(self.overlay, "_shell_window", None)
            if target is None or not target.winfo_exists():
                failures.append(f"{name}: no window appeared")
                continue
            for label in self._dead_buttons(target):
                failures.append(f"{name}: dead button {label!r}")
        self.assertEqual(failures, [], f"buttons with no live handler: {failures}")


if __name__ == "__main__":
    unittest.main()
