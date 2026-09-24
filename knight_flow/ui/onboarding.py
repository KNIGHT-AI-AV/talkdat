from __future__ import annotations

from .. import font_families

from .. import mac_support
from ..flat_button import FlatButton

# Rebound at runtime by brand_font.apply_app_family; the literal keeps
# import free of GDI calls (they hang detached processes).
BRAND_UI_FAMILY = font_families.UI_FAMILY
BRAND_DISPLAY_FAMILY = font_families.UI_FAMILY

import contextlib
import copy
import sys
import threading
import time

from .. import platform_copy
import tkinter as tk
import webbrowser
from array import array
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageEnhance, ImageOps, ImageTk

from .. import main_thread, ui_scale
from ..audio_input import list_input_devices, open_raw_input_stream, pcm_rms_level, resolve_input_device
from ..hotkeys import physical_key_down
from ..local_stt import DEFAULT_LOCAL_MODEL_ID, downloaded_size_mb, is_downloaded, local_model_for_id
from ..mic_registry import DEFERRED_MICROPHONE_RELEASE, ONBOARDING, microphone_registry
from ..onboarding import (
    permissions_outstanding,
    GATEKEEPER_NOTE,
    PRIVACY_URL,
    TERMS_URL,
    ONBOARDING_STEPS,
    WRITING_PRESETS,
    apply_writing_preset,
    hotkey_labels,
    mark_onboarding_complete,
    microphone_quality,
    permission_is_satisfied,
    permission_pages,
    primary_hotkey,
    selected_access_choice,
    selected_writing_preset,
)
from . import leading
from .atelier_controls import AtelierButton
from . import type_scale
from ..stt_registry import (
    FLAGSHIP_CLOUD_PROVIDER_IDS,
    MANAGED_CLOUD_PROVIDER_IDS,
    PROVIDER_BY_ID,
    flagship_cloud_provider_labels,
    model_for_id,
    model_id_for_label,
    model_label,
    model_labels,
    provider_capability_summary,
    provider_id_for_label,
    provider_label,
    provider_settings,
    selected_model_id,
    selected_provider_id,
    selected_variant,
    sync_legacy_deepgram,
)


# Displayed, not just a constant name: this is the first item of the mic
# picker and its reset value.
WINDOWS_DEFAULT_MIC = mac_support.SYSTEM_DEFAULT_MIC_LABEL


ONBOARDING_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "onboarding"
ONBOARDING_ART = {
    "intro": "01-arrival-stone.png",
    "welcome": "01-arrival-stone.png",
    "voice": "03-route-engine.png",
    "microphone": "04-voice-instrument.png",
    "controls": "04-voice-instrument.png",
    "menu": "05-command-deck.png",
    "superpowers": "05-command-deck.png",
    "writing": "06-finish-engine.png",
    "test": "06-finish-engine.png",
}

# Generated artwork is deliberately rendered with Lanczos resampling and an
# alpha mask. That is the right final quality, but doing it for every raw Tk
# Configure event turns a window drag into a queue of expensive synchronous
# paints. Keep the last complete frame on screen and render only the settled
# size. Initial page artwork still paints on the first idle turn.
ART_RESIZE_SETTLE_MS = 160

# X-484: eight steps now. The two that were removed asked for a decision
# the product no longer has, so resume receipts naming them fall back to
# the first step rather than crashing, which _resume_step_index already
# does for any unknown id.
# The functional steps remain intact so resume receipts and every real
# setup task keep their identity. The visible progress model is intentionally
# calmer: four meaningful chapters instead of ten tiny implementation labels.
ONBOARDING_CHAPTERS = (
    ("Start", frozenset({"intro", "welcome"})),
    ("Voice", frozenset({"voice", "permissions", "microphone"})),
    ("Control", frozenset({"controls", "menu", "superpowers"})),
    ("Finish", frozenset({"writing", "test"})),
)


def _rgb_channels(colour: str) -> tuple[int, int, int]:
    """Resolve the six-digit theme colours used by the shipped palette catalog."""

    value = str(colour).strip().lstrip("#")
    if len(value) == 3:
        value = "".join(character * 2 for character in value)
    if len(value) != 6:
        raise ValueError(f"unsupported theme colour: {colour!r}")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _relative_luminance(colour: str) -> float:
    channels = []
    for channel in _rgb_channels(colour):
        value = channel / 255.0
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _mix_colour(colour: str, target: str, amount: float) -> str:
    source_channels = _rgb_channels(colour)
    target_channels = _rgb_channels(target)
    clean_amount = max(0.0, min(1.0, float(amount)))
    mixed = tuple(
        round(source + (destination - source) * clean_amount)
        for source, destination in zip(source_channels, target_channels, strict=True)
    )
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


def _repair_fill_contrast(fill: str, foreground: str, minimum: float = 4.5) -> str:
    """Keep a theme's hue when possible, nudging only fills that miss AA."""

    if _contrast_ratio(fill, foreground) >= minimum:
        return fill
    target = "#000000" if _relative_luminance(foreground) > 0.5 else "#ffffff"
    for step in range(1, 21):
        candidate = _mix_colour(fill, target, step / 20.0)
        if _contrast_ratio(candidate, foreground) >= minimum:
            return candidate
    return target


def accessible_control_palette(palette: dict[str, str], *, canvas: str | None = None) -> dict[str, str]:
    """Return semantic control roles with an AA-safe primary label pair.

    Talk DAT! ships fifty themes. Some accents sit in the visual midrange where
    neither the theme's normal text nor one fixed white/ink label is readable.
    The foreground is selected from true black/white against every primary
    state, then only the failing state fills are moved toward the opposite
    extreme. This preserves the theme instead of replacing it.
    """

    fills = (palette["accent"], palette["accent2"], palette["accent2"])
    candidates = ("#000000", "#ffffff")
    foreground = max(candidates, key=lambda candidate: min(_contrast_ratio(fill, candidate) for fill in fills))
    primary, hover, pressed = (_repair_fill_contrast(fill, foreground) for fill in fills)
    return {
        "canvas": canvas or palette["bg"],
        "surface": palette["button"],
        "surface_hover": palette["select"],
        "surface_pressed": palette["field"],
        "surface_disabled": palette["field"],
        "border": palette["stroke"],
        "text": palette["text"],
        "text_disabled": palette["muted"],
        "primary": primary,
        "primary_hover": hover,
        "primary_pressed": pressed,
        "on_primary": foreground,
        "on_primary_disabled": palette["muted"],
        "focus": palette["accent"],
        "shadow": palette["bg"],
        "top_highlight": palette["stroke"],
        "primary_highlight": palette["stroke"],
    }


# The three ways speech can be transcribed, as they are offered on first run.
#
# Speed is stated because it is the largest difference between them and the
# only one somebody cannot discover before choosing. Measured on one machine
# against the same 5-second clip, timed from the end of the recording:
#
#     Deepgram, streaming      119-413 ms, text arriving while you speak
#     bundled local, batch     938-1647 ms
#
# 2026-09-22: Talk DAT! is free, with no trial and no paid tier. Local is
# the default; your own provider key is the other lane, billed by that
# provider and nobody else.
#
# Defined once. This block was written out twice, and a correction to one copy
# would have quietly missed the other -- the same fault that made the download
# message say two different things in 0.4.26.
ROUTE_CARDS: dict[str, tuple[str, str, str]] = {
    "local": (
        "Private on-device",
        "START HERE",
        # X-176 once took "free" out of this card because a weekly cap and a
        # paid Local Forever sat behind it. 2026-09-22: both are gone, so the
        # card can say what is now simply true.
        "Every local model, offline, free and yours forever. Audio never leaves "
        f"{platform_copy.THIS_COMPUTER}. Nothing to sign up for, and no limit on use.",
    ),
    "byok": (
        "Bring your own",
        "YOUR KEY",
        "Your own provider key, billed by your provider. Streaming text "
        "while you speak, on your own account.",
    ),
}


def _rounded_rectangle(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
    **kwargs: Any,
) -> int:
    radius = max(0.0, min(float(radius), (x2 - x1) / 2, (y2 - y1) / 2))
    points = (
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
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


class OnboardingWizard:
    """Guided first-run setup that rehearses the real Talk DAT! input path."""

    def __init__(self, host: Any) -> None:
        self.host = host
        self.config = host.config
        if not isinstance(self.config.get("onboarding"), dict):
            self.config["onboarding"] = {}
        # Every pixel constant in this file was tuned at 96 DPI. Under DPI
        # awareness a pixel is a physical pixel, so they all pass through here.
        self.px = lambda value: ui_scale.px(value, host.config)
        ui = self.config.setdefault("ui", {})
        self.theme = host._settings_theme_key(str(ui.get("settings_theme") or ui.get("theme") or "Flow Dark"))
        self.palette = host._settings_palette(self.theme)
        # Sized to the screen it is on, not to the 1040x720 it was designed
        # at. On a large display nothing changes; on a small or scaled one
        # the window takes at most ~86% of the work area and everything
        # inside wraps against self.fit instead of design-time widths.
        try:
            _l, _t, _r, _b = host._logical_work_area()
            avail_w = max(320, _r - _l)
            avail_h = max(220, _b - _t)
        except Exception:
            avail_w, avail_h = 1920, 1080
        design_w, design_h = 1040, 720
        win_w = min(design_w, int(avail_w * 0.86))
        win_h = min(design_h, int(avail_h * 0.86))
        self.fit = min(1.0, win_w / design_w, win_h / design_h)
        self.window = host._utility_window(
            "onboarding",
            "Talk DAT! Setup",
            f"{win_w}x{win_h}",
            bg=self.palette["bg"],
            resizable=True,
            # mac-port already clamped the MINIMUM against the available
            # screen, which X-535 does not do: X-535 caps the geometry and the
            # restored size, so a 840x620 logical minimum could still exceed a
            # small display. Both halves are kept.
            minimum_size=(min(840, max(320, avail_w - 40)), min(620, max(220, avail_h - 40))),
            # X-535: a setup wizard opens at the size it was designed for.
            # It is a sequence a person walks once, not a document they keep,
            # and remembering a size meant remembering one grown to fit the
            # tallest step -- which then opened that big on step one, forever.
            remember_size=False,
        )
        if self.window is None:
            return

        self.window._talk_dat_onboarding = self  # type: ignore[attr-defined]
        self.step_index = 0
        self.photos: list[ImageTk.PhotoImage] = []
        self.dynamic_photos: dict[str, ImageTk.PhotoImage] = {}
        self.art_sources: dict[str, Image.Image] = {}
        self._art_render_state: dict[int, dict[str, Any]] = {}
        self._content_extent_after: str | None = None
        # X-460: one fit per step render; the receipt is the step index
        # the last fit served, so a Configure storm never re-grows.
        self._fit_after: str | None = None
        self._fit_served_step: int | None = None
        self._fit_tries = 0
        self._extent_retries = 0
        self._content_extent_signature: tuple[int, int, int] | None = None
        self.status_var = tk.StringVar(value="")
        self.route_status_var = tk.StringVar(value="")
        self.mic_status_var = tk.StringVar(value="Select an input, then start the private level check when you are ready.")
        self.control_status_var = tk.StringVar(
            value="HOLD the key below and watch it light. Release to finish."
            if mac_support.IS_MAC and primary_hotkey(host.config) == ("fn",)
            else f"Press and hold {self._chord_text()}. Each key lights independently."
        )
        # X-103: "Ready when you are" told the first outside user nothing --
        # he did not know WHICH keys or that holding (not tapping) is the
        # gesture. Name the chord and the motion, every time.
        self.practice_status_var = tk.StringVar(value=f"HOLD {self._chord_text()} while you speak, release to finish. Your test stays inside this setup window.")
        self.access_status_var = tk.StringVar(value=f"Checking {platform_copy.THIS_COMPUTER} for an existing Talk DAT! account...")
        self.access_choice = selected_access_choice(self.config)
        self.account_after: str | None = None
        self.account_activation_started = False
        # A config that already CHOSE a provider keeps its choice. X-516: no
        # managed route any more; what the config resolves to is what the
        # person gets.
        initial_route = self._route_for_provider(selected_provider_id(self.config))
        self.route_var = tk.StringVar(value=initial_route)
        self.writing_var = tk.StringVar(value=selected_writing_preset(self.config))
        # Owner decision 2026-09-23: the anonymous usage counts get their own
        # switch (privacy.share_usage_counts), mentioned once above Finish.
        from ..official_build import share_usage_counts

        self.share_counts_var = tk.BooleanVar(value=share_usage_counts(self.config))
        self.microphone_tested = False
        self.hotkey_rehearsed = False
        self.dictation_tested = False
        self.destroyed = False
        self.meter_state: dict[str, Any] = {
            "stream": None,
            "after": None,
            "opening": False,
            "closing": False,
            "on_closed": None,
            "generation": 0,
            "level": 0.0,
            "peak": 0.0,
            "wave": [0.0] * 64,
            "error": "",
        }
        self._microphone_query_generation = 0
        self.key_after: str | None = None
        self.test_after: str | None = None
        self.permission_after: str | None = None
        self.permission_index = 0
        self.keyboard_pressed: set[str] = set()
        self.test_started_by_button = False
        self.practice_baseline = ""
        # Bound methods are new objects every time they are accessed. Keep one
        # stable callback object so teardown can prove it still owns the sink.
        self.test_sink = self._receive_test_result

        active_provider = selected_provider_id(self.config)
        byok_provider = active_provider if active_provider in FLAGSHIP_CLOUD_PROVIDER_IDS else "deepgram"
        self.provider_holder = {"id": byok_provider}
        settings = provider_settings(self.config, byok_provider)
        model_id = selected_model_id(self.config, byok_provider)
        self.provider_var = tk.StringVar(value=provider_label(byok_provider))
        self.model_var = tk.StringVar(value=model_label(byok_provider, model_id))
        self.variant_var = tk.StringVar(value=selected_variant(self.config, byok_provider))
        self.key_var = tk.StringVar(value=str(settings.get("api_key", "")))
        self.language_var = tk.StringVar(
            value=str(settings.get("language") or self.config.get("deepgram", {}).get("language", "en-US"))
        )
        current_device = str(self.config.setdefault("audio", {}).get("input_device", "")).strip()
        self.audio_device_var = tk.StringVar(value=current_device or WINDOWS_DEFAULT_MIC)

        self._build_shell()
        self.render_step(self._resume_step_index())

    def _button_palette(self, master: tk.Misc | None = None) -> dict[str, str]:
        canvas = self.palette["bg"]
        if master is not None:
            with contextlib.suppress(Exception):
                canvas = str(master.cget("bg"))
        return accessible_control_palette(self.palette, canvas=canvas)

    def _chord_text(self) -> str:
        """The actual trigger keys as words -- "Ctrl + Win", never "trigger"."""
        try:
            labels = hotkey_labels(primary_hotkey(self.config))
            if labels:
                return " + ".join(labels)
        except Exception:
            pass
        return "Ctrl + Win"

    def _resume_step_index(self) -> int:
        """Where to start: the saved place for an unfinished setup, else 0.

        X-102, straight from the first outside Mac user: he closed the wizard
        partway, relaunched, and was marched through from step zero -- asked
        again for things he had already done. Every step transition records
        its place (see render_step); this restores it, along with what was
        already proven, so quitting -- deliberately or via a crash -- costs
        nothing. A COMPLETED setup that reopens the wizard starts at 0 on
        purpose: that person came back to walk it, not to resume it.
        """
        onboarding = self.config.get("onboarding", {})
        if onboarding.get("completed"):
            return 0
        saved_id = str(onboarding.get("resume_step_id") or "").strip()
        saved = next(
            (index for index, step in enumerate(ONBOARDING_STEPS) if step.id == saved_id),
            -1,
        )
        if saved < 0:
            try:
                saved = int(onboarding.get("resume_step", 0) or 0)
            except (TypeError, ValueError):
                saved = 0
        saved = max(0, min(len(ONBOARDING_STEPS) - 1, saved))
        flags = onboarding.get("resume_flags", {})
        if saved > 0 and isinstance(flags, dict):
            self.microphone_tested = flags.get("microphone_tested") is True
            self.hotkey_rehearsed = flags.get("hotkey_rehearsed") is True
            self.dictation_tested = flags.get("dictation_tested") is True
            route = str(flags.get("route", "")).strip()
            if route:
                self.route_var.set(route)
            access = str(flags.get("access_choice", "")).strip()
            if access:
                self.access_choice = access
        return saved

    def _store_resume_receipt(self) -> None:
        """Persist semantic progress and any proof earned on the current page."""

        if self.config.get("onboarding", {}).get("completed"):
            return
        candidate = copy.deepcopy(self.config)
        onboarding = candidate.setdefault("onboarding", {})
        onboarding["resume_step"] = self.step_index  # legacy readers
        onboarding["resume_step_id"] = ONBOARDING_STEPS[self.step_index].id
        onboarding["resume_flags"] = {
            "microphone_tested": self.microphone_tested,
            "hotkey_rehearsed": self.hotkey_rehearsed,
            "dictation_tested": self.dictation_tested,
            "route": self.route_var.get(),
            "access_choice": self.access_choice,
        }
        self._save_setup(candidate)

    def _build_shell(self) -> None:
        window = self.window
        palette = self.palette
        window.configure(bg=palette["bg"])
        self.host._style_settings_widgets(window, palette)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(2, weight=1)

        self.header = tk.Frame(window, height=self.px(72), bg=palette["bg"], bd=0, highlightthickness=0)
        self.header.grid(row=0, column=0, sticky="ew", padx=self.px(16), pady=(self.px(12), 0))
        self.header.grid_propagate(False)
        self.header.columnconfigure(1, weight=1)
        self.header.rowconfigure(0, weight=1)
        icon_holder = tk.Label(self.header, bg=palette["bg"], bd=0, highlightthickness=0)
        icon_holder.grid(row=0, column=0, sticky="w", padx=(self.px(12), self.px(16)))
        icon_path = Path(__file__).resolve().parents[1] / "assets" / "app_icon.png"
        try:
            source = Image.open(icon_path).convert("RGBA")
            self.art_sources["header-icon"] = source
            icon = ImageOps.contain(source, (self.px(40), self.px(40)), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(icon, master=icon_holder)
            self.header_photo = photo
            icon_holder.configure(image=photo)
        except Exception:
            icon_holder.configure(text="Talk DAT!", fg=palette["text"], font=(BRAND_UI_FAMILY, type_scale.SUBHEADING, "bold"))

        header_copy = tk.Frame(self.header, bg=palette["bg"], bd=0, highlightthickness=0)
        header_copy.grid(row=0, column=1, sticky="w")
        title_label = tk.Label(
            header_copy,
            text="Talk DAT!",
            bg=palette["bg"],
            fg=palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.HEADING, "bold"),
            anchor="w",
        )
        title_label.pack(anchor="w")
        self.header_subtitle_var = tk.StringVar(value=self._header_subtitle())
        subtitle_label = tk.Label(
            header_copy,
            textvariable=self.header_subtitle_var,
            bg=palette["bg"],
            fg=palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.SECONDARY),
            anchor="w",
        )
        subtitle_label.pack(anchor="w", pady=(self.px(4), 0))
        header_actions = tk.Frame(
            self.header,
            bg=palette["bg"],
            bd=0,
            highlightthickness=0,
        )
        header_actions.grid(row=0, column=2, sticky="e", padx=(self.px(12), self.px(8)))
        # X-401: the help chip anchors to the LEFT of these controls. Without
        # this it was placed 156px from the window edge and sat on Minimize.
        self.window._header_actions = header_actions  # type: ignore[attr-defined]
        # A custom-chrome window whose caption controls are 92px and 76px word
        # buttons reads as a hobby project; every premium custom-chrome app
        # draws a glyph in a caption lane. These are the app's OWN shared
        # controls -- the same drawn minus and X, the same 44x32 lane, the same
        # palette hover with danger on close -- rather than a second pair
        # hand-rolled here, so the wizard's titlebar and every other Talk DAT!
        # titlebar are one control set. They stay native tk.Buttons, so keyboard
        # focus, Enter/Space activation and the accessible name ("Minimize",
        # "Close window") all survive the change from words to glyphs.
        minimize_button = self.host._minimize_control(
            self.window,
            header_actions,
            palette["bg"],
            width=44,
        )
        minimize_button.pack(side="left")
        close_button = self.host._close_control(
            self.window,
            header_actions,
            palette["bg"],
        )
        close_button.pack(side="left", padx=(self.px(8), 0))
        separator = tk.Frame(self.header, height=1, bg=palette["stroke"], bd=0, highlightthickness=0)
        separator.place(relx=0, rely=1.0, relwidth=1.0, y=-1)
        self.host._bind_utility_drag_handle(
            window,
            self.header,
            icon_holder,
            header_copy,
            title_label,
            subtitle_label,
        )

        self.progress = tk.Canvas(window, height=self.px(48), bg=palette["bg"], bd=0, highlightthickness=0)
        self.progress.grid(row=1, column=0, sticky="ew", padx=self.px(24), pady=(self.px(4), self.px(8)))
        self.progress.bind("<Configure>", lambda _event: self._draw_progress())

        self.content_shell = tk.Frame(window, bg=palette["bg"], bd=0, highlightthickness=0)
        self.content_shell.grid(row=2, column=0, sticky="nsew", padx=self.px(24), pady=(0, self.px(12)))
        self.content_shell.columnconfigure(0, weight=1)
        self.content_shell.rowconfigure(0, weight=1)
        self.content_canvas = tk.Canvas(
            self.content_shell,
            bg=palette["panel"],
            bd=0,
            highlightthickness=1,
            highlightbackground=palette["stroke"],
            yscrollincrement=max(1, self.px(28)),
        )
        self.content_canvas.grid(row=0, column=0, sticky="nsew")
        self.content_scrollbar = ttk.Scrollbar(
            self.content_shell,
            orient="vertical",
            command=self.content_canvas.yview,
            style="Flow.Vertical.TScrollbar",
        )
        self.content_scrollbar.grid(row=0, column=1, sticky="ns", padx=(self.px(4), 0))
        self.content_scrollbar.grid_remove()
        self.content_canvas.configure(yscrollcommand=self._content_yview_changed)
        self.content = tk.Frame(self.content_canvas, bg=palette["panel"], bd=0, highlightthickness=0)
        self.content_window = self.content_canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(1, weight=1)
        self.content_canvas.bind("<Configure>", self._queue_content_extent_sync, add="+")
        self.content.bind("<Configure>", self._queue_content_extent_sync, add="+")
        install_resize_proxy = getattr(self.host, "_install_resize_visual_proxy", None)
        if callable(install_resize_proxy):
            install_resize_proxy(self.window, self.content_shell)

        footer = tk.Frame(window, bg=palette["bg"], bd=0, highlightthickness=0)
        footer.grid(row=3, column=0, sticky="ew", padx=self.px(24), pady=(0, self.px(16)))
        footer.columnconfigure(1, weight=1)
        self.back_button = AtelierButton(
            footer,
            text="Back",
            command=self.previous_step,
            palette=self._button_palette(footer),
            primary=False,
            min_width=104,
            scale=self.px(100) / 100.0,
        )
        self.back_button.grid(row=0, column=0, sticky="w")
        tk.Label(
            footer,
            textvariable=self.status_var,
            bg=palette["bg"],
            fg=palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.SECONDARY),
            anchor="e",
            justify="right",
            wraplength=self.px(520),
        ).grid(row=0, column=1, sticky="ew", padx=self.px(20))
        self.next_button = AtelierButton(
            footer,
            text="Continue",
            command=self.next_step,
            palette=self._button_palette(footer),
            primary=True,
            min_width=132,
            scale=self.px(100) / 100.0,
        )
        self.next_button.grid(row=0, column=2, sticky="e")

        window.bind("<KeyPress>", self._key_press, add="+")
        window.bind("<KeyRelease>", self._key_release, add="+")
        window.bind("<Alt-Left>", lambda _event: self.previous_step(), add="+")
        window.bind("<Alt-Right>", lambda _event: self.next_step(), add="+")
        window.bind("<MouseWheel>", self._scroll_content, add="+")
        window.bind("<<TalkDATGeometrySettled>>", self._settle_art_panels, add="+")
        window.bind("<Destroy>", self._on_destroy, add="+")

    def _content_yview_changed(self, first: str, last: str) -> None:
        self.content_scrollbar.set(first, last)
        if float(first) <= 0.01 and float(last) - float(first) >= 0.99:
            self.content_scrollbar.grid_remove()
        else:
            self.content_scrollbar.grid()

    def _sync_content_extent(self, _event: tk.Event | None = None) -> None:
        if self.destroyed or not self.content_canvas.winfo_exists():
            return
        width = max(1, self.content_canvas.winfo_width())
        viewport_height = max(1, self.content_canvas.winfo_height())
        required_height = max(viewport_height, self.content.winfo_reqheight())
        signature = (width, viewport_height, required_height)
        if signature == self._content_extent_signature:
            return
        self._content_extent_signature = signature
        self.content_canvas.itemconfigure(
            self.content_window,
            width=width,
            height=required_height,
        )
        self.content_canvas.configure(scrollregion=(0, 0, width, required_height))

    def _queue_content_extent_sync(self, _event: tk.Event | None = None) -> None:
        """Collapse the canvas and child Configure pair into one idle layout."""

        if self.destroyed or self._content_extent_after is not None:
            return

        def apply() -> None:
            self._content_extent_after = None
            self._sync_content_extent()
            # X-460c: a measurement taken while any label is still wrapped
            # at 1 px (its master unmapped) is a skyscraper, and the
            # signature dedup would keep it for good. Measure again shortly,
            # as the ONE pending callback, until the wrap settles.
            retries = int(getattr(self, "_extent_retries", 0))
            if self._labels_still_wrapping() and retries < 20:
                self._extent_retries = retries + 1
                self._content_extent_signature = None
                with contextlib.suppress(tk.TclError):
                    self._content_extent_after = self.window.after(60, apply)
                return
            self._extent_retries = 0

        try:
            self._content_extent_after = self.window.after_idle(apply)
        except tk.TclError:
            self._content_extent_after = None

    def _queue_fit_to_step(self) -> None:
        """One fit per step render, after Tk has laid the content out."""
        if self.destroyed:
            return
        if self._fit_after is not None:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(self._fit_after)
            self._fit_after = None
        self._fit_tries = 0
        try:
            self._fit_after = self.window.after(80, self._fit_window_to_step)
        except tk.TclError:
            self._fit_after = None

    def _work_area_bottom(self) -> int:
        """The lowest screen pixel a window may occupy on this monitor."""
        work_area = None
        finder = getattr(self.host, "_active_monitor_work_area", None)
        if callable(finder):
            with contextlib.suppress(Exception):
                work_area = finder()
        if work_area is not None:
            return int(work_area[3])
        # No monitor API (the Mac, a headless test): the screen less a
        # taskbar-sized margin.
        return int(self.window.winfo_screenheight()) - self.px(48)

    def _grow_ceiling(self) -> int | None:
        """The tallest this window may grow itself to, or None for no ceiling.

        The ceiling is a SHARE OF THE WORK AREA, so it only exists when the
        work area does. Falling back to `winfo_screenheight()` looked harmless
        and was not: it imposed a bound on hosts that have no monitor API --
        the capture host, the Mac -- where `_work_area_bottom()` was already
        the agreed answer. That took a clean 3617-test suite to two failures,
        because two 200% layout tests then measured a tree that had settled
        differently from the one they were written against.
        """
        finder = getattr(self.host, "_active_monitor_work_area", None)
        if not callable(finder):
            return None
        with contextlib.suppress(Exception):
            area = finder()
            if area:
                height = int(area[3]) - int(area[1])
                if height > 0:
                    return int(height * ui_scale.OPENING_SHARE_OF_WORK_AREA)
        return None

    def _fit_window_to_step(self) -> None:
        """X-460: grow the window by the step's overflow, as far as the
        monitor's work area allows. Grow only, once per step render, so a
        person who shrinks the window by hand keeps their size and gets the
        scrollbar back."""
        self._fit_after = None
        if self.destroyed or not self.content_canvas.winfo_exists():
            return
        if self._fit_served_step == self.step_index:
            return
        # X-460c: never measure a tree whose labels are still wrapped at
        # 1 px; wait for the wrap, a dozen tries at most.
        if self._labels_still_wrapping() and self._fit_tries < 12:
            self._fit_tries += 1
            with contextlib.suppress(tk.TclError):
                self._fit_after = self.window.after(60, self._fit_window_to_step)
            return
        self._fit_served_step = self.step_index
        try:
            self.window.update_idletasks()
            self._verify_content_extent()
            viewport_height = int(self.content_canvas.winfo_height())
            required_height = int(self.content.winfo_reqheight())
            if viewport_height <= 1 or required_height <= viewport_height:
                return
            overflow = required_height - viewport_height + self.px(4)
            width = int(self.window.winfo_width())
            height = int(self.window.winfo_height())
            x = int(self.window.winfo_x())
            y = int(self.window.winfo_y())
            bottom = self._work_area_bottom()
            # X-535: growing to spare somebody a scrollbar is a courtesy, and
            # it stops well before the window owns the screen. The scroll view
            # handles the rest, which is what it is for.
            ceiling = self._grow_ceiling()
            if ceiling is not None:
                bottom = min(bottom, y + ceiling)
            room = bottom - (y + height) - self.px(8)
            # No early return when there is no room left. `max(0, room)` below
            # already yields a zero grow, and returning here would skip
            # `_fold_art_band` -- the step that moves a short decorative band
            # out of the way when the screen cannot hold everything. Skipping
            # it left two 200% layout tests measuring a tree that had never
            # settled, and the full suite went from clean to two failures.
            grow = min(overflow, max(0, room))
            # When the window already sits low, pull it up to make the room.
            if grow < overflow and y > self.px(24):
                lift = min(overflow - grow, y - self.px(24))
                y -= lift
                grow += lift
            if grow >= self.px(8):
                self.window.geometry(f"{width}x{height + grow}+{x}+{y}")
            # X-460b: the screen could not hold all of it. A short art band
            # (120 logical px or less) is decoration and steps aside before
            # the person is asked to scroll past real content.
            if grow < overflow:
                self._fold_art_band(overflow - grow)
        except tk.TclError:
            return

    def _fold_art_band(self, remaining: int) -> None:
        stack: list[tk.Misc] = [self.content]
        while stack:
            widget = stack.pop()
            with contextlib.suppress(tk.TclError):
                stack.extend(widget.winfo_children())
            art_height = getattr(widget, "_talkdat_art_height", None)
            if art_height is None or int(art_height) > 120:
                continue
            try:
                if widget.winfo_manager() == "grid":
                    widget.grid_remove()
                elif widget.winfo_manager() == "pack":
                    widget.pack_forget()
                else:
                    continue
            except tk.TclError:
                continue
            remaining -= self.px(int(art_height))
            if remaining <= 0:
                return

    def _verify_content_extent(self) -> None:
        if self.destroyed or not self.content_canvas.winfo_exists():
            return
        self._content_extent_signature = None
        self._sync_content_extent()

    def _labels_still_wrapping(self) -> bool:
        """True while any label is wrapped at 1-2 px: its master has not
        been laid out yet, so every height in the tree is a lie."""
        content = getattr(self, "content", None)
        if content is None:
            return False
        stack: list[tk.Misc] = [content]
        try:
            while stack:
                widget = stack.pop()
                stack.extend(widget.winfo_children())
                if isinstance(widget, tk.Label) and 0 < int(widget.cget("wraplength")) <= 2:
                    return True
        except Exception:
            # A fake or a dying widget: nothing to wait for.
            return False
        return False

    def _cancel_content_extent_sync(self) -> None:
        fit = self._fit_after
        self._fit_after = None
        if fit:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(fit)
        receipt = self._content_extent_after
        self._content_extent_after = None
        if receipt:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(receipt)

    def _scroll_content(self, event: tk.Event) -> str | None:
        canvas = getattr(self, "content_canvas", None)
        shell = getattr(self, "content_shell", None)
        if canvas is None or shell is None or not canvas.winfo_exists():
            return None
        pointer_x = self.window.winfo_pointerx()
        pointer_y = self.window.winfo_pointery()
        inside = (
            shell.winfo_rootx() <= pointer_x < shell.winfo_rootx() + shell.winfo_width()
            and shell.winfo_rooty() <= pointer_y < shell.winfo_rooty() + shell.winfo_height()
        )
        first, last = canvas.yview()
        if not inside or last - first >= 0.99:
            return None
        delta = int(getattr(event, "delta", 0))
        if not delta:
            return None
        canvas.yview_scroll(-1 if delta > 0 else 1, "units")
        return "break"

    def _header_subtitle(self) -> str:
        """What the window is. Where you are is the band under it.

        This used to read ``Step 3 of 10  |  Tune your microphone`` -- a pipe
        with two literal spaces on each side doing the work of a component,
        and repeating a step title that is already set at display size two
        inches below it. The three parts now read down the window in order:
        the count and the segmented bar in `_draw_progress`, then the step
        title as the page heading in `_page_heading`. Nothing says it twice.
        """

        return "Setup"

    def _step_caption(self) -> str:
        return f"Step {self.step_index + 1} of {len(ONBOARDING_STEPS)}"

    def _chapter_index(self, step_id: str | None = None) -> int:
        current = step_id or ONBOARDING_STEPS[self.step_index].id
        for index, (_label, members) in enumerate(ONBOARDING_CHAPTERS):
            if current in members:
                return index
        return 0

    def _draw_header(self) -> None:
        if self.destroyed:
            return
        self.header_subtitle_var.set(self._header_subtitle())

    def _draw_progress(self) -> None:
        """One segment per step: done, current, still to come.

        The chapter names above four wide bars said where you were in a
        grouping nobody had been told about, and the actual count lived in the
        header as a pipe-separated string. A person in setup wants one thing
        from this band -- how much is left -- and a bar with a segment per step
        answers it without being read. The chapter name stays as the quiet
        right-hand label, because "Voice" is still a useful thing to know when
        the bar tells you you are four along.
        """

        if self.destroyed:
            return
        canvas = self.progress
        canvas.delete("all")
        width = max(self.px(560), canvas.winfo_width())
        left = self.px(8)
        right = width - self.px(8)
        caption_y = self.px(12)

        canvas.create_text(
            left,
            caption_y,
            text=self._step_caption(),
            anchor="w",
            fill=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.CAPTION),
        )
        chapter_label = ONBOARDING_CHAPTERS[self._chapter_index()][0]
        canvas.create_text(
            right,
            caption_y,
            text=chapter_label,
            anchor="e",
            fill=self.palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.CAPTION, "bold"),
        )

        total = len(ONBOARDING_STEPS)
        gap = self.px(4)
        track = right - left
        segment_w = (track - gap * (total - 1)) / total
        bar_top = self.px(28)
        bar_bottom = self.px(32)
        for index in range(total):
            x1 = left + index * (segment_w + gap)
            if index < self.step_index:
                fill = self.palette["accent2"]
            elif index == self.step_index:
                fill = self.palette["accent"]
            else:
                fill = self.palette["stroke"]
            canvas.create_rectangle(x1, bar_top, x1 + segment_w, bar_bottom, fill=fill, outline="")

    def _clear_content(self) -> None:
        with contextlib.suppress(Exception):
            self.content_canvas.yview_moveto(0.0)
        self._stop_page_activity()
        self._cancel_all_art_panel_draws()
        for child in self.content.winfo_children():
            child.destroy()
        self.photos.clear()
        self.dynamic_photos.clear()
        self._content_extent_signature = None

    def _page_heading(self) -> tk.Frame:
        step = ONBOARDING_STEPS[self.step_index]
        heading = tk.Frame(self.content, bg=self.palette["panel"], bd=0, highlightthickness=0)
        heading.grid(row=0, column=0, sticky="ew", padx=self.px(28), pady=(self.px(20), self.px(12)))
        heading.columnconfigure(0, weight=1)
        title_label = tk.Label(
            heading,
            text=step.title,
            bg=self.palette["panel"],
            fg=self.palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.DISPLAY, "bold"),
            anchor="w",
            justify="left",
        )
        title_label.grid(row=0, column=0, sticky="ew")
        description_label = tk.Label(
            heading,
            text=step.description,
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.BODY),
            anchor="w",
            justify="left",
        )
        description_label.grid(row=1, column=0, sticky="ew", pady=(self.px(4), 0))
        self._bind_responsive_wrap(title_label, heading, maximum=860, initial=320)
        self._bind_responsive_wrap(description_label, heading, maximum=860, initial=320)
        return heading

    def _bind_responsive_wrap(
        self,
        label: tk.Label,
        master: tk.Misc,
        *,
        maximum: int,
        reserve: int = 0,
        initial: int = 180,
    ) -> None:
        """Keep label wrapping inside the pixels its parent actually owns.

        A fixed logical wrap length becomes wider than the entire viewport at
        200% scaling. Start conservatively so the label cannot enlarge its
        grid before the first layout pass, then follow the real parent width.
        """

        maximum_pixels = self.px(maximum)
        reserve_pixels = self.px(reserve) if reserve else 0
        initial_pixels = min(maximum_pixels, self.px(initial))
        label.configure(wraplength=max(1, initial_pixels))

        def apply(width: int | None = None) -> None:
            try:
                available = int(width if width is not None else master.winfo_width()) - reserve_pixels
                target = max(1, min(maximum_pixels, available))
                current = int(label.cget("wraplength"))
                # A one-pixel expansion can pull a whole word onto the prior
                # line, enlarge the parent's requested width, and then undo
                # itself on the next Configure event.  At 150% that formed an
                # endless 806/807px art-panel oscillation. Shrinks remain
                # immediate so text never escapes its viewport; growth waits
                # for a small DPI-scaled margin so layout reaches a fixed point.
                growth_margin = max(2, self.px(4))
                if target < current or target - current >= growth_margin:
                    label.configure(wraplength=target)
                    self._queue_content_extent_sync()
            except tk.TclError:
                return

        master.bind("<Configure>", lambda event: apply(event.width), add="+")
        self.window.after_idle(apply)

    def _art_panel(
        self,
        master: tk.Misc,
        art_key: str,
        *,
        height: int = 220,
        centering: tuple[float, float] = (0.5, 0.5),
    ) -> tk.Canvas:
        """A theme-safe product stage for generated, text-free artwork.

        The art always lives inside its own dark photographic world. Interface
        labels, selection and status remain native widgets outside the image,
        so every theme keeps readable text and keyboard state.
        """
        canvas = tk.Canvas(
            master,
            width=1,
            height=self.px(height),
            bg=self.palette["panel"],
            bd=0,
            highlightthickness=0,
        )
        # X-460b: the fit knows which canvases are decoration it may fold.
        canvas._talkdat_art_height = height  # type: ignore[attr-defined]
        canvas.bind(
            "<Configure>",
            lambda event, target=canvas, key=art_key, anchor=centering: self._queue_art_panel_draw(
                target,
                key,
                anchor,
                event,
            ),
            add="+",
        )
        canvas.bind(
            "<Destroy>",
            lambda event, target=canvas, key=art_key: self._forget_art_panel(target, key)
            if event.widget is target
            else None,
            add="+",
        )
        return canvas

    def _art_panel_size(self, canvas: tk.Canvas, event: tk.Event | None = None) -> tuple[int, int]:
        event_width = int(getattr(event, "width", 0) or 0)
        event_height = int(getattr(event, "height", 0) or 0)
        width = event_width if event_width > 0 else canvas.winfo_width()
        height = event_height if event_height > 0 else canvas.winfo_height()
        return max(1, width), max(self.px(120), height)

    def _queue_art_panel_draw(
        self,
        canvas: tk.Canvas,
        art_key: str,
        centering: tuple[float, float] = (0.5, 0.5),
        event: tk.Event | None = None,
        *,
        settled: bool = False,
    ) -> None:
        """Render the first frame at idle and one final frame after a resize.

        Tk can emit dozens of Configure events during a single pointer move.
        Replacing the artwork on each event made the old image disappear while
        the next Lanczos crop was still being built. This trailing-edge queue
        leaves the complete frame visible, ignores duplicate sizes, and owns a
        single cancellable callback per canvas.
        """

        if self.destroyed:
            return
        try:
            if not canvas.winfo_exists():
                return
            target_size = self._art_panel_size(canvas, event)
        except tk.TclError:
            return

        state_key = id(canvas)
        state = self._art_render_state.setdefault(
            state_key,
            {
                "after": None,
                "queued_size": None,
                "rendered_size": None,
                "measured_size": None,
                "canvas": canvas,
                "art_key": art_key,
                "centering": centering,
            },
        )
        state["canvas"] = canvas
        state["art_key"] = art_key
        state["centering"] = centering
        receipt = state.get("after")
        rendered_size = state.get("rendered_size")
        if rendered_size == target_size:
            if receipt:
                with contextlib.suppress(tk.TclError):
                    self.window.after_cancel(receipt)
            state["after"] = None
            state["queued_size"] = None
            return
        if receipt and state.get("queued_size") == target_size:
            return
        if receipt:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(receipt)
            state["after"] = None
        state["queued_size"] = target_size

        # Manual borderless resizing has an exact press/release lifecycle in
        # the shared utility shell. Do not race a timer against the pointer;
        # the shell emits TalkDATGeometrySettled on release and this canvas
        # paints exactly once on the following idle turn.
        if getattr(self.window, "_talkdat_live_resize", False) and not settled:
            return

        def render_settled_size() -> None:
            current = self._art_render_state.get(state_key)
            if current is not state:
                return
            state["after"] = None
            if self.destroyed:
                return
            # The timer may have been queued just before a new resize press.
            # Keep the complete old frame and leave queued_size intact; the
            # shell's exact release event calls _settle_art_panels and performs
            # the one final Lanczos render.
            if getattr(self.window, "_talkdat_live_resize", False):
                return
            state["queued_size"] = None
            try:
                if not canvas.winfo_exists():
                    return
                actual_size = self._art_panel_size(canvas)
            except tk.TclError:
                return
            try:
                shell_height = max(1, int(self.window.winfo_height()))
            except (AttributeError, tk.TclError, TypeError, ValueError):
                shell_height = 0
            if shell_height > 1 and actual_size[1] > shell_height:
                # Scroll canvases briefly report the inner document's requested
                # height before the actual viewport wins negotiation. An art
                # panel cannot legitimately be taller than its whole window;
                # wait instead of rendering the transient 2,000-3,000px box.
                state["measured_size"] = actual_size
                state["queued_size"] = actual_size
                with contextlib.suppress(tk.TclError):
                    state["after"] = self.window.after(16, render_settled_size)
                return
            # A first idle can still observe the scroll frame's requested
            # content height (several thousand pixels) before the viewport is
            # negotiated. Rendering that transient box wastes a multi-megapixel
            # Lanczos pass and briefly shows the wrong crop. Require the same
            # measured viewport on two event-loop turns before first paint.
            if state.get("rendered_size") is None and not settled:
                if state.get("measured_size") != actual_size:
                    state["measured_size"] = actual_size
                    state["queued_size"] = actual_size
                    with contextlib.suppress(tk.TclError):
                        state["after"] = self.window.after(
                            16,
                            render_settled_size,
                        )
                    return
            if state.get("rendered_size") == actual_size:
                return
            self._draw_art_panel(canvas, art_key, centering)

        try:
            if rendered_size is None or settled:
                state["after"] = self.window.after_idle(render_settled_size)
            else:
                state["after"] = self.window.after(ART_RESIZE_SETTLE_MS, render_settled_size)
        except tk.TclError:
            state["after"] = None
            state["queued_size"] = None

    def _settle_art_panels(self, _event: tk.Event | None = None) -> None:
        """Commit the final artwork frame after the shell releases resize."""

        if self.destroyed:
            return
        for state in tuple(self._art_render_state.values()):
            canvas = state.get("canvas")
            art_key = state.get("art_key")
            centering = state.get("centering", (0.5, 0.5))
            if canvas is None or not art_key:
                continue
            self._queue_art_panel_draw(canvas, art_key, centering, settled=True)

    def _forget_art_panel(self, canvas: tk.Canvas, art_key: str) -> None:
        state = self._art_render_state.pop(id(canvas), None)
        receipt = state.get("after") if state else None
        if receipt:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(receipt)
        self.dynamic_photos.pop(f"art:{art_key}:{id(canvas)}", None)

    def _cancel_all_art_panel_draws(self) -> None:
        for state in tuple(self._art_render_state.values()):
            receipt = state.get("after")
            if receipt:
                with contextlib.suppress(tk.TclError):
                    self.window.after_cancel(receipt)
        self._art_render_state.clear()

    def _draw_art_panel(
        self,
        canvas: tk.Canvas,
        art_key: str,
        centering: tuple[float, float] = (0.5, 0.5),
    ) -> None:
        if self.destroyed or not canvas.winfo_exists():
            return
        filename = ONBOARDING_ART.get(art_key, art_key)
        path = ONBOARDING_ASSET_DIR / filename
        width = max(1, canvas.winfo_width())
        height = max(self.px(120), canvas.winfo_height())
        try:
            source = self.art_sources.get(filename)
            if source is None:
                source = Image.open(path).convert("RGB")
                self.art_sources[filename] = source
            image = ImageOps.fit(
                source,
                (width, height),
                method=Image.Resampling.LANCZOS,
                centering=centering,
            ).convert("RGBA")
            mask = Image.new("L", (width, height), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, width - 1, height - 1),
                radius=max(self.px(10), 1),
                fill=255,
            )
            image.putalpha(mask)
            photo = ImageTk.PhotoImage(image, master=canvas)
            key = f"art:{art_key}:{id(canvas)}"
            self.dynamic_photos[key] = photo
            # The expensive frame is complete. Swap it in only now so a live
            # resize never exposes a half-painted or empty artwork panel.
            canvas.delete("all")
            canvas.create_image(0, 0, image=photo, anchor="nw")
        except Exception:
            canvas.delete("all")
            _rounded_rectangle(
                canvas,
                1,
                1,
                width - 1,
                height - 1,
                self.px(10),
                fill=self.palette["field"],
                outline="",
            )
        _rounded_rectangle(
            canvas,
            1,
            1,
            width - 1,
            height - 1,
            self.px(10),
            fill="",
            outline=self.palette["stroke"],
            width=1,
        )
        state = self._art_render_state.get(id(canvas))
        if state is not None:
            state["rendered_size"] = (width, height)

    def _fact_row(
        self,
        master: tk.Misc,
        row: int,
        title: str,
        detail: str,
        *,
        accent: str | None = None,
        compact: bool = False,
        wrap_width: int = 360,
    ) -> tk.Frame:
        holder = tk.Frame(master, bg=self.palette["panel"], bd=0, highlightthickness=0)
        holder.grid(row=row, column=0, sticky="ew", pady=(0, self.px(7 if compact else 14)))
        holder.columnconfigure(1, weight=1)
        dot = tk.Canvas(holder, width=self.px(18), height=self.px(18), bg=self.palette["panel"], bd=0, highlightthickness=0)
        dot.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, self.px(12)), pady=(self.px(4), 0))
        dot.create_oval(
            self.px(4),
            self.px(4),
            self.px(14),
            self.px(14),
            fill=accent or self.palette["accent2"],
            outline="",
        )
        title_label = tk.Label(
            holder,
            text=title,
            bg=self.palette["panel"],
            fg=self.palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.BODY if compact else type_scale.SUBHEADING, "bold"),
            anchor="w",
            justify="left",
        )
        title_label.grid(row=0, column=1, sticky="ew")
        detail_label = tk.Label(
            holder,
            text=detail,
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.SECONDARY if compact else type_scale.BODY),
            anchor="w",
            justify="left",
        )
        detail_label.grid(row=1, column=1, sticky="ew", pady=(self.px(4), 0))
        self._bind_responsive_wrap(title_label, holder, maximum=wrap_width, reserve=30, initial=150)
        self._bind_responsive_wrap(detail_label, holder, maximum=wrap_width, reserve=30, initial=150)
        return holder

    def render_step(self, index: int) -> None:
        self.step_index = max(0, min(len(ONBOARDING_STEPS) - 1, int(index)))
        self._clear_content()
        self._page_heading()
        self.status_var.set("")
        step_id = ONBOARDING_STEPS[self.step_index].id
        {
            "welcome": self._render_welcome,
            "voice": self._render_voice,
            "intro": self._render_intro,
            "permissions": self._render_permissions,
            "microphone": self._render_microphone,
            "controls": self._render_controls,
            "menu": self._render_menu,
            "superpowers": self._render_superpowers,
            "writing": self._render_writing,
            "test": self._render_test,
        }[step_id]()
        self.back_button.configure(state="disabled" if self.step_index == 0 else "normal")
        if step_id == "test":
            self.next_button.configure(text="Finish setup")
        elif step_id == "intro":
            self.next_button.configure(text="Get started")
        elif step_id == "access" and not self._account_active():
            self.next_button.configure(text="Continue privately")
        else:
            self.next_button.configure(text="Continue")
        self._draw_progress()
        self._draw_header()
        self._queue_content_extent_sync()
        # X-460: grow the window to the step, up to the work area, instead
        # of scrolling. After the extent sync so the measurement is real.
        self._queue_fit_to_step()
        # Record the semantic page and its proof on every transition. A stable
        # id survives the extra Permissions page on macOS and future reorders.
        self._store_resume_receipt()

    def _access_card(
        self,
        master: tk.Misc,
        *,
        row: int,
        title: str,
        badge: str,
        description: str,
        button_text: str,
        command: Callable[[], None],
    ) -> None:
        card = tk.Frame(
            master,
            bg=self.palette["panel"],
            bd=0,
            highlightthickness=0,
        )
        card.grid(row=row, column=0, sticky="ew", pady=(0, self.px(8)))
        card.columnconfigure(0, weight=1)
        tk.Label(
            card,
            text=badge,
            bg=self.palette["panel"],
            fg=self.palette["accent2"],
            font=(BRAND_UI_FAMILY, type_scale.CAPTION, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            card,
            text=title,
            bg=self.palette["panel"],
            fg=self.palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.SUBHEADING, "bold"),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(self.px(4), 0))
        tk.Label(
            card,
            text=description,
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.BODY),
            justify="left",
            anchor="nw",
            wraplength=self.px(390),
        ).grid(row=2, column=0, sticky="ew", pady=(self.px(4), self.px(8)))
        button = self._detail_button(button_text, command, master=card)
        button.grid(row=3, column=0, sticky="ew")
        if row == 1:
            self.create_account_button = button
        else:
            self.restore_account_button = button

    def _start_account_activation(self, choice: str) -> None:
        self.access_choice = choice
        self.config.setdefault("onboarding", {})["access_choice"] = choice
        self.account_activation_started = True
        self.access_status_var.set("Opening secure browser sign-in. This window will recognize the signed activation automatically.")
        self._invoke_callback("license_activate")
        self._refresh_access_status()

    def _refresh_access_status(self) -> None:
        if self.destroyed or ONBOARDING_STEPS[self.step_index].id != "access":
            return
        if self.account_after:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(self.account_after)
            self.account_after = None
        activation_callback = self.host.callbacks.get("license_activation_status")
        state = self._license_state()
        try:
            activation = activation_callback() if callable(activation_callback) else {}
        except Exception:
            activation = {}
        active = bool(state.get("active"))
        if active:
            email = str(state.get("email") or "your verified account")
            self.access_choice = "account"
            self.config.setdefault("onboarding", {})["access_choice"] = "account"
            self.access_status_var.set(f"Connected: {email} is signed in on {platform_copy.THIS_COMPUTER}.")
            self.access_badge.configure(text="ACCOUNT CONNECTED", fg=self.palette["accent2"])
            self.create_account_button.configure(text="Account connected", state="disabled")
            self.restore_account_button.configure(text="Restore complete", state="disabled")
            self.next_button.configure(text="Continue")
        else:
            activation_state = str(activation.get("state") or "idle")
            detail = str(activation.get("detail") or "")
            if activation_state in {"starting", "waiting"}:
                self.access_status_var.set(detail or "Finish secure sign-in in your browser.")
                self.access_badge.configure(text="WAITING FOR BROWSER")
            elif activation_state == "error" and self.account_activation_started:
                self.access_status_var.set(f"Account connection is unavailable: {detail} Private local setup still works.")
                self.access_badge.configure(text="PRIVATE MODE AVAILABLE")
            elif not self.account_activation_started:
                self.access_status_var.set("No account is connected. Choose an account path or continue with private local/BYOK setup.")
                self.access_badge.configure(text="PRIVATE MODE AVAILABLE")
            self.next_button.configure(text="Continue privately")
        self.account_after = self.window.after(500, self._refresh_access_status)

    def _render_intro(self) -> None:
        """A calm first contact: one product, one promise, no decision yet."""
        body = tk.Frame(self.content, bg=self.palette["panel"], bd=0, highlightthickness=0)
        body.grid(row=1, column=0, sticky="nsew", padx=self.px(28), pady=(0, self.px(24)))
        body.columnconfigure(0, weight=6, uniform="intro")
        body.columnconfigure(1, weight=4, uniform="intro")
        body.rowconfigure(0, weight=1)

        art = self._art_panel(body, "intro", height=330, centering=(0.38, 0.5))
        art.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(24)))

        copy = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        copy.grid(row=0, column=1, sticky="nsew")
        copy.columnconfigure(0, weight=1)
        copy.rowconfigure(0, weight=1)
        copy.rowconfigure(4, weight=1)
        tk.Label(
            copy,
            text="Talk, and your words are typed for you.",
            bg=self.palette["panel"],
            fg=self.palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.TITLE, "bold"),
            anchor="w",
            justify="left",
            wraplength=self.px(330),
        ).grid(row=1, column=0, sticky="ew", pady=(0, self.px(20)))
        self._fact_row(copy, 2, "Hold, speak, release", "Talk naturally. The result is cleaned and delivered when you finish.")
        self._fact_row(copy, 3, "Works where you already write", "Your text goes into the app you were using. There is no extra window to copy from.", accent=self.palette["accent"])

    def _render_welcome(self) -> None:
        body = tk.Frame(self.content, bg=self.palette["panel"], bd=0, highlightthickness=0)
        body.grid(row=1, column=0, sticky="nsew", padx=self.px(28), pady=(0, self.px(24)))
        body.columnconfigure(0, weight=4, uniform="welcome")
        body.columnconfigure(1, weight=6, uniform="welcome")
        body.rowconfigure(0, weight=1)

        facts = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        facts.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(24)))
        facts.columnconfigure(0, weight=1)
        facts.rowconfigure(0, weight=1)
        facts.rowconfigure(4, weight=1)
        tk.Label(
            facts,
            text="Nothing happens until you press the key.",
            bg=self.palette["panel"],
            fg=self.palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.TITLE, "bold"),
            anchor="w",
            justify="left",
            wraplength=self.px(340),
        ).grid(row=1, column=0, sticky="ew", pady=(0, self.px(20)))
        self._fact_row(
            facts,
            2,
            "Microphone off by default",
            "Nothing records until you hold the trigger, click the Pill, or enable hands-free.",
            wrap_width=290,
        )
        self._fact_row(
            facts,
            3,
            "Saved while it works",
            "A temporary local safety copy protects your words during transcription. Recovery settings control cleanup.",
            accent=self.palette["accent"],
            wrap_width=290,
        )
        self._fact_row(
            facts,
            4,
            "Your speech route",
            "Stay on-device, or connect your own supported provider.",
            wrap_width=290,
        )

        art = self._art_panel(body, "welcome", height=320, centering=(0.30, 0.5))
        art.grid(row=0, column=1, sticky="nsew")

    def _route_for_provider(self, provider_id: str) -> str:
        if provider_id == "local":
            return "local"
        return "byok"

    def _license_state(self) -> dict[str, Any]:
        callback = self.host.callbacks.get("license_status")
        if not callable(callback):
            return {}
        try:
            state = callback() or {}
        except Exception:
            return {}
        return state if isinstance(state, dict) else {}

    def _account_active(self) -> bool:
        return bool(self._license_state().get("active"))

    def _render_voice(self) -> None:
        body = tk.Frame(self.content, bg=self.palette["panel"], bd=0, highlightthickness=0)
        body.grid(row=1, column=0, sticky="nsew", padx=self.px(28), pady=(0, self.px(20)))
        # X-401: the founder's screenshot showed a scrolling column of cards
        # beside a mostly empty detail panel. The step now uses the width it
        # has: the three routes sit in one row across the top, the detail
        # panel takes the whole width beneath, and nothing needs a scrollbar
        # at 1080p.
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        selector = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        selector.grid(row=0, column=0, sticky="ew")
        selector.columnconfigure(0, weight=1)
        art = self._art_panel(selector, "voice", height=72, centering=(0.54, 0.5))
        art.grid(row=0, column=0, sticky="ew", pady=(0, self.px(12)))

        cards = tk.Frame(selector, bg=self.palette["panel"], bd=0, highlightthickness=0)
        cards.grid(row=1, column=0, sticky="ew")
        for column in range(3):
            cards.columnconfigure(column, weight=1, uniform="route-cards")
        self.route_buttons: dict[str, tk.Radiobutton] = {}
        self.route_cards: dict[str, tuple[tk.Frame, tk.Label, tk.Label]] = {}
        # The card order IS the recommendation (X-59 doctrine). X-516 makes
        # that local: it is the only route that needs nothing set up.
        for row, route in enumerate(("local", "byok")):
            title, badge, description = ROUTE_CARDS[route]
            card = tk.Frame(
                cards,
                bg=self.palette["surface"],
                bd=0,
                highlightthickness=1,
                highlightbackground=self.palette["stroke"],
                cursor="hand2",
            )
            card.grid(row=0, column=row, sticky="nsew", padx=(0, self.px(12)) if row < 2 else 0)
            card.columnconfigure(0, weight=1)
            header = tk.Frame(card, bg=self.palette["surface"], bd=0, highlightthickness=0)
            header.grid(row=0, column=0, sticky="ew", padx=self.px(12), pady=(self.px(8), 0))
            header.columnconfigure(0, weight=1)
            radio = tk.Radiobutton(
                header,
                text=title,
                variable=self.route_var,
                value=route,
                command=lambda selected=route: self._select_route(selected),
                indicatoron=True,
                anchor="w",
                justify="left",
                font=(BRAND_UI_FAMILY, type_scale.SUBHEADING, "bold"),
                bg=self.palette["surface"],
                fg=self.palette["text"],
                activebackground=self.palette["surface"],
                activeforeground=self.palette["text"],
                selectcolor=self.palette["surface"],
                highlightthickness=1,
                highlightbackground=self.palette["surface"],
                highlightcolor=self.palette["accent2"],
                bd=0,
                takefocus=True,
                cursor="hand2",
            )
            # X-460: the badge is an eyebrow ABOVE the title, the way the
            # account cards do it. Sharing one row, the title was clipped to
            # "Talk DA1" and "Private on-d" on a 940-wide window.
            badge_label = tk.Label(
                header,
                text=badge,
                bg=self.palette["surface"],
                fg=self.palette["accent2"],
                font=(BRAND_UI_FAMILY, type_scale.CAPTION, "bold"),
                anchor="w",
            )
            badge_label.grid(row=0, column=0, sticky="w", padx=(self.px(4), 0))
            radio.grid(row=1, column=0, sticky="ew")
            description_label = tk.Label(
                card,
                text=description,
                bg=self.palette["surface"],
                fg=self.palette["muted"],
                font=(BRAND_UI_FAMILY, type_scale.BODY),
                anchor="w",
                justify="left",
                wraplength=self.px(250),
            )
            description_label.grid(
                row=1,
                column=0,
                sticky="ew",
                padx=(self.px(36), self.px(12)),
                pady=(self.px(4), self.px(8)),
            )
            self._bind_responsive_wrap(description_label, card, maximum=300, reserve=48, initial=200)
            for sequence in ("<Left>", "<Up>"):
                radio.bind(sequence, lambda _event, selected=route: self._move_route_choice(selected, -1))
            for sequence in ("<Right>", "<Down>"):
                radio.bind(sequence, lambda _event, selected=route: self._move_route_choice(selected, 1))
            radio.bind("<Return>", lambda _event, selected=route: self._activate_route_control(selected))
            radio.bind("<Button-1>", lambda _event, selected=route: self._route_pointer(selected), add="+")
            radio.bind("<FocusIn>", lambda _event, selected=route: self._style_route_card(selected), add="+")
            radio.bind("<FocusOut>", lambda _event, selected=route: self._style_route_card(selected), add="+")
            for target in (card, header, badge_label, description_label):
                target.bind("<Button-1>", lambda _event, selected=route: self._activate_route_control(selected))
            self.route_buttons[route] = radio
            self.route_cards[route] = (card, badge_label, description_label)
            self._style_route_card(route)

        self.route_detail = tk.Frame(
            body,
            bg=self.palette["surface"],
            bd=0,
            highlightthickness=1,
            highlightbackground=self.palette["stroke"],
        )
        self.route_detail.grid(row=1, column=0, sticky="nsew", pady=(self.px(16), 0))
        self.route_detail.columnconfigure(1, weight=1)
        self._refresh_route_detail()

    def _activate_route_control(self, route: str) -> str:
        button = getattr(self, "route_buttons", {}).get(route)
        if button is None:
            return "break"
        button.focus_set()
        button.invoke()
        return "break"

    def _route_pointer(self, route: str) -> str | None:
        """X-516: no route is disabled any more, so every radio clicks natively."""

        return None

    def _style_route_card(self, route: str) -> None:
        button = getattr(self, "route_buttons", {}).get(route)
        card_parts = getattr(self, "route_cards", {}).get(route)
        if button is None or card_parts is None or not button.winfo_exists():
            return
        card, badge_label, description_label = card_parts
        selected = self.route_var.get() == route
        enabled = True  # X-516: both remaining routes always work
        focused = button.focus_get() is button
        fill = self.palette["select"] if selected else self.palette["surface"]
        outline = self.palette["accent2"] if focused else self.palette["accent"] if selected else self.palette["stroke"]
        card.configure(
            bg=fill,
            highlightbackground=outline,
            highlightcolor=outline,
            highlightthickness=self.px(2) if selected or focused else self.px(1),
            cursor="hand2" if enabled else "",
        )
        for child in card.winfo_children():
            with contextlib.suppress(tk.TclError):
                child.configure(bg=fill)
        button.configure(
            bg=fill,
            fg=self.palette["text"] if enabled else self.palette["muted"],
            activebackground=fill,
            activeforeground=self.palette["text"],
            selectcolor=fill,
            disabledforeground=self.palette["muted"],
            state=tk.NORMAL if enabled else tk.DISABLED,
            cursor="hand2" if enabled else "",
        )
        badge_label.configure(
            bg=fill,
            fg=self.palette["accent2"] if enabled else self.palette["muted"],
            text=ROUTE_CARDS[route][1],
        )
        description_label.configure(bg=fill, fg=self.palette["muted"])

    def _select_route(self, route: str) -> None:
        self.route_var.set(route)
        for selected_route in getattr(self, "route_buttons", {}):
            self._style_route_card(selected_route)
        self._refresh_route_detail()

    def _move_route_choice(self, current: str, direction: int) -> str:
        """Arrow-key radio navigation for the three mutually exclusive routes."""

        order = ("local", "byok")
        start = order.index(current) if current in order else 0
        step = 1 if direction >= 0 else -1
        for offset in range(1, len(order) + 1):
            candidate = order[(start + step * offset) % len(order)]
            self._select_route(candidate)
            button = getattr(self, "route_buttons", {}).get(candidate)
            if button is not None:
                with contextlib.suppress(Exception):
                    button.focus_set()
            break
        return "break"

    def _refresh_route_detail(self) -> None:
        for child in self.route_detail.winfo_children():
            child.destroy()
        route = self.route_var.get()
        if route == "local":
            # X-59.C-2: the install-time PC audit picks the local model this
            # machine can actually carry, and says so -- the crash reports we
            # dug out of were strong models on weak machines.
            audit_line = ""
            recommended_id = DEFAULT_LOCAL_MODEL_ID
            try:
                from ..pc_audit import audit_pc, recommended_local_model

                audit = audit_pc()
                audit_line = audit.summary
                candidate = recommended_local_model(audit)
                if local_model_for_id(candidate) is not None:
                    recommended_id = candidate
            except Exception:
                pass
            model = local_model_for_id(recommended_id) or local_model_for_id(DEFAULT_LOCAL_MODEL_ID)
            ready = is_downloaded(model)
            downloaded = downloaded_size_mb(model)
            if ready:
                status = f"Ready on {platform_copy.THIS_COMPUTER}"
            elif downloaded:
                status = f"Preparing locally - {downloaded} of about {model.size_mb} MB present"
            else:
                status = f"One-time download required - about {model.size_mb} MB"
            self.route_status_var.set(f"{model.label}. {status}.")
            self._detail_label(0, "Speech model", model.label + (f" · matched to {platform_copy.THIS_COMPUTER}" if audit_line else ""))
            if audit_line:
                self._detail_label(1, f"{platform_copy.THIS_COMPUTER_SENTENCE}", audit_line)
            self._detail_label(2, "Privacy", f"Audio stays on {platform_copy.THIS_COMPUTER} after the one-time model download.")
            self._detail_label(3, "Status", status)
            button = self._detail_button("Prepare local model", self._prepare_local_model)
            button.grid(
                row=4,
                column=1,
                sticky="w",
                padx=self.px(16),
                pady=(self.px(4), self.px(16)),
            )
        else:
            self.route_status_var.set("Choose a provider. Only providers with working adapters are shown here.")
            provider_box = self._detail_combo(self.provider_var, flagship_cloud_provider_labels())
            provider_box.configure(state="readonly")
            provider_box.bind("<<ComboboxSelected>>", self._provider_changed)
            self._detail_row(0, "Provider", provider_box)
            model_box = self._detail_combo(self.model_var, model_labels(self.provider_holder["id"]))
            model_box.configure(state="readonly")
            model_box.bind("<<ComboboxSelected>>", lambda _event: self._model_changed(model_box))
            self.provider_model_box = model_box
            self._detail_row(1, "Speech model", model_box)
            key_entry = ttk.Entry(
                self.route_detail,
                textvariable=self.key_var,
                show="•",
                style="Flow.TEntry",
            )
            self.provider_key_entry = key_entry
            self._detail_row(2, "API key", key_entry)
            language = ttk.Entry(
                self.route_detail,
                textvariable=self.language_var,
                style="Flow.TEntry",
            )
            self._detail_row(3, "Language", language)
            links = tk.Frame(self.route_detail, bg=self.palette["surface"])
            for kind, label in (("login", "Sign in"), ("keys", "Get API key"), ("docs", "Provider docs")):
                self._detail_button(
                    label,
                    lambda selected=kind: self._open_provider_link(selected),
                    master=links,
                ).pack(side="left", padx=(0, self.px(8)))
            self._detail_row(4, "Provider help", links)
            self._provider_changed()
        tk.Label(
            self.route_detail,
            textvariable=self.route_status_var,
            bg=self.palette["surface"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.SECONDARY),
            anchor="w",
            justify="left",
            wraplength=self.px(520),
        ).grid(row=8, column=0, columnspan=2, sticky="ew", padx=self.px(16), pady=(self.px(8), self.px(12)))

    def _detail_label(self, row: int, label: str, value: str) -> None:
        widget = tk.Label(
            self.route_detail,
            text=value,
            bg=self.palette["surface"],
            fg=self.palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.BODY),
            justify="left",
            anchor="w",
            wraplength=self.px(700),
        )
        self._detail_row(row, label, widget)

    def _detail_row(self, row: int, label: str, widget: tk.Widget) -> None:
        tk.Label(
            self.route_detail,
            text=label,
            bg=self.palette["surface"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.SECONDARY, "bold"),
            anchor="w",
        ).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(self.px(16), self.px(20)),
            pady=self.px(4),
        )
        widget.grid(
            row=row,
            column=1,
            sticky="ew",
            padx=(0, self.px(16)),
            pady=self.px(4),
        )

    def _detail_combo(self, variable: tk.StringVar, values: list[str]) -> Any:
        from tkinter import ttk

        return ttk.Combobox(self.route_detail, textvariable=variable, values=values, style="Flow.TCombobox")

    def _detail_button(
        self,
        text: str,
        command: Callable[[], None],
        *,
        master: tk.Misc | None = None,
        primary: bool = False,
        min_width: int = 96,
    ) -> AtelierButton:
        parent = master or self.route_detail
        return AtelierButton(
            parent,
            text=text,
            command=command,
            palette=self._button_palette(parent),
            primary=primary,
            min_width=min_width,
            scale=self.px(100) / 100.0,
        )

    def _provider_changed(self, _event: tk.Event | None = None) -> None:
        previous = self.provider_holder["id"]
        self._remember_provider(previous)
        provider_id = provider_id_for_label(self.provider_var.get())
        if provider_id not in FLAGSHIP_CLOUD_PROVIDER_IDS:
            provider_id = "deepgram"
            self.provider_var.set(provider_label(provider_id))
        self.provider_holder["id"] = provider_id
        settings = getattr(self, "_provider_drafts", {}).get(provider_id) or provider_settings(copy.deepcopy(self.config), provider_id)
        current_model = str(settings.get("model") or PROVIDER_BY_ID[provider_id].models[0].id)
        self.model_var.set(model_label(provider_id, current_model))
        self.key_var.set(str(settings.get("api_key", "")))
        self.language_var.set(str(settings.get("language") or "en-US"))
        if hasattr(self, "provider_model_box"):
            self.provider_model_box.configure(values=model_labels(provider_id))
        self.route_status_var.set(provider_capability_summary(provider_id, current_model))

    def _model_changed(self, _box: Any | None = None) -> None:
        provider_id = self.provider_holder["id"]
        model_id = model_id_for_label(provider_id, self.model_var.get())
        self.route_status_var.set(provider_capability_summary(provider_id, model_id))

    def _remember_provider(self, provider_id: str) -> None:
        if provider_id not in PROVIDER_BY_ID:
            return
        drafts = getattr(self, "_provider_drafts", None)
        if drafts is None:
            drafts = self._provider_drafts = {}
        settings = copy.deepcopy(drafts.get(provider_id) or provider_settings(copy.deepcopy(self.config), provider_id))
        settings["api_key"] = self.key_var.get().strip()
        settings["language"] = self.language_var.get().strip() or "en-US"
        settings["model"] = model_id_for_label(provider_id, self.model_var.get())
        model = model_for_id(provider_id, settings["model"])
        settings["variant"] = str(settings.get("variant") or model.variants[0])
        drafts[provider_id] = settings


    def _open_provider_link(self, kind: str) -> None:
        provider = PROVIDER_BY_ID[self.provider_holder["id"]]
        url = {"login": provider.login_url, "keys": provider.api_keys_url, "docs": provider.docs_url}.get(kind, "")
        if url:
            webbrowser.open(url)

    def _prepare_local_model(self) -> None:
        def show(message: str) -> None:
            with contextlib.suppress(Exception):
                if self.window is not None and self.window.winfo_exists():
                    self.route_status_var.set(message)

        self.route_status_var.set("Checking your offline model...")
        callback = self.host.callbacks.get("prepare_local_model")
        if not callable(callback):
            self.route_status_var.set("Offline model setup is unavailable in this window. Open Settings > Speech.")
            return
        try:
            callback(show)
        except TypeError:
            # An older host that cannot report progress: still say something true.
            callback()
            self.route_status_var.set("Preparing your offline model in the background. You can continue setup.")

    def _commit_voice_route(self) -> bool:
        from ..stt_registry import local_only
        route = self.route_var.get()
        if route not in {"local", "byok"}:
            self.status_var.set("Choose Local or Your key before continuing.")
            return False
        if route == "byok" and local_only(self.config):
            self.status_var.set("Local-only privacy is on. Choose Local here, or review Privacy in Settings before using your own provider.")
            return False
        candidate = copy.deepcopy(self.config)
        stt = candidate.setdefault("stt", {})
        if route == "local":
            provider_id = "local"
            previous = str(stt.get("provider", ""))
            if previous in FLAGSHIP_CLOUD_PROVIDER_IDS:
                stt["cloud_provider"] = previous
        else:
            provider_id = self.provider_holder["id"]
            if provider_id not in FLAGSHIP_CLOUD_PROVIDER_IDS:
                self.status_var.set("Choose an available speech provider.")
                return False
            self._remember_provider(provider_id)
            settings = provider_settings(candidate, provider_id)
            settings.update(self._provider_drafts[provider_id])
            provider = PROVIDER_BY_ID[provider_id]
            if not provider.key_optional and not str(settings.get("api_key", "")).strip():
                self.status_var.set(f"Add your {provider.key_label} to continue, or choose Private on-device.")
                with contextlib.suppress(Exception):self.provider_key_entry.focus_set()
                return False
            stt["cloud_provider"] = provider_id
        stt.update(provider=provider_id, route_mode=route)
        settings = provider_settings(candidate, provider_id)
        settings["language"] = self.language_var.get().strip() or "en-US"
        candidate.setdefault("deepgram", {})["language"] = settings["language"]
        sync_legacy_deepgram(candidate)
        candidate.setdefault("onboarding", {})["route"] = route
        if not self._save_setup(candidate):
            return False
        if provider_id == "local":
            self.window.after(50, self._prepare_local_model)
        return True

    def _save_setup(self, candidate: dict[str, Any]) -> bool:
        host = getattr(self, "host", None)
        callback = getattr(host, "callbacks", {}).get("onboarding_save")
        try:
            if callable(callback):
                result = callback(candidate)
                if type(result) is not dict or result.get("saved") is not True:
                    raise ValueError("The setup save was not confirmed.")
                self._setup_runtime_refreshed = result.get("runtime_refreshed", True)
                if not self._setup_runtime_refreshed:
                    self.status_var.set("Saved. Restart Talk DAT to apply every setting.")
                return True
            # Compatibility for older hosts. The shipping app supplies the
            # transaction above so persistence and runtime refresh are distinct.
            old = copy.deepcopy(self.config)
            self.config.clear();self.config.update(copy.deepcopy(candidate))
            try:self._invoke_callback("save_settings")
            except Exception:
                self.config.clear();self.config.update(old)
                raise
            if host is not None:
                from .. import net_fence
                from ..stt_registry import local_only
                net_fence.set_local_only(local_only(self.config) or str(self.config.get("stt", {}).get("route_mode", "local")) == "local")
                host.apply_runtime_config()
            self._setup_runtime_refreshed = True
            return True
        except Exception:
            self.status_var.set("Setup could not be saved. Your previous settings remain; try again.")
            return False


    def _render_microphone(self) -> None:
        body = tk.Frame(self.content, bg=self.palette["panel"], bd=0, highlightthickness=0)
        body.grid(row=1, column=0, sticky="nsew", padx=self.px(28), pady=(0, self.px(20)))
        body.columnconfigure(0, weight=4, uniform="microphone")
        body.columnconfigure(1, weight=6, uniform="microphone")
        body.rowconfigure(0, weight=1)

        visual = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        visual.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(24)))
        visual.columnconfigure(0, weight=1)
        art = self._art_panel(visual, "microphone", height=184, centering=(0.58, 0.5))
        art.grid(row=0, column=0, sticky="ew")
        self._fact_row(
            visual,
            1,
            "Local level check",
            "The meter reads this microphone on your computer. No audio is uploaded or saved.",
            compact=True,
        )
        self._fact_row(
            visual,
            2,
            "One microphone owner",
            "Starting Mic Doctor pauses this check first, so two tools never compete for the device.",
            accent=self.palette["accent"],
            compact=True,
        )

        instrument = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        instrument.grid(row=0, column=1, sticky="nsew")
        instrument.columnconfigure(0, weight=1)
        controls = tk.Frame(instrument, bg=self.palette["panel"])
        controls.grid(row=0, column=0, sticky="ew", pady=(0, self.px(12)))
        controls.columnconfigure(1, weight=1)
        tk.Label(
            controls,
            text="Input",
            bg=self.palette["panel"],
            fg=self.palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.SUBHEADING, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, self.px(12)))
        from tkinter import ttk

        # PortAudio can take several seconds on its first device query. Paint a
        # complete, usable page first and let the guarded worker fill the list.
        devices = [WINDOWS_DEFAULT_MIC]
        self.mic_box = ttk.Combobox(controls, textvariable=self.audio_device_var, values=devices, state="readonly", style="Flow.TCombobox")
        self.mic_box.grid(row=0, column=1, sticky="ew")
        self.mic_box.bind("<<ComboboxSelected>>", self._microphone_changed, add="+")
        refresh_button = self._detail_button("Refresh", self._refresh_microphones, master=controls, min_width=84)
        self.mic_refresh_button = refresh_button
        refresh_button.grid(
            row=0, column=2, padx=(self.px(8), 0)
        )

        def fit_microphone_controls(event: tk.Event | None = None) -> None:
            """Give the selected input the full row on narrow scaled layouts."""

            width = int(getattr(event, "width", controls.winfo_width()))
            if width < self.px(430):
                self.mic_box.grid_configure(row=0, column=1, columnspan=2, sticky="ew")
                refresh_button.grid_configure(
                    row=1,
                    column=1,
                    columnspan=2,
                    sticky="e",
                    padx=(0, 0),
                    pady=(self.px(8), 0),
                )
            else:
                self.mic_box.grid_configure(row=0, column=1, columnspan=1, sticky="ew")
                refresh_button.grid_configure(
                    row=0,
                    column=2,
                    columnspan=1,
                    sticky="",
                    padx=(self.px(8), 0),
                    pady=(0, 0),
                )

        controls.bind("<Configure>", fit_microphone_controls, add="+")
        self.window.after_idle(fit_microphone_controls)

        self.mic_canvas = tk.Canvas(
            instrument,
            height=self.px(178),
            bg=self.palette["surface"],
            bd=0,
            highlightthickness=1,
            highlightbackground=self.palette["stroke"],
        )
        self.mic_canvas.grid(row=1, column=0, sticky="ew", pady=(0, self.px(12)))
        self.mic_canvas.bind("<Configure>", lambda _event: self._draw_mic_meter())
        status = tk.Label(
            instrument,
            textvariable=self.mic_status_var,
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.SUBHEADING, "bold"),
            anchor="w",
            justify="left",
            wraplength=self.px(480),
        )
        status.grid(row=2, column=0, sticky="ew")
        tk.Label(
            instrument,
            text="The microphone remains off until you start this check. Leaving the page, closing setup, or using Panic Stop closes it.",
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.BODY),
            anchor="w",
            justify="left",
            wraplength=self.px(480),
        ).grid(row=3, column=0, sticky="ew", pady=(self.px(4), 0))
        action_row = tk.Frame(instrument, bg=self.palette["panel"], bd=0, highlightthickness=0)
        action_row.grid(row=4, column=0, sticky="ew", pady=(self.px(12), 0))
        action_row.columnconfigure(0, weight=1)
        self.mic_test_button = self._detail_button(
            "Start mic check",
            self._toggle_meter,
            master=action_row,
            primary=True,
            min_width=132,
        )
        self.mic_test_button.grid(row=0, column=0, sticky="w")
        self._detail_button(
            "Open Mic Doctor",
            self._open_mic_doctor,
            master=action_row,
            min_width=132,
        ).grid(row=0, column=1, sticky="e", padx=(self.px(12), 0))
        self.window.after(0, lambda: self._refresh_microphones(initial=True))

    def _microphone_changed(self, _event: tk.Event | None = None) -> None:
        candidate = copy.deepcopy(self.config)
        candidate.setdefault("audio", {})["input_device"] = (
            "" if self.audio_device_var.get() == WINDOWS_DEFAULT_MIC else self.audio_device_var.get().strip()
        )
        if not self._save_setup(candidate):
            self.audio_device_var.set(self.config.get("audio", {}).get("input_device") or WINDOWS_DEFAULT_MIC)
            return
        if (
            self.meter_state.get("stream") is not None
            or bool(self.meter_state.get("opening"))
        ):
            self._restart_meter()
        else:
            self.mic_status_var.set("Input selected. Start the mic check when you are ready.")

    def _toggle_meter(self) -> None:
        if bool(self.meter_state.get("closing")):
            self.mic_status_var.set("Finishing the previous microphone check...")
            return
        if self.meter_state.get("stream") is not None or bool(self.meter_state.get("opening")):
            self.mic_status_var.set("Closing the microphone locally...")
            self._stop_meter(
                on_closed=lambda: self.mic_status_var.set(
                    "Mic check stopped. Your microphone is off."
                )
            )
            return
        self._start_meter()

    def _panic_stop_meter(self) -> object:
        """Begin driver shutdown while keeping Panic's owner claim honest."""

        # Panic supersedes any refresh/selection restart already queued behind
        # an in-flight close. Otherwise the old owner can release and a new mic
        # can open just as the global panic path announces completion.
        self.meter_state["on_closed"] = None
        self._stop_meter()
        return DEFERRED_MICROPHONE_RELEASE

    def _open_mic_doctor(self) -> None:
        self.mic_status_var.set("Setup meter paused while Mic Doctor runs.")
        # A device refresh/selection can already have queued _start_meter for
        # the end of this same driver close. Mic Doctor is an explicit change
        # of tool, so it supersedes that restart; otherwise both surfaces race
        # to open a microphone immediately after the close completes.
        self.meter_state["on_closed"] = None
        self._stop_meter(on_closed=self.host.open_mic_doctor)

    def _refresh_microphones(self, *, initial: bool = False) -> None:
        if self.destroyed or ONBOARDING_STEPS[self.step_index].id != "microphone":
            return
        self._microphone_query_generation += 1
        generation = self._microphone_query_generation
        refresh_button = getattr(self, "mic_refresh_button", None)
        if refresh_button is not None:
            with contextlib.suppress(Exception):
                if refresh_button.winfo_exists():
                    refresh_button.configure(text="Checking...", state="disabled")
        if initial:
            self.mic_status_var.set("Checking this computer for microphones...")
        else:
            self.mic_status_var.set("Refreshing the microphone list...")

        def query() -> None:
            try:
                discovered = tuple(list_input_devices())
                error = ""
            except Exception as exc:
                discovered = ()
                error = str(exc)

            def apply() -> None:
                if (
                    self.destroyed
                    or generation != self._microphone_query_generation
                    or ONBOARDING_STEPS[self.step_index].id != "microphone"
                ):
                    return
                values = [WINDOWS_DEFAULT_MIC, *discovered]
                try:
                    if not self.mic_box.winfo_exists():
                        return
                    self.mic_box.configure(values=values)
                    selected = self.audio_device_var.get()
                    missing = selected not in values
                    if missing:
                        self.mic_box.configure(values=[*values, selected])
                    if refresh_button is not None and refresh_button.winfo_exists():
                        refresh_button.configure(text="Refresh", state="normal")
                except tk.TclError:
                    return
                if missing:
                    self.mic_status_var.set("The selected microphone is unavailable. Reconnect it or choose another input explicitly.")
                elif error:
                    self.mic_status_var.set(
                        f"Could not refresh microphones: {error}. The system default is still available."
                    )
                elif not self.meter_state.get("stream") and not self.meter_state.get("opening"):
                    self.mic_status_var.set(
                        "Microphones ready. Start the private level check when you are ready."
                    )
                if not initial and (
                    self.meter_state.get("stream") is not None
                    or bool(self.meter_state.get("opening"))
                ):
                    self._restart_meter()

            main_thread.post(apply)

        try:
            threading.Thread(
                target=query,
                name="talkdat-onboarding-microphones",
                daemon=True,
            ).start()
        except Exception as exc:
            if refresh_button is not None:
                with contextlib.suppress(Exception):
                    if refresh_button.winfo_exists():
                        refresh_button.configure(text="Refresh", state="normal")
            self.mic_status_var.set(f"Could not check microphones: {exc}")

    def _selected_device(self) -> int | None:
        value = self.audio_device_var.get().strip()
        return resolve_input_device("" if value == WINDOWS_DEFAULT_MIC else value)

    def _start_meter(self) -> None:
        if (
            self.destroyed
            or ONBOARDING_STEPS[self.step_index].id != "microphone"
            or self.meter_state.get("stream") is not None
            or bool(self.meter_state.get("opening"))
            or bool(self.meter_state.get("closing"))
        ):
            return
        generation = int(self.meter_state.get("generation", 0)) + 1
        self.meter_state["generation"] = generation
        self.meter_state["opening"] = True
        self.mic_status_var.set("Opening the selected microphone locally...")
        button = getattr(self, "mic_test_button", None)
        if button is not None and button.winfo_exists():
            button.configure(text="Opening...", state="disabled")
        mic_box = getattr(self, "mic_box", None)
        if mic_box is not None and mic_box.winfo_exists():
            # The worker captures the selected device before it enters the
            # driver. Freezing the selector until that result is attached (or
            # discarded) prevents the label/config from changing underneath
            # an in-flight open and claiming a different microphone is live.
            mic_box.configure(state="disabled")

        def callback(indata: Any, _frames: int, _time_info: Any, _status: Any) -> None:
            raw = bytes(indata)
            level = min(1.0, pcm_rms_level(raw) * 3.2)
            self.meter_state["level"] = max(float(self.meter_state.get("level", 0.0)) * 0.72, level)
            self.meter_state["peak"] = max(float(self.meter_state.get("peak", 0.0)), level)
            samples = array("h")
            usable = raw[: len(raw) - (len(raw) % 2)]
            if not usable:
                return
            samples.frombytes(usable)
            if sys.byteorder != "little":
                samples.byteswap()
            if not samples:
                return
            stride = max(1, len(samples) // 64)
            wave = [max(-1.0, min(1.0, samples[min(index * stride, len(samples) - 1)] / 32768.0 * 2.8)) for index in range(64)]
            self.meter_state["wave"] = wave

        selected_label = self.audio_device_var.get().strip() or WINDOWS_DEFAULT_MIC
        selected_value = "" if selected_label == WINDOWS_DEFAULT_MIC else selected_label
        try:
            token = microphone_registry().acquire(
                ONBOARDING,
                device=selected_label,
                phase="opening",
                stop=self._panic_stop_meter,
            )
        except Exception as exc:
            self.meter_state["opening"] = False
            self.meter_state["error"] = str(exc)
            self.mic_status_var.set(f"Microphone unavailable: {exc}")
            if button is not None and button.winfo_exists():
                button.configure(text="Try mic check", state="normal")
            if mic_box is not None and mic_box.winfo_exists():
                mic_box.configure(state="readonly")
            self._draw_mic_meter()
            return
        self.meter_state["mic_token"] = token

        def close_stream(stream: Any, release_token: int | None) -> None:
            with contextlib.suppress(Exception):
                stream.stop()
            with contextlib.suppress(Exception):
                stream.close()
            microphone_registry().release(release_token)

        def close_stale_stream(stream: Any, release_token: int | None) -> None:
            close_stream(stream, release_token)
            main_thread.post(self._finish_meter_close)

        def open_stream() -> None:
            stream = None
            try:
                selected_device = resolve_input_device(selected_value)
                if selected_value and selected_device is None:
                    raise ValueError("The selected microphone is unavailable. Reconnect it or choose another input.")
                stream, _rate, _channels, _device = open_raw_input_stream(
                    samplerate=16000,
                    channels=1,
                    dtype="int16",
                    blocksize=1024,
                    device=selected_device,
                    callback=callback,
                    allow_device_fallback=False,
                )
                if _device != selected_device:
                    raise ValueError("The selected microphone could not be opened. Choose another input explicitly.")
                stream.start()
            except Exception as exc:
                if stream is not None:
                    close_stream(stream, token)
                else:
                    microphone_registry().release(token)
                main_thread.post(self._finish_meter_close)

                def report_error(error: str = str(exc)) -> None:
                    if generation != int(self.meter_state.get("generation", 0)):
                        return
                    self.meter_state.pop("mic_token", None)
                    self.meter_state["opening"] = False
                    self.meter_state["error"] = error
                    if self.destroyed:
                        return
                    self.mic_status_var.set(f"Microphone unavailable: {error}")
                    if button is not None and button.winfo_exists():
                        button.configure(text="Try mic check", state="normal")
                    if mic_box is not None and mic_box.winfo_exists():
                        mic_box.configure(state="readonly")
                    self._draw_mic_meter()

                main_thread.post(report_error)
                return

            def attach() -> None:
                if (
                    self.destroyed
                    or generation != int(self.meter_state.get("generation", 0))
                    or not bool(self.meter_state.get("opening"))
                    or ONBOARDING_STEPS[self.step_index].id != "microphone"
                ):
                    try:
                        threading.Thread(
                            target=lambda: close_stale_stream(stream, token),
                            name="talkdat-onboarding-mic-discard",
                            daemon=True,
                        ).start()
                    except Exception:
                        # Losing the already-started driver handle is worse than
                        # paying a rare synchronous cleanup cost.
                        close_stale_stream(stream, token)
                    return
                try:
                    self.meter_state["stream"] = stream
                    self.meter_state["opening"] = False
                    microphone_registry().set_phase(token, "metering")
                    self.meter_state["error"] = ""
                    self.meter_state["after"] = self.window.after(32, self._meter_tick)
                    if button is not None and button.winfo_exists():
                        button.configure(text="Stop mic check", state="normal")
                    if mic_box is not None and mic_box.winfo_exists():
                        mic_box.configure(state="readonly")
                except Exception as exc:
                    self.meter_state["stream"] = stream
                    self._stop_meter()
                    self.meter_state["error"] = str(exc)
                    self.mic_status_var.set(f"Microphone unavailable: {exc}")
                    if button is not None and button.winfo_exists():
                        button.configure(text="Try mic check", state="normal")
                    if mic_box is not None and mic_box.winfo_exists():
                        mic_box.configure(state="readonly")
                    self._draw_mic_meter()

            main_thread.post(attach)

        try:
            threading.Thread(
                target=open_stream,
                name="talkdat-onboarding-mic-open",
                daemon=True,
            ).start()
        except Exception as exc:
            self.meter_state["opening"] = False
            self.meter_state.pop("mic_token", None)
            microphone_registry().release(token)
            self.meter_state["error"] = str(exc)
            self.mic_status_var.set(f"Microphone unavailable: {exc}")
            if button is not None and button.winfo_exists():
                button.configure(text="Try mic check", state="normal")
            if mic_box is not None and mic_box.winfo_exists():
                mic_box.configure(state="readonly")

    def _restart_meter(self) -> None:
        self._stop_meter(on_closed=self._start_meter)

    def _meter_tick(self) -> None:
        if self.destroyed or ONBOARDING_STEPS[self.step_index].id != "microphone":
            return
        level = float(self.meter_state.get("level", 0.0))
        message, band = microphone_quality(level)
        earned_proof = band in {"good", "hot"} and not self.microphone_tested
        if band in {"good", "hot"}:
            self.microphone_tested = True
        if earned_proof:
            self._store_resume_receipt()
        self.mic_status_var.set(message)
        self._draw_mic_meter()
        self.meter_state["level"] = level * 0.88
        self.meter_state["after"] = self.window.after(32, self._meter_tick)

    def _draw_mic_meter(self) -> None:
        canvas = getattr(self, "mic_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return
        canvas.delete("all")
        width = max(self.px(300), canvas.winfo_width())
        height = max(self.px(150), canvas.winfo_height())
        center = height / 2
        canvas.create_rectangle(0, 0, width, height, fill=self.palette["surface"], outline="")
        grid_start = self.px(22)
        grid_end = self.px(18)
        grid_step = max(1, self.px(32))
        grid_inset = self.px(24)
        axis_inset = self.px(20)
        for x in range(grid_start, width - grid_end, grid_step):
            canvas.create_line(x, grid_inset, x, height - grid_inset, fill=self.palette["field"], width=1)
        canvas.create_line(axis_inset, center, width - axis_inset, center, fill=self.palette["stroke"], width=1)
        wave = list(self.meter_state.get("wave") or [0.0] * 64)
        points: list[float] = []
        for index, sample in enumerate(wave):
            x = 24 + (width - 48) * index / max(1, len(wave) - 1)
            y = center - float(sample) * (height * 0.34)
            points.extend((x, y))
        if len(points) >= 4:
            canvas.create_line(*points, fill=self.palette["accent"], width=7)
            canvas.create_line(*points, fill=self.palette["accent2"], width=2)
        level = min(1.0, float(self.meter_state.get("level", 0.0)))
        canvas.create_text(self.px(24), self.px(22), text="LIVE LOCAL INPUT", anchor="nw", fill=self.palette["muted"], font=(BRAND_UI_FAMILY, type_scale.CAPTION, "bold"))
        canvas.create_text(
            width - self.px(24),
            self.px(22),
            text=f"{round(level * 100):02d}%",
            anchor="ne",
            fill=self.palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.SUBHEADING, "bold"),
        )

    def _finish_meter_close(self) -> None:
        self.meter_state["closing"] = False
        button = getattr(self, "mic_test_button", None)
        if button is not None:
            with contextlib.suppress(Exception):
                if button.winfo_exists():
                    button.configure(text="Start mic check", state="normal")
        mic_box = getattr(self, "mic_box", None)
        if mic_box is not None:
            with contextlib.suppress(Exception):
                if mic_box.winfo_exists():
                    mic_box.configure(state="readonly")
        callback = self.meter_state.pop("on_closed", None)
        if callable(callback) and not self.destroyed:
            callback()

    def _stop_meter(self, *, on_closed: Callable[[], None] | None = None) -> None:
        if bool(self.meter_state.get("closing")):
            if on_closed is not None:
                prior = self.meter_state.get("on_closed")
                if callable(prior):
                    self.meter_state["on_closed"] = lambda: (prior(), on_closed())
                else:
                    self.meter_state["on_closed"] = on_closed
            # Only the worker that owns the driver handle may complete this
            # state. A second stop must not reopen the gate while stop()/close()
            # is still blocked inside PortAudio.
            return
        was_opening = bool(self.meter_state.get("opening"))
        if on_closed is not None:
            self.meter_state["on_closed"] = on_closed
        self.meter_state["generation"] = int(self.meter_state.get("generation", 0)) + 1
        self.meter_state["opening"] = False
        after = self.meter_state.get("after")
        if after:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(after)
            self.meter_state["after"] = None
        stream = self.meter_state.get("stream")
        self.meter_state["stream"] = None
        token = self.meter_state.pop("mic_token", None)
        button = getattr(self, "mic_test_button", None)
        if button is not None:
            with contextlib.suppress(Exception):
                if button.winfo_exists():
                    button.configure(text="Finishing...", state="disabled")
        mic_box = getattr(self, "mic_box", None)
        if mic_box is not None:
            with contextlib.suppress(Exception):
                if mic_box.winfo_exists():
                    mic_box.configure(state="disabled")
        if token is not None and (was_opening or stream is not None):
            # Panic and diagnostics must distinguish a cooperative asynchronous
            # driver close from a surface that refused to stop. Opening workers
            # own no stream yet, but they are still committed to stale-close as
            # soon as the driver returns.
            microphone_registry().set_phase(token, "closing")
        if stream is None:
            if was_opening:
                # The open worker still owns any driver handle it may acquire.
                # Keep its privacy token registered until that worker either
                # fails or closes the stale stream it acquired.
                self.meter_state["closing"] = True
                return
            microphone_registry().release(token)
            self._finish_meter_close()
            return

        self.meter_state["closing"] = True
        def close_stream() -> None:
            with contextlib.suppress(Exception):
                stream.stop()
            # A failed PortAudio stop must not skip close. Keep the privacy
            # registry claim until both attempts finish, but never make the Tk
            # page wait for a slow or broken driver while closing/navigating.
            with contextlib.suppress(Exception):
                stream.close()
            microphone_registry().release(token)
            main_thread.post(self._finish_meter_close)

        try:
            threading.Thread(
                target=close_stream,
                name="talkdat-onboarding-mic-close",
                daemon=True,
            ).start()
        except Exception:
            # Thread creation failure must not strand a live PortAudio handle
            # after this method detached its only UI reference.
            close_stream()

    def _render_controls(self) -> None:
        # The real trigger runtime is already live during onboarding. Own its
        # delivery before asking somebody to press the chord so a rehearsal can
        # never paste into whichever application sits behind this window.
        self.host.onboarding_test_sink = self.test_sink
        body = tk.Frame(self.content, bg=self.palette["panel"], bd=0, highlightthickness=0)
        body.grid(row=1, column=0, sticky="nsew", padx=self.px(28), pady=(0, self.px(20)))
        body.columnconfigure(0, weight=4, uniform="controls")
        body.columnconfigure(1, weight=6, uniform="controls")
        body.rowconfigure(0, weight=1)

        visual = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        visual.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(24)))
        visual.columnconfigure(0, weight=1)
        art = self._art_panel(visual, "controls", height=200, centering=(0.56, 0.5))
        art.grid(row=0, column=0, sticky="ew", pady=(0, self.px(12)))
        self._fact_row(
            visual,
            1,
            "Hold to speak",
            "Release the configured trigger to finish. Your rehearsal stays inside setup.",
            compact=True,
            wrap_width=285,
        )
        self._fact_row(
            visual,
            2,
            "Mouse option",
            "Click the Pill once for hands-free dictation. Click again or use the trigger to stop.",
            accent=self.palette["accent"],
            compact=True,
            wrap_width=285,
        )

        rehearsal = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        rehearsal.grid(row=0, column=1, sticky="nsew")
        rehearsal.columnconfigure(0, weight=1)
        chord = primary_hotkey(self.config)
        labels = hotkey_labels(chord)
        chord_text = self._chord_text()
        self.control_status_var.set(
            f"Press and hold {chord_text}. Each key lights independently."
        )
        key_row = tk.Frame(rehearsal, bg=self.palette["panel"], bd=0, highlightthickness=0)
        key_row.grid(row=0, column=0, sticky="ew", pady=(self.px(8), self.px(16)))
        for column in range(max(1, len(chord))):
            key_row.columnconfigure(column, weight=1, uniform="trigger-key")
        self.key_canvases: dict[str, tk.Canvas] = {}
        for index, (key, label) in enumerate(zip(chord, labels, strict=False)):
            canvas = tk.Canvas(
                key_row,
                height=self.px(96),
                bg=self.palette["panel"],
                bd=0,
                highlightthickness=0,
            )
            canvas.grid(row=0, column=index, sticky="ew", padx=(0, self.px(8)) if index < len(chord) - 1 else 0)
            self.key_canvases[key] = canvas
            self._draw_keycap(canvas, label, False)
        tk.Label(
            rehearsal,
            textvariable=self.control_status_var,
            bg=self.palette["panel"], fg=self.palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.SUBHEADING, "bold"),
            anchor="w",
            justify="left",
            wraplength=self.px(500),
        ).grid(row=1, column=0, sticky="ew", pady=(0, self.px(8)))
        tk.Label(
            rehearsal,
            text=f"Hold {chord_text} while you speak, then release to finish.",
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.BODY),
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", pady=(0, self.px(12)))

        def open_hotkey_settings(_event: tk.Event | None = None) -> None:
            with contextlib.suppress(Exception):
                self.host._settings_initial_page = ("Dictation", "Hotkeys")
                self.host.open_settings()

        self._detail_button(
            "Change trigger",
            open_hotkey_settings,
            master=rehearsal,
            min_width=124,
        ).grid(row=3, column=0, sticky="w")
        # X-118: if the mapped chords fight each other, the person hears it
        # HERE, in one sentence naming both sides -- never later as a
        # shortcut that silently does nothing.
        with contextlib.suppress(Exception):
            from ..hotkeys import chord_conflicts

            found = chord_conflicts(self.config.get("hotkeys", {}))
            if found:
                warning_photo = self.host._ui_icon_photo(
                    "warning",
                    self.px(23),
                    self.palette["warning"],
                    self.palette["text"],
                )
                warning_label = tk.Label(
                    rehearsal,
                    text=found[0],
                    image=warning_photo,
                    compound="left",
                    bg=self.palette["panel"], fg=self.palette["warning"],
                    font=(BRAND_UI_FAMILY, type_scale.SECONDARY, "bold"),
                    wraplength=self.px(500), justify="left",
                    padx=self.px(4),
                )
                warning_label._talkdat_icon_photo = warning_photo  # type: ignore[attr-defined]
                warning_label.grid(row=4, column=0, sticky="ew", pady=(self.px(12), 0))
        self._start_key_poll()

    def _draw_keycap(self, canvas: tk.Canvas, label: str, pressed: bool) -> None:
        canvas.delete("all")
        width = max(self.px(92), canvas.winfo_width())
        height = max(self.px(88), canvas.winfo_height())
        controls = self._button_palette(canvas)
        fill = controls["primary_hover"] if pressed else self.palette["surface"]
        outline = self.palette["accent"] if pressed else self.palette["stroke"]
        foreground = controls["on_primary"] if pressed else self.palette["text"]
        secondary = controls["on_primary"] if pressed else self.palette["muted"]
        _rounded_rectangle(
            canvas,
            self.px(4),
            self.px(4),
            width - self.px(4),
            height - self.px(6),
            self.px(9),
            fill=fill,
            outline=outline,
            width=2 if pressed else 1,
        )
        canvas.create_line(
            self.px(14),
            height - self.px(20),
            width - self.px(14),
            height - self.px(20),
            fill=foreground if pressed else self.palette["stroke"],
            width=self.px(1),
        )
        canvas.create_text(
            width / 2,
            height * 0.43,
            text=label,
            fill=foreground,
            font=(BRAND_UI_FAMILY, type_scale.HEADING, "bold"),
        )
        canvas.create_text(
            width / 2,
            height * 0.70,
            text="PRESSED" if pressed else "waiting",
            fill=secondary,
            font=(BRAND_UI_FAMILY, type_scale.CAPTION, "bold"),
        )

    def _start_key_poll(self) -> None:
        if self.destroyed or ONBOARDING_STEPS[self.step_index].id != "controls":
            return
        chord = primary_hotkey(self.config)
        chord_text = self._chord_text()
        states: list[bool] = []
        labels = hotkey_labels(chord)
        for key, label in zip(chord, labels, strict=False):
            physical = physical_key_down(key)
            pressed = key in self.keyboard_pressed if physical is None else bool(physical)
            states.append(pressed)
            canvas = getattr(self, "key_canvases", {}).get(key)
            if canvas is not None:
                self._draw_keycap(canvas, label, pressed)
        # X-354: this poll runs on the Tk thread at 32ms, and the snapshot
        # crosses into the app's lock. Taken every tick, the UI thread
        # acquires that lock 31 times a second -- which is how a trigger
        # press whose start path held the lock through slow work ghosted
        # this very window. Key light-up stays at 32ms (it reads hardware,
        # no locks); the snapshot only phrases the status line, so a 250ms
        # cadence is indistinguishable to a person and 30x less contention.
        now = time.monotonic()
        cached_at = getattr(self, "_snapshot_taken_at", 0.0)
        if now - cached_at >= 0.25 or not getattr(self, "_snapshot_cache", None):
            self._snapshot_cache = self._status_snapshot()
            self._snapshot_taken_at = now
        snapshot = self._snapshot_cache
        active = bool(snapshot.get("session_active"))
        earned_proof = bool(states and all(states) and not self.hotkey_rehearsed)
        if states and all(states):
            self.hotkey_rehearsed = True
            self.control_status_var.set(
                f"Perfect. {chord_text} is down and the microphone is active."
                if active
                else f"Perfect. {chord_text} is down. Hold it while you speak."
            )
        elif self.hotkey_rehearsed and snapshot.get("overlay_state") == "processing":
            self.control_status_var.set(
                f"Released {chord_text} correctly. Talk DAT! is finishing that capture."
            )
        elif self.hotkey_rehearsed:
            self.control_status_var.set(
                f"Trigger learned. Hold {chord_text} whenever you want to dictate."
            )
        else:
            pressed_count = sum(states)
            single_hold = mac_support.IS_MAC and len(labels) == 1
            if single_hold:
                self.control_status_var.set("That is it - keep holding while you speak, release to finish." if pressed_count else "HOLD the key below and watch it light. Release to finish.")
            else:
                self.control_status_var.set(
                    f"{pressed_count} of {len(states)} keys detected. Keep holding and complete {chord_text}."
                    if pressed_count
                    else f"Press and hold {chord_text}. Each key lights independently."
                )
        if earned_proof:
            self._store_resume_receipt()
        self.key_after = self.window.after(32, self._start_key_poll)

    def _render_permissions(self) -> None:
        """X-23: every macOS permission announced before its dialog appears.

        The list on the left re-checks itself while the page is open, which is
        the part that matters. Granting Accessibility means leaving for System
        Settings, ticking a box and coming back -- if the page still showed a
        red cross on return, the honest conclusion would be that it had not
        worked, and the next thing tried would be granting it a second time.
        """
        pages = permission_pages()
        if not pages:
            return
        self.permission_index = min(self.permission_index, len(pages) - 1)

        body = tk.Frame(self.content, bg=self.palette["panel"], bd=0, highlightthickness=0)
        body.grid(row=1, column=0, sticky="nsew", padx=self.px(30), pady=(0, self.px(16)))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        rail = tk.Frame(body, bg=self.palette["panel"])
        rail.grid(row=0, column=0, sticky="nsw", padx=(0, self.px(22)))
        self._permission_rows: dict[str, tuple[tk.Canvas, tk.Label, tk.Label]] = {}
        for index, page in enumerate(pages):
            row = tk.Frame(rail, bg=self.palette["panel"], cursor="hand2")
            row.grid(row=index, column=0, sticky="ew", pady=(0, self.px(10)))
            tick = tk.Canvas(row, width=self.px(22), height=self.px(22), bg=self.palette["panel"],
                             bd=0, highlightthickness=0)
            tick.grid(row=0, column=0, rowspan=2, padx=(0, self.px(10)))
            name = tk.Label(row, text=page.label, bg=self.palette["panel"], fg=self.palette["text"],
                            font=(mac_support.FONT_UI_SEMIBOLD, 11), anchor="w")
            name.grid(row=0, column=1, sticky="w")
            state = tk.Label(row, text="", bg=self.palette["panel"], fg=self.palette["muted"],
                             font=(mac_support.FONT_UI, 9), anchor="w")
            state.grid(row=1, column=1, sticky="w")
            self._permission_rows[page.key] = (tick, name, state)
            for widget in (row, tick, name, state):
                widget.bind("<Button-1>", lambda _e, i=index: self._show_permission(i), add="+")

        self.permission_detail = tk.Frame(body, bg=self.palette["panel"])
        self.permission_detail.grid(row=0, column=1, sticky="nsew")
        self.permission_detail.columnconfigure(0, weight=1)

        tk.Label(
            body,
            text=GATEKEEPER_NOTE,
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(mac_support.FONT_UI, 9),
            anchor="w",
            justify="left",
            wraplength=self.wrap(self.host_px(900)),
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(self.px(14), 0))

        self._show_permission(self.permission_index)
        self._poll_permissions()
        # The dialogs people expect, fired from a helper process the moment
        # the page opens. Once per wizard: macOS shows each prompt only once
        # per grant anyway, and re-running on every visit would reopen
        # System Settings dialogs nobody asked for.
        report = mac_support.permission_report()
        if all(permission_is_satisfied(report.get(page.key, "unknown")) for page in pages):
            # Field report #8: never ask twice. All three already granted --
            # a resumed or revisited wizard shows the green checklist and
            # fires nothing.
            self.status_var.set("All three are already allowed. Nothing to do on this page.")
        elif not permissions_outstanding(report):
            self.status_var.set(
                "Some permissions could not be checked. You can review them in System Settings."
            )
        elif not getattr(self, "_permission_prompts_fired", False):
            self._permission_prompts_fired = True
            if mac_support.fire_permission_prompts_via_helper():
                self.status_var.set(
                    "macOS is showing its permission pop-ups now. Allow each one; "
                    "the list on the left ticks green by itself."
                )

    def _show_permission(self, index: int) -> None:
        pages = permission_pages()
        if not pages or not getattr(self, "permission_detail", None):
            return
        if not self.permission_detail.winfo_exists():
            return
        self.permission_index = max(0, min(len(pages) - 1, int(index)))
        page = pages[self.permission_index]
        for child in self.permission_detail.winfo_children():
            child.destroy()

        tk.Label(self.permission_detail, text=page.title, bg=self.palette["panel"],
                 fg=self.palette["text"], font=(mac_support.FONT_UI_SEMIBOLD, 15),
                 anchor="w").grid(row=0, column=0, sticky="ew")
        tk.Label(self.permission_detail, text=page.why, bg=self.palette["panel"],
                 fg=self.palette["muted"], font=(mac_support.FONT_UI, 10), anchor="w",
                 justify="left", wraplength=self.wrap(self.host_px(620))).grid(row=1, column=0, sticky="ew", pady=(self.px(6), self.px(12)))

        # A drawing of the actual dialog. The page's whole purpose is that the
        # thing which appears next is recognised, and a picture does that where
        # a paragraph describing a picture does not.
        preview = tk.Canvas(self.permission_detail, height=self.px(132), bg=self.palette["panel"],
                            bd=0, highlightthickness=0)
        preview.grid(row=2, column=0, sticky="ew")
        preview.bind("<Configure>",
                     lambda _e, c=preview, p=page: self._draw_permission_dialog(c, p), add="+")

        tk.Label(self.permission_detail, text=f"Click {page.dialog_button}.", bg=self.palette["panel"],
                 fg=self.palette["text"], font=(mac_support.FONT_UI_SEMIBOLD, 10),
                 anchor="w").grid(row=3, column=0, sticky="ew", pady=(self.px(10), self.px(2)))
        tk.Label(self.permission_detail, text=page.breaks, bg=self.palette["panel"],
                 fg=self.palette["muted"], font=(mac_support.FONT_UI, 9), anchor="w",
                 justify="left", wraplength=self.wrap(self.host_px(620))).grid(row=4, column=0, sticky="ew")

        actions = tk.Frame(self.permission_detail, bg=self.palette["panel"])
        actions.grid(row=5, column=0, sticky="ew", pady=(self.px(14), 0))
        self._detail_button("Show the pop-ups again",
                            lambda: (mac_support.fire_permission_prompts_via_helper(),
                                     self.status_var.set("Asked macOS to show the permission pop-ups again.")),
                            master=actions).grid(row=0, column=0)
        self._detail_button(f"Open {page.settings_path.split(' > ')[-1]} settings",
                            lambda p=page: self._open_permission_settings(p),
                            master=actions).grid(row=0, column=1, padx=(self.px(10), 0))
        self._refresh_permission_states()

    def _draw_permission_dialog(self, canvas: tk.Canvas, page: Any) -> None:
        if not canvas.winfo_exists():
            return
        canvas.delete("all")
        width = max(canvas.winfo_width(), self.px(360))
        height = max(canvas.winfo_height(), self.px(120))
        card_w = min(width, self.px(430))
        left, top = 2, 2
        right, bottom = left + card_w, height - 2
        _rounded_rectangle(canvas, left, top, right, bottom, self.px(12),
                           fill=self.palette.get("field", "#101418"), outline=self.palette["stroke"])
        text_left = left + self.px(58)
        # The app icon macOS puts in its own dialog.
        canvas.create_oval(left + self.px(18), top + self.px(20),
                           left + self.px(46), top + self.px(48),
                           fill="#d8452c", outline="")
        canvas.create_text(text_left, top + self.px(24), anchor="nw", text=page.dialog_title,
                           fill=self.palette["text"], font=(mac_support.FONT_UI_SEMIBOLD, 10),
                           width=card_w - self.px(76))
        canvas.create_text(text_left, top + self.px(62), anchor="nw",
                           text="You can change this later in System Settings.",
                           fill=self.palette["muted"], font=(mac_support.FONT_UI, 9),
                           width=card_w - self.px(76))
        # Two buttons, with the one to click lit. Deliberately shows the refuse
        # button too: it is on the real dialog, and a picture that omits it
        # stops matching the moment it appears.
        button_y2 = bottom - self.px(14)
        button_y1 = button_y2 - self.px(26)
        allow_x2 = right - self.px(16)
        allow_x1 = allow_x2 - self.px(118)
        deny_x2 = allow_x1 - self.px(10)
        deny_x1 = deny_x2 - self.px(90)
        _rounded_rectangle(canvas, deny_x1, button_y1, deny_x2, button_y2, self.px(6),
                           fill=self.palette.get("button", "#1b2228"), outline=self.palette["stroke"])
        canvas.create_text((deny_x1 + deny_x2) / 2, (button_y1 + button_y2) / 2,
                           text="Don't Allow", fill=self.palette["muted"],
                           font=(mac_support.FONT_UI, 9))
        _rounded_rectangle(canvas, allow_x1, button_y1, allow_x2, button_y2, self.px(6),
                           fill=self.palette["accent"], outline="")
        canvas.create_text((allow_x1 + allow_x2) / 2, (button_y1 + button_y2) / 2,
                           text=page.dialog_button, fill="#0d1417",
                           font=(mac_support.FONT_UI_SEMIBOLD, 9))

    def _open_permission_settings(self, page: Any) -> None:
        if mac_support.open_privacy_settings(page.key):
            self.status_var.set(
                f"System Settings > {page.settings_path}. Switch Talk DAT! on, then come back -- "
                "this page notices on its own."
            )
        else:
            self.status_var.set(f"Open System Settings > {page.settings_path} and switch Talk DAT! on.")

    def _refresh_permission_states(self) -> None:
        rows = getattr(self, "_permission_rows", {})
        if not rows:
            return
        report = mac_support.permission_report()
        for key, (tick, _name, state) in rows.items():
            if not tick.winfo_exists():
                continue
            reported = report.get(key, "unknown")
            done = permission_is_satisfied(reported)
            tick.delete("all")
            size = self.px(20)
            colour = self.palette["accent2"] if done else self.palette["stroke"]
            tick.create_oval(2, 2, size, size, outline=colour, width=2,
                             fill=colour if done else self.palette["panel"])
            if done:
                tick.create_line(size * 0.28, size * 0.52, size * 0.44, size * 0.68,
                                 size * 0.74, size * 0.30, fill="#0d1417", width=2,
                                 capstyle="round", joinstyle="round")
            state.configure(
                text={
                    "granted": "Allowed",
                    "denied": "Refused - switch it on in Settings",
                    "not asked": "Not yet allowed",
                }.get(reported, "Cannot be checked on this Mac"),
                fg=self.palette["accent2"] if done else self.palette["muted"],
            )

    def _poll_permissions(self) -> None:
        """Re-read every permission while the page is open.

        Granting these means leaving the app, so the only way the page can be
        truthful when the user comes back is to keep asking.
        """
        if self.destroyed or not getattr(self, "_permission_rows", None):
            return
        self._refresh_permission_states()
        with contextlib.suppress(tk.TclError):
            self.permission_after = self.window.after(1200, self._poll_permissions)

    def _render_superpowers(self) -> None:
        """Present the six core behaviors as one coherent command deck."""
        body = tk.Frame(self.content, bg=self.palette["panel"], bd=0, highlightthickness=0)
        body.grid(row=1, column=0, sticky="nsew", padx=self.px(28), pady=(0, self.px(20)))
        body.columnconfigure(0, weight=5, uniform="powers")
        body.columnconfigure(1, weight=5, uniform="powers")
        body.rowconfigure(0, weight=1)

        visual = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        visual.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(24)))
        visual.columnconfigure(0, weight=1)
        art = self._art_panel(visual, "superpowers", height=340, centering=(0.5, 0.5))
        art.grid(row=0, column=0, sticky="nsew")
        tk.Label(
            visual,
            text="Six things Talk DAT! does for you.",
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.BODY),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(self.px(8), 0))

        features = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        features.grid(row=0, column=1, sticky="nsew")
        features.columnconfigure(0, weight=1)

        # This claim follows the route the person actually chose. Cloud routes
        # upload audio to their transcription service; local does not.
        try:
            chosen_route = str(self.route_var.get() or "").strip().lower()
        except Exception:
            chosen_route = ""
        if chosen_route == "local":
            privacy_card = (
                f"Your voice stays on {platform_copy.THIS_COMPUTER}",
                "On the local route, audio is transcribed here and never uploaded.",
            )
        else:
            # Said before a route is picked, too: the cautious phrasing rather
            # than the flattering one.
            privacy_card = (
                "You choose where your voice goes",
                "Cloud routes send audio to the transcription service; local keeps it here.",
            )

        cards = (
            ("Finished writing", "Talk DAT! cleans punctuation and structure before delivering the result."),
            ("Your words", "Correct a name or phrase once, then save it from the Pill menu for later."),
            ("Voice editing", "Highlight text, use the Fix That trigger, and say the change you want."),
            ("Translation", "Use the translation workspace with a cloud or on-device route."),
            ("Protected recovery", "If cloud transcription misses, Talk DAT! can retry captured audio on-device."),
            privacy_card,
        )
        for row, (title, detail) in enumerate(cards):
            self._fact_row(
                features,
                row,
                title,
                detail,
                accent=self.palette["accent"] if row in {0, 2} else self.palette["accent2"],
                compact=True,
            )

    def wrap(self, value: int) -> int:
        """A design-time wraplength, scaled to the window this wizard got.
        Fixed design-width wraplengths overflow a clamped window and read as
        "the menu does not scale to my resolution" -- because it didn't."""
        return max(180, int(value * getattr(self, "fit", 1.0)))

    def host_px(self, value: int) -> int:
        with contextlib.suppress(Exception):
            from .. import ui_scale

            return ui_scale.px(value, getattr(self.host, "config", {}))
        return value

    def _render_menu(self) -> None:
        """Teach the real Pill Panel using its current live row model."""
        body = tk.Frame(self.content, bg=self.palette["panel"], bd=0, highlightthickness=0)
        body.grid(row=1, column=0, sticky="nsew", padx=self.px(28), pady=(0, self.px(20)))
        body.columnconfigure(0, weight=5, uniform="menu")
        body.columnconfigure(1, weight=5, uniform="menu")
        body.rowconfigure(0, weight=1)

        visual = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        visual.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(24)))
        visual.columnconfigure(0, weight=1)
        art = self._art_panel(visual, "menu", height=322, centering=(0.52, 0.5))
        art.grid(row=0, column=0, sticky="nsew")
        tk.Label(
            visual,
            text=f"{mac_support.SECONDARY_CLICK_PHRASE} the Pill any time to open the menu.",
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.BODY),
            anchor="w",
            justify="left",
            wraplength=self.px(420),
        ).grid(row=1, column=0, sticky="ew", pady=(self.px(8), 0))

        panel = tk.Frame(
            body,
            bg=self.palette["surface"],
            bd=0,
            highlightthickness=1,
            highlightbackground=self.palette["stroke"],
        )
        panel.grid(row=0, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        tk.Label(
            panel,
            text="PINNED SWITCHES",
            bg=self.palette["surface"],
            fg=self.palette["accent2"],
            font=(BRAND_UI_FAMILY, type_scale.CAPTION, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=self.px(16), pady=(self.px(12), self.px(4)))
        current_route = self.route_var.get()
        route_label = "Cloud" if current_route == "managed" else "Local" if current_route == "local" else "Your key" if current_route == "byok" else "Auto"
        finish_label = "Executive" if str(self.config.get("cleanup", {}).get("format_intensity", "standard")) == "executive" else "Chill"
        tk.Label(
            panel,
            text=f"Speech: {route_label}     Finish: {finish_label}",
            bg=self.palette["select"],
            fg=self.palette["text"],
            font=(BRAND_UI_FAMILY, type_scale.SECONDARY, "bold"),
            anchor="w",
            padx=self.px(12),
            pady=self.px(8),
        ).grid(row=1, column=0, sticky="ew", padx=self.px(12), pady=(0, self.px(8)))

        try:
            current_rows = list(self.host._context_menu_rows())
        except Exception:
            current_rows = []
        top_level_actions = {
            "settings",
            "paste_last",
            "history",
            "more_features",
            "check_updates",
            "stats",
            "restart_app",
            "quit_app",
        }
        visible_rows = [row for row in current_rows if row[0] in top_level_actions]
        for row_index, (action, title, subtitle, _icon) in enumerate(visible_rows, start=2):
            row = tk.Frame(panel, bg=self.palette["surface"], bd=0, highlightthickness=0)
            row.grid(row=row_index, column=0, sticky="ew", padx=self.px(16), pady=(0, self.px(4)))
            row.columnconfigure(1, weight=1)
            marker = tk.Canvas(row, width=self.px(16), height=self.px(26), bg=self.palette["surface"], bd=0, highlightthickness=0)
            marker.grid(row=0, column=0, sticky="n", padx=(0, self.px(8)))
            marker.create_oval(
                self.px(5), self.px(10), self.px(11), self.px(16),
                fill=self.palette["accent"] if action in {"settings", "paste_last", "history"} else self.palette["stroke"],
                outline="",
            )
            display_title = f"{title}: {subtitle}" if action == "more_features" and subtitle else title
            tk.Label(
                row,
                text=display_title,
                bg=self.palette["surface"],
                fg=self.palette["text"],
                font=(BRAND_UI_FAMILY, type_scale.BODY),
                anchor="w",
                justify="left",
                wraplength=self.px(410),
            ).grid(row=0, column=1, sticky="ew")

        if not visible_rows:
            tk.Label(
                panel,
                text="The Pill menu is available as soon as setup closes.",
                bg=self.palette["surface"],
                fg=self.palette["muted"],
                font=(BRAND_UI_FAMILY, type_scale.BODY),
                anchor="w",
                justify="left",
                wraplength=self.px(420),
            ).grid(row=2, column=0, sticky="ew", padx=self.px(16), pady=self.px(16))

        def open_live_pill_panel() -> None:
            self.host._open_context_menu_from_event()
            self.status_var.set("Pill menu opened. Use arrow keys to explore; Escape closes it.")

        self._detail_button(
            "Open the Pill menu",
            open_live_pill_panel,
            master=panel,
            min_width=164,
        ).grid(
            row=(2 + len(visible_rows)) if visible_rows else 3,
            column=0,
            sticky="w",
            padx=self.px(16),
            pady=(self.px(12), self.px(16)),
        )

    def _render_writing(self) -> None:
        body = tk.Frame(self.content, bg=self.palette["panel"], bd=0, highlightthickness=0)
        body.grid(row=1, column=0, sticky="nsew", padx=self.px(28), pady=(0, self.px(20)))
        body.columnconfigure(0, weight=5, uniform="writing")
        body.columnconfigure(1, weight=5, uniform="writing")
        body.rowconfigure(0, weight=1)
        visual = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        visual.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(24)))
        visual.columnconfigure(0, weight=1)
        art = self._art_panel(visual, "writing", height=326, centering=(0.5, 0.5))
        art.grid(row=0, column=0, sticky="nsew")
        visual_caption = tk.Label(
            visual,
            text="The preset controls structure. Chill and Executive control how much your wording changes.",
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.BODY),
            anchor="w",
            justify="left",
        )
        visual_caption.grid(row=1, column=0, sticky="ew", pady=(self.px(8), 0))
        self._bind_responsive_wrap(visual_caption, visual, maximum=420, initial=180)

        options = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        options.grid(row=0, column=1, sticky="nsew")
        options.columnconfigure(0, weight=1)
        self.writing_buttons: dict[str, tk.Radiobutton] = {}
        self.writing_cards: dict[str, tuple[tk.Frame, tk.Label, tk.Label]] = {}
        for row, preset in enumerate(("smart", "fast", "verbatim")):
            data = WRITING_PRESETS[preset]
            card = tk.Frame(
                options,
                bg=self.palette["surface"],
                bd=0,
                highlightthickness=1,
                highlightbackground=self.palette["stroke"],
                cursor="hand2",
            )
            card.grid(row=row, column=0, sticky="ew", pady=(0, self.px(12)) if row < 2 else 0)
            card.columnconfigure(0, weight=1)
            header = tk.Frame(card, bg=self.palette["surface"], bd=0, highlightthickness=0)
            header.grid(row=0, column=0, sticky="ew", padx=self.px(12), pady=(self.px(8), 0))
            header.columnconfigure(0, weight=1)
            radio = tk.Radiobutton(
                header,
                text=str(data["title"]),
                variable=self.writing_var,
                value=preset,
                command=lambda selected=preset: self._select_writing(selected),
                indicatoron=True,
                anchor="w",
                justify="left",
                font=(BRAND_UI_FAMILY, type_scale.SUBHEADING, "bold"),
                bg=self.palette["surface"],
                fg=self.palette["text"],
                activebackground=self.palette["surface"],
                activeforeground=self.palette["text"],
                selectcolor=self.palette["surface"],
                highlightthickness=1,
                highlightbackground=self.palette["surface"],
                highlightcolor=self.palette["accent2"],
                bd=0,
                takefocus=True,
                cursor="hand2",
            )
            radio.grid(row=0, column=0, sticky="ew")
            badge_label = tk.Label(
                header,
                text=str(data["badge"]),
                bg=self.palette["surface"],
                fg=self.palette["accent2"],
                font=(BRAND_UI_FAMILY, type_scale.CAPTION, "bold"),
                anchor="e",
            )
            badge_label.grid(row=0, column=1, sticky="e", padx=(self.px(8), 0))
            description_label = tk.Label(
                card,
                text=str(data["description"]),
                bg=self.palette["surface"],
                fg=self.palette["muted"],
                font=(BRAND_UI_FAMILY, type_scale.BODY),
                anchor="w",
                justify="left",
                wraplength=self.px(360),
            )
            description_label.grid(
                row=1,
                column=0,
                sticky="ew",
                padx=(self.px(36), self.px(12)),
                pady=(self.px(4), self.px(12)),
            )
            self._bind_responsive_wrap(description_label, card, maximum=390, reserve=48, initial=180)
            for sequence in ("<Left>", "<Up>"):
                radio.bind(sequence, lambda _event, selected=preset: self._move_writing_choice(selected, -1))
            for sequence in ("<Right>", "<Down>"):
                radio.bind(sequence, lambda _event, selected=preset: self._move_writing_choice(selected, 1))
            radio.bind("<Return>", lambda _event, selected=preset: self._activate_writing_control(selected))
            radio.bind("<FocusIn>", lambda _event, selected=preset: self._style_writing_card(selected), add="+")
            radio.bind("<FocusOut>", lambda _event, selected=preset: self._style_writing_card(selected), add="+")
            for target in (card, header, badge_label, description_label):
                target.bind("<Button-1>", lambda _event, selected=preset: self._activate_writing_control(selected))
            self.writing_buttons[preset] = radio
            self.writing_cards[preset] = (card, badge_label, description_label)
            self._style_writing_card(preset)
        recommendation = tk.Label(
            options,
            text="Smart and faithful is recommended. It creates structure only when your spoken intent clearly calls for it.",
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.BODY),
            justify="left",
            anchor="w",
        )
        recommendation.grid(row=3, column=0, sticky="ew", pady=(self.px(12), 0))
        self._bind_responsive_wrap(recommendation, options, maximum=440, initial=180)

    def _activate_writing_control(self, preset: str) -> str:
        button = getattr(self, "writing_buttons", {}).get(preset)
        if button is None:
            return "break"
        button.focus_set()
        button.invoke()
        return "break"

    def _style_writing_card(self, preset: str) -> None:
        button = getattr(self, "writing_buttons", {}).get(preset)
        card_parts = getattr(self, "writing_cards", {}).get(preset)
        if button is None or card_parts is None or not button.winfo_exists():
            return
        card, badge_label, description_label = card_parts
        selected = self.writing_var.get() == preset
        focused = button.focus_get() is button
        fill = self.palette["select"] if selected else self.palette["surface"]
        outline = self.palette["accent2"] if focused else self.palette["accent"] if selected else self.palette["stroke"]
        card.configure(
            bg=fill,
            highlightbackground=outline,
            highlightcolor=outline,
            highlightthickness=self.px(2) if selected or focused else self.px(1),
        )
        for child in card.winfo_children():
            with contextlib.suppress(tk.TclError):
                child.configure(bg=fill)
        button.configure(
            bg=fill,
            fg=self.palette["text"],
            activebackground=fill,
            activeforeground=self.palette["text"],
            selectcolor=fill,
        )
        badge_label.configure(bg=fill, fg=self.palette["accent2"])
        description_label.configure(bg=fill, fg=self.palette["muted"])

    def _select_writing(self, preset: str) -> None:
        self.writing_var.set(preset if preset in WRITING_PRESETS else "smart")
        for option in getattr(self, "writing_buttons", {}):
            self._style_writing_card(option)

    def _move_writing_choice(self, current: str, direction: int) -> str:
        """Arrow-key radio navigation for the mutually exclusive writing presets."""

        order = ("smart", "fast", "verbatim")
        start = order.index(current) if current in order else 0
        step = 1 if direction >= 0 else -1
        candidate = order[(start + step) % len(order)]
        self._select_writing(candidate)
        button = getattr(self, "writing_buttons", {}).get(candidate)
        if button is not None:
            with contextlib.suppress(Exception):
                button.focus_set()
        return "break"

    def _render_test(self) -> None:
        body = tk.Frame(self.content, bg=self.palette["panel"], bd=0, highlightthickness=0)
        body.grid(row=1, column=0, sticky="nsew", padx=self.px(28), pady=(0, self.px(20)))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        self.test_hero = tk.Frame(body, bg=self.palette["panel"], bd=0, highlightthickness=0)
        self.test_hero.grid(row=0, column=0, sticky="ew")
        self.test_hero.columnconfigure(0, weight=4, uniform="test-hero")
        self.test_hero.columnconfigure(1, weight=6, uniform="test-hero")
        art = self._art_panel(self.test_hero, "test", height=112, centering=(0.5, 0.5))
        art.grid(row=0, column=0, sticky="ew", padx=(0, self.px(12)))
        self.test_visual = tk.Canvas(
            self.test_hero,
            height=self.px(112),
            bg=self.palette["surface"],
            bd=0,
            highlightthickness=1,
            highlightbackground=self.palette["stroke"],
        )
        self.test_visual.grid(row=0, column=1, sticky="ew")
        self.test_visual.bind("<Configure>", lambda _event: self._draw_test_visual())
        action_row = tk.Frame(body, bg=self.palette["panel"])
        action_row.grid(row=1, column=0, sticky="ew", pady=(self.px(12), self.px(8)))
        action_row.columnconfigure(0, weight=1)
        tk.Label(
            action_row,
            textvariable=self.practice_status_var,
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.SECONDARY, "bold"),
            anchor="w",
            justify="left",
            wraplength=self.px(650),
        ).grid(row=0, column=0, sticky="ew")
        self.test_button = self._detail_button(
            "Start with mouse",
            self._toggle_test,
            master=action_row,
            primary=True,
            min_width=142,
        )
        self.test_button.grid(row=0, column=1, sticky="e")
        self.practice_text = tk.Text(
            body,
            height=6,
            wrap="word",
            bg=self.palette["field"],
            fg=self.palette["text"],
            insertbackground=self.palette["text"],
            selectbackground=self.palette["select"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.palette["stroke"],
            highlightcolor=self.palette["accent"],
            font=(BRAND_UI_FAMILY, type_scale.BODY),
            padx=self.px(16),
            pady=self.px(12),
        )
        leading.apply(self.practice_text, prose=True)
        self.practice_text.grid(row=2, column=0, sticky="nsew")
        self.practice_text.insert(
            "1.0",
            "TRY THIS OR USE YOUR OWN WORDS\n\n"
            "Hi Sam, can we move our call to Thursday at 3 PM? "
            "Before then I need three things: the final logo, the updated timeline, and the client's notes.",
        )
        self.practice_text.configure(state="disabled")
        tk.Label(
            body,
            text="For safety, the setup test is routed into this box instead of whichever app was previously focused. Normal auto-paste resumes after setup.",
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.BODY),
            justify="left",
            anchor="w",
            wraplength=self.px(860),
        ).grid(row=3, column=0, sticky="ew", pady=(self.px(8), 0))

        self._render_terms_notice(body, 4)
        self.host.onboarding_test_sink = self.test_sink
        self._poll_test()

    def _draw_test_visual(self) -> None:
        canvas = getattr(self, "test_visual", None)
        if canvas is None or not canvas.winfo_exists():
            return
        canvas.delete("all")
        width = max(self.px(260), canvas.winfo_width())
        height = max(self.px(96), canvas.winfo_height())
        state = str(self._status_snapshot().get("overlay_state", "idle"))
        active = state in {"starting", "connected", "listening", "command"}
        processing = state == "processing"
        wave_width = max(self.px(92), min(self.px(260), width - self.px(150)))
        image = self.host._compact_wave_frame(wave_width, self.px(52), active=active or processing)
        if image is not None:
            if processing:
                image = ImageEnhance.Color(image).enhance(1.65)
                image = ImageEnhance.Brightness(image).enhance(1.15)
            photo = ImageTk.PhotoImage(image, master=canvas)
            self.dynamic_photos["test"] = photo
            canvas.create_image(self.px(16), height / 2, image=photo, anchor="w")
        label = "LISTENING" if active else "FORMATTING" if processing else "READY"
        color = self.palette["accent2"] if active else self.palette["warm"] if processing else self.palette["muted"]
        canvas.create_text(width - self.px(16), height / 2 - self.px(9), text=label, anchor="e", fill=color, font=(BRAND_UI_FAMILY, type_scale.CAPTION, "bold"))
        canvas.create_text(width - self.px(16), height / 2 + self.px(12), text="Hold trigger or use mouse", anchor="e", fill=self.palette["muted"], font=(BRAND_UI_FAMILY, type_scale.CAPTION))

    def _render_terms_notice(self, parent: tk.Widget, row: int) -> None:
        """X-428: the last thing above Finish. Real text, real links, in the tab order.

        Placed here rather than as a launch modal on purpose -- setup already
        ends on a button, so accepting costs the press that was happening
        anyway. What that press accepted is written into config by
        mark_onboarding_complete.
        """
        holder = tk.Frame(parent, bg=self.palette["panel"])
        holder.grid(row=row, column=0, sticky="ew", pady=(self.px(10), 0))

        tk.Label(
            holder,
            text=(
                f"Talk DAT! runs on {platform_copy.THIS_COMPUTER}. On the local route your speech is transcribed on this "
                "machine and never sent anywhere. A cloud route sends it to the provider you pick, "
                "and you choose the route every time. An account is optional; if you make one we "
                "keep only your email and which computers are signed in. We never count or keep "
                "what you dictate."
            ),
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.CAPTION),
            anchor="w",
            justify="left",
            wraplength=self.px(620),
        ).grid(row=0, column=0, columnspan=4, sticky="ew")

        tk.Label(
            holder,
            text="Finishing setup accepts the",
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.CAPTION),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(self.px(4), 0))
        self._terms_link(holder, 1, 1, "Terms", TERMS_URL)
        tk.Label(
            holder,
            text="and the",
            bg=self.palette["panel"],
            fg=self.palette["muted"],
            font=(BRAND_UI_FAMILY, type_scale.CAPTION),
        ).grid(row=1, column=2, sticky="w", padx=(self.px(4), 0), pady=(self.px(4), 0))
        self._terms_link(holder, 1, 3, "Privacy Notice", PRIVACY_URL)
        holder.columnconfigure(4, weight=1)
        # Owner decision 2026-09-23: one line and the toggle, no nag, and only
        # in a build that can send the counts at all.
        from ..official_build import USAGE_COUNTS_LINE, usage_counts_available

        if usage_counts_available():
            tk.Checkbutton(
                holder,
                text=USAGE_COUNTS_LINE,
                variable=self.share_counts_var,
                anchor="w",
                justify="left",
                wraplength=self.px(620),
                font=(BRAND_UI_FAMILY, type_scale.CAPTION),
                bg=self.palette["panel"],
                fg=self.palette["muted"],
                activebackground=self.palette["panel"],
                activeforeground=self.palette["text"],
                selectcolor=self.palette["panel"],
                highlightthickness=1,
                highlightbackground=self.palette["panel"],
                highlightcolor=self.palette["accent2"],
                bd=0,
                takefocus=True,
                cursor="hand2",
            ).grid(row=2, column=0, columnspan=5, sticky="w", pady=(self.px(6), 0))

    def _terms_link(self, parent: tk.Widget, row: int, column: int, text: str, url: str) -> None:
        link = tk.Label(
            parent,
            text=text,
            bg=self.palette["panel"],
            fg=self.palette["accent2"],
            font=(BRAND_UI_FAMILY, type_scale.CAPTION, "underline"),
            cursor="hand2",
            takefocus=True,
        )
        link.grid(row=row, column=column, sticky="w", padx=(self.px(4), 0), pady=(self.px(4), 0))
        open_it = lambda _event=None, target=url: webbrowser.open(target)
        link.bind("<Button-1>", open_it)
        link.bind("<Return>", open_it)
        link.bind("<space>", open_it)

    def _toggle_test(self) -> None:
        snapshot = self._status_snapshot()
        if snapshot.get("session_active"):
            self._invoke_callback("push_to_talk_stop")
            return
        holder = getattr(self, "finish_choice_frame", None)
        if holder is not None and holder.winfo_exists():
            holder.destroy()
        hero = getattr(self, "test_hero", None)
        if hero is not None and hero.winfo_exists():
            hero.grid()
        with contextlib.suppress(Exception):
            self.practice_text.grid()
            self.practice_text.master.rowconfigure(2, weight=1)
            self.practice_text.configure(height=6)
        self.test_started_by_button = True
        self._invoke_callback("push_to_talk")

    def _finishing_verdict(self) -> dict[str, Any]:
        """X-389: what the test step may honestly claim about finishing.

        The founder ran the setup test on a PC that was signed out: Talk DAT!
        Cloud refused the finishing pass, the rules tidy ran instead, both
        preview boxes showed the same untouched words, and the step still
        said "formatting all completed". `finishing_status` already knows the
        truth (X-366); the wizard just never asked."""
        try:
            from ..llm import finishing_status

            verdict = finishing_status(self.config)
        except Exception:
            return {"ok": False, "reason": "unknown", "message": "Finishing readiness could not be checked. Your test words remain available."}
        return verdict if isinstance(verdict, dict) and type(verdict.get("ok")) is bool else {"ok": False, "reason": "unknown", "message": "Finishing readiness could not be checked."}

    def _poll_test(self) -> None:
        if self.destroyed or ONBOARDING_STEPS[self.step_index].id != "test":
            return
        snapshot = self._status_snapshot()
        active = bool(snapshot.get("session_active"))
        state = str(snapshot.get("overlay_state", "idle"))
        if active:
            self.practice_status_var.set("Listening - speak naturally, then release the keys or click Stop.")
            self.test_button.configure(text="Stop test")
        elif state == "processing":
            self.practice_status_var.set("Formatting and protecting your result...")
            self.test_button.configure(text="Working...", state="disabled")
        elif self.dictation_tested:
            self.practice_status_var.set("Test received. Review the words above; you can record another test whenever you want.")
            self.test_button.configure(text="Test again", state="normal")
        else:
            self.practice_status_var.set(f"Ready when you are. HOLD {self._chord_text()} while speaking, or start with the mouse.")
            self.test_button.configure(text="Start with mouse", state="normal")
        preview = str(getattr(self.host, "last_preview", "") or "").strip()
        if active and preview:
            self._set_practice_text(preview)
        self._draw_test_visual()
        self.test_after = self.window.after(70, self._poll_test)

    def _receive_test_result(self, text: str) -> None:
        if self.destroyed:
            return

        if ONBOARDING_STEPS[self.step_index].id == "controls":
            def deliver_rehearsal() -> None:
                if self.destroyed or ONBOARDING_STEPS[self.step_index].id != "controls":
                    return
                self.control_status_var.set(
                    f"{self._chord_text()} complete. Your rehearsal stayed inside setup and normal delivery remains protected."
                    if str(text).strip()
                    else f"{self._chord_text()} complete. No speech was returned, but nothing was pasted outside setup."
                )

            self.window.after(0, deliver_rehearsal)
            return

        def deliver() -> None:
            if self.destroyed or ONBOARDING_STEPS[self.step_index].id != "test":
                return
            earned_proof = bool(str(text).strip()) and not self.dictation_tested
            self.dictation_tested = bool(str(text).strip())
            if earned_proof:
                self._store_resume_receipt()
            self._set_practice_text(str(text).strip() or "No speech was returned. Try again or finish setup and use protected-audio recovery.")
            self.practice_status_var.set("These are the words Talk DAT produced." if self.dictation_tested else "No speech was returned. Try the microphone check or record another test.")
            # X-137: the finish decision, put to the user with THEIR OWN
            # words as the example -- the same take, both finishes, choose.
            if self.dictation_tested:
                self._offer_finish_choice()

        self.window.after(0, deliver)

    def _offer_finish_choice(self) -> None:
        raw_callback = self.host.callbacks.get("last_raw_text")
        both_callback = self.host.callbacks.get("format_both")
        raw = str(raw_callback() or "").strip() if callable(raw_callback) else ""
        if not raw or not callable(both_callback):
            return

        def show(chill: str, executive: str) -> None:
            if self.destroyed or ONBOARDING_STEPS[self.step_index].id != "test":
                return
            holder = getattr(self, "finish_choice_frame", None)
            if holder is not None and holder.winfo_exists():
                holder.destroy()
            hero = getattr(self, "test_hero", None)
            if hero is not None and hero.winfo_exists():
                hero.grid_remove()
            with contextlib.suppress(Exception):
                self.practice_text.grid_remove()
                self.practice_text.master.rowconfigure(2, weight=0)
            parent = self.practice_text.master
            holder = tk.Frame(parent, bg=self.palette["panel"], bd=0, highlightthickness=0)
            holder.grid(row=4, column=0, sticky="ew", pady=(self.px(8), 0))
            holder.columnconfigure(0, weight=1)
            holder.columnconfigure(1, weight=1)
            self.finish_choice_frame = holder
            tk.Label(
                holder,
                text=(
                    "Same recording, two versions. Pick the style you prefer; you can switch any time from the Pill menu. "
                    "Identical text means there was no visible difference on this take."
                ),
                bg=self.palette["panel"],
                fg=self.palette["text"],
                font=(BRAND_UI_FAMILY, type_scale.SUBHEADING, "bold"),
                anchor="w",
                justify="left",
                wraplength=self.px(820),
            ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, self.px(8)))

            def pane(column: int, title: str, color: str, body_text: str, key: str, button_text: str) -> None:
                frame = tk.Frame(holder, bg=self.palette["surface"], bd=0, highlightthickness=1, highlightbackground=self.palette["stroke"])
                frame.grid(row=1, column=column, sticky="nsew", padx=(0, self.px(8)) if column == 0 else (self.px(8), 0))
                frame.columnconfigure(0, weight=1)
                tk.Label(frame, text=title, bg=self.palette["surface"], fg=color, font=(BRAND_UI_FAMILY, type_scale.CAPTION, "bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=self.px(12), pady=(self.px(8), 0))
                box = tk.Text(
                    frame,
                    height=5,
                    wrap="word",
                    bg=self.palette["surface"],
                    fg=self.palette["text"],
                    relief="flat",
                    bd=0,
                    highlightthickness=self.px(2),
                    highlightbackground=self.palette["stroke"],
                    highlightcolor=self.palette["accent"],
                    takefocus=1,
                    font=(BRAND_UI_FAMILY, type_scale.BODY),
                    padx=self.px(12),
                    pady=self.px(8),
                )
                leading.apply(box)
                box.grid(row=1, column=0, sticky="nsew")
                scrollbar = ttk.Scrollbar(
                    frame,
                    orient="vertical",
                    command=box.yview,
                    style="Flow.Vertical.TScrollbar",
                )
                scrollbar.grid(row=1, column=1, sticky="ns")

                def update_overflow(first: str, last: str) -> None:
                    scrollbar.set(first, last)
                    if float(first) <= 0.0 and float(last) >= 1.0:
                        scrollbar.grid_remove()
                    else:
                        scrollbar.grid()

                box.configure(yscrollcommand=update_overflow)
                box.insert("1.0", body_text.strip() or "(no preview)")
                box.configure(state="disabled")
                self._detail_button(button_text, lambda choice=key: choose(choice), master=frame, min_width=112).grid(row=2, column=0, sticky="e", padx=self.px(12), pady=(0, self.px(8)))

            def choose(key: str) -> None:
                candidate = copy.deepcopy(self.config)
                cleanup = candidate.setdefault("cleanup", {})
                cleanup["format_intensity"] = key
                cleanup["intensity_default_migrated"] = True
                if not self._save_setup(candidate):return
                label = "Executive" if key == "executive" else "Chill"
                self.practice_status_var.set(f"{label} is now your default writing style. Change it any time from the Pill menu.")
                if holder.winfo_exists():
                    holder.destroy()

            pane(0, "CHILL - YOUR WORDS, TIDIED", self.palette["warm"], chill, "standard", "Use Chill")
            pane(1, "EXECUTIVE - MORE FORMAL", self.palette["accent2"], executive, "executive", "Use Executive")

        try:
            both_callback(raw, show)
        except Exception:
            pass

    def _set_practice_text(self, text: str) -> None:
        widget = getattr(self, "practice_text", None)
        if widget is None or not widget.winfo_exists():
            return
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _status_snapshot(self) -> dict[str, Any]:
        callback = self.host.callbacks.get("status_provider")
        if not callable(callback):
            return {}
        try:
            value = callback()
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _key_press(self, event: tk.Event) -> None:
        key = self._event_key(event)
        if key:
            self.keyboard_pressed.add(key)

    def _key_release(self, event: tk.Event) -> None:
        key = self._event_key(event)
        if key:
            self.keyboard_pressed.discard(key)

    def _event_key(self, event: tk.Event) -> str:
        keysym = str(getattr(event, "keysym", "")).lower()
        if keysym.startswith("control"):
            return "ctrl"
        if keysym.startswith("alt"):
            return "alt"
        if keysym.startswith("shift"):
            return "shift"
        # Aqua reports Command as Meta_L/Meta_R. Without this the Controls step
        # could never be completed on a Mac: the person holds exactly the chord
        # they were told to, the Ctrl keycap lights, the other one stays grey
        # forever, and "now press the other key" never goes away.
        if keysym in {"super_l", "super_r", "win_l", "win_r", "meta_l", "meta_r",
                      "command_l", "command_r"}:
            return "cmd"
        if keysym == "space":
            return "space"
        return keysym

    def previous_step(self) -> None:
        if self.step_index <= 0:
            return
        self.render_step(self.step_index - 1)

    def next_step(self) -> None:
        step_id = ONBOARDING_STEPS[self.step_index].id
        if step_id == "access":
            self.config.setdefault("onboarding", {})["access_choice"] = self.access_choice
        if step_id == "voice" and not self._commit_voice_route():
            return
        if step_id == "microphone":
            candidate = copy.deepcopy(self.config)
            candidate.setdefault("audio", {})["input_device"] = "" if self.audio_device_var.get() == WINDOWS_DEFAULT_MIC else self.audio_device_var.get().strip()
            if not self._save_setup(candidate):return
        if step_id == "writing":
            candidate = copy.deepcopy(self.config)
            apply_writing_preset(candidate, self.writing_var.get())
            if not self._save_setup(candidate):return
        if step_id == "test":
            self.finish()
            return
        self.render_step(self.step_index + 1)

    def finish(self) -> None:
        if not self._commit_voice_route():
            return
        candidate = copy.deepcopy(self.config)
        apply_writing_preset(candidate, self.writing_var.get())
        from ..official_build import usage_counts_available

        if usage_counts_available():
            privacy = candidate.get("privacy")
            if not isinstance(privacy, dict):
                privacy = candidate["privacy"] = {}
            privacy["share_usage_counts"] = bool(self.share_counts_var.get())
        mark_onboarding_complete(candidate, route=self.route_var.get(),
            microphone_tested=self.microphone_tested, hotkey_rehearsed=self.hotkey_rehearsed,
            dictation_tested=self.dictation_tested, access_choice=self.access_choice)
        if not self._save_setup(candidate):
            return
        self.host.set_state("captured", "Setup saved.",
            "Hold your trigger, speak, and release to paste. Untested steps remain available in Help."
            if getattr(self, "_setup_runtime_refreshed", True)
            else "Restart Talk DAT to apply every saved setting.")
        self.window.destroy()


    def _invoke_callback(self, name: str) -> Any:
        callback = self.host.callbacks.get(name)
        if callable(callback):
            return callback()
        return None

    def _stop_page_activity(self) -> None:
        self._stop_meter()
        if self.account_after:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(self.account_after)
            self.account_after = None
        if self.key_after:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(self.key_after)
            self.key_after = None
        if self.test_after:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(self.test_after)
            self.test_after = None
        if self.permission_after:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(self.permission_after)
            self.permission_after = None
        self._permission_rows = {}
        self._dispose_test_capture()

    def _dispose_test_capture(self) -> None:
        """End a capture this page started, then take our sink back.

        X-183. The setup test promises, on screen, that "the setup test is routed
        into this box instead of whichever app was previously focused". Leaving
        the page cleared the sink and left the capture RUNNING, so the transcript
        arrived with nowhere to go and fell through to ordinary auto-paste --
        into whatever application was behind the wizard. During first-run setup,
        which is the worst possible moment to type into a stranger's window.

        Three details, all of which the previous code got wrong, and all of which
        match the `dispose_speak` fix already shipped for Translation:

        CANCEL, not `push_to_talk_stop`. Stop FINALISES the dictation, so with
        the sink already gone, stopping is precisely what delivers it to the
        wrong place. Cancel discards it.

        Cancel runs BEFORE the sink is cleared, so no result can land in the gap
        with the capture live and the sink already absent.

        Only OUR sink is reclaimed. Clearing another surface's sink would hand
        ITS transcript to auto-paste, which is the same defect relocated.

        The old code also gated its stop on `test_started_by_button`, so a
        capture begun with the real trigger -- keyboard, mouse or controller --
        escaped entirely. Ownership is the sink's identity now, not which control
        happened to start it.
        """
        if getattr(self.host, "onboarding_test_sink", None) is not self.test_sink:
            return
        snapshot = self._status_snapshot()
        in_flight_states = {"starting", "connected", "listening", "command", "processing"}
        try:
            if snapshot.get("session_active") or str(snapshot.get("overlay_state", "idle")) in in_flight_states:
                with contextlib.suppress(Exception):
                    self._invoke_callback("cancel")
        finally:
            self.test_started_by_button = False
            # Cancellation can run arbitrary host cleanup. Do not erase a new
            # owner that legitimately claimed the shared sink during it.
            if getattr(self.host, "onboarding_test_sink", None) is self.test_sink:
                self.host.onboarding_test_sink = None

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self.window or self.destroyed:
            return
        self.destroyed = True
        self._cancel_content_extent_sync()
        self._cancel_all_art_panel_draws()
        # `_stop_page_activity` disposes the capture for BOTH endings now, so the
        # old `test_started_by_button` branch here is gone: it only ever covered
        # the button, and a trigger-started capture walked straight past it.
        self._stop_page_activity()


def open_onboarding_wizard(host: Any, *, step: str | None = None) -> None:
    """Open setup, optionally straight at one page.

    `step` exists for X-23: a Mac whose permissions were cleared -- which is
    what replacing the app does, since the grants are bound to its code
    signature -- needs the permission page and nothing else. Sending it back
    through the whole wizard would re-ask for the account choice, the speech
    route and the writing preset that were already settled.
    """
    wizard = OnboardingWizard(host)
    if step:
        with contextlib.suppress(Exception):
            ids = [item.id for item in ONBOARDING_STEPS]
            if step in ids:
                wizard.render_step(ids.index(step))
    return wizard
