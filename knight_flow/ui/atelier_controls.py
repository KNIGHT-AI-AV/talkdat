"""Small, reusable Tk controls for the Talk DAT! Atelier surfaces.

The controls in this module deliberately consume semantic palette roles rather
than owning colors.  The preferred roles are documented by
``ATELIER_PALETTE_ROLES``.  Existing Talk DAT! palette names are accepted as
aliases so a control can be introduced without changing saved themes.

``AtelierButton`` is a real :class:`tkinter.Button`.  A generated, semantic
background preserves the quiet lift and rounded focus treatment without hiding
the action inside a Canvas.  Windows accessibility clients therefore receive a
native Button role, name, focus, enabled state, and Invoke action.
"""

from __future__ import annotations

import math
import tkinter as tk
from collections import OrderedDict
from collections.abc import Callable, Mapping
from tkinter import font as tkfont
from typing import Any, ClassVar, Final

from PIL import Image, ImageDraw, ImageTk

from . import type_scale


ATELIER_PALETTE_ROLES: Final[tuple[str, ...]] = (
    "canvas",
    "surface",
    "surface_hover",
    "surface_pressed",
    "surface_disabled",
    "border",
    "text",
    "text_disabled",
    "primary",
    "primary_hover",
    "primary_pressed",
    "on_primary",
    "on_primary_disabled",
    "focus",
    "shadow",
    "top_highlight",
    "primary_highlight",
)


# Canonical roles come first.  The remaining names are semantic aliases used by
# the current theme catalog.  There are intentionally no color constants here:
# high-contrast and user themes stay in control of every rendered color.
_ROLE_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "canvas": ("canvas", "bg", "panel"),
    "surface": ("surface", "button", "raised"),
    "surface_hover": ("surface_hover", "select", "raised", "surface", "button"),
    "surface_pressed": ("surface_pressed", "field", "select", "surface", "button"),
    "surface_disabled": ("surface_disabled", "field", "surface", "button"),
    "border": ("border", "stroke", "border_strong", "border_subtle"),
    "text": ("text", "text_primary"),
    "text_disabled": ("text_disabled", "muted", "text_secondary", "text"),
    "primary": ("primary", "accent"),
    "primary_hover": ("primary_hover", "accent2", "primary", "accent"),
    "primary_pressed": ("primary_pressed", "accent2", "primary", "accent"),
    "on_primary": ("on_primary", "primary_text", "text", "text_primary"),
    "on_primary_disabled": (
        "on_primary_disabled",
        "text_disabled",
        "muted",
        "on_primary",
        "text",
    ),
    "focus": ("focus", "accent2", "accent", "border", "stroke"),
    "shadow": ("shadow", "bg", "canvas", "panel"),
    "top_highlight": ("top_highlight", "highlight", "stroke", "border", "surface"),
    "primary_highlight": (
        "primary_highlight",
        "top_highlight",
        "highlight",
        "accent2",
        "primary",
        "accent",
    ),
}


def _resolve_palette(palette: Mapping[str, str]) -> dict[str, str]:
    """Return canonical Atelier roles resolved from a semantic palette.

    A clear error at construction time is preferable to a half-drawn button.
    Values must be non-empty strings understood by Tk as colors; Tk performs
    the final platform-specific color validation when the widget is created.
    """

    resolved: dict[str, str] = {}
    missing: list[str] = []
    for role in ATELIER_PALETTE_ROLES:
        value = next(
            (
                str(palette[key]).strip()
                for key in _ROLE_ALIASES[role]
                if key in palette and str(palette[key]).strip()
            ),
            "",
        )
        if value:
            resolved[role] = value
        else:
            missing.append(role)
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"palette cannot resolve semantic role(s): {names}")
    return resolved


def _validated_scale(scale: float) -> float:
    value = float(scale)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("scale must be a positive finite number")
    return value


def _scaled(value: float, scale: float, *, minimum: int = 1) -> int:
    return max(minimum, int(round(float(value) * scale)))


def _rounded_points(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
) -> tuple[float, ...]:
    """Polygon points used by Canvas to render a rounded rectangle."""

    radius = max(0.0, min(float(radius), (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    return (
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    )


class AtelierButton(tk.Button):
    """A native, focusable, theme-driven Talk DAT! action button.

    ``min_width`` is expressed in unscaled design pixels.  ``scale`` is also
    explicit so callers use the same DPI decision as the containing window.
    The total requested height is 44 design pixels for a primary action and 40
    for a secondary action, including the focus and two-pixel lift regions.
    """

    PRIMARY_HEIGHT: Final[int] = 44
    SECONDARY_HEIGHT: Final[int] = 40
    PRIMARY_MIN_WIDTH: Final[int] = 112
    SECONDARY_MIN_WIDTH: Final[int] = 96
    RADIUS: Final[int] = 6
    FOCUS_RING: Final[int] = 2
    LIFT: Final[int] = 2
    PRESSED_TRAVEL: Final[int] = 1
    # X-536: how far outside its own edge a press may still land, in design
    # pixels. A release one pixel past the border used to cancel the action
    # outright, which punishes exactly the people least able to hold a pointer
    # still -- and on a touch screen the finger's centroid drifts on lift by
    # more than this on its own. Apple's fluid-interface rule is ~10px of
    # hysteresis around a tap target; this is that, in our unit, scaled.
    HIT_SLOP: Final[int] = 10
    HORIZONTAL_PADDING: Final[int] = 18
    # X-536: this was a bare 14, which made a primary action's label SMALLER
    # than the body copy beside it (BODY is 12pt = 16px) -- backwards for the
    # most important control on the panel. It is now the body step, so the
    # button label matches the prose it sits next to and the bold weight
    # carries the emphasis instead of the size, which is the cheaper way to
    # get presence: weight adds it without taking more space.
    #
    # Kept in PIXELS on purpose. Every other measurement in this widget
    # (heights, padding, the focus ring) is design pixels multiplied by an
    # explicit `scale`, and a point size would ALSO be multiplied by Tk's own
    # `tk scaling` -- so mixing the two units in one widget scales the text
    # twice against its own box. One unit per widget; the conversion is done
    # here, once, where it is visible.
    LABEL_SIZE: Final[int] = round(type_scale.BODY * type_scale.POINTS_TO_PIXELS)
    RESIZE_FRAME_MS: Final[int] = 16
    RESIZE_SETTLE_MS: Final[int] = 96
    SKIN_CACHE_LIMIT: Final[int] = 48
    SKIN_CACHE_PIXEL_LIMIT: Final[int] = 2_500_000

    # PIL images are interpreter-independent and safe to reuse as immutable
    # render results.  ImageTk.PhotoImage objects are deliberately *not*
    # shared: each native Button keeps its own Tk image and accessibility
    # semantics.  The LRU bound caps a worst-case run of one-off resize widths.
    _skin_cache: ClassVar[OrderedDict[tuple[object, ...], Image.Image]] = OrderedDict()

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command: Callable[[], object] | None,
        palette: Mapping[str, str],
        primary: bool = False,
        min_width: int | float | None = None,
        *,
        scale: float = 1.0,
        **kwargs: Any,
    ) -> None:
        self.scale = _validated_scale(scale)
        self.primary = bool(primary)
        self._text = str(text)
        self._command = command
        self._state = str(kwargs.pop("state", tk.NORMAL))
        self._validate_state(self._state)
        self._colors = _resolve_palette(palette)
        self._minimum_design_width = (
            float(min_width)
            if min_width is not None
            else float(self.PRIMARY_MIN_WIDTH if self.primary else self.SECONDARY_MIN_WIDTH)
        )
        if not math.isfinite(self._minimum_design_width) or self._minimum_design_width <= 0:
            raise ValueError("min_width must be a positive finite number")

        requested_font = kwargs.pop("font", None)
        self._font = tkfont.Font(master=master, font=requested_font or "TkDefaultFont")
        self._font.configure(size=-_scaled(self.LABEL_SIZE, self.scale), weight="bold")

        self._hovered = False
        self._pressed = False
        self._keyboard_armed: str | None = None
        self._resize_frame_after: str | None = None
        self._resize_settle_after: str | None = None
        self._pending_resize: tuple[int, int] | None = None
        self._last_observed_size: tuple[int, int] | None = None
        self._last_render_signature: tuple[object, ...] | None = None
        self._rgba_cache: dict[str, tuple[int, int, int, int]] = {}
        self._destroyed = False
        height = self.design_height(self.primary, self.scale)
        width = self._requested_width()

        # A one-pixel seed lets Tk create the native Button before the rounded
        # semantic background is rendered.  Keeping text on the Button (rather
        # than baking it into the image) is what exposes the accessible name.
        self._background_image: tk.PhotoImage | ImageTk.PhotoImage = tk.PhotoImage(
            master=master,
            width=1,
            height=1,
        )
        kwargs.update(
            {
                "width": width,
                "height": height,
                "text": self._text,
                "command": self._dispatch_command,
                "image": self._background_image,
                "compound": tk.CENTER,
                "font": self._font,
                "bg": self._colors["canvas"],
                "fg": self._colors["on_primary" if self.primary else "text"],
                "activebackground": self._colors["canvas"],
                "activeforeground": self._colors["on_primary" if self.primary else "text"],
                "disabledforeground": self._colors[
                    "on_primary_disabled" if self.primary else "text_disabled"
                ],
                "bd": 0,
                "highlightthickness": 0,
                "relief": tk.FLAT,
                "overrelief": tk.FLAT,
                "padx": 0,
                "pady": 0,
                "takefocus": True,
                "cursor": "hand2" if self._state == tk.NORMAL else "",
                "state": self._state,
            }
        )
        super().__init__(master, **kwargs)

        self.bind("<Configure>", self._on_resize, add="+")
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<B1-Motion>", self._on_drag, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")
        self.bind("<FocusIn>", self._on_focus_in, add="+")
        self.bind("<FocusOut>", self._on_focus_out, add="+")
        self.bind("<KeyPress-Return>", self._on_keyboard_press, add="+")
        self.bind("<KeyRelease-Return>", self._on_keyboard_release, add="+")
        self.bind("<KeyPress-space>", self._on_keyboard_press, add="+")
        self.bind("<KeyRelease-space>", self._on_keyboard_release, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._redraw()

    @classmethod
    def design_height(cls, primary: bool, scale: float = 1.0) -> int:
        """Return the exact requested widget height for a design scale."""

        valid_scale = _validated_scale(scale)
        base = cls.PRIMARY_HEIGHT if primary else cls.SECONDARY_HEIGHT
        return _scaled(base, valid_scale)

    @staticmethod
    def _validate_state(state: str) -> None:
        if state not in {tk.NORMAL, tk.DISABLED}:
            raise tk.TclError(f'bad state "{state}": must be normal or disabled')

    def _requested_width(self) -> int:
        measured = int(self._font.measure(self._text)) + _scaled(
            self.HORIZONTAL_PADDING * 2,
            self.scale,
        )
        return max(_scaled(self._minimum_design_width, self.scale), measured)

    def _sync_requested_width(self) -> None:
        super().configure(width=self._requested_width())
        self._redraw()

    def configure(self, cnf: Any = None, **kwargs: Any) -> Any:
        """Configure native Button options while retaining the scaled skin."""

        if cnf is None and not kwargs:
            return super().configure()
        if isinstance(cnf, str) and cnf in {"text", "state"} and not kwargs:
            return super().configure(cnf)
        if cnf is not None and not isinstance(cnf, Mapping):
            return super().configure(cnf, **kwargs)

        options: dict[str, Any] = dict(cnf or {})
        options.update(kwargs)
        text_changed = False
        state_changed = False
        if "text" in options:
            self._text = str(options.pop("text"))
            text_changed = True
        if "state" in options:
            state = str(options.pop("state"))
            self._validate_state(state)
            self._state = state
            state_changed = True
            if state == tk.DISABLED:
                self._hovered = False
                self._pressed = False
                self._keyboard_armed = None
        if "command" in options:
            self._command = options.pop("command")
            options["command"] = self._dispatch_command
        if state_changed or "cursor" in options:
            options["cursor"] = "hand2" if self._state == tk.NORMAL else ""

        if text_changed:
            options["text"] = self._text
        if state_changed:
            options["state"] = self._state

        result = super().configure(**options) if options else None
        if text_changed:
            self._sync_requested_width()
        if text_changed or state_changed or "cursor" in options:
            self._redraw()
        return result

    config = configure

    def cget(self, key: str) -> Any:
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        return super().cget(key)

    def _dispatch_command(self) -> object | None:
        if callable(self._command):
            return self._command()
        return None

    def invoke(self) -> object | None:
        """Use Tk's native Invoke action; disabled buttons remain inert."""

        return super().invoke()

    def _on_resize(self, event: tk.Event[Any]) -> None:
        """Coalesce raw Configure storms into at most one render per frame.

        Tk can emit dozens of Configure notifications while a parent window is
        dragged.  Rendering the 3x antialiased skin synchronously in each event
        blocks geometry negotiation and makes every menu appear to tear.  Keep
        the newest size, paint on the next frame, then make one exact final pass
        after the resize stream has settled.
        """

        if self._destroyed:
            return
        try:
            event_width = getattr(event, "width", None)
            event_height = getattr(event, "height", None)
            width = max(1, int(self.winfo_width() if event_width is None else event_width))
            height = max(1, int(self.winfo_height() if event_height is None else event_height))
        except (tk.TclError, TypeError, ValueError):
            return
        size = (width, height)
        if size == self._last_observed_size:
            return
        self._last_observed_size = size
        self._pending_resize = size
        self._schedule_resize_redraw()

    def _schedule_resize_redraw(self) -> None:
        if self._destroyed:
            return
        if self._resize_frame_after is None:
            try:
                self._resize_frame_after = self.after(
                    self.RESIZE_FRAME_MS,
                    self._flush_resize_redraw,
                )
            except tk.TclError:
                return

        if self._resize_settle_after is not None:
            try:
                self.after_cancel(self._resize_settle_after)
            except tk.TclError:
                pass
        try:
            self._resize_settle_after = self.after(
                self.RESIZE_SETTLE_MS,
                self._settle_resize_redraw,
            )
        except tk.TclError:
            self._resize_settle_after = None

    def _flush_resize_redraw(self) -> None:
        self._resize_frame_after = None
        if self._destroyed:
            return
        try:
            self._redraw()
        finally:
            self._pending_resize = None

    def _settle_resize_redraw(self) -> None:
        self._resize_settle_after = None
        if self._destroyed:
            return
        if self._resize_frame_after is not None:
            try:
                self.after_cancel(self._resize_frame_after)
            except tk.TclError:
                pass
            self._resize_frame_after = None
        # Read the widget rather than trusting an older event so the final skin
        # is exact even when Windows coalesced the final native size message.
        try:
            final_size = (
                max(1, int(self.winfo_width())),
                max(1, int(self.winfo_height())),
            )
        except tk.TclError:
            self._pending_resize = None
            return
        self._last_observed_size = final_size
        self._pending_resize = final_size
        try:
            self._redraw()
        finally:
            self._pending_resize = None

    def _on_destroy(self, event: tk.Event[Any]) -> None:
        if getattr(event, "widget", None) is not self:
            return
        self._destroyed = True
        for attribute in ("_resize_frame_after", "_resize_settle_after"):
            receipt = getattr(self, attribute, None)
            if receipt is not None:
                try:
                    self.after_cancel(receipt)
                except tk.TclError:
                    pass
            setattr(self, attribute, None)
        self._pending_resize = None

    def _on_enter(self, _event: tk.Event[Any]) -> None:
        if self._state == tk.NORMAL:
            self._hovered = True
            super().configure(cursor="hand2")
            self._redraw()

    def _on_leave(self, _event: tk.Event[Any]) -> None:
        self._hovered = False
        if self._state != tk.NORMAL:
            super().configure(cursor="")
        self._redraw()

    def _on_press(self, _event: tk.Event[Any]) -> str:
        if self._state != tk.NORMAL:
            return "break"
        self.focus_set()
        self._keyboard_armed = None
        self._pressed = True
        self._redraw()
        return "break"

    def _within_hit_area(self, event: tk.Event[Any]) -> bool:
        """Whether a pointer at ``event`` still counts as on this button.

        The button's own rectangle grown by ``HIT_SLOP``. Growing it is the
        point: the visible edge is where the button is *drawn*, not where a
        person aiming at it stops meaning to press it.
        """

        slop = _scaled(self.HIT_SLOP, self.scale)
        try:
            width, height = self.winfo_width(), self.winfo_height()
        except tk.TclError:
            return False
        return (
            -slop <= int(event.x) < width + slop
            and -slop <= int(event.y) < height + slop
        )

    def _on_drag(self, event: tk.Event[Any]) -> str:
        """Track in or out of the hit area for the whole press, not just its end.

        Feedback during an interaction has to be continuous. Without this the
        button stays lit while the pointer is dragged right across the panel,
        so the one affordance that says "let go here and nothing happens" only
        appears after letting go, when it is no longer a choice.
        """

        if self._state != tk.NORMAL:
            return "break"
        pressed = self._within_hit_area(event)
        if pressed != self._pressed:
            self._pressed = pressed
            self._hovered = pressed
            self._redraw()
        return "break"

    def _on_release(self, event: tk.Event[Any]) -> str:
        was_pressed = self._pressed
        self._pressed = False
        inside = self._within_hit_area(event)
        self._hovered = bool(inside and self._state == tk.NORMAL)
        self._redraw()
        if was_pressed and inside:
            self.invoke()
        return "break"

    def _on_focus_in(self, _event: tk.Event[Any]) -> None:
        self._redraw()

    def _on_focus_out(self, _event: tk.Event[Any]) -> None:
        self._keyboard_armed = None
        self._pressed = False
        self._redraw()

    @staticmethod
    def _keyboard_key(event: tk.Event[Any]) -> str:
        return str(getattr(event, "keysym", "")).lower()

    def _on_keyboard_press(self, event: tk.Event[Any]) -> str:
        if self._state != tk.NORMAL:
            return "break"
        key = self._keyboard_key(event)
        if key not in {"return", "space"}:
            return "break"
        if self._keyboard_armed is None:
            self._keyboard_armed = key
            self._pressed = True
            self._redraw()
        return "break"

    def _on_keyboard_release(self, event: tk.Event[Any]) -> str:
        key = self._keyboard_key(event)
        armed = self._keyboard_armed
        if armed != key:
            return "break"
        self._keyboard_armed = None
        self._pressed = False
        self._redraw()
        if self._state == tk.NORMAL:
            self.invoke()
        return "break"

    def _body_colors(self) -> tuple[str, str, str]:
        if self._state == tk.DISABLED:
            return (
                self._colors["surface_disabled"],
                self._colors["on_primary_disabled" if self.primary else "text_disabled"],
                self._colors["top_highlight"],
            )
        if self.primary:
            fill = (
                self._colors["primary_pressed"]
                if self._pressed
                else self._colors["primary_hover"]
                if self._hovered
                else self._colors["primary"]
            )
            return fill, self._colors["on_primary"], self._colors["primary_highlight"]
        fill = (
            self._colors["surface_pressed"]
            if self._pressed
            else self._colors["surface_hover"]
            if self._hovered
            else self._colors["surface"]
        )
        return fill, self._colors["text"], self._colors["top_highlight"]

    def _rgba(self, color: str) -> tuple[int, int, int, int]:
        cached = self._rgba_cache.get(color)
        if cached is not None:
            return cached
        red, green, blue = self.winfo_rgb(color)
        rgba = red // 257, green // 257, blue // 257, 255
        self._rgba_cache[color] = rgba
        return rgba

    @classmethod
    def _cached_skin(cls, signature: tuple[object, ...]) -> Image.Image | None:
        image = cls._skin_cache.pop(signature, None)
        if image is not None:
            cls._skin_cache[signature] = image
        return image

    @classmethod
    def _remember_skin(cls, signature: tuple[object, ...], image: Image.Image) -> None:
        pixels = int(image.width) * int(image.height)
        if pixels > cls.SKIN_CACHE_PIXEL_LIMIT:
            return
        cls._skin_cache[signature] = image
        cls._skin_cache.move_to_end(signature)
        while len(cls._skin_cache) > cls.SKIN_CACHE_LIMIT or sum(
            int(cached.width) * int(cached.height) for cached in cls._skin_cache.values()
        ) > cls.SKIN_CACHE_PIXEL_LIMIT:
            cls._skin_cache.popitem(last=False)

    def _draw_skin(
        self,
        *,
        width: int,
        height: int,
        focus: int,
        radius: int,
        lift: int,
        travel: int,
        fill: str,
        highlight: str,
        focused: bool,
    ) -> Image.Image:
        """Render one immutable, downsampled decorative button skin."""

        # Draw at 3x and downsample so the generated skin retains the previous
        # antialiased rounded silhouette.  The image is decoration only: Tk
        # continues to render the actual text and expose the native semantics.
        supersample = 3
        image = Image.new(
            "RGBA",
            (max(1, width * supersample), max(1, height * supersample)),
            self._rgba(self._colors["canvas"]),
        )
        draw = ImageDraw.Draw(image)

        def box(values: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            return tuple(int(value * supersample) for value in values)  # type: ignore[return-value]

        x1 = focus
        y1 = focus + travel
        x2 = max(focus + 1, width - focus - 1)
        y2 = max(focus + 1, height - focus - lift - 1 + travel)
        scaled_radius = radius * supersample
        if lift:
            draw.rounded_rectangle(
                box((x1, y1 + lift, x2, y2 + lift)),
                radius=scaled_radius,
                fill=self._rgba(self._colors["shadow"]),
            )

        draw.rounded_rectangle(
            box((x1, y1, x2, y2)),
            radius=scaled_radius,
            fill=self._rgba(fill),
            outline=self._rgba(self._colors["border"]),
            width=max(1, _scaled(1, self.scale) * supersample),
        )
        highlight_inset = max(radius, _scaled(8, self.scale))
        draw.line(
            (
                (x1 + highlight_inset) * supersample,
                (y1 + _scaled(1, self.scale)) * supersample,
                (x2 - highlight_inset) * supersample,
                (y1 + _scaled(1, self.scale)) * supersample,
            ),
            fill=self._rgba(highlight),
            width=max(1, _scaled(1, self.scale) * supersample),
        )
        if focused:
            draw.rounded_rectangle(
                box((1, 1 + travel, width - 2, height - 2 - lift + travel)),
                radius=(radius + focus) * supersample,
                outline=self._rgba(self._colors["focus"]),
                width=max(1, focus * supersample),
            )

        return image.resize((max(1, width), max(1, height)), Image.Resampling.LANCZOS)

    def _redraw(self) -> None:
        if self._destroyed or not getattr(self, "tk", None):
            return
        try:
            current_width = self.winfo_width()
            current_height = self.winfo_height()
        except tk.TclError:
            return
        requested_width = int(float(super().cget("width")))
        requested_height = int(float(super().cget("height")))
        pending_width, pending_height = self._pending_resize or (current_width, current_height)
        width = requested_width if pending_width <= 1 else pending_width
        height = requested_height if pending_height <= 1 else pending_height

        focus = _scaled(self.FOCUS_RING, self.scale)
        radius = _scaled(self.RADIUS, self.scale)
        lift = 0 if self._pressed else _scaled(self.LIFT, self.scale)
        travel = _scaled(self.PRESSED_TRAVEL, self.scale) if self._pressed else 0
        fill, text, highlight = self._body_colors()
        try:
            focused = self.focus_get() is self
        except tk.TclError:
            return
        signature: tuple[object, ...] = (
            width,
            height,
            self.scale,
            focus,
            radius,
            lift,
            travel,
            focused,
            self._rgba(self._colors["canvas"]),
            self._rgba(self._colors["shadow"]),
            self._rgba(self._colors["border"]),
            self._rgba(fill),
            self._rgba(highlight),
            self._rgba(self._colors["focus"]),
            self._rgba(text),
        )
        if signature == self._last_render_signature:
            return

        image = self._cached_skin(signature)
        if image is None:
            image = self._draw_skin(
                width=width,
                height=height,
                focus=focus,
                radius=radius,
                lift=lift,
                travel=travel,
                fill=fill,
                highlight=highlight,
                focused=focused,
            )
            self._remember_skin(signature, image)
        self._background_image = ImageTk.PhotoImage(image, master=self)
        super().configure(
            image=self._background_image,
            bg=self._colors["canvas"],
            fg=text,
            activebackground=self._colors["canvas"],
            activeforeground=text,
            disabledforeground=text,
        )
        self._last_render_signature = signature


__all__ = ["ATELIER_PALETTE_ROLES", "AtelierButton"]
