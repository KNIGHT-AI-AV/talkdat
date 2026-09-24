"""Give a Tk ``Text`` widget the leading its type size asks for.

``type_scale`` decides how loose each step should read; this is the half that
puts the number on the screen. It is separate from ``type_scale`` on purpose:
that module stays importable with no display and no tkinter, which is what lets
the whole scale be tested headless, and importing tkinter into it would end
that.

The call reads the widget's own font rather than taking a size, so there is no
second place for the size to be wrong. Ask a widget how it is set and it always
tells the truth; pass the size alongside it and the two drift.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from tkinter import font as tkfont

from . import type_scale


def apply(widget: tk.Text, *, prose: bool = False) -> int:
    """Set ``spacing1``/``spacing2`` from the widget's font. Returns the pixels.

    ``spacing2`` is the leading proper -- the gap between the wrapped lines of
    one paragraph. ``spacing1`` puts the same gap above each paragraph, so a
    block of prose separates into paragraphs without a blank line having to be
    typed into the content.

    ``spacing3`` is deliberately left alone: it adds space *below* the last
    line, which on a short widget reads as a mis-centred box rather than as
    leading.

    Best effort by design. Leading is a refinement, and a widget that has
    already been destroyed, or a font Tk cannot resolve, must never take a panel
    down on the way to looking slightly nicer.
    """

    try:
        resolved = tkfont.Font(root=widget, font=widget.cget("font"))
        points = resolved.actual("size")
        linespace = resolved.metrics("linespace")
        # X-604: the display's own pixels per point. The app is DPI aware
        # (ui_scale), so at 150% a 12 pt line renders 32 px tall; measured
        # against the 96-DPI conversion the target was smaller than the line
        # and every body widget got no leading at all on the owner's screen.
        pixels_per_point = float(widget.winfo_fpixels("1p")) or type_scale.POINTS_TO_PIXELS
    except (tk.TclError, RuntimeError, TypeError, ValueError):
        return 0

    # A negative Tk size is already in pixels; the scale speaks points.
    if points < 0:
        points = abs(points) / pixels_per_point

    extra = type_scale.extra_leading_px(points, linespace, prose=prose, pixels_per_point=pixels_per_point)
    if extra <= 0:
        return 0
    with contextlib.suppress(tk.TclError):
        widget.configure(spacing1=extra, spacing2=extra)
    return extra


__all__ = ["apply"]
