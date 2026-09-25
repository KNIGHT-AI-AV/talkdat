"""Find-more P1-4: on the Mac Paste Last pastes, and Fix That and Command mode paste in place.

The paste target proofs -- the focused control, the edit-target signature and
the "has the person moved on" input generation -- answered 0 or () off
Windows. Paste Last requires bool(input_generation), so it always stopped
with "Paste Last stopped because the target changed."; Fix That and Command
mode require all three, so they always fell back to copy-only.

On the Mac the target is now the frontmost app's pid plus the focused
accessibility element (its identity and frame), and the input generation is
the time of the last key-down or click (CGEventSourceSecondsSinceLastEventType),
read after the shortcut's keys are up (the trap Windows X-667 fixed). These
tests fake the Mac's answers (mac_support's AX, input-clock and key-state
glue) and drive the real app code; each fails on the code before the fix.
"""
from __future__ import annotations

import contextlib
import ctypes
import threading
import time
import unittest
from unittest.mock import patch

from knight_flow import mac_support, paste
from knight_flow.paste import PasteReceipt
from tests.test_app_session_lifecycle import _app

PID = 501
FIELD = 0x5EED  # the focused text area's accessibility identity
OTHER_FIELD = 0x0DD
FRAME = (120.0, 340.5, 480.0, 96.0)


class FakeMac:
    """What the Mac says: frontmost pid, focused element, last input, keys held."""

    def __init__(self) -> None:
        self.pid = PID
        self.element = FIELD
        self.frame: tuple[float, float, float, float] | None = FRAME
        self.last_input_at = time.monotonic() - 5.0
        self.held: list[bool] = []

    def focused(self):
        return (self.pid, self.element, self.frame)

    def seconds_since_input(self) -> float:
        return time.monotonic() - self.last_input_at

    def keys_down(self) -> bool:
        down = self.held.pop(0) if self.held else False
        if down:
            self.last_input_at += 0.05  # a held chord auto-repeats its key-down
        return down

    def person_clicks(self) -> None:
        self.last_input_at = time.monotonic()


@contextlib.contextmanager
def on_a_mac(fake: FakeMac):
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(mac_support, "IS_MAC", True))
        # The Windows branches check os.name, not IS_MAC: with no windll they
        # read nothing on this pretend Mac, as they would on a real one.
        stack.enter_context(patch.object(ctypes, "windll", None, create=True))
        stack.enter_context(patch.object(mac_support, "frontmost_window_id", lambda: fake.pid))
        stack.enter_context(patch.object(mac_support, "_read_focused_element", fake.focused, create=True))
        stack.enter_context(patch.object(mac_support, "_seconds_since_last_input", fake.seconds_since_input, create=True))
        stack.enter_context(patch.object(mac_support, "_any_key_or_button_down", fake.keys_down, create=True))
        clock = mac_support.InputClock() if hasattr(mac_support, "InputClock") else None
        stack.enter_context(patch.object(mac_support, "_INPUT_CLOCK", clock, create=True))
        yield


def paste_like_the_paste_layer(fake: FakeMac | None = None):
    """What paste_text_with_receipt does with the proofs: copy-only as asked, or
    wait for the keys (the rest of a held chord) and ask before the chord."""
    calls: list[dict] = []

    def deliver(_text: str, **options: object) -> PasteReceipt:
        calls.append(options)
        mode = str(options.get("paste_mode"))
        if mode == "copy_only":
            return PasteReceipt(True, "copy_only", "copy_only", ("copy_only",))
        while fake is not None and fake.keys_down():
            pass
        if not options["can_deliver"]():
            return PasteReceipt(False, mode, "cancelled", ("clipboard", "cancelled"))
        return PasteReceipt(True, mode, "clipboard", ("clipboard",))

    return deliver, calls


def join_workers(name: str) -> None:
    for thread in threading.enumerate():
        if thread.name == name:
            thread.join(5.0)


class PasteLastPastesOnTheMac(unittest.TestCase):
    def run_paste_last(self, fake: FakeMac):
        app = _app(object())
        app.last_transcript = "Recovered words"
        app.config["dictation"] = {"paste_mode": "auto"}
        deliver, calls = paste_like_the_paste_layer(fake)
        with on_a_mac(fake), \
             patch("knight_flow.app.paste_text_with_receipt", side_effect=deliver), \
             patch("knight_flow.app.copy_text", return_value=True):
            app.paste_last()
        return app, calls

    def test_paste_last_delivers_by_pasting(self) -> None:
        app, calls = self.run_paste_last(FakeMac())
        self.assertEqual(len(calls), 1, app.overlay.states)
        self.assertEqual(calls[0]["paste_mode"], "auto")
        self.assertEqual(app.overlay.states[-1], ("captured", "Pasted and copied last transcript."))

    def test_the_input_is_read_once_the_shortcut_is_let_go(self) -> None:
        # Paste Last fires on key-down; a chord still held keeps adding
        # key-downs (auto-repeat) until it is let go. Read before that, the
        # generation always moved and Paste Last only copied.
        fake = FakeMac()
        fake.held = [True, True, True, False]
        app, _calls = self.run_paste_last(fake)
        self.assertEqual(app.overlay.states[-1], ("captured", "Pasted and copied last transcript."))


class FixThatAndCommandPasteInPlaceOnTheMac(unittest.TestCase):
    def app(self):
        token = object()
        app = _app(token)
        app.config["dictation"] = {"paste_mode": "auto", "restore_clipboard_after_paste": True}
        app._has_a_writing_model = lambda: True
        app.start_session = lambda *_args, **_kwargs: None
        app.add_history = lambda _entry: None
        return app, token

    def run_fix_that(self, fake: FakeMac, *, during_rewrite=lambda: None):
        app, token = self.app()
        deliver, calls = paste_like_the_paste_layer()

        def rewrite(*_args: object, **_kwargs: object) -> str:
            during_rewrite()
            return "the cat"

        with on_a_mac(fake), \
             patch("knight_flow.app.copy_selected_text", return_value=("teh cat", "old words")), \
             patch("knight_flow.app.paste_text_with_receipt", side_effect=deliver), \
             patch("knight_flow.app.restore_clipboard_if_unchanged"), \
             patch("knight_flow.llm.llm_rewrite", side_effect=rewrite):
            app.start_fix_that()  # captures the target with the real proofs
            app.apply_fix_that("fix the spelling", delivery_token=token)
            join_workers("TalkDatFixThat")
        return app, calls

    def test_fix_that_pastes_the_rewrite_in_place(self) -> None:
        app, calls = self.run_fix_that(FakeMac())
        self.assertEqual(calls[0]["paste_mode"], "auto", app.overlay.states)
        self.assertEqual(app.overlay.states[-1], ("captured", "Fixed in place."))

    def test_fix_that_still_copies_when_the_person_clicked_away(self) -> None:
        fake = FakeMac()
        app, calls = self.run_fix_that(fake, during_rewrite=fake.person_clicks)
        self.assertEqual(calls[-1]["paste_mode"], "copy_only")
        self.assertIn("copied", app.overlay.states[-1][1].lower())

    def test_fix_that_still_copies_when_focus_moved_to_another_field(self) -> None:
        fake = FakeMac()

        def other_field() -> None:
            fake.element = OTHER_FIELD

        app, calls = self.run_fix_that(fake, during_rewrite=other_field)
        self.assertEqual(calls[-1]["paste_mode"], "copy_only")
        self.assertIn("copied", app.overlay.states[-1][1].lower())

    def test_command_mode_applies_the_command_in_place(self) -> None:
        app, token = self.app()
        deliver, calls = paste_like_the_paste_layer()
        with on_a_mac(FakeMac()), \
             patch("knight_flow.app.copy_selected_text", return_value=("teh cat sat", "old words")), \
             patch("knight_flow.app.paste_text_with_receipt", side_effect=deliver), \
             patch("knight_flow.app.restore_clipboard_if_unchanged"), \
             patch("knight_flow.app.transform_text", return_value="The cat sat."):
            app.start_command_mode()
            app.handle_command("make it a sentence", delivery_token=token)
        self.assertEqual(calls[0]["paste_mode"], "auto", app.overlay.states)
        self.assertTrue(app.overlay.states[-1][1].startswith("Applied "), app.overlay.states)


class TheRestoreAfterAnInPlacePasteWaitsForTheTarget(unittest.TestCase):
    def test_fix_thats_restore_leaves_the_target_time_to_read(self) -> None:
        # Fix That and Command mode now paste on the Mac, then put the old
        # clipboard back as soon as the paste layer returns (10 ms after
        # Command+V). An app that reads later would paste the old clipboard.
        from tests.mac_pasteboard_fake import PLAIN, FakePasteboard, mac_simulation

        board = FakePasteboard()
        board.hold([(PLAIN, b"old words")])
        slept: list[float] = []
        with mac_simulation(board), patch.object(paste.time, "sleep", side_effect=slept.append):
            self.assertTrue(paste.copy_text("the cat"))  # the rewrite, pasted
            self.assertTrue(paste.restore_clipboard_if_unchanged("the cat", "old words"))
        self.assertTrue(any(seconds >= 0.15 for seconds in slept), slept)
        self.assertEqual(board.plain_text(), "old words")


class TheMacProofsArePure(unittest.TestCase):
    def test_the_signature_is_pid_element_and_frame(self) -> None:
        self.assertEqual(mac_support.edit_target_signature(PID, FIELD, FRAME), (PID, FIELD, 120, 340, 480, 96))
        for pid, element, frame in ((0, FIELD, FRAME), (PID, 0, FRAME), (PID, FIELD, None),
                                    (PID, FIELD, (0.0, 0.0, 0.0, 0.0))):
            with self.subTest(pid=pid, element=element, frame=frame):
                self.assertEqual(mac_support.edit_target_signature(pid, element, frame), ())

    def test_the_input_clock_moves_only_on_new_input(self) -> None:
        clock = mac_support.InputClock()
        first = clock.generation(100.000)
        self.assertGreater(first, 0)
        self.assertEqual(clock.generation(100.004), first, "the jitter between two reads is not input")
        self.assertEqual(clock.generation(99.997), first)
        moved = clock.generation(100.300)
        self.assertGreater(moved, first)
        self.assertEqual(clock.generation(None), 0, "unknown is never a usable generation")

    def test_an_unreadable_mac_answers_zero(self) -> None:
        def broken():
            raise OSError("AX unavailable")

        with patch.object(mac_support, "IS_MAC", True), \
             patch.object(mac_support, "_read_focused_element", broken), \
             patch.object(mac_support, "_seconds_since_last_input", broken):
            self.assertEqual(paste.foreground_focus_window_id(), 0)
            self.assertEqual(paste.foreground_edit_target_signature(), ())
            self.assertEqual(paste.foreground_input_generation(), 0)

    def test_waiting_for_the_keys_gives_up_at_the_deadline(self) -> None:
        with patch.object(mac_support, "IS_MAC", True), \
             patch.object(mac_support, "_any_key_or_button_down", lambda: True), \
             patch.object(paste.time, "sleep"):
            self.assertFalse(paste.wait_for_keys_released(timeout_ms=0))
        with patch.object(mac_support, "IS_MAC", True), \
             patch.object(mac_support, "_any_key_or_button_down", lambda: False), \
             patch.object(paste.time, "sleep") as slept:
            self.assertTrue(paste.wait_for_keys_released())
        slept.assert_not_called()


if __name__ == "__main__":
    unittest.main()
