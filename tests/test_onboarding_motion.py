from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from knight_flow.ui.onboarding import ART_RESIZE_SETTLE_MS, OnboardingWizard


class _QueuedWindow:
    def __init__(self) -> None:
        self._next = 0
        self.pending: dict[str, object] = {}
        self.delays: list[int | str] = []
        self.cancelled: list[str] = []
        self.height = 720

    def _store(self, delay: int | str, callback: object) -> str:
        self._next += 1
        receipt = f"after-{self._next}"
        self.delays.append(delay)
        self.pending[receipt] = callback
        return receipt

    def after(self, delay: int, callback: object) -> str:
        return self._store(delay, callback)

    def after_idle(self, callback: object) -> str:
        return self._store("idle", callback)

    def after_cancel(self, receipt: str) -> None:
        self.cancelled.append(receipt)
        self.pending.pop(receipt, None)

    def winfo_height(self) -> int:
        return self.height

    def run_only_pending(self) -> None:
        self.assert_one_pending()
        _receipt, callback = self.pending.popitem()
        callback()  # type: ignore[operator]

    def assert_one_pending(self) -> None:
        if len(self.pending) != 1:
            raise AssertionError(f"expected one pending callback, got {self.pending!r}")


class _SizingCanvas:
    def __init__(self, width: int = 420, height: int = 220) -> None:
        self.width = width
        self.height = height
        self.exists = True

    def winfo_exists(self) -> bool:
        return self.exists

    def winfo_width(self) -> int:
        return self.width

    def winfo_height(self) -> int:
        return self.height


def _motion_wizard() -> tuple[OnboardingWizard, _QueuedWindow]:
    wizard = OnboardingWizard.__new__(OnboardingWizard)
    window = _QueuedWindow()
    wizard.window = window
    wizard.destroyed = False
    wizard.px = lambda value: int(value)
    wizard._art_render_state = {}
    wizard.dynamic_photos = {}
    wizard._content_extent_after = None
    wizard._content_extent_signature = None
    return wizard, window


class ArtworkResizeQueueTests(unittest.TestCase):
    def test_a_resize_burst_renders_only_the_last_distinct_size(self) -> None:
        wizard, window = _motion_wizard()
        canvas = _SizingCanvas()
        draws: list[tuple[int, int]] = []

        def draw(target: _SizingCanvas, _key: str, _centering: object) -> None:
            size = (target.width, max(120, target.height))
            draws.append(size)
            wizard._art_render_state[id(target)]["rendered_size"] = size

        wizard._draw_art_panel = draw  # type: ignore[method-assign]

        wizard._queue_art_panel_draw(
            canvas,  # type: ignore[arg-type]
            "intro",
            event=SimpleNamespace(width=420, height=220),
        )
        self.assertEqual(window.delays, ["idle"])
        window.run_only_pending()
        self.assertEqual(draws, [])
        window.run_only_pending()
        self.assertEqual(draws, [(420, 220)])

        for width in range(430, 631, 10):
            canvas.width = width
            canvas.height = 260
            wizard._queue_art_panel_draw(
                canvas,  # type: ignore[arg-type]
                "intro",
                event=SimpleNamespace(width=width, height=260),
            )

        window.assert_one_pending()
        self.assertEqual(window.delays[:2], ["idle", 16])
        self.assertTrue(all(delay == ART_RESIZE_SETTLE_MS for delay in window.delays[2:]))
        window.run_only_pending()
        self.assertEqual(draws, [(420, 220), (630, 260)])

        # A duplicate final Configure event is a no-op, not another repaint.
        wizard._queue_art_panel_draw(
            canvas,  # type: ignore[arg-type]
            "intro",
            event=SimpleNamespace(width=630, height=260),
        )
        self.assertEqual(window.pending, {})
        self.assertEqual(draws, [(420, 220), (630, 260)])

    def test_destroyed_art_cancels_its_callback_and_releases_its_photo(self) -> None:
        wizard, window = _motion_wizard()
        canvas = _SizingCanvas()
        key = f"art:intro:{id(canvas)}"
        wizard.dynamic_photos[key] = object()  # type: ignore[assignment]

        wizard._queue_art_panel_draw(canvas, "intro")  # type: ignore[arg-type]
        receipt = next(iter(window.pending))
        wizard._forget_art_panel(canvas, "intro")  # type: ignore[arg-type]

        self.assertEqual(window.pending, {})
        self.assertEqual(window.cancelled, [receipt])
        self.assertNotIn(id(canvas), wizard._art_render_state)
        self.assertNotIn(key, wizard.dynamic_photos)

    def test_manual_resize_waits_for_the_shells_exact_settle_event(self) -> None:
        wizard, window = _motion_wizard()
        canvas = _SizingCanvas()
        draws: list[tuple[int, int]] = []

        def draw(target: _SizingCanvas, _key: str, _centering: object) -> None:
            size = (target.width, max(120, target.height))
            draws.append(size)
            wizard._art_render_state[id(target)]["rendered_size"] = size

        wizard._draw_art_panel = draw  # type: ignore[method-assign]
        wizard._queue_art_panel_draw(canvas, "intro")  # type: ignore[arg-type]
        window.run_only_pending()
        window.run_only_pending()

        window._talkdat_live_resize = True
        for width in (480, 560, 640):
            canvas.width = width
            wizard._queue_art_panel_draw(
                canvas,  # type: ignore[arg-type]
                "intro",
                event=SimpleNamespace(width=width, height=220),
            )
        self.assertEqual(window.pending, {})
        self.assertEqual(draws, [(420, 220)])

        window._talkdat_live_resize = False
        wizard._settle_art_panels()
        self.assertEqual(window.delays[-1], "idle")
        window.run_only_pending()
        self.assertEqual(draws, [(420, 220), (640, 220)])

    def test_timer_queued_before_press_cannot_render_during_the_drag(self) -> None:
        wizard, window = _motion_wizard()
        canvas = _SizingCanvas()
        draws: list[tuple[int, int]] = []

        def draw(target: _SizingCanvas, _key: str, _centering: object) -> None:
            size = (target.width, max(120, target.height))
            draws.append(size)
            wizard._art_render_state[id(target)]["rendered_size"] = size

        wizard._draw_art_panel = draw  # type: ignore[method-assign]
        wizard._queue_art_panel_draw(canvas, "intro")  # type: ignore[arg-type]
        window.run_only_pending()
        window.run_only_pending()
        canvas.width = 620
        wizard._queue_art_panel_draw(  # type: ignore[arg-type]
            canvas,
            "intro",
            event=SimpleNamespace(width=620, height=220),
        )
        window._talkdat_live_resize = True
        window.run_only_pending()
        self.assertEqual(draws, [(420, 220)])

        window._talkdat_live_resize = False
        wizard._settle_art_panels()
        window.run_only_pending()
        self.assertEqual(draws, [(420, 220), (620, 220)])

    def test_transient_document_height_is_never_rendered_as_art(self) -> None:
        wizard, window = _motion_wizard()
        canvas = _SizingCanvas(width=526, height=2976)
        draws: list[tuple[int, int]] = []

        def draw(target: _SizingCanvas, _key: str, _centering: object) -> None:
            size = (target.width, target.height)
            draws.append(size)
            wizard._art_render_state[id(target)]["rendered_size"] = size

        wizard._draw_art_panel = draw  # type: ignore[method-assign]
        wizard._queue_art_panel_draw(canvas, "intro")  # type: ignore[arg-type]
        window.run_only_pending()
        window.run_only_pending()
        self.assertEqual(draws, [])

        canvas.width, canvas.height = 537, 373
        window.run_only_pending()
        window.run_only_pending()
        self.assertEqual(draws, [(537, 373)])


class _DrawingCanvas(_SizingCanvas):
    def __init__(self, events: list[str]) -> None:
        super().__init__(320, 180)
        self.events = events

    def delete(self, _target: object) -> None:
        self.events.append("delete")

    def create_image(self, *_args: object, **_kwargs: object) -> int:
        self.events.append("image")
        return 1

    def create_polygon(self, *_args: object, **_kwargs: object) -> int:
        self.events.append("border")
        return 2


class ArtworkSwapTests(unittest.TestCase):
    def test_the_previous_frame_is_not_cleared_until_the_new_photo_is_complete(self) -> None:
        wizard, _window = _motion_wizard()
        events: list[str] = []
        canvas = _DrawingCanvas(events)
        wizard.palette = {"stroke": "#333333", "field": "#111111"}
        wizard.art_sources = {"01-arrival-stone.png": Image.new("RGB", (16, 16), "black")}

        def photo_ready(*_args: object, **_kwargs: object) -> object:
            events.append("photo")
            return object()

        with patch("knight_flow.ui.onboarding.ImageTk.PhotoImage", side_effect=photo_ready):
            wizard._draw_art_panel(canvas, "intro")  # type: ignore[arg-type]

        self.assertLess(events.index("photo"), events.index("delete"))
        self.assertEqual(events.count("delete"), 1)
        self.assertEqual(events[-2:], ["image", "border"])


class _ContentCanvas:
    def __init__(self) -> None:
        self.width = 700
        self.height = 480
        self.item_updates = 0
        self.config_updates = 0

    def winfo_exists(self) -> bool:
        return True

    def winfo_width(self) -> int:
        return self.width

    def winfo_height(self) -> int:
        return self.height

    def itemconfigure(self, *_args: object, **_kwargs: object) -> None:
        self.item_updates += 1

    def configure(self, **_kwargs: object) -> None:
        self.config_updates += 1


class _Content:
    def __init__(self) -> None:
        self.required_height = 560

    def winfo_reqheight(self) -> int:
        return self.required_height


class ContentExtentQueueTests(unittest.TestCase):
    def test_canvas_and_content_configures_share_one_idle_layout_pass(self) -> None:
        wizard, window = _motion_wizard()
        wizard.content_canvas = _ContentCanvas()  # type: ignore[assignment]
        wizard.content = _Content()  # type: ignore[assignment]
        wizard.content_window = object()

        wizard._queue_content_extent_sync()
        wizard._queue_content_extent_sync()
        window.run_only_pending()
        self.assertEqual(wizard.content_canvas.item_updates, 1)
        self.assertEqual(wizard.content_canvas.config_updates, 1)

        # The same settled geometry is ignored even if Tk repeats Configure.
        wizard._queue_content_extent_sync()
        window.run_only_pending()
        self.assertEqual(wizard.content_canvas.item_updates, 1)

        wizard.content.required_height = 620
        wizard._queue_content_extent_sync()
        window.run_only_pending()
        self.assertEqual(wizard.content_canvas.item_updates, 2)


class OnboardingCloseMotionTests(unittest.TestCase):
    def test_header_close_uses_the_shared_transition_but_finish_stays_immediate(self) -> None:
        source = Path(__file__).resolve().parents[1].joinpath(
            "knight_flow", "ui", "onboarding.py"
        ).read_text(encoding="utf-8")
        shell_start = source.index("def _build_shell(")
        shell_end = source.index("def _content_yview_changed(", shell_start)
        shell = source[shell_start:shell_end]
        finish_start = source.index("def finish(")
        finish_end = source.index("def _invoke_callback(", finish_start)
        finish = source[finish_start:finish_end]

        # The header used to call `self.host._request_utility_close(self.window)`
        # from its own AtelierButton. The titlebar now uses the app's shared
        # caption glyphs instead of word buttons, and `_close_control` makes
        # that same call inside overlay.py -- plus the close-lock check the
        # hand-wired command never had. The contract this test exists to hold
        # is unchanged: the header closes through the shared transition and
        # never destroys the window itself.
        self.assertIn("self.host._close_control(", shell)
        self.assertNotIn("command=self.window.destroy", shell)
        self.assertNotIn("self.window.destroy()", shell)
        self.assertIn("self.window.destroy()", finish)


if __name__ == "__main__":
    unittest.main()
