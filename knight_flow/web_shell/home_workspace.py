"""The screen that greets a launch, assembled away from the native UI queue.

His report, 2026-09-21: the app opened on "random settings that I had open",
because boot called open_settings() with no destination and the shell fell
back to `self._last_page`. A settings page is not a greeting, and the page it
lands on is whatever the last session happened to leave behind.

Home is split in two on purpose. The greeting half is pure configuration --
version, shortcut, speech engine, what changed in this build -- and costs
nothing, so it renders on the first frame. The activity half reads the
history store, which walks up to 20,000 rows, so it loads on a worker thread
and arrives when it arrives. Home must never be the reason a launch feels
slow; that was the other half of the same report.
"""
from __future__ import annotations

import copy
import logging
import sys
import threading

log = logging.getLogger(__name__)

# "cmd" is what the config calls the platform's own modifier. On this keyboard
# it is the Windows key, and printing "Cmd" to a Windows user is a shortcut
# they will look for and not find.
_KEY_LABELS = {
    "ctrl": "Ctrl",
    "alt": "Option" if sys.platform == "darwin" else "Alt",
    "shift": "Shift",
    "cmd": "⌘" if sys.platform == "darwin" else "Win",
    "esc": "Esc",
    "space": "Space",
}


def format_shortcut(shortcuts) -> str:
    """The first binding of a hotkey, written the way a key cap reads."""
    if not isinstance(shortcuts, list):
        return ""
    for shortcut in shortcuts:
        parts = shortcut if isinstance(shortcut, list) else [shortcut]
        keys = [_KEY_LABELS.get(str(part).strip().lower(), str(part).strip().title())
                for part in parts if str(part).strip()]
        if keys:
            return "+".join(keys)
    return ""


def home_greeting(config):
    """Everything Home can say without touching the history store."""
    from knight_flow.stt_registry import PROVIDER_BY_ID, provider_is_ready, selected_model_id, selected_provider_id
    from knight_flow.updater import bundled_changelog_section
    from knight_flow.version import APP_VERSION

    hotkeys = config.get("hotkeys", {}) if isinstance(config.get("hotkeys"), dict) else {}
    provider_id = selected_provider_id(config)
    provider = PROVIDER_BY_ID.get(provider_id)
    model_id = selected_model_id(config, provider_id)
    from knight_flow.local_stt import model_display_name

    model_label = model_id or "Automatic"
    if provider is not None:
        model_label = next((model.label for model in provider.models if model.id == model_id), model_label)
    # A status line, not a choice: the name alone reads "Speech runs on this
    # computer (Parakeet TDT 0.6B v3)." without a second pair of brackets.
    model_label = model_display_name(model_label)
    try:
        ready = bool(provider_is_ready(config, provider_id))
    except Exception:
        # A provider that cannot answer is not a reason for Home to fail; the
        # Speech page is where a broken provider gets diagnosed.
        ready = False

    # Parsed as Markdown blocks, never split by line (owner's audit,
    # 2026-09-23): CHANGELOG.md is hard-wrapped at about 78 characters, and a
    # line-at-a-time read turned each wrapped line into its own bullet, cutting
    # sentences in half. The section's opening paragraph is its summary; only
    # "- " items are bullets, each one whole.
    from knight_flow.release_notes import changelog_digest

    digest = changelog_digest(bundled_changelog_section(APP_VERSION), limit=5)
    # His ask, 2026-09-21: greet him by name. Trimmed and length-capped because
    # it is free text that lands in a heading; the renderer sets it as a text
    # node, so this is about layout, not escaping. Blank means no name, which
    # is the default and stays correct for anyone who never fills it in.
    name = " ".join(str(config.get("ui", {}).get("display_name") or "").split())[:40]
    return {
        "name": name,
        "version": APP_VERSION,
        "summary": digest["summary"],
        "notes": digest["notes"],
        "more_notes": digest["more"],
        "shortcuts": {
            "push_to_talk": format_shortcut(hotkeys.get("push_to_talk")),
            "hands_free": format_shortcut(hotkeys.get("hands_free")),
        },
        "speech": {
            "label": provider.label if provider is not None else "Current provider",
            "model": model_label,
            "local": provider_id == "local",
            "ready": ready,
        },
    }


def load_activity(config):
    """The history-backed half. Walks the store, so it never runs on the UI queue.

    history_stats already carries every figure Home shows, so this deliberately
    does NOT call usage_summary as the Stats page does -- Home wants the four
    numbers, not the provider-cost model behind them.
    """
    from knight_flow.history import history_stats

    stats = history_stats(config)
    return {
        "words": int(stats.get("dictated_words") or 0),
        "entries": int(stats.get("entries") or 0),
        "streak_days": int(stats.get("streak_days") or 0),
        "minutes_saved": int(stats.get("minutes_saved") or 0),
        "history_enabled": config.get("privacy", {}).get("save_history", True) is not False,
    }


def update_answer(outcome) -> dict:
    """An update-check outcome, as Home shows it: plain words, one of five phases.

    Built from what check_updates reports and nothing else, so a malformed or
    unexpected report degrades to "failed" with a sentence instead of a blank.
    """
    from knight_flow.version import APP_VERSION

    outcome = outcome if isinstance(outcome, dict) else {}
    phase = str(outcome.get("phase") or "")
    version = " ".join(str(outcome.get("version") or "").split())[:40]
    if phase == "current":
        return {"phase": "current", "message": f"Talk DAT! is up to date ({version or APP_VERSION})."}
    if phase == "available" and version:
        if outcome.get("required"):
            message = f"Version {version} is a required update. Install it when you are not dictating."
        else:
            message = f"Version {version} is ready to install."
        return {"phase": "available", "version": version, "required": bool(outcome.get("required")),
                "message": message}
    if phase == "store":
        return {"phase": "store",
                "message": "Updates for this copy come from the Microsoft Store. The Store page is opening."}
    if phase == "busy":
        return {"phase": "busy", "message": "Already checking for updates. The answer will appear here."}
    detail = " ".join(str(outcome.get("message") or "").split())[:240]
    return {"phase": "failed",
            "message": "Couldn't check for updates. " + (detail or "Try again in a minute.")}


class HomeWorkspace:
    """Greets immediately; fills in activity when the worker finishes.

    It also answers Check for updates in place (owner's audit, 2026-09-23: the
    button only navigated to Settings > General, where nothing checked either).
    ``updates`` is the app's own update path, reached through two calls:
    ``check(report)`` runs check_updates with a reporter, and ``install()`` is
    install_or_check_update, which opens the verified Update window for the
    release the check found.
    """

    OPERATIONS = frozenset({"status", "refresh", "check_updates", "install_update"})

    def __init__(self, config, dispatch, loader=load_activity, greeter=home_greeting, updates=None):
        self.config, self.dispatch, self.loader, self.greeter = config, dispatch, loader, greeter
        self.updates = updates
        self.activity = None
        self.phase = "idle"
        self.message = ""
        self.closed = False
        self.revision = 0
        self.update = {"phase": "idle"}
        self._update_ticket = 0

    def handle(self, payload):
        if type(payload) is not dict or set(payload) != {"operation"} or payload["operation"] not in self.OPERATIONS:
            raise ValueError("That Home action is unavailable.")
        if self.closed:
            raise ValueError("Home is closed. Open it again to refresh.")
        operation = payload["operation"]
        if operation == "check_updates":
            self._check_updates()
        elif operation == "install_update":
            self._install_update()
        if operation == "refresh" and self.phase != "loading":
            self.revision += 1
            revision = self.revision
            snapshot = copy.deepcopy(self.config)
            self.phase, self.message = "loading", ""

            def work():
                try:
                    data, error = self.loader(snapshot), ""
                except Exception:
                    log.exception("home activity could not load")
                    data, error = None, "Your activity could not load."

                def finish():
                    if self.closed or revision != self.revision:
                        return
                    if not error:
                        self.activity = data
                    self.phase, self.message = ("error", error) if error else ("ready", "")

                self.dispatch(finish)

            try:
                threading.Thread(target=work, name="TalkDatHome", daemon=True).start()
            except Exception:
                self.phase, self.message = "error", "Your activity could not load."

        # The greeting is rebuilt every poll so a provider or shortcut changed
        # in Settings is reflected the next time Home is looked at.
        try:
            greeting = self.greeter(self.config)
        except Exception:
            log.exception("home greeting could not build")
            greeting = {"name": "", "version": "", "summary": [], "notes": [], "more_notes": 0,
                        "shortcuts": {}, "speech": {}}
        return {"phase": self.phase, "message": self.message, "revision": self.revision,
                "greeting": greeting, "activity": copy.deepcopy(self.activity),
                "update": copy.deepcopy(self.update)}

    def _check_updates(self):
        if self.update.get("phase") == "checking":
            return
        if self.updates is None:
            self.update = update_answer({"phase": "failed", "message": "Update checks are unavailable in this window."})
            return
        self._update_ticket += 1
        ticket = self._update_ticket
        self.update = {"phase": "checking", "message": "Checking for updates…"}

        def report(outcome):
            # check_updates answers from its worker thread; Home's state is
            # only ever touched on the thread that serves the page.
            def finish():
                if self.closed or ticket != self._update_ticket:
                    return
                self.update = update_answer(outcome)

            self.dispatch(finish)

        try:
            self.updates.check(report)
        except Exception:
            log.exception("home update check could not start")
            self.update = update_answer({"phase": "failed", "message": "The check could not start. Try again in a minute."})

    def _install_update(self):
        if self.updates is None or self.update.get("phase") != "available":
            raise ValueError("Check for updates first.")
        self.updates.install()
        self.update = {**self.update, "message": f"The update window is open. Version {self.update.get('version', '')} installs from there."}

    def close(self):
        self.closed = True
        self.revision += 1
        self._update_ticket += 1


class HomeUpdates:
    """Home's two doors into the app's existing update path."""

    def __init__(self, app):
        self.app = app

    def check(self, report):
        self.app.check_updates(silent=False, report=report)

    def install(self):
        self.app.install_or_check_update()
