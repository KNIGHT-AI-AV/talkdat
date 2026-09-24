"""X-604: the field a take goes into decides what it may become (commandments 52, 76-78).

  PASSWORD: the words as said; no model, no plugin, no journal, no history,
  no last-take memory, no preview on screen, never the clipboard (typed).
  CONSOLE (a terminal): command text, rules only, and Enter is never pressed
  for the person -- the words "press enter" come off and the Pill says so.
  SINGLE-LINE: one line; an inferred list becomes an inline series.
  A chat app keeps a period the speaker SAID.

The kind is read once, as the take starts (field_context.FieldProbe), from
UI Automation / the AX API and the foreground app, never from the text.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow import field_context as fc
from knight_flow.field_text import console_text, password_text, single_line_text
from knight_flow.text_pipeline import complete_prepared_dictation, process_dictation
from tests.parity_battery import local_config


def with_field(field: str) -> dict:
    config = local_config()
    config["_field"] = field
    return config


class TheFieldIsReadFromTheControlTests(unittest.TestCase):
    def uia(self, **element):
        constants = SimpleNamespace(UIA_EditControlTypeId=1, UIA_DocumentControlTypeId=2)
        defaults = dict(CurrentIsPassword=False, CurrentControlType=1, CurrentNativeWindowHandle=0,
                        CurrentAriaProperties="")
        defaults.update(element)
        automation = SimpleNamespace(GetFocusedElement=lambda: SimpleNamespace(**defaults))
        return fc._kind_uia(automation, constants)

    def test_a_password_box_says_so(self):
        self.assertEqual(self.uia(CurrentIsPassword=True), fc.PASSWORD)

    def test_chromium_names_the_line_mode(self):
        # Measured 2026-09-23 on the Claude app: an input reports
        # "multiline=false", its message box "multiline=true".
        self.assertEqual(self.uia(CurrentAriaProperties="expanded=false;multiline=false;required=false"),
                         fc.SINGLE_LINE)
        self.assertEqual(self.uia(CurrentAriaProperties="expanded=false;multiline=true"), fc.MULTI_LINE)

    def test_a_document_is_multi_line_and_an_unknown_edit_is_unknown(self):
        self.assertEqual(self.uia(CurrentControlType=2), fc.MULTI_LINE)
        self.assertEqual(self.uia(), fc.UNKNOWN)
        self.assertEqual(self.uia(CurrentControlType=50000), fc.UNKNOWN)

    def test_the_mac_roles(self):
        self.assertEqual(fc._kind_from_ax("AXTextField", "AXSecureTextField"), fc.PASSWORD)
        self.assertEqual(fc._kind_from_ax("AXTextField", ""), fc.SINGLE_LINE)
        self.assertEqual(fc._kind_from_ax("AXTextArea", ""), fc.MULTI_LINE)
        self.assertEqual(fc._kind_from_ax("AXWebArea", ""), fc.UNKNOWN)

    def test_terminals_are_known_by_their_app(self):
        for name in ("WindowsTerminal.exe", "powershell.exe", "cmd.exe", "wezterm-gui.exe", "terminal.app",
                     "iterm.app", "warp.app", "ghostty.app"):
            with self.subTest(name=name):
                self.assertEqual(fc.read_field_kind(name), fc.CONSOLE)
        self.assertFalse(fc.is_terminal_app("code.exe"))
        self.assertFalse(fc.is_terminal_app(None))

    def test_a_pending_read_counts_as_secure_and_never_blocks_long(self):
        slow = fc.FieldProbe.start(reader=lambda: __import__("time").sleep(0.5) or fc.MULTI_LINE)
        self.assertTrue(slow.pending)
        self.assertTrue(slow.secure_or_pending())
        self.assertEqual(slow.result(timeout=0.01), fc.UNKNOWN)
        self.assertEqual(slow.result(timeout=2), fc.MULTI_LINE)
        self.assertFalse(slow.secure_or_pending())
        broken = fc.FieldProbe.start(reader=lambda: 1 / 0)
        self.assertEqual(broken.result(timeout=2), fc.UNKNOWN)


class TheTextEachFieldTakesTests(unittest.TestCase):
    def test_single_line(self):
        self.assertEqual(single_line_text("We need three things:\n1. Milk\n2. Eggs\n3. Bread",
                                          "we need three things milk eggs and bread"),
                         "We need three things: milk, eggs, and bread")
        self.assertEqual(single_line_text("Hi Diane,\n\nCan you send it?", "hi diane can you send it"),
                         "Hi Diane, can you send it?")
        self.assertEqual(single_line_text("Agenda:\n- Monday review\n- budget", "agenda Monday review budget"),
                         "Agenda: Monday review and budget")

    def test_console(self):
        self.assertEqual(console_text("Git checkout -b fix/login.", ""), "git checkout -b fix/login")
        self.assertEqual(console_text("Git push origin main, no, origin develop.", ""), "git push origin develop")
        self.assertEqual(console_text("Git push origin main, no, develop.", ""), "git push origin develop")
        self.assertEqual(console_text("Echo “yes, no, maybe”.", ""), 'echo "yes, no, maybe"')
        self.assertEqual(console_text("NODE_ENV=production npm start.", ""), "NODE_ENV=production npm start")
        self.assertEqual(console_text("Cd ..", ""), "cd ..")

    def test_password(self):
        self.assertEqual(password_text("Blue harbor seven."), "blue harbor seven")
        self.assertEqual(password_text("Hunter, two!"), "hunter two")
        self.assertEqual(password_text(""), "")


class ThePipelineHonoursTheFieldTests(unittest.TestCase):
    def test_a_password_take_runs_nothing_but_the_words(self):
        with patch("knight_flow.formatting.local_finish") as model, \
             patch("knight_flow.format_journal.record_formatting") as journal:
            processed = process_dictation("Blue harbor seven.", with_field("password"))
            completed = complete_prepared_dictation(processed, with_field("password"))
        self.assertEqual((processed.text, processed.route, processed.send_enter), ("blue harbor seven", "password", False))
        model.assert_not_called()
        journal.assert_not_called()
        self.assertEqual(completed.text, "blue harbor seven")

    def test_a_spoken_enter_still_submits_a_password_form(self):
        processed = process_dictation("Hunter two. Press enter.", with_field("password"))
        self.assertEqual((processed.text, processed.send_enter), ("hunter two", True))

    def test_a_terminal_never_gets_an_enter_and_never_the_model(self):
        with patch("knight_flow.formatting.local_finish") as model:
            processed = process_dictation("git status press enter", with_field("console"))
        model.assert_not_called()
        self.assertEqual((processed.text, processed.send_enter, processed.held_enter), ("git status", False, True))

    def test_the_boundaries(self):
        self.assertEqual(process_dictation("blue harbor seven", with_field("text")).text[:1], "B")
        self.assertIn("\n", process_dictation("we need three things milk eggs and bread", local_config()).text)
        self.assertNotIn("\n", process_dictation("we need three things milk eggs and bread",
                                                 with_field("single-line")).text)


class TheAppKeepsNothingFromAPasswordTests(unittest.TestCase):
    def take(self, field: str, raw: str):
        from knight_flow.paste import PasteReceipt
        from tests.test_app_session_lifecycle import _app

        token = object()
        app = _app(object())
        app.config = local_config()
        app.session_token = token
        app._session_field = (token, fc.FieldProbe(kind=field))
        app._caret_context_reader = lambda: None
        app._note_model_format_ms = lambda _ms: None
        app.play_landing_sound = lambda: None
        history, states = [], []
        app.add_history = history.append
        app.overlay.set_state = lambda *args, **kwargs: states.append(args)
        with patch("knight_flow.app.active_profile", return_value={}), \
             patch("knight_flow.app.apply_profile", side_effect=lambda cfg, profile: cfg), \
             patch("knight_flow.app.paste_text_with_receipt",
                   return_value=PasteReceipt(True, "type", "type", ())) as paste, \
             patch("knight_flow.app.save_config"), \
             patch("knight_flow.app.threading.Thread"), \
             patch("knight_flow.formatting.local_finish", return_value=None):
            result = app.handle_dictation(raw, delivery_token=token)
        return app, result, paste, history, states

    def test_a_password_is_typed_and_leaves_no_trace(self):
        app, result, paste, history, states = self.take(fc.PASSWORD, "Blue harbor seven.")
        self.assertEqual(result["text"], "blue harbor seven")
        self.assertEqual(paste.call_args.kwargs["paste_mode"], "type")
        self.assertFalse(paste.call_args.kwargs["smart_leading_space"])
        self.assertEqual(history, [])
        self.assertNotIn("harbor", str(getattr(app, "last_transcript", "")))
        self.assertNotIn("harbor", str(getattr(app, "last_original", "")))
        self.assertNotIn("harbor", str(getattr(app, "last_raw_transcript", "")))
        self.assertFalse(any("harbor" in str(part).lower() for state in states for part in state), states)

    def test_an_ordinary_field_is_unchanged(self):
        app, result, paste, history, states = self.take(fc.MULTI_LINE, "blue harbor seven")
        self.assertEqual(result["text"][:1], "B")
        self.assertNotEqual(paste.call_args.kwargs["paste_mode"], "type")
        self.assertEqual(len(history), 1)
        self.assertIn("harbor", app.last_transcript.lower())

    def test_a_terminal_says_enter_is_the_persons(self):
        _app, result, paste, _history, states = self.take(fc.CONSOLE, "git status press enter")
        self.assertEqual(result["text"], "git status")
        self.assertFalse(paste.call_args.kwargs["send_enter"])
        from knight_flow.platform_copy import ENTER_KEY

        self.assertIn(f"Press {ENTER_KEY} to run it", states[-1][1])


class AChatAppKeepsASaidPeriodTests(unittest.TestCase):
    def test_the_paste_layer_keeps_it_only_when_said(self):
        from knight_flow import paste

        with patch.object(paste, "foreground_process_name", return_value="slack.exe"):
            self.assertEqual(paste.strip_messenger_trailing_period("Sounds good."), "Sounds good")
            self.assertEqual(paste.strip_messenger_trailing_period("Sounds good.", keep=True), "Sounds good.")

    def test_mac_chat_apps_are_chat_apps_too(self):
        from knight_flow import paste

        for app in ("slack.app", "messages.app", "whatsapp.app", "discord.app"):
            with self.subTest(app=app), patch.object(paste, "foreground_process_name", return_value=app):
                self.assertEqual(paste.strip_messenger_trailing_period("Sounds good."), "Sounds good")


if __name__ == "__main__":
    unittest.main()
