from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow.app import TalkDatApp, atomic_write_text
from knight_flow.paste import PasteReceipt
from knight_flow.translation import DEFAULT_TRANSLATION_MODEL, TranslationError, TranslationResult


EDIT_TARGET_A = (191, 291, 10, 20, 12, 38)
EDIT_TARGET_B = (191, 292, 10, 74, 12, 92)


class _Overlay:
    def __init__(self) -> None:
        self.states: list[tuple[str, str]] = []
        self.onboarding_test_sink = None
        self.root = SimpleNamespace(after=lambda _delay, callback: callback())

    def set_state(self, state: str, message: str = "", _preview: str = "") -> None:
        self.states.append((state, message))

    def set_level(self, _level: float) -> None:
        return


class CrashRecoveryTests(unittest.TestCase):
    def test_atomic_live_draft_replaces_file_without_leaving_temporary_bytes(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            draft = directory / "live-draft.txt"
            draft.write_text("old draft", encoding="utf-8")

            atomic_write_text(draft, "new draft")

            self.assertEqual(draft.read_text(encoding="utf-8"), "new draft")
            self.assertEqual(list(directory.glob(".live-draft.txt.*.tmp")), [])

    def test_session_live_draft_uses_atomic_writer_contract(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            draft = Path(temporary_directory) / "live-transcript-draft.txt"
            app = TalkDatApp.__new__(TalkDatApp)
            # X-222: the draft now obeys privacy.save_history, so a bare object
            # with no config would AttributeError. Given one that says history
            # is ON, which is what this test has always been about.
            app.config = {"privacy": {"save_history": True}}

            with patch("knight_flow.app.live_draft_path", return_value=draft):
                app.write_live_draft("dictation", "Transcript ready to paste.", True)

            content = draft.read_text(encoding="utf-8")
            self.assertIn("Status: final-ish", content)
            self.assertIn("Transcript ready to paste.", content)


def _app(token: object, *, error: str = "") -> TalkDatApp:
    app = TalkDatApp.__new__(TalkDatApp)
    app.lock = threading.RLock()
    app.session = object()
    app.session_token = token
    app._guided_delivery_token = None
    app._deferred_delivery_owner = None
    app.session_chime_token = token
    app.session_mode = "dictation"
    app.session_control = "hold"
    app.session_error_message = error
    app.safety_capture = None
    app.safety_capture_token = None
    app.safety_capture_failure_token = None
    app._session_audio_already_saved = False
    app.last_transcript = ""
    app.last_original = ""
    app.last_diff = ""
    app.overlay = _Overlay()
    app.config = {"providers": {"active": "deepgram"}}
    app.release_activation_guards = lambda: None
    app.play_sound = lambda _name: None
    app.write_live_draft = lambda *_args: None
    return app


class _CapturedSession:
    def __init__(self, *, degraded: bool, seconds: float = 10.0) -> None:
        self.transport_degraded = degraded
        self._samples = int(16000 * seconds)

    def captured_audio(self) -> tuple[bytes, int, int, bool]:
        # Ten seconds by default: the retry heuristics compare transcript
        # density against audio DURATION, so a fixture standing in for "a
        # long recording that lost most of its words" must actually be long.
        return b"\xff\x1f" * self._samples, 16000, 1, True


class _QueuedRoot:
    def __init__(self) -> None:
        self.callbacks: list[object] = []
        self.queued = threading.Event()

    def after(self, _delay: int, callback: object) -> None:
        self.callbacks.append(callback)
        self.queued.set()

    def run_next(self) -> None:
        callback = self.callbacks.pop(0)
        callback()


class _SafetyCapture:
    session_id = "protected-test-session"
    audio_bytes = 3200

    def __init__(self) -> None:
        self.audio: list[tuple[bytes, int, int, bool]] = []
        self.updates: list[dict[str, object]] = []
        self.finalized: list[dict[str, object]] = []

    def append(self, data: bytes, sample_rate: int, channels: int, *, heard_voice: bool = False) -> bool:
        self.audio.append((data, sample_rate, channels, heard_voice))
        return True

    def update(self, **changes: object) -> None:
        self.updates.append(changes)

    def flush(self) -> bool:
        return True

    def finalize(self, **changes: object) -> dict[str, object]:
        self.finalized.append(changes)
        return changes


class SessionLifecycleTests(unittest.TestCase):
    def test_microphone_frames_route_to_the_current_protected_session_only(self) -> None:
        token = object()
        app = _app(token)
        capture = _SafetyCapture()
        app.safety_capture = capture
        app.safety_capture_token = token

        app.on_session_audio(token, b"\x01\x00" * 100, 16000, 1, True)
        app.on_session_audio(object(), b"\x02\x00" * 100, 16000, 1, True)

        self.assertEqual(capture.audio, [(b"\x01\x00" * 100, 16000, 1, True)])

    def test_formatting_failure_keeps_protected_audio_and_raw_transcript(self) -> None:
        token = object()
        app = _app(token)
        capture = _SafetyCapture()
        app.safety_capture = capture
        app.safety_capture_token = token
        app.recover_transcript_if_needed = lambda _session, _mode, text: text

        def fail_formatting(_text: str, **_delivery: object) -> None:
            raise RuntimeError("formatter unavailable")

        app.handle_dictation = fail_formatting
        app.on_session_done(token, "dictation", "do not lose these words")

        self.assertEqual(capture.finalized[-1]["status"], "processing_failed")
        self.assertEqual(capture.finalized[-1]["raw_transcript"], "do not lose these words")
        self.assertIn("formatter unavailable", str(capture.finalized[-1]["error"]))
        self.assertEqual(app.overlay.states[-1][0], "error")

    def test_token_remains_current_until_formatting_and_paste_finish(self) -> None:
        token = object()
        app = _app(token)
        app.recover_transcript_if_needed = lambda _session, _mode, text: text
        current_during_handle: list[bool] = []
        app.handle_dictation = lambda _text, **_delivery: current_during_handle.append(app.is_current(token))

        app.on_session_done(token, "dictation", "hello")

        self.assertEqual(current_during_handle, [True])
        self.assertIsNone(app.session_token)
        self.assertEqual(app.overlay.states[0][0], "processing")

    def test_provider_error_recovers_local_audio_before_showing_terminal_error(self) -> None:
        token = object()
        app = _app(token, error="socket closed")
        app.recover_transcript_if_needed = lambda _session, _mode, _text: "recovered words"
        handled: list[str] = []
        app.handle_dictation = lambda text, **_delivery: handled.append(text)

        app.on_session_done(token, "dictation", "")

        self.assertEqual(handled, ["recovered words"])
        self.assertFalse(any(state == "error" for state, _message in app.overlay.states))

    def test_live_draft_failure_never_blocks_dictation_paste(self) -> None:
        token = object()
        app = _app(token)
        app.recover_transcript_if_needed = lambda _session, _mode, text: text
        app.write_live_draft = TalkDatApp.write_live_draft.__get__(app)
        handled: list[str] = []
        app.handle_dictation = lambda text, **_delivery: handled.append(text)

        with patch("knight_flow.app.atomic_write_text", side_effect=TypeError("draft unavailable")):
            app.on_session_done(token, "dictation", "still paste this transcript")

        self.assertEqual(handled, ["still paste this transcript"])
        self.assertIsNone(app.session_token)

    def test_guided_result_cannot_fall_through_when_page_closes_during_formatting(self) -> None:
        token = object()
        app = _app(token)
        app.config = {
            "dictation": {"auto_paste": True, "paste_mode": "clipboard"},
            "privacy": {"save_history": False},
        }
        app.recover_transcript_if_needed = lambda _session, _mode, text: text
        received: list[str] = []
        app.overlay.onboarding_test_sink = received.append
        formatting_started = threading.Event()
        continue_formatting = threading.Event()

        def delayed_format(text: str, _config: dict[str, object], **_options: object) -> SimpleNamespace:
            formatting_started.set()
            self.assertTrue(continue_formatting.wait(2.0))
            return SimpleNamespace(original=text, text="Protected result.", send_enter=False)

        with (
            patch("knight_flow.app.process_dictation", side_effect=delayed_format),
            patch("knight_flow.app.paste_text_with_receipt") as paste,
        ):
            worker = threading.Thread(
                target=app.on_session_done,
                args=(token, "dictation", "protected result"),
            )
            worker.start()
            self.assertTrue(formatting_started.wait(2.0))

            # This is the real teardown order: cancel the flight, then release
            # the surface-owned sink while formatting is still in progress.
            app.cancel()
            app.overlay.onboarding_test_sink = None
            continue_formatting.set()
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        self.assertEqual(received, [])
        paste.assert_not_called()
        # cancel() owns the terminal idle state; the stale formatter must not
        # add a second status after it returns.
        # The idle line names the chords as THIS platform spells them (Ctrl+Win
        # on Windows, Control+Command on a Mac), so compare against the builder.
        self.assertEqual(app.overlay.states[-1][1], app._idle_hint())

    def test_cancelled_formatter_cannot_overwrite_a_new_listening_session(self) -> None:
        token = object()
        app = _app(token)
        app.config = {
            "dictation": {"auto_paste": True, "paste_mode": "clipboard"},
            "privacy": {"save_history": False},
        }
        app.recover_transcript_if_needed = lambda _session, _mode, text: text
        app.overlay.onboarding_test_sink = lambda _text: None
        app.last_original = "Earlier original"
        app.last_transcript = "Earlier result"
        app.last_diff = "Earlier diff"
        formatting_started = threading.Event()
        continue_formatting = threading.Event()

        def delayed_format(text: str, _config: dict[str, object], **_options: object) -> SimpleNamespace:
            formatting_started.set()
            self.assertTrue(continue_formatting.wait(2.0))
            return SimpleNamespace(original=text, text="Stale formatted result.", send_enter=False)

        with (
            patch("knight_flow.app.process_dictation", side_effect=delayed_format),
            patch("knight_flow.app.paste_text_with_receipt") as paste,
        ):
            worker = threading.Thread(
                target=app.on_session_done,
                args=(token, "dictation", "stale flight"),
            )
            worker.start()
            self.assertTrue(formatting_started.wait(2.0))

            app.cancel()
            app.overlay.onboarding_test_sink = None
            new_token = object()
            app.session_token = new_token
            app.session = object()
            app.session_mode = "dictation"
            app.session_control = "hold"
            app.overlay.set_state("listening", "New session listening.")
            continue_formatting.set()
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        self.assertIs(app.session_token, new_token)
        self.assertEqual(app.last_original, "Earlier original")
        self.assertEqual(app.last_transcript, "Earlier result")
        self.assertEqual(app.last_diff, "Earlier diff")
        self.assertEqual(app.overlay.states[-1], ("listening", "New session listening."))
        paste.assert_not_called()

    def test_queued_guided_result_cannot_enter_a_reused_setup_sink_after_redo(self) -> None:
        old_token = object()
        app = _app(old_token)
        app.config = {
            "dictation": {"auto_paste": True, "paste_mode": "clipboard"},
            "privacy": {"save_history": False},
        }
        root = _QueuedRoot()
        app.overlay.root = root
        received: list[str] = []
        reused_sink = received.append
        app.overlay.onboarding_test_sink = reused_sink
        app._guided_delivery_token = old_token
        result: dict[str, object] = {}

        with (
            patch(
                "knight_flow.app.process_dictation",
                return_value=SimpleNamespace(
                    original="old setup words",
                    text="Old setup result.",
                    send_enter=False,
                ),
            ),
            patch("knight_flow.app.paste_text_with_receipt") as paste,
        ):
            worker = threading.Thread(
                target=lambda: result.update(
                    app.handle_dictation(
                        "old setup words",
                        delivery_token=old_token,
                        guided_sink=reused_sink,
                    )
                )
            )
            worker.start()
            self.assertTrue(root.queued.wait(2.0))

            # Redo keeps the same visible page callback but owns a new flight.
            new_token = object()
            with app.lock:
                app.session_token = new_token
                app._guided_delivery_token = None
                app.session = object()
                app.session_mode = "dictation"
                app.session_control = "hold"
            app.overlay.onboarding_test_sink = reused_sink
            app.overlay.set_state("listening", "New setup test listening.")

            root.run_next()
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        self.assertEqual(received, [])
        self.assertEqual(result["delivery"]["success"], False)
        self.assertIn(result["delivery"]["method"], {"guided_test_closed", "cancelled_before_delivery"})
        self.assertIs(app.session_token, new_token)
        self.assertEqual(app.overlay.states[-1], ("listening", "New setup test listening."))
        paste.assert_not_called()

    def test_cancel_during_slow_empty_recovery_cannot_clear_a_new_session(self) -> None:
        token = object()
        app = _app(token)
        capture = _SafetyCapture()
        app.safety_capture = capture
        app.safety_capture_token = token
        recovery_started = threading.Event()
        continue_recovery = threading.Event()
        handled: list[str] = []
        app.handle_dictation = lambda text, **_delivery: handled.append(text)

        def delayed_empty_recovery(_session: object, _mode: str, _text: str) -> str:
            recovery_started.set()
            self.assertTrue(continue_recovery.wait(2.0))
            return ""

        app.recover_transcript_if_needed = delayed_empty_recovery
        worker = threading.Thread(target=app.on_session_done, args=(token, "dictation", ""))
        worker.start()
        self.assertTrue(recovery_started.wait(2.0))

        app.cancel()
        new_token = object()
        app.session_token = new_token
        app.session = object()
        app.session_mode = "dictation"
        app.session_control = "hold"
        app.overlay.set_state("listening", "New session listening.")
        continue_recovery.set()
        worker.join(2.0)

        self.assertFalse(worker.is_alive())
        self.assertIs(app.session_token, new_token)
        self.assertEqual(handled, [])
        self.assertEqual(capture.finalized[-1]["status"], "cancelled")
        self.assertEqual(app.overlay.states[-1], ("listening", "New session listening."))
        self.assertFalse(any(message == "No speech captured. Ready again." for _state, message in app.overlay.states))

    def test_cancel_during_slow_command_recovery_never_runs_the_stale_command(self) -> None:
        token = object()
        app = _app(token)
        recovery_started = threading.Event()
        continue_recovery = threading.Event()
        commands: list[str] = []
        app.handle_command = commands.append

        def delayed_command_recovery(_session: object, _mode: str, _text: str) -> str:
            recovery_started.set()
            self.assertTrue(continue_recovery.wait(2.0))
            return "open settings"

        app.recover_transcript_if_needed = delayed_command_recovery
        worker = threading.Thread(target=app.on_session_done, args=(token, "command", ""))
        worker.start()
        self.assertTrue(recovery_started.wait(2.0))

        app.cancel()
        new_token = object()
        app.session_token = new_token
        app.session = object()
        app.session_mode = "dictation"
        app.session_control = "hold"
        app.overlay.set_state("listening", "New session listening.")
        continue_recovery.set()
        worker.join(2.0)

        self.assertFalse(worker.is_alive())
        self.assertEqual(commands, [])
        self.assertIs(app.session_token, new_token)
        self.assertEqual(app.overlay.states[-1], ("listening", "New session listening."))

    def test_cancelled_formatter_exception_cannot_paint_over_a_new_session(self) -> None:
        token = object()
        app = _app(token)
        app.config = {
            "dictation": {"auto_paste": True, "paste_mode": "clipboard"},
            "privacy": {"save_history": False},
        }
        app.recover_transcript_if_needed = lambda _session, _mode, text: text
        formatting_started = threading.Event()
        continue_formatting = threading.Event()

        def delayed_failure(_text: str, _config: dict[str, object], **_options: object) -> object:
            formatting_started.set()
            self.assertTrue(continue_formatting.wait(2.0))
            raise RuntimeError("old formatter failed")

        with patch("knight_flow.app.process_dictation", side_effect=delayed_failure):
            worker = threading.Thread(
                target=app.on_session_done,
                args=(token, "dictation", "stale flight"),
            )
            worker.start()
            self.assertTrue(formatting_started.wait(2.0))

            app.cancel()
            new_token = object()
            app.session_token = new_token
            app.session = object()
            app.session_mode = "dictation"
            app.session_control = "hold"
            app.overlay.set_state("listening", "New session listening.")
            continue_formatting.set()
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        self.assertIs(app.session_token, new_token)
        self.assertEqual(app.overlay.states[-1], ("listening", "New session listening."))
        self.assertFalse(any(state == "error" for state, _message in app.overlay.states[-1:]))

    def test_session_error_waits_for_done_callback_before_releasing_guards(self) -> None:
        token = object()
        app = _app(token)
        released: list[bool] = []
        app.release_activation_guards = lambda: released.append(True)

        app.on_session_error(token, "network interrupted")

        self.assertEqual(released, [])
        self.assertEqual(app.session_error_message, "network interrupted")
        self.assertEqual(app.overlay.states[-1][0], "processing")

    def test_degraded_partial_transcript_retries_complete_safety_audio(self) -> None:
        app = _app(object())
        app.config["dictation"] = {"retry_failed_capture": True, "safety_recordings_enabled": False}
        session = _CapturedSession(degraded=True)

        with patch(
            "knight_flow.app.transcribe_pcm",
            return_value="complete transcript recovered from the entire captured recording",
        ) as transcribe:
            result = app.recover_transcript_if_needed(session, "dictation", "partial transcript")

        self.assertEqual(result, "complete transcript recovered from the entire captured recording")
        transcribe.assert_called_once()

    def test_degraded_but_complete_transcript_is_kept_without_reprocessing(self) -> None:
        """The founder's 09:59 case: 27 seconds of speech, a full transcript
        in hand, and only the socket's goodbye lost -- the old code burned
        14 seconds of CPU re-transcribing it locally under a toast claiming
        the words were local. Healthy density means DONE: no cloud retry,
        no local rescue, nothing runs twice."""
        app = _app(object())
        app.config["dictation"] = {"retry_failed_capture": True, "safety_recordings_enabled": False}
        session = _CapturedSession(degraded=True, seconds=27.0)
        live_text = " ".join(["word"] * 82)

        with patch("knight_flow.app.transcribe_pcm") as transcribe:
            result = app.recover_transcript_if_needed(session, "dictation", live_text)

        self.assertEqual(result, live_text)
        transcribe.assert_not_called()

    def test_degraded_retry_never_replaces_a_longer_usable_partial(self) -> None:
        app = _app(object())
        app.config["dictation"] = {"retry_failed_capture": True, "safety_recordings_enabled": False}
        session = _CapturedSession(degraded=True)
        live = "this partial transcript is longer and still usable"

        with patch("knight_flow.app.transcribe_pcm", return_value="short result"):
            result = app.recover_transcript_if_needed(session, "dictation", live)

        self.assertEqual(result, live)

    def test_healthy_partial_transcript_does_not_spend_a_second_request(self) -> None:
        app = _app(object())
        app.config["dictation"] = {"retry_failed_capture": True, "safety_recordings_enabled": False}
        session = _CapturedSession(degraded=False)

        with patch("knight_flow.app.transcribe_pcm") as transcribe:
            result = app.recover_transcript_if_needed(session, "dictation", "healthy transcript")

        self.assertEqual(result, "healthy transcript")
        transcribe.assert_not_called()

    def test_dictation_shows_actual_fallback_route_and_retains_content_free_receipt(self) -> None:
        app = _app(object())
        app.config = {
            "dictation": {"auto_paste": True, "paste_mode": "clipboard"},
            "privacy": {"save_history": True},
        }
        history: list[dict[str, object]] = []
        app.add_history = history.append
        receipt = PasteReceipt(
            True,
            "clipboard",
            "direct_type",
            ("clipboard", "direct_type"),
            fallback_used=True,
        )

        with (
            patch(
                "knight_flow.app.process_dictation",
                return_value=SimpleNamespace(original="private original", text="private final", send_enter=False),
            ),
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt),
        ):
            app.handle_dictation("private original")

        self.assertIn("Inserted by direct typing after automatic fallback", app.overlay.states[-1][1])
        self.assertEqual(history[0]["delivery"], receipt.as_dict())
        self.assertNotIn("private final", str(history[0]["delivery"]))

    def test_cancelled_paste_receipt_never_falls_back_to_copying_stale_text(self) -> None:
        token = object()
        app = _app(token)
        app.config = {
            "dictation": {"auto_paste": True, "paste_mode": "clipboard"},
            "privacy": {"save_history": False},
        }
        receipt = PasteReceipt(False, "clipboard", "cancelled", ("clipboard", "cancelled"))

        with (
            patch(
                "knight_flow.app.process_dictation",
                return_value=SimpleNamespace(original="old words", text="Old result.", send_enter=False),
            ),
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt),
            patch("knight_flow.app.copy_text") as copy,
        ):
            result = app.handle_dictation(
                "old words",
                delivery_token=token,
                guided_sink=None,
            )

        self.assertFalse(result["delivery"]["success"])
        self.assertEqual(result["delivery"]["method"], "cancelled_during_delivery")
        copy.assert_not_called()

    def test_cancel_during_final_copy_fallback_cannot_leak_the_old_result(self) -> None:
        old_token = object()
        app = _app(old_token)
        app.config = {
            "dictation": {"auto_paste": True, "paste_mode": "clipboard"},
            "privacy": {"save_history": False},
        }
        app.last_original = "Earlier original"
        app.last_transcript = "Earlier result"
        copy_started = threading.Event()
        continue_copy = threading.Event()
        calls = 0
        result: dict[str, object] = {}

        def delivery_route(_text: str, **options: object) -> PasteReceipt:
            nonlocal calls
            calls += 1
            if calls == 1:
                return PasteReceipt(False, "clipboard", "none", ("clipboard", "direct_type"), True)
            self.assertEqual(options["paste_mode"], "copy_only")
            can_deliver = options["can_deliver"]
            copy_started.set()
            self.assertTrue(continue_copy.wait(2.0))
            if not can_deliver():
                return PasteReceipt(False, "copy_only", "cancelled", ("copy_only", "cancelled"))
            return PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))

        with (
            patch(
                "knight_flow.app.process_dictation",
                return_value=SimpleNamespace(original="old words", text="Old result.", send_enter=False),
            ),
            patch("knight_flow.app.paste_text_with_receipt", side_effect=delivery_route),
        ):
            worker = threading.Thread(
                target=lambda: result.update(
                    app.handle_dictation(
                        "old words",
                        delivery_token=old_token,
                        guided_sink=None,
                    )
                )
            )
            worker.start()
            self.assertTrue(copy_started.wait(2.0))

            new_token = object()
            with app.lock:
                app.session_token = new_token
                app.session = object()
                app.session_mode = "dictation"
                app.session_control = "hold"
            app.overlay.set_state("listening", "New session listening.")
            continue_copy.set()
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result["delivery"]["method"], "cancelled_during_recovery_copy")
        self.assertFalse(result["delivery"]["success"])
        self.assertIs(app.session_token, new_token)
        self.assertEqual(app.last_original, "Earlier original")
        self.assertEqual(app.last_transcript, "Earlier result")
        self.assertEqual(app.overlay.states[-1], ("listening", "New session listening."))

    def test_auto_paste_off_never_claims_text_was_pasted(self) -> None:
        app = _app(object())
        app.config = {
            "dictation": {"auto_paste": False},
            "privacy": {"save_history": False},
        }
        with patch(
            "knight_flow.app.process_dictation",
            return_value=SimpleNamespace(original="hello", text="hello", send_enter=False),
        ):
            app.handle_dictation("hello")

        self.assertEqual(app.overlay.states[-1][1], "Captured locally. Auto paste is off.")

    def test_onboarding_test_receives_formatted_text_without_pasting_into_another_app(self) -> None:
        app = _app(object())
        app.config = {
            "dictation": {"auto_paste": True, "paste_mode": "clipboard"},
            "privacy": {"save_history": False},
        }
        received: list[str] = []
        app.overlay.onboarding_test_sink = received.append

        with (
            patch(
                "knight_flow.app.process_dictation",
                return_value=SimpleNamespace(original="spoken test", text="Spoken test.", send_enter=False),
            ),
            patch("knight_flow.app.paste_text_with_receipt") as paste,
        ):
            result = app.handle_dictation("spoken test")

        self.assertEqual(received, ["Spoken test."])
        self.assertEqual(result["delivery"]["method"], "onboarding_test")
        paste.assert_not_called()
        self.assertEqual(app.overlay.states[-1][1], "Setup test complete. Mic off.")

    def test_auto_translation_pastes_the_local_translation_and_records_a_receipt(self) -> None:
        app = _app(object())
        app.config = {
            "dictation": {"auto_paste": True, "paste_mode": "clipboard"},
            "privacy": {"save_history": True},
            "translation": {"enabled": True, "auto_translate_dictation": True},
        }
        history: list[dict[str, object]] = []
        app.add_history = history.append
        receipt = PasteReceipt(True, "clipboard", "clipboard", ("clipboard",))
        translated = TranslationResult("Hola", "en", "es", DEFAULT_TRANSLATION_MODEL, 1)

        with (
            patch(
                "knight_flow.app.process_dictation",
                return_value=SimpleNamespace(original="Hello", text="Hello", send_enter=False),
            ),
            patch("knight_flow.app.translate_text", return_value=translated),
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt) as paste,
        ):
            result = app.handle_dictation("Hello")

        self.assertEqual(result["text"], "Hola")
        self.assertEqual(history[0]["translation"]["target_code"], "es")
        self.assertEqual(paste.call_args.args[0], "Hola")

    def test_auto_translation_failure_pastes_the_safe_source_text(self) -> None:
        app = _app(object())
        app.config = {
            "dictation": {"auto_paste": True, "paste_mode": "clipboard"},
            "privacy": {"save_history": True},
            "translation": {"enabled": True, "auto_translate_dictation": True},
        }
        history: list[dict[str, object]] = []
        app.add_history = history.append
        receipt = PasteReceipt(True, "clipboard", "clipboard", ("clipboard",))

        with (
            patch(
                "knight_flow.app.process_dictation",
                return_value=SimpleNamespace(original="Keep this", text="Keep this", send_enter=False),
            ),
            patch("knight_flow.app.translate_text", side_effect=TranslationError("runtime", "Model unavailable")),
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt) as paste,
        ):
            result = app.handle_dictation("Keep this")

        self.assertEqual(result["text"], "Keep this")
        self.assertIn("Model unavailable", result["translation_error"])
        self.assertEqual(paste.call_args.args[0], "Keep this")
        self.assertIn("original text was kept safely", app.overlay.states[-1][1])

    def test_post_paste_refinement_is_inert_and_never_edits_a_document(self) -> None:
        old_token = object()
        app = _app(old_token)
        app._model_format_ms = []
        app._screen_names = []
        app.last_original = "old raw"
        app.last_transcript = "Old local result"

        with (
            patch("knight_flow.app.process_dictation") as process,
            patch("knight_flow.app.foreground_input_generation", return_value=17),
            patch("knight_flow.app.foreground_window_id", return_value=88),
        ):
            app._refine_after_paste(
                "old raw",
                {"dictation": {"undo_replacement": "auto"}, "cleanup": {}},
                pasted_text="Old local result",
                paste_window=88,
                pasted_at=0.0,
                sent_enter=False,
                paste_succeeded=True,
                paste_method="clipboard",
                paste_input_generation=17,
                delivery_token=old_token,
            )

        process.assert_not_called()
        self.assertEqual((app.last_original, app.last_transcript), ("old raw", "Old local result"))

    def test_new_session_invalidates_a_blocked_fix_that_rewrite(self) -> None:
        old_token = object()
        app = _app(old_token)
        app._fix_that_selection = "old selected text"
        app._fix_that_clipboard = "original clipboard"
        app._fix_that_window = 91
        app._fix_that_focus_window = 191
        app._fix_that_edit_target = EDIT_TARGET_A
        app._fix_that_input_generation = 20
        app.config["dictation"] = {"paste_mode": "clipboard"}
        started = threading.Event()
        release = threading.Event()

        def delayed_rewrite(*_args: object, **_kwargs: object) -> str:
            started.set()
            self.assertTrue(release.wait(2.0))
            return "old rewritten text"

        with (
            # X-491: Quick Fix rewrites through llm_rewrite now (local engine or the
            # person's own key), not the managed service. Same stub, new target.
            patch("knight_flow.llm.llm_rewrite", side_effect=delayed_rewrite),
            patch("knight_flow.app.foreground_window_id", return_value=91),
            patch("knight_flow.app.foreground_focus_window_id", return_value=191),
            patch("knight_flow.app.foreground_edit_target_signature", return_value=EDIT_TARGET_A),
            patch("knight_flow.app.foreground_input_generation", return_value=21),
            patch("knight_flow.app.copy_selected_text", return_value=("old selected text", "old selected text")),
            patch("knight_flow.app.paste_text_with_receipt") as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.apply_fix_that("make it clear", delivery_token=old_token)
            self.assertTrue(started.wait(2.0))
            new_token = object()
            with app.lock:
                app.session_token = new_token
                app.session = object()
                app._deferred_delivery_owner = None
            app.last_transcript = "New result"
            app.overlay.set_state("listening", "New session listening.")
            release.set()
            worker = next(t for t in threading.enumerate() if t.name == "TalkDatFixThat")
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        paste.assert_not_called()
        self.assertEqual(app.last_transcript, "New result")
        self.assertEqual(app.overlay.states[-1], ("listening", "New session listening."))

    def test_fix_that_copies_result_when_selection_changes_inside_the_same_field(self) -> None:
        token = object()
        app = _app(token)
        app._fix_that_selection = "field A selection"
        app._fix_that_clipboard = "original clipboard"
        app._fix_that_window = 91
        app._fix_that_focus_window = 191
        app._fix_that_edit_target = EDIT_TARGET_A
        app._fix_that_input_generation = 20
        receipt = PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))
        started = threading.Event()
        release = threading.Event()

        def delayed_rewrite(*_args: object, **_kwargs: object) -> str:
            started.set()
            self.assertTrue(release.wait(2.0))
            return "rewritten field A"

        with (
            patch("knight_flow.app.foreground_window_id", return_value=91),
            patch("knight_flow.app.foreground_focus_window_id", return_value=191),
            patch("knight_flow.app.foreground_edit_target_signature", return_value=EDIT_TARGET_A),
            patch("knight_flow.app.foreground_input_generation", return_value=21),
            patch(
                "knight_flow.app.copy_selected_text",
                return_value=("field B secret", "field A selection"),
            ),
            patch("knight_flow.llm.llm_rewrite", side_effect=delayed_rewrite) as rewrite,
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt) as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.apply_fix_that("make it clear", delivery_token=token)
            self.assertTrue(started.wait(2.0))
            worker = next(t for t in threading.enumerate() if t.name == "TalkDatFixThat")
            release.set()
            worker.join(2.0)

        rewrite.assert_called_once()
        # X-491: the text is POSITIONAL on llm_rewrite, where it was a keyword
        # on the managed rewrite_text. Still the assertion that matters most in
        # this test: the rewrite must be given what was selected when the user
        # asked, not whatever is under the cursor by the time it runs.
        self.assertEqual(rewrite.call_args.args[0], "field A selection")
        self.assertEqual(paste.call_args.kwargs["paste_mode"], "copy_only")
        self.assertIn("copied", app.overlay.states[-1][1].lower())

    def test_fix_that_copies_result_for_identical_text_in_a_different_focused_control(self) -> None:
        token = object()
        app = _app(token)
        app._fix_that_selection = "same text"
        app._fix_that_clipboard = "original clipboard"
        app._fix_that_window = 91
        app._fix_that_focus_window = 191
        app._fix_that_edit_target = EDIT_TARGET_A
        app._fix_that_input_generation = 20
        receipt = PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))
        started = threading.Event()
        release = threading.Event()

        def delayed_rewrite(*_args: object, **_kwargs: object) -> str:
            started.set()
            self.assertTrue(release.wait(2.0))
            return "same text improved"

        with (
            patch("knight_flow.app.foreground_window_id", return_value=91),
            patch("knight_flow.app.foreground_focus_window_id", return_value=192),
            patch("knight_flow.app.foreground_edit_target_signature", return_value=EDIT_TARGET_B),
            patch("knight_flow.app.foreground_input_generation", return_value=21),
            patch("knight_flow.app.copy_selected_text") as copy_selection,
            patch("knight_flow.llm.llm_rewrite", side_effect=delayed_rewrite) as rewrite,
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt) as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.apply_fix_that("make it clear", delivery_token=token)
            self.assertTrue(started.wait(2.0))
            worker = next(t for t in threading.enumerate() if t.name == "TalkDatFixThat")
            release.set()
            worker.join(2.0)

        copy_selection.assert_not_called()
        rewrite.assert_called_once()
        self.assertEqual(paste.call_args.kwargs["paste_mode"], "copy_only")
        self.assertIn("copied", app.overlay.states[-1][1].lower())

    def test_fix_that_shared_renderer_signature_change_can_never_auto_paste(self) -> None:
        token = object()
        app = _app(token)
        app._fix_that_selection = "same text"
        app._fix_that_clipboard = "original clipboard"
        app._fix_that_window = 91
        app._fix_that_focus_window = 191
        app._fix_that_edit_target = EDIT_TARGET_A
        app._fix_that_input_generation = 20
        receipt = PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))
        started = threading.Event()
        release = threading.Event()

        def delayed_rewrite(*_args: object, **_kwargs: object) -> str:
            started.set()
            self.assertTrue(release.wait(2.0))
            return "safer result"

        with (
            patch("knight_flow.app.foreground_window_id", return_value=91),
            patch("knight_flow.app.foreground_focus_window_id", return_value=191),
            patch("knight_flow.app.foreground_edit_target_signature", return_value=EDIT_TARGET_B),
            patch("knight_flow.app.foreground_input_generation", return_value=21),
            patch("knight_flow.app.copy_selected_text") as copy_selection,
            patch("knight_flow.llm.llm_rewrite", side_effect=delayed_rewrite),
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt) as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.apply_fix_that("make it clear", delivery_token=token)
            self.assertTrue(started.wait(2.0))
            worker = next(t for t in threading.enumerate() if t.name == "TalkDatFixThat")
            release.set()
            worker.join(2.0)

        copy_selection.assert_not_called()
        self.assertEqual(paste.call_args.kwargs["paste_mode"], "copy_only")

    def test_fix_that_target_race_falls_back_to_one_owner_only_clipboard_copy(self) -> None:
        token = object()
        app = _app(token)
        app._fix_that_selection = "same text"
        app._fix_that_clipboard = "original clipboard"
        app._fix_that_window = 91
        app._fix_that_focus_window = 191
        app._fix_that_edit_target = EDIT_TARGET_A
        app._fix_that_input_generation = 20
        app.config["dictation"] = {
            "paste_mode": "clipboard",
            "restore_clipboard_after_paste": True,
        }
        started = threading.Event()
        release = threading.Event()
        modes: list[str] = []

        def delayed_rewrite(*_args: object, **_kwargs: object) -> str:
            started.set()
            self.assertTrue(release.wait(2.0))
            return "race-safe rewrite"

        def delivery(_text: str, **options: object) -> PasteReceipt:
            mode = str(options["paste_mode"])
            modes.append(mode)
            allowed = options["can_deliver"]
            self.assertTrue(callable(allowed))
            if mode == "clipboard":
                self.assertFalse(allowed())
                return PasteReceipt(False, "clipboard", "cancelled", ("clipboard", "cancelled"))
            self.assertTrue(allowed())
            return PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))

        signatures = iter((EDIT_TARGET_A, EDIT_TARGET_A, EDIT_TARGET_B))
        with (
            patch("knight_flow.app.foreground_window_id", return_value=91),
            patch("knight_flow.app.foreground_focus_window_id", return_value=191),
            patch("knight_flow.app.foreground_edit_target_signature", side_effect=lambda: next(signatures)),
            patch("knight_flow.app.foreground_input_generation", return_value=21),
            patch("knight_flow.app.copy_selected_text", return_value=("same text", "same text")),
            patch("knight_flow.llm.llm_rewrite", side_effect=delayed_rewrite),
            patch("knight_flow.app.paste_text_with_receipt", side_effect=delivery),
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.apply_fix_that("make it clear", delivery_token=token)
            self.assertTrue(started.wait(2.0))
            worker = next(t for t in threading.enumerate() if t.name == "TalkDatFixThat")
            release.set()
            worker.join(2.0)

        self.assertEqual(modes, ["clipboard", "copy_only"])
        self.assertEqual(app.last_transcript, "race-safe rewrite")
        self.assertIn("copied", app.overlay.states[-1][1].lower())

    def test_new_session_invalidates_a_blocked_translate_last(self) -> None:
        old_token = object()
        app = _app(old_token)
        app.last_transcript = "old source"
        app.add_history = lambda _entry: None
        started = threading.Event()
        release = threading.Event()

        def delayed_translation(*_args: object, **_kwargs: object) -> TranslationResult:
            started.set()
            self.assertTrue(release.wait(2.0))
            return TranslationResult("old translated", "en", "es", "test", 1)

        with (
            patch("knight_flow.app.copy_selected_text", return_value=("", "original clipboard")),
            patch("knight_flow.app.translate_text", side_effect=delayed_translation),
            patch("knight_flow.app.paste_text_with_receipt") as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.translate_last()
            self.assertTrue(started.wait(2.0))
            new_token = object()
            with app.lock:
                app.session_token = new_token
                app.session = object()
                app._deferred_delivery_owner = None
            app.last_transcript = "New result"
            app.overlay.set_state("listening", "New session listening.")
            release.set()
            worker = next(t for t in threading.enumerate() if t.name == "TalkDatTranslateLast")
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        paste.assert_not_called()
        self.assertEqual(app.last_transcript, "New result")
        self.assertEqual(app.overlay.states[-1], ("listening", "New session listening."))

    def test_superseded_audio_recovery_stays_in_its_record_and_not_shared_state(self) -> None:
        old_token = object()
        app = _app(old_token)
        app.config = {"privacy": {"save_history": True}}
        history: list[dict[str, object]] = []
        app.add_history = history.append
        started = threading.Event()
        release = threading.Event()

        def delayed_transcribe(*_args: object, **_kwargs: object) -> str:
            started.set()
            self.assertTrue(release.wait(2.0))
            return "old recovered raw"

        with (
            patch("knight_flow.app.read_safety_audio", return_value=(b"audio", 16000, 1)),
            patch("knight_flow.app.transcribe_pcm", side_effect=delayed_transcribe),
            patch(
                "knight_flow.app.process_dictation",
                return_value=SimpleNamespace(text="Old recovered final"),
            ),
            patch("knight_flow.app.update_safety_session") as update,
            patch("knight_flow.app.paste_text_with_receipt") as copy_receipt,
        ):
            app.recover_audio_session("old-session")
            self.assertTrue(started.wait(2.0))
            new_token = object()
            with app.lock:
                app.session_token = new_token
                app.session = object()
                app._deferred_delivery_owner = None
            app.last_transcript = "New result"
            app.overlay.set_state("listening", "New session listening.")
            release.set()
            worker = next(t for t in threading.enumerate() if t.name == "TalkDatAudioRecovery")
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        copy_receipt.assert_not_called()
        self.assertEqual(app.last_transcript, "New result")
        self.assertEqual(app.overlay.states[-1], ("listening", "New session listening."))
        self.assertEqual(history[-1]["delivery"]["method"], "superseded_history_only")
        self.assertEqual(update.call_args.kwargs["final_text"], "Old recovered final")

    def test_new_session_invalidates_a_blocked_command_transform(self) -> None:
        old_token = object()
        app = _app(old_token)
        app.config["dictation"] = {"paste_mode": "clipboard"}
        app.add_history = lambda _entry: None
        app.last_transcript = "Earlier result"
        app._command_selection = "old selection"
        app._command_clipboard = "clipboard"
        app._command_window = 77
        app._command_focus_window = 177
        app._command_edit_target = EDIT_TARGET_A
        app._command_input_generation = 30
        started = threading.Event()
        release = threading.Event()

        def delayed_transform(*_args: object, **_kwargs: object) -> str:
            started.set()
            self.assertTrue(release.wait(2.0))
            return "Old command output"

        with (
            patch("knight_flow.app.copy_selected_text", return_value=("old selection", "old selection")),
            patch("knight_flow.app.transform_text", side_effect=delayed_transform),
            patch("knight_flow.app.foreground_window_id", return_value=77),
            patch("knight_flow.app.foreground_focus_window_id", return_value=177),
            patch("knight_flow.app.foreground_edit_target_signature", return_value=EDIT_TARGET_A),
            patch("knight_flow.app.foreground_input_generation", return_value=31),
            patch("knight_flow.app.paste_text_with_receipt") as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            worker = threading.Thread(
                target=app.handle_command,
                args=("make it concise",),
                kwargs={"delivery_token": old_token},
            )
            worker.start()
            self.assertTrue(started.wait(2.0))
            new_token = object()
            with app.lock:
                app.session_token = new_token
                app.session = object()
                app._deferred_delivery_owner = None
            app.last_transcript = "New result"
            app.overlay.set_state("listening", "New session listening.")
            release.set()
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        paste.assert_not_called()
        self.assertEqual(app.last_transcript, "New result")
        self.assertEqual(app.overlay.states[-1], ("listening", "New session listening."))

    def test_command_copies_result_when_window_changes_after_voice_capture(self) -> None:
        token = object()
        app = _app(token)
        app._command_selection = "window A selection"
        app._command_clipboard = "original clipboard"
        app._command_window = 77
        app._command_focus_window = 177
        app._command_edit_target = EDIT_TARGET_A
        app._command_input_generation = 30
        app.add_history = lambda _entry: None
        receipt = PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))

        with (
            patch("knight_flow.app.foreground_window_id", return_value=88),
            patch("knight_flow.app.foreground_focus_window_id", return_value=188),
            patch("knight_flow.app.foreground_edit_target_signature", return_value=EDIT_TARGET_B),
            patch("knight_flow.app.foreground_input_generation", return_value=31),
            patch("knight_flow.app.copy_selected_text") as copy_selection,
            patch("knight_flow.app.transform_text", return_value="window A result") as transform,
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt) as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.handle_command("make it concise", delivery_token=token)

        copy_selection.assert_not_called()
        transform.assert_called_once()
        self.assertEqual(paste.call_args.kwargs["paste_mode"], "copy_only")
        self.assertIn("manual paste", app.overlay.states[-1][1].lower())

    def test_command_copies_result_for_a_different_selection_inside_the_same_field(self) -> None:
        token = object()
        app = _app(token)
        app._command_selection = "field A selection"
        app._command_clipboard = "original clipboard"
        app._command_window = 77
        app._command_focus_window = 177
        app._command_edit_target = EDIT_TARGET_A
        app._command_input_generation = 30
        app.add_history = lambda _entry: None
        receipt = PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))

        with (
            patch("knight_flow.app.foreground_window_id", return_value=77),
            patch("knight_flow.app.foreground_focus_window_id", return_value=177),
            patch("knight_flow.app.foreground_edit_target_signature", return_value=EDIT_TARGET_A),
            patch("knight_flow.app.foreground_input_generation", return_value=31),
            patch(
                "knight_flow.app.copy_selected_text",
                return_value=("field B secret", "field A selection"),
            ),
            patch("knight_flow.app.transform_text", return_value="field A result") as transform,
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt) as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.handle_command("make it concise", delivery_token=token)

        transform.assert_called_once()
        self.assertEqual(transform.call_args.args[0], "field A selection")
        self.assertEqual(paste.call_args.kwargs["paste_mode"], "copy_only")

    def test_command_copies_result_for_identical_text_in_a_different_focused_control(self) -> None:
        token = object()
        app = _app(token)
        app._command_selection = "same text"
        app._command_clipboard = "original clipboard"
        app._command_window = 77
        app._command_focus_window = 177
        app._command_edit_target = EDIT_TARGET_A
        app._command_input_generation = 30
        app.add_history = lambda _entry: None
        receipt = PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))

        with (
            patch("knight_flow.app.foreground_window_id", return_value=77),
            patch("knight_flow.app.foreground_focus_window_id", return_value=178),
            patch("knight_flow.app.foreground_edit_target_signature", return_value=EDIT_TARGET_B),
            patch("knight_flow.app.foreground_input_generation", return_value=31),
            patch("knight_flow.app.copy_selected_text") as copy_selection,
            patch("knight_flow.app.transform_text", return_value="same text improved") as transform,
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt) as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.handle_command("make it concise", delivery_token=token)

        copy_selection.assert_not_called()
        transform.assert_called_once()
        self.assertEqual(paste.call_args.kwargs["paste_mode"], "copy_only")

    def test_command_shared_renderer_signature_change_can_never_auto_paste(self) -> None:
        token = object()
        app = _app(token)
        app._command_selection = "same text"
        app._command_clipboard = "original clipboard"
        app._command_window = 77
        app._command_focus_window = 177
        app._command_edit_target = EDIT_TARGET_A
        app._command_input_generation = 30
        app.add_history = lambda _entry: None
        receipt = PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))

        with (
            patch("knight_flow.app.foreground_window_id", return_value=77),
            patch("knight_flow.app.foreground_focus_window_id", return_value=177),
            patch("knight_flow.app.foreground_edit_target_signature", return_value=EDIT_TARGET_B),
            patch("knight_flow.app.foreground_input_generation", return_value=31),
            patch("knight_flow.app.copy_selected_text") as copy_selection,
            patch("knight_flow.app.transform_text", return_value="safer result"),
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt) as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.handle_command("make it concise", delivery_token=token)

        copy_selection.assert_not_called()
        self.assertEqual(paste.call_args.kwargs["paste_mode"], "copy_only")

    def test_command_target_race_falls_back_to_one_owner_only_clipboard_copy(self) -> None:
        token = object()
        app = _app(token)
        app._command_selection = "same text"
        app._command_clipboard = "original clipboard"
        app._command_window = 77
        app._command_focus_window = 177
        app._command_edit_target = EDIT_TARGET_A
        app._command_input_generation = 30
        app.config["dictation"] = {
            "paste_mode": "clipboard",
            "restore_clipboard_after_paste": True,
        }
        app.add_history = lambda _entry: None
        modes: list[str] = []

        def delivery(_text: str, **options: object) -> PasteReceipt:
            mode = str(options["paste_mode"])
            modes.append(mode)
            allowed = options["can_deliver"]
            self.assertTrue(callable(allowed))
            if mode == "clipboard":
                self.assertFalse(allowed())
                return PasteReceipt(False, "clipboard", "cancelled", ("clipboard", "cancelled"))
            self.assertTrue(allowed())
            return PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))

        signatures = iter((EDIT_TARGET_A, EDIT_TARGET_A, EDIT_TARGET_B))
        with (
            patch("knight_flow.app.foreground_window_id", return_value=77),
            patch("knight_flow.app.foreground_focus_window_id", return_value=177),
            patch("knight_flow.app.foreground_edit_target_signature", side_effect=lambda: next(signatures)),
            patch("knight_flow.app.foreground_input_generation", return_value=31),
            patch("knight_flow.app.copy_selected_text", return_value=("same text", "same text")),
            patch("knight_flow.app.transform_text", return_value="race-safe result"),
            patch("knight_flow.app.paste_text_with_receipt", side_effect=delivery),
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.handle_command("make it concise", delivery_token=token)

        self.assertEqual(modes, ["clipboard", "copy_only"])
        self.assertEqual(app.last_transcript, "race-safe result")
        self.assertIn("manual paste", app.overlay.states[-1][1].lower())

    def test_command_missing_edit_signature_can_never_auto_paste(self) -> None:
        token = object()
        app = _app(token)
        app._command_selection = "selected text"
        app._command_clipboard = "original clipboard"
        app._command_window = 77
        app._command_focus_window = 177
        app._command_edit_target = ()
        app._command_input_generation = 30
        app.add_history = lambda _entry: None
        receipt = PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))

        with (
            patch("knight_flow.app.foreground_window_id", return_value=77),
            patch("knight_flow.app.foreground_focus_window_id", return_value=177),
            patch("knight_flow.app.foreground_edit_target_signature", return_value=()),
            patch("knight_flow.app.foreground_input_generation", return_value=31),
            patch("knight_flow.app.copy_selected_text") as copy_selection,
            patch("knight_flow.app.transform_text", return_value="safe result"),
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt) as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            app.handle_command("make it concise", delivery_token=token)

        copy_selection.assert_not_called()
        self.assertEqual(paste.call_args.kwargs["paste_mode"], "copy_only")

    def test_run_transform_refuses_a_different_target_after_slow_formatting(self) -> None:
        app = _app(object())
        app.config["dictation"] = {"paste_mode": "clipboard"}
        app.add_history = lambda _entry: None
        app.last_original = "Earlier raw"
        app.last_transcript = "Earlier result"
        target = [44]
        started = threading.Event()
        release = threading.Event()

        def delayed_transform(*_args: object, **_kwargs: object) -> str:
            started.set()
            self.assertTrue(release.wait(2.0))
            return "Transformed old selection"

        with (
            patch("knight_flow.app.copy_selected_text", return_value=("old selection", "clipboard")),
            patch("knight_flow.app.transform_text", side_effect=delayed_transform),
            patch("knight_flow.app.foreground_window_id", side_effect=lambda: target[0]),
            patch("knight_flow.app.foreground_input_generation", return_value=32),
            patch("knight_flow.app.paste_text_with_receipt") as paste,
            patch("knight_flow.app.restore_clipboard_if_unchanged"),
        ):
            worker = threading.Thread(target=app.run_transform, args=("polish",))
            worker.start()
            self.assertTrue(started.wait(2.0))
            target[0] = 55
            release.set()
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        paste.assert_not_called()
        self.assertEqual((app.last_original, app.last_transcript), ("Earlier raw", "Earlier result"))

    def test_paste_last_inserts_and_keeps_exact_transcript_on_clipboard(self) -> None:
        app = _app(object())
        app.last_transcript = "Recovered words"
        app.config["dictation"] = {
            "restore_clipboard_after_paste": True,
            "smart_leading_space": True,
            "paste_mode": "auto",
        }
        receipt = PasteReceipt(True, "auto", "clipboard", ("clipboard",))
        authorization: list[bool] = []

        def deliver(_text: str, **options: object) -> PasteReceipt:
            authorization.append(bool(options["can_deliver"]()))
            return receipt

        with (
            patch("knight_flow.app.paste_text_with_receipt", side_effect=deliver) as paste,
            patch("knight_flow.app.copy_text", return_value=True) as copy,
            patch("knight_flow.app.foreground_window_id", return_value=44),
            patch("knight_flow.app.foreground_input_generation", return_value=9),
        ):
            app.paste_last()

        self.assertFalse(paste.call_args.kwargs["restore_clipboard"])
        self.assertEqual(authorization, [True])
        copy.assert_not_called()
        self.assertEqual(app.overlay.states[-1], ("captured", "Pasted and copied last transcript."))

    def test_paste_last_copies_when_automatic_insertion_is_blocked(self) -> None:
        app = _app(object())
        app.last_transcript = "Still recoverable"
        receipt = PasteReceipt(False, "auto", "none", ("clipboard", "direct_type"), fallback_used=True)

        with (
            patch("knight_flow.app.paste_text_with_receipt", return_value=receipt),
            patch("knight_flow.app.copy_text", return_value=True),
            patch("knight_flow.app.foreground_window_id", return_value=44),
            patch("knight_flow.app.foreground_input_generation", return_value=9),
        ):
            app.paste_last()

        self.assertEqual(
            app.overlay.states[-1],
            ("captured", "Copied last transcript. Automatic paste was blocked."),
        )

    def test_paste_last_uses_one_text_snapshot_while_shared_state_changes(self) -> None:
        app = _app(object())
        app.last_transcript = "Original recovery snapshot"
        receipt = PasteReceipt(True, "type", "direct_type", ("direct_type",))

        def deliver(text: str, **_options: object) -> PasteReceipt:
            self.assertEqual(text, "Original recovery snapshot")
            app.last_transcript = "Newer dictation result"
            return receipt

        with (
            patch("knight_flow.app.paste_text_with_receipt", side_effect=deliver) as paste,
            patch("knight_flow.app.copy_text", return_value=True) as copy,
            patch("knight_flow.app.foreground_window_id", return_value=44),
            patch("knight_flow.app.foreground_input_generation", return_value=9),
        ):
            app.paste_last()

        paste.assert_called_once()
        copy.assert_called_once_with("Original recovery snapshot")
        self.assertEqual(app.last_transcript, "Newer dictation result")
        self.assertEqual(
            app.overlay.states[-1],
            ("captured", "Pasted and copied last transcript."),
        )

    def test_translation_window_copies_only_because_a_top_level_window_is_not_a_field(self) -> None:
        app = _app(object())
        app.config["dictation"] = {"paste_mode": "clipboard"}

        with (
            patch(
                "knight_flow.app.paste_text_with_receipt",
                return_value=PasteReceipt(True, "copy_only", "copy_only", ("copy_only",)),
            ) as deliver,
            patch("knight_flow.app.foreground_window_id") as foreground,
        ):
            outcome = app.translation_paste("Translated result")

        self.assertTrue(outcome["success"])
        self.assertEqual(deliver.call_args.args[0], "Translated result")
        self.assertEqual(deliver.call_args.kwargs["paste_mode"], "copy_only")
        foreground.assert_not_called()
        self.assertIn("copied", outcome["message"].lower())

    def test_translation_window_copy_failure_leaves_the_result_open(self) -> None:
        app = _app(object())
        app.config["dictation"] = {"paste_mode": "clipboard"}

        with (
            patch(
                "knight_flow.app.paste_text_with_receipt",
                return_value=PasteReceipt(False, "copy_only", "none", ("copy_only",)),
            ) as deliver,
        ):
            outcome = app.translation_paste("Translated result")

        self.assertFalse(outcome["success"])
        self.assertEqual(deliver.call_args.kwargs["paste_mode"], "copy_only")
        self.assertIn("remains open", outcome["message"].lower())


if __name__ == "__main__":
    unittest.main()


class TurningHistoryOffLeavesNothingBehindTests(unittest.TestCase):
    """X-222: "Save local transcript history" off did not mean off.

    The crash-recovery draft is a plaintext copy of the same words History
    stores, and it was written unconditionally. So somebody who deliberately
    turned history OFF still had their last dictation sitting on disk in the
    clear, with nothing in the app saying so and no way to reach it from the
    UI to remove it.

    The cost is real and is not hidden: with history off there is no crash
    recovery. Somebody who asks for nothing on disk has asked for nothing on
    disk, and that is the correct reading, but it is a capability they lose.
    """

    def app_with(self, save_history: bool, draft: Path) -> TalkDatApp:
        app = TalkDatApp.__new__(TalkDatApp)
        app.config = {"privacy": {"save_history": save_history}}
        return app

    def test_with_history_off_the_draft_is_never_written(self) -> None:
        with TemporaryDirectory() as directory:
            draft = Path(directory) / "live-transcript-draft.txt"
            app = self.app_with(False, draft)
            with patch("knight_flow.app.live_draft_path", return_value=draft):
                app.write_live_draft("dictation", "something private", True)
            self.assertFalse(
                draft.exists() and draft.read_text(encoding="utf-8").strip(),
                "a dictation reached disk with history switched off",
            )

    def test_flipping_the_switch_off_removes_what_is_already_there(self) -> None:
        """A setting that only stops the NEXT dictation leaves the last one
        behind, which is the worst of both."""
        with TemporaryDirectory() as directory:
            draft = Path(directory) / "live-transcript-draft.txt"
            draft.write_text("a dictation taken before the toggle", encoding="utf-8")
            app = self.app_with(False, draft)
            with patch("knight_flow.app.live_draft_path", return_value=draft):
                app.clear_live_draft()
            self.assertEqual(draft.read_text(encoding="utf-8"), "")

    def test_with_history_on_nothing_changes(self) -> None:
        with TemporaryDirectory() as directory:
            draft = Path(directory) / "live-transcript-draft.txt"
            app = self.app_with(True, draft)
            with patch("knight_flow.app.live_draft_path", return_value=draft):
                app.write_live_draft("dictation", "Transcript ready to paste.", True)
            self.assertIn("Transcript ready to paste.", draft.read_text(encoding="utf-8"))

    def test_saving_settings_clears_the_draft_when_history_is_off(self) -> None:
        """The switch is flipped in save_settings, so that is where the
        already-written draft has to go."""
        source = (Path(__file__).resolve().parents[1] / "knight_flow" / "app.py").read_text(encoding="utf-8")
        start = source.index("def save_settings(")
        body = source[start:source.index(chr(10) + "    def ", start + 10)]
        self.assertIn("clear_live_draft", body)
        self.assertIn('save_history', body)
