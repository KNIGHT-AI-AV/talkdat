"""Session ownership at queued paints, insertion and local recovery boundaries."""
from __future__ import annotations

import copy
import queue
import threading
import unittest
from unittest.mock import patch

from knight_flow.app import TalkDatApp
from knight_flow.paste import PasteReceipt
from tests.test_app_session_lifecycle import _CapturedSession, _app
from tests.test_esc_while_processing_keeps_the_words import processing_app


class QueuedTranscriptTests(unittest.TestCase):
    def queued_app(self):
        token = object()
        app = _app(token)
        app._released_processing = False
        app._cross_thread_calls = queue.Queue()
        app.overlay._ui_thread_id = -1
        drafts, captions = [], []
        app.write_live_draft = lambda *args: drafts.append(args)
        app.overlay.captions_update = lambda *args: captions.append(args)
        return app, token, drafts, captions

    def drain(self, app):
        app.overlay._ui_thread_id = threading.get_ident()
        while not app._cross_thread_calls.empty():
            app._cross_thread_calls.get_nowait()()

    def test_partial_queued_before_release_does_not_restore_listening(self):
        app, token, drafts, captions = self.queued_app()
        app.on_session_update(token, "dictation", "old partial", False)
        self.assertEqual(drafts, [], "worker wrote the draft before ownership was rechecked")
        app._released_processing = True
        app.overlay.set_state("processing", "Finalizing.")
        self.drain(app)
        self.assertEqual(app.overlay.states[-1][0], "processing")
        self.assertEqual(drafts, [])
        self.assertEqual(captions, [])

    def test_cancelled_partial_never_reaches_a_new_take(self):
        app, token, drafts, captions = self.queued_app()
        app.on_session_update(token, "dictation", "old partial", False)
        app.session_token = object()
        app.overlay.set_state("listening", "New take.")
        self.drain(app)
        self.assertEqual(app.overlay.states[-1], ("listening", "New take."))
        self.assertEqual(drafts, [])
        self.assertEqual(captions, [])

    def test_final_after_release_is_retained_without_live_paint(self):
        app, token, drafts, captions = self.queued_app()
        app._released_processing = True
        app.overlay.set_state("processing", "Finalizing.")
        app.on_session_update(token, "dictation", "complete final", True)
        self.drain(app)
        self.assertEqual(drafts, [("dictation", "complete final", True)])
        self.assertEqual(captions, [("complete final", True)])
        self.assertEqual(app.overlay.states[-1][0], "processing")


class DeliveryBoundaryTests(unittest.TestCase):
    def test_fresh_formatter_notice_remains_visible_on_normal_delivery(self):
        from knight_flow.formatting import note_local_finish_refusal
        app, token = processing_app()
        def format_current(*_args, **_kwargs):
            note_local_finish_refusal("model_unavailable")
            return type("Text", (), {"original": "the words", "text": "The words.", "send_enter": False})()
        with (
            patch("knight_flow.app.process_dictation", side_effect=format_current),
            patch("knight_flow.app.paste_text_with_receipt", return_value=PasteReceipt(
                True, "clipboard", "clipboard", ("clipboard",))),
        ):
            app.handle_dictation("the words", delivery_token=token, guided_sink=None)
        self.assertIn("built-in rules", app.overlay.states[-1][1])

    def test_current_formatter_notice_does_not_hide_esc_recovery(self):
        from knight_flow.formatting import note_local_finish_refusal
        app, token = processing_app()
        app._withheld_delivery_token = token
        def format_current(*_args, **_kwargs):
            note_local_finish_refusal("model_unavailable")
            return type("Text", (), {"original": "the words", "text": "The words.", "send_enter": False})()
        with (
            patch("knight_flow.app.process_dictation", side_effect=format_current),
            patch("knight_flow.app.paste_text_with_receipt", return_value=PasteReceipt(
                True, "copy_only", "copy_only", ("copy_only",))),
        ):
            app.handle_dictation("the words", delivery_token=token, guided_sink=None)
        self.assertEqual(app.overlay.states[-1], ("captured", "Kept, not pasted."))

    def test_previous_take_notice_does_not_replace_esc_recovery(self):
        from knight_flow.formatting import note_local_finish_refusal
        app, token = processing_app()
        app._withheld_delivery_token = token
        note_local_finish_refusal("model_unavailable")
        with (
            patch("knight_flow.app.process_dictation", return_value=type("Text", (), {
                "original": "the words", "text": "The words.", "send_enter": False})()),
            patch("knight_flow.app.paste_text_with_receipt", return_value=PasteReceipt(
                True, "copy_only", "copy_only", ("copy_only",))),
        ):
            result = app.handle_dictation("the words", delivery_token=token, guided_sink=None)
        self.assertEqual(result["delivery"]["method"], "copy_only")
        self.assertEqual(app.overlay.states[-1], ("captured", "Kept, not pasted."))

    def test_mac_password_delivery_preserves_the_concealed_option(self):
        from knight_flow.field_context import FieldProbe, PASSWORD

        app, token = processing_app()
        app._session_field = (token, FieldProbe(PASSWORD))
        options_seen = []

        def paste(_text, **options):
            options_seen.append(options)
            return PasteReceipt(True, "type", "direct_type", ("direct_type",))

        with (
            patch("knight_flow.mac_support.IS_MAC", True),
            patch("knight_flow.mac_support.capture_delivery_target", return_value=lambda: True),
            patch("knight_flow.app.process_dictation",
                  return_value=type("Text", (), {"original": "secret", "text": "secret", "send_enter": False})()),
            patch("knight_flow.app.paste_text_with_receipt", side_effect=paste),
        ):
            app.handle_dictation("secret", delivery_token=token, guided_sink=None)
        self.assertEqual(len(options_seen), 1)
        self.assertTrue(options_seen[0]["concealed"])
        self.assertEqual(options_seen[0]["paste_mode"], "type")
        self.assertFalse(options_seen[0]["restore_clipboard"])
        self.assertTrue(options_seen[0]["typing_can_continue"]())
        self.assertEqual(app.history, [])

    def test_auto_stop_focus_change_during_delivery_keeps_words_without_typing(self):
        app, token = processing_app()
        app._flight_window = (token, 111)
        app._auto_stopped_token = token
        current_window = [111]
        calls, external_keys = [], []

        def paste(_text, **options):
            mode = options["paste_mode"]
            calls.append(mode)
            if mode == "copy_only":
                self.assertTrue(options["can_deliver"]())
                return PasteReceipt(True, mode, "copy_only", (mode,))
            current_window[0] = 222  # equivalent to a focus move during a paste wait
            if options["can_deliver"]():
                external_keys.append("ctrl+v")
                return PasteReceipt(True, mode, "clipboard", (mode,))
            return PasteReceipt(False, mode, "cancelled", (mode, "cancelled"))

        with (
            patch("knight_flow.app.foreground_window_id", side_effect=lambda: current_window[0]),
            patch("knight_flow.app.process_dictation",
                  return_value=type("Text", (), {"original": "the words", "text": "The words.", "send_enter": False})()),
            patch("knight_flow.app.paste_text_with_receipt", side_effect=paste),
        ):
            result = app.handle_dictation("the words", delivery_token=token, guided_sink=None)
        self.assertEqual(external_keys, [])
        self.assertEqual(calls, ["clipboard", "copy_only"])
        self.assertEqual(result["text"], "The words.")
        self.assertEqual(len(app.history), 1)
        self.assertIn("Kept, not pasted", app.overlay.states[-1][1])

    def test_esc_during_delivery_refuses_keys_but_keeps_current_words(self):
        app, token = processing_app()
        keys, modes = [], []

        def paste(_text, **options):
            mode = options["paste_mode"]
            modes.append(mode)
            if mode == "copy_only":
                self.assertTrue(options["can_deliver"]())
                return PasteReceipt(True, mode, "copy_only", (mode,))
            app._withheld_delivery_token = token
            if options["can_deliver"]():
                keys.append("ctrl+v")
                return PasteReceipt(True, mode, "clipboard", (mode,))
            return PasteReceipt(False, mode, "cancelled", (mode, "cancelled"))

        with (
            patch("knight_flow.app.process_dictation",
                  return_value=type("Text", (), {"original": "the words", "text": "The words.", "send_enter": False})()),
            patch("knight_flow.app.paste_text_with_receipt", side_effect=paste),
        ):
            result = app.handle_dictation("the words", delivery_token=token, guided_sink=None)
        self.assertEqual(keys, [])
        self.assertEqual(modes, ["clipboard", "copy_only"])
        self.assertTrue(result["delivery"]["success"])


class ResolvedRecoveryTests(unittest.TestCase):
    def test_local_capture_recovery_ignores_a_stale_provider_name(self):
        app = _app(object())
        app.config = {
            "privacy": {"local_only": True},
            "stt": {"provider": "deepgram", "route_mode": "local", "local_fallback": False},
            "dictation": {"retry_failed_capture": True},
        }
        app._session_audio_already_saved = True
        current = _CapturedSession(degraded=False)
        current.provider_id = "local"
        with patch("knight_flow.app.transcribe_pcm", return_value="recovered locally") as transcribe:
            result = app.recover_transcript_if_needed(current, "dictation", "")
        self.assertEqual(result, "recovered locally")
        self.assertEqual(transcribe.call_args.kwargs["provider_id"], "local")
        self.assertEqual(transcribe.call_args.args[0]["stt"]["provider"], "local")

    def test_recovery_retains_the_resolved_model_snapshot(self):
        app = _app(object())
        captured_config = {
            "privacy": {"local_only": True},
            "stt": {"provider": "local", "route_mode": "local", "providers": {"local": {"model": "whisper-small"}}},
            "dictation": {"retry_failed_capture": True},
        }
        app.config = copy.deepcopy(captured_config)
        app.config["stt"]["providers"]["local"]["model"] = "parakeet-tdt-0.6b-v3"
        app._session_audio_already_saved = True
        current = _CapturedSession(degraded=False)
        current._talkdat_config = copy.deepcopy(captured_config)
        current._talkdat_provider_id = "local"
        with patch("knight_flow.app.transcribe_pcm", return_value="same model retry") as transcribe:
            app.recover_transcript_if_needed(current, "dictation", "")
        self.assertEqual(transcribe.call_args.args[0]["stt"]["providers"]["local"]["model"], "whisper-small")
        self.assertEqual(captured_config["stt"]["providers"]["local"]["model"], "whisper-small")


if __name__ == "__main__":
    unittest.main()
