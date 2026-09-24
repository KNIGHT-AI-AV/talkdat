"""X-351, the macOS half: Talk DAT! in every app's right-click menu, the
NATIVE way -- the Services menu.

macOS already has the extension point Windows lacks: an app that declares
NSServices gets its items into the right-click menu of EVERY app's text
selection, system-wide, and when the service returns a string the system
replaces the selection in place -- no paste dance, no caret proofs.

Two services ship:
  "Talk DAT!: Rewrite"            -- the clean fixed instruction
  "Talk DAT!: Rewrite with prompt" -- asks one line ("Make this shorter")

The provider reuses the exact engine Fix That uses (llm.llm_rewrite), so the
two doors cannot drift. X-516 moved it there from managed_cloud.rewrite_text:
this was the last path on macOS that sent a selection to our servers, and it
did so from the right-click menu of every app on the machine.

Registration is best-effort and mac-only: PyObjC ships with macOS's
system Python and rides the app bundle; if it is absent the app simply
logs and runs without Services. The bundle's Info.plist must carry the
fragment in docs/mac/NSServices-fragment.plist -- that wiring happens in
the mac build (0.4.123); this module is inert until it does.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

log = logging.getLogger("knight_flow.mac_services")

REWRITE_INSTRUCTION = "Rewrite this cleanly. Keep the meaning and the language."


def _fallback_one_line(overlay) -> str:
    """A minimal modal line for ports whose overlay lacks ask_one_line."""
    import threading
    import tkinter as tk

    result = {"value": ""}
    done = threading.Event()

    def build() -> None:
        try:
            window = tk.Toplevel(overlay.root)
            window.title("Rewrite how?")
            window.attributes("-topmost", True)
            tk.Label(window, text='For example: "Make this shorter."').pack(padx=16, pady=(12, 4))
            entry = tk.Entry(window, width=42)
            entry.pack(padx=16, pady=8, ipady=4)

            def finish(_event=None) -> None:
                result["value"] = entry.get().strip()
                window.destroy()
                done.set()

            def cancel(_event=None) -> None:
                window.destroy()
                done.set()

            entry.bind("<Return>", finish)
            entry.bind("<Escape>", cancel)
            window.protocol("WM_DELETE_WINDOW", cancel)
            window.lift()
            entry.focus_set()
        except Exception:
            done.set()

    overlay.root.after(0, build)
    done.wait(timeout=45)
    return result["value"]


def register(config: dict[str, Any], overlay: Any) -> bool:
    """Install the Services provider. Returns whether it is live."""
    if sys.platform != "darwin":
        return False
    try:
        import objc  # noqa: F401
        from AppKit import NSPasteboard, NSPasteboardTypeString, NSRegisterServicesProvider
        from Foundation import NSObject
    except Exception:
        log.info("PyObjC unavailable; Services menu integration is off")
        return False

    from .llm import llm_rewrite
    from .style_profile import render_instruction

    def run_rewrite(text: str, instruction: str) -> str:
        voice = render_instruction(config.get("style_profile", {}))
        return str(llm_rewrite(text, instruction, config, system=voice) or "").strip()

    class TalkDatServiceProvider(NSObject):
        def rewriteSelection_userData_error_(self, pboard, _user_data, _error):  # noqa: N802
            self._handle(pboard, REWRITE_INSTRUCTION)

        def promptedRewriteSelection_userData_error_(self, pboard, _user_data, _error):  # noqa: N802
            instruction = ""
            try:
                ask = getattr(overlay, "ask_one_line", None)
                if callable(ask):
                    instruction = ask("Rewrite how?", 'For example: "Make this shorter."')
                else:
                    instruction = _fallback_one_line(overlay)
            except Exception:
                log.debug("prompt window failed", exc_info=True)
            if instruction:
                self._handle(pboard, instruction)

        def _handle(self, pboard, instruction: str) -> None:
            try:
                text = str(pboard.stringForType_(NSPasteboardTypeString) or "").strip()
                if not text:
                    return
                result = run_rewrite(text, instruction)
                if not result:
                    return
                # Returning a string on the pasteboard is what makes macOS
                # REPLACE the selection in the calling app.
                pboard.clearContents()
                pboard.setString_forType_(result, NSPasteboardTypeString)
            except Exception:
                log.warning("service rewrite failed", exc_info=True)

    provider = TalkDatServiceProvider.alloc().init()
    NSRegisterServicesProvider(provider, "TalkDatServices")
    # Keep the provider alive for the process lifetime.
    register._provider = provider  # type: ignore[attr-defined]
    log.info("Services menu provider registered")
    return True
