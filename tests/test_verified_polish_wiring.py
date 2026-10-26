"""T1 wired into the app: the instant draft lands, the model's polish follows,
and the polish replaces the draft only where verified_replace proves it may.

Everything outside the app is a stand-in: formatting is a fake, the paste is a
fake that writes into the simulated desktop (tests/simulated_editor.py), and
the UI Automation adapter reads that desktop. No key, click, clipboard or
window is touched.
"""
from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow import net_fence
from knight_flow.app import TalkDatApp, _PolishRecord
from knight_flow.paste import PasteReceipt
from tests.simulated_editor import Desktop
from tests.test_app_session_lifecycle import _app

DRAFT, POLISH = "send the report on friday", "Send the report on Friday."
FIELD = (1, ("edit", 1))


class _Adapter:
    """verified_replace's adapter over the simulated desktop; its paste is the
    one the app hands it (the app's own clipboard route), or none."""

    def __init__(self, desktop: Desktop, paste=None) -> None:
        self.desktop, self._paste = desktop, paste

    def read(self, left_chars):
        return self.desktop.read(left_chars)

    def select_before_caret(self, text):
        return self.desktop.select_before_caret(text)

    def collapse_to(self, read):
        self.desktop.collapse_to(read)

    def paste(self, text):
        return bool(self._paste and self._paste(text))


class _Take:
    """One take through handle_dictation with every outside piece faked."""

    def __init__(self, test: unittest.TestCase, *, verified_polish=True, on_polish=None, shape=None) -> None:
        self.token = object()
        self.app = app = _app(self.token)
        app.config = {
            "dictation": {"auto_paste": True, "paste_mode": "clipboard", "verified_polish": verified_polish},
            "privacy": {"save_history": True},
            "onboarding": {"finish_prompt_2_done": True},
        }
        app._take_view = None
        test.addCleanup(TalkDatApp._end_take_view, app)
        test.addCleanup(net_fence.set_local_only, False)
        self.desktop = Desktop()
        self.desktop.add(*FIELD, text="Note: ")
        self.desktop.focus_on(*FIELD)
        app._verified_target = lambda paste=None: _Adapter(self.desktop, paste)
        self.history: list[dict] = []
        self.written = threading.Event()
        app.add_history = lambda entry: (self.history.append(entry), self.written.set())
        self.formatting_calls: list[bool] = []
        self.pastes: list[tuple[str, dict]] = []
        self.on_polish = on_polish or (lambda: None)
        self.shape = shape or (lambda text: text)

    def formatting(self, raw, config, local_only=False):
        self.formatting_calls.append(local_only)
        if local_only:
            return SimpleNamespace(original=raw, text=DRAFT, send_enter=False, route="rules")
        self.on_polish()
        return SimpleNamespace(original=raw, text=POLISH, send_enter=False, route="model")

    def paste(self, text, **options):
        self.pastes.append((text, options))
        allowed = options.get("can_deliver")
        if allowed is not None and not allowed():
            return PasteReceipt(False, "clipboard", "cancelled", ("clipboard", "cancelled"))
        shaped = self.shape(text) if "delivered" in options else text
        if "delivered" in options:
            options["delivered"].append((shaped, "clipboard"))
        self.desktop.app_paste(shaped)
        return PasteReceipt(True, "clipboard", "clipboard", ("clipboard",))

    def run(self, test: unittest.TestCase, *, wait=True):
        with (
            patch("knight_flow.app.sys.platform", "win32"),
            patch("knight_flow.app.process_dictation", side_effect=self.formatting),
            patch("knight_flow.app.paste_text_with_receipt", side_effect=self.paste),
            patch("knight_flow.app.foreground_window_id", return_value=FIELD[0]),
            patch("knight_flow.app.foreground_input_generation", return_value=0),
        ):
            result = self.app.handle_dictation(DRAFT, delivery_token=self.token, guided_sink=None)
            if wait:
                test.assertTrue(self.written.wait(5), "the take's History entry was never written")
        return result


class VerifiedPolishIsOptIn(unittest.TestCase):
    def on(self, dictation: dict, config: dict | None = None, platform: str = "win32") -> bool:
        app = _app(object())
        app.config = {"dictation": dictation}
        with patch("knight_flow.app.sys.platform", platform):
            return TalkDatApp._verified_polish_on(app, config)

    def test_off_unless_set_to_exactly_true(self) -> None:
        self.assertFalse(self.on({}))
        for value in ("yes", 1, "true", None, False):
            self.assertFalse(self.on({"verified_polish": value}), value)
        self.assertFalse(self.on({"undo_replacement": "auto"}), "the retired setting turns nothing on")
        self.assertTrue(self.on({"verified_polish": True}))

    def test_only_where_it_can_work(self) -> None:
        self.assertFalse(self.on({"verified_polish": True}, platform="darwin"))
        self.assertFalse(self.on({"verified_polish": True, "auto_paste": False}))
        for mode in ("type", "copy_only"):
            self.assertFalse(self.on({"verified_polish": True, "paste_mode": mode}), mode)
        translated = {"translation": {"enabled": True, "auto_translate_dictation": True}}
        self.assertFalse(self.on({"verified_polish": True}, translated))

    def test_the_default_take_is_formatted_in_full_and_delivered_once(self) -> None:
        take = _Take(self, verified_polish=False)
        result = take.run(self, wait=False)
        self.assertEqual(take.formatting_calls, [False], "the model's formatting, before the one delivery")
        self.assertEqual([text for text, _options in take.pastes], [POLISH])
        self.assertEqual(result["text"], POLISH)
        self.assertEqual(len(take.history), 1, "written at once, no polish pending")
        self.assertNotIn("polish", take.history[0])
        self.assertEqual(take.desktop.field.text, "Note: " + POLISH)


class APolishReplacesOnlyWhereProved(unittest.TestCase):
    def test_the_draft_lands_at_once_and_the_polish_replaces_it(self) -> None:
        take = _Take(self)
        result = take.run(self)
        self.assertEqual(result["text"], DRAFT, "the instant draft is what the take delivered")
        self.assertEqual(take.formatting_calls, [True, False])
        self.assertEqual(take.desktop.field.text, "Note: " + POLISH)
        self.assertIsNone(take.desktop.field.selection)
        (draft_paste, draft_options), (polish_paste, polish_options) = take.pastes
        self.assertEqual((draft_paste, polish_paste), (DRAFT, POLISH))
        self.assertFalse(polish_options["allow_typing"])
        self.assertTrue(polish_options["keep_final_period"])
        self.assertNotIn("send_enter", polish_options)
        (entry,) = take.history
        self.assertEqual(entry["text"], POLISH)
        self.assertEqual(entry["alternatives"], [{"kind": "draft", "text": DRAFT}])
        self.assertEqual((entry["polish"]["replaced"], entry["polish"]["reason"]), (True, "replaced"))
        self.assertEqual(take.app.last_transcript, POLISH)

    def test_a_field_changed_while_the_polish_was_made_is_left_alone(self) -> None:
        take = _Take(self)
        take.on_polish = lambda: take.desktop.type("!")  # the person typed after the draft
        take.run(self)
        self.assertEqual(take.desktop.field.text, "Note: " + DRAFT + "!")
        self.assertEqual(len(take.pastes), 1, "the polish was never pasted")
        (entry,) = take.history
        self.assertEqual(entry["text"], DRAFT)
        self.assertEqual(entry["alternatives"], [{"kind": "polished", "text": POLISH, "reason": "changed_before_caret"}])
        self.assertFalse(entry["polish"]["replaced"])
        self.assertEqual(take.app.last_transcript, DRAFT)

    def test_a_newer_take_wins(self) -> None:
        take = _Take(self)
        take.on_polish = lambda: setattr(take.app, "session_token", object())
        take.run(self)
        self.assertEqual(take.desktop.field.text, "Note: " + DRAFT)
        self.assertEqual(len(take.pastes), 1)
        (entry,) = take.history
        self.assertEqual(entry["polish"]["reason"], "newer_take")
        self.assertEqual(entry["alternatives"][0]["text"], POLISH)

    def test_a_shaping_it_cannot_read_keeps_the_polish(self) -> None:
        take = _Take(self, shape=str.upper)
        take.run(self)
        self.assertEqual(take.desktop.field.text, "Note: " + DRAFT.upper())
        (entry,) = take.history
        self.assertEqual(entry["polish"]["reason"], "unknown_shaping")
        self.assertEqual(entry["alternatives"][0]["text"], POLISH)

    def test_a_locked_takes_polish_stays_on_this_computer(self) -> None:
        take = _Take(self)
        take.app._take_view = (take.token, net_fence.begin_take(locked=True), True)
        take.on_polish = lambda: net_fence.assert_cloud_allowed("https://api.example.com/v1/format", "Formatting")
        take.run(self)
        self.assertEqual(take.desktop.field.text, "Note: " + DRAFT)
        (entry,) = take.history
        self.assertEqual(entry["polish"]["reason"], "polish_failed")
        self.assertEqual(entry["polish"]["remote_attempts"],
                         [{"host": "api.example.com", "what": "Formatting", "refused": True}])
        self.assertTrue(entry["receipt"]["locked"])
        self.assertFalse(net_fence.take_locked(), "no fence view is left open")

    def test_the_pill_says_what_landed(self) -> None:
        take = _Take(self)
        take.run(self)
        state, message = take.app.overlay.states[-1]
        self.assertNotEqual(state, "error")
        self.assertIn("Inserted", message)


class TheHistoryEntryIsWrittenOnce(unittest.TestCase):
    def setUp(self) -> None:
        self.written: list[dict] = []
        self.record = _PolishRecord(self.written.append, lambda entry, result: {**entry, "polish": result})

    def test_entry_then_result(self) -> None:
        self.record.entry({"text": "a"})
        self.assertEqual(self.written, [])
        self.record.result({"reason": "replaced"})
        self.record.result({"reason": "again"})
        self.assertEqual(self.written, [{"text": "a", "polish": {"reason": "replaced"}}])

    def test_result_then_entry(self) -> None:
        self.record.result({"reason": "too_late"})
        self.record.entry({"text": "a"})
        self.assertEqual(self.written, [{"text": "a", "polish": {"reason": "too_late"}}])

    def test_a_polish_that_never_reports(self) -> None:
        with patch("knight_flow.app.POLISH_HISTORY_WAIT_SECONDS", 0.05):
            self.record.entry({"text": "a"})
        for _ in range(100):
            if self.written:
                break
            threading.Event().wait(0.02)
        self.assertEqual(self.written, [{"text": "a", "polish": {"replaced": False, "reason": "no_polish_in_time"}}])
        self.record.result({"reason": "replaced"})
        self.assertEqual(len(self.written), 1)

    def test_a_finish_that_fails_still_writes_the_entry(self) -> None:
        record = _PolishRecord(self.written.append, lambda entry, result: 1 / 0)
        record.result({})
        record.entry({"text": "a"})
        self.assertEqual(self.written, [{"text": "a"}])


class ThePolishInHistory(unittest.TestCase):
    def finish(self, result: dict) -> dict:
        return TalkDatApp._polish_entry(_app(object()), {"text": DRAFT, "original": DRAFT}, result)

    def test_nothing_but_routes_and_hosts_beside_the_take(self) -> None:
        entry = self.finish({"replaced": False, "reason": "too_late", "polished": POLISH, "route": "model",
                             "remote_attempts": [], "steps": ["decided"], "meaning": {}})
        self.assertEqual(set(entry["polish"]), {"replaced", "reason", "route", "remote_attempts"})

    def test_an_identical_or_empty_polish_keeps_no_alternative(self) -> None:
        for reason in ("identical", "no_polish"):
            self.assertNotIn("alternatives", self.finish({"replaced": False, "reason": reason, "polished": POLISH}))
        self.assertNotIn("alternatives", self.finish({"replaced": False, "reason": "newer_take", "polished": ""}))


class ThePolishPaste(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _app(object())
        self.app.config = {"dictation": {"restore_clipboard_after_paste": True}}
        self.claim = TalkDatApp._reserve_deferred_delivery(self.app, self.app.session_token)

    def paste(self, method: str, success: bool) -> tuple[bool, dict]:
        with patch("knight_flow.app.paste_text_with_receipt",
                   return_value=PasteReceipt(success, "clipboard", method, (method,))) as paste:
            sent = TalkDatApp._verified_paste(self.app, POLISH, "clipboard", self.claim)
        return sent, paste.call_args.kwargs

    def test_pasted_by_the_drafts_route_never_typed(self) -> None:
        sent, options = self.paste("clipboard", True)
        self.assertTrue(sent)
        self.assertEqual(options["paste_mode"], "clipboard")
        self.assertFalse(options["allow_typing"])
        self.assertTrue(options["keep_final_period"])
        self.assertTrue(options["restore_clipboard"])
        self.assertNotIn("smart_leading_space", options)
        self.assertTrue(options["can_deliver"]())
        TalkDatApp._release_deferred_delivery(self.app, self.claim)
        self.assertFalse(options["can_deliver"](), "only while the take's claim holds")

    def test_what_counts_as_sent(self) -> None:
        self.assertFalse(self.paste("direct_type", True)[0])
        self.assertFalse(self.paste("none", False)[0])
        self.assertTrue(self.paste("clipboard_commit_unknown", False)[0], "the read-back decides")


if __name__ == "__main__":
    unittest.main()
