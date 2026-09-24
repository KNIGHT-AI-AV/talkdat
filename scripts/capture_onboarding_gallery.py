"""Capture every Windows onboarding page without starting the production app.

This is a developer-only visual regression helper. It builds the real wizard
against a minimal host, leaves the microphone off, and saves one PNG per step.
No user configuration, account, network route, or release artifact is touched.
"""

from __future__ import annotations

import argparse
import copy
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.onboarding import ONBOARDING_STEPS
from knight_flow.themes import SETTINGS_THEME_PALETTES
from knight_flow import ui_scale
from knight_flow.ui.onboarding import OnboardingWizard


class CaptureHost:
    def __init__(self, root: tk.Tk, theme: str, scale: float = 1.0, viewport: str | None = None) -> None:
        self.root = root
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.config.setdefault("ui", {})["settings_theme"] = theme
        self.config["ui"]["scale"] = scale
        self.viewport = viewport
        self.last_preview = ""
        self.onboarding_test_sink = None
        self._settings_initial_page: tuple[str, str] | None = None
        raw_sample = (
            "today's list number one gym at seven number two send the production report "
            "number three review the photo shoot selects and number four confirm friday's launch plan"
        )

        def format_both(_raw: str, done: Any) -> None:
            done(
                "Today's list: (1) gym at 7:00; (2) send the production report; "
                "(3) review the photo-shoot selects; and (4) confirm Friday's launch plan.",
                "Today's priorities are:\n1. Gym at 7:00.\n2. Send the production report.\n"
                "3. Review the photo-shoot selects.\n4. Confirm Friday's launch plan.",
            )

        self.callbacks = {
            "save_settings": lambda: None,
            "license_status": lambda: {
                "active": True,
                "email": "person@example.com",
                "permanent_core": False,
            },
            "license_activation_status": lambda: {"state": "idle", "detail": ""},
            "license_activate": lambda: None,
            "account": lambda: None,
            "prepare_local_model": lambda report=None: report("Ready for visual review") if callable(report) else None,
            "status_provider": lambda: {"session_active": False, "overlay_state": "idle"},
            "push_to_talk": lambda: None,
            "push_to_talk_stop": lambda: None,
            "cancel": lambda: None,
            "last_text": lambda: "",
            "last_raw_text": lambda: raw_sample,
            "format_both": format_both,
        }

    def _settings_theme_key(self, theme: str) -> str:
        return theme if theme in {f"{family} {mode}" for family, modes in SETTINGS_THEME_PALETTES.items() for mode in modes} else "Flow Dark"

    def _settings_palette(self, theme: str) -> dict[str, str]:
        family, mode = self._settings_theme_key(theme).rsplit(" ", 1)
        return dict(SETTINGS_THEME_PALETTES[family][mode])

    def _utility_window(
        self,
        _name: str,
        title: str,
        geometry: str,
        *,
        bg: str,
        resizable: bool,
        minimum_size: tuple[int, int],
        # X-535: the real host clamps to the monitor and lets a caller opt out
        # of remembering a size. The gallery renders at a fixed viewport on
        # purpose, so it honours neither -- but it must still ACCEPT them, or
        # it stops doubling the thing it doubles.
        remember_size: bool = True,
        anchor_to_pill: bool = False,
    ) -> tk.Toplevel:
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry(f"{self.viewport or geometry}+32+32")
        window.configure(bg=bg)
        window.resizable(resizable, resizable)
        window.minsize(*minimum_size)
        # Screen grabs capture pixels, not an off-screen backing store. Keep
        # this developer-only window above whatever happens to be open so the
        # gallery cannot silently photograph the desktop behind it.
        with __import__("contextlib").suppress(tk.TclError):
            window.attributes("-topmost", True)
        return window

    def _style_settings_widgets(self, window: tk.Toplevel, palette: dict[str, str]) -> None:
        style = ttk.Style(window)
        with __import__("contextlib").suppress(tk.TclError):
            style.theme_use("clam")
        style.configure(
            "Flow.TCombobox",
            fieldbackground=palette["field"],
            background=palette["button"],
            foreground=palette["text"],
            arrowcolor=palette["accent"],
            padding=(10, 6),
            bordercolor=palette["stroke"],
            lightcolor=palette["stroke"],
            darkcolor=palette["stroke"],
            arrowsize=16,
        )
        style.map(
            "Flow.TCombobox",
            fieldbackground=[("readonly", palette["field"]), ("disabled", palette["panel"])],
            foreground=[("readonly", palette["text"]), ("disabled", palette["muted"])],
            background=[("readonly", palette["button"])],
            selectbackground=[("readonly", palette["field"])],
            selectforeground=[("readonly", palette["text"])],
        )
        with __import__("contextlib").suppress(Exception):
            window.option_add("*TCombobox*Listbox.background", palette["field"])
            window.option_add("*TCombobox*Listbox.foreground", palette["text"])
            window.option_add("*TCombobox*Listbox.selectBackground", palette["select"])
            window.option_add("*TCombobox*Listbox.selectForeground", palette["text"])
        style.configure("Flow.TButton", background=palette["button"], foreground=palette["text"])
        style.configure(
            "Flow.Vertical.TScrollbar",
            background=palette["button"],
            troughcolor=palette["panel"],
            bordercolor=palette["stroke"],
            arrowcolor=palette["muted"],
            lightcolor=palette["button"],
            darkcolor=palette["button"],
        )

    def _minimize_control(self, window: tk.Toplevel, parent: tk.Widget, bg: str, *, width: int = 84) -> tk.Frame:
        return self._caption_control(window, parent, bg, "Minimize", width)

    def _close_control(self, window: tk.Toplevel, parent: tk.Widget, bg: str, *, command: Any = None) -> tk.Frame:
        return self._caption_control(window, parent, bg, "Close window", 44)

    def _caption_control(self, window: tk.Toplevel, parent: tk.Widget, bg: str, label: str, width: int) -> tk.Frame:
        # The gallery's stand-in for the app's shared caption controls (overlay
        # _minimize_control / _close_control): the same design-pixel lane, scaled
        # the same way, so the wizard's header measures here exactly as it does
        # under the real host. The glyph itself is not drawn; layout is what the
        # gallery and the high-DPI tests measure.
        from knight_flow import ui_scale

        palette = self._settings_palette(self.config["ui"]["settings_theme"])
        zone = tk.Frame(parent, bg=bg, width=ui_scale.px(width, self.config), height=ui_scale.px(32, self.config))
        zone.pack_propagate(False)
        button = tk.Button(
            zone,
            text=label,
            bg=bg,
            fg=palette.get("muted", "#9aa3b5"),
            relief="flat",
            bd=0,
            takefocus=1,
            highlightthickness=0,
        )
        button.pack(fill="both", expand=True)
        window._talkdat_minimize_control = zone  # type: ignore[attr-defined]
        return zone
    def _bind_utility_drag_handle(self, _window: tk.Toplevel, *_widgets: tk.Widget) -> None:
        return None

    def _compact_wave_frame(self, _width: int, _height: int, *, active: bool = False) -> None:
        return None

    def _context_menu_rows(self) -> list[tuple[str, str, str, Any]]:
        return [
            ("settings", "Settings", "Tools, account and every preference", None),
            ("paste_last", "Paste last transcript", "Insert here and keep on clipboard", None),
            ("history", "History", "Search and recover transcripts", None),
            ("more_features", "Features", "Ramble, captions, translate, scratchpad, Scribe, offline speech", None),
            ("check_updates", "Check for updates", "Install the latest release", None),
            ("stats", "Stats", "Words, streaks, time saved", None),
            ("restart_app", "Restart Talk DAT!", "Relaunch fresh; dictations are protected", None),
            ("quit_app", "Close Talk DAT!", "Exit completely until you open it again", None),
        ]

    def apply_runtime_config(self) -> None:
        return None

    def open_settings(self) -> None:
        return None

    def open_mic_doctor(self) -> None:
        return None

    def set_state(self, *_args: str) -> None:
        return None


def capture(
    output: Path,
    theme: str,
    scale: float = 1.0,
    viewport: str | None = None,
    steps: set[str] | None = None,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    ui_scale.enable_dpi_awareness()
    root = tk.Tk()
    root.tk.call("tk", "scaling", 96.0 * scale / 72.0)
    root.withdraw()
    capture_geometry = viewport or "1040x720"
    for index, step in enumerate(ONBOARDING_STEPS):
        if steps and step.id not in steps:
            continue
        # Each page gets a fresh wizard. That keeps timers, requested widget
        # sizes, focus, and native window paint state from the prior page out
        # of the next page's evidence.
        host = CaptureHost(root, theme, scale, viewport)
        wizard = OnboardingWizard(host)
        if wizard.window is None:
            raise RuntimeError("onboarding window did not open")
        wizard.render_step(index)
        # Content-heavy pages can update their requested size while Tk is
        # laying them out. A production window may be moved or resized by the
        # user, but a visual-regression frame must stay at the named viewport
        # or ImageGrab can clip a screen edge and report a false layout bug.
        wizard.window.geometry(f"{capture_geometry}+0+0")
        wizard.window.deiconify()
        wizard.window.lift()
        root.update_idletasks()
        root.update()
        wizard.window.geometry(f"{capture_geometry}+0+0")
        root.update_idletasks()
        root.update()
        time.sleep(0.08)
        root.update()
        window = wizard.window
        bbox = (
            window.winfo_rootx(),
            window.winfo_rooty(),
            window.winfo_rootx() + window.winfo_width(),
            window.winfo_rooty() + window.winfo_height(),
        )
        try:
            frame = ImageGrab.grab(window=window.winfo_id())
        except (OSError, TypeError):
            frame = ImageGrab.grab(bbox=bbox, all_screens=True)
        frame.save(output / f"{index + 1:02d}-{step.id}.png")
        if step.id == "test":
            wizard._offer_finish_choice()
            root.update_idletasks()
            root.update()
            time.sleep(0.08)
            root.update()
            try:
                frame = ImageGrab.grab(window=window.winfo_id())
            except (OSError, TypeError):
                frame = ImageGrab.grab(bbox=bbox, all_screens=True)
            frame.save(output / "10b-test-finishes.png")
        wizard.window.destroy()
        root.update()
    root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--theme", default="Flow Dark")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--viewport")
    parser.add_argument("--step", action="append", choices=[step.id for step in ONBOARDING_STEPS])
    arguments = parser.parse_args()
    capture(
        arguments.output.resolve(),
        arguments.theme,
        max(1.0, min(3.0, arguments.scale)),
        arguments.viewport,
        set(arguments.step or ()),
    )


if __name__ == "__main__":
    main()
