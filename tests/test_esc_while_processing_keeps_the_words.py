"""X-623 (interaction grid D1): Esc while processing keeps the words.

Esc is the global Cancel and fires in every app, as does any chord holding it.
Pressed to leave an autocomplete or a dialog in the second after the person
stopped talking, it killed the delivery of a take that was already
processing: the words never pasted (the audio stayed in History, the text
did not arrive anywhere).

Now the Esc key is App.cancel_from_key: with the microphone open it cancels
as before; once the take is processing its words are copied to the clipboard
and saved in History instead of typed, with one line, "Kept, not pasted." The
tray's Cancel stays the full cancel.

The first test drives the real HotkeyController with the app's own keyboard
map, then the real delivery. Sabotage: map Esc back to cancel() and the
"kept" assertions go red (tested below, in-process).
"""
from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch

from knight_flow.app import TalkDatApp
from knight_flow.hotkeys import HotkeyController
from knight_flow.paste import PasteReceipt


class _Overlay:
    def __init__(self) -> None:
        self.states: list[tuple[str, str]] = []
        self.toasts: list[str] = []
        self.onboarding_test_sink = None
        self.root = SimpleNamespace(after=lambda _delay, callback: callback())

    def set_state(self, state: str, message: str = "", _preview: str = "", **_kwargs) -> None:
        self.states.append((state, message))

    def set_level(self, _level: float) -> None:
        return

    def flag(self, message: str, *, detail: str = "", **_kwargs) -> None:
        # X-743: the Pill says it itself (Overlay.flag), title then detail.
        self.toasts.append(f"{message}. {detail}".strip())


def processing_app(mode: str = "dictation"):
    """An app whose take was released and is being formatted right now."""
    token = object()
    app = TalkDatApp.__new__(TalkDatApp)
    app.lock = threading.RLock()
    app.session = None
    app.session_token = token
    app._released_processing = True
    app._trigger_released_at = time.perf_counter()
    app._flight_mode = (token, mode)
    app._guided_delivery_token = None
    app._deferred_delivery_owner = None
    app.session_chime_token = None
    app.session_mode = "processing"
    app.session_control = "processing"
    app.session_error_message = ""
    app.safety_capture = None
    app.safety_capture_token = None
    app.safety_capture_failure_token = None
    app.last_transcript = ""
    app.last_original = ""
    app.last_diff = ""
    app.overlay = _Overlay()
    app.config = {"dictation": {"auto_paste": True, "paste_mode": "clipboard"}, "privacy": {"save_history": True}}
    app.release_activation_guards = lambda: None
    app.play_sound = lambda _name: None
    app.play_landing_sound = lambda: None
    app.write_live_draft = lambda *_args: None
    app.history: list[dict] = []
    app.add_history = app.history.append
    return app, token


def press_esc(callbacks: dict) -> None:
    """The real keyboard path: HotkeyController, its dispatch worker, the callback."""
    done = threading.Event()
    wrapped = dict(callbacks)
    original = wrapped["cancel"]

    def cancel_then_signal() -> None:
        try:
            original()
        finally:
            done.set()

    wrapped["cancel"] = cancel_then_signal
    controller = HotkeyController({"cancel": [["esc"]]}, wrapped)
    controller._on_key_press_name("esc")
    controller._on_key_release_name("esc")
    assert done.wait(2.0), "the Esc callback never ran"


def deliver(app, token) -> list[dict]:
    calls: list[dict] = []

    def paste(text, **options):
        calls.append({"text": text, **options})
        mode = options.get("paste_mode")
        return PasteReceipt(True, mode, "copy_only" if mode == "copy_only" else "clipboard", (mode,))

    with (
        patch("knight_flow.app.process_dictation",
              return_value=SimpleNamespace(original="the words", text="The words.", send_enter=False)),
        patch("knight_flow.app.paste_text_with_receipt", side_effect=paste),
    ):
        app.handle_dictation("the words", delivery_token=token, guided_sink=None)
    return calls


class EscWhileProcessingTests(unittest.TestCase):
    def assert_kept_not_pasted(self, app, calls) -> None:
        self.assertTrue(calls, "the words went nowhere")
        self.assertEqual([call["paste_mode"] for call in calls], ["copy_only"],
                         "the words were typed into whatever had focus")
        self.assertEqual(calls[0]["text"], "The words.")
        self.assertEqual(len(app.history), 1, "History does not have the words")
        self.assertEqual(app.overlay.states[-1], ("captured", "Kept, not pasted."))
        self.assertTrue(app.overlay.toasts and app.overlay.toasts[-1].startswith("Kept, not pasted."))

    def test_esc_on_a_processing_take_keeps_the_words(self) -> None:
        app, token = processing_app()
        press_esc(TalkDatApp._hotkey_callbacks(app, {"cancel": app.cancel}))
        self.assertIs(app.session_token, token, "Esc cancelled the take that was landing")
        self.assert_kept_not_pasted(app, deliver(app, token))

    def test_sabotage_esc_mapped_back_to_cancel_loses_the_words(self) -> None:
        app, token = processing_app()
        press_esc({"cancel": app.cancel})   # the old keyboard map
        calls = deliver(app, token)
        with self.assertRaises(AssertionError):
            self.assert_kept_not_pasted(app, calls)

    def test_without_esc_the_take_pastes_as_always(self) -> None:
        app, token = processing_app()
        calls = deliver(app, token)
        self.assertEqual([call["paste_mode"] for call in calls], ["clipboard"])

    def test_the_tray_cancel_is_still_the_full_cancel(self) -> None:
        app, _token = processing_app()
        mapped = TalkDatApp._hotkey_callbacks(app, {"cancel": app.cancel, "hands_free": app.cancel})
        self.assertEqual(mapped["cancel"], app.cancel_from_key)
        self.assertEqual(mapped["hands_free"], app.cancel)

    def test_with_the_microphone_open_esc_cancels(self) -> None:
        app, _token = processing_app()
        app.session = mock.Mock()
        app._released_processing = False
        app.cancel = mock.Mock()
        app.cancel_from_key()
        app.cancel.assert_called_once()

    def test_a_command_finishing_keeps_its_full_cancel(self) -> None:
        app, _token = processing_app(mode="command")
        app.cancel = mock.Mock()
        app.cancel_from_key()
        app.cancel.assert_called_once()

    def test_idle_esc_does_nothing(self) -> None:
        app, _token = processing_app()
        app.session_token = None
        app.cancel = mock.Mock()
        app.cancel_from_key()
        app.cancel.assert_not_called()
        self.assertEqual(app.overlay.states, [])

    def test_a_password_is_never_copied(self) -> None:
        app, token = processing_app()
        app.cancel_from_key()
        probe = SimpleNamespace(result=lambda *_a: "password", secure_or_pending=lambda: True)
        app._session_field = (token, probe)
        calls = deliver(app, token)
        self.assertEqual(calls, [])
        self.assertEqual(app.history, [])


if __name__ == "__main__":
    unittest.main()
