from __future__ import annotations

from .. import font_families

from .. import mac_support

# Rebound at runtime by brand_font.apply_app_family; the literal keeps
# import free of GDI calls (they hang detached processes).
BRAND_UI_FAMILY = font_families.UI_FAMILY
BRAND_DISPLAY_FAMILY = font_families.UI_FAMILY

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Mapping, Sequence

from PIL import Image, ImageColor, ImageEnhance

from ..clay import clay_tile_rgb
from . import type_scale


# X-74: one flat level, industry standard. "Home" is dead; every section is a
# real destination and none of them opens another row of tabs.
FLOW_CONSOLE_SECTIONS = (
    ("general", "General", "Language, cleanup, updates"),
    ("colors", "Colors", "Every theme, painted as itself"),
    ("dictation", "Dictation", "Microphone, hotkeys, timing"),
    ("formatting", "Formatting", "Writing style and vocabulary"),
    ("speech", "Speech", "On this machine, or your own key"),
    ("advanced", "Advanced", "Backups, diagnostics, Race"),
)

FLOW_MATERIAL_PATH = Path(__file__).resolve().parents[1] / "assets" / "ui" / "flow-console-material.png"


@dataclass(frozen=True)
class NavigationLayout:
    width: int
    row_height: int
    description_wraplength: int


@dataclass(frozen=True)
class SettingsSearchEntry:
    """One navigable Settings label and the copy people may search for."""

    page: str
    section: str
    label: str
    help_text: str = ""
    aliases: tuple[str, ...] = ()

    @property
    def display(self) -> str:
        location = self.page if not self.section else f"{self.page} / {self.section}"
        return f"{self.label}  ·  {location}"


def _settings_search_words(value: str) -> tuple[str, ...]:
    cleaned = "".join(character.casefold() if character.isalnum() else " " for character in str(value))
    return tuple(part for part in cleaned.split() if part)


def settings_search_results(
    entries: Sequence[SettingsSearchEntry],
    query: str,
    *,
    limit: int = 8,
) -> tuple[SettingsSearchEntry, ...]:
    """Rank Settings labels, help copy, and legacy aliases deterministically."""

    words = _settings_search_words(query)
    if not words:
        return ()
    phrase = " ".join(words)
    ranked: list[tuple[int, str, str, SettingsSearchEntry]] = []
    for entry in entries:
        label = " ".join(_settings_search_words(entry.label))
        location = " ".join(_settings_search_words(f"{entry.page} {entry.section}"))
        aliases = tuple(" ".join(_settings_search_words(alias)) for alias in entry.aliases)
        help_text = " ".join(_settings_search_words(entry.help_text))
        haystack = " ".join((label, location, *aliases, help_text))
        if not all(word in haystack for word in words):
            continue
        if phrase == label or phrase in aliases:
            score = 0
        elif label.startswith(phrase):
            score = 1
        elif all(word in label for word in words):
            score = 2
        elif all(word in location or any(word in alias for alias in aliases) for word in words):
            score = 3
        else:
            score = 4
        ranked.append((score, label, location, entry))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return tuple(item[3] for item in ranked[: max(1, int(limit))])


def blend_hex(base: str, over: str, amount: float) -> str:
    """Mix two #rrggbb colours. X-152.

    A Tk widget background takes a literal colour, so the state layers every
    design system publishes as an alpha (hover at 0.06, pressed at 0.12) have
    to be resolved against the surface underneath them here, in Python, rather
    than by a compositor. Anything that needs a translucent tone in this file
    goes through this function.
    """
    amount = max(0.0, min(1.0, float(amount)))
    try:
        base_rgb = tuple(int(base.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        over_rgb = tuple(int(over.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        # Named Tk colours ("white", "SystemButtonFace") reach the palette in
        # some themes; returning the base is correct and keeps the rail drawn.
        return base
    mixed = tuple(round(b + (o - b) * amount) for b, o in zip(base_rgb, over_rgb))
    return "#%02x%02x%02x" % mixed


def navigation_layout(
    *,
    requested_width: int,
    max_text_width: int,
    label_linespace: int,
    description_linespace: int,
    scale: float = 1.0,
) -> NavigationLayout:
    """Size the navigation rail from rendered text instead of fixed pixels."""

    scale = max(1.0, float(scale))
    metric = lambda value: max(1, round(value * scale))
    width = max(metric(requested_width), int(max_text_width) + metric(48))
    row_height = max(metric(64), int(label_linespace) + int(description_linespace) + metric(32))
    return NavigationLayout(
        width=width,
        row_height=row_height,
        description_wraplength=max(metric(80), width - metric(32)),
    )


def context_menu_height(row_count: int, *, top: int = 12, pitch: int = 44, row_height: int = 40, bottom: int = 12) -> int:
    count = max(0, int(row_count))
    if count == 0:
        return top + bottom
    return top + pitch * (count - 1) + row_height + bottom


def menu_unfold_frames(start: int, target: int, *, steps: int = 8) -> tuple[int, ...]:
    """Heights for one accordion unfold, ease-out, always landing on target.

    X-168. The Features row used to toggle by DESTROYING the menu window and
    building a new one a pitch taller. That is a Win32 window teardown, a fresh
    Toplevel, a region carve, a focus_force and -- because the plate cache held
    exactly one entry keyed on height -- a full blurred re-render of the whole
    plate, every single time. Folding and unfolding thrashed that cache
    forever: two heights, one slot. He reported it as "no lag!" and he was
    describing a rebuild, not an animation.

    Ease-out cubic, because the motion is a container settling into a new size:
    it should leave fast and arrive slowly. Consecutive duplicates are dropped,
    so a two-pixel change costs two frames instead of eight identical ones.

    The last value is `target` by construction rather than by arithmetic luck.
    A container animation that lands one pixel short leaves a visible seam
    against the plate it is meant to frame.
    """
    begin = max(0, int(start))
    end = max(0, int(target))
    if begin == end:
        return (end,)
    count = max(1, int(steps))
    frames: list[int] = []
    for index in range(1, count + 1):
        progress = index / count
        eased = 1.0 - (1.0 - progress) ** 3
        value = int(round(begin + (end - begin) * eased))
        if not frames or frames[-1] != value:
            frames.append(value)
    frames[-1] = end
    return tuple(frames)


def navigation_step(keys: Sequence[str], current: str, delta: int) -> str:
    items = tuple(keys)
    if not items:
        return ""
    try:
        index = items.index(current)
    except ValueError:
        index = 0
    return items[(index + int(delta)) % len(items)]


@lru_cache(maxsize=16)
def _clay_swatch(base: tuple[int, int, int]) -> Image.Image:
    """Render one seamless clay tile for a palette colour.

    Window size is deliberately absent from this cache key.  The procedural
    part costs roughly 65,000 Python calls for a 256px tile; repeating the
    finished tile across a differently sized window is only a handful of PIL
    paste operations.  Keeping those two jobs separate turns live-resize
    settlement from a visible pause into a cheap copy.
    """

    return Image.fromarray(clay_tile_rgb(base, seed=11))


def clay_field(width: int, height: int, base: tuple[int, int, int]) -> Image.Image:
    """A lime-wash / Roman clay field in the theme's own panel colour.

    Painted once at tile resolution and then repeated, never scaled. Only the
    small swatch is cached; retaining eight expanded desktop-sized images cost
    roughly 63 MiB at 1080p and more than 250 MiB at 4K. A
    full-window panel is hundreds of thousands of pixels and doing the maths on
    each one would stall the UI every time a window opens, so the tile is still
    the unit of work -- but it is now tiled at 1:1 rather than stretched.

    Stretching was the original mistake. Upscaling a 192px tile across a panel
    is a three-times blur, which removed the trowel strokes and the mineral
    grain and left only the broadest wave, so the surface read as an uneven
    gradient instead of plaster. The texture is built from whole numbers of
    cycles per tile precisely so it can wrap without a seam, which makes
    repeating it free and keeps every scale of detail the maths produced.
    """
    width = max(1, int(width))
    height = max(1, int(height))
    swatch = _clay_swatch(tuple(int(channel) for channel in base))
    tile = swatch.width

    field = Image.new("RGB", (width, height))
    for top in range(0, height, tile):
        for left in range(0, width, tile):
            field.paste(swatch, (left, top))
    return field.convert("RGBA")


@lru_cache(maxsize=1)
def _material_source() -> Image.Image | None:
    try:
        return Image.open(FLOW_MATERIAL_PATH).convert("RGBA")
    except (FileNotFoundError, OSError):
        return None


def flow_console_material(
    width: int,
    height: int,
    *,
    background: str = "#071114",
    opacity: int = 70,
    left_anchor: bool = True,
) -> Image.Image:
    """Return a quiet, crop-safe material layer for a utility surface."""

    width = max(1, int(width))
    height = max(1, int(height))
    base = ImageColor.getrgb(background)
    # Plaster first, always. This used to run only when the shipped material was
    # missing -- which it never is -- so the clay never actually rendered on
    # anyone's machine. It is the surface now, and the photographic material is
    # laid over it rather than instead of it.
    clay = clay_field(width, height, base)

    source = _material_source()
    if source is None:
        return clay

    scale = max(width / source.width, height / source.height)
    resized = source.resize(
        (max(width, round(source.width * scale)), max(height, round(source.height * scale))),
        Image.Resampling.LANCZOS,
    )
    x = 0 if left_anchor else max(0, (resized.width - width) // 2)
    y = max(0, (resized.height - height) // 2)
    crop = resized.crop((x, y, x + width, y + height))
    crop = ImageEnhance.Contrast(crop).enhance(0.92)
    tint_alpha = 255 - max(0, min(255, int(opacity)))
    tint = Image.new("RGBA", (width, height), (*base, tint_alpha))
    finished = Image.alpha_composite(crop, tint)
    # Let the clay through at roughly a third. Enough that the surface varies
    # like lime wash across a wall and takes the theme's own pigment; not so
    # much that it competes with anything written on top of it.
    return Image.blend(finished, clay, 0.34)


class FlowNavigationRail(tk.Frame):
    """Continuous navigation rail with one selected spine and no card rows."""

    def __init__(
        self,
        master: tk.Misc,
        sections: Sequence[tuple[str, str, str]],
        command: Callable[[str], None],
        palette: Mapping[str, str],
        *,
        width: int = 184,
        scale: float = 1.0,
    ) -> None:
        self._scale = max(1.0, float(scale))
        self._px = lambda value: max(1, round(float(value) * self._scale))
        # tkinter.font.Font takes `root`, not `master`. Anything unrecognised
        # falls through **options straight into Tcl, so `master=` was sent as the
        # font option `-master` and raised TclError. That happened while building
        # the settings window, after _utility_window had already called
        # overrideredirect(True) to remove the OS titlebar and before the glass
        # titlebar existed -- so Settings opened as a blank panel with no way to
        # close it. Tk routes callback exceptions to stderr, which a --windowed
        # build discards, so nothing was logged either.
        # The rail used to render at 9-bold, 11-bold, 9-regular and 10-regular:
        # two of the four bold, and the largest thing on it 11pt. The sizes now
        # come from the desktop type scale, and only the rail's own title is
        # bold. `_label_font` and `_description_font` measure; `_row_font` is
        # what Tk actually draws, so all three sit at body size and the width
        # the layout reserves is the width the text really needs.
        self._title_font = tkfont.Font(
            root=master, family=BRAND_UI_FAMILY, size=type_scale.HEADING, weight="bold"
        )
        self._label_font = tkfont.Font(
            root=master, family=BRAND_UI_FAMILY, size=type_scale.BODY, weight="bold"
        )
        self._description_font = tkfont.Font(
            root=master, family=BRAND_UI_FAMILY, size=type_scale.BODY
        )
        self._row_font = tkfont.Font(root=master, family=BRAND_UI_FAMILY, size=type_scale.BODY)
        max_text_width = max(
            (
                max(self._label_font.measure(label), self._description_font.measure(description))
                for _key, label, description in sections
            ),
            default=0,
        )
        self._layout = navigation_layout(
            requested_width=width,
            max_text_width=max_text_width,
            label_linespace=self._label_font.metrics("linespace"),
            description_linespace=self._description_font.metrics("linespace"),
            scale=self._scale,
        )
        super().__init__(master, width=self._layout.width, bd=0, highlightthickness=0)
        self.pack_propagate(False)
        self._command = command
        self._sections = tuple(sections)
        self._rows: dict[str, tuple[tk.Frame, tk.Frame, tk.Button]] = {}
        self._selected = self._sections[0][0] if self._sections else ""
        self._focused = ""
        self._hovered = ""
        self._palette = dict(palette)

        # The rail was headed "FLOW CONSOLE". Nobody outside this repository
        # has ever called it that, and a customer opening Settings should be
        # told they are in Settings.
        title = tk.Label(self, text="Settings", anchor="w", bd=0, highlightthickness=0)
        title.pack(
            fill="x",
            padx=(self._px(20), self._px(12)),
            pady=(self._px(20), self._px(12)),
        )
        self._title = title

        for key, label, description in self._sections:
            row_shell = tk.Frame(
                self,
                height=self._layout.row_height,
                bd=0,
                highlightthickness=0,
                takefocus=False,
            )
            row_shell.pack(fill="x")
            row_shell.pack_propagate(False)
            spine = tk.Frame(row_shell, width=self._px(4), bd=0, highlightthickness=0, takefocus=False)
            spine.pack(side="left", fill="y")
            # One native button owns the entire visible row.  The old
            # Frame-plus-two-Label composite looked like navigation but exposed
            # no Button role to Windows accessibility.  Two-line text preserves
            # the label and its orientation hint without splitting the hit zone.
            button = tk.Button(
                row_shell,
                text=f"{label}\n{description}",
                command=lambda item=key: self._pointer_select(item),
                anchor="w",
                justify="left",
                cursor="hand2",
                relief="flat",
                bd=0,
                padx=self._px(16),
                pady=self._px(8),
                takefocus=1,
                highlightthickness=self._px(2),
                wraplength=self._layout.description_wraplength,
            )
            button.pack(side="left", fill="both", expand=True)
            button.bind("<Return>", lambda _event, target=button: (target.invoke(), "break")[-1], add="+")
            # Space is the native Tk Button activation path; keep an explicit
            # binding contract for tests and non-Windows Tk builds.
            button.bind("<space>", lambda _event, target=button: (target.invoke(), "break")[-1], add="+")
            button.bind("<Up>", lambda _event, item=key: self._move(item, -1), add="+")
            button.bind("<Down>", lambda _event, item=key: self._move(item, 1), add="+")
            button.bind("<Home>", lambda _event: self._focus_edge(0), add="+")
            button.bind("<End>", lambda _event: self._focus_edge(-1), add="+")
            button.bind("<Enter>", lambda _event, item=key: self._set_hover(item), add="+")
            button.bind("<Leave>", lambda _event, item=key: self._clear_hover(item), add="+")
            button.bind("<FocusIn>", lambda _event, item=key: self._set_focus(item), add="+")
            button.bind("<FocusOut>", lambda _event, item=key: self._clear_focus(item), add="+")
            self._rows[key] = (row_shell, spine, button)

        self.apply_palette(palette)

    def select(self, key: str, *, notify: bool = True) -> None:
        if key not in self._rows:
            return
        self._selected = key
        self.apply_palette(self._palette)
        if notify:
            self._command(key)

    def _pointer_select(self, key: str) -> str:
        self._rows[key][2].focus_set()
        self.select(key)
        return "break"

    def _keyboard_select(self, key: str) -> str:
        self.select(key)
        return "break"

    def _move(self, current: str, delta: int) -> str:
        target = navigation_step(tuple(self._rows), current, delta)
        if target:
            self._rows[target][2].focus_set()
            self.select(target)
        return "break"

    def _focus_edge(self, index: int) -> str:
        keys = tuple(self._rows)
        if keys:
            target = keys[index]
            self._rows[target][2].focus_set()
            self.select(target)
        return "break"

    def _set_hover(self, key: str) -> None:
        if self._hovered == key:
            return
        self._hovered = key
        self.apply_palette(self._palette)

    def _clear_hover(self, key: str) -> None:
        if self._hovered != key:
            return
        self._hovered = ""
        self.apply_palette(self._palette)

    def _set_focus(self, key: str) -> None:
        self._focused = key
        self.apply_palette(self._palette)

    def _clear_focus(self, key: str) -> None:
        if self._focused == key:
            self._focused = ""
            self.apply_palette(self._palette)

    @property
    def selected(self) -> str:
        return self._selected

    @property
    def measured_width(self) -> int:
        return self._layout.width

    def apply_palette(self, palette: Mapping[str, str]) -> None:
        self._palette = dict(palette)
        # X-127 (his review): "the side bar seems disconnected... make it part
        # of the single entity." The rail used to sit on `bg` while the pages
        # sat on `panel` -- two different planes meeting at a hard vertical
        # edge, which read as a bolted-on module. Rail and content now share
        # the SAME panel surface; only the selected row's `surface` tone and
        # the warm spine differentiate, so the console is one plane.
        base = palette["panel"]
        selected_bg = palette["surface"]
        self.configure(bg=base)
        self._title.configure(
            bg=base,
            fg=palette["muted"],
            font=self._title_font,
        )
        # X-152: hover was missing entirely, and a row that does not respond to
        # the pointer is the cheapest-feeling thing a menu can do. Every design
        # system publishes hover as a state layer over the surface (M3 uses
        # 0.08); resolved here to a literal because Tk cannot composite. It
        # lands PART of the way to the selected tone so hover never impersonates
        # selection, which stays distinguished by its spine and label colour.
        hover_bg = blend_hex(base, selected_bg, 0.55)
        for key, (row, spine, button) in self._rows.items():
            selected = key == self._selected
            hovered = key == self._hovered and not selected
            row_bg = selected_bg if selected else (hover_bg if hovered else base)
            row.configure(bg=row_bg)
            spine.configure(
                bg=palette["warm"] if selected
                else (blend_hex(row_bg, palette["warm"], 0.35) if hovered else base)
            )
            button.configure(
                bg=row_bg,
                fg=palette["text"] if selected
                else (blend_hex(palette["muted"], palette["text"], 0.5) if hovered else palette["muted"]),
                activebackground=selected_bg if selected else hover_bg,
                activeforeground=palette["text"],
                highlightbackground=palette["accent"] if key == self._focused else row_bg,
                highlightcolor=palette["accent"],
                font=self._row_font,
            )


class FlowSubnav(tk.Frame):
    """A compact view selector for related settings pages."""

    def __init__(self, master: tk.Misc, palette: Mapping[str, str], *, scale: float = 1.0) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self._scale = max(1.0, float(scale))
        self._px = lambda value: max(1, round(float(value) * self._scale))
        self._palette = dict(palette)
        self._items: dict[str, tuple[tk.Button, tk.Frame, Callable[[], None]]] = {}
        self._selected = ""
        self.apply_palette(palette)

    def add(self, key: str, label: str, command: Callable[[], None]) -> None:
        column = len(self._items)
        slot = tk.Frame(self, bd=0, highlightthickness=0)
        slot.grid(row=0, column=column, sticky="ew")
        button = tk.Button(
            slot,
            text=label,
            command=lambda item=key: self.select(item),
            anchor="center",
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=self._px(12),
            pady=self._px(8),
        )
        button.pack(fill="both", expand=True)
        indicator = tk.Frame(slot, height=self._px(2), bd=0, highlightthickness=0)
        indicator.pack(fill="x")
        self.columnconfigure(column, weight=1)
        self._items[key] = (button, indicator, command)
        if not self._selected:
            self._selected = key
        self.apply_palette(self._palette)

    def select(self, key: str, *, notify: bool = True) -> None:
        item = self._items.get(key)
        if item is None:
            return
        self._selected = key
        self.apply_palette(self._palette)
        if notify:
            item[2]()

    def apply_palette(self, palette: Mapping[str, str]) -> None:
        self._palette = dict(palette)
        self.configure(bg=palette["panel"])
        for key, (button, indicator, _command) in self._items.items():
            selected = key == self._selected
            button.configure(
                bg=palette["surface"] if selected else palette["panel"],
                fg=palette["text"] if selected else palette["muted"],
                activebackground=palette["select"],
                activeforeground=palette["text"],
                font=(BRAND_UI_FAMILY, type_scale.SECONDARY, "bold"),
            )
            indicator.configure(bg=palette["accent"] if selected else palette["panel"])
