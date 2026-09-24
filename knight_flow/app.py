from __future__ import annotations

import contextlib
import copy
import gc
import json
import queue
import logging
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus

from collections import deque

from . import platform_copy
from . import main_thread
from .chimes import play_chime, prewarm_sounds
from .audio_spool import (
    AudioSafetyCapture,
    list_safety_sessions,
    read_safety_audio,
    recover_interrupted_sessions,
    save_safety_recording,
    start_safety_capture,
    update_safety_session,
)
from .audio_input import is_digitally_silent, likely_has_input_signal, warm_audio_input_backend
from .capture_timing import pcm_duration_ms
from .mic_registry import microphone_registry
from .config import (
    DEFAULT_CONFIG,
    app_dir,
    config_path,
    full_history_path,
    history_path,
    live_draft_path,
    preserve_live_draft_for_recovery,
    load_config,
    save_config,
    engine_recording_ceiling,
)
from .feedback import build_feedback_payload, submit_feedback
from .format_journal import journal_tail
from .history import create_history_store, history_backend, pin_text
from .hotkeys import apply_trigger_style, HotkeyController
from .http_api import ControlServer
from .meeting import MeetingRecorder
from .onboarding import (
    chord_label,
    onboarding_blocks_update_reminders,
    onboarding_is_complete,
    permission_pages,
    permissions_outstanding,
)
from .profiles import active_profile, apply_profile
from .wake import WakeWordListener
from .logger import configure_logging
from .llm import keep_local_finisher_resident, prepare_local_formatter
from .licensing import LicenseError, LicenseManager
from . import local_fallback
from . import mac_support
from .local_stt import download_model as download_local_model
from .local_stt import download_progress_mb as local_download_progress_mb
from .local_stt import model_to_prefetch, model_to_warm, warm_engine
from .overlay import Overlay
from .ui_scale import enable_dpi_awareness
from .paste import (
    copy_selected_text,
    copy_text,
    external_delivery_claim,
    foreground_edit_target_signature,
    foreground_focus_window_id,
    foreground_input_generation,
    foreground_window_id,
    paste_text_with_receipt,
    restore_clipboard_if_unchanged,
)
from .single_instance import already_running, show_already_running_message
from .stt_registry import PROVIDER_BY_ID, provider_label, selected_model_id, selected_provider_id
from .stt_sessions import create_stt_session, selected_stt_api_key, transcribe_pcm
from .text_pipeline import (
    command_to_transform,
    process_dictation,
    transform_text,
    unified_diff,
)
from .translation import (
    TranslationError,
    auto_translation_enabled,
    resolve_source_language,
    resolve_target_language,
    install_ollama_runtime,
    install_translation_model,
    translate_text,
    translation_model_status,
)
from .mac_menu_bar import MacMenuBar
from .tray import TrayController
from .formatting import smart_format, take_local_finish_notice
from .trigger_intent import PRESS_BOUNCE, PRESS_CANCEL_AND_RESTART, press_intent
from .updater import UpdateError, bundled_changelog_section, check_for_update, download_installer, launch_installer, record_version_seen
from .update_policy import (
    IDLE_SETTLE_SECONDS,
    TRIGGER_IDLE,
    TRIGGER_QUIT,
    TRIGGER_START,
    should_remind,
)
from .version import APP_RELEASES_URL, APP_VERSION
from .windows_audio import OutputMuteGuard


log = logging.getLogger(__name__)


# ``handle_dictation`` is also exercised directly by recovery tools and tests,
# where the current overlay sink is the intended destination. A completed STT
# session passes an explicit snapshot instead. This sentinel distinguishes
# "look it up now" from "there was no guided-test sink when this flight ended."
_DYNAMIC_GUIDED_SINK = object()

# These receipts prove that no edit was committed. If an exact edit-target
# signature changes in the tiny gap between route selection and the delivery
# helper's own predicate, it is therefore safe to make one owner-only clipboard
# copy. Commit-unknown and partial-typing receipts are intentionally excluded:
# a second delivery transaction could make an ambiguous document worse.
_PRECOMMIT_REFUSAL_METHODS = frozenset({"cancelled", "none", "protected_rich_clipboard"})


def _copy_after_precommit_refusal(
    text: str,
    receipt: Any,
    *,
    can_deliver: Callable[[], bool],
) -> Any:
    if bool(getattr(receipt, "success", False)):
        return receipt
    if str(getattr(receipt, "method", "")) not in _PRECOMMIT_REFUSAL_METHODS:
        return receipt
    return paste_text_with_receipt(
        text,
        restore_clipboard=False,
        paste_mode="copy_only",
        can_deliver=can_deliver,
    )


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            file.write(text)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            with contextlib.suppress(OSError):
                temporary_path.unlink()


# X-203: the plaintext transcript log grew forever and nothing ever trimmed it.
#
# History has a retention limit and honours it -- for history.jsonl. This file
# is the SAME dictations in plain text, written beside it, and no code path in
# the product ever removed a line from it. Somebody who set "keep 50" got 50 in
# one file and every dictation they had ever spoken in the other. On the
# founder's own machine it reached 1.4 MB covering ten weeks.
#
# Two bounds, because they fail differently. The retention limit is the user's
# stated wish and must be obeyed. The size ceiling is the backstop for the
# default -- history_limit ships as 0, meaning unlimited, and an unbounded
# plaintext record of everything a person has ever dictated is the single worst
# artifact this app can leave behind on a machine that changes hands.
FULL_HISTORY_MAX_BYTES = 4 * 1024 * 1024
FULL_HISTORY_BANNER = "=" * 72

# X-369: how long a cloud failure stays as evidence that cloud is unwell.
#
# The streak counts CONSECUTIVE failures and a clean cloud dictation is what
# clears it (see the reset beside `retry_needed`). This window exists only to
# discard evidence old enough to be meaningless -- it must never be short
# enough to act as a second reset during ordinary use. It was 180 seconds,
# which is shorter than the gap between two normal dictations, so a sustained
# outage reset the streak on every attempt: "three consecutive misses" was
# unreachable, the local rescue never armed, and an activated customer was
# told "Cloud dropped this one" forever while a working on-device model sat
# idle. That is a total product outage produced entirely by the timer.
CLOUD_FAILURE_MEMORY_SECONDS = 24 * 60 * 60


def split_full_history(text: str) -> list[str]:
    """The log, as whole entries. Each opens with a banner/header/banner block.

    Splitting on the banner alone yields two fragments per entry, so they are
    paired back up here rather than at each call site -- getting that wrong
    silently halves the retention limit, which is the kind of error that looks
    like the setting working.
    """
    separator = "\n" + FULL_HISTORY_BANNER + "\n"
    parts = text.split(separator)
    if len(parts) < 3:
        return []
    blocks = [separator + part for part in parts[1:]]
    return ["".join(blocks[index:index + 2]) for index in range(0, len(blocks), 2)]


def trim_full_history(path: Path, config: dict[str, Any]) -> None:
    """Bound the plaintext transcript log by the user's limit and by size."""
    try:
        size = path.stat().st_size
        limit = config_int(config.get("privacy", {}).get("history_limit", 0), 0)
        if limit <= 0 and size <= FULL_HISTORY_MAX_BYTES:
            return
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        # Never interrupt a delivered dictation over housekeeping -- but say so,
        # because a trim that keeps failing means the log keeps growing, and
        # that is exactly the unbounded state this function exists to end.
        log.warning("could not read the transcript log to trim it", exc_info=True)
        return
    records = split_full_history(text)
    if not records:
        return
    if limit > 0:
        records = records[-limit:]
    while len(records) > 1 and sum(len(r.encode("utf-8")) for r in records) > FULL_HISTORY_MAX_BYTES:
        records.pop(0)
    # Deliberately NOT stripped. Every entry the writer appends begins with a
    # newline before its banner, so a trimmed file that lost its leading one
    # would split one block out of phase on the NEXT trim -- and a mis-phased
    # split pairs each entry's body with the following entry's header, which
    # silently keeps the wrong records while still keeping the right NUMBER of
    # them. That reads as working.
    kept = "".join(records)
    if kept == text:
        return
    try:
        atomic_write_text(path, kept)
    except OSError:
        log.debug("could not trim the full transcript log", exc_info=True)


# X-415: statuses the engine sends while it works; none of them means the
# microphone closed. Mapped to the processing state only once the stop
# has been requested (the release), never during the hold.
ENGINE_WORK_STATUSES = frozenset({"transcribing", "loading_model", "downloading_model"})
LIVE_SESSION_CONTROLS = frozenset({"hold", "command_hold", "hands_free"})


class TalkDatApp:
    def __init__(self, project_root: Path | None = None) -> None:
        # X-294, THE CRASH READ OUT OF THE MINIDUMP ITSELF. Python's cyclic
        # collector runs on WHICHEVER thread happens to allocate the 700th
        # object. When that is pystray's menu thread (or a pynput thread),
        # the collector frees dead tkinter objects there, Tcl notices its
        # interpreter being touched from the wrong thread, panics, and
        # calls C abort() -- a c0000409 fail-fast that faulthandler cannot
        # even see (dump stack: libffi ctypes wndproc -> _tkinter ->
        # tcl86t Tcl_Panic -> ucrtbase abort). The overlay animates
        # constantly, so there is ALWAYS dead Tk garbage waiting, which is
        # why every single tray click killed the app. Automatic collection
        # is disabled here, before any thread exists, and the Tk thread
        # collects on a timer instead (_collect_garbage_on_tk_thread).
        # Plain refcount frees still happen everywhere immediately; only
        # CYCLE collection is rescheduled.
        gc.disable()
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.config = load_config(self.project_root)
        self._plugins_were_enabled = self.config.get("plugins", {}).get("enabled") is True
        from .caret_context import read_caret_context

        self._caret_context_reader = read_caret_context
        from .progressive_formatting import ProgressiveFormatter
        self._progressive_formatter = ProgressiveFormatter()
        self.lock = threading.RLock()
        self.session: Any | None = None
        self.session_token: object | None = None
        self._ramble_workspace_sink = None
        # A cancelled session is detached immediately so Panic Stop never waits
        # on an audio driver from Tk. Detachment is not proof that the driver has
        # released the microphone, however, so keep those exact sessions visible
        # to status/diagnostics until their worker thread has truly exited.
        self._dictation_closing_sessions: set[int] = set()
        # A guided result can be queued onto Tk after STT finishes. Keep its
        # flight identity separate from session_token, which is cleared in the
        # completion finally block. Cancel or a new session invalidates it.
        self._guided_delivery_token: object | None = None
        # Formatting, Fix That, translation, and protected-audio recovery can
        # finish after their initiating session has left ``session_token``.
        # One owner token linearizes those deferred results. A new capture or
        # newer deferred action invalidates the old one before it can touch the
        # keyboard, clipboard, shared last-result model, or Pill status.
        self._deferred_delivery_owner: object | None = None
        self.session_chime_token: object | None = None
        self.session_mode = "idle"
        self.session_control = "idle"
        self.session_error_message = ""
        # Set per session. Non-empty only when this dictation was routed to a
        # local model because there was no network to reach the cloud one.
        self.offline_fallback_notice = ""
        # When the cloud keeps failing, rescuing one dictation at a time stops
        # being kindness and starts being a slot machine: every attempt pays
        # the failed round trip before the local model saves it. Three
        # fallbacks inside ten minutes promote the fallback to the session's
        # route, with a toast saying so. Session-only -- the config on disk
        # keeps the person's actual choice, and a restart returns to it.
        self._cloud_fallback_times: deque[float] = deque(maxlen=8)
        # What the model's formatting actually costs on this machine, so the
        # decision to paste early can be made on a measurement instead of on an
        # assumption baked in when the pipeline was slower. Short, because the
        # answer changes the moment somebody switches speech provider and a
        # long window would keep asserting yesterday's pipeline.
        self._model_format_ms: deque[float] = deque(maxlen=5)
        self._switched_to_local_for_session = False
        self._provider_before_local_switch = ""
        self.safety_capture: AudioSafetyCapture | None = None
        self.safety_capture_token: object | None = None
        self.safety_capture_failure_token: object | None = None
        self._session_audio_already_saved = False
        self.last_transcript = ""
        self.last_original = ""
        self.last_diff = ""
        self.output_mute_guard = OutputMuteGuard()
        self.update_lock = threading.Lock()
        self.update_in_progress = False
        self.license_activation_lock = threading.Lock()
        self.license_activation_in_progress = False
        self._license_activation_cancel = threading.Event()
        self.license_activation_snapshot: dict[str, Any] = {
            "state": "idle",
            "detail": "Account activation has not started.",
        }
        self.license_manager = LicenseManager(self.config)
        self.local_model_prefetch_lock = threading.Lock()
        self.local_model_prefetch_in_progress = False
        self.meeting: MeetingRecorder | None = None
        self.wake_listener: WakeWordListener | None = None
        self.control_server: ControlServer | None = None
        self.paused = False
        self.pending_update: Any | None = None
        # X-106: what a trigger press means depends on where the pipeline is.
        # Stamped by stop_session, cleared wherever a dictation truly ends.
        self._trigger_released_at: float | None = None
        self._released_processing = False
        self._last_hands_free_toggle_at = 0.0
        self._previous_version = str(self.config.get("updates", {}).get("current_version", ""))
        self._recovered_draft: Path | None = None
        recovered_sessions = recover_interrupted_sessions(
            limit=config_int(self.config.get("dictation", {}).get("safety_recording_limit"), 5)
        )
        if recovered_sessions:
            log.warning("recovered %s interrupted protected voice session(s)", recovered_sessions)
            # X-544: the audio is only half of what the crash interrupted. The
            # live draft holds the WORDS, and the first interim update of the
            # next dictation overwrites it -- 63 seconds, the day this was
            # found. Copy it aside before the app is usable again, so the next
            # sentence he speaks cannot erase the one the crash ate.
            self._recovered_draft = preserve_live_draft_for_recovery(
                save_history=bool(self.config.get("privacy", {}).get("save_history", True))
            )
            if self._recovered_draft is not None:
                log.warning("the interrupted transcript was kept at %s", self._recovered_draft)
        record_version_seen(self.config)
        # Reclaim the installers past updates left behind -- they were 6.5 GB
        # on the founder's machine before anything deleted them. Best-effort:
        # a locked file just stays for the next launch to collect.
        try:
            from .updater import prune_stale_installers

            prune_stale_installers()
        except Exception as error:
            log.warning("stale installer cleanup skipped: %s", error)
        save_config(self.config)
        prepare_local_formatter(self.config)

        callbacks = {
            "hands_free": self.toggle_hands_free,
            "cancel": self.cancel,
            "panic": self.panic_stop,
            "polish": lambda: self.run_transform("polish"),
            "prompt_engineer": lambda: self.run_transform("prompt_engineer"),
            "turn_to_list": lambda: self.run_transform("turn_to_list"),
            "view_diff": self.copy_last_diff,
            "scratchpad": self.open_scratchpad,
            "paste_last": self.paste_last,
            "copy_last": self.copy_last,
            "pin_last": self.pin_last,
            "meeting_mode": self.toggle_meeting_mode,
            "translate_last": self.translate_last,
            "translate_toggle": self.toggle_auto_translation,
            "translation": self.open_translation,
            "translation_translate": self.translation_translate,
            "translation_model_status": self.translation_model_status,
            "translation_install_model": self.translation_install_model,
            "translation_install_runtime": self.translation_install_runtime,
            "translation_paste": self.translation_paste,
            "feedback": self.send_feedback,
            "feature_idea": lambda: self.overlay.root.after(0, lambda: self.overlay.open_feedback_form("feature")),
            "push_menu_order": self.push_menu_order,
            "route_state": self.route_state,
            "quick_fix": self.quick_fix_selection,
            "update_badge": self.update_badge,
            "set_route": self.set_route_mode,
            "record_pronunciation": self.record_pronunciation,
            "last_text": lambda: self.last_transcript or self.read_last_history_text(),
            "last_raw_text": lambda: str(getattr(self, "last_raw_transcript", "") or ""),
            "format_both": self.format_both_finishes,
            "pause": self.toggle_pause,
            "restart": self.restart,
            "stats": self.open_stats,
            "local_models": self.open_local_models,
            "prepare_local_model": self.prefetch_selected_local_model,
            "install_update": self.install_or_check_update,
            "push_menu_order": self.push_menu_order,
            "push_to_talk": self.start_push_to_talk,
            "push_to_talk_stop": self.stop_session,
            "command_mode": self.start_command_mode,
            "fix_that": self.start_fix_that,
            # X-134 (catalog audit): fix_that is a HOLD action, so releasing
            # the chord emits fix_that_stop -- which was never wired, leaving
            # the mic open with no release half. Same stop as push-to-talk:
            # end the capture; the fixthat session mode routes the transcript
            # into apply_fix_that.
            "fix_that_stop": self.stop_session,
            "ramble": self.start_ramble,
            "captions_toggle": self.toggle_captions,
            "captions_stream": self.start_captions_stream,
            "captions_stop": self.stop_captions_stream,
            "scribe_toggle": self.toggle_scribe,
            "mic_doctor_run": self.run_mic_doctor,
            "mic_doctor_open": lambda: bool(getattr(self, "web_shell", None) and self.web_shell.open_settings("mic-doctor")),
            "speech_check_open": lambda: bool(getattr(self, "web_shell", None) and self.web_shell.open_settings("speech-check")),
            "mic_input_select": self.set_microphone_input,
            "taste_race_run": self.run_taste_race,
            "read_back": self.read_back_last,
            "command_mode_stop": self.stop_session,
            "save_settings": self.save_settings,
            "onboarding_save": self.save_onboarding_settings,
            "quit": self.quit,
            "show": self.show_overlay,
            "hide": self.hide_overlay,
            "settings": self.open_settings,
            "status": self.open_status,
            "history": self.open_history,
            "recent_audio_sessions": self.recent_audio_sessions,
            "recover_audio_session": self.recover_audio_session,
            "check_updates": self.check_updates,
            "account": self.open_account,
            "license_status": self.license_status,
            "license_activate": self.activate_license,
            "license_activation_cancel": self._license_activation_cancel.set,
            "license_email_start": self.begin_email_sign_in,
            "license_email_verify": self.finish_email_sign_in,
            "license_sign_out": self.sign_out_license,
            # The reset dialog needs the bare boolean -- did the credential
            # store actually forget the licence -- without the toast that
            # sign_out_license shows, because reset reports its own summary.
            "license_forget": lambda: self.license_manager.forget_license(),
            "reset_execute": self.execute_reset,
            "reset_finish": self.finish_reset,
            "_actions_blocked": lambda: getattr(self, "_reset_in_progress", False) is True,
            "license_activation_status": self.license_activation_status,
            "status_provider": self.status_snapshot,
        }
        # Before the first window exists, or it does nothing: DPI awareness is
        # process-wide and locked in at first use. Without it, every window on
        # a scaled display is rendered at 96 DPI and bitmap-stretched by
        # Windows -- reported from a real install as "low-resolution ugliness".
        enable_dpi_awareness()
        from .brand_font import apply_app_family
        apply_app_family(self.config)
        self.overlay = Overlay(self.config, callbacks)
        # X-284 + mac-port union, revised by X-294. On macOS the menu bar
        # item must be built on the Tk thread (pystray's NSStatusItem cannot
        # live on a worker), so MacMenuBar is thread-safe by construction.
        # On Windows the menu runs on pystray's win32 worker -- and the
        # X-294 minidump proved root.after is ITSELF a Tcl call, so the
        # dispatcher is now a plain queue.put that the Tk thread drains on
        # its own clock (_drain_cross_thread_calls, armed in run()).
        self._cross_thread_calls: queue.Queue[Callable[[], None]] = queue.Queue()
        self.tray = (
            MacMenuBar(callbacks)
            if mac_support.IS_MAC
            else TrayController(callbacks, dispatch=self._cross_thread_calls.put)
        )
        self.hotkeys = HotkeyController(
            apply_trigger_style(
                self.config.get("hotkeys", {}),
                str(self.config.get("dictation", {}).get("trigger_style", "both")),
            ),
            callbacks,
            hold_debounce_ms=int(self.config.get("dictation", {}).get("hold_debounce_ms", 140)),
        )
        self.web_shell = None
        try:
            from .web_shell.shell_app import AppShell, renderer_available
            if renderer_available():
                self.web_shell = AppShell(self)
                callbacks["web_settings"] = self.web_shell.open_settings
                callbacks["web_menu"] = self.web_shell.open_menu
                callbacks["web_menu_close"] = self.web_shell.menu_controller.hide
        except Exception as error:
            log.warning("Web shell unavailable; using the existing windows (%s)", type(error).__name__)

    def run(self) -> None:
        log.info("Talk DAT! starting")
        provider_id = selected_provider_id(self.config)
        log.info(
            "Config loaded: stt_provider=%s model=%s cleanup=%s",
            provider_id,
            selected_model_id(self.config, provider_id),
            self.config.get("cleanup", {}).get("level"),
        )
        # MacMenuBar needs the Tk root to create its status item on the right
        # thread; TrayController takes no argument and ignores one.
        if mac_support.IS_MAC:
            self.tray.start(self.overlay.root)
        else:
            self.tray.start()
        # X-172b, measured on the frozen build: spawning the settings renderer
        # and booting its webview costs about 5s, and _start_input_runtime()
        # below blocks THIS thread for ~3.8s before Tk's mainloop ever runs --
        # so a root.after() prewarm cannot begin until the audio wait is over
        # and the two costs ran end to end. Home appeared at 9.3s. Started here,
        # on its own thread, the spawn overlaps the audio init. ShellController
        # .open() takes its own lock, so the later open_home() cannot race it
        # into spawning a second renderer. Nothing on this thread touches Tk.
        if (
            self.web_shell is not None
            and bool(self.config.get("ui", {}).get("show_home_on_start", True))
            and not self.needs_onboarding()
        ):
            def prewarm_home_renderer() -> None:
                with contextlib.suppress(Exception):
                    self.web_shell.prewarm_settings()

            threading.Thread(target=prewarm_home_renderer, name="TalkDatPrewarmHome", daemon=True).start()
        if self.web_shell is not None:
            self.overlay.root.after(3000, self.web_shell.prewarm)
        dictation = self.config.get("dictation", {})
        prewarm_sounds([str(dictation.get("sound_on", "felted_halo")), str(dictation.get("sound_off", "wood_block"))])
        self.overlay.set_state("processing", "Preparing microphone.", "Triggers enable when audio is ready.")
        self.overlay.force_visible()
        with contextlib.suppress(Exception):
            self.overlay.root.update_idletasks()
        # X-123, his order: Home greets every boot (sign-in state included --
        # the saved licence signs in by itself). Off-switch in config;
        # onboarding keeps the first-run stage to itself.
        # X-172, his report 2026-09-21 -- two faults, one line apart:
        #   "it goes to like this weird menu where settings has to appear
        #    first ... random settings that I had open"  -> this called
        #   open_settings(), whose no-destination branch falls back to the
        #   last page the previous session closed on. It calls open_home()
        #   now, which is an explicit destination with no such branch.
        #   "when it opened up, it was massively laggy" -> X-124 papered over
        #   that by WAITING for PortAudio (7.7s measured) before opening,
        #   because opening built the renderer on the pill's own thread. So a
        #   launch sat blank for the whole audio load and then paid for a cold
        #   process spawn anyway. The renderer is prewarmed hidden instead,
        #   which is what the pill menu has always done, and Home opens on a
        #   renderer that is already up.
        if bool(self.config.get("ui", {}).get("show_home_on_start", True)) and not self.needs_onboarding():
            def open_home_when_calm(tries: int = 0) -> None:
                # The audio wait is gone; a live dictation is the one thing
                # still worth yielding to, since opening a window over it
                # takes the focus the words are being typed into.
                with self.lock:
                    busy = self.session is not None or self.session_token is not None
                if not busy or tries > 20:
                    self.overlay.open_home()
                    return
                self.overlay.root.after(700, lambda: open_home_when_calm(tries + 1))

            # The renderer was started on its own thread above, before the
            # audio init; by the time the mainloop runs this is a navigate.
            self.overlay.root.after(250, open_home_when_calm)
        with contextlib.suppress(Exception):
            self.overlay.prewarm_grow_frames()
        self._start_input_runtime()
        self.overlay.set_state(
            "idle",
            self._idle_hint(),
            "Mic is off. STT is idle.",
        )
        self.overlay.force_visible()
        self.overlay.root.after(700, self.apply_performance_preset_once)
        self.overlay.root.after(700, self.prefetch_selected_local_model)
        self.overlay.root.after(900, self.warm_selected_local_model)
        if self.needs_onboarding():
            self.overlay.root.after(450, self.overlay.open_onboarding)
        elif self._macos_permissions_need_attention():
            # X-23. These grants are bound to the app's code signature, so a
            # rebuild or a reinstall clears them and every headline feature goes
            # quiet at once with no error anywhere. Setup is finished, so the
            # whole wizard would be wrong -- open the one page that fixes it.
            self.overlay.root.after(450, lambda: self.overlay.open_onboarding("permissions"))
        if bool(self.config.get("updates", {}).get("check_on_start", True)):
            self.overlay.root.after(2600, lambda: self.check_updates(silent=True))
        self._schedule_periodic_update_check()
        from .activation_metrics import report_heartbeat, report_install, stamp_first_run

        stamp_first_run(self.config, save_config)
        # X-132: the count-only install ping, retried until acked. Rides the
        # same startup beat and the same anonymous install id.
        # Open source: "" (send nothing) in a source build, with the kill
        # switch, or when Settings > Privacy > "Share anonymous usage counts"
        # is off (privacy.share_usage_counts) -- official_build decides.
        # Local-only privacy governs audio and text, not these counts.
        from .official_build import activation_api_base, describe as _describe_build

        log.info("network services: %s", _describe_build(self.config))
        _metrics_api = activation_api_base(self.config)
        report_install(self.config, save_config, _metrics_api)
        # X-167: the install ping fires once, so it counts machines that ever
        # installed, not machines still in use. This one says "a copy of this
        # version ran today", at most daily, which is what makes an ACTIVE count
        # and a version breakdown possible. Same privacy budget: anonymous id,
        # version, platform, nothing else.
        report_heartbeat(self.config, save_config, _metrics_api)
        if sys.platform == "darwin":
            # X-148: the dmg's Finder drag cannot touch the Dock (no code
            # runs); the app pins its own tile once, first launch from
            # /Applications. mac_support exists only on the mac port -- the
            # guarded import keeps this line merge-stable on main.
            try:
                from .mac_support import pin_to_dock_once

                pin_to_dock_once(self.config, save_config)
            except Exception:
                log.debug("dock pin unavailable", exc_info=True)
        self.overlay.root.after(1500, self.maybe_show_whats_new)
        self.overlay.root.after(2000, self._clipboard_learn_tick)
        self.control_server = ControlServer(
            self.config,
            {
                "status_provider": self.status_snapshot,
                "hands_free": self.toggle_hands_free,
                "panic": self.panic_stop,
                "paste_last": self.paste_last,
                "copy_last": self.copy_last,
                "last_text": lambda: self.last_transcript or self.read_last_history_text(),
            },
        )
        self.control_server.start()
        self.refresh_wake_word()
        self._drain_cross_thread_calls()
        self._collect_garbage_on_tk_thread()
        self.overlay.run()

    def _drain_cross_thread_calls(self) -> None:
        """Run tray, hotkey, and control callbacks on the Tk thread (X-294).

        Background threads only ever queue.put() when an action can reach Tk;
        everything graphical happens here. 40ms is beneath what a hand can
        feel on a menu click or emergency stop.
        """
        while True:
            try:
                fn = self._cross_thread_calls.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                log.exception("tray callback failed")
        try:
            self.overlay.root.after(40, self._drain_cross_thread_calls)
        except Exception:
            log.debug("cross-call drain stopped: the window is gone")

    def _collect_garbage_on_tk_thread(self) -> None:
        """The only place cyclic garbage is ever collected (X-294).

        On this thread, dead tkinter objects are freed by the interpreter
        thread that owns them, which is the one arrangement Tcl accepts.
        Young generations every pass; the full heap roughly once a minute.
        """
        self._gc_pass = int(getattr(self, "_gc_pass", 0)) + 1
        try:
            gc.collect(2 if self._gc_pass % 15 == 0 else 1)
        except Exception:
            log.exception("scheduled gc pass failed")
        try:
            self.overlay.root.after(4000, self._collect_garbage_on_tk_thread)
        except Exception:
            log.debug("gc scheduling stopped: the window is gone")

    def _start_input_runtime(self) -> None:
        """Warm PortAudio, then start the hotkeys.

        X-172b tried this on a worker thread to unblock the Tk mainloop, and
        MEASURED WORSE: Home moved from 6.7s to 8.4s. Three heavy startup jobs
        (this, the settings renderer, the local model) then ran at once on a
        six-core machine and contended; serialised, the renderer gets the
        machine while this is only waiting on PortAudio. Kept synchronous
        deliberately -- do not "fix" it again without measuring the window.
        """
        try:
            elapsed_ms = warm_audio_input_backend()
            log.info("audio backend ready: init_ms=%s", int(round(elapsed_ms)))
        except Exception:
            log.exception("audio backend warmup failed; capture will retry on demand")
        self._check_macos_input_permission()
        self.hotkeys.start()

    def _chord(self, action: str, fallback: tuple[str, ...]) -> str:
        return chord_label(getattr(self, "config", {}), action, fallback)

    def _idle_hint(self) -> str:
        """The idle line, naming the chords actually bound on this platform.

        This was a literal "Hold Ctrl+Win to talk. Toggle only with
        Ctrl+Win+Space" in three places here and three more in the overlay. On a
        Mac it named a key that does not exist, and a hands-free chord that is
        deliberately not bound there -- Ctrl+Cmd+Space is the system Character
        Viewer, so the macOS default moved it.
        """
        return (
            f"Hold {self._chord('push_to_talk', ('ctrl', 'cmd'))} to talk. "
            f"Toggle only with {self._chord('hands_free', ('ctrl', 'cmd', 'space'))} or Mic."
        )

    def _check_macos_input_permission(self) -> None:
        """Say so on the Pill when macOS is blocking the trigger key.

        Without Accessibility, pynput's listener starts, logs "this process is
        not trusted" where nobody will see it, and then never reports a key.
        Every symptom of that is silence: holding the trigger does nothing, and
        the app looks broken rather than blocked. macOS will not show its own
        prompt for a listener that simply never receives events, so the app has
        to ask, once, and then keep the reason visible on the Pill.
        """
        if not mac_support.IS_MAC:
            return
        report = mac_support.permission_report()
        missing = permissions_outstanding(report)
        if not missing:
            return
        # X-23: name the one that is actually missing. This used to check
        # Accessibility alone and blame it for everything, so a Mac with
        # Accessibility granted and Input Monitoring refused -- which is the
        # common shape, because they are two separate switches in two separate
        # lists -- was told to fix something already correct while the trigger
        # went on doing nothing.
        pages = {page.key: page for page in permission_pages()}
        first = pages.get(missing[0])
        log.warning("macOS permissions missing: %s", ", ".join(missing))
        # NOTHING is prompted from here. AXIsProcessTrustedWithOptions(prompt)
        # and IOHIDRequestAccess put up a system dialog, and to do that macOS
        # spins its own run loop while the foreign call holds no Python thread
        # state. Tk's event source then fires a callback into that, and the
        # process dies instantly:
        #
        #   Fatal Python error: PyEval_RestoreThread: ... the current Python
        #   thread state is NULL
        #
        # Which from the outside is an app that asks for permission three times
        # and vanishes. The permission page does this properly instead: it
        # explains each one and opens the right Settings pane through
        # /usr/bin/open, a subprocess that cannot re-enter our event loop.
        if first is None:
            return
        with contextlib.suppress(Exception):
            names = " and ".join(pages[name].label for name in missing if name in pages)
            self.overlay.set_state(
                "error",
                f"Allow Talk DAT! under Privacy & Security > {names}, then restart.",
                "",
            )

    def refresh_wake_word(self) -> None:
        if threading.get_ident() != getattr(
            getattr(self, "overlay", None), "_ui_thread_id", threading.get_ident()
        ):
            self._cross_thread_calls.put(lambda: self.refresh_wake_word())
            return
        if getattr(self, "_quitting", False):
            listener = getattr(self, "wake_listener", None)
            if listener is not None:
                listener.stop()
            return
        from .wake_runtime import WakeRuntime

        runtime = getattr(self, "_wake_runtime", None)
        if runtime is None:
            runtime = self._wake_runtime = WakeRuntime(self)
        runtime.refresh(retry=True)

    def toggle_pause(self) -> None:
        if threading.get_ident() != getattr(
            getattr(self, "overlay", None), "_ui_thread_id", threading.get_ident()
        ):
            self._cross_thread_calls.put(lambda: self.toggle_pause())
            return
        self.paused = not self.paused
        self.refresh_wake_word()
        if self.paused:
            self.cancel()
            self.overlay.set_state("idle", "Talk DAT! paused. Triggers are off.", f"Resume from {mac_support.MENU_SURFACE_NAME}: Resume dictation.")
        else:
            self.overlay.set_state(
                "idle",
                f"Talk DAT! resumed. Hold {self._chord('push_to_talk', ('ctrl', 'cmd'))} to talk.",
                "",
            )
        try:
            self.tray.set_paused(self.paused)
        except Exception:
            pass

    def restart(self, *, settings_confirmed: bool = False) -> None:
        if threading.get_ident() != getattr(
            getattr(self, "overlay", None), "_ui_thread_id", threading.get_ident()
        ):
            self._cross_thread_calls.put(
                lambda: self.restart(settings_confirmed=settings_confirmed)
            )
            return
        if getattr(self, "_reset_in_progress", False) and not getattr(self, "_reset_finished", False):
            return
        shell = getattr(self, "web_shell", None)
        if (
            shell is not None
            and not settings_confirmed
            and shell.confirm_exit(lambda: self.restart(settings_confirmed=True))
        ):
            return
        if not self._auxiliary_audio_exit(lambda: self.restart(settings_confirmed=True)):
            return
        import os
        import subprocess
        import sys

        log.info("restart requested")
        with self.lock:
            session = self.session
            capture = self.safety_capture
            self.session = None
            self.session_token = None
            self._guided_delivery_token = None
            self._deferred_delivery_owner = None
            self.safety_capture = None
            self.safety_capture_token = None
            self.safety_capture_failure_token = None
        if session:
            session.cancel()
            with contextlib.suppress(Exception):
                session.join(1.5)
            self.finalize_safety_capture(
                capture,
                status="app_restarted",
                raw_transcript=str(getattr(session, "current_text", lambda: "")() or ""),
                error="Talk DAT! restarted before delivery. The captured audio remains available in History.",
            )
        elif capture is not None:
            self.finalize_safety_capture(
                capture,
                status="app_restarted",
                error="Talk DAT! restarted before delivery. The captured audio remains available in History.",
            )
        self.release_activation_guards()
        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable], close_fds=True)
            else:
                subprocess.Popen(
                    [sys.executable, "-m", "knight_flow"],
                    close_fds=True,
                    cwd=str(self.project_root),
                )
        except Exception as exc:
            self._quitting = False
            log.warning("restart failed to launch new instance: %s", exc)
            self.overlay.set_state("error", "Talk DAT! could not restart.", f"Quit it from {mac_support.MENU_SURFACE_NAME}, then open it again.")
            return
        if shell is not None:
            shell.close()
        os._exit(0)

    def install_or_check_update(self) -> None:
        if self.pending_update is not None:
            self.show_update_window(self.pending_update)
        else:
            self.check_updates(silent=False)

    def maybe_show_whats_new(self) -> None:
        previous = self._previous_version
        if not previous or previous == APP_VERSION:
            return

        def worker() -> None:
            notes = ""
            url = str(self.config.get("updates", {}).get("latest_release_url", "")) or APP_RELEASES_URL
            try:
                # Asked from the PREVIOUS version deliberately: that is what
                # makes the multi-version digest span the versions this
                # person actually skipped. Asking from APP_VERSION made the
                # gap always one release, so the What's New tab showed a
                # sliver of the work every time someone jumped builds.
                info = check_for_update(previous)
                if info.latest_version == APP_VERSION:
                    notes = info.release_notes
                    url = info.release_url or url
            except UpdateError:
                notes = ""
            if not notes.strip():
                # Offline, rate-limited, or a fetch hiccup: the tab must
                # NEVER open empty. The build carries its own changelog;
                # this version's section is always available.
                notes = bundled_changelog_section(APP_VERSION)
            self.overlay.root.after(
                0, lambda: self.overlay.open_whats_new(previous, APP_VERSION, notes, url)
            )

        threading.Thread(target=worker, name="TalkDatWhatsNew", daemon=True).start()

    def pin_last(self) -> None:
        text = self.last_transcript or self.read_last_history_text()
        if not text:
            self.overlay.set_state("error", "No transcript to pin yet.", "Dictate something first, then pin it.")
            return
        try:
            pin_text(text)
            self.overlay.set_state("captured", "Pinned last transcript.", preview(text, 112))
        except OSError as exc:
            log.warning("pin failed: %s", exc)
            self.overlay.set_state("error", "Could not pin the last transcript.", "Nothing was changed. Try again in a moment.")

    def toggle_meeting_mode(self) -> None:
        if threading.get_ident() != getattr(self.overlay, '_ui_thread_id', threading.get_ident()):
            self._cross_thread_calls.put(self.toggle_meeting_mode)
            return
        if self.meeting is not None and self.meeting.running:
            self.meeting.stop()
            return
        if self._scribe_busy() or self.session is not None or self.session_token is not None or microphone_registry().is_active():
            self.overlay.set_state('idle', 'Finish the current recording before starting meeting notes.')
            return

        def deliver(state, message, detail=''):
            def update():
                if self.meeting is recorder and not getattr(self, '_quitting', False) and self.session is None and self.session_token is None:
                    self.overlay.set_state(state, message, detail)
            self._cross_thread_calls.put(update)

        def on_status(message):
            deliver('processing', preview(message, 160))

        def on_line(text):
            deliver('captured', 'Meeting note saved.', preview(text, 112))

        recorder = MeetingRecorder(self.config, on_status=on_status, on_line=on_line)
        self.meeting = recorder
        try:
            recorder.start()
        except Exception:
            self.overlay.set_state('error', 'Meeting notes could not start. Check the recording source and save folder.')

    def _schedule_periodic_update_check(self) -> None:
        hours = int(self.config.get("updates", {}).get("check_interval_hours", 24))
        delay_ms = max(1, hours) * 3600 * 1000

        def tick() -> None:
            if bool(self.config.get("updates", {}).get("check_on_start", True)):
                self.check_updates(silent=True)
            self.overlay.root.after(delay_ms, tick)

        self.overlay.root.after(delay_ms, tick)
        self.start_handoff_watch()
        self.start_right_click_rewrite()

    def needs_onboarding(self) -> bool:
        return not onboarding_is_complete(self.config)

    def _macos_permissions_need_attention(self) -> bool:
        """Whether a finished setup has since lost a macOS permission.

        Only true on macOS, and only when a permission is genuinely refused or
        never granted -- "unknown" means the check could not run, and reopening
        setup over an unreadable answer would be a loop nobody can escape.
        """
        if not mac_support.IS_MAC:
            return False
        with contextlib.suppress(Exception):
            return bool(permissions_outstanding(mac_support.permission_report()))
        return False

    def start_push_to_talk(self) -> None:
        log.info("push_to_talk start")
        if self.stop_hands_free_if_active("push_to_talk"):
            return
        self.start_session("dictation", "Hold mode: release to stop.", control="hold")

    def start_command_mode(self) -> None:
        log.info("command_mode start")
        if self.stop_hands_free_if_active("command_mode"):
            return
        # Capture the command's selection before the microphone opens. Sampling
        # after STT would let a click into another app or field silently change
        # what the spoken command transforms.
        selected, previous_clipboard = copy_selected_text()
        self._command_selection = selected.strip()
        self._command_clipboard = previous_clipboard
        self._command_window = foreground_window_id()
        self._command_focus_window = foreground_focus_window_id()
        self._command_edit_target = foreground_edit_target_signature()
        self._command_input_generation = foreground_input_generation()
        self.start_session("command", "Command: release keys to stop.", control="command_hold")

    def quick_fix_selection(self, instruction: str) -> None:
        """X-351: the right-click door into Fix That's pipeline.

        Same capture, same caret proofs, same engine -- the only
        difference from Fix That is that the instruction arrives TYPED
        (or fixed) instead of spoken, so no microphone session opens.
        The caller has already refocused the original window.
        """
        log.info("quick_fix start: %s", preview(instruction, 40))
        if self.stop_hands_free_if_active("quick_fix"):
            return
        if not self._has_a_writing_model():
            self.overlay.set_state(
                "error",
                "Rewrite needs a writing model.",
                "Choose a local model or add your own provider key in Settings. Either one works.",
            )
            return
        selected, previous_clipboard = copy_selected_text()
        selected = selected.strip()
        if not selected:
            self.overlay.set_state("error", "Select the text first, then right-click and pick Talk DAT!.")
            return
        self._fix_that_selection = selected
        self._fix_that_clipboard = previous_clipboard
        self._fix_that_window = foreground_window_id()
        self._fix_that_focus_window = foreground_focus_window_id()
        self._fix_that_edit_target = foreground_edit_target_signature()
        self._fix_that_input_generation = foreground_input_generation()
        self.apply_fix_that(instruction)

    def start_right_click_rewrite(self) -> None:
        """X-351: install the platform door -- the Windows observer hook,
        or the macOS Services provider. Both reuse quick_fix's pipeline."""
        try:
            from . import selection_menu

            started = selection_menu.start(
                config=self.config,
                on_right_click=lambda x, y, hwnd: self.overlay._post_ui(
                    lambda: self.overlay.show_rewrite_chip(x, y, hwnd)
                ),
            )
            if started:
                log.info("right-click rewrite chip armed")
        except Exception:
            log.warning("right-click rewrite hook failed to start", exc_info=True)
        try:
            from . import mac_services

            mac_services.register(self.config, self.overlay)
        except Exception:
            log.warning("mac services registration failed", exc_info=True)

    def start_handoff_watch(self) -> None:
        """X-11: register talkdat:// and watch for browser-dropped sign-ins."""
        try:
            from .handoff import register_protocol

            register_protocol()
        except Exception:
            log.debug("protocol registration failed", exc_info=True)

        if mac_support.IS_MAC:
            # Windows gets every talkdat:// open as a second process with the
            # URI in argv. macOS only does that when the app is NOT running; if
            # it is -- which is the normal case when someone signs in on the
            # web -- the system delivers an Apple Event to the live process and
            # starts nothing. Feeding that event into the same drop file the
            # tick already watches keeps one code path for both platforms.
            try:
                from .handoff import stash_uri_for_primary

                mac_support.watch_url_scheme(stash_uri_for_primary)
            except Exception:
                log.debug("url scheme handler failed to install", exc_info=True)

        def tick() -> None:
            try:
                from .handoff import parse_signin_code, take_stashed_uri

                uri = take_stashed_uri()
                if uri:
                    code = parse_signin_code(uri)
                    if code:
                        self.complete_handoff(code)
            except Exception:
                log.debug("handoff tick failed", exc_info=True)
            self.overlay.root.after(1200, tick)

        self.overlay.root.after(1200, tick)

    def complete_handoff(self, code: str) -> None:
        """Exchange the one-time code for this PC's licence, zero typing."""

        def worker() -> None:
            try:
                import json as json_module
                import platform
                import urllib.request

                from .licensing import ensure_device_identity
                from .official_build import SIGN_IN_OFF, service_url

                exchange_url = service_url(self.config, "/v1/handoff/exchange")
                if not exchange_url:
                    # A build from source has no account service unless it
                    # was given one; say so rather than fail at the socket.
                    self.overlay.root.after(0, lambda: self.overlay.set_state(
                        "error", "The web sign-in link could not finish.", SIGN_IN_OFF))
                    return
                payload = {
                    "code": code,
                    "deviceId": ensure_device_identity(self.config),
                    "deviceName": platform.node() or platform_copy.THIS_COMPUTER_SENTENCE,
                }
                request = urllib.request.Request(
                    exchange_url,
                    data=json_module.dumps(payload).encode("utf-8"),
                    headers={"content-type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    result = json_module.loads(response.read().decode("utf-8"))
                state = self.license_manager.adopt_handoff(result)
                # Synced preferences ride the same payload (X-06): a fresh
                # PC opens the menu the account left it.
                order = result.get("menuOrder")
                if isinstance(order, list) and order:
                    self.config.setdefault("overlay", {})["menu_order"] = [str(item) for item in order]
                    save_config(self.config)
                self.overlay.root.after(0, lambda: self.overlay.set_state(
                    "captured",
                    f"Signed in on {platform_copy.THIS_COMPUTER}.",
                    state.detail,
                ))
            except Exception as exc:
                log.exception("handoff exchange failed")
                # X-113 #6: say what the server said, and name a control that
                # exists. The old copy told people to press "Continue with
                # Google" -- a button this app has never had.
                detail = "Open the account window and press Website to try again."
                try:
                    import urllib.error

                    if isinstance(exc, urllib.error.HTTPError):
                        body = json_module.loads(exc.read().decode("utf-8"))
                        server_says = str(body.get("message") or "").strip()
                        if server_says:
                            detail = server_says
                except Exception:
                    log.debug("handoff error body unreadable", exc_info=True)
                self.overlay.root.after(0, lambda: self.overlay.set_state(
                    "error",
                    "The web sign-in link could not finish.",
                    detail,
                ))

        threading.Thread(target=worker, name="TalkDatHandoff", daemon=True).start()

    def start_fix_that(self) -> None:
        """X-42: highlight anything, hold the chord, say what you want.

        The selection is captured BEFORE the mic opens -- pressing the chord
        must not steal it -- and the spoken words become the instruction for
        the meaning-preserving rewrite. It needs a model to write with --
        local or the person's own key -- and nothing else."""
        log.info("fix_that start")
        if self.stop_hands_free_if_active("fix_that"):
            return
        if not self._has_a_writing_model():
            self.overlay.set_state(
                "error",
                "Fix That needs a writing model.",
                "Choose a local model or add your own provider key in Settings. Either one works.",
            )
            return
        selected, previous_clipboard = copy_selected_text()
        selected = selected.strip()
        if not selected:
            self.overlay.set_state("error", "Select the text to fix first, then hold the chord and speak.")
            return
        self._fix_that_selection = selected
        self._fix_that_clipboard = previous_clipboard
        self._fix_that_window = foreground_window_id()
        self._fix_that_focus_window = foreground_focus_window_id()
        self._fix_that_edit_target = foreground_edit_target_signature()
        self._fix_that_input_generation = foreground_input_generation()
        self.start_session("fixthat", "Fix That: say what to change, release to apply.", control="hold")

    def apply_fix_that(
        self,
        instruction: str,
        *,
        delivery_token: object = _DYNAMIC_GUIDED_SINK,
    ) -> None:
        """The release half: instruction spoken, rewrite and replace."""
        selection = str(getattr(self, "_fix_that_selection", "") or "")
        previous_clipboard = getattr(self, "_fix_that_clipboard", "")
        target_window = int(getattr(self, "_fix_that_window", 0) or 0)
        target_focus_window = int(getattr(self, "_fix_that_focus_window", 0) or 0)
        target_edit_target = tuple(getattr(self, "_fix_that_edit_target", ()) or ())
        origin_input_generation = int(getattr(self, "_fix_that_input_generation", 0) or 0)
        self._fix_that_selection = ""
        self._fix_that_clipboard = ""
        self._fix_that_window = 0
        self._fix_that_focus_window = 0
        self._fix_that_edit_target = ()
        self._fix_that_input_generation = 0
        instruction = str(instruction or "").strip()
        if not selection:
            return
        if not instruction:
            restore_clipboard_if_unchanged(selection, previous_clipboard)
            self.overlay.set_state(
                "error",
                "No instruction heard. The selection was not touched.",
                "Select the text again, hold the Fix That shortcut, and say the change you want.",
            )
            return

        # A top-level or focused HWND is not enough to identify an edit field:
        # Chromium/Electron can expose one renderer HWND for many DOM inputs.
        # Automatic replacement therefore requires the caret owner + rectangle
        # captured before the mic opened. If any proof is unavailable or moved,
        # Fix That still does the useful work but returns the rewrite by clipboard
        # instead of risking insertion into the wrong field.
        automatic_target_proven = bool(
            target_window
            and target_focus_window
            and target_edit_target
            and foreground_window_id() == target_window
            and foreground_focus_window_id() == target_focus_window
            and foreground_edit_target_signature() == target_edit_target
        )
        if automatic_target_proven:
            verified_selection, _validation_clipboard = copy_selected_text()
            verified_selection = verified_selection.strip()
            if verified_selection != selection:
                automatic_target_proven = False
                if verified_selection:
                    restore_clipboard_if_unchanged(verified_selection, previous_clipboard)
        else:
            restore_clipboard_if_unchanged(selection, previous_clipboard)

        claim = self._reserve_deferred_delivery(delivery_token)
        if claim is None:
            restore_clipboard_if_unchanged(selection, previous_clipboard)
            return
        input_generation = foreground_input_generation()
        log.debug(
            "fix-that target revalidated origin_input=%s delivery_input=%s",
            origin_input_generation,
            input_generation,
        )

        def delivery_owner_is_current() -> bool:
            return self._deferred_delivery_is_current(claim)

        def automatic_delivery_is_current() -> bool:
            return (
                automatic_target_proven
                and delivery_owner_is_current()
                and bool(target_window)
                and foreground_window_id() == target_window
                and bool(target_focus_window)
                and foreground_focus_window_id() == target_focus_window
                and bool(target_edit_target)
                and foreground_edit_target_signature() == target_edit_target
                and bool(input_generation)
                and foreground_input_generation() == input_generation
            )

        def worker() -> None:
            try:
                from .llm import llm_rewrite

                self.overlay.root.after(
                    0,
                    lambda: self.overlay.set_state(
                        "processing", f"Fixing: {preview(instruction, 58)}", preview(selection, 112)
                    ) if self._deferred_delivery_is_current(claim) else None,
                )
                from .style_profile import render_instruction

                voice = render_instruction(self.config.get("style_profile", {}))
                result = llm_rewrite(selection, instruction, self.config, system=voice)
                result = str(result or "").strip()
                if not result:
                    raise RuntimeError("empty rewrite")

                def deliver() -> None:
                    try:
                        with external_delivery_claim():
                            if not delivery_owner_is_current():
                                return
                            automatic = automatic_delivery_is_current()
                            keep_previous = bool(
                                self.config.get("dictation", {}).get(
                                    "restore_clipboard_after_paste", True
                                )
                            )
                            receipt = paste_text_with_receipt(
                                result,
                                restore_clipboard=False,
                                paste_mode=(
                                    str(self.config.get("dictation", {}).get("paste_mode", "auto"))
                                    if automatic
                                    else "copy_only"
                                ),
                                typing_interval_ms=config_int(
                                    self.config.get("dictation", {}).get("typing_interval_ms"), 2
                                ),
                                clipboard_paste_delay_ms=config_int(
                                    self.config.get("dictation", {}).get("clipboard_paste_delay_ms"), 10
                                ),
                                can_deliver=(
                                    automatic_delivery_is_current
                                    if automatic
                                    else delivery_owner_is_current
                                ),
                            )
                            if automatic:
                                receipt = _copy_after_precommit_refusal(
                                    result,
                                    receipt,
                                    can_deliver=delivery_owner_is_current,
                                )
                            if not delivery_owner_is_current():
                                return
                            if receipt.method == "copy_only":
                                # Manual handoff is the safe fallback; the result
                                # must remain available for the user's own paste.
                                pass
                            elif keep_previous:
                                expected = (
                                    result
                                    if receipt.method in {"clipboard", "shift_insert"}
                                    else selection
                                )
                                restore_clipboard_if_unchanged(expected, previous_clipboard)
                            elif receipt.method not in {"clipboard", "shift_insert"}:
                                copy_text(result)
                            self.last_original = selection
                            self.last_transcript = result
                            self.last_diff = unified_diff(selection, result)
                            if not receipt.success:
                                failure_message = (
                                    "Fix That could not verify whether insertion completed. "
                                    "Inspect the field before pasting again."
                                    if receipt.method == "clipboard_commit_unknown"
                                    else "Fix That stopped during typing. Review the field; "
                                    "the full rewrite is kept as the last result."
                                    if receipt.method == "direct_type_partial"
                                    else "Fix That kept the rewrite as the last result, but the clipboard copy failed."
                                )
                                # What to do, not a preview of the text: the
                                # toast under the error is read as advice.
                                self.overlay.set_state(
                                    "error",
                                    failure_message,
                                    "The rewrite is kept: Paste last transcript in the Pill menu puts it in.",
                                )
                                return
                            message = (
                                "Fixed in place."
                                if receipt.method != "copy_only"
                                else "Rewrite copied. Return to the original selection and paste."
                            )
                            self.overlay.set_state("captured", message, preview(result, 112))
                            if receipt.method != "copy_only":
                                with contextlib.suppress(Exception):
                                    self.offer_correction_learning(selection, result, instruction)
                    finally:
                        self._release_deferred_delivery(claim)

                self.overlay.root.after(0, deliver)
            except Exception:
                log.exception("fix that failed")

                def show_failure() -> None:
                    try:
                        if not self._deferred_delivery_is_current(claim):
                            return
                        restore_clipboard_if_unchanged(selection, previous_clipboard)
                        self.overlay.set_state(
                            "error", "Fix That could not finish.", "The selection was not changed."
                        )
                    finally:
                        self._release_deferred_delivery(claim)

                self.overlay.root.after(0, show_failure)

        threading.Thread(target=worker, name="TalkDatFixThat", daemon=True).start()

    def offer_correction_learning(self, before: str, after: str, instruction: str) -> None:
        """Offer a spelling only after the explicit Fix That edit was delivered."""
        from .learned_words import (
            already_known, auto_learn_mode, correction_candidate, remember_correction, tombstoned,
        )
        if auto_learn_mode(self.config) == "off":
            return
        pair = correction_candidate(before, after, instruction)
        if not pair or already_known(pair[1], self.config) or tombstoned(pair[1], self.config):
            return

        def accept() -> None:
            if remember_correction(pair[0], pair[1], self.config):
                self.save_settings()

        self.overlay.offer_learned_word(pair[1], accept)

    def read_back_last(self) -> None:
        """X-38: hear the last dictation before you trust it, eyes-free.

        The built-in Windows voice, spawned hidden -- no dependency, no
        network. Cloud neural voices ride the managed tier later."""
        text = (self.last_transcript or "").strip()
        if not text:
            self.overlay.set_state("error", "Nothing to read back yet.", "Dictate something first.")
            return

        def worker() -> None:
            try:
                import subprocess

                if mac_support.IS_MAC:
                    # macOS ships `say`. The PowerShell System.Speech route has
                    # no counterpart here, so without this the read-back would
                    # fail into a debug log and look like nothing happened.
                    subprocess.run(["/usr/bin/say", text[:2000]], timeout=120)
                    return

                import base64
                import base64
                import subprocess

                encoded = base64.b64encode(text[:2000].encode("utf-16-le")).decode()
                script = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    "$s.Rate = 1; "
                    "$t = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('" + encoded + "')); "
                    "$s.Speak($t); $s.Dispose()"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                    timeout=120,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                log.debug("read back failed", exc_info=True)

        self.overlay.set_state("processing", "Reading it back.", preview(text, 112))
        threading.Thread(target=worker, name="TalkDatReadBack", daemon=True).start()

    def start_microphone_check(self, mode, on_done=None):
        from knight_flow.microphone_check import MicrophoneCheck
        from knight_flow.config import _SAVE_LOCK
        with self.lock:
            previous = getattr(self, '_microphone_check', None)
            captions = getattr(self, '_captions_engine', None)
            practice = getattr(self, '_pronunciation_practice', None)
            if (self._scribe_busy() or (getattr(self, 'meeting', None) is not None and self.meeting.running)
                    or (previous is not None and not previous.finished.is_set())
                    or (captions is not None and not captions.finished.is_set())
                    or (practice is not None and practice.active)
                    or self.session is not None or self.session_token is not None or microphone_registry().is_active()):
                raise ValueError('Finish the current recording or check before starting another.')
            def delivered(state):
                if getattr(self, '_microphone_check', None) is check and on_done is not None:on_done(state)
            with _SAVE_LOCK:
                check = MicrophoneCheck(self.config, registry=microphone_registry(),
                    dispatch=self._cross_thread_calls.put, mode=mode, on_done=delivered)
            self._microphone_check = check
            check.start()
            return check


    def stop_microphone_check(self):
        check = getattr(self, '_microphone_check', None)
        if check is not None:check.stop()


    def set_microphone_input(self, value):
        from knight_flow.config import _SAVE_LOCK, save_config
        if type(value) is not str or len(value)>512 or '\x00' in value:
            raise ValueError('Choose a microphone from the input list.')
        with self.lock:
            check=getattr(self,'_microphone_check',None)
            if check is not None and not check.finished.is_set():
                raise ValueError('Stop the check before changing microphones.')
            with _SAVE_LOCK:
                candidate=copy.deepcopy(self.config)
                candidate.setdefault('audio',{})['input_device']=value
                save_config(candidate)
                self.config.clear();self.config.update(candidate)


    def run_mic_doctor(self, report_cb):
        """Test only the selected input, then deliver its level report on the UI queue."""
        def done(state):
            from knight_flow.mic_doctor import MicReport
            values = state.get('report')
            if values:
                report_cb(MicReport(**{key:values[key] for key in ('speech_rms','noise_floor','clipping_ratio','verdict','advice')}))
            elif state['phase'] == 'error':
                report_cb(MicReport(0.0,0.0,0.0,'error',state['message']))
        return self.start_microphone_check('mic', done)


    def run_taste_race(self, update_cb, done_cb):
        """Run the existing local speech check; no provider comparison or upload."""
        def done(state):
            if state['phase'] == 'ready':
                update_cb('local',state['recognition_ms'],state['text'] or '(heard nothing)','')
                done_cb('Local recognition time, measured after capture. Test audio discarded.')
            elif state['phase'] == 'error':
                update_cb('local',0,'',state['message']);done_cb(state['message'])
        return self.start_microphone_check('speech', done)


    def _scribe_busy(self):
        engine = getattr(self, '_scribe_engine', None)
        return bool(engine and (not engine.finished.is_set() or (engine.recorder is not None and not engine.recorder.closed.is_set())))

    def toggle_scribe(self) -> None:
        if getattr(self, '_quitting', False):
            return
        if threading.get_ident() != getattr(self.overlay, '_ui_thread_id', threading.get_ident()):
            self._cross_thread_calls.put(self.toggle_scribe)
            return
        with self.lock:
            engine = getattr(self, '_scribe_engine', None)
            if self._scribe_busy():
                if engine.phase == 'transcribing':
                    engine.cancel()
                else:
                    engine.finish()
                return
            if engine is not None and engine.body and engine.saved_path is None:
                self.overlay.set_state('error', 'Your Scribe draft is still unsaved.', 'Save or copy the current draft in Writing > Scribe before starting another.')
                return
            if (self.session is not None or self.session_token is not None
                    or microphone_registry().is_active()
                    or getattr(self, '_captions_engine', None) is not None
                    or (getattr(self, 'meeting', None) is not None and self.meeting.running)
                    or (getattr(self, '_microphone_check', None) is not None and not self._microphone_check.finished.is_set())
                    or getattr(getattr(self, '_pronunciation_practice', None), 'active', False)):
                self.overlay.set_state('idle', 'Finish the current recording or microphone check before starting Scribe.')
                return
            if not self._has_a_writing_model():
                self.overlay.set_state('error', 'Scribe needs a writing model.', 'Choose a local model or your own provider key in Writing > Formatting.')
                return
            from .scribe_engine import ScribeEngine
            engine = ScribeEngine(self.config, dispatch=self._cross_thread_calls.put, on_state=self._on_scribe_state)
            self._scribe_engine = engine
            engine.start()

    def stop_scribe(self):
        engine = getattr(self, '_scribe_engine', None)
        if engine is not None and self._scribe_busy():
            engine.cancel()

    def _on_scribe_state(self, engine, phase, message):
        if getattr(self, '_scribe_engine', None) is not engine or getattr(self, '_quitting', False):
            return
        if getattr(self, 'session', None) is not None or getattr(self, 'session_token', None) is not None:
            return
        state = {'recording': 'listening', 'ready': 'captured', 'review': 'error',
                 'error': 'error', 'close-failed': 'error', 'save-failed': 'error',
                 'empty': 'idle', 'paused': 'idle'}.get(phase, 'processing')
        self.overlay.set_state(state, message, 'Open Writing > Scribe to review notes and original recordings.')

    def toggle_captions(self) -> None:
        """X-32 gated this on the tier, because the streaming engines were
        a server cost. X-491: there is no server leg to pay for, so the gate
        is simply whether there is a model to write with."""
        if not self._has_a_writing_model():
            self.overlay.set_state(
                "error",
                "Live captions need a writing model.",
                "Choose a local model or add your own provider key in Settings. Either one works.",
            )
            return
        self.overlay.toggle_captions()
        engine = getattr(self, "_captions_engine", None)
        if engine is not None:
            self._on_caption_state(engine, engine.phase, engine.error)

    def start_captions_stream(self) -> bool:
        """Toggle a bounded local stream; never overlap a retiring model worker."""
        engine = getattr(self, "_captions_engine", None)
        if engine is not None:
            self.stop_captions_stream()
            return False
        check = getattr(self, '_microphone_check', None)
        if check is not None and not check.finished.is_set():
            self.overlay.captions_stream_state("error", "Finish or stop the microphone check before captions.")
            return False
        if self._scribe_busy() or (getattr(self, 'meeting', None) is not None and self.meeting.running):
            self.overlay.captions_stream_state("error", "Finish or pause the meeting recording before captions.")
            return False
        from .caption_stream import LocalCaptionStream

        engine = LocalCaptionStream(
            self.config, registry=microphone_registry(),
            dispatch=self._cross_thread_calls.put,
            on_text=self._on_caption_text, on_state=self._on_caption_state,
        )
        self._captions_engine = engine
        self.overlay.captions_stream_state("preparing", "Preparing the local speech model. Microphone off.")
        engine.start()
        return True

    def stop_captions_stream(self) -> None:
        """Idempotent close path: closing a window can never start a microphone."""
        engine = getattr(self, "_captions_engine", None)
        if engine is not None:
            engine.stop()
            self.overlay.captions_stream_state("stopping", "Closing the microphone.")

    def _on_caption_text(self, engine, text: str) -> None:
        if getattr(self, "_captions_engine", None) is engine and not engine.stop_event.is_set():
            self.overlay.captions_update(text, True)

    def _on_caption_state(self, engine, phase: str, detail: str) -> None:
        if getattr(self, "_captions_engine", None) is not engine:
            return
        if engine.finished.is_set():
            self._captions_engine = None
        status = detail or {"preparing": "Preparing the local speech model. Microphone off.",
                            "starting": "Opening the microphone.", "stopping": "Stopping captions."}.get(phase, "")
        self.overlay.captions_stream_state(phase, status)
        # Captions is independent of normal dictation. Its late state must not
        # replace the Pill's active recording or delivery status.
        if getattr(self, "session", None) is not None or getattr(self, "session_token", None) is not None:
            return
        if detail:
            self.overlay.set_state("error", detail, "")
        elif phase == "listening":
            self.overlay.set_state("captured", "Live captions running.", "Speech is transcribed on this computer.")
        elif phase == "stopped":
            self.overlay.set_state("idle", "Captions stopped.", "")

    def start_ramble(self) -> None:
        """X-40: talk for up to an hour; download a finished document.

        X-491: the gate was a billing rule and is now a capability one --
        the polish needs a model to write with, local or the person's own.
        The format is chosen BEFORE the mic opens, exactly as specced: click
        Ramble, pick the output, talk."""
        shell = getattr(self, "web_shell", None)
        if shell is not None and shell.open_settings("ramble"):
            return
        if not self._has_a_writing_model():
            self.overlay.set_state(
                "error",
                "Ramble needs a writing model.",
                "Choose a local model or add your own provider key in Settings. Either one works.",
            )
            return

        def begin(fmt: str) -> None:
            self._ramble_format = fmt
            self.overlay.root.after(0, self.overlay.show_ramble_indicator)
            self.start_session(
                "ramble",
                "Ramble: talk as long as you like. Toggle hands-free or click the pill to finish.",
                control="hands_free",
            )

        self.overlay.open_ramble_chooser(begin)

    def finish_ramble(self, raw_text: str) -> None:
        self.overlay.root.after(0, self.overlay.hide_ramble_indicator)
        """The delivery half: full pipeline, then a real document."""
        fmt = str(getattr(self, "_ramble_format", "markdown") or "markdown")
        self._ramble_format = ""

        def worker() -> None:
            try:
                from .ramble_export import save_ramble

                processed = process_dictation(raw_text, self.config)
                path = save_ramble(processed.text, fmt)
                self.last_transcript = processed.text

                def announce() -> None:
                    self.overlay.set_state("captured", f"Ramble saved: {path.name}", str(path.parent))
                    try:
                        import os

                        os.startfile(str(path.parent))  # noqa: S606 - opening the user's own folder
                    except Exception:
                        log.debug("could not open the rambles folder", exc_info=True)

                self.overlay.root.after(0, announce)
            except Exception:
                log.exception("ramble export failed")
                # The ramble path returns from finish_session before
                # add_history ever runs, so "your words are in History" was a
                # promise this branch cannot keep. What DOES hold the words is
                # the live transcript draft the session wrote just before
                # handing off -- unless transcript history is off, in which
                # case the draft was deliberately cleared (X-222) and honesty
                # means saying no copy was kept.
                draft = live_draft_path()
                detail = (
                    f"Your words are in the live draft: {draft}"
                    if draft.exists()
                    else "Transcript history is off, so no copy was kept on disk."
                )
                self.overlay.root.after(0, lambda: self.overlay.set_state(
                    "error", "The ramble was transcribed but the document failed.",
                    detail))

        self.overlay.root.after(0, lambda: self.overlay.set_state(
            "processing", "Building your document.", ""))
        threading.Thread(target=worker, name="TalkDatRamble", daemon=True).start()

    def toggle_hands_free(self) -> None:
        if threading.get_ident() != getattr(
            getattr(self, "overlay", None), "_ui_thread_id", threading.get_ident()
        ):
            self._cross_thread_calls.put(lambda: self.toggle_hands_free())
            return
        runtime = getattr(self, "_wake_runtime", None)
        if runtime is not None and runtime.cancel_handoff():
            self.overlay.set_state(
                "idle", "Dictation cancelled before opening its microphone."
            )
            return
        # X-115 trigger feel: two toggles inside a quarter second are one
        # decision plus chatter, never two decisions -- the same law the
        # trigger key already follows (BOUNCE_MS). Without this, an impatient
        # double-click opened a session and slammed it shut milliseconds
        # later, which read as "it activates and deactivates and just breaks".
        now = time.monotonic()
        with self.lock:
            if now - self._last_hands_free_toggle_at < 0.25:
                log.info(
                    "hands_free toggle ignored: %.0fms after the last (chatter)",
                    (now - self._last_hands_free_toggle_at) * 1000.0,
                )
                return
            self._last_hands_free_toggle_at = now
            active = self.session is not None
        if active:
            self.stop_session()
        else:
            log.info("hands_free start")
            self.start_session(
                "dictation", "Hands-free: toggle to stop.", control="hands_free"
            )

    def stop_hands_free_if_active(self, source: str) -> bool:
        with self.lock:
            should_stop = self.session is not None and self.session_control == "hands_free"
        if not should_stop:
            return False
        log.info("%s requested while hands_free active; stopping session", source)
        self.stop_session()
        return True

    def start_session(self, mode: str, message: str, *, control: str = "hold") -> None:
        if threading.get_ident() != getattr(
            getattr(self, "overlay", None), "_ui_thread_id", threading.get_ident()
        ):
            self._cross_thread_calls.put(
                lambda: self.start_session(mode, message, control=control)
            )
            return
        if getattr(self, "_quitting", False):
            return
        if mode == "dictation":
            # The model finishes this take after release. If Ollama dropped it
            # (a restart, another model taking the VRAM), load it now, while
            # the person is still talking, instead of timing out afterwards.
            # Non-blocking; at most one check every twenty seconds.
            try:
                keep_local_finisher_resident(self.config)
            except Exception:
                log.debug("finisher residency check skipped", exc_info=True)
        if self._scribe_busy() or (
            getattr(self, "meeting", None) is not None and self.meeting.running
        ):
            self.overlay.set_state(
                "idle", "Finish or pause the meeting recording before dictating."
            )
            return
        # X-161, reported: "upon clicking, the interface occasionally fails to
        # transition to gray, instead experiencing latency before improperly
        # scaling". The cause was the ORDER of this function. It opened with a
        # cloud handshake -- a real network round trip -- and only reached its
        # first set_state afterwards, so on a slow link the pill sat in `idle`
        # through the whole connect and the press looked ignored. The grow then
        # arrived late and read as a glitch rather than a response.
        #
        # The standby gray is now the FIRST thing that happens, before any
        # work at all. It is what X-137 asked for in the first place: the click
        # answers instantly in gray, and the pill grows only once the mic is
        # genuinely open (`listening`, per EXPANDED_STATES).
        #
        # `paused` is checked first only because it is a bool read; it cannot
        # stall, and flashing gray before saying "paused" would be a lie.
        if self.paused:
            log.info("session start ignored: paused")
            self.overlay.set_state("idle", f"Talk DAT! is paused. Resume from {mac_support.MENU_SURFACE_NAME}: Resume dictation.", "")
            return
        # X-106: a trigger press while the previous dictation is still being
        # transcribed is a decision, not noise. Decode it BEFORE the
        # already-active gate below turns every press into a shrug: pressed
        # again after a beat = "no, redo" (cancel in flight, this press starts
        # the redo); pressed within the bounce window = finger chatter (the
        # in-flight result is worth more than a twitch); mic still open =
        # key auto-repeat (ignore, or holding would cancel itself).
        with self.lock:
            in_flight = self.session is not None or self.session_token is not None
            released = bool(self._released_processing)
            released_at = self._trigger_released_at
        if in_flight:
            since_release_ms = (
                (time.perf_counter() - released_at) * 1000.0
                if released_at is not None
                else None
            )
            intent = press_intent(
                recording=not released,
                processing=released,
                ms_since_release=since_release_ms,
            )
            if intent == PRESS_CANCEL_AND_RESTART:
                log.info(
                    "trigger press %.0fms after release: canceling the in-flight dictation for a redo",
                    since_release_ms or -1.0,
                )
                self.cancel()
            elif intent == PRESS_BOUNCE:
                log.info(
                    "trigger press ignored: bounce %.0fms after release; the in-flight result delivers",
                    since_release_ms or -1.0,
                )
                return
            else:
                log.info("session start ignored: already recording")
                return

        # X-166, his report: "press to hold not holding, sometimes not
        # triggering at all". X-161 put this grey at the very top of the
        # function, ABOVE the gate below, so an auto-repeat while he was holding
        # repainted the pill to `starting` and then returned -- dragging a live
        # dictation back out of `listening` and making the hold look dropped.
        #
        # The grey belongs after the last point a press can be refused, and it
        # is still immediate: everything above is a lock and a few comparisons,
        # microseconds, while the slow thing (the cloud handshake) now runs on
        # its own thread below.
        runtime = getattr(self, "_wake_runtime", None)
        if runtime is not None and runtime.handoff(
            lambda: self.start_session(mode, message, control=control)
        ):
            return
        self.overlay.set_state("starting", "Opening microphone.")

        self._maybe_return_to_cloud()
        # 2026-09-22: Talk DAT! is free. There is no entitlement gate here --
        # no plan, trial or word allowance can refuse a dictation, signed in
        # or not. tests/test_talk_dat_is_free.py keeps it that way.
        with self.lock:
            check = getattr(self, "_microphone_check", None)
            if check is not None and not check.finished.is_set():
                self.overlay.set_state(
                    "idle", "Finish or stop the microphone check before dictating."
                )
                return
            if getattr(getattr(self, "_pronunciation_practice", None), "active", False):
                self.overlay.set_state(
                    "idle", "Finish or cancel pronunciation practice before dictating."
                )
                return
            if self.session is not None or self.session_token is not None:
                log.info("session start ignored: already active")
                self.overlay.set_state(
                    "processing", "Still processing the previous dictation."
                )
                return

            from .stt_registry import resolve_route

            # The pill's three-position switch resolves HERE, before the
            # microphone opens: local is local, cloud is the user's cloud
            # leg, and auto picks the leg only when it can actually work.
            profile = copy.deepcopy(active_profile(self.config))
            provider_id = resolve_route(self.config)
            session_config = self.config
            route_notice = ""
            # X-480: the route resolved to local while the config still names
            # something else -- a provider without a key, or a name left over
            # from the retired managed cloud. The session would then carry a
            # provider name nothing can serve.
            #
            # Deciding once, before the microphone opens, is the entire reason
            # this block exists, so the config handed to the session has to
            # agree with the decision.
            config_names = str(self.config.get("stt", {}).get("provider", "")).strip()
            if provider_id == "local" and config_names not in ("", "local"):
                stale = local_fallback.fallback_model(self.config)
                if stale is not None:
                    session_config = local_fallback.config_using(self.config, stale)
            # A config saved in the managed-cloud era still names that
            # service. There is nothing behind the name, so the dictation runs
            # here -- or, with no model on this machine, is refused with the
            # two ways in that exist. Signed in or not makes no difference:
            # 2026-09-22, Talk DAT! is free and an account gates nothing.
            if provider_id == "local" and config_names == "talk_dat_cloud":
                offline = local_fallback.fallback_model(self.config)
                if offline is None:
                    log.info("legacy managed route with no local model: nothing can serve this")
                    self.overlay.set_state(
                        "error",
                        "No speech model on this machine yet.",
                        "Download one from Tools > Local models in the Pill menu, or add your own provider key. Talk DAT! runs on your machine or on your key, and right now it has neither.",
                    )
                    return
                session_config = local_fallback.config_using(self.config, offline)
                route_notice = f"This ran on {platform_copy.THIS_COMPUTER}."
            # Decided before the microphone opens, because the cost of getting
            # this wrong is paid entirely after the person stops speaking. With
            # no route to the internet, a cloud provider spends a DNS timeout
            # and an HTTP timeout before admitting it, and all of that lands on
            # someone watching an empty caret. The rescue path below would still
            # save the dictation; this only removes the wait.
            if (
                bool(getattr(self, "_auto_local_sticky", False))
                # X-532: the reader was gated on route_mode == "auto" too, so
                # even a sticky flag that HAD been set could never be acted
                # on. The flag itself is the condition; it is only ever set
                # by a rescue and only ever cleared by a clean remote
                # dictation or an explicit route change.
                and provider_id != "local"
            ):
                # X-338: cloud already failed three times running; do not
                # make the person watch it fail a fourth. The recovery
                # probe, not the dictation path, decides when to go back.
                sticky_model = local_fallback.rescue_model(session_config, provider_id)
                if sticky_model is not None:
                    session_config = local_fallback.config_using(
                        session_config, sticky_model
                    )
                    provider_id = "local"
                    self.offline_fallback_notice = local_fallback.describe(sticky_model)
            offline_model = local_fallback.preflight_model(session_config, provider_id)
            if offline_model is not None:
                session_config = local_fallback.config_using(session_config, offline_model)
                provider_id = "local"
                self.offline_fallback_notice = local_fallback.describe(offline_model)
                self._note_cloud_fallback()
            else:
                self.offline_fallback_notice = route_notice
            session_config = apply_profile(session_config, profile)
            provider = PROVIDER_BY_ID[provider_id]
            model_id = selected_model_id(session_config, provider_id)
            api_key = selected_stt_api_key(session_config, provider_id)
            if (
                not api_key
                and provider.api_kind != "external"
                and not provider.key_optional
            ):
                log.error("missing STT API key for provider=%s", provider_id)
                self.overlay.set_state(
                    "error",
                    f"Missing {provider.label} API key.",
                    f"Add it in Settings > Speech, or set {provider.env_key}.",
                )
                return

            token = object()
            self.session_token = token
            self._session_profile = (token, profile)
            # X-604: the kind of field this take is going into (password,
            # terminal, single line), read off this thread while the person's
            # focus is still on it. Nothing here waits for the answer.
            from .field_context import FieldProbe

            self._session_field = (token, FieldProbe.start())
            progressive_formatter = getattr(self, "_progressive_formatter", None)
            if progressive_formatter is not None:
                progressive_formatter.reset()
            self._guided_delivery_token = None
            self._deferred_delivery_owner = None
            self.session_mode = mode
            self.session_control = control
            self.session_error_message = ""
            # X-106: this flight is RECORDING until its own release stamps
            # otherwise. A stale released-flag here would let a press cancel
            # an open microphone.
            self._released_processing = False
            self._trigger_released_at = None
            state = "command" if mode == "command" else "starting"
            # Say it while they are still holding the key. Told afterwards it
            # reads as an apology for a transcript they have already accepted;
            # told now it reads as the product working without a network, which
            # is the thing being sold.
            self.overlay.set_state(state, message, self.offline_fallback_notice)
            limits = self.session_limits(control, provider_id)
            # X-34: one on-device read of the foreground window title; its
            # proper nouns bias THIS dictation's vocabulary and then vanish.
            try:
                from .screen_context import foreground_title, names_from_title

                self._screen_names = names_from_title(foreground_title())
            except Exception:
                self._screen_names = []

            try:
                session = create_stt_session(
                    config=session_config,
                    max_seconds=limits["max_seconds"],
                    no_speech_timeout_seconds=limits["no_speech_timeout_seconds"],
                    silence_timeout_seconds=limits["silence_timeout_seconds"],
                    tail_capture_ms=int(
                        self.config.get("dictation", {}).get("tail_capture_ms", 520)
                    ),
                    min_capture_ms=int(
                        self.config.get("dictation", {}).get("min_capture_ms", 900)
                    ),
                    on_update=lambda text, is_final, t=token, m=mode: (
                        self.on_session_update(t, m, text, is_final)
                    ),
                    on_status=lambda status, t=token, m=mode, c=control: (
                        self.on_session_status(t, m, status, c)
                    ),
                    on_level=lambda level: self.overlay.set_level(level),
                    on_done=lambda text, t=token, m=mode: self.on_session_done(t, m, text),
                    on_error=lambda error, t=token: self.on_session_error(t, error),
                    on_audio=lambda data, rate, channels, heard, t=token: (
                        self.on_session_audio(t, data, rate, channels, heard)
                    ),
                )
                if mode == "dictation" and hasattr(session, "on_stable_update"):
                    prepared_config = apply_profile(self.config, profile)
                    if self._screen_names:
                        prepared_config = {
                            **prepared_config,
                            "_screen_names": list(self._screen_names),
                        }
                    session.on_stable_update = lambda text, t=token, cfg=prepared_config: (
                        self.prepare_stable_dictation(t, text, cfg)
                    )
                capture_limit = max(
                    5,
                    config_int(
                        self.config.get("dictation", {}).get("safety_recording_limit"), 5
                    ),
                )
                capture = start_safety_capture(
                    mode=mode,
                    control=control,
                    provider=provider_id,
                    model=model_id,
                    limit=capture_limit,
                )
            except Exception as exc:
                self.session_token = None
                self.session_mode = "idle"
                self.session_control = "idle"
                self.overlay.set_state(
                    "error",
                    f"Could not protect this voice session: {preview(str(exc), 82)}",
                    "The microphone stayed off so your speech could not be lost.",
                )
                log.exception("could not arm protected voice session")
                return
            self.session = session
            self.safety_capture = capture
            self.safety_capture_token = token
            # X-50b: the dead-mic ding must also cover the mic that never
            # OPENS (PaErrorCode -9999 in the field): zero audio callbacks
            # means the frame counter never runs, so a one-shot timer asks
            # "has ANY frame arrived?" 2.5s in.
            self._session_audio_seen = False
            self.safety_capture_failure_token = None

        def no_frames_check(check_token=token) -> None:
            if check_token is not self.session_token:
                return
            if getattr(self, "_session_audio_seen", False):
                return
            if getattr(self, "_dead_mic_warned", None) is check_token:
                return
            self._dead_mic_warned = check_token
            with contextlib.suppress(Exception):
                from .chimes import play_sound_named

                play_sound_named("chime_down")
            self.overlay.set_state(
                "error",
                "The microphone did not start.",
                "Check your microphone, or open Mic Doctor in Settings > Dictation.",
            )

        # X-354: both of these lived INSIDE the lock above, and neither needs
        # it -- the mute guard talks to a COM audio endpoint that can stall for
        # seconds on a busy device, and holding the app lock through that is
        # what parked the UI thread behind a trigger press (the ghosted setup
        # window). They run here, after the lock, before the mic opens.
        #
        # The timer is armed THROUGH main_thread.post because this method runs
        # on the hotkey dispatch worker: the guarded root.after deliberately
        # drops the delay for cross-thread callers, so arming it directly from
        # here would fire the dead-mic check ~25ms in -- before the first
        # audio frame can possibly arrive -- instead of at 2.5s. Posted, the
        # real Tcl timer is created on the Tk thread with its real delay.
        main_thread.post(lambda: self.overlay.root.after(2500, no_frames_check))
        self.begin_activation_guards()

        try:
            session.start()
            log.info(
                "session started: mode=%s provider=%s model=%s", mode, provider_id, model_id
            )
        except Exception as exc:
            with self.lock:
                if self.session is session:
                    self.session = None
                    self.session_token = None
                    self.session_chime_token = None
                    failed_capture = self.safety_capture
                    self.safety_capture = None
                    self.safety_capture_token = None
                    self.safety_capture_failure_token = None
                else:
                    failed_capture = None
            if failed_capture is not None:
                self.finalize_safety_capture(
                    failed_capture,
                    status="start_failed",
                    error=str(exc),
                )
            self.release_activation_guards()
            self.overlay.set_state(
                "error",
                f"{provider.label} could not start: {preview(str(exc), 82)}",
                "Check it in Settings > Speech, or switch to Local speech from the Pill menu.",
            )
            log.exception("could not start STT provider=%s model=%s", provider_id, model_id)

    def session_limits(self, control: str, provider_id: str | None = None) -> dict[str, int]:
        dictation = self.config.get("dictation", {})
        hold = control in {"hold", "command_hold"}
        # X-41: nobody hits the 5-minute wall that cut Mayowa off mid-ramble.
        # The ceiling comes from the ENGINE alone (local 10h, own-key cloud
        # 1h) -- Talk DAT! is free, so there is no plan to consult; a user's
        # own smaller setting is respected, never exceeded.
        cloud_engine = bool(provider_id) and provider_id != "local"
        ceiling = engine_recording_ceiling(cloud_engine)
        key = "hold_max_seconds" if hold else "max_seconds"
        configured = dictation.get(key)
        # X-185: a SHIPPED DEFAULT is not a user's choice, and treating it as one
        # is why X-41 never actually worked.
        #
        # DEFAULT_CONFIG carries max_seconds=300 and hold_max_seconds=1800, so
        # `configured` is never None for anyone. The line below used to read
        # `min(int(configured), ceiling)`, which on the cloud engine computed min(300, 3600) = 300. The five-minute wall that X-41
        # set out to remove was the shipped default itself, so people kept
        # being cut off mid-ramble and the comment above described a fix that
        # could not fire.
        #
        # "Still equal to what we shipped" now means "not customised", so the
        # engine's ceiling applies; anyone who has actually chosen a limit still
        # gets it, and still never exceeds the ceiling.
        shipped = DEFAULT_CONFIG.get("dictation", {}).get(key)
        customised = (
            configured is not None
            and shipped is not None
            and int(configured) != int(shipped)
        )
        if customised:
            max_seconds = min(int(configured), ceiling)
        else:
            max_seconds = ceiling
        if hold:
            return {
                "max_seconds": max_seconds,
                "no_speech_timeout_seconds": int(dictation.get("hold_no_speech_timeout_seconds", 120)),
                "silence_timeout_seconds": int(dictation.get("hold_silence_timeout_seconds", 300)),
            }
        return {
            "max_seconds": max_seconds,
            "no_speech_timeout_seconds": int(dictation.get("no_speech_timeout_seconds", 15)),
            "silence_timeout_seconds": int(dictation.get("silence_timeout_seconds", 45)),
        }

    def _session_heard_nothing(self, session: Any) -> bool:
        """X-138: true only when the capture is provably empty -- no interim
        text, no VAD voice, no RMS signal. Any doubt returns False and the
        normal finalize runs; the cost of a wrong False is a short wait, the
        cost of a wrong True is a lost dictation."""
        try:
            if str(getattr(session, "current_text", lambda: "")() or "").strip():
                return False
            audio = self.session_audio(session)
            if audio is None:
                return False
            pcm16, _sample_rate, _channels, heard_voice = audio
            if heard_voice:
                return False
            return not likely_has_input_signal(pcm16)
        except Exception:
            log.debug("empty-capture check failed; finalizing normally", exc_info=True)
            return False

    def stop_session(self) -> None:
        if threading.get_ident() != getattr(
            getattr(self, "overlay", None), "_ui_thread_id", threading.get_ident()
        ):
            self._cross_thread_calls.put(lambda: self.stop_session())
            return
        runtime = getattr(self, "_wake_runtime", None)
        if runtime is not None and runtime.cancel_handoff():
            self.overlay.set_state(
                "idle", "Dictation cancelled before opening its microphone."
            )
            return
        with self.lock:
            session = self.session
        if session is None:
            return
        # X-138 (his priority): an accidental press with nothing said must
        # not sit in "Finalizing" while a silent stream times out. A
        # provably-empty capture is a cancel, not a finalize -- the pill
        # returns to idle immediately.
        if self._session_heard_nothing(session):
            log.info("empty-capture fast abort: no voice, no signal, no text")
            self.cancel()
            self.overlay.set_state("idle", "Nothing heard. Mic closed.", "")
            return
        self.overlay.set_state("processing", "Finalizing. Mic closing.")
        log.info("session stop requested")
        self.last_session_ended_at = time.time()
        # X-106: from this release until the result lands, a trigger press is
        # a decision about the IN-FLIGHT dictation -- see press_intent.
        self._trigger_released_at = time.perf_counter()
        self._released_processing = True
        # The seam is the settled pause after dictation, not the instant it
        # stops -- the next sentence is often already coming. Re-checked when
        # the timer fires, so a resumed session simply blocks the reminder.
        with contextlib.suppress(Exception):
            self.overlay.root.after(
                (IDLE_SETTLE_SECONDS + 5) * 1000,
                lambda: self.remind_about_update(TRIGGER_IDLE),
            )
        # Trailing audio is already handled downstream: the capture loop keeps
        # the stream open and sleeps `dictation.tail_capture_ms` (520ms by
        # default, adjustable in Settings) after the stop event, so the last
        # word is still being recorded. Adding a second delay here would stack
        # on that and give two knobs for one behaviour.
        session.stop()

    def cancel(self) -> None:
        if threading.get_ident() != getattr(
            getattr(self, "overlay", None), "_ui_thread_id", threading.get_ident()
        ):
            self._cross_thread_calls.put(lambda: self.cancel())
            return
        runtime = getattr(self, "_wake_runtime", None)
        if runtime is not None:
            runtime.cancel_handoff()
        progressive_formatter = getattr(self, "_progressive_formatter", None)
        if progressive_formatter is not None:
            progressive_formatter.reset()
        with self.lock:
            session = self.session
            capture = self.safety_capture
            closing_session_id = id(session) if session is not None else None
            closing_sessions = getattr(self, "_dictation_closing_sessions", None)
            if not isinstance(closing_sessions, set):
                closing_sessions = set()
                self._dictation_closing_sessions = closing_sessions
            if closing_session_id is not None:
                closing_sessions.add(closing_session_id)
            self.session = None
            self.session_token = None
            self._guided_delivery_token = None
            self._deferred_delivery_owner = None
            self.safety_capture = None
            self.safety_capture_token = None
            self.safety_capture_failure_token = None
            self.session_chime_token = None
            self.session_mode = "idle"
            self.session_control = "idle"
            self.session_error_message = ""
            self._released_processing = False
            self._trigger_released_at = None
        self.release_activation_guards()
        if session:
            session.cancel()

            # The driver/session thread can take its full 1.5 second join
            # budget. Never spend that budget on Tk: Panic Stop reaches this
            # method on the UI thread so every other registered microphone
            # owner can be stopped safely. Detach above, signal cancellation
            # now, and finish protected-audio bookkeeping independently.
            def finish_cancelled_session() -> None:
                try:
                    with contextlib.suppress(Exception):
                        session.join(1.5)
                    raw_transcript = ""
                    with contextlib.suppress(Exception):
                        raw_transcript = str(
                            getattr(session, "current_text", lambda: "")() or ""
                        )
                    with contextlib.suppress(Exception):
                        self.finalize_safety_capture(
                            capture,
                            status="cancelled",
                            raw_transcript=raw_transcript,
                            error=(
                                "Voice session was cancelled. The captured audio remains available "
                                "in History."
                            ),
                        )
                finally:
                    # Both shipped session implementations keep their actual
                    # worker in ``_thread``. Their public ``running`` becomes
                    # false as soon as stop is requested, which is deliberately
                    # too early for a privacy claim. If a custom session has no
                    # thread, a completed join is the best available proof.
                    while True:
                        worker = getattr(session, "_thread", None)
                        try:
                            driver_alive = bool(
                                worker is not None
                                and callable(getattr(worker, "is_alive", None))
                                and worker.is_alive()
                            )
                        except Exception:
                            driver_alive = True
                        if not driver_alive:
                            break
                        try:
                            session.join(0.25)
                        except Exception:
                            time.sleep(0.05)
                    if closing_session_id is not None:
                        with self.lock:
                            current_closing = getattr(
                                self, "_dictation_closing_sessions", None
                            )
                            if isinstance(current_closing, set):
                                current_closing.discard(closing_session_id)

            cleanup = threading.Thread(
                target=finish_cancelled_session,
                name="TalkDatCancelCleanup",
                daemon=True,
            )
            try:
                cleanup.start()
            except Exception:
                log.exception("cancel cleanup worker could not start")
                self.finalize_safety_capture(
                    capture,
                    status="cancelled",
                    error=(
                        "Voice session was cancelled. The captured audio remains available "
                        "in History."
                    ),
                )
            self._landing_sound_pending = False
            self.play_sound("off")
            log.info("session cancelled")
        self.overlay.set_state("idle", self._idle_hint(), "")
        self.overlay.set_level(0)

    def _mic_is_still_open(self) -> bool:
        """True between the trigger press and the stop request: the person is
        still speaking, so nothing may repaint the Pill as processing."""
        return (
            not bool(getattr(self, "_released_processing", False))
            and getattr(self, "session_control", "idle") in LIVE_SESSION_CONTROLS
        )

    def on_session_status(self, token: object, mode: str, status: str, control: str) -> None:
        if not self.is_current(token):
            return
        if status in ENGINE_WORK_STATUSES and self._mic_is_still_open():
            # X-415, his rule: the rainbow means "we are no longer listening,
            # we are processing". While the trigger is held, the engine may
            # load, warm a GPU shape or transcribe a closed segment in the
            # background (X-405), and the local engine reports that through
            # this same callback. Painting the Pill with it told him the mic
            # had closed while he was still talking. The work continues; the
            # Pill stays live until the release, which paints processing itself.
            log.debug("engine status %s during an open mic stays off the Pill", status)
            return
        if status == "warming":
            self.overlay.set_state("starting", "Opening microphone.")
        elif status == "listening":
            should_play = False
            with self.lock:
                if self.session_chime_token is not token:
                    self.session_chime_token = token
                    should_play = True
            if should_play:
                self.play_sound("on")
            state = "command" if mode == "command" else "listening"
            if mode == "command":
                message = "Command: release keys to stop."
            elif control == "hands_free":
                message = "Hands-free: toggle to stop."
            else:
                message = "Hold mode: release to stop."
            self.overlay.set_state(state, message)
        elif status == "connected":
            self.overlay.set_state("starting", "Connected. Opening microphone.")
        elif status == "transcribing":
            self.overlay.set_state("processing", "Transcribing audio.")
        elif status == "downloading_model":
            # The same wordless message existed in two places. This is the one
            # that shows during a dictation that triggers the download, when
            # the pill is the only thing on screen and there is no Settings
            # panel to look at instead.
            self.overlay.set_state("processing", self._local_download_message())
        elif status == "loading_model":
            self.overlay.set_state("processing", "Loading local model.")
        elif status == "time_limit":
            self.overlay.set_state("processing", "Time limit reached. Finalizing.")
        elif status == "no_speech_timeout":
            self.overlay.set_state("processing", self._no_speech_message())
            log.info("credit guard: no speech timeout")
        elif status == "silence_timeout":
            self.overlay.set_state("processing", "Silence timeout. Closing mic to protect credits.")
            log.info("credit guard: silence timeout")
        else:
            self.overlay.set_state("starting", "Starting voice session.")

    def _session_was_digitally_silent(self, session: Any) -> bool:
        """Whether the session recorded nothing but exact zeros.

        Not every session type is guaranteed to expose its buffer, and this is
        only ever used to choose between two messages, so anything unreadable
        answers False and leaves the existing wording in place.
        """
        getter = getattr(session, "captured_audio", None)
        if not callable(getter):
            return False
        # Checked rather than caught: a silent handler here would be one more
        # place a failure disappears, which is what test_failures_are_visible
        # exists to stop. Both session types return
        # (pcm, sample_rate, channels, heard_voice).
        captured = getter()
        if not isinstance(captured, tuple) or not captured:
            return False
        pcm = captured[0]
        if not isinstance(pcm, (bytes, bytearray, memoryview)):
            return False
        return is_digitally_silent(bytes(pcm))

    def _no_speech_message(self) -> str:
        """Say "the microphone gave us nothing" when that is what happened.

        macOS does not fail a capture whose permission was refused -- it hands
        over silence. The recording succeeds, every sample is zero, and the
        default message then tells the person they did not speak, which is both
        wrong and unactionable. Measured during the port: ten seconds of capture
        with speech playing aloud returned a peak amplitude of exactly 0.

        A working microphone in a silent room still delivers a noise floor, so
        all-zero samples mean no signal reached us at all.
        """
        if not mac_support.IS_MAC:
            return "No speech heard. Closing mic to protect credits."
        capture = self.safety_capture
        recorded = getattr(capture, "captured_audio", None)
        pcm = recorded() if callable(recorded) else b""
        if pcm and is_digitally_silent(pcm):
            log.warning(
                "the microphone returned only digital silence; macOS is probably refusing access"
            )
            return "The microphone sent no signal. Check Privacy & Security > Microphone."
        if mac_support.microphone_permission() == "denied":
            return "Microphone access is off. Turn Talk DAT! on in Privacy & Security."
        return "No speech heard. Closing mic to protect credits."

    def _field_probe(self, token: object) -> Any:
        saved = getattr(self, "_session_field", None)
        return saved[1] if saved is not None and saved[0] is token else None

    def _secure_take(self, token: object) -> bool:
        """X-604 (commandment 78): a take whose words must not be shown or kept.

        While the field read is still answering, the take counts as secure for
        anything that would put its words on screen or on disk.
        """
        probe = self._field_probe(token)
        return probe is not None and probe.secure_or_pending()

    def prepare_stable_dictation(self, token: object, text: str, config: dict[str, Any]) -> None:
        from .field_context import CONSOLE

        probe = self._field_probe(token)
        if probe is not None and (probe.secure_or_pending() or probe.result(0) == CONSOLE):
            return  # no model runs on a password, and a command is never rewritten
        with self.lock:
            formatter = getattr(self, "_progressive_formatter", None)
            if self.session_token is token and formatter is not None:
                formatter.request(text, config)

    def on_session_update(self, token: object, mode: str, text: str, is_final: bool) -> None:
        if not self.is_current(token):
            return
        state = "command" if mode == "command" else "listening"
        label = "Command" if mode == "command" else ("Captured" if is_final else "Hearing")
        if self._secure_take(token):
            # X-604: a password field. No preview, no caption, no crash draft.
            self.overlay.set_state(state, "Password field: your words are not shown.", "")
            return
        self.write_live_draft(mode, text, is_final)
        # X-32: the caption strip eats the same partial stream the pill
        # previews -- no second transcription, no extra latency.
        try:
            self.overlay.captions_update(text, is_final)
        except Exception:
            log.debug("caption update skipped", exc_info=True)
        self.overlay.set_state(state, f"{label}: {preview(text, 58)}", preview(text, 112))

    def _local_download_message(self, model: Any = None) -> str:
        """"Downloading local model" with no number, for 640 MB on a first run,
        is indistinguishable from a hang.

        Hugging Face's progress bar is switched off deliberately -- a frozen
        windowed build has no stderr and printing to it crashed the download --
        so the figure comes from the partial files it is already writing.
        """
        try:
            if model is None:
                from .local_stt import local_model_for_id
                from .stt_registry import selected_model_id, selected_provider_id

                model = local_model_for_id(
                    selected_model_id(self.config, selected_provider_id(self.config))
                )
            fetched, expected = local_download_progress_mb(model)
            label = getattr(model, "label", "local model")
        except Exception:
            log.debug("could not read model download progress", exc_info=True)
            return "Downloading local model. One-time setup."
        if expected <= 0:
            return f"Downloading {label}. One-time setup."
        if fetched <= 0:
            return f"Downloading {label} ({expected:.0f} MB). One-time setup."
        return (
            f"Downloading {label}: {fetched:.0f} of {expected:.0f} MB "
            f"({min(99, fetched / expected * 100):.0f}%)."
        )

    def on_session_audio(
        self,
        token: object,
        data: bytes,
        sample_rate: int,
        channels: int,
        heard_voice: bool,
    ) -> None:
        # X-50: a dead mic announces itself. Two seconds without a voiced
        # frame (Mayowa tightened it from four -- nobody says nothing for
        # two seconds after pressing talk) earns a falling chime and exactly
        # what is wrong. Any voiced frame resets the meter; one warning per
        # session, and the session keeps running in case the device wakes.
        if token is self.session_token:
            self._session_audio_seen = True
            if heard_voice:
                self._dead_mic_ms = 0
                self._dead_mic_token = token
            elif getattr(self, "_dead_mic_token", None) is token or getattr(self, "_dead_mic_token", None) is None:
                self._dead_mic_token = token
                frame_ms = int(len(data) / max(1, sample_rate * channels * 2) * 1000)
                self._dead_mic_ms = int(getattr(self, "_dead_mic_ms", 0) or 0) + frame_ms
                if self._dead_mic_ms >= 2000 and getattr(self, "_dead_mic_warned", None) is not token:
                    self._dead_mic_warned = token
                    with contextlib.suppress(Exception):
                        from .chimes import play_sound_named

                        play_sound_named("chime_down")
                    self.overlay.root.after(0, lambda: self.overlay.set_state(
                        "error",
                        "No sound is reaching the microphone.",
                        "Check your microphone, or open Mic Doctor in Settings > Dictation.",
                    ))
        with self.lock:
            capture = self.safety_capture if token is self.safety_capture_token else None
        if capture is None or capture.append(data, sample_rate, channels, heard_voice=heard_voice):
            return
        with self.lock:
            if token is not self.session_token or token is self.safety_capture_failure_token:
                return
            self.safety_capture_failure_token = token
            self.session_error_message = "Local protected recording stopped unexpectedly."
            session = self.session
        if session is not None:
            session.stop()
        self.overlay.set_state(
            "processing",
            "Local audio protection failed. Closing the microphone.",
            "Talk DAT! will still salvage the in-memory transcript and audio if possible.",
        )
        log.error("protected voice writer stopped during an active session")

    def on_session_error(self, token: object, error: str) -> None:
        if not self.is_current(token):
            return
        with self.lock:
            self.session_error_message = str(error or "Voice transcription failed.")
        provider_id = selected_provider_id(self.config)
        self.overlay.set_state(
            "processing",
            f"{provider_label(provider_id)} interrupted. Recovering captured audio.",
            preview(error, 112),
        )
        log.error("STT error provider=%s: %s", provider_id, error)

    def on_session_done(self, token: object, mode: str, raw_text: str) -> None:
        with self.lock:
            if self.session_token is not token:
                return
            # Claim the delivery destination at the STT-to-formatting boundary.
            # A guided surface may close while formatting or translation is
            # still running. Re-reading its global sink only at paste time would
            # turn that close into ordinary desktop auto-paste.
            guided_sink = getattr(self.overlay, "onboarding_test_sink", None)
            ramble_sink = getattr(self, "_ramble_workspace_sink", None) if mode == "ramble" else None
            self._guided_delivery_token = token if callable(guided_sink) else None
        # Some providers complete without first emitting a finalizing status.
        # Enter processing before any recovery or cleanup work so release always
        # hands directly from the live pill to the rainbow progress state.
        self.overlay.set_state("processing", "Finalizing captured speech.",
                               "" if self._secure_take(token) else preview(raw_text, 112))
        with self.lock:
            session = self.session
            capture = (
                getattr(self, "safety_capture", None)
                if token is getattr(self, "safety_capture_token", None)
                else None
            )
            error_message = self.session_error_message
            self.session = None
            if hasattr(self, "safety_capture"):
                self.safety_capture = None
            if hasattr(self, "safety_capture_token"):
                self.safety_capture_token = None
            if hasattr(self, "safety_capture_failure_token"):
                self.safety_capture_failure_token = None
            self.session_chime_token = None
            self.session_mode = "processing"
            self.session_control = "processing"
            self.session_error_message = ""

        self.release_activation_guards()
        self.overlay.set_level(0)
        # X-338, his order: the finish sound was premature -- it fired
        # here, at mic release, seconds before the words actually landed.
        # It now rides the paste: armed here, played by
        # play_landing_sound() the moment delivery succeeds.
        self._landing_sound_pending = True
        try:
            if capture is not None:
                capture.update(
                    status="processing",
                    raw_transcript=raw_text.strip(),
                    error=error_message,
                )
                capture.flush()
            self._session_audio_already_saved = bool(capture and capture.audio_bytes > 0)
            raw_text = self.recover_transcript_if_needed(session, mode, raw_text.strip())
            # Recovery can make a second provider/local-model request. Cancel or
            # Redo may install a new listening flight while that work is still
            # running, so the recovered words belong only to the captured old
            # flight. Stop before touching the new draft, Pill, or mode handler.
            if not self.is_current(token):
                self.finalize_safety_capture(
                    capture,
                    status="cancelled",
                    raw_transcript=raw_text,
                    error=(
                        "Result discarded after Cancel or Redo. "
                        "Protected audio remains available in History."
                    ),
                )
                log.info("session done: stale result discarded after transcript recovery")
                return
            if capture is not None:
                capture.update(raw_transcript=raw_text, status="processing")
            self.write_live_draft(mode, raw_text, True)
            if error_message and not raw_text:
                self.finalize_safety_capture(
                    capture,
                    status="transcription_failed",
                    error=error_message,
                )
                provider_id = selected_provider_id(self.config)
                self.overlay.set_state(
                    "error",
                    f"{provider_label(provider_id)} error: {preview(error_message, 82)}",
                    "Captured audio was saved locally. Check the provider and retry from History.",
                )
                log.info("session done: provider error after recovery")
                return
            if not raw_text:
                silent = mac_support.IS_MAC and self._session_was_digitally_silent(session)
                self.finalize_safety_capture(
                    capture,
                    status="no_transcript",
                    error="No transcript returned. The protected audio remains available in History.",
                )
                if silent:
                    # Every sample exactly zero. A working microphone in a silent
                    # room still delivers a noise floor, so this is not a quiet
                    # person -- macOS is refusing the microphone and answering
                    # with silence instead of an error. Verified here: 179,200
                    # samples captured with speech playing aloud, peak 0.
                    log.warning(
                        "captured audio was digitally silent; macOS is refusing microphone access"
                    )
                    self.overlay.set_state(
                        "error",
                        "The microphone sent no signal at all.",
                        "Turn Talk DAT! on under Privacy & Security > Microphone, then try again.",
                    )
                else:
                    self.overlay.set_state("idle", "No speech captured. Ready again.", "")
                log.info("session done: no speech captured silent=%s", silent)
                return

            if mode == "ramble":
                # X-40: an hour of talk is a DOCUMENT, not a paste.
                if callable(ramble_sink):
                    accepted = ramble_sink(token, raw_text)
                    self.finalize_safety_capture(
                        capture, status="captured" if accepted else "cancelled",
                        raw_transcript=raw_text,
                        error="" if accepted else "The Ramble workspace no longer owns this recording.",
                    )
                else:
                    self.finish_ramble(raw_text)
                return
            if mode == "captions":
                # X-69: captions are a DISPLAY, never a paste. The partials
                # already painted the strip live; the final text goes nowhere
                # else by design.
                self.overlay.set_state("idle", "Captions stopped.", "")
                return
            if mode == "fixthat":
                # X-42: this transcript is the INSTRUCTION, not content --
                # nothing pastes here; the rewrite handles delivery.
                self.apply_fix_that(raw_text, delivery_token=token)
                return
            if mode == "command":
                self.handle_command(raw_text, delivery_token=token)
                self.finalize_safety_capture(
                    capture,
                    status="command_complete",
                    raw_transcript=raw_text,
                    final_text=self.last_transcript,
                    error=error_message,
                )
            else:
                result = self.handle_dictation(
                    raw_text,
                    delivery_token=token,
                    guided_sink=guided_sink,
                )
                final_text = (
                    str(result.get("text") or "")
                    if isinstance(result, dict)
                    else str(getattr(self, "last_transcript", "") or raw_text)
                )
                delivery = result.get("delivery") if isinstance(result, dict) else None
                if capture is not None and isinstance(result, dict):
                    capture.update(timings=result.get("timings"), format_route=result.get("format_route"))
                delivered = bool(delivery.get("success")) if isinstance(delivery, dict) else bool(final_text)
                if delivered and final_text:
                    # X-96: the moment the funnel goes from "installed" to
                    # "it worked for this person". First time only, plus the
                    # one day-7 report a week later; nothing else after that.
                    try:
                        from .activation_metrics import record_first_dictation
                        from .official_build import activation_api_base

                        record_first_dictation(self.config, save_config, activation_api_base(self.config))
                    except Exception:
                        log.debug("activation stamp skipped", exc_info=True)
                self.finalize_safety_capture(
                    capture,
                    status="delivered" if delivered else "delivery_failed",
                    raw_transcript=raw_text,
                    final_text=final_text,
                    error=error_message,
                    delivery=delivery if isinstance(delivery, dict) else None,
                )
        except Exception as exc:
            log.exception("session completion failed")
            self.finalize_safety_capture(
                capture,
                status="processing_failed",
                raw_transcript=raw_text,
                error=str(exc),
            )
            # A cancelled formatter can finish after Cancel/Redo has already
            # opened a new microphone. Preserve the old protected-audio record,
            # but never paint its error over a newer live session.
            if self.is_current(token):
                self.overlay.set_state(
                    "error",
                    f"Could not finish dictation: {preview(str(exc), 82)}",
                    "Your recording was kept. Open History to recover the words.",
                )
        finally:
            self._session_audio_already_saved = False
            with self.lock:
                if self._guided_delivery_token is token:
                    self._guided_delivery_token = None
                if self.session_token is token:
                    formatter = getattr(self, "_progressive_formatter", None)
                    if formatter is not None:
                        formatter.reset()
                    self.session_token = None
                    self.session_mode = "idle"
                    self.session_control = "idle"

    def recover_transcript_if_needed(self, session: Any, mode: str, raw_text: str) -> str:
        audio = self.session_audio(session)
        if audio is None:
            return raw_text
        pcm16, sample_rate, channels, heard_voice = audio
        transport_degraded = self.session_transport_degraded(session)
        reason = "degraded" if transport_degraded else ("ok" if raw_text else "empty")
        if not getattr(self, "_session_audio_already_saved", False):
            self.save_session_audio(pcm16, sample_rate, channels, mode=mode, reason=reason)
        audio_ms = pcm_duration_ms(len(pcm16), sample_rate, channels)
        has_signal = heard_voice or likely_has_input_signal(pcm16)
        # A transport blip mid-session used to force a full local
        # re-transcription even when the live transcript was COMPLETE -- the
        # founder watched 27s of audio burn 14s of CPU only for the comparator
        # to keep the cloud text it already had, under a toast claiming the
        # words were local. Healthy live text wins outright: one word per
        # three seconds of audio is far below any real speech rate, so text
        # denser than that with a degraded-flag is a finished transcript
        # whose socket died on the way out, not a truncated one.
        if raw_text and transport_degraded:
            live_words = len(raw_text.split())
            plausible_minimum = max(1, int(audio_ms / 3000))
            if live_words >= plausible_minimum:
                log.info(
                    "degraded transport but live transcript is healthy: words=%s audio_ms=%.0f -- keeping it",
                    live_words,
                    audio_ms,
                )
                return raw_text
        retry_needed = not raw_text or transport_degraded
        if not retry_needed:
            # A clean remote dictation resets the failure streak, and X-516
            # makes it lower the sticky local flag too. That flag used to be
            # lowered by a probe asking OUR service whether it was healthy,
            # which said nothing about whether somebody else's provider had
            # recovered. Their own success is the honest signal.
            self._cloud_failure_streak = 0
            self._auto_local_sticky = False
        if not retry_needed or not has_signal:
            if retry_needed:
                log.info(
                    "capture retry skipped: no input signal heard_voice=%s rms_signal=%s duration_ms=%.0f bytes=%s",
                    heard_voice,
                    has_signal,
                    audio_ms,
                    len(pcm16),
                )
            return raw_text

        dictation = self.config.get("dictation", {})
        if not bool(dictation.get("retry_failed_capture", True)):
            log.info("capture retry skipped: retry_failed_capture disabled")
            return raw_text
        if audio_ms < 250:
            log.info("capture retry skipped: audio too short duration_ms=%.0f bytes=%s", audio_ms, len(pcm16))
            return raw_text

        self.overlay.set_state(
            "processing",
            "Recovering captured audio.",
            "Retrying once from the local safety buffer after an interrupted stream."
            if transport_degraded
            else "Retrying once from the local safety buffer.",
        )
        # X-72 failure doctrine (his words, replacing the retry-twice
        # design): the FIRST cloud failure never touches the local model --
        # no surprise CPU freeze. The pill flashes red with a quiet double
        # beep so the person KNOWS, and if their very next attempt fails
        # too, THEN the local rescue takes over automatically.
        provider_id = selected_provider_id(self.config)
        rescue = local_fallback.rescue_model(self.config, provider_id)
        # X-516: there is no metered bucket of ours to be empty any more.
        # A remote failure is a remote failure, and the say-it-again doctrine
        # below is the right response to all of them.
        if rescue is not None:
            now_mono = time.monotonic()
            last_failure = float(getattr(self, "_cloud_failure_at", 0.0))
            streak = (
                int(getattr(self, "_cloud_failure_streak", 0))
                if now_mono - last_failure < CLOUD_FAILURE_MEMORY_SECONDS
                else 0
            )
            self._cloud_failure_streak = streak + 1
            self._cloud_failure_at = now_mono
            # X-338, his policy: auto is CLOUD. "Try cloud again until
            # cloud fails, like, too many times" -- three consecutive
            # misses inside the streak window, then the PC takes over and
            # STAYS in charge until cloud proves healthy again.
            if bool(getattr(self, "_auto_local_sticky", False)):
                pass  # already stuck local; rescue below runs immediately
            elif self._cloud_failure_streak < 3:
                def _beep() -> None:
                    with contextlib.suppress(Exception):
                        import winsound

                        winsound.Beep(660, 110)
                        winsound.Beep(500, 110)

                threading.Thread(target=_beep, name="cloud-fail-beep", daemon=True).start()
                self.overlay.set_state(
                    "error",
                    "Cloud dropped this one.",
                    f"Say it again. After three misses, {platform_copy.THIS_COMPUTER} takes over automatically.",
                )
                log.info(
                    "cloud provider=%s failed; signaled (streak=%d), no local rescue yet",
                    provider_id, self._cloud_failure_streak,
                )
                return raw_text

        retry_config = self.config
        retry_provider = ""
        if rescue is not None:
            retry_config = local_fallback.config_using(self.config, rescue)
            retry_provider = "local"
            self._note_cloud_fallback()
            # X-338/X-516: the switch to local is STICKY. It stays until a
            # remote dictation succeeds again or the person picks a route.
            #
            # X-531: it used to raise a permanent badge above the pill too.
            # That went; the rescue is announced by the status line and the
            # toast below, which is what X-59.B asked for and what the outage
            # test asserts.
            #
            # X-532: it also used to be gated on route_mode == "auto". X-480
            # deleted that mode, so the stickiness stopped engaging for
            # anybody -- the rescue still saved each dictation, but the
            # promise not to make you watch a fourth failure quietly stopped
            # being kept. Reaching here already means a remote route failed
            # and the machine caught it, which is the whole condition.
            self._auto_local_sticky = True
            self.overlay.set_state(
                "processing",
                f"Transcribing on {platform_copy.THIS_COMPUTER} instead.",
                local_fallback.describe(rescue),
            )
            # X-59.B: the rescue must be LOUD. The founder ran a week on
            # silent local fallbacks and read the degradation as the product
            # -- a transient state line is not enough when the words still
            # arrive and nothing looks wrong.
            try:
                self.overlay.show_toast(
                    f"Cloud was unavailable. This dictation ran on {platform_copy.THIS_COMPUTER} instead."
                )
            except Exception:
                log.debug("fallback toast failed", exc_info=True)
            log.info("cloud provider=%s failed; rescuing locally with %s", provider_id, rescue.id)
        try:
            recovered = transcribe_pcm(
                retry_config, pcm16, sample_rate, channels, provider_id=retry_provider
            ).strip()
        except Exception as exc:
            log.warning("capture retry failed: %s", exc, exc_info=True)
            return raw_text
        if not recovered:
            log.info("capture retry returned no transcript")
            return raw_text
        if raw_text and len(recovered.split()) < len(raw_text.split()):
            log.info(
                "capture retry kept live transcript: recovered_words=%s live_words=%s",
                len(recovered.split()),
                len(raw_text.split()),
            )
            return raw_text
        log.info("capture retry recovered transcript chars=%s", len(recovered))
        self.overlay.set_state("processing", "Recovered captured audio.", preview(recovered, 112))
        return recovered

    def session_transport_degraded(self, session: Any) -> bool:
        if session is None:
            return False
        try:
            return bool(getattr(session, "transport_degraded", False))
        except Exception:
            log.debug("session transport health was unavailable", exc_info=True)
            return False

    def session_audio(self, session: Any) -> tuple[bytes, int, int, bool] | None:
        getter = getattr(session, "captured_audio", None)
        if not callable(getter):
            return None
        try:
            pcm16, sample_rate, channels, heard_voice = getter()
        except Exception:
            log.debug("session did not expose captured audio", exc_info=True)
            return None
        if not pcm16:
            return None
        return bytes(pcm16), int(sample_rate), int(channels), bool(heard_voice)

    def save_session_audio(self, pcm16: bytes, sample_rate: int, channels: int, *, mode: str, reason: str) -> None:
        dictation = self.config.get("dictation", {})
        try:
            limit = max(5, int(dictation.get("safety_recording_limit", 5)))
        except (TypeError, ValueError):
            limit = 5
        try:
            path = save_safety_recording(
                pcm16,
                sample_rate=sample_rate,
                channels=channels,
                reason=f"{mode}-{reason}",
                limit=limit,
            )
        except OSError as exc:
            log.warning("could not save safety recording: %s", exc)
            return
        if path:
            log.info("saved safety recording: %s", path)

    def finalize_safety_capture(
        self,
        capture: AudioSafetyCapture | None,
        *,
        status: str,
        raw_transcript: str = "",
        final_text: str = "",
        error: str = "",
        delivery: dict[str, Any] | None = None,
    ) -> None:
        if capture is None:
            return
        try:
            capture.finalize(
                status=status,
                raw_transcript=raw_transcript,
                final_text=final_text,
                error=error,
                delivery=delivery,
            )
            log.info(
                "protected voice session finalized: id=%s status=%s bytes=%s",
                capture.session_id,
                status,
                capture.audio_bytes,
            )
        except Exception:
            log.exception("could not finalize protected voice session id=%s", capture.session_id)

    def _typical_model_format_ms(self) -> float | None:
        """The median recent cost of the model's formatting, or None if unknown.

        Median rather than mean: one 8-second stall while a laptop wakes its
        network card should not convince the app that the pipeline is slow for
        the next five dictations.
        """
        samples = sorted(self._format_samples())
        if not samples:
            return None
        return samples[len(samples) // 2]

    def _format_samples(self) -> deque[float]:
        """The measurement window, created on demand.

        Built lazily rather than assumed, because an app assembled without
        running the full constructor -- which is how the session tests build
        one -- would otherwise raise mid-dictation. A missing measurement must
        cost a routing decision, never somebody's words.
        """
        samples = getattr(self, "_model_format_ms", None)
        if samples is None:
            samples = deque(maxlen=5)
            self._model_format_ms = samples
        return samples

    def _note_model_format_ms(self, elapsed_ms: float) -> None:
        """Record what the model's formatting cost, from either delivery path."""
        self._format_samples().append(float(elapsed_ms))

    def _refine_after_paste(
        self,
        raw_text: str,
        config: dict[str, Any],
        *,
        pasted_text: str,
        paste_window: int,
        pasted_at: float,
        sent_enter: bool,
        paste_succeeded: bool,
        paste_method: str = "",
        paste_input_generation: int = 0,
        delivery_token: object = _DYNAMIC_GUIDED_SINK,
    ) -> None:
        """Run the model's formatting after the text is already on screen, and
        correct in place if it is still safe to do so.

        Every refusal path here leaves the locally formatted text alone, which
        is the text the product delivered before this existed. The failure mode
        being guarded against is worse than a missed improvement: the words are
        already in someone's document, possibly already typed over, and taking
        out the wrong characters destroys work that was never ours.
        """

        # A successful Ctrl+Z followed by an indeterminate Ctrl+V can remove the
        # entire delivered dictation. No window, caret, or clipboard probe can
        # prove an arbitrary editor's document state after that partial chord.
        # Keep this compatibility entry point inert and deliver the fully
        # formatted result once instead. The setting remains readable so older
        # configs migrate without loss, but no automatic post-paste edit runs.
        log.info("post-paste refinement skipped: safe single delivery is active")
        return

    def handle_dictation(
        self,
        raw_text: str,
        *,
        delivery_token: object = _DYNAMIC_GUIDED_SINK,
        guided_sink: object = _DYNAMIC_GUIDED_SINK,
    ) -> dict[str, Any]:
        explicit_flight = delivery_token is not _DYNAMIC_GUIDED_SINK

        def flight_is_current() -> bool:
            return not explicit_flight or self.is_current(delivery_token)

        def cancelled_result(method: str = "cancelled_before_delivery") -> dict[str, Any]:
            return {
                "text": "",
                "original": raw_text,
                "send_enter": False,
                "delivery": {
                    "success": False,
                    "requested_mode": "cancelled",
                    "method": method,
                    "attempts": (),
                    "fallback_used": False,
                },
                "translation": None,
                "translation_error": "",
            }

        if not flight_is_current():
            return cancelled_result()

        reserved_sink = (
            getattr(self.overlay, "onboarding_test_sink", None)
            if guided_sink is _DYNAMIC_GUIDED_SINK
            else guided_sink
        )
        guided_delivery_reserved = callable(reserved_sink)
        post_stt_started = time.perf_counter()
        from .field_context import CONSOLE, PASSWORD, SINGLE_LINE

        saved_field = getattr(self, "_session_field", None)
        field_probe = (saved_field[1] if explicit_flight and saved_field is not None
                       and saved_field[0] is delivery_token else None)
        field = field_probe.result() if field_probe is not None else ""
        secure_take = field == PASSWORD
        self.overlay.set_state("processing", "Formatting transcript.",
                               "" if secure_take else preview(raw_text, 112))
        saved_profile = getattr(self, "_session_profile", None)
        if explicit_flight and saved_profile is not None and saved_profile[0] is delivery_token:
            profile = saved_profile[1]
        else:
            profile = active_profile(self.config)
        effective_config = apply_profile(self.config, profile)
        if field in {PASSWORD, CONSOLE, SINGLE_LINE}:
            # Only these change the text, so only these change the config the
            # progressive formatter keyed its prepared result on.
            effective_config = {**effective_config, "_field": field}
        translate_ok = field not in {PASSWORD, CONSOLE}
        # Safe single delivery: wait for the final formatting result and insert
        # it exactly once. The older speculative route pasted a local draft and
        # later used Ctrl+Z/Ctrl+V to replace it. If Ctrl+Z committed but Ctrl+V
        # failed, the target document could be left empty with no reliable way
        # to inspect or repair an arbitrary editor.
        speculative = False
        format_started = time.perf_counter()
        screen_names = list(getattr(self, "_screen_names", []) or [])
        if screen_names:
            effective_config = {**effective_config, "_screen_names": screen_names}
        formatter = getattr(self, "_progressive_formatter", None)
        prepared = formatter.take(raw_text, effective_config) if formatter is not None else None
        if prepared is not None:
            from .text_pipeline import complete_prepared_dictation
            processed = complete_prepared_dictation(prepared, effective_config, started=format_started)
        else:
            processed = process_dictation(raw_text, effective_config, local_only=speculative)
        format_ms = int(round((time.perf_counter() - format_started) * 1000.0))
        if not flight_is_current():
            return cancelled_result()
        if not speculative:
            # Keep the recent formatting cost. The journal now separately names
            # rules, accepted models, fallback and work prepared during capture.
            self._note_model_format_ms(float(format_ms))
        translation_receipt: dict[str, Any] | None = None
        translation_error = ""
        skip_translation = False
        if processed.text and translate_ok and auto_translation_enabled(effective_config):
            # X-30: bilingual auto-detect, opt-in and conservative. Its ONLY
            # power is to skip the translation when the utterance is already
            # decisively in the target language -- flip to Spanish mid-flow
            # with EN->ES auto-translate on and your Spanish is delivered
            # untouched instead of translated twice. Off by default; short or
            # ambiguous utterances keep the configured behaviour.
            try:
                from .language_detect import should_skip_translation
                from .translation import translation_settings as _tsettings

                skip_translation = should_skip_translation(
                    processed.text,
                    source=resolve_source_language(effective_config).code,
                    target=resolve_target_language(effective_config).code,
                    enabled=bool(_tsettings(effective_config).get("bilingual_auto_detect", False)),
                )
            except Exception:
                skip_translation = False
            if skip_translation:
                log.info("bilingual auto-detect: already in the target language; delivered untouched")
        if processed.text and translate_ok and auto_translation_enabled(effective_config) and not skip_translation:
            self.overlay.set_state("processing", "Translating.", preview(processed.text, 112))
            try:
                translated = translate_text(processed.text, effective_config)
                processed.text = translated.text
                translation_receipt = translated.as_dict()
            except TranslationError as exc:
                # X-516: there is no second engine to rescue this. Translation
                # runs on this machine or not at all, so a setup-shaped
                # failure keeps its honest local error, which already names
                # the one-click model download. The managed retry that used to
                # live here was the last path that sent a person's words to
                # our servers.
                translation_error = str(exc)
                log.warning("automatic local translation skipped code=%s message=%s", exc.code, exc)
        if not flight_is_current():
            return cancelled_result()

        if not processed.text and not processed.send_enter:
            if not secure_take:
                self.last_original = processed.original
                self.last_transcript = processed.text
                self.last_diff = unified_diff(processed.original, processed.text)
            log.info(
                "dictation processed: raw_chars=%s final_chars=0 format_ms=%s paste_ms=0 post_stt_ms=%s",
                len(raw_text),
                format_ms,
                int(round((time.perf_counter() - post_stt_started) * 1000.0)),
            )
            self.overlay.set_state("idle", "Nothing to paste. Ready again.", "")
            return {"text": "", "delivery": {"success": False, "method": "empty"}}

        delivery: dict[str, object]
        paste_started = time.perf_counter()
        paste_input_generation = 0
        delivery_cancelled = not flight_is_current()
        current_sink = getattr(self.overlay, "onboarding_test_sink", None)
        guided_sink_still_owned = guided_delivery_reserved and current_sink is reserved_sink
        if delivery_cancelled:
            receipt = None
            delivery = {
                "success": False,
                "requested_mode": "cancelled",
                "method": "cancelled_before_delivery",
                "attempts": (),
                "fallback_used": False,
            }
        elif guided_delivery_reserved and not guided_sink_still_owned:
            # The guided surface closed or yielded ownership after recording.
            # The result is intentionally discarded instead of falling through
            # to whichever application happens to be focused now.
            receipt = None
            delivery = {
                "success": False,
                "requested_mode": "onboarding_test",
                "method": "guided_test_closed",
                "attempts": ("guided_test",),
                "fallback_used": False,
            }
        elif guided_sink_still_owned:
            guided_delivery_finished = threading.Event()
            guided_delivery_result = {"delivered": False}

            def deliver_to_guided_surface(
                text: str = processed.text,
                sink: object = reserved_sink,
            ) -> None:
                try:
                    # ``after(0)`` crosses back to Tk. Check both the surface
                    # identity and this exact delivery flight while holding the
                    # short-lived claim. Reusing the same page/sink for Redo is
                    # therefore not enough to admit an older queued result.
                    with self.lock:
                        flight_owned = (
                            not explicit_flight
                            or (
                                self.session_token is delivery_token
                                and self._guided_delivery_token is delivery_token
                            )
                        )
                        sink_owned = getattr(self.overlay, "onboarding_test_sink", None) is sink
                        if flight_owned and sink_owned and callable(sink):
                            if explicit_flight:
                                self._guided_delivery_token = None
                            sink(text)
                            guided_delivery_result["delivered"] = True
                except Exception:
                    log.exception("guided setup result could not be delivered")
                finally:
                    guided_delivery_finished.set()

            if threading.current_thread() is threading.main_thread():
                deliver_to_guided_surface()
            else:
                try:
                    self.overlay.root.after(0, deliver_to_guided_surface)
                except Exception:
                    log.exception("guided setup result could not be scheduled")
                    guided_delivery_finished.set()
                if not guided_delivery_finished.wait(2.0):
                    # Invalidate the queued callback. If Tk eventually receives
                    # it, the per-flight claim above refuses the stale result.
                    with self.lock:
                        if explicit_flight and self._guided_delivery_token is delivery_token:
                            self._guided_delivery_token = None

            receipt = None
            guided_delivered = bool(guided_delivery_result["delivered"])
            delivery = {
                "success": guided_delivered,
                "requested_mode": "onboarding_test",
                "method": "onboarding_test" if guided_delivered else "guided_test_closed",
                "attempts": ("guided_test",),
                "fallback_used": False,
            }
        elif self.config.get("dictation", {}).get("auto_paste", True):
            # Read only at insertion, after the model/translation has finished.
            # Nearby document text never becomes model input or journal data.
            # Recovery-only test/tool app instances have no native reader.
            from .caret_context import apply_caret_context, join_at_caret, usable_context

            caret_reader = getattr(self, "_caret_context_reader", None)
            caret_started = time.perf_counter()
            caret = None
            if (callable(caret_reader) and not secure_take
                    and effective_config.get("cleanup", {}).get("smart_format", True)
                    and self.config.get("dictation", {}).get("paste_mode", "auto") != "copy_only"):
                try:
                    caret = caret_reader()
                except Exception:
                    caret = None
            if usable_context(caret):
                before_caret = processed.text
                processed.text = apply_caret_context(processed.text, raw_text, caret, effective_config)
                processed.text = join_at_caret(processed.text, caret)
                if processed.text != before_caret:
                    from .format_journal import record_formatting

                    record_formatting(
                        effective_config, raw=raw_text, final=processed.text,
                        stage="insertion", route="caret",
                        elapsed_ms=(time.perf_counter() - caret_started) * 1000.0,
                    )
            paste_options: dict[str, Any] = {
                "send_enter": processed.send_enter,
                "restore_clipboard": bool(
                    self.config.get("dictation", {}).get("restore_clipboard_after_paste", True)
                ),
                "smart_leading_space": bool(
                    self.config.get("dictation", {}).get("smart_leading_space", True)
                ) and not usable_context(caret),
                "paste_mode": str(self.config.get("dictation", {}).get("paste_mode", "auto")),
                "typing_interval_ms": config_int(
                    self.config.get("dictation", {}).get("typing_interval_ms"), 2
                ),
                "clipboard_paste_delay_ms": config_int(
                    self.config.get("dictation", {}).get("clipboard_paste_delay_ms"), 10
                ),
            }
            from .caret_context import ends_with_spoken_mark

            paste_options["keep_final_period"] = ends_with_spoken_mark(raw_text)
            if secure_take:
                # A password never touches the clipboard, where clipboard
                # history, the cloud clipboard and clipboard managers keep
                # copies: it is typed, with no leading space.
                paste_options.update(paste_mode="type", smart_leading_space=False, restore_clipboard=False)
            if explicit_flight:
                # This predicate is checked inside the paste implementation
                # immediately before Ctrl+V, Shift+Insert, Enter, and every
                # direct-typed character. A pre-paste check alone leaves a race
                # during clipboard waits and long direct-typing routes.
                paste_options["can_deliver"] = flight_is_current
            receipt = paste_text_with_receipt(processed.text, **paste_options)
            delivery = receipt.as_dict()
            if receipt.success:
                paste_input_generation = foreground_input_generation()
        else:
            receipt = None
            delivery = {
                "success": True,
                "requested_mode": "disabled",
                "method": "local_capture",
                "attempts": (),
                "fallback_used": False,
            }
        delivery_cancelled = delivery_cancelled or not flight_is_current()
        if delivery_cancelled:
            return cancelled_result()
        if receipt is not None and receipt.method == "cancelled":
            # The paste layer failed closed because its delivery authorization
            # changed (or could not be verified). Do not turn that refusal into
            # a clipboard fallback that leaks the same stale result.
            return cancelled_result("cancelled_during_delivery")
        if delivery.get("method") == "guided_test_closed":
            if flight_is_current():
                self.overlay.set_state("idle", "Setup test closed. Nothing was typed.", "")
            return {
                "text": "",
                "original": raw_text,
                "send_enter": False,
                "delivery": delivery,
                "translation": translation_receipt,
                "translation_error": translation_error,
            }
        recovery_copy = False
        if receipt is not None and receipt.method == "clipboard_commit_unknown":
            # The paste chord may already have committed. The paste layer keeps
            # the complete result on the clipboard, so never send a second
            # insertion or overwrite it with a redundant recovery transaction.
            recovery_copy = True
            delivery = {
                "success": True,
                "requested_mode": receipt.requested_mode,
                "method": "copy_only",
                "attempts": (*receipt.attempts, "commit_unknown_kept_on_clipboard"),
                "fallback_used": True,
            }
        elif (
            receipt is not None
            and not receipt.success
            and receipt.method != "protected_rich_clipboard"
            and not secure_take
        ):
            recovery_options: dict[str, Any] = {"paste_mode": "copy_only"}
            if explicit_flight:
                recovery_options["can_deliver"] = flight_is_current
            recovery_receipt = paste_text_with_receipt(processed.text, **recovery_options)
            if recovery_receipt.method == "cancelled" or not flight_is_current():
                return cancelled_result("cancelled_during_recovery_copy")
            recovery_copy = recovery_receipt.success
            if recovery_copy:
                delivery = {
                    "success": True,
                    "requested_mode": receipt.requested_mode,
                    "method": "copy_only",
                    "attempts": (*receipt.attempts, "final_copy"),
                    "fallback_used": True,
                }
        result = {
            "text": processed.text,
            "original": processed.original,
            "send_enter": processed.send_enter,
            "delivery": delivery,
            "translation": translation_receipt,
            "translation_error": translation_error,
        }
        delivered_at = time.perf_counter()
        released_at = getattr(self, "_trigger_released_at", None)
        result["format_route"] = getattr(processed, "route", "unknown")
        result["timings"] = {
            "format_ms": format_ms,
            "paste_ms": round((delivered_at - paste_started) * 1000, 1),
            "post_stt_ms": round((delivered_at - post_stt_started) * 1000, 1),
            "release_to_delivery_ms": round((delivered_at - released_at) * 1000, 1) if released_at is not None else None,
        }
        # A cancel-and-restart can install a new session while the previous
        # formatter is returning. The old flight may have delivered already,
        # but it must never overwrite the new flight's transcript model or UI.
        if not flight_is_current():
            return result
        # X-338: the finish chime rides the LANDING -- every delivery shape
        # (paste, commit-unknown clipboard, recovery copy, capture-only)
        # resolves into this one dict, so this is the single honest moment.
        if delivery.get("success"):
            self.play_landing_sound()
        if not secure_take:
            self.last_original = processed.original
            self.last_transcript = processed.text
            self.last_diff = unified_diff(processed.original, processed.text)
            # X-137: the raw words behind the last result, kept for the finish
            # chooser (both onboarding's and the day-two prompt's A/B preview).
            self.last_raw_transcript = raw_text
        paste_ms = int(round((time.perf_counter() - paste_started) * 1000.0))
        if speculative:
            self._refine_after_paste(
                raw_text,
                effective_config,
                pasted_text=processed.text,
                paste_window=foreground_window_id(),
                pasted_at=time.monotonic(),
                sent_enter=bool(processed.send_enter),
                paste_succeeded=bool(delivery.get("success")),
                paste_method=str(delivery.get("method") or ""),
                paste_input_generation=paste_input_generation,
                delivery_token=delivery_token,
            )
        log.info(
            "dictation processed: raw_chars=%s final_chars=%s format_ms=%s paste_ms=%s post_stt_ms=%s delivery=%s fallback=%s route=%s release_to_delivery_ms=%s",
            len(raw_text),
            len(processed.text),
            format_ms,
            paste_ms,
            int(round((time.perf_counter() - post_stt_started) * 1000.0)),
            delivery.get("method"),
            delivery.get("fallback_used"),
            result["format_route"],
            result["timings"]["release_to_delivery_ms"],
        )

        # X-137, "at least two distinct prompts": the finish decision comes
        # back ONCE more after onboarding, at the third real dictation, with
        # the person's own words as the example. One-shot, stamped, never
        # again.
        if not guided_delivery_reserved and delivery.get("success") and not secure_take:
            try:
                onboarding_cfg = self.config.setdefault("onboarding", {})
                if not onboarding_cfg.get("finish_prompt_2_done"):
                    count = int(onboarding_cfg.get("real_dictations", 0)) + 1
                    onboarding_cfg["real_dictations"] = count
                    if count >= 3:
                        onboarding_cfg["finish_prompt_2_done"] = True
                        raw_for_prompt = raw_text
                        self.format_both_finishes(
                            raw_for_prompt,
                            lambda chill, execu: self.overlay.open_finish_chooser(chill, execu),
                        )
                    save_config(self.config)
            except Exception:
                log.debug("finish re-prompt skipped", exc_info=True)

        if not secure_take and self.config.get("privacy", {}).get("save_history", True):
            self.add_history(
                {
                    "type": "dictation",
                    "original": processed.original,
                    "text": processed.text,
                    "send_enter": processed.send_enter,
                    "delivery": delivery,
                    "translation": translation_receipt,
                    "translation_error": translation_error,
                    "created_at": time.time(),
                }
            )

        if not flight_is_current():
            return result
        if secure_take:
            self.overlay.set_state(
                "captured" if delivery.get("success") else "error",
                "Password field: typed as you said it. Nothing was kept."
                if delivery.get("success")
                else "Could not type into the password field. Nothing was kept.",
                "",
            )
            return result
        if getattr(processed, "held_enter", False) and delivery.get("success"):
            from .platform_copy import ENTER_KEY

            self.overlay.set_state("captured", f"Typed into the terminal. Press {ENTER_KEY} to run it.", "")
            return result
        # X-465: a local-only install has no cloud to quietly rescue a
        # formatter that could not run, so the reason is said out loud once.
        # The words still arrived; what is being reported is WHICH formatter
        # wrote them, which is the difference between Executive and rules.
        local_notice = take_local_finish_notice()
        if local_notice:
            self.overlay.set_state(
                "error",
                "Your text was formatted by the built-in rules, not the model.",
                local_finish_advice(local_notice),
            )
        elif translation_error:
            self.overlay.set_state(
                "error",
                "Translation unavailable; the original text was kept safely.",
                preview(translation_error, 112),
            )
        elif guided_sink_still_owned:
            self.overlay.set_state("captured", "Setup test complete. Mic off.", preview(processed.text, 112))
        elif receipt is None:
            self.overlay.set_state("captured", "Captured locally. Auto paste is off.", preview(processed.text, 112))
        elif receipt.success:
            self.overlay.set_state("captured", f"{receipt.visible_label()}. Mic off.", preview(processed.text, 112))
        elif receipt.method == "protected_rich_clipboard":
            self.overlay.set_state(
                "captured",
                "Rich clipboard preserved. Transcript kept in History for Paste Last.",
                preview(processed.text, 112),
            )
        else:
            state = "captured" if recovery_copy else "error"
            message = (
                "Insertion unavailable. Copied for manual paste. Mic off."
                if recovery_copy
                else "Insertion and clipboard unavailable. Transcript kept for retry. Mic off."
            )
            self.overlay.set_state(
                state,
                message,
                preview(processed.text, 112)
                if recovery_copy
                else "Click where the text should go, then use Paste last transcript in the Pill menu.",
            )
        return result

    def handle_command(
        self,
        command: str,
        *,
        delivery_token: object = _DYNAMIC_GUIDED_SINK,
    ) -> None:
        claim = self._reserve_deferred_delivery(delivery_token)
        if claim is None:
            return
        target_window = int(getattr(self, "_command_window", 0) or 0)
        target_focus_window = int(getattr(self, "_command_focus_window", 0) or 0)
        target_edit_target = tuple(getattr(self, "_command_edit_target", ()) or ())
        origin_input_generation = int(getattr(self, "_command_input_generation", 0) or 0)
        selected = str(getattr(self, "_command_selection", "") or "").strip()
        previous_clipboard = getattr(self, "_command_clipboard", "")
        self._command_window = 0
        self._command_focus_window = 0
        self._command_edit_target = ()
        self._command_input_generation = 0
        self._command_selection = ""
        self._command_clipboard = ""
        try:
            self.overlay.set_state("processing", f"Running command: {preview(command, 72)}")
            automatic_target_proven = bool(
                selected
                and target_window
                and target_focus_window
                and target_edit_target
                and foreground_window_id() == target_window
                and foreground_focus_window_id() == target_focus_window
                and foreground_edit_target_signature() == target_edit_target
            )
            if selected and automatic_target_proven:
                verified_selection, _validation_clipboard = copy_selected_text()
                if verified_selection.strip() != selected:
                    automatic_target_proven = False
                    if verified_selection:
                        restore_clipboard_if_unchanged(
                            verified_selection,
                            previous_clipboard,
                        )
            elif selected:
                restore_clipboard_if_unchanged(selected, previous_clipboard)
            input_generation = foreground_input_generation()
            log.debug(
                "command target revalidated origin_input=%s delivery_input=%s",
                origin_input_generation,
                input_generation,
            )

            def delivery_owner_is_current() -> bool:
                return self._deferred_delivery_is_current(claim)

            def automatic_delivery_is_current() -> bool:
                return (
                    automatic_target_proven
                    and delivery_owner_is_current()
                    and bool(target_window)
                    and foreground_window_id() == target_window
                    and bool(target_focus_window)
                    and foreground_focus_window_id() == target_focus_window
                    and bool(target_edit_target)
                    and foreground_edit_target_signature() == target_edit_target
                    and bool(input_generation)
                    and foreground_input_generation() == input_generation
                )

            if selected:
                transform_id = command_to_transform(command)
                output = transform_text(selected, transform_id, self.config, instruction=command)
                with external_delivery_claim():
                    if not delivery_owner_is_current():
                        return
                    automatic = automatic_delivery_is_current()
                    keep_previous = bool(
                        self.config.get("dictation", {}).get("restore_clipboard_after_paste", True)
                    )
                    receipt = paste_text_with_receipt(
                        output,
                        restore_clipboard=False,
                        paste_mode=(
                            str(self.config.get("dictation", {}).get("paste_mode", "auto"))
                            if automatic
                            else "copy_only"
                        ),
                        typing_interval_ms=config_int(
                            self.config.get("dictation", {}).get("typing_interval_ms"), 2
                        ),
                        clipboard_paste_delay_ms=config_int(
                            self.config.get("dictation", {}).get("clipboard_paste_delay_ms"), 10
                        ),
                        can_deliver=(
                            automatic_delivery_is_current
                            if automatic
                            else delivery_owner_is_current
                        ),
                    )
                    if automatic:
                        receipt = _copy_after_precommit_refusal(
                            output,
                            receipt,
                            can_deliver=delivery_owner_is_current,
                        )
                    if not delivery_owner_is_current():
                        return
                    if receipt.method == "copy_only":
                        pass
                    elif keep_previous:
                        expected = (
                            output
                            if receipt.method in {"clipboard", "shift_insert"}
                            else selected
                        )
                        restore_clipboard_if_unchanged(expected, previous_clipboard)
                    elif receipt.method not in {"clipboard", "shift_insert"}:
                        copy_text(output)
                    self.last_original = selected
                    self.last_transcript = output
                    self.last_diff = unified_diff(selected, output)
                    self.add_history(
                        {
                            "type": "command_transform",
                            "command": command,
                            "original": selected,
                            "text": output,
                            "created_at": time.time(),
                        }
                    )
                    if receipt.success and receipt.method != "copy_only":
                        message = f"Applied {transform_id}."
                    elif receipt.success:
                        message = f"{transform_id} result copied for manual paste."
                    elif receipt.method == "clipboard_commit_unknown":
                        message = (
                            f"{transform_id} may already be inserted. "
                            "Inspect the field before pasting again."
                        )
                    elif receipt.method == "direct_type_partial":
                        message = (
                            f"{transform_id} stopped during typing. "
                            "Review the field; the full result is kept in History."
                        )
                    else:
                        message = (
                            f"{transform_id} is kept in History, but the clipboard copy failed."
                        )
                    self.overlay.set_state("captured", message, preview(output, 112))
                return

            if not (
                delivery_owner_is_current()
                and bool(input_generation)
                and foreground_input_generation() == input_generation
            ):
                return
            url = "https://www.perplexity.ai/search?q=" + quote_plus(command)
            webbrowser.open(url)
            if not self._deferred_delivery_is_current(claim):
                return
            self.add_history(
                {"type": "command_search", "command": command, "url": url, "created_at": time.time()}
            )
            self.overlay.set_state("captured", "Opened command search.", preview(command, 112))
        except Exception:
            if selected:
                restore_clipboard_if_unchanged(selected, previous_clipboard)
            raise
        finally:
            self._release_deferred_delivery(claim)

    def run_transform(self, transform_id: str) -> None:
        claim = self._reserve_deferred_delivery()
        if claim is None:
            return
        target_window = foreground_window_id()
        selected = ""
        previous_clipboard = ""
        try:
            selected, previous_clipboard = copy_selected_text()
            selected = selected.strip()
            source = selected or self.last_transcript
            if not source:
                self.overlay.set_state(
                    "error",
                    "No selected text or last transcript to transform.",
                    "Select some text, or dictate something first.",
                )
                return
            input_generation = foreground_input_generation()

            def operation_is_current() -> bool:
                return self._deferred_delivery_is_current(claim)

            def selected_target_is_current() -> bool:
                return (
                    operation_is_current()
                    and bool(target_window)
                    and foreground_window_id() == target_window
                    and bool(input_generation)
                    and foreground_input_generation() == input_generation
                )

            output = transform_text(source, transform_id, self.config)
            with external_delivery_claim():
                if selected:
                    if not selected_target_is_current():
                        restore_clipboard_if_unchanged(selected, previous_clipboard)
                        return
                    keep_previous = bool(
                        self.config.get("dictation", {}).get("restore_clipboard_after_paste", True)
                    )
                    receipt = paste_text_with_receipt(
                        output,
                        restore_clipboard=False,
                        paste_mode=str(self.config.get("dictation", {}).get("paste_mode", "auto")),
                        typing_interval_ms=config_int(
                            self.config.get("dictation", {}).get("typing_interval_ms"), 2
                        ),
                        clipboard_paste_delay_ms=config_int(
                            self.config.get("dictation", {}).get("clipboard_paste_delay_ms"), 10
                        ),
                        can_deliver=selected_target_is_current,
                    )
                    if not operation_is_current():
                        return
                    if keep_previous:
                        expected = (
                            output
                            if receipt.method in {"clipboard", "shift_insert", "copy_only"}
                            else selected
                        )
                        restore_clipboard_if_unchanged(expected, previous_clipboard)
                    elif receipt.method not in {"clipboard", "shift_insert", "copy_only"}:
                        copy_text(output)
                    message = (
                        f"Applied {transform_id} to selection."
                        if receipt.success
                        else f"Copied {transform_id} result for manual paste."
                    )
                else:
                    receipt = paste_text_with_receipt(
                        output,
                        paste_mode="copy_only",
                        can_deliver=operation_is_current,
                    )
                    if not receipt.success or not operation_is_current():
                        return
                    message = f"Copied {transform_id} result from last transcript."

                self.last_original = source
                self.last_transcript = output
                self.last_diff = unified_diff(source, output)
                self.add_history(
                    {
                        "type": "transform",
                        "transform": transform_id,
                        "original": source,
                        "text": output,
                        "created_at": time.time(),
                    }
                )
                self.overlay.set_state("captured", message, preview(output, 112))
        except Exception:
            if selected:
                restore_clipboard_if_unchanged(selected, previous_clipboard)
            raise
        finally:
            self._release_deferred_delivery(claim)

    def translation_translate(
        self,
        text: str,
        source: str,
        target: str,
        model: str,
    ) -> dict[str, Any]:
        result = translate_text(
            text,
            self.config,
            source_value=source,
            target_value=target,
            model_value=model,
        )
        self.last_original = text
        self.last_transcript = result.text
        self.last_diff = unified_diff(text, result.text)
        if self.config.get("privacy", {}).get("save_history", True):
            self.add_history(
                {
                    "type": "translation",
                    "original": text,
                    "text": result.text,
                    "source_language": result.source_code,
                    "target_language": result.target_code,
                    "model": result.model,
                    "created_at": time.time(),
                }
            )
        return result.as_dict()

    def translation_model_status(self, model: str = "") -> dict[str, Any]:
        return translation_model_status(self.config, model or None)

    def translation_install_model(self, model: str = "") -> tuple[bool, str]:
        return install_translation_model(self.config, model or None)

    def translation_install_runtime(self) -> tuple[bool, str]:
        return install_ollama_runtime()

    def translation_paste(self, text: str) -> dict[str, Any]:
        output = str(text or "").strip()
        if not output:
            return {"success": False, "message": "There is no translated text to copy."}
        claim = self._reserve_deferred_delivery()
        if claim is None:
            return {"success": False, "message": "A newer action already owns delivery."}

        try:
            with external_delivery_claim():
                # The translation window necessarily takes focus. A top-level
                # HWND cannot prove which field inside Word, a browser, or an
                # Electron composer was originally active, so automatic paste
                # can target the wrong control. Copying is deterministic and
                # lets the person return to the exact field before they paste.
                receipt = paste_text_with_receipt(
                    output,
                    paste_mode="copy_only",
                    can_deliver=lambda: self._deferred_delivery_is_current(claim),
                )
                if not self._deferred_delivery_is_current(claim):
                    return {"success": False, "message": "A newer action replaced this copy."}
                return {
                    "success": bool(receipt.success),
                    "message": (
                        "Translation copied. Return to the destination and paste it."
                        if receipt.success
                        else "Clipboard is unavailable. The translation remains open."
                    ),
                    "delivery": receipt.as_dict(),
                }
        finally:
            self._release_deferred_delivery(claim)

    def _clipboard_learn_tick(self) -> None:
        """Watch for the copy that means "I just fixed that word by hand".

        Polled on the Tk loop about once a second -- one clipboard read, no
        window watching, no accessibility hooks. Three gates before anything
        is learned, each cutting a different false positive:

        - the shape gate (`looks_learnable`) admits only spellings ordinary
          prose never produces, so copied sentences and common words pass by;
        - the word must NOT appear in the last dictation we delivered --
          copying our own output back is navigation, not correction, while a
          spelling absent from our output is exactly what a hand-fix produces;
        - a dictation must have happened at all, because before the first one
          this app has corrected nothing and has no business learning.

        The learn is applied immediately and announced by the little pop-over
        above the pill; "Don't save" undoes it. Errors are swallowed whole --
        a clipboard hiccup must never cost anything visible.
        """
        if getattr(self, "_reset_in_progress", False) is True:
            self.overlay.root.after(1100, self._clipboard_learn_tick)
            return
        with contextlib.suppress(Exception):
            if bool(self.config.get("dictionary", {}).get("auto_learn", True)) and self.last_transcript:
                import pyperclip

                from .learned_words import forget, note_fix_evidence, remember

                from .paste import clipboard_is_private

                # X-604: a copy its app marked private (a password manager's)
                # is never read, learned, or shown in the pop-over.
                captured = "" if clipboard_is_private() else str(pyperclip.paste() or "").strip()
                previous = getattr(self, "_learn_last_clip", None)
                self._learn_last_clip = captured
                if (
                    captured
                    and captured != previous
                    and captured.lower() not in (self.last_transcript or "").lower()
                    and captured.lower() not in (self.last_original or "").lower()
                ):
                    # X-80 v2: shape learns instantly; a plain word learns on
                    # its second deliberate fix inside two weeks; a dismissal
                    # is a tombstone and never comes back.
                    verdict = note_fix_evidence(captured, self.config, time.time())
                    # X-466: "learn" and "offer" are different answers and used
                    # to do the same thing -- both called remember() and the
                    # difference reached the log alone, so the setting that was
                    # meant to ask never asked.
                    if verdict == "learn" and remember(captured, self.config):
                        self.save_settings()
                        log.info("learned a corrected word from the clipboard")

                        def reject(word: str = captured) -> None:
                            if forget(word, self.config):
                                self.save_settings()

                        self.overlay.root.after(
                            0, lambda: self.overlay.show_learned_word(captured, reject)
                        )
                    elif verdict == "offer":
                        # Nothing is stored yet. The pop-over asks, and only a
                        # yes writes it to the dictionary.
                        log.info("offering a word from the clipboard")

                        def accept(word: str = captured) -> None:
                            if remember(word, self.config):
                                self.save_settings()

                        self.overlay.root.after(
                            0, lambda: self.overlay.offer_learned_word(captured, accept)
                        )
        self.overlay.root.after(1100, self._clipboard_learn_tick)

    def toggle_auto_translation(self) -> None:
        """Flip automatic dictation translation from a hotkey, with a receipt.

        Turning it ON also enables translation itself -- a person reaching for
        the switch wants translated dictation, and answering their keypress
        with a second setting they must find first is the settings tab's
        failure mode moved onto a hotkey. The pill states which languages are
        now in effect, because a silent mode flip is how someone dictates a
        paragraph into the wrong language.
        """
        settings = self.config.setdefault("translation", {})
        turning_on = not bool(settings.get("enabled", False) and settings.get("auto_translate_dictation", False))
        settings["auto_translate_dictation"] = turning_on
        if turning_on:
            settings["enabled"] = True
        self.save_settings()
        if turning_on:
            from .translation import resolve_source_language, resolve_target_language

            source = resolve_source_language(self.config)
            target = resolve_target_language(self.config)
            self.overlay.set_state(
                "captured",
                "Auto-translate ON.",
                f"Dictation now arrives in {target.label} (from {source.label}).",
            )
        else:
            self.overlay.set_state("captured", "Auto-translate OFF.", "Dictation arrives as spoken.")

    def translate_last(self) -> None:
        claim = self._reserve_deferred_delivery()
        if claim is None:
            return
        target_window = foreground_window_id()
        selected, previous_clipboard = copy_selected_text()
        selected = selected.strip()
        source_text = selected or self.last_transcript or self.read_last_history_text()
        if not source_text:
            self._release_deferred_delivery(claim)
            self.overlay.set_state(
                "error",
                "No selected text or last transcript to translate.",
                "Select some text, or dictate something first.",
            )
            return
        input_generation = foreground_input_generation()
        self.overlay.set_state("processing", "Translating locally.", preview(source_text, 112))

        def operation_is_current() -> bool:
            return self._deferred_delivery_is_current(claim)

        def selected_target_is_current() -> bool:
            return (
                operation_is_current()
                and bool(target_window)
                and foreground_window_id() == target_window
                and bool(input_generation)
                and foreground_input_generation() == input_generation
            )

        def worker() -> None:
            release_queued = False

            def schedule_state(state: str, message: str, detail: str) -> None:
                nonlocal release_queued

                def apply_state() -> None:
                    try:
                        if operation_is_current():
                            self.overlay.set_state(state, message, detail)
                    finally:
                        self._release_deferred_delivery(claim)

                release_queued = True
                try:
                    self.overlay.root.after(0, apply_state)
                except Exception:
                    release_queued = False
                    raise

            try:
                result = translate_text(source_text, self.config)
                output = result.text
                with external_delivery_claim():
                    if not operation_is_current():
                        restore_clipboard_if_unchanged(selected, previous_clipboard)
                        return
                    if selected:
                        if not selected_target_is_current():
                            restore_clipboard_if_unchanged(selected, previous_clipboard)
                            self.add_history(
                                {
                                    "type": "translation",
                                    "original": source_text,
                                    "text": output,
                                    "source_language": result.source_code,
                                    "target_language": result.target_code,
                                    "model": result.model,
                                    "delivery": {"success": False, "method": "target_changed"},
                                    "created_at": time.time(),
                                }
                            )
                            if operation_is_current():
                                schedule_state(
                                    "captured",
                                    "Translation kept in History. The original selection was not touched.",
                                    preview(output, 112),
                                )
                            return
                        receipt = paste_text_with_receipt(
                            output,
                            restore_clipboard=False,
                            paste_mode=str(
                                self.config.get("dictation", {}).get("paste_mode", "auto")
                            ),
                            typing_interval_ms=config_int(
                                self.config.get("dictation", {}).get("typing_interval_ms"), 2
                            ),
                            clipboard_paste_delay_ms=config_int(
                                self.config.get("dictation", {}).get("clipboard_paste_delay_ms"), 10
                            ),
                            can_deliver=selected_target_is_current,
                        )
                        if not operation_is_current():
                            return
                        copied = copy_text(output)
                        message = (
                            "Translated selection and kept a clipboard copy."
                            if receipt.success and copied
                            else "Translation copied. The original selection was not changed."
                            if copied
                            else "Translation kept in History; clipboard is unavailable."
                        )
                    else:
                        receipt = paste_text_with_receipt(
                            output,
                            paste_mode="copy_only",
                            can_deliver=operation_is_current,
                        )
                        if not operation_is_current():
                            return
                        message = (
                            "Translated and copied the last transcript."
                            if receipt.success
                            else "Translation kept in History; clipboard is unavailable."
                        )
                    self.last_original = source_text
                    self.last_transcript = output
                    self.last_diff = unified_diff(source_text, output)
                    self.add_history(
                        {
                            "type": "translation",
                            "original": source_text,
                            "text": output,
                            "source_language": result.source_code,
                            "target_language": result.target_code,
                            "model": result.model,
                            "created_at": time.time(),
                        }
                    )
                    schedule_state("captured", message, preview(output, 112))
            except Exception:
                restore_clipboard_if_unchanged(selected, previous_clipboard)
                if operation_is_current():
                    schedule_state(
                        "error", "Translation could not finish.", "The source text was not changed."
                    )
            finally:
                if not release_queued:
                    self._release_deferred_delivery(claim)

        threading.Thread(target=worker, name="TalkDatTranslateLast", daemon=True).start()

    def send_feedback(
        self,
        kind: str = "feature",
        title: str = "",
        details: str = "",
        contact: str = "",
        language: str = "",
        context: str = "",
        include_logs: bool = False,
    ) -> bool:
        # A receipt means the service acknowledged the report. Email drafts
        # are an explicit form action and never turn a failed send into success.
        # Only the consented native fallback path reads a log here.
        logs = journal_tail() if include_logs else ""
        payload = build_feedback_payload(
            kind=kind,
            title=title,
            details=details,
            contact=contact,
            language=language,
            context=context,
            logs=logs,
        )
        # Field report #1: his crash arrived with no trail. faulthandler has
        # been writing crash-traceback.log at the moment of death since
        # 0.4.77; a bug report is the one place that file is worth its bytes.
        # Only bug-kind reports carry it, only the tail, and absence is fine.
        if kind == "bug":
            try:
                crash_log = app_dir() / "crash-traceback.log"
                if crash_log.exists() and crash_log.stat().st_size:
                    tail = crash_log.read_text(encoding="utf-8", errors="replace")[-4000:]
                    payload["crash_trail"] = tail
            except Exception:
                log.debug("crash trail could not be attached", exc_info=True)
        if submit_feedback(payload):
            return True
        return False

    def paste_last(self) -> None:
        text = self.last_transcript or self.read_last_history_text()
        # X-401: the founder reported "paste transcription does not work" and
        # the log had nothing to say about it. Every exit of this action now
        # leaves a line, so the next report can be read instead of guessed.
        log.info("paste_last: requested chars=%s", len(text or ""))
        if not text:
            log.info("paste_last: nothing to paste")
            self.overlay.set_state("error", "No previous transcript to paste.", "Dictate something first.")
            return
        claim = self._reserve_deferred_delivery()
        if claim is None:
            return
        target_window = foreground_window_id()
        input_generation = foreground_input_generation()

        def target_is_current() -> bool:
            return (
                self._deferred_delivery_is_current(claim)
                and bool(target_window)
                and foreground_window_id() == target_window
                and bool(input_generation)
                and foreground_input_generation() == input_generation
            )

        try:
            with external_delivery_claim():
                if not target_is_current():
                    log.info("paste_last: target changed before delivery")
                    self.overlay.set_state(
                        "error", "Paste Last stopped because the target changed.", preview(text, 112)
                    )
                    return
                receipt = paste_text_with_receipt(
                    text,
                    # Recovery always leaves the exact snapshot available even
                    # when the insertion route uses direct typing.
                    restore_clipboard=False,
                    smart_leading_space=bool(
                        self.config.get("dictation", {}).get("smart_leading_space", True)
                    ),
                    paste_mode=str(self.config.get("dictation", {}).get("paste_mode", "auto")),
                    typing_interval_ms=config_int(
                        self.config.get("dictation", {}).get("typing_interval_ms"), 2
                    ),
                    clipboard_paste_delay_ms=config_int(
                        self.config.get("dictation", {}).get("clipboard_paste_delay_ms"), 10
                    ),
                    can_deliver=target_is_current,
                )
                if not self._deferred_delivery_is_current(claim):
                    return
                copied = (
                    True
                    if receipt.method in {"clipboard", "shift_insert", "copy_only", "clipboard_commit_unknown"}
                    else copy_text(text)
                )
                if receipt.success and copied:
                    message = "Pasted and copied last transcript."
                    state = "captured"
                elif receipt.success:
                    message = "Pasted last transcript; clipboard is unavailable."
                    state = "captured"
                elif copied:
                    message = "Copied last transcript. Automatic paste was blocked."
                    state = "captured"
                else:
                    message = "Could not paste or copy. The last transcript is still in History."
                    state = "error"
                self.overlay.set_state(state, message, preview(text, 112))
        finally:
            self._release_deferred_delivery(claim)

    def copy_last(self) -> None:
        if not self.last_transcript:
            self.last_transcript = self.read_last_history_text()
        if not self.last_transcript:
            self.overlay.set_state("error", "No previous transcript to copy.", "Dictate something first.")
            return
        if copy_text(self.last_transcript):
            self.overlay.set_state("captured", "Copied last transcript to the clipboard.", preview(self.last_transcript, 112))
        else:
            self.overlay.set_state(
                "error",
                "The clipboard is unavailable.",
                "Your last transcript is kept. Try Copy again in a moment.",
            )

    def copy_last_diff(self) -> None:
        if not self.last_diff:
            self.overlay.set_state("error", "No cleanup diff yet.", "Dictate something first.")
            return
        copy_text(self.last_diff)
        self.overlay.set_state("captured", "Copied last cleanup diff.", preview(self.last_diff, 112))

    def open_scratchpad(self) -> None:
        self.overlay.open_scratchpad()

    def open_translation(self) -> None:
        self.overlay.root.after(0, self.overlay.open_translation)

    def open_settings(self) -> None:
        self.overlay.root.after(0, self.overlay.open_settings)

    def open_status(self) -> None:
        self.overlay.root.after(0, self.overlay.open_status)

    def open_history(self) -> None:
        self.overlay.root.after(0, self.overlay.open_history)

    def license_status(self) -> dict[str, Any]:
        return self.license_manager.status().to_dict()

    def sign_out_license(self) -> None:
        """Sign this device out and show the result."""
        if self.license_manager.forget_license():
            self.license_activation_snapshot = {"state": "idle", "detail": "Signed out on this device."}
            # X-525: signing out never affected dictation, and there is no
            # managed cloud to come back for. Say what an account is actually
            # for now, so signing out does not read as losing the engine.
            self.overlay.set_state("captured", "Signed out.", "Dictation keeps working. Sign in again to sync your preferences.")
        else:
            self.overlay.set_state("error", "Could not sign out.", f"{mac_support.CREDENTIAL_VAULT_NAME} was unavailable.")

    def license_activation_status(self) -> dict[str, Any]:
        with self.license_activation_lock:
            return {
                **self.license_activation_snapshot,
                "in_progress": self.license_activation_in_progress,
            }

    def open_account(self) -> None:
        self.overlay.root.after(0, self.overlay.open_account)

    def activate_license(self) -> None:
        with self.license_activation_lock:
            if self.license_activation_in_progress:
                self.license_activation_snapshot = {
                    "state": "waiting",
                    "detail": "Account activation is already waiting for browser sign-in.",
                }
                self.overlay.set_state("processing", "Account activation is already waiting for browser sign-in.")
                return
            self.license_activation_in_progress = True
            self._license_activation_cancel.clear()
            self.license_activation_snapshot = {
                "state": "starting",
                "detail": "Preparing secure browser sign-in.",
            }
        self.overlay.set_state("processing", "Preparing secure account activation.", f"Audio and transcripts stay on {platform_copy.THIS_COMPUTER}.")

        def worker() -> None:
            try:
                log.info("license activation: requesting device code")
                started = self.license_manager.begin_activation()
                user_code = str(started.get("userCode") or "")
                device_code = str(started.get("deviceCode") or "")
                verification_uri = str(started.get("verificationUri") or self.license_manager.product_url)
                # X-113 #17: the fallback matches the server's real TTL (30
                # minutes). 600 quietly gave up twenty minutes early whenever
                # the field went missing.
                expires_in = max(60, int(started.get("expiresIn") or 1800))
                interval = max(2, min(10, int(started.get("interval") or 3)))
                if not user_code or not device_code:
                    raise LicenseError("The account service did not return a complete activation code.")
                with self.license_activation_lock:
                    self.license_activation_snapshot = {
                        "state": "waiting",
                        "detail": f"Finish sign-in in your browser with code {user_code}.",
                        "user_code": user_code,
                        "expires_at": time.time() + expires_in,
                    }
                log.info("license activation: code %s issued, opening %s", user_code, verification_uri)
                copy_text(user_code)
                webbrowser.open(verification_uri)
                self.overlay.set_state(
                    "processing",
                    f"Finish sign-in in your browser. Code {user_code} is copied.",
                    "Talk DAT! keeps waiting securely; local dictation remains available.",
                )
                # X-113 #5: only a definitive server verdict stops the poll.
                # Network blips and cold-start 5xx arrive as LicenseErrors with
                # no code at all, and the old loop abandoned an ALREADY
                # APPROVED sign-in on the first one -- the user finished in the
                # browser and the app declared failure anyway.
                retryable = {"authorization_pending", "rate_limited", "device_code_in_use", ""}
                deadline = time.monotonic() + expires_in
                while time.monotonic() < deadline:
                    if self._license_activation_cancel.is_set():
                        with self.license_activation_lock:
                            self.license_activation_snapshot = {"state": "idle", "detail": "Sign-in cancelled."}
                        self.overlay.show_toast("Sign-in cancelled. Press Sign in whenever you're ready.")
                        return
                    try:
                        state = self.license_manager.exchange_activation(user_code=user_code, device_code=device_code)
                        with self.license_activation_lock:
                            self.license_activation_snapshot = {
                                "state": "active",
                                "detail": state.detail,
                                "email": state.email,
                            }
                        self.overlay.set_state("captured", state.detail, state.email)
                        return
                    except LicenseError as exc:
                        if str(getattr(exc, "code", "") or "") not in retryable:
                            raise
                    time.sleep(interval)
                raise LicenseError("The sign-in code expired. Press Sign in again for a fresh code.")
            except LicenseError as exc:
                # The one log line that would have named this feature's first
                # field failure: the worker previously reported errors only to
                # the Pill, which nobody can quote back afterwards.
                log.warning("license activation failed: %s", exc)
                with self.license_activation_lock:
                    self.license_activation_snapshot = {
                        "state": "error",
                        "detail": str(exc),
                    }
                self.overlay.set_state("error", str(exc), "Core local dictation is unaffected.")
            finally:
                with self.license_activation_lock:
                    self.license_activation_in_progress = False

        threading.Thread(target=worker, name="TalkDatLicenseActivation", daemon=True).start()

    def _note_cloud_fallback(self) -> None:
        """Count a cloud-to-local fallback, and escalate when they cluster.

        More than two inside ten minutes means the cloud route is having a
        bad day, not a bad moment. The session's provider switches to local
        so the next dictation skips the doomed attempt entirely, and a toast
        says so in words -- a silent route change reads as the transcripts
        getting mysteriously slower. The switch is session-only: nothing is
        written to disk, so a restart (or Settings) returns to their choice.
        """
        now_mono = time.monotonic()
        self._cloud_fallback_times.append(now_mono)
        if self._switched_to_local_for_session:
            return
        recent = [stamp for stamp in self._cloud_fallback_times if now_mono - stamp < 600]
        if len(recent) < 3:
            return
        self._switched_to_local_for_session = True
        self._provider_before_local_switch = str(self.config.get("stt", {}).get("provider", ""))
        self.config.setdefault("stt", {})["provider"] = "local"
        log.warning("cloud route failed %d times in %ds; session switched to the local model", len(recent), 600)
        self.overlay.show_toast(
            "Switched to your local model, the cloud connection is having issues. "
            "Your provider choice is unchanged in Settings; restarting returns to it."
        )

    def _maybe_return_to_cloud(self) -> None:
        """The other half of automatic failover: going back.

        The escalation that parks a session on local is only honest if the
        route returns when the outage ends -- otherwise "automatic switch"
        quietly means "your own cloud provider stops being used the first bad
        ten minutes and never resumes". Two conditions, both required:
        Windows reports a network again, and no fallback has fired for two
        minutes -- one green ping mid-outage is how a route flaps.

        Checked as a dictation starts rather than on a timer, because that
        is the moment the answer matters and the moment the person is
        looking at the pill to see the toast.
        """
        if not self._switched_to_local_for_session:
            return
        from .connectivity import network_is_available

        if not network_is_available(force=True):
            return
        now_mono = time.monotonic()
        if self._cloud_fallback_times and now_mono - self._cloud_fallback_times[-1] < 120:
            return
        provider = self._provider_before_local_switch
        if not provider or provider == "local":
            self._switched_to_local_for_session = False
            return
        self.config.setdefault("stt", {})["provider"] = provider
        self._switched_to_local_for_session = False
        self._provider_before_local_switch = ""
        log.info("cloud connection recovered; session switched back to %s", provider)
        self.overlay.show_toast(
            f"Cloud connection restored, switched back to {provider_label(provider)}."
        )

    # ------------------------------------------------------------- X-432
    # Sign in without leaving the app. His order: "full login and account
    # setup" from the menu on Mac and Windows, with the website as an option
    # rather than the only door. The account is created on the first verify,
    # so "setup" is the same two steps as sign-in.
    #
    # Same snapshot dictionary and lock as the browser flow, so the Account
    # window shows this the way it shows that. Two extra phases: code_sent,
    # which opens the code box, and code_error, which keeps it open with the
    # service's own words so a mistyped digit is not a dead end.

    def begin_email_sign_in(self, email: str) -> None:
        with self.license_activation_lock:
            if self.license_activation_in_progress:
                self.overlay.set_state("processing", "Another sign-in is already in progress.")
                return
            self.license_activation_in_progress = True
            self.license_activation_snapshot = {"state": "starting", "detail": "Sending your code."}

        def worker() -> None:
            try:
                started = self.license_manager.begin_activation()
                user_code = str(started.get("userCode") or "")
                device_code = str(started.get("deviceCode") or "")
                if not user_code or not device_code:
                    raise LicenseError("The account service did not return a complete activation code.")
                sent = self.license_manager.start_email_code(email)
                with self.license_activation_lock:
                    self.license_activation_snapshot = {
                        "state": "code_sent",
                        "detail": f"We sent a six-digit code to {email.strip().lower()}. Type it here.",
                        "email": email.strip().lower(),
                        "user_code": user_code,
                        "device_code": device_code,
                        "expires_at": time.time() + max(60, int(sent.get("expiresInSeconds") or 600)),
                    }
                self.overlay.show_toast("Check your email for the six-digit code.")
            except LicenseError as exc:
                with self.license_activation_lock:
                    self.license_activation_snapshot = {"state": "error", "detail": str(exc)}
                self.overlay.set_state("error", str(exc), "Core local dictation is unaffected.")
            finally:
                with self.license_activation_lock:
                    # code_sent is a resting state: the person is off reading
                    # their mail. Nothing is in progress until they come back.
                    self.license_activation_in_progress = False

        threading.Thread(target=worker, name="TalkDatEmailSignIn", daemon=True).start()

    def finish_email_sign_in(self, code: str) -> None:
        with self.license_activation_lock:
            pending = dict(self.license_activation_snapshot)
            if self.license_activation_in_progress:
                self.overlay.set_state("processing", "Another sign-in is already in progress.")
                return
            if pending.get("state") not in {"code_sent", "code_error"}:
                self.overlay.set_state("error", "Ask for a code first.", "Type your email and press Email me a code.")
                return
            self.license_activation_in_progress = True
            self.license_activation_snapshot = {**pending, "state": "verifying", "detail": "Checking your code."}

        def worker() -> None:
            try:
                email = str(pending.get("email") or "")
                session = self.license_manager.verify_email_code(email, code)
                token = str(session.get("accessToken") or "")
                if not token:
                    raise LicenseError("The account service did not return a session.")
                self.license_manager.approve_device(token, str(pending.get("user_code") or ""))
                state = self.license_manager.exchange_activation(
                    user_code=str(pending.get("user_code") or ""),
                    device_code=str(pending.get("device_code") or ""),
                )
                with self.license_activation_lock:
                    self.license_activation_snapshot = {
                        "state": "active",
                        "detail": state.detail,
                        "email": state.email,
                    }
                self.overlay.set_state("captured", state.detail, state.email)
            except LicenseError as exc:
                # A wrong or stale code keeps the box open: the person is one
                # retype away, not back at the start.
                retry = str(getattr(exc, "code", "") or "") in {"code_invalid", "code_expired", "code_locked", ""}
                with self.license_activation_lock:
                    self.license_activation_snapshot = (
                        {**pending, "state": "code_error", "detail": str(exc)}
                        if retry and str(getattr(exc, "code", "")) != "code_locked"
                        else {"state": "error", "detail": str(exc)}
                    )
                self.overlay.set_state("error", str(exc), "Core local dictation is unaffected.")
            finally:
                with self.license_activation_lock:
                    self.license_activation_in_progress = False

        threading.Thread(target=worker, name="TalkDatEmailVerify", daemon=True).start()

    def recent_audio_sessions(self) -> list[dict[str, Any]]:
        return list_safety_sessions(5)

    def recover_audio_session(self, session_id: str) -> None:
        session_id = str(session_id or "").strip()
        if not session_id:
            self.overlay.set_state("error", "Choose a protected voice session first.")
            return
        claim = self._reserve_deferred_delivery()
        if claim is None:
            return
        self.overlay.set_state(
            "processing",
            "Recovering protected audio.",
            "The result will be copied and kept in History.",
        )

        def worker() -> None:
            release_queued = False

            def schedule_state(state: str, message: str, detail: str) -> None:
                nonlocal release_queued

                def apply_state() -> None:
                    try:
                        if self._deferred_delivery_is_current(claim):
                            self.overlay.set_state(state, message, detail)
                    finally:
                        self._release_deferred_delivery(claim)

                release_queued = True
                try:
                    self.overlay.root.after(0, apply_state)
                except Exception:
                    release_queued = False
                    raise

            try:
                pcm16, sample_rate, channels = read_safety_audio(session_id)
                raw_text = transcribe_pcm(self.config, pcm16, sample_rate, channels).strip()
                if not raw_text:
                    raise RuntimeError("The selected speech model returned no transcript.")
                profile = active_profile(self.config)
                processed = process_dictation(raw_text, apply_profile(self.config, profile))
                final_text = processed.text or raw_text
                copied = False
                if self._deferred_delivery_is_current(claim):
                    with external_delivery_claim():
                        if self._deferred_delivery_is_current(claim):
                            receipt = paste_text_with_receipt(
                                final_text,
                                paste_mode="copy_only",
                                can_deliver=lambda: self._deferred_delivery_is_current(claim),
                            )
                            copied = receipt.success
                current = self._deferred_delivery_is_current(claim)
                update_safety_session(
                    session_id,
                    status="recovered",
                    raw_transcript=raw_text,
                    final_text=final_text,
                    error="",
                    delivery={
                        "success": copied,
                        "method": (
                            "recovery_copy"
                            if copied
                            else "superseded_history_only"
                            if not current
                            else "history_only"
                        ),
                    },
                )
                if self.config.get("privacy", {}).get("save_history", True):
                    self.add_history(
                        {
                            "type": "recovered_dictation",
                            "original": raw_text,
                            "text": final_text,
                            "delivery": {
                                "success": copied,
                                "method": (
                                    "recovery_copy"
                                    if copied
                                    else "superseded_history_only"
                                    if not current
                                    else "history_only"
                                ),
                            },
                            "protected_session_id": session_id,
                            "created_at": time.time(),
                        }
                    )
                if not current:
                    return
                self.last_original = raw_text
                self.last_transcript = final_text
                self.last_diff = unified_diff(raw_text, final_text)
                message = (
                    "Protected speech recovered and copied."
                    if copied
                    else "Protected speech recovered in History. Clipboard is unavailable."
                )
                schedule_state("captured", message, preview(final_text, 112))
            except Exception as exc:
                error_message = str(exc)
                update_safety_session(session_id, status="recovery_failed", error=error_message)
                if self._deferred_delivery_is_current(claim):
                    schedule_state(
                        "error",
                        f"Could not recover protected audio: {preview(error_message, 82)}",
                        "The local recording was not deleted.",
                    )
            finally:
                if not release_queued:
                    self._release_deferred_delivery(claim)

        threading.Thread(target=worker, name="TalkDatAudioRecovery", daemon=True).start()

    def open_stats(self) -> None:
        shell = getattr(self, "web_shell", None)
        if shell is not None and shell.open_settings("stats"):
            return
        self.overlay.root.after(0, self.overlay.open_stats)

    def open_local_models(self) -> None:
        self.overlay.root.after(0, self.overlay.open_local_models)

    def check_updates(
        self,
        *,
        silent: bool = False,
        install: bool = True,
        report: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Ask the release server whether a newer Talk DAT! exists.

        ``report`` (2026-09-23, Home's Check for updates): the same check, but
        the answer is handed back as ``{"phase": ...}`` for the page that asked
        to show in place -- "current", "available" (with "version"), "failed"
        (with "message"), "store" or "busy". With a reporter nothing else
        speaks for it: no toast, no Pill status and no Update window; the
        answer belongs where the question was asked. The pending update, the
        tray entry and the Pill's update dot are still recorded, so Install
        (install_or_check_update) finds the release this check found.
        """
        # Logged on entry so "I clicked it and nothing happened" is answerable
        # from the log. Without this the manual path left no trace at all, so a
        # click that never arrived and a check that ran and found nothing looked
        # identical after the fact.
        def answer(outcome: dict[str, Any]) -> None:
            if report is None:
                return
            try:
                report(outcome)
            except Exception:
                log.warning("update check result could not be reported", exc_info=True)

        if getattr(self, "_reset_in_progress", False) is True:
            answer({"phase": "failed", "message": "Talk DAT! is clearing local data. Check again when it has finished."})
            return
        log.info("update check requested: silent=%s install=%s reported=%s", silent, install, report is not None)
        # X-116, Store policy 10.2.5: a Store install updates ONLY through the
        # Store. The certification failure quoted our own Check for updates.
        # Manual click -> open the Store product page; background check ->
        # stand down entirely.
        from .updater import STORE_PRODUCT_URI, running_from_store

        if running_from_store():
            if not silent:
                log.info("update check routed to the Store: this copy has package identity")
                with contextlib.suppress(Exception):
                    webbrowser.open(STORE_PRODUCT_URI)
                if report is not None:
                    answer({"phase": "store"})
                    return
                self.overlay.set_state(
                    "captured",
                    "Updates for this copy come from the Microsoft Store.",
                    "The Store page is opening; updates install from there.",
                )
            return
        with self.update_lock:
            if self.update_in_progress:
                if report is not None:
                    answer({"phase": "busy"})
                elif not silent:
                    self.overlay.set_state("processing", "Already checking for updates.")
                return
            self.update_in_progress = True

        if not silent and report is None:
            self.overlay.set_state("processing", "Checking GitHub releases for updates.")

        def finish(message: str, detail: str = "", *, state: str = "captured") -> None:
            if report is not None:
                if state == "error":
                    answer({"phase": "failed", "message": " ".join(part for part in (message, detail) if part)})
                return
            if silent:
                return
            self.overlay.root.after(0, lambda: self.overlay.set_state(state, message, detail))

        def worker() -> None:
            try:
                updates = self.config.setdefault("updates", {})
                info = check_for_update(APP_VERSION, channel=str(updates.get("channel", "stable")))
                updates["last_checked_at"] = int(time.time())
                updates["latest_version"] = info.latest_version
                log.info("update check result: available=%s latest=%s current=%s",
                         info.available, info.latest_version, APP_VERSION)
                updates["latest_release_url"] = info.release_url
                save_config(self.config)
                if not info.available:
                    self.pending_update = None
                    with contextlib.suppress(Exception):
                        self.tray.set_update_available("")
                    if report is not None:
                        answer({"phase": "current", "version": APP_VERSION})
                        return
                    # A pill state change alone is not an answer. Someone who
                    # right-clicks the pill and chooses Check for updates is
                    # looking at the menu, not at the pill, so the reply has to
                    # come to them. Only when they asked -- a silent background
                    # check must stay silent.
                    if not silent:
                        with contextlib.suppress(Exception):
                            self.overlay.show_toast(f"Talk DAT! is up to date  -  v{APP_VERSION}")
                    finish(f"Talk DAT! is up to date. v{APP_VERSION}")
                    return

                # Remember the available update so the user can install it any time
                # from the tray ("Install update vX") or pill menu, not just now.
                self.pending_update = info
                with contextlib.suppress(Exception):
                    self.tray.set_update_available(f"v{info.latest_version}")

                if silent and info.latest_version == str(updates.get("skip_version", "")):
                    return

                # Remember when this particular version first appeared, because
                # the reminder cadence escalates with how long it has been
                # ignored and "how long" has to survive a restart.
                if str(updates.get("first_seen_update", "")) != info.latest_version:
                    updates["first_seen_update"] = info.latest_version
                    updates["first_seen_update_at"] = int(time.time())
                    # X-47: a fresh release earns fresh patience -- the
                    # three-dialog allowance resets per version.
                    updates["dialog_dismissals"] = 0
                    save_config(self.config)

                # X-84: the Pill carries the flag the moment we know.
                severity = "red" if getattr(info, "forced", False) else "green"
                with contextlib.suppress(Exception):
                    self.overlay.root.after(0, lambda: self.overlay.set_update_flag(severity))

                if report is not None:
                    # The page that asked shows the answer and its Install
                    # button, which reaches install_or_check_update and the
                    # verified Update window from there. Answered before any
                    # predownload: the question was "is there one?", and a
                    # 190 MB download must not stand between it and the reply.
                    answer({
                        "phase": "available",
                        "version": str(info.latest_version),
                        "required": bool(getattr(info, "forced", False)),
                    })
                    return
                predownloaded: Path | None = None
                # A red release fixes something the person is living with, so
                # it downloads whether or not auto-download is on -- that
                # setting governs convenience, not repairs.
                if info.installer_url and (getattr(info, "forced", False) or (silent and bool(updates.get("auto_download", False)))):
                    try:
                        predownloaded = download_installer(info)
                        updates["last_installer_path"] = str(predownloaded)
                        save_config(self.config)
                    except UpdateError:
                        predownloaded = None
                if getattr(info, "forced", False):
                    # Forced, but never rude: install_or_check_update waits for
                    # the microphone to be idle. Taking the app away mid-
                    # sentence would lose the words being spoken, which is a
                    # worse bug than the one being patched.
                    self.overlay.root.after(0, lambda: self.show_update_window(info, predownloaded))
                    return
                if silent:
                    # A background check must not open a window just because it
                    # found something. It runs on a timer that cannot see
                    # whether the microphone is live, and taking focus while
                    # someone is speaking eats the words they were saying.
                    self.overlay.root.after(0, lambda: self.remind_about_update(TRIGGER_START, info, predownloaded))
                    return
                self.overlay.root.after(0, lambda: self.show_update_window(info, predownloaded))
            except UpdateError as error:
                log.warning("update check failed: %s", error)
                finish("Update check failed.", str(error), state="error")
            except Exception as error:
                # A URLError, a JSON surprise, anything unexpected: it used
                # to kill this thread SILENTLY -- no log line, no message,
                # indistinguishable from the button doing nothing. Never
                # again: the log names it and the user is told.
                log.warning("update check crashed: %s", error, exc_info=True)
                finish("Update check failed.", "Could not reach the release server. Try again in a minute.", state="error")
            finally:
                with self.update_lock:
                    self.update_in_progress = False
                log.info("update check finished")

        threading.Thread(target=worker, name="TalkDatUpdater", daemon=True).start()

    def remind_about_update(self, trigger: str, info: Any = None, predownloaded: Path | None = None) -> None:
        """Mention a waiting update, but only if this moment is a safe one.

        Called at seams rather than on a timer: launch, a settled pause after a
        dictation, returning to an idle machine, and on the way out. The policy
        decides; this only supplies what it is deciding from.
        """
        info = info or self.pending_update
        if info is None:
            return
        updates = self.config.setdefault("updates", {})
        now = int(time.time())
        session_at = float(getattr(self, "last_session_ended_at", 0) or 0)

        decision = should_remind(
            {
                "update_available": True,
                "trigger": trigger,
                "latest_version": info.latest_version,
                "skip_version": str(updates.get("skip_version", "")),
                "snooze_until": int(updates.get("snooze_until", 0) or 0),
                "last_reminded_at": int(updates.get("last_reminded_at", 0) or 0),
                "first_seen_at": int(updates.get("first_seen_update_at", 0) or 0),
                "security_update": bool(getattr(info, "security", False)),
                "session_active": bool(getattr(self, "session_active", False)),
                "session_processing": bool(getattr(self, "session_processing", False)),
                "update_window_open": bool(getattr(self, "update_window_open", False)),
                "onboarding_incomplete": onboarding_blocks_update_reminders(self.config),
                "seconds_since_session": int(now - session_at) if session_at else 10 ** 6,
                "seconds_idle": int(getattr(self, "seconds_idle", 0) or 0),
            },
            now=now,
        )
        log.info("update reminder: trigger=%s show=%s reason=%s",
                 trigger, decision.should_remind, decision.reason)
        if not decision.should_remind:
            return

        updates["last_reminded_at"] = now
        save_config(self.config)

        # X-47, Mayowa's escalation: the real dialog gets THREE dismissals
        # per version; after that it never interrupts again -- a tiny
        # clickable pop-over above the pill takes over, and the menu row
        # stays red throughout (see update_badge).
        dismissals = int(updates.get("dialog_dismissals", 0) or 0)
        if decision.intrusive and dismissals < 3:
            self.show_update_window(info, predownloaded)
            return
        with contextlib.suppress(Exception):
            self.overlay.show_update_popover(
                str(info.latest_version),
                on_update=lambda: self.check_updates(silent=False, install=True),
            )

    def show_update_window(self, info: Any, predownloaded: Path | None = None) -> None:
        data = {
            "current_version": APP_VERSION,
            "latest_version": info.latest_version,
            "published_at": info.published_at,
            "release_notes": info.release_notes,
            "release_url": info.release_url,
            "has_installer": bool(info.installer_url),
            "installer_size": info.installer_size,
            "has_checksum": bool(info.installer_sha256),
            "provenance_verified": bool(info.receipt_verified),
            "source_commit": str(info.receipt_commit),
            "publisher_signature_required": bool(info.artifact_signing_enabled),
            "predownloaded": predownloaded is not None,
        }
        self.overlay.open_update_window(
            data,
            on_install=lambda set_progress, set_status, on_done: self.install_update(
                info, predownloaded, set_progress, set_status, on_done
            ),
            on_skip=lambda: self.skip_update_version(info.latest_version),
        )

    def install_update(
        self,
        info: Any,
        predownloaded: Path | None,
        set_progress: Any,
        set_status: Any,
        on_done: Any,
    ) -> None:
        def worker() -> None:
            # Logged at every stage because "install from check for update not
            # actually working all the way" arrived as a report with no trail:
            # the download pile proved downloads happened, and nothing recorded
            # whether the handoff ever did.
            try:
                installer = predownloaded
                if installer is None or not installer.exists():
                    set_status("Downloading update...")
                    log.info("update install: downloading %s", info.latest_version)
                    installer = download_installer(info, progress=set_progress)
                log.info("update install: installer ready at %s", installer)
                updates = self.config.setdefault("updates", {})
                updates["last_installer_path"] = str(installer)
                save_config(self.config)
                set_status("Rechecking installer integrity before launch...")
                launch_installer(
                    installer,
                    expected_sha256=info.installer_sha256,
                    expected_size=info.installer_size,
                    require_authenticode=bool(info.artifact_signing_enabled),
                )
                set_status("Installer verified. Starting silent update...")
                log.info("update install: installer launched for %s; quitting in 2.2s", info.latest_version)
                on_done(True, "Update installer started. Talk DAT! will close and relaunch when install finishes.")
                self.overlay.root.after(2200, self.quit)
            except UpdateError as error:
                log.warning("update install failed: %s", error)
                on_done(False, str(error))
            except Exception as error:
                # X-535: the same silent thread death the check worker above
                # was already cured of, still live in its sibling. Anything
                # that is not an UpdateError killed this worker before
                # on_done, so the window sat on "Downloading update..." for
                # as long as it stayed open -- no error, no log line,
                # indistinguishable from a slow connection.
                #
                # http.client.IncompleteRead is the realistic one: a truncated
                # 487 MB body raises it, and it is neither a URLError nor an
                # OSError, so download_installer never converts it.
                log.warning("update install crashed: %s", error, exc_info=True)
                on_done(False, "The update could not be installed. Try again in a minute.")

        threading.Thread(target=worker, name="TalkDatUpdateInstall", daemon=True).start()

    def skip_update_version(self, version: str) -> None:
        updates = self.config.setdefault("updates", {})
        updates["skip_version"] = str(version)
        save_config(self.config)

    def show_overlay(self) -> None:
        self.overlay.show()

    def hide_overlay(self) -> None:
        self.overlay.hide()

    # App theme families -> the website's clay theme names. Only the families
    # with a genuine clay counterpart map; everything else means "night", the
    # site's shipped near-black design. The promise is that a signed-in
    # person's site matches their app, and an approximate match in the same
    # colour world keeps that promise better than refusing to sync at all.
    _SITE_THEME_BY_FAMILY = {
        "Roman Clay": "ember",
        "Oxide Copper": "ember",
        "Ember Glass": "ember",
        "Crimson Bloom": "ember",
        "Sandstone": "amber",
        "Desert Bloom": "amber",
        "Solar Ribbon": "amber",
        "Champagne Glass": "amber",
        "Obsidian Gold": "amber",
        "Teal Circuit": "teal",
        "Aqua Noir": "teal",
        "Terminal Rain": "teal",
        "Deep Forest": "sage",
        "Lime Wash": "sage",
        "Midnight Ink": "indigo",
        "Cobalt Heat": "indigo",
        "Violet Signal": "indigo",
        "Arctic Aurora": "indigo",
        "Ivory Halo": "bone",
        "Venetian Plaster": "bone",
    }

    def _push_theme_preference(self) -> None:
        """Mirror the app's theme onto the account, so the website matches.

        Best effort in a thread: a theme is decoration, and no save may ever
        wait on -- or fail because of -- a network call about paint. Skipped
        entirely when the PC is not activated, because the server needs the
        signed licence to know whose account to paint.
        """
        theme_name = str(self.config.get("ui", {}).get("settings_theme", ""))
        family = theme_name.removesuffix(" Dark").removesuffix(" Light").strip()
        site_theme = self._SITE_THEME_BY_FAMILY.get(family, "night")
        if site_theme == getattr(self, "_last_pushed_theme", None):
            return
        token = None
        with contextlib.suppress(Exception):
            from .credentials import credential_store
            from .licensing import LICENSE_TARGET

            store = credential_store()
            token = store.read(LICENSE_TARGET) if store.available else None
        if not token:
            return

        def push() -> None:
            with contextlib.suppress(Exception):
                import json as json_module
                import urllib.request

                from .official_build import service_url

                prefs_url = service_url(self.config, "/v1/prefs")
                if not prefs_url:
                    return
                request = urllib.request.Request(
                    prefs_url,
                    data=json_module.dumps({"theme": site_theme}).encode("utf-8"),
                    headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10):
                    pass
                self._last_pushed_theme = site_theme
                log.info("theme preference mirrored to the account: %s", site_theme)

        threading.Thread(target=push, daemon=True).start()

    def update_badge(self) -> str:
        """X-47: the pill menu's red row. Empty means no update pending."""
        try:
            from .updater import is_newer_version

            latest = str(self.config.get("updates", {}).get("latest_version", "") or "")
            if latest and is_newer_version(latest, APP_VERSION):
                return f"Update available - v{latest}"
        except Exception:
            log.debug("update badge unavailable", exc_info=True)
        return ""

    def _has_a_writing_model(self) -> bool:
        """X-491: is there anything to write WITH?

        This replaced the old paid-cloud entitlement check on the five
        features the managed service used to serve. The QUESTION changed with the product: not
        "has this person paid us" but "is a local model or their own key
        configured", which is the only thing that can still do the work.
        """
        try:
            from .llm import llm_configured

            return llm_configured(self.config)
        except Exception:
            # A formatter we cannot even ask about is not one we can use, so
            # the answer is still no -- but it is SAID. This handler was
            # silent when first written and the suite caught it: five features
            # gate on this, and one that starts refusing for a reason nobody
            # logged is indistinguishable from one nobody configured.
            log.warning("could not determine whether a writing model exists", exc_info=True)
            return False

    def route_state(self) -> dict[str, Any]:
        """What the pill's two-position switch needs to draw itself.

        X-525: `cloud_locked` is gone. It asked whether the leg was
        "talk_dat_cloud", and `cloud_leg_provider` answers `byok_provider() or
        "local"` since X-480, so it could never be true again. A flag that
        cannot fire is not a guard, it is a label nobody reads.
        """
        from .stt_registry import cloud_leg_provider, route_mode

        return {
            "mode": route_mode(self.config),
            "leg": cloud_leg_provider(self.config),
        }

    def set_route_mode(self, mode: str) -> bool:
        """The pill's switch writes here. One tap, reflected everywhere:
        config first (every menu reads it), the Settings speech tab repaints
        live if open, and the pill confirms what it did in plain words."""
        from .stt_registry import ROUTE_MODES, byok_provider, resolve_route

        mode = str(mode).strip().lower()
        if mode not in ROUTE_MODES:
            return False
        stt = self.config.setdefault("stt", {})
        current = str(stt.get("provider", "local"))
        if current not in {"", "local"}:
            # Leaving (or re-affirming) a cloud provider: remember it as THE
            # cloud leg so Local -> Cloud round-trips land where they left.
            stt["cloud_provider"] = current
        stt["route_mode"] = mode
        stt["provider"] = resolve_route(self.config)
        self.save_settings()
        # X-338: the fence IS the guarantee -- while Local is selected,
        # every cloud helper refuses at the socket boundary.
        from . import net_fence
        net_fence.set_local_only(mode == "local")
        # Picking a route by hand ends any rescue the app imposed on its own.
        # It used to only clear on "auto", a mode X-480 deleted.
        self._auto_local_sticky = False
        # X-338: switching toward local warms the engine NOW, so the first
        # dictation does not pay the model load.
        if mode == "local":
            self.warm_selected_local_model()
        try:
            self.overlay.refresh_route_paint()
        except Exception:
            log.debug("route repaint skipped", exc_info=True)
        # X-532: these keys must be ROUTE_MODES and nothing else.
        #
        # They were "cloud" / "auto" / "local" while `mode` was already
        # guarded to ("local", "byok"), so tapping "Your key" on the pill
        # raised KeyError HERE -- after the route had been saved, before the
        # pill could confirm it. The tap handler catches everything and logs
        # at DEBUG, so the switch simply appeared to do nothing, silently, on
        # every install since X-525.
        labels = {
            # X-192: "Everything" was a promise the formatter broke. Speech
            # and finishing both stay here now, so the sentence names them
            # rather than claiming a scope no single setting can guarantee.
            "local": ("Local", f"Speech and finishing both stay on {platform_copy.THIS_COMPUTER}."),
            "byok": ("Your key", "Dictation runs on the provider you hold the key for."),
        }
        title, detail = labels[mode]
        if mode == "byok":
            # Say whose key, and say so plainly when there isn't one: a byok
            # route with no key resolves home (resolve_route), and a person
            # who is not told that reads the fallback as a broken switch.
            leg = byok_provider(self.config)
            detail = (
                f"Dictation runs on your own {leg} key."
                if leg
                else f"No provider key saved yet, so this still runs on {platform_copy.THIS_COMPUTER}. "
                     "Add a key under Settings, Speech."
            )
        self.overlay.set_state("captured", f"Route: {title}", detail)
        return True

    def push_menu_order(self, order: list[str]) -> None:
        """X-06: mirror the reordered pill menu onto the account, so every
        signed-in PC and future install opens it the user's way. Same
        best-effort contract as the theme push: never block, never fail a
        local save over a network call about arrangement."""
        token = None
        with contextlib.suppress(Exception):
            from .credentials import credential_store
            from .licensing import LICENSE_TARGET

            store = credential_store()
            token = store.read(LICENSE_TARGET) if store.available else None
        if not token:
            return

        def push() -> None:
            with contextlib.suppress(Exception):
                import json as json_module
                import urllib.request

                from .official_build import service_url

                prefs_url = service_url(self.config, "/v1/prefs")
                if not prefs_url:
                    return
                request = urllib.request.Request(
                    prefs_url,
                    data=json_module.dumps({"menuOrder": list(order)}).encode("utf-8"),
                    headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10):
                    pass
                log.info("menu order mirrored to the account")

        threading.Thread(target=push, daemon=True).start()

    def _local_clip_transcriber(self):
        """A Path -> text callable over the ACTIVE local model (X-35).

        Training runs against the local engine: it is free, offline, and the
        one engine every install is guaranteed to have. The indirection is
        what lets an engine switch re-derive aliases from the same clips.
        """
        import wave

        from .local_stt import transcribe
        from .stt_registry import selected_model_id

        model_id = selected_model_id(self.config, "local")

        def run(path) -> str:
            with wave.open(str(path), "rb") as source:
                rate = source.getframerate()
                channels = source.getnchannels()
                pcm = source.readframes(source.getnframes())
            return transcribe(
                model_id=model_id,
                pcm16=pcm,
                sample_rate=rate,
                channels=channels,
                language="en",
            )

        return run

    def record_pronunciation(self, term_text: str, on_status) -> None:
        from .pronunciation_practice import PronunciationPractice
        with self.lock:
            check = getattr(self, '_microphone_check', None)
            if check is not None and not check.finished.is_set():
                raise ValueError('Finish or stop the microphone check before pronunciation practice.')
            practice = getattr(self, '_pronunciation_practice', None)
            if practice is None:
                practice = self._pronunciation_practice = PronunciationPractice(self)
            practice.start(term_text, on_status)

    def cancel_pronunciation(self) -> None:
        practice = getattr(self, '_pronunciation_practice', None)
        if practice is not None:
            practice.cancel()

    def format_both_finishes(self, raw: str, on_done: Any) -> None:
        """X-137: the same words, finished both ways, for the A/B chooser.

        A PREVIEW pass: smart_format only, no dictionary/vocab/journal side
        effects, each intensity forced on a config copy. Results land back
        on the Tk thread; a formatter failure falls back to the raw words
        so the chooser never shows an empty pane."""
        raw = str(raw or "").strip()

        def worker() -> None:
            results: dict[str, str] = {}
            for key in ("standard", "executive"):
                forced = copy.deepcopy(self.config)
                forced.setdefault("cleanup", {})["format_intensity"] = key
                forced.setdefault("cleanup", {})["smart_format"] = True
                try:
                    results[key] = smart_format(raw, forced) if raw else ""
                except Exception:
                    log.debug("finish preview (%s) failed", key, exc_info=True)
                    results[key] = raw
            with contextlib.suppress(Exception):
                self.overlay.root.after(0, lambda: on_done(results.get("standard", raw), results.get("executive", raw)))

        threading.Thread(target=worker, name="TalkDatFinishPreview", daemon=True).start()

    def save_onboarding_settings(self, candidate: dict[str, Any]) -> dict[str, bool]:
        """Persist setup before applying it; report runtime refresh separately."""
        from .config import _SAVE_LOCK
        from .web_shell.shell_persistence import save_settings_config
        from .stt_registry import local_only, route_mode
        from . import net_fence

        with _SAVE_LOCK:
            saved = copy.deepcopy(candidate)
            save_settings_config(saved)
            self.config.clear()
            self.config.update(saved)
        refreshed = True
        try:
            net_fence.set_local_only(local_only(self.config) or route_mode(self.config) == "local")
            self._auto_local_sticky = False
            self.overlay.apply_runtime_config()
            self.save_settings(persist=False)
            self.overlay.refresh_route_paint()
        except Exception as error:
            refreshed = False
            log.warning("Setup saved but runtime refresh failed (%s)", type(error).__name__)
        return {"saved": True, "runtime_refreshed": refreshed}

    def execute_reset(self, intended, revision, complete):
        from .web_shell.reset_adapter import actions_for_app
        actions_for_app(self).execute(intended, revision, complete)

    def finish_reset(self):
        from .web_shell.reset_adapter import actions_for_app
        actions_for_app(self).finish()

    def save_settings(self, *, persist: bool = True) -> None:
        if getattr(self, "_reset_in_progress", False) is True:
            return
        if persist:
            save_config(self.config)
        # X-222: the switch is flipped here -- overlay.py writes
        # privacy["save_history"] and then calls this -- so this is the moment
        # the draft taken BEFORE the toggle has to go. Clearing only on the
        # next dictation would leave it there indefinitely for anyone who
        # turned history off and stopped talking.
        if not self.config.get("privacy", {}).get("save_history", True):
            self.clear_live_draft()
        from .plugins import plugins_enabled, request_reload
        enabled = plugins_enabled(self.config)
        previous = getattr(self, "_plugins_were_enabled", enabled)
        self._plugins_were_enabled = enabled
        if previous != enabled:
            request_reload(self.config if enabled else None)
        prepare_local_formatter(self.config)
        # X-35: an engine switch re-derives every trained term's aliases from
        # the stored clips -- same voice, new engine's ears. Cheap no-op when
        # nothing was ever trained.
        try:
            from .stt_registry import selected_model_id, selected_provider_id

            engine_key = f"{selected_provider_id(self.config)}:{selected_model_id(self.config, selected_provider_id(self.config))}"
        except Exception:
            engine_key = ""
        if engine_key and engine_key != getattr(self, "_trained_engine_key", engine_key):
            def retrain() -> None:
                try:
                    from .pronunciation import refresh_term_aliases

                    if refresh_term_aliases(self.config, self._local_clip_transcriber()):
                        save_config(self.config)
                        log.info("pronunciation aliases re-derived for %s", engine_key)
                except Exception:
                    log.debug("pronunciation refresh failed", exc_info=True)

            threading.Thread(target=retrain, name="TalkDatPronunciationRefresh", daemon=True).start()
        self._trained_engine_key = engine_key
        self._push_theme_preference()
        self.hotkeys.update_config(
            apply_trigger_style(
                self.config.get("hotkeys", {}),
                str(self.config.get("dictation", {}).get("trigger_style", "both")),
            ),
            hold_debounce_ms=int(self.config.get("dictation", {}).get("hold_debounce_ms", 50)),
        )
        self.refresh_wake_word()
        if self.control_server is not None:
            if bool(self.config.get("remote", {}).get("enabled", False)):
                self.control_server.start()
            else:
                self.control_server.stop()
        self.overlay.root.after(120, self.prefetch_selected_local_model)

    def warm_selected_local_model(self) -> None:
        """Build the local inference session before the first dictation needs it.

        Downloading the weights was already done ahead of time; loading them was
        not, and only the second one is paid on every launch. Measured on this
        machine with the same 5-second clip: 7.9s for the first transcription of
        a session, 0.9-1.6s for every one after it. The whole difference is
        constructing the ONNX session, and it was landing on the first thing
        somebody does after opening the app.

        Silent by design. It changes nothing a person can see except that the
        first dictation stops being slow, and announcing "warming up" would draw
        attention to a wait that no longer exists. If it fails the model still
        loads on demand, exactly as before.
        """
        if getattr(self, "_reset_in_progress", False) is True:
            return
        model = model_to_warm(self.config)
        if model is None:
            return
        # X-338: the fence follows the saved route from the very first
        # breath of the app; this method runs at startup, so it is the one
        # place both startup and every later warm pass through.
        from . import net_fence
        net_fence.set_local_only(
            str(self.config.get("stt", {}).get("route_mode", "auto")).strip().lower() == "local"
        )

        def worker() -> None:
            started = time.perf_counter()
            if warm_engine(model):
                log.info("local engine warm: model=%s ms=%d",
                         model.id, int((time.perf_counter() - started) * 1000))

        threading.Thread(target=worker, name="TalkDatWarmLocal", daemon=True).start()

    def apply_performance_preset_once(self) -> None:
        """X-78: the install-time PC audit picks the local default FOR this
        machine, once, so the background prefetch that makes "runs on your
        machine" true pulls a model this machine can actually run. The audit
        runs off the Tk thread because the GPU probe can shell out."""
        stt = self.config.setdefault("stt", {})
        if stt.get("performance_preset_applied"):
            return

        def worker() -> None:
            try:
                from .pc_audit import audit_pc, recommended_local_model

                audit = audit_pc()
                recommendation = recommended_local_model(audit)
            except Exception:
                log.debug("pc audit failed; keeping the packaged default", exc_info=True)
                return

            def apply() -> None:
                providers = stt.setdefault("providers", {})
                local = providers.setdefault("local", {})
                chosen = str(local.get("model") or "")
                from .local_stt import DEFAULT_LOCAL_MODEL_ID as packaged_default
                if not chosen or chosen == packaged_default:
                    local["model"] = recommendation
                stt["performance_preset_applied"] = True
                stt["performance_preset"] = {"summary": audit.summary, "model": recommendation}
                save_config(self.config)
                log.info("performance preset: %s -> %s", audit.summary, recommendation)

            self.overlay.root.after(0, apply)

        threading.Thread(target=worker, name="TalkDatPcAudit", daemon=True).start()

    def prefetch_selected_local_model(self, on_status: Callable[[str], None] | None = None) -> None:
        """X-83: a button that silently does nothing is indistinguishable from
        a broken one -- reported as "Prepare local model does nothing". Every
        exit path now speaks, and progress reaches the caller's own surface
        (the onboarding page) instead of only the pill, which is behind it.
        """
        if getattr(self, "_reset_in_progress", False) is True:
            return

        def say(message: str) -> None:
            if on_status is None:
                return
            with contextlib.suppress(Exception):
                self.overlay.root.after(0, lambda: on_status(message))

        with self.lock:
            if self.session is not None:
                say("Waiting for the current dictation to finish, then preparing the model.")
                self.overlay.root.after(3000, lambda: self.prefetch_selected_local_model(on_status))
                return
        model = model_to_prefetch(self.config)
        if model is None:
            say("Your offline model is already installed and ready, nothing to download.")
            return
        with self.local_model_prefetch_lock:
            if self.local_model_prefetch_in_progress:
                say(f"{model.label} is already being prepared. This continues in the background.")
                return
            self.local_model_prefetch_in_progress = True

        def report(status: str) -> None:
            messages = {
                "downloading_model": self._local_download_message(model),
                "loading_model": f"Loading and checking {model.label}.",
                "verifying_model": f"Verifying {model.label}.",
                "model_ready": f"{model.label} is ready.",
            }
            message = messages.get(status, f"Preparing {model.label}.")
            say(message)

            def update() -> None:
                with self.lock:
                    session_active = self.session is not None
                if not session_active and status != "model_ready":
                    self.overlay.set_state("processing", message, "Microphone off. Local model setup runs once.")

            self.overlay.root.after(0, update)

        def worker() -> None:
            error = ""
            try:
                download_local_model(model, report)
                log.info("local model ready: model=%s", model.id)
            except Exception as exc:
                error = str(exc) or exc.__class__.__name__
                log.exception("local model prefetch failed: model=%s", model.id)
            finally:
                with self.local_model_prefetch_lock:
                    self.local_model_prefetch_in_progress = False
                say(f"{model.label} is ready, offline speech will work with no internet."
                    if not error else f"Could not prepare {model.label}: {preview(error, 90)}")

            def finish() -> None:
                with self.lock:
                    session_active = self.session is not None
                if session_active:
                    return
                if error:
                    self.overlay.set_state("error", f"Local model setup failed: {preview(error, 100)}", "Open Local Models to retry.")
                else:
                    self.overlay.set_state("captured", f"{model.label} is ready.", "Private on-device speech is ready.")

            self.overlay.root.after(0, finish)

        self.overlay.set_state("processing", f"Preparing {model.label}.", "Microphone off. Downloading once for private speech.")
        threading.Thread(target=worker, name=f"TalkDatPrefetch-{model.id}", daemon=True).start()

    def panic_stop(self) -> None:
        """Stop dictation plus every auxiliary surface in the mic registry.

        X-175. This was `self.cancel()` and nothing else. Cancel ends the
        dictation session, and the dictation session is one of at least seven
        surfaces in this app that can hold the microphone: live captions, the
        Settings level meter, Mic Doctor, Race, pronunciation practice,
        Translation's Speak and onboarding's rehearsal all open their own
        streams. Panic therefore silenced one of them and left the rest
        recording, while the pill went quiet and looked like it had worked.

        A panic button that appears to work is worse than one that visibly
        fails. This sweeps every explicitly registered auxiliary owner, while
        deliberately avoiding a global "microphone off" claim: several legacy
        capture tools still own their shutdown inside their own window.
        """
        # Hotkey actions run on TalkDatHotkeyDispatch and the local control API
        # uses ThreadingHTTPServer. Both may call this bound method directly.
        # Registry stoppers are allowed to update their owning surface (the
        # onboarding mic rehearsal cancels Tk timers and changes controls), so
        # the entire panic transaction must enter through the existing
        # pure-Python cross-thread queue before *any* stopper is invoked. Calling
        # root.after from the worker would still enter Tcl on the wrong thread.
        ui_thread_id = int(
            getattr(getattr(self, "overlay", None), "_ui_thread_id", threading.get_ident())
        )
        if threading.get_ident() != ui_thread_id:
            pending = getattr(self, "_cross_thread_calls", None)
            if pending is None:
                log.error("panic stop could not reach the UI dispatcher")
                return
            pending.put(self.panic_stop)
            return

        log.info("panic stop requested")
        self.cancel()
        runtime = getattr(self, "_wake_runtime", None)
        if runtime is not None:
            runtime.suspend()
        elif getattr(self, "wake_listener", None) is not None:
            self.wake_listener.stop()
        self.stop_scribe()
        if getattr(self, "meeting", None) is not None:
            self.meeting.stop()
        # Preparing a cold caption model has not acquired a microphone yet.
        # Cancel it too, so it cannot open one after Panic Stop returns.
        self.stop_captions_stream()
        self.stop_microphone_check()
        registry = microphone_registry()
        remaining = registry.stop_all()
        if remaining:
            owners = tuple(owner for owner in registry.owners() if owner.name in remaining)
            pending = tuple(owner for owner in owners if owner.phase == "closing")
            refused = tuple(owner for owner in owners if owner.phase != "closing")
            if refused:
                # Deliberately loud. If a surface refuses even to enter its
                # close path, the person pressing panic needs that to be
                # discoverable rather than silent.
                names = tuple(owner.name for owner in refused)
                log.error("panic stop could not release: %s", ", ".join(names))
                self.overlay.set_state(
                    "error",
                    "Panic stopped dictation, but a registered mic test did not close.",
                    ", ".join(names),
                )
            elif pending:
                # A Windows audio driver can close on a worker so the UI never
                # hangs. Keep the owner disclosed and say exactly what is still
                # happening; "off" is reserved for the confirmed release.
                pending_names = tuple(owner.name for owner in pending)
                deadline = time.monotonic() + 5.0
                self.overlay.set_state(
                    "processing",
                    "Panic Stop is closing a registered mic test.",
                    ", ".join(pending_names),
                )

                def confirm_closed() -> None:
                    # Confirm the global privacy claim, not only disappearance
                    # of the original tokens. A buggy queued restart or another
                    # surface opening mid-close must never let this say "off"
                    # while the registry still names a live owner.
                    still_open = registry.owners()
                    if not still_open:
                        self.overlay.set_state(
                            "captured",
                            "Panic Stop completed for dictation and registered mic tests.",
                            "Other capture tools keep their own visible stop control.",
                        )
                        return
                    if time.monotonic() >= deadline:
                        names = tuple(owner.name for owner in still_open)
                        log.error("panic stop timed out closing: %s", ", ".join(names))
                        self.overlay.set_state(
                            "error",
                            "A registered microphone test did not finish closing.",
                            ", ".join(names),
                        )
                        return
                    self.overlay.root.after(50, confirm_closed)

                self.overlay.root.after(50, confirm_closed)

    def status_snapshot(self) -> dict[str, Any]:
        # X-354, from a ghosted setup window on the founder's PC: this is
        # called from the Tk thread (the pill menu, and onboarding's key
        # rehearsal poll at 32ms), while start_session holds self.lock on the
        # dispatch worker through operations that can each take seconds on a
        # slow machine -- a credential read through lsass, model preflight,
        # session arming, the COM mute guard. An unconditional acquire here
        # parks the UI thread behind all of that: Windows ghosts the window
        # at 5 seconds, and if the holder wedges, the app is dead to the eye
        # with nothing in the log. A status readout is advisory; it must
        # NEVER buy consistency with the UI thread's liveness. Bounded wait,
        # and on timeout the previous snapshot serves, marked stale.
        acquired = self.lock.acquire(timeout=0.2)
        if not acquired:
            cached = getattr(self, "_last_status_snapshot", None)
            if isinstance(cached, dict):
                stale = dict(cached)
                stale["stale"] = True
                return stale
            return {"app": "running", "version": APP_VERSION, "stale": True}
        try:
            session = self.session
            session_mode = self.session_mode
            session_control = self.session_control
            closing_dictation = bool(
                getattr(self, "_dictation_closing_sessions", set())
            )
        finally:
            self.lock.release()
        registry = microphone_registry()
        registry_active = registry.is_active()
        dictation_owners = (
            (("dictation",) if session is not None else ())
            + (("dictation (closing)",) if closing_dictation else ())
        )
        snapshot = {
            "app": "running",
            "version": APP_VERSION,
            "overlay_state": self.overlay.state,
            "session_active": session is not None,
            "session_running": bool(session and session.running),
            # Compatibility field with an explicit scope: ordinary dictation
            # plus auxiliary surfaces that joined MicrophoneRegistry. Legacy
            # capture tools keep their own visible stop controls and are not
            # falsely inferred from an empty registry.
            "microphone_in_use": (
                session is not None or closing_dictation or registry_active
            ),
            "microphone_owners": ", ".join(
                dictation_owners + registry.names()
            ) or "none",
            "microphone_status_scope": "dictation and registered auxiliary tests",
            "dictation_close_pending": closing_dictation,
            "session_mode": session_mode,
            "session_control": session_control,
            "stt_provider": provider_label(selected_provider_id(self.config)),
            "model": selected_model_id(self.config, selected_provider_id(self.config)),
            "language": self.config.get("deepgram", {}).get("language", "en-US"),
            "auto_paste": bool(self.config.get("dictation", {}).get("auto_paste", True)),
            "mute_output_while_recording": bool(self.config.get("dictation", {}).get("mute_output_while_recording", True)),
            "hide_over_fullscreen_media": bool(self.config.get("overlay", {}).get("hide_over_fullscreen_media", True)),
            "save_history": bool(self.config.get("privacy", {}).get("save_history", True)),
            "history_backend": history_backend(self.config),
            "config_path": str(config_path()),
            "history_path": str(history_path()),
            "live_draft_path": str(live_draft_path()),
            "full_history_path": str(full_history_path()),
            "update_check_on_start": bool(self.config.get("updates", {}).get("check_on_start", True)),
            "update_auto_download": bool(self.config.get("updates", {}).get("auto_download", False)),
            "update_latest_version": str(self.config.get("updates", {}).get("latest_version", "")),
            "update_latest_release_url": str(self.config.get("updates", {}).get("latest_release_url", "")),
        }
        # X-366: whether AI finishing can actually run, and if not why. The
        # text lands either way, so without this the product quietly writes
        # worse than it can and the only trace is a log line.
        try:
            from .llm import finishing_status

            verdict = finishing_status(self.config)
            snapshot["finishing_ok"] = bool(verdict.get("ok"))
            snapshot["finishing_reason"] = str(verdict.get("reason", ""))
            snapshot["finishing_message"] = str(verdict.get("message", ""))
        except Exception:
            log.debug("could not read finishing status", exc_info=True)
        # The stale-serve above depends on this being stamped on every
        # successful pass; a snapshot that was never taken cannot go stale.
        self._last_status_snapshot = snapshot
        return snapshot

    def play_landing_sound(self) -> None:
        """X-338: the finish chime plays when the words LAND, not when the
        microphone releases. One ding per dictation, exactly at paste."""
        if getattr(self, "_landing_sound_pending", False):
            self._landing_sound_pending = False
            self.play_sound("off")

    def play_sound(self, kind: str) -> None:
        # X-26: a chime through a live call microphone is the single most
        # embarrassing sound this app can make. Dictation keeps working in a
        # meeting -- only the noise stops.
        try:
            from .meeting_quiet import meeting_in_progress

            if meeting_in_progress(self.config):
                return
        except Exception:
            log.debug("meeting-quiet probe failed; chime plays", exc_info=True)
        dictation = self.config.get("dictation", {})
        # X-26: a chime through a live call microphone is the single most
        # embarrassing sound this app can make. Dictation keeps working in a
        # meeting -- only the noise stops.
        try:
            from .meeting_quiet import meeting_in_progress

            if meeting_in_progress(self.config):
                return
        except Exception:
            log.debug("meeting-quiet probe failed; chime plays", exc_info=True)
        name = dictation.get("sound_off", "wood_block") if kind == "off" else dictation.get("sound_on", "felted_halo")
        play_chime(kind, enabled=bool(dictation.get("play_sounds", True)), name=str(name))

    def begin_activation_guards(self) -> None:
        dictation = self.config.get("dictation", {})
        self.overlay.set_session_visible(True)
        self.output_mute_guard.start(
            enabled=bool(dictation.get("mute_output_while_recording", True)),
            fade_ms=int(dictation.get("mute_fade_ms", 180)),
        )

    def release_activation_guards(self) -> None:
        self.output_mute_guard.stop(fade_ms=int(self.config.get("dictation", {}).get("mute_fade_in_ms", 240)))
        self.overlay.set_session_visible(False)

    def clear_live_draft(self) -> None:
        """Empty the crash-recovery draft. Cheap no-op when already empty."""
        try:
            path = live_draft_path()
            if path.exists() and path.stat().st_size:
                path.write_text("", encoding="utf-8")
        except OSError:
            log.debug("live draft clear skipped", exc_info=True)

    def write_live_draft(self, mode: str, text: str, is_final: bool) -> None:
        """X-222: "Save local transcript history" off has to mean off.

        This draft is a plaintext copy of the same words History stores, kept
        so a hard crash or a power cut does not lose a half-finished dictation.
        It was written unconditionally, so somebody who had deliberately turned
        history OFF still had their last dictation sitting on disk in the
        clear, with nothing in the app saying so and no way to reach it.

        It obeys the same switch as add_history now, and anything already in it
        goes too: a setting that only stops the NEXT dictation leaves the last
        one behind, which is the worst of both.

        THE COST, stated rather than buried: with history off there is no crash
        recovery. That is the correct reading of the request -- somebody who
        asks for nothing on disk has asked for nothing on disk -- but it is a
        real capability they lose, not a free win.
        """
        if not self.config.get("privacy", {}).get("save_history", True):
            self.clear_live_draft()
            return
        text = text.strip()
        if not text:
            return
        try:
            path = live_draft_path()
            status = "final-ish" if is_final else "interim"
            atomic_write_text(
                path,
                f"Talk DAT! live draft\n"
                f"Updated: {timestamp()}\n"
                f"Mode: {mode}\n"
                f"Status: {status}\n\n"
                f"{text}\n",
            )
        except Exception:
            # Crash recovery is best-effort. A draft failure must never block
            # the primary transcript formatting and paste path.
            log.exception("live draft write failed")

    def add_history(self, entry: dict[str, Any]) -> None:
        # X-29: the markdown mirror rides the same funnel every kind of
        # delivery already passes through -- off by default, never able to
        # fail the history write it sits beside.
        try:
            from .export_markdown import append_dictation

            append_dictation(self.config, str(entry.get("text", "")))
        except Exception:
            log.debug("markdown mirror skipped this entry", exc_info=True)
        # X-39: every accepted dictation is a style vote.
        try:
            from .style_profile import observe

            profile = self.config.setdefault("style_profile", {})
            observe(profile, str(entry.get("text", "")))
        except Exception:
            log.debug("style vote skipped", exc_info=True)
        try:
            store = create_history_store(self.config)
            store.append(entry)
            self.append_full_history(entry)
            limit = int(self.config.get("privacy", {}).get("history_limit", 0))
            if limit > 0:
                store.trim(limit)
        except OSError:
            # The transcript is already delivered, so this is not worth
            # interrupting anyone over -- but it is why History looks like it
            # skipped a dictation, and that is worth being able to find out.
            log.warning("could not record this dictation in history", exc_info=True)

    def append_full_history(self, entry: dict[str, Any]) -> None:
        try:
            path = full_history_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            entry_type = str(entry.get("type", "entry")).replace("_", " ")
            lines = [
                "",
                "=" * 72,
                f"{timestamp()} - {entry_type}",
                "=" * 72,
            ]
            original = str(entry.get("original", "")).strip()
            command = str(entry.get("command", "")).strip()
            text = str(entry.get("text", "")).strip()
            url = str(entry.get("url", "")).strip()
            transform = str(entry.get("transform", "")).strip()
            if command:
                lines.extend(["", "Command:", command])
            if transform:
                lines.extend(["", "Transform:", transform])
            if original:
                lines.extend(["", "Raw / original:", original])
            if text:
                lines.extend(["", "Final / pasted:", text])
            if url:
                lines.extend(["", "Opened URL:", url])
            if not any([original, command, text, url, transform]):
                lines.extend(["", json.dumps(entry, ensure_ascii=False, indent=2)])
            with path.open("a", encoding="utf-8") as file:
                file.write("\n".join(lines).rstrip() + "\n")
            trim_full_history(path, self.config)
        except OSError:
            pass


    def read_last_history_text(self) -> str:
        try:
            return create_history_store(self.config).last_text()
        except OSError:
            return ""

    def is_current(self, token: object) -> bool:
        with self.lock:
            return token is self.session_token

    def _reserve_deferred_delivery(
        self,
        origin_token: object = _DYNAMIC_GUIDED_SINK,
    ) -> tuple[object, object | None] | None:
        """Own a deferred external result without depending on session cleanup.

        A completed voice flight clears ``session_token`` in ``finally`` before
        its optional refinement or rewrite returns. The captured origin may
        therefore transition from its token to ``None`` and remain valid. Any
        different token, explicit cancellation, or newer deferred operation
        invalidates the claim.
        """

        explicit_origin = origin_token is not _DYNAMIC_GUIDED_SINK
        with self.lock:
            if explicit_origin and self.session_token is not origin_token:
                return None
            captured_origin = self.session_token if not explicit_origin else origin_token
            owner = object()
            self._deferred_delivery_owner = owner
            return owner, captured_origin

    def _deferred_delivery_is_current(
        self,
        claim: tuple[object, object | None] | None,
    ) -> bool:
        if claim is None:
            return False
        owner, origin_token = claim
        with self.lock:
            return (
                self._deferred_delivery_owner is owner
                and self.session_token in {origin_token, None}
            )

    def _release_deferred_delivery(
        self,
        claim: tuple[object, object | None] | None,
    ) -> None:
        if claim is None:
            return
        owner, _origin_token = claim
        with self.lock:
            if self._deferred_delivery_owner is owner:
                self._deferred_delivery_owner = None

    def _auxiliary_audio_exit(self, resume):
        self._quitting = True
        self.stop_scribe()
        meeting = getattr(self, "meeting", None)
        if meeting is not None:
            meeting.stop()
        self.stop_captions_stream()
        self.stop_microphone_check()
        practice = getattr(self, "_pronunciation_practice", None)
        if practice is not None:
            practice.cancel()
        runtime = getattr(self, "_wake_runtime", None)
        wake = getattr(self, "wake_listener", None)
        if runtime is not None:
            runtime.stop()
        elif wake is not None:
            wake.stop()
        registry = microphone_registry()
        registry.stop_all()
        engine = getattr(self, "_scribe_engine", None)
        captures = [
            getattr(engine, "recorder", None),
            getattr(meeting, "_recorder", None),
            wake,
        ]
        from .plugins import request_reload
        plugin_close = getattr(self, "_plugin_quit_close", None)
        if plugin_close is None:
            plugin_close = self._plugin_quit_close = request_reload(None)
        pending = not plugin_close.is_set() or registry.is_active() or any(
            item is not None and not item.closed.is_set() for item in captures
        )
        if pending:
            deadline = getattr(self, "_meeting_quit_deadline", None)
            if deadline is None:
                deadline = self._meeting_quit_deadline = time.monotonic() + 12
            if time.monotonic() < deadline:
                self.overlay.root.after(100, resume)
            else:
                self._meeting_quit_deadline = None
                self._quitting = False
                self.overlay.set_state(
                    "error",
                    "An audio device is still closing.",
                    "Use Panic Stop to retry before leaving. Your original recordings are kept.",
                )
            return False
        self._meeting_quit_deadline = None
        return True

    def quit(self, *, settings_confirmed: bool = False) -> None:
        if threading.get_ident() != getattr(
            getattr(self, "overlay", None), "_ui_thread_id", threading.get_ident()
        ):
            self._cross_thread_calls.put(
                lambda: self.quit(settings_confirmed=settings_confirmed)
            )
            return
        if getattr(self, "_reset_in_progress", False) and not getattr(self, "_reset_finished", False):
            return
        shell = getattr(self, "web_shell", None)
        if (
            shell is not None
            and not settings_confirmed
            and shell.confirm_exit(lambda: self.quit(settings_confirmed=True))
        ):
            return
        if not self._auxiliary_audio_exit(lambda: self.quit(settings_confirmed=True)):
            return
        log.info("Talk DAT! quitting")
        practice = getattr(self, "_pronunciation_practice", None)
        if practice is not None:
            practice.cancel()
        if not getattr(self, "_reset_finished", False):
            with contextlib.suppress(Exception):
                self.remind_about_update(TRIGGER_QUIT)
        with self.lock:
            session = self.session
            capture = self.safety_capture
            self.session = None
            self.session_token = None
            self._guided_delivery_token = None
            self._deferred_delivery_owner = None
            self.safety_capture = None
            self.safety_capture_token = None
            self.safety_capture_failure_token = None
        if session:
            session.cancel()
            with contextlib.suppress(Exception):
                session.join(1.5)
            self.finalize_safety_capture(
                capture,
                status="app_closed",
                raw_transcript=str(getattr(session, "current_text", lambda: "")() or ""),
                error="Talk DAT! closed before delivery. The captured audio remains available in History.",
            )
        elif capture is not None:
            self.finalize_safety_capture(
                capture,
                status="app_closed",
                error="Talk DAT! closed before delivery. The captured audio remains available in History.",
            )
        if self.meeting is not None:
            self.meeting.stop()
        if self.wake_listener is not None:
            self.wake_listener.stop()
        if self.control_server is not None:
            self.control_server.stop()
        self.release_activation_guards()
        self.hotkeys.stop()
        self.tray.stop()
        # Resizable utility windows keep their latest logical dimensions in the
        # shared config as they settle. Flush that lightweight UI state before
        # destroying the Tk tree so quitting with a window still open does not
        # lose its cross-DPI restore receipt.
        if not getattr(self, "_reset_finished", False):
            with contextlib.suppress(Exception):
                save_config(self.config)
        if shell is not None:
            shell.close()
        # Split root: the Pill is a Toplevel on macOS; the interpreter root is
        # overlay._tk_root, and destroying THAT is what ends the process.
        self.overlay.root.after(0, self.overlay._tk_root.destroy)


def preview(text: str, limit: int) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


#: Reasons the local writing model stood down, said as advice. Since
#: 2026-09-23 an error's second line is shown to the person under the Pill,
#: so an internal code such as "too_slow" must never reach it verbatim.
LOCAL_FINISH_ADVICE = {
    "too_slow": (
        "This computer needs longer than the formatting time budget allows. Your words still "
        "arrived. To use the model, raise the budget in Settings > Writing > Formatting."
    ),
}


def local_finish_advice(notice: str) -> str:
    """What to do about a local-formatter notice, in plain words."""
    code = " ".join(str(notice or "").split())
    advice = LOCAL_FINISH_ADVICE.get(code.lower())
    if advice:
        return advice
    return preview(code, 112) if code else "Your words still arrived. Check the writing model in Settings > Writing > Formatting."


def config_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def main() -> None:
    import sys

    if "--document-export-smoke" in sys.argv[1:]:
        from .pdf_export_smoke import run
        run()
        return
    if "--local-runtime-smoke" in sys.argv[1:]:
        _run_local_runtime_smoke()
        return
    if "--check-permissions" in sys.argv[1:]:
        sys.exit(_print_permission_report())
    cli_actions = {"--toggle": "/toggle", "--cancel": "/cancel", "--paste-last": "/paste-last", "--copy-last": "/copy-last", "--status": "/status"}
    requested = [cli_actions[arg] for arg in sys.argv[1:] if arg in cli_actions]
    if requested:
        _run_cli(requested[0])
        return
    configure_logging()
    # X-113: the receive half of talkdat://. The browser launches a second
    # copy of this exe with the URI as its argument; until now NOTHING read
    # argv for it, so the sign-in landed on an "already running" message box
    # (or, cold, on an app that never looked). Stashing on both branches
    # reuses the one delivery path: the primary's handoff watcher claims the
    # file within about a second.
    from .handoff import parse_signin_code, stash_uri_for_primary

    protocol_uri = next((arg for arg in sys.argv[1:] if arg.lower().startswith("talkdat:")), "")
    if already_running():
        if protocol_uri and parse_signin_code(protocol_uri):
            stash_uri_for_primary(protocol_uri)
            return
        show_already_running_message()
        return
    if protocol_uri and parse_signin_code(protocol_uri):
        stash_uri_for_primary(protocol_uri)
    app = TalkDatApp()
    app.run()


def _run_local_runtime_smoke() -> None:
    """Exercise frozen local-STT imports and optionally transcribe a WAV file."""
    import importlib.metadata
    import os
    import sys
    import tempfile
    import traceback
    import wave

    result_path = Path(
        os.environ.get("TALK_DAT_SMOKE_RESULT", "").strip()
        or Path(tempfile.gettempdir(), "talk-dat-local-runtime-smoke.json")
    )
    result: dict[str, Any] = {"success": False, "frozen": bool(getattr(sys, "frozen", False))}
    try:
        import faster_whisper
        import onnx_asr

        result["onnx_asr_version"] = importlib.metadata.version("onnx-asr")
        result["faster_whisper_version"] = importlib.metadata.version("faster-whisper")
        result["onnx_asr_loader"] = callable(getattr(onnx_asr, "load_model", None))
        result["faster_whisper_loader"] = callable(getattr(faster_whisper, "WhisperModel", None))
        if not result["onnx_asr_loader"] or not result["faster_whisper_loader"]:
            raise RuntimeError("A packaged local speech engine did not expose its model loader.")

        wav_path = os.environ.get("TALK_DAT_LOCAL_SMOKE_WAV", "").strip()
        if wav_path:
            from .local_stt import DEFAULT_LOCAL_MODEL_ID, transcribe

            with wave.open(wav_path, "rb") as source:
                if source.getsampwidth() != 2:
                    raise RuntimeError("Local runtime smoke WAV must be 16-bit PCM.")
                transcript = transcribe(
                    model_id=DEFAULT_LOCAL_MODEL_ID,
                    pcm16=source.readframes(source.getnframes()),
                    sample_rate=source.getframerate(),
                    channels=source.getnchannels(),
                    language="en-US",
                ).strip()
            if not transcript:
                raise RuntimeError("Packaged local speech inference returned an empty transcript.")
            result["transcript"] = transcript
        result["success"] = True
    except Exception as exc:
        result["error"] = str(exc) or exc.__class__.__name__
        result["traceback"] = traceback.format_exc()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if not result["success"]:
        raise SystemExit(1)


def _launched_from_a_terminal() -> bool:
    """Whether this process was started from a shell rather than by Finder.

    macOS attributes TCC decisions to the "responsible process", which for
    anything started from a shell is the terminal application. That makes a
    permission check run from a terminal answer a different question than the
    one being asked.
    """
    if not mac_support.IS_MAC:
        return False
    import os

    # Finder and `open` hand the app to launchd, so a bundle started the normal
    # way has pid 1 as its parent. Anything else -- a shell, a build script, an
    # IDE -- stays the parent and carries its own TCC identity. isatty() was
    # tried first and is wrong: redirecting the output of a command run from a
    # shell makes it report False.
    #
    # No try/except here on purpose: getppid() cannot fail, and a silent handler
    # on this path is what test_failures_are_visible exists to prevent.
    return os.getppid() != 1


def _print_permission_report() -> int:
    """Report whether macOS is letting the app do its job, and exit non-zero if not.

    "Dictation does nothing when I hold the key" has one overwhelmingly likely
    cause on macOS and no visible symptom: without Accessibility the key listener
    starts, is refused, and reports nothing ever again. This turns that into one
    command with a plain answer, for support and for anyone verifying an install.

    Two things make the answer easy to get wrong, and both are reported here
    rather than left as traps:

    - macOS grants the permission to a code signature, so `python talk_dat.py`
      from a checkout is a different application to the OS than the installed
      bundle, and answers for itself.
    - A process started from a terminal is attributed to the *terminal*. Run
      this from Terminal and it will cheerfully report "granted" because
      Terminal has Accessibility, while the app launched from Finder does not.
      That is exactly backwards from what the person asking needs to know.
    """
    if not mac_support.IS_MAC:
        print("Permissions: nothing to check on this platform.")
        return 0

    report = mac_support.permission_report()
    outstanding = permissions_outstanding(report)
    pages = {page.key: page for page in permission_pages()}
    inherited = _launched_from_a_terminal()

    print("Talk DAT! permission check")
    # X-23: all three, not just Accessibility. Input Monitoring is a separate
    # switch in a separate list, and a Mac with Accessibility granted and Input
    # Monitoring refused -- the ordinary shape -- used to report a clean bill of
    # health while the trigger did nothing.
    for key in mac_support.PERMISSION_ORDER:
        page = pages.get(key)
        label = (page.label if page else key).ljust(16)
        state = report.get(key, "unknown")
        print(f"  {label}: {state if state != 'not asked' else 'not granted yet'}")
    if inherited:
        print()
        print("  WARNING: started from a terminal, so these are the terminal's")
        print("  permissions, not the app's. macOS attributes a process launched")
        print("  from a shell to that shell. To see what the app itself has,")
        print("  launch it normally and read the last few lines of:")
        print(f"    {app_dir() / 'talk-dat.log'}")
    for key in outstanding:
        page = pages.get(key)
        if page is None:
            continue
        print()
        print(f"  {page.breaks}")
        print("  Turn Talk DAT! on under:")
        print(f"    System Settings > {page.settings_path}")
    return 1 if outstanding else 0


def _run_cli(route: str) -> None:
    """Send a control command to the running app via the local control API."""
    import urllib.request

    config = load_config()
    remote = config.get("remote", {})
    if not remote.get("enabled", False):
        print("The local control API is disabled. Enable remote.enabled in Settings first.")
        return
    port = int(remote.get("port", 4670))
    token = str(remote.get("token", "")).strip()
    url = f"http://127.0.0.1:{port}{route}"
    if token:
        url += f"?token={token}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            print(response.read().decode("utf-8"))
    except OSError as exc:
        print(f"Could not reach Talk DAT! on port {port}: {exc}")
