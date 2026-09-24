"""A vertically scrolling region for panels that outgrow their window.

Written for the local model list, which is as long as the number of models and
so is not a length any window can be sized around. Measured before this
existed: 53 widgets and 1526 pixels past the bottom of the window, with no
scrollbar, no wheel binding, and -- because utility windows are
overrideredirect -- no resize border either. Everything below "Whisper Large
v3", its Download button included, was reachable only by finding the 22 pixel
grip in the corner and dragging the window taller than the screen.

Kept out of overlay.py so it can be tested against a bare Tk root. The first
version lived inside open_settings as a closure, and proving it worked meant
building the entire settings window a third time in one test class -- which
was heavy enough that a later HTTP test began timing out five seconds in.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any


def scrollable_region(parent: tk.Misc, bg: str, *, wheel_host: tk.Misc | None = None) -> tuple[tk.Frame, tk.Frame]:
    """Build a scrolling region. Returns (holder, content).

    Grid or pack `holder` where the panel should sit, and put the rows into
    `content`. `wheel_host` is the widget the mouse wheel is bound on, and
    defaults to the containing toplevel.
    """
    holder = tk.Frame(parent, bg=bg)
    canvas = tk.Canvas(holder, bg=bg, bd=0, highlightthickness=0)
    bar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
    content = tk.Frame(canvas, bg=bg)
    window_id = canvas.create_window((0, 0), window=content, anchor="nw")
    canvas.configure(yscrollcommand=bar.set)
    canvas.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")

    def fit(_event: Any = None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
        # Without this the content keeps its natural width and the rows refuse
        # to stretch to the panel.
        canvas.itemconfigure(window_id, width=canvas.winfo_width())

    content.bind("<Configure>", fit)
    canvas.bind("<Configure>", fit)

    def wheel(event: tk.Event) -> str | None:
        # The binding lives on the toplevel and the canvas is a descendant, so
        # the canvas can be destroyed first. Scrolling a dead widget raises
        # inside a Tk event handler, where the only outlet is the background
        # error handler, and it does that once per wheel event.
        if not canvas.winfo_exists():
            return None
        # Tk delivers the wheel to the widget under the pointer and does not
        # walk up to ancestors, so binding on the canvas alone does nothing
        # once the pointer is over a row inside it. Widget paths are
        # hierarchical strings, which makes ancestry a prefix test.
        if not str(event.widget).startswith(str(canvas)):
            return None
        canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    host = wheel_host if wheel_host is not None else parent.winfo_toplevel()
    host.bind("<MouseWheel>", wheel, add="+")
    return holder, content


# Widgets that can hold a scroll link. isinstance is pure Python; asking each
# widget for its option list would be a Tcl round trip per widget, and the tree
# this is called on is Settings' ~900 controls.
_VIEWS_THAT_SCROLL = (
    tk.Canvas,
    tk.Text,
    tk.Listbox,
    tk.Entry,
    tk.Spinbox,
    ttk.Entry,
    ttk.Treeview,
    ttk.Combobox,
)
_SCROLL_LINK_OPTIONS = ("xscrollcommand", "yscrollcommand")


def sever_scroll_links(widgets: Any) -> int:
    """Cut every scrollbar/view link in a tree that is about to be destroyed.

    Returns the number of links actually cut.

    X-538. The link is configured on the *view* -- ``canvas.configure(
    yscrollcommand=bar.set)`` -- so it outlives the scrollbar, and a view whose
    scrollbar has already been deleted calls a Tcl command that no longer
    exists. The error surfaces through the background handler rather than at
    the call site, which is why it reads as a mystery in the log:

        _tkinter.TclError: invalid command name ".!toplevel10.!frame5.!scrollbar"

    Ordinary teardown never exposes this, because one ``window.destroy()``
    deletes the subtree inside Tk with no observable half-state. Slice
    retirement (``Overlay._retire_toplevel_in_slices``) deliberately deletes
    leaves in small batches, so both halves of the pair are genuinely alive at
    different moments. Severing first makes the ordering irrelevant instead of
    trying to get it right.

    Never raises: this runs during teardown, where a failure would strand a
    half-retired window.
    """

    cut = 0
    for widget in widgets:
        try:
            if not widget.winfo_exists():
                continue
        except Exception:
            continue
        if isinstance(widget, _VIEWS_THAT_SCROLL):
            for option in _SCROLL_LINK_OPTIONS:
                try:
                    if str(widget.cget(option)) == "":
                        continue
                    widget.configure({option: ""})
                    cut += 1
                except Exception:
                    # Not every member of the tuple carries both options.
                    pass
        elif isinstance(widget, (tk.Scrollbar, ttk.Scrollbar)):
            try:
                if str(widget.cget("command")) != "":
                    widget.configure(command="")
                    cut += 1
            except Exception:
                pass
    return cut
