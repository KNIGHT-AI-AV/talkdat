"""X-743: every old message call reaches the Pill (Overlay.flag), and the opt-ins speak.

The message spec's migration (section 15.1): six Tk functions are redirected
through flag() and keep their names, so no caller breaks; the direct call sites
in app.py say their words through flag(); and the set_state calls whose words
used to reach nobody (a status line only the Tk Status window showed) opt in
with say=. Nothing here needs a window: the redirects are driven on a bare
Overlay with flag() replaced, and the call sites are read from the source.
"""
from __future__ import annotations

import ast
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

from knight_flow import island
from knight_flow.overlay import Overlay

ROOT = Path(__file__).resolve().parents[1] / "knight_flow"


def bare_overlay() -> Overlay:
    overlay = object.__new__(Overlay)
    overlay._ui_thread_id = threading.get_ident()
    overlay.config = {}
    overlay.flag = mock.Mock()
    return overlay


class TheOldNamesReachFlagTests(unittest.TestCase):
    def test_show_toast(self) -> None:
        overlay = bare_overlay()
        overlay.show_toast("Talk DAT! is up to date", detail="Talk DAT! 1.2.3", kind="done")
        overlay.flag.assert_called_once_with("Talk DAT! is up to date", detail="Talk DAT! 1.2.3", tone="done")

    def test_show_toast_now(self) -> None:
        overlay = bare_overlay()
        overlay._show_toast_now("Update ready. Click to see it.")
        overlay.flag.assert_called_once_with("Update ready. Click to see it.", detail="", tone="info", origin="person")

    def test_the_error_message_of_every_error_state(self) -> None:
        overlay = bare_overlay()
        overlay._show_error_message("The microphone did not start.", "Check your microphone.")
        overlay.flag.assert_called_once_with("The microphone did not start.", detail="Check your microphone.",
                                             tone="error", key="state", origin="person")

    def test_the_learned_word_and_the_offer(self) -> None:
        overlay = bare_overlay()
        undone, added = [], []
        with mock.patch("knight_flow.meeting_quiet.meeting_in_progress", return_value=False):
            overlay.show_learned_word("Kubernetes", lambda: undone.append(True))
            overlay.offer_learned_word("Kubernetes", added.append)
        (receipt_args, receipt), (offer_args, offer) = overlay.flag.call_args_list
        self.assertEqual(receipt_args, ('Added "Kubernetes"',))
        self.assertEqual((receipt["key"], receipt["hold_ms"], receipt["tone"]), ("word", 6000, "done"))
        self.assertEqual([(a.label, a.accelerator) for a in receipt["actions"]], [("Undo", "<Alt-d>")])
        self.assertEqual(offer_args, ('Add "Kubernetes" to your words?',))
        self.assertEqual([a.label for a in offer["actions"]], ["Add"])
        receipt["actions"][0].run()
        offer["actions"][0].run()
        self.assertEqual((undone, added), ([True], ["Kubernetes"]))

    def test_a_meeting_still_keeps_the_word_notice_away(self) -> None:
        overlay = bare_overlay()
        with mock.patch("knight_flow.meeting_quiet.meeting_in_progress", return_value=True):
            overlay.show_learned_word("Kubernetes", lambda: None)
        overlay.flag.assert_not_called()

    def test_the_update_offer(self) -> None:
        overlay = bare_overlay()
        installed = []
        overlay.show_update_popover("v1.2.4", lambda: installed.append(True))
        args, kwargs = overlay.flag.call_args
        self.assertEqual(args, ("Talk DAT! 1.2.4 is ready",))
        self.assertEqual((kwargs["key"], kwargs["hold_ms"]), ("update", 20000))
        self.assertEqual([(a.label, a.accelerator, a.primary) for a in kwargs["actions"]],
                         [("Install", "<Alt-u>", True)])
        kwargs["actions"][0].run()
        self.assertEqual(installed, [True])

    def test_the_update_flag_is_the_pip(self) -> None:
        overlay = bare_overlay()
        with mock.patch.object(Overlay, "_render_update_flag"), mock.patch.object(Overlay, "_represent_layered"), \
                mock.patch.object(Overlay, "_wake_animation"):
            overlay.set_update_flag("red")
        self.assertEqual(overlay._update_flag, "red")
        self.assertIsNotNone(overlay._pip_since, "the pip does not breathe when it arrives")

    def test_set_state_speaks_through_flag(self) -> None:
        source = ast.get_source_segment((ROOT / "overlay.py").read_text(encoding="utf-8"),
                                        next(node for node in ast.walk(ast.parse((ROOT / "overlay.py").read_text(encoding="utf-8")))
                                             if isinstance(node, ast.FunctionDef) and node.name == "_set_state_now"))
        self.assertIn("island.say_tone(normalized, say)", source)
        self.assertIn('self.flag(message, tone=tone, key="state", origin="person")', source)
        self.assertIn("self._show_error_message(message, preview)", source)
        self.assertEqual(island.say_tone("error", None), "error", "an error still speaks without opting in")


def calls(module: str, name: str) -> list[ast.Call]:
    tree = ast.parse((ROOT / module).read_text(encoding="utf-8"))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and getattr(node.func, "attr", getattr(node.func, "id", "")) == name]


def said(call: ast.Call) -> ast.expr | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == "say"), None)


def words(call: ast.Call) -> str:
    if len(call.args) < 2:
        return ""
    value = call.args[1]
    if isinstance(value, ast.Constant):
        return str(value.value)
    if isinstance(value, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else "{}" for part in value.values)
    return ast.unparse(value)


#: The message spec's opt-ins, by the words each one says (line numbers drift).
#: Two of them are spelled per platform on mac-port, so they are matched by
#: their source form: "Hold {} to talk." names the bound chord (Ctrl+Win on
#: Windows, the Mac keyboard's own names there) and self._no_speech_message()
#: says why a Mac mic gave nothing. test_the_platform_words_are_the_plain_ones pins
#: what Windows still reads.
OPT_INS = {
    "done": ["Pinned last transcript.", "Signed in on {}.", "Ramble saved: {}", "Typed into the terminal. Press {} to run it.",
             "Auto-translate ON.", "Auto-translate OFF.", "Copied last transcript to the clipboard.",
             "Copied last cleanup diff.", "Updates for this copy come from the Microsoft Store.", "Route: {}",
             "{} is your default finish.", "{} is ready.", "Panic Stop completed for dictation and registered mic tests."],
    "warn": ["Captured locally. Auto paste is off.", "Rich clipboard preserved. Transcript kept in History for Paste Last."],
    "info": ["Talk DAT! paused. Triggers are off.", "Talk DAT! resumed. Hold {} to talk.",
             "Finish the current recording before starting meeting notes.",
             "Finish the current recording or microphone check before starting Scribe.",
             "Dictation cancelled before opening its microphone.", "Nothing heard. Mic closed.",
             "No speech captured. Ready again.", "Nothing to paste. Ready again."],
    "busy": ["Still processing the previous dictation.", "self._local_download_message()", "Loading local model.",
             "Time limit reached. Finalizing.", "self._no_speech_message()",
             "No speech for a while. Closing the mic.", "{} interrupted. Recovering captured audio.",
             "Recovering captured audio.", "Recovered captured audio.", "Checking GitHub releases for updates.",
             "Preparing {}."],
}


class TheCallSitesMovedTests(unittest.TestCase):
    def test_no_app_call_site_uses_the_toast_any_more(self) -> None:
        self.assertEqual([node.lineno for node in calls("app.py", "show_toast")], [])
        flagged = calls("app.py", "flag")
        self.assertGreaterEqual(len(flagged), 7, "the direct call sites say their words through flag()")

    def test_the_rescue_is_loud_and_said_once(self) -> None:
        rescue = [call for call in calls("app.py", "flag") if call.args and isinstance(call.args[0], ast.Constant)
                  and call.args[0].value == "Your speech provider did not answer"]
        self.assertEqual(len(rescue), 1)
        self.assertEqual(next(k.value.value for k in rescue[0].keywords if k.arg == "tone"), "warn")
        transcribing = [call for call in calls("app.py", "set_state") if words(call).startswith("Transcribing on")]
        self.assertTrue(transcribing and all(said(call) is None for call in transcribing),
                        "the rescue would be said twice")

    def test_every_opt_in_speaks_with_its_tone(self) -> None:
        sites = calls("app.py", "set_state")
        found = 0
        for tone, texts in OPT_INS.items():
            for text in texts:
                with self.subTest(words=text):
                    matching = [call for call in sites if words(call) == text and said(call) is not None]
                    self.assertTrue(matching, f"{text!r} does not opt in with say=")
                    found += len(matching)
                    for call in matching:
                        value = said(call)
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            self.assertEqual(value.value, tone)
                        elif isinstance(value, ast.Constant):
                            self.assertIs(value.value, True)
        self.assertEqual(found, 35)
        transforms = [call for call in sites if words(call) == "message" and said(call) is not None]
        self.assertEqual(len(transforms), 3, "the two command results and the model setup line")
        everywhere = sum(1 for call in sites if said(call) is not None)
        everywhere += sum(1 for module in ("wake_runtime.py", "web_shell/ramble_adapter.py")
                          for call in calls(module, "set_state") if said(call) is not None)
        # 40 opt-ins, plus the four refusals through _say_why_not and the
        # rescue through flag(): the spec's 45.
        self.assertEqual(everywhere, 40)

    @unittest.skipIf(sys.platform == "darwin", "the Mac spells these its own way")
    def test_the_platform_words_are_the_plain_ones(self) -> None:
        from knight_flow.app import RESUME_SURFACE_NAME, TalkDatApp
        from knight_flow.onboarding import chord_label

        app = TalkDatApp.__new__(TalkDatApp)
        self.assertEqual(app._no_speech_message(), "No speech heard. Closing the mic.")
        self.assertEqual(chord_label({}, "push_to_talk", ("ctrl", "cmd")), "Ctrl+Win")
        self.assertEqual(RESUME_SURFACE_NAME, "the tray icon")

    def test_the_refusals_speak_through_one_call(self) -> None:
        refusal = ast.get_source_segment((ROOT / "app.py").read_text(encoding="utf-8"),
                                         next(node for node in ast.walk(ast.parse((ROOT / "app.py").read_text(encoding="utf-8")))
                                              if isinstance(node, ast.FunctionDef) and node.name == "_say_why_not"))
        self.assertIn('self.overlay.flag(message, key="refusal", origin="person")', refusal)
        reasons = [call for call in calls("app.py", "_say_why_not")]
        self.assertGreaterEqual(len(reasons), 4, "paused, meeting, mic check and practice refusals")

    def test_sign_in_and_the_emailed_code_stay_on_the_account_page(self) -> None:
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("Press Sign in whenever you're ready", source)
        self.assertNotIn("Check your email for the six-digit code.", source)


if __name__ == "__main__":
    unittest.main()
