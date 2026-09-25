"""X-633 (interaction grid d2, d3): a paused or refusing Pill says why.

A paused Pill ignored clicks and hotkeys and looked idle; starts refused by a
meeting, Scribe, the mic check or pronunciation practice only repainted the
idle Pill with a status line nobody sees. A press did nothing and said
nothing.

Now each refusal raises its reason as a toast, at most one every 3 s, and a
paused Pill looks paused: gray at 60%.

The GUI half runs through scripts/run_tests_offscreen.py.
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

import numpy as np

from knight_flow.app import RESUME_SURFACE_NAME, TalkDatApp


def refusing_app(**state):
    app = TalkDatApp.__new__(TalkDatApp)
    app.lock = threading.RLock()
    app.session = None
    app.session_token = None
    app._released_processing = False
    app._trigger_released_at = None
    app.paused = False
    app._scribe_busy = lambda: False
    app.meeting = None
    app.config = {"stt": {"provider": "local", "providers": {}}, "dictation": {}}
    app.overlay = mock.Mock()
    app.overlay._ui_thread_id = threading.get_ident()
    app._wake_runtime = None
    app._maybe_return_to_cloud = lambda: None
    for name, value in state.items():
        setattr(app, name, value)
    return app


class RefusalsSayWhyTests(unittest.TestCase):
    def test_a_paused_start_says_so_once_per_three_seconds(self) -> None:
        app = refusing_app(paused=True)
        app.start_session("dictation", "Hands-free: toggle to stop.", control="hands_free")
        app.start_session("dictation", "Hands-free: toggle to stop.", control="hands_free")
        app.overlay.flag.assert_called_once_with(
            f"Talk DAT! is paused. Resume from {RESUME_SURFACE_NAME}: Resume dictation.",
            key="refusal", origin="person")
        self.assertEqual(app.overlay.set_state.call_count, 2)
        app._last_refusal_toast_at -= 3.1
        app.start_session("dictation", "Hands-free: toggle to stop.", control="hands_free")
        self.assertEqual(app.overlay.flag.call_count, 2)

    def test_a_meeting_scribe_mic_check_or_practice_refusal_says_why(self) -> None:
        cases = {
            "meeting": dict(meeting=mock.Mock(running=True)),
            "mic check": dict(_microphone_check=mock.Mock(finished=mock.Mock(is_set=lambda: False))),
            "practice": dict(_pronunciation_practice=mock.Mock(active=True)),
        }
        for name, state in cases.items():
            with self.subTest(refusal=name):
                app = refusing_app(**state)
                app.start_session("dictation", "Hold mode: release to stop.")
                app.overlay.flag.assert_called_once()
                self.assertIn("before dictating", app.overlay.flag.call_args.args[0])

    def test_pausing_and_resuming_set_the_look(self) -> None:
        app = refusing_app()
        app.refresh_wake_word = lambda: None
        app.cancel = mock.Mock()
        app.tray = mock.Mock()
        app.toggle_pause()
        app.overlay.set_paused.assert_called_with(True)
        app.toggle_pause()
        app.overlay.set_paused.assert_called_with(False)


class ThePausedLookTests(unittest.TestCase):
    def drawn(self, overlay):
        import knight_flow.overlay as module

        real = module.ImageTk.PhotoImage
        seen = []

        def spy(image=None, *args, **kwargs):
            seen.append(image)
            return real(image, *args, **kwargs)

        overlay.idle_photo_cache.clear()
        overlay.idle_render_cache.clear()
        real_layered = overlay._present_layered

        def layered_spy(image, *args, **kwargs):
            seen.append(image)
            return real_layered(image, *args, **kwargs)

        with mock.patch.object(module.ImageTk, "PhotoImage", side_effect=spy), \
                mock.patch.object(overlay, "_present_layered", side_effect=layered_spy):
            overlay._draw_visual()
        return seen[-1]

    def test_paused_is_gray_at_sixty_percent_and_resume_restores_it(self) -> None:
        from tests.pill_harness import build_overlay, destroy_overlay, pump

        overlay = build_overlay({})
        self.addCleanup(destroy_overlay, overlay)
        overlay.set_paused(True)
        pump(overlay.root, 0.2)
        pixels = np.asarray(self.drawn(overlay).convert("RGBA"), dtype=np.int32)
        body = pixels[pixels[..., 3] > 0]
        self.assertTrue(len(body))
        self.assertLessEqual(int(body[:, 3].max()), int(255 * 0.6) + 1, "a paused Pill is not dimmed")
        spread = np.max(np.abs(body[:, 0] - body[:, 1])) + np.max(np.abs(body[:, 1] - body[:, 2]))
        self.assertLessEqual(int(spread), 4, "a paused Pill is not gray")
        overlay.set_paused(False)
        pump(overlay.root, 0.2)
        pixels = np.asarray(self.drawn(overlay).convert("RGBA"), dtype=np.int32)
        self.assertEqual(int(pixels[..., 3].max()), 255)


if __name__ == "__main__":
    unittest.main()
