"""Mac dictation keeps its chosen AX window and field throughout insertion.

Only native AX answers and key/clipboard effects are replaced. The paste and
application delivery paths stay real; no microphone, UI, model or network runs.
"""
from contextlib import ExitStack
from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch

from knight_flow import mac_support, paste
from tests.test_esc_while_processing_keeps_the_words import processing_app


class MacDictationTargetTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.target = [501, "document-a", "field-a"]
        self.typed, self.chords, self.enters, self.copies = [], [], [], []
        self.stack.enter_context(patch.object(mac_support, "IS_MAC", True))
        self.stack.enter_context(patch.object(mac_support, "_read_delivery_target",
                                             side_effect=lambda: tuple(self.target), create=True))
        self.stack.enter_context(patch.object(mac_support, "_delivery_elements_equal",
                                             side_effect=lambda a, b: a == b, create=True))
        self.keys = SimpleNamespace(PAUSE=.025,
            typewrite=lambda text, **_kw: self.typed.append(text),
            press=lambda key: self.enters.append(key),
            hotkey=lambda *keys: self.chords.append(keys))
        self.stack.enter_context(patch.object(paste, "pyautogui", self.keys))
        self.stack.enter_context(patch.object(paste, "settle_modifiers"))
        self.stack.enter_context(patch.object(paste, "clipboard_text", return_value="old"))
        self.stack.enter_context(patch.object(paste, "copy_text", side_effect=self.copy))
        self.stack.enter_context(patch.object(paste, "strip_messenger_trailing_period",
                                             side_effect=lambda text, **_kw: text))
        self.stack.enter_context(patch.object(paste, "foreground_input_generation", return_value=1))
        self.stack.enter_context(patch("knight_flow.app.foreground_input_generation", return_value=1))
        self.stack.enter_context(patch.object(paste.time, "sleep"))

    def copy(self, text, **_kw):
        self.copies.append(text)
        return True

    def deliver(self, text="abcd", send_enter=False, secure=False):
        app, token = processing_app()
        app.config["dictation"].update(paste_mode="type", restore_clipboard_after_paste=False,
                                         smart_leading_space=False)
        if secure:
            from knight_flow.field_context import FieldProbe, PASSWORD
            app._session_field = (token, FieldProbe(PASSWORD))
        with patch("knight_flow.app.process_dictation", return_value=SimpleNamespace(
                original=text, text=text, send_enter=send_enter)), \
             patch("knight_flow.app.take_local_finish_notice", return_value=""):
            result = app.handle_dictation(text, delivery_token=token, guided_sink=None)
        return app, result

    def test_same_app_different_field_stops_after_first_character(self):
        def emit(text, **_kw):
            self.typed.append(text)
            self.target[2] = "field-b"
        self.keys.typewrite = emit
        app, result = self.deliver()
        self.assertEqual(self.typed, ["a"])
        self.assertEqual(self.chords, [])
        self.assertEqual(self.copies, ["abcd"])
        self.assertEqual(result["delivery"]["method"], "copy_only")
        self.assertEqual(app.history[0]["text"], "abcd")
        self.assertIn("Some text may already", app.overlay.states[-1][1])

    def test_same_app_different_window_stops_before_newline(self):
        def emit(text, **_kw):
            self.typed.append(text)
            if text == "b":
                self.target[1] = "document-b"
        self.keys.typewrite = emit
        self.deliver("ab\ncd")
        self.assertEqual(self.typed, ["a", "b"])
        self.assertEqual(self.enters, [])
        self.assertEqual(self.chords, [])

    def test_lost_target_after_last_character_suppresses_trailing_enter(self):
        def emit(text, **_kw):
            self.typed.append(text)
            self.target[2] = "field-b"
        self.keys.typewrite = emit
        _app, result = self.deliver("a", send_enter=True)
        self.assertEqual(self.typed, ["a"])
        self.assertEqual(self.enters, [])
        self.assertIn("enter_cancelled", result["delivery"]["attempts"])

    def test_unknown_field_keeps_words_without_external_input(self):
        self.target[2] = None
        _app, result = self.deliver()
        self.assertEqual(self.typed, [])
        self.assertEqual(self.chords, [])
        self.assertEqual(self.copies, ["abcd"])
        self.assertEqual(result["delivery"]["method"], "copy_only")

    def test_secure_partial_typing_never_keeps_password(self):
        def emit(text, **_kw):
            self.typed.append(text)
            self.target[2] = "field-b"
        self.keys.typewrite = emit
        app, _result = self.deliver(secure=True)
        self.assertEqual(self.typed, ["a"])
        self.assertEqual(self.copies, [])
        self.assertEqual(self.chords, [])
        self.assertEqual(app.history, [])

    def test_unchanged_field_completes_every_character_and_newline(self):
        _app, result = self.deliver("ab\ncd")
        self.assertEqual("".join(self.typed), "abcd")
        self.assertEqual(self.enters, ["enter"])
        self.assertEqual(self.copies, [])
        self.assertTrue(result["delivery"]["success"])

    def test_clipboard_wait_refuses_chord_when_field_changes(self):
        app, token = processing_app()
        app.config["dictation"].update(paste_mode="clipboard", restore_clipboard_after_paste=False,
                                         smart_leading_space=False)
        def changed_after_copy(text, **_kw):
            self.copies.append(text)
            self.target[2] = "field-b"
            return True
        with patch.object(paste, "copy_text", side_effect=changed_after_copy), \
             patch("knight_flow.app.process_dictation", return_value=SimpleNamespace(
                 original="abcd", text="abcd", send_enter=False)):
            result = app.handle_dictation("abcd", delivery_token=token, guided_sink=None)
        self.assertEqual(self.chords, [])
        self.assertEqual(self.typed, [])
        self.assertEqual(result["delivery"]["method"], "copy_only")

    def test_target_loss_cannot_be_undone_by_returning_focus(self):
        guard = mac_support.capture_delivery_target()
        self.assertTrue(guard())
        self.target[2] = "field-b"
        self.assertFalse(guard())
        self.target[2] = "field-a"
        self.assertFalse(guard())

    def test_known_field_guard_does_not_depend_on_the_redo_token(self):
        """Mac counterpart of test_typing_target_continuation's
        test_guard_owns_a_known_window_but_does_not_depend_on_redo_token."""
        received = []

        def spy(_text, **options):
            received.append(options)
            return paste.PasteReceipt(True, "type", "direct_type", ("direct_type",))

        app, token = processing_app()
        app.config["dictation"].update(paste_mode="type", restore_clipboard_after_paste=False,
                                         smart_leading_space=False)
        with patch("knight_flow.app.process_dictation", return_value=SimpleNamespace(
                original="abcd", text="abcd", send_enter=False)), \
             patch("knight_flow.app.take_local_finish_notice", return_value=""), \
             patch("knight_flow.app.paste_text_with_receipt", side_effect=spy):
            app.handle_dictation("abcd", delivery_token=token, guided_sink=None)
        guard = received[0]["typing_can_continue"]
        app.session_token = object()
        self.assertTrue(guard())
        self.target[2] = "field-b"
        self.assertFalse(guard())
        self.target[2] = "field-a"
        self.assertFalse(guard(), "a refused field must stay refused")

    def test_unknown_field_does_not_invent_a_target_identity(self):
        """Mac counterpart of test_unknown_window_does_not_invent_target_identity.
        Windows types on when it cannot name the window. The Mac refuses a field
        it cannot read, and never adopts one that becomes readable later."""
        self.target[2] = None
        guard = mac_support.capture_delivery_target()
        self.assertFalse(guard())
        self.target[2] = "field-b"
        self.assertFalse(guard())

    def test_failed_ax_read_latches_refusal(self):
        guard = mac_support.capture_delivery_target()
        with patch.object(mac_support, "_read_delivery_target", side_effect=RuntimeError("AX unavailable")):
            self.assertFalse(guard())
        self.assertFalse(guard())

    def test_equal_native_references_need_not_be_same_python_object(self):
        class Element:
            def __init__(self, name):
                self.name = name
        self.target[1:] = [Element("document-a"), Element("field-a")]
        with patch.object(mac_support, "_delivery_elements_equal", side_effect=lambda a, b: a.name == b.name):
            guard = mac_support.capture_delivery_target()
            self.target[1:] = [Element("document-a"), Element("field-a")]
            self.assertTrue(guard())
            self.target[2] = Element("field-b")
            self.assertFalse(guard())

    def test_timeout_cannot_insert_into_a_new_field_in_the_same_app(self):
        app, token = processing_app()
        app._flight_window = (token, 501)
        app._flight_mac_target = (token, mac_support.capture_delivery_target())
        app._auto_stopped_token = token
        self.target[2] = "field-b"
        with patch("knight_flow.app.foreground_window_id", return_value=501):
            self.assertTrue(app._auto_stopped_elsewhere(token))

    def test_explicit_stop_may_choose_a_new_field(self):
        app, token = processing_app()
        app._flight_window = (token, 501)
        app._flight_mac_target = (token, mac_support.capture_delivery_target())
        self.target[2] = "field-b"
        with patch("knight_flow.app.foreground_window_id", return_value=501):
            self.assertFalse(app._auto_stopped_elsewhere(token))

    def test_recording_start_binds_timeout_to_the_original_field(self):
        from tests.test_signed_out_still_dictates import _FakeApp, _run_start_session
        from knight_flow.app import TalkDatApp
        app = _FakeApp(account_active=False)
        with patch("knight_flow.field_context.FieldProbe.start", return_value=SimpleNamespace()), \
             patch("knight_flow.app.foreground_window_id", return_value=501), \
             patch("knight_flow.screen_context.foreground_title", return_value=""):
            self.assertIsNotNone(_run_start_session(app, model_on_disk=True))
            token = app.session_token
            app._auto_stopped_token = token
            self.target[2] = "field-b"
            self.assertTrue(TalkDatApp._auto_stopped_elsewhere(app, token))


class NativeAXTargetBoundaryTests(unittest.TestCase):
    """Exercise the AX glue against its public API, without loading frameworks."""

    def read(self, *, trusted=True, field_error=0, window_error=0, field_pid=501,
             window_pid=501, front_pid=501, changed_mid_read=False):
        root, field, window, other = object(), object(), object(), object()
        focused_reads = []
        def attribute(element, name, output):
            if element is root and name == "AXFocusedUIElement":
                focused_reads.append(1)
                return field_error, other if changed_mid_read and len(focused_reads) > 1 else field
            if element is field and name == "AXWindow":
                return window_error, window
            raise AssertionError("Target proof must not read document contents")
        api = SimpleNamespace(
            AXIsProcessTrusted=lambda: trusted,
            AXUIElementCreateSystemWide=lambda: root,
            AXUIElementSetMessagingTimeout=lambda element, seconds: 0,
            AXUIElementCopyAttributeValue=attribute,
            AXUIElementGetPid=lambda element, output: (0, field_pid if element is field else window_pid),
        )
        core = SimpleNamespace(CFEqual=lambda a, b: a is b)
        with patch.dict("sys.modules", {"ApplicationServices": api, "CoreFoundation": core}), \
             patch.object(mac_support, "frontmost_window_id", return_value=front_pid):
            return mac_support._read_delivery_target()

    def test_native_read_returns_a_window_and_field_from_the_frontmost_app(self):
        target = self.read()
        self.assertEqual(target[0], 501)
        self.assertIsNotNone(target[1])
        self.assertIsNotNone(target[2])
        self.assertIsNot(target[1], target[2])

    def test_untrusted_process_does_not_read_a_target(self):
        self.assertIsNone(self.read(trusted=False))

    def test_ax_errors_refuse_a_target(self):
        for options in ({"field_error": -25204}, {"window_error": -25205}):
            with self.subTest(options=options):
                self.assertIsNone(self.read(**options))

    def test_foreign_window_and_background_app_are_refused(self):
        for options in ({"window_pid": 777}, {"front_pid": 777}):
            with self.subTest(options=options):
                self.assertIsNone(self.read(**options))

    def test_our_own_window_cannot_be_an_external_target(self):
        self.assertIsNone(self.read(field_pid=os.getpid()))

    def test_focus_changed_while_assembling_snapshot_is_refused(self):
        self.assertIsNone(self.read(changed_mid_read=True))


if __name__ == "__main__":
    unittest.main()
