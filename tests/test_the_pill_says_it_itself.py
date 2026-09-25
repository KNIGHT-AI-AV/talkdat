"""X-742: a message is the Pill itself changing shape, in the Pill's own bitmap.

The owner rejected messages that "look like a separate piece" and asked for
parts that "morph out of the same asset design element universe, not a weird
overlay". These tests drive a real Overlay on the offscreen desktop and read
the bitmaps it hands to UpdateLayeredWindow:

* a lengthened Pill is ONE continuous capsule: no gap, no second shape, alpha
  above zero along its whole midline, an outline whose radius is half its
  height, and nothing drawn outside it;
* it is the Pill's own window that grows (no second window appears), in one
  call with its pixels, and it comes back to the exact idle rectangle and
  frame size when the message has gone;
* the end nearer a side stays exactly where it was while the far end moves,
  and the bottom edge stays on the edge it sits on;
* focus never moves, the window keeps WS_EX_NOACTIVATE, the queue and its
  safety rules hold on the real Pill, reduced motion only fades, the
  colour-key fallback shows a plain capsule, a segment's Pill end still
  dictates, dictation pre-empts a message, and screen readers are told.

Runs only through scripts/run_tests_offscreen.py.
"""
from __future__ import annotations

import ctypes
import sys
import time
import tkinter as tk
import unittest
from ctypes import wintypes
from unittest import mock

import numpy as np

from knight_flow import island
from knight_flow.layered_window import capsule_alpha_mask
from tests.pill_harness import Counter, build_overlay, destroy_overlay, pump

WS_EX_NOACTIVATE = 0x08000000


def user32():
    dll = ctypes.WinDLL("user32", use_last_error=True)
    dll.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    dll.GetAncestor.restype = wintypes.HWND
    dll.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    dll.GetWindowRect.restype = wintypes.BOOL
    dll.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    dll.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    dll.GetForegroundWindow.restype = wintypes.HWND
    dll.IsWindowVisible.argtypes = (wintypes.HWND,)
    dll.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    return dll


USER32 = user32() if sys.platform == "win32" else None


def outer(overlay) -> int:
    return int(USER32.GetAncestor(int(overlay.root.winfo_id()), 2) or 0)


def window_rect(overlay) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    USER32.GetWindowRect(outer(overlay), ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def process_windows() -> set[int]:
    """Every visible top-level window this process owns."""
    found: set[int] = set()
    pid = ctypes.windll.kernel32.GetCurrentProcessId()
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd, _lparam):
        owner = wintypes.DWORD()
        USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and USER32.IsWindowVisible(hwnd):
            found.add(int(hwnd))
        return True

    ctypes.windll.user32.EnumWindows(proc(collect), 0)
    return found


class Pushed:
    """Every bitmap the presenter hands to UpdateLayeredWindow, with where."""

    def __init__(self, overlay) -> None:
        self.frames: list[tuple[tuple[int, int] | None, np.ndarray]] = []
        api = overlay._pill_presenter.api
        plain, moved = api.update_layered, api.update_layered_at

        def spy_plain(hwnd, width, height, bgra, alpha):
            ok = plain(hwnd, width, height, bgra, alpha)
            if ok:
                self.frames.append((None, np.frombuffer(bytes(bgra), np.uint8).reshape(height, width, 4).copy()))
            return ok

        def spy_moved(hwnd, x, y, width, height, bgra, alpha):
            ok = moved(hwnd, x, y, width, height, bgra, alpha)
            if ok:
                self.frames.append(((x, y), np.frombuffer(bytes(bgra), np.uint8).reshape(height, width, 4).copy()))
            return ok

        api.update_layered, api.update_layered_at = spy_plain, spy_moved

    def last(self) -> np.ndarray:
        assert self.frames, "nothing was pushed"
        return self.frames[-1][1]


def settle_idle(overlay, seconds: float = 3.0) -> None:
    deadline = time.perf_counter() + seconds
    pump(overlay.root, 0.1)
    while (overlay._open_anim_active or overlay._flag_view is not None) and time.perf_counter() < deadline:
        pump(overlay.root, 0.02)
    pump(overlay.root, 0.1)


def until(overlay, predicate, seconds: float = 4.0) -> bool:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if predicate():
            return True
        pump(overlay.root, 0.01)
    return bool(predicate())


def components(mask: np.ndarray) -> int:
    """Connected pieces (4-neighbour) of a boolean mask."""
    seen = np.zeros_like(mask, dtype=bool)
    height, width = mask.shape
    count = 0
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        count += 1
        stack = [(y0, x0)]
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
    return count


QUIET = mock.patch("knight_flow.meeting_quiet.meeting_in_progress", return_value=False)


@unittest.skipUnless(sys.platform == "win32", "UpdateLayeredWindow is Windows")
class TheMessageIsThePillTests(unittest.TestCase):
    def setUp(self) -> None:
        QUIET.start()
        self.addCleanup(QUIET.stop)
        self.overlay = build_overlay({})
        self.addCleanup(destroy_overlay, self.overlay)
        settle_idle(self.overlay)
        self.assertTrue(self.overlay._pill_presenter.armed, self.overlay._pill_presenter_path)

    def say(self, *args, **kwargs):
        overlay = self.overlay
        overlay.flag(*args, **kwargs)
        self.assertTrue(until(overlay, lambda: overlay._flag_view is not None and overlay._flag_view.phase == "hold"),
                        "the message never settled")
        pump(overlay.root, 0.05)
        return overlay._flag_view

    def test_the_lengthened_pill_is_one_continuous_capsule(self) -> None:
        overlay = self.overlay
        before = process_windows()
        pushed = Pushed(overlay)
        view = self.say("Your speech provider did not answer", detail="This one was transcribed on this PC.")
        overlay._draw_visual()
        alpha = pushed.last()[..., 3]
        x, y, w, h = view.capsule_now
        self.assertEqual((w, h), (view.target.w, view.target.h), "not settled on the capsule")
        # No second window: the Pill's own window grew to hold it.
        self.assertEqual(process_windows(), before, "a message opened a window of its own")
        self.assertEqual(window_rect(overlay), (view.envelope.x, view.envelope.y, view.envelope.w, view.envelope.h))
        self.assertEqual(alpha.shape, (view.envelope.h, view.envelope.w))
        # One piece, nothing outside it.
        drawn = alpha > 0
        self.assertEqual(components(drawn), 1, "the capsule is in more than one piece")
        outside = drawn.copy()
        outside[y:y + h, x:x + w] = False
        self.assertEqual(int(outside.sum()), 0, "something is drawn outside the capsule")
        # No gap anywhere along the midline, from one rounded end to the other.
        mid = alpha[y + h // 2, x:x + w]
        self.assertTrue(np.all(mid[1:-1] > 0), "the midline has a gap")
        self.assertTrue(np.all(mid[2:-2] == 255), "the capsule is not solid inside")
        # The outline is a capsule of radius h/2: exactly the Pill's own mask.
        expected = np.asarray(capsule_alpha_mask(w, h)).astype(int)
        self.assertLessEqual(int(np.abs(alpha[y:y + h, x:x + w].astype(int) - expected).max()), 1)
        r = h / 2.0
        for row in range(1, h - 1):
            edge = int(np.argmax(alpha[y + row, x:x + w] >= 128))
            circle = r - np.sqrt(max(0.0, r * r - (row + 0.5 - r) ** 2))
            self.assertAlmostEqual(edge, circle, delta=1.01, msg=f"row {row}: the end is not a half circle of radius h/2")

    def test_the_pinned_end_stays_and_the_far_end_moves(self) -> None:
        overlay = self.overlay
        pill = overlay._flag_pill_rect()
        pushed = Pushed(overlay)
        view = self.say("Copied your last dictation", tone="done")
        grow = [(where, frame) for where, frame in pushed.frames if where is not None]
        self.assertGreater(len(grow), 6, "the Pill did not lengthen over several frames")
        lefts, rights, bottoms = set(), [], set()
        for (wx, wy), frame in grow:
            drawn = frame[..., 3] > 0
            columns = np.nonzero(drawn.any(axis=0))[0]
            rows = np.nonzero(drawn.any(axis=1))[0]
            lefts.add(wx + int(columns[0]))
            rights.append(wx + int(columns[-1]))
            bottoms.add(wy + int(rows[-1]))
        self.assertEqual(view.pin, "left", "a centred Pill pins its left end")
        self.assertEqual(lefts, {pill.x}, "the pinned end moved")
        self.assertEqual(bottoms, {pill.y + pill.h - 1}, "the Pill left the edge it sits on")
        self.assertGreater(len(set(rights)), 5, "the far end did not travel")
        self.assertEqual(rights[0], pill.x + pill.w - 1, "frame 0 is not the Pill")
        self.assertGreater(max(rights), pill.x + pill.w + 100)

    def test_frame_zero_is_the_pill_itself(self) -> None:
        from knight_flow.layered_window import premultiplied_bgra

        overlay = self.overlay
        pushed = Pushed(overlay)
        with mock.patch.object(type(overlay), "_flag_clock_ms", lambda _self: 1_000_000.0):
            overlay.flag("Copied your last dictation", tone="info")
            first = next(frame for where, frame in pushed.frames if where is not None)
        # The Pill's art moves on its own at rest, so frame 0 is compared with
        # the Pill's own frame of the SAME picture: what it would have shown.
        source = overlay._layered_frame(overlay._pill_layered_source)
        idle = np.frombuffer(premultiplied_bgra(source), np.uint8).reshape(source.height, source.width, 4)
        pill = overlay._flag_view.pill
        env = overlay._flag_view.envelope
        crop = first[pill.y - env.y:pill.y - env.y + pill.h, pill.x - env.x:pill.x - env.x + pill.w]
        self.assertLessEqual(int(np.abs(crop.astype(int) - idle.astype(int)).max()), 2,
                             "frame 0 is not the Pill's own picture")
        rest = first.copy()
        rest[pill.y - env.y:pill.y - env.y + pill.h, pill.x - env.x:pill.x - env.x + pill.w] = 0
        self.assertEqual(int(rest[..., 3].max()), 0, "frame 0 draws beyond the Pill")

    def test_a_frame_of_the_lengthened_pill_is_cheap(self) -> None:
        """X-170: the UI thread composes each frame; it must stay well inside a
        16 ms frame even at 150% (these Pills are built at 1.5x)."""
        import statistics

        overlay = self.overlay
        view = self.say("Your speech provider did not answer", detail="This one was transcribed on this PC.")
        field = overlay._pill_layered_source
        costs = []
        for index in range(30):
            start = time.perf_counter()
            overlay._flag_frame(view, field, view.started_ms + index * 17.0)
            costs.append((time.perf_counter() - start) * 1000.0)
        median = statistics.median(costs)
        print(f"\nX-742 lengthened-Pill frame: median {median:.2f} ms, worst {max(costs):.2f} ms")
        self.assertLess(median, 12.0)

    def test_contraction_returns_to_the_exact_idle_frame(self) -> None:
        overlay = self.overlay
        idle_rect = window_rect(overlay)
        idle_geometry = overlay._last_geometry
        idle_size = (int(overlay.current_width), int(overlay.current_height))
        pushed = Pushed(overlay)
        self.say("Nothing heard", tone="info")
        self.assertNotEqual(window_rect(overlay), idle_rect)
        overlay._flag_contract()
        self.assertTrue(until(overlay, lambda: overlay._flag_view is None), "the message never folded")
        pump(overlay.root, 0.1)
        self.assertEqual(window_rect(overlay), idle_rect, "the Pill did not come back to its own rectangle")
        self.assertEqual(overlay._last_geometry, idle_geometry)
        where, frame = pushed.frames[-1]
        self.assertEqual((frame.shape[1], frame.shape[0]), idle_size, "the last frame is not the idle size")
        # The contraction ended with the Pill's own frame placed in the same call.
        moved = [where for where, _frame in pushed.frames if where is not None]
        self.assertEqual(moved[-1], (idle_rect[0], idle_rect[1]))

    def test_a_click_puts_it_away_and_the_next_click_dictates(self) -> None:
        overlay = self.overlay
        dictated = Counter()
        overlay.callbacks["pill_hands_free"] = dictated
        view = self.say("Copied your last dictation", tone="done")
        x, y, w, h = view.capsule_now
        point = (view.envelope.x + x + w - 30, view.envelope.y + y + h // 2)
        press(overlay, *point)
        self.assertEqual(dictated.calls, 0, "a click on the message started a dictation")
        self.assertEqual(overlay._flag_view.phase, "out")
        self.assertTrue(until(overlay, lambda: overlay._flag_view is None))
        pump(overlay.root, 0.6)  # past the double-click time
        rect = window_rect(overlay)
        press(overlay, rect[0] + rect[2] // 2, rect[1] + rect[3] // 2)
        self.assertEqual(dictated.calls, 1)

    def test_focus_never_moves(self) -> None:
        overlay = self.overlay
        other = tk.Toplevel(overlay.root)
        other.geometry("200x120+40+40")
        other.attributes("-alpha", 1.0)
        pump(overlay.root, 0.1)
        other.focus_force()
        pump(overlay.root, 0.2)
        other_hwnd = int(USER32.GetAncestor(int(other.winfo_id()), 2) or 0)
        foreground = int(USER32.GetForegroundWindow() or 0)
        try:
            view = self.say("The microphone did not start.", detail="Check your microphone.", tone="error")
            style = int(USER32.GetWindowLongPtrW(outer(overlay), -20))
            self.assertTrue(style & WS_EX_NOACTIVATE, "the lengthened Pill can take the focus")
            x, y, w, h = view.capsule_now
            press(overlay, view.envelope.x + x + w // 2, view.envelope.y + y + h // 2)
            self.assertTrue(until(overlay, lambda: overlay._flag_view is None))
            self.assertTrue(int(USER32.GetWindowLongPtrW(outer(overlay), -20)) & WS_EX_NOACTIVATE)
            if foreground == other_hwnd:
                self.assertEqual(int(USER32.GetForegroundWindow() or 0), other_hwnd, "the message took the focus")
            self.assertNotEqual(int(USER32.GetForegroundWindow() or 0), outer(overlay))
        finally:
            other.destroy()

    def test_an_info_never_replaces_an_unread_error_on_the_pill(self) -> None:
        overlay = self.overlay
        view = self.say("No sound is reaching the microphone.", detail="Check the input device.", tone="error")
        overlay.flag("Talk DAT! is up to date")
        pump(overlay.root, 0.3)
        self.assertIs(overlay._flag_view, view, "the info replaced the error")
        overlay._flag_contract()
        self.assertTrue(until(overlay, lambda: overlay._flag_view is not None
                              and overlay._flag_view.message.title == "Talk DAT! is up to date", 3.0))

    def test_the_same_key_updates_in_place(self) -> None:
        overlay = self.overlay
        view = self.say("Installing 1.2.4", tone="info", key="install", progress=0.2)
        words = view.words
        overlay.flag("Installing 1.2.4", tone="info", key="install", progress=0.7)
        pump(overlay.root, 0.05)
        self.assertIs(overlay._flag_view, view, "an update made a new entrance")
        self.assertIsNot(view.words, words)
        self.assertEqual(view.message.progress, 0.7)

    def test_hover_holds_a_message(self) -> None:
        overlay = self.overlay
        view = self.say("Copied your last dictation", tone="done", hold_ms=500)
        x, y, w, h = view.capsule_now
        centre = (view.envelope.x + x + w // 2, view.envelope.y + y + h // 2)
        with mock.patch.object(overlay.root, "winfo_pointerxy", return_value=centre):
            pump(overlay.root, 1.2)
            self.assertIs(overlay._flag_view, view, "it contracted under the pointer")
            self.assertEqual(view.phase, "hold")
        with mock.patch.object(overlay.root, "winfo_pointerxy", return_value=(-30000, -30000)):
            self.assertTrue(until(overlay, lambda: overlay._flag_view is None, 4.0), "it never left")

    def test_dictation_pre_empts_and_the_error_comes_back(self) -> None:
        overlay = self.overlay
        self.say("The microphone did not start.", detail="Check your microphone.", tone="error")
        overlay.set_state("listening", "", "")
        view = overlay._flag_view
        self.assertTrue(view is not None and view.preempt and view.phase == "out")
        self.assertTrue(overlay.compact, "the open animation did not wait for the message to fold")
        self.assertTrue(until(overlay, lambda: overlay._flag_view is None, 2.0))
        self.assertTrue(until(overlay, lambda: not overlay.compact, 2.0), "the Pill never opened")
        self.assertIsNone(overlay._flag_view, "a message stretched while the Pill was live")
        overlay.set_state("idle", "", "")
        self.assertTrue(until(overlay, lambda: overlay._flag_view is not None, 3.0), "the error never came back")
        self.assertEqual(overlay._flag_view.message.tone, "error")

    def test_a_state_that_opts_in_says_its_words_and_never_the_dictation(self) -> None:
        overlay = self.overlay
        overlay.set_state("captured", "Copied last transcript to the clipboard.", "the words someone dictated",
                          say=True)
        self.assertTrue(until(overlay, lambda: overlay._flag_view is not None))
        view = overlay._flag_view
        self.assertEqual((view.message.title, view.message.detail, view.message.tone),
                         ("Copied last transcript to the clipboard.", "", "done"))
        overlay._flag_end_now()
        overlay._flag_queue = island.MessageQueue()
        overlay.set_state("captured", "Pasted.", "the words someone dictated")
        pump(overlay.root, 0.2)
        self.assertIsNone(overlay._flag_view, "a state that did not opt in spoke")

    def test_screen_readers_are_told_once_with_the_tone(self) -> None:
        overlay = self.overlay
        with mock.patch("knight_flow.overlay.announce_to_screen_reader") as spoken:
            self.say("The microphone did not start.", detail="Check your microphone.", tone="error")
        spoken.assert_called_once()
        hwnd, text, tone = spoken.call_args.args
        self.assertEqual((hwnd, tone), (outer(overlay), "error"))
        self.assertEqual(text, "The microphone did not start. Check your microphone.")


def press(overlay, x_root: int, y_root: int) -> None:
    event = mock.Mock(x_root=x_root, y_root=y_root, x=0, y=0)
    overlay._start_drag(event)
    overlay._end_drag(event)
    pump(overlay.root, 0.02)


@unittest.skipUnless(sys.platform == "win32", "UpdateLayeredWindow is Windows")
class SegmentsTests(unittest.TestCase):
    def setUp(self) -> None:
        QUIET.start()
        self.addCleanup(QUIET.stop)
        self.overlay = build_overlay({})
        self.addCleanup(destroy_overlay, self.overlay)
        settle_idle(self.overlay)

    def show_word(self, word: str = "Kubernetes", **kwargs):
        overlay = self.overlay
        rejected = Counter()
        overlay.show_learned_word(word, rejected, **kwargs)
        self.assertTrue(until(overlay, lambda: overlay._flag_view is not None and overlay._flag_view.phase == "hold"))
        return overlay._flag_view, rejected

    def test_a_learned_word_is_a_segment_of_the_pill_with_undo(self) -> None:
        overlay = self.overlay
        pushed = Pushed(overlay)
        view, rejected = self.show_word()
        overlay._draw_visual()
        self.assertEqual(view.layout.mode, "segment")
        self.assertEqual(view.message.title, 'Added "Kubernetes"')
        self.assertEqual([action.label for action in view.message.actions], ["Undo"])
        alpha = pushed.last()[..., 3]
        self.assertEqual(components(alpha > 0), 1, "the segment is a separate piece")
        button = view.layout.buttons[0]
        bx, by, bw, bh = button.rect
        press(overlay, view.envelope.x + view.words_origin[0] + bx + bw // 2,
              view.envelope.y + view.words_origin[1] + by + bh // 2)
        self.assertEqual(rejected.calls, 0, "Undo ran before the segment folded away")
        self.assertTrue(until(overlay, lambda: rejected.calls == 1, 2.0), "Undo never ran")

    def test_the_pill_end_of_a_segment_still_dictates(self) -> None:
        overlay = self.overlay
        dictated = Counter()
        overlay.callbacks["pill_hands_free"] = dictated
        view, _rejected = self.show_word()
        x, y, w, h = view.capsule_now
        head_left = x if view.pin == "left" else x + w - view.target.head
        press(overlay, view.envelope.x + head_left + view.target.head // 2, view.envelope.y + y + h // 2)
        self.assertEqual(dictated.calls, 1, "the Pill end of a segment did not dictate")

    def test_alt_d_undoes_while_shown_and_is_gone_after(self) -> None:
        overlay = self.overlay
        view, rejected = self.show_word()
        self.assertTrue(overlay.root.bind("<Alt-d>"), "Alt+D is not bound while the segment shows")
        overlay._flag_choose(0)
        self.assertTrue(until(overlay, lambda: rejected.calls == 1, 2.0))
        self.assertFalse(overlay.root.bind("<Alt-d>").strip(), "Alt+D outlived the segment")

    def test_the_second_word_waits_and_the_first_keeps_its_undo(self) -> None:
        """X-631, on the Pill."""
        overlay = self.overlay
        first, rejected = self.show_word("Alpha")
        overlay.show_learned_word("Beta", Counter())
        pump(overlay.root, 0.3)
        self.assertIs(overlay._flag_view, first)
        overlay._flag_choose(0)
        self.assertTrue(until(overlay, lambda: rejected.calls == 1, 2.0))
        self.assertTrue(until(overlay, lambda: overlay._flag_view is not None
                              and overlay._flag_view.message.title == 'Added "Beta"', 3.0))

    def test_the_update_offer_is_a_segment_with_install(self) -> None:
        overlay = self.overlay
        installed = Counter()
        overlay.show_update_popover("9.9.9", installed)
        self.assertTrue(until(overlay, lambda: overlay._flag_view is not None and overlay._flag_view.phase == "hold"))
        view = overlay._flag_view
        self.assertEqual((view.message.title, view.message.actions[0].label), ("Talk DAT! 9.9.9 is ready", "Install"))
        self.assertEqual(view.message.reading_ms(), 20000)
        overlay.show_update_popover("9.9.9", installed)
        self.assertEqual(overlay._flag_queue.waiting, [], "a second offer stacked")
        overlay._flag_choose(0)
        self.assertTrue(until(overlay, lambda: installed.calls == 1, 2.0))

    def test_the_pip_is_a_light_in_the_rim_and_takes_its_press(self) -> None:
        overlay = self.overlay
        pushed = Pushed(overlay)
        overlay.set_update_flag("red")
        pump(overlay.root, 1.2)  # past its one breath
        overlay._draw_visual()
        frame = pushed.last()
        from knight_flow import pill_message

        cx, cy = pill_message.pip_centre(frame.shape[1], frame.shape[0], overlay._flag_scale())
        blue, green, red, alpha = (int(v) for v in frame[int(cy), int(cx)])
        self.assertEqual(alpha, 255)
        self.assertGreater(red, 200)
        self.assertLess(green, 120)
        root_x, root_y = overlay.canvas.winfo_rootx(), overlay.canvas.winfo_rooty()
        self.assertTrue(overlay._update_flag_hit(root_x + int(cx), root_y + int(cy)))
        self.assertLessEqual(3.0 * overlay._flag_scale(), frame.shape[0] / 2.0)
        overlay.set_update_flag("")


@unittest.skipUnless(sys.platform == "win32", "UpdateLayeredWindow is Windows")
class ReducedMotionAndFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        QUIET.start()
        self.addCleanup(QUIET.stop)

    def test_reduced_motion_only_fades(self) -> None:
        overlay = build_overlay({}, reduce_motion=True)
        self.addCleanup(destroy_overlay, overlay)
        settle_idle(overlay)
        pushed = Pushed(overlay)
        overlay.flag("Copied your last dictation", tone="done")
        self.assertTrue(until(overlay, lambda: overlay._flag_view is not None and overlay._flag_view.phase == "hold"))
        view = overlay._flag_view
        moved = [frame for where, frame in pushed.frames if where is not None]
        widths = set()
        peaks = []
        for frame in moved:
            drawn = frame[..., 3] > 0
            columns = np.nonzero(drawn.any(axis=0))[0]
            widths.add(int(columns[-1] - columns[0] + 1))
            x, y, w, h = view.capsule_now
            peaks.append(int(frame[y + h // 2, x + w - h, 3]))
        # Only two extents ever: the resting Pill (frame 0 of the cross-fade)
        # and the whole capsule. Nothing in between: nothing travelled.
        self.assertLessEqual(widths, {view.target.w, view.pill.w}, "under reduced motion the capsule travelled")
        self.assertIn(view.target.w, widths)
        self.assertLess(peaks[0], 255, "it did not fade in")
        self.assertEqual(peaks[-1], 255)

    def test_the_colour_key_path_shows_a_plain_capsule(self) -> None:
        overlay = build_overlay({})
        self.addCleanup(destroy_overlay, overlay)
        overlay.config["overlay"]["pill_per_pixel_alpha"] = False
        overlay._fall_back_to_colour_key("test")
        settle_idle(overlay)
        idle = (overlay.root.winfo_width(), overlay.root.winfo_height())
        overlay.flag("Copied your last dictation", tone="done")
        self.assertTrue(until(overlay, lambda: overlay._flag_view is not None and overlay._flag_view.phase == "hold"))
        view = overlay._flag_view
        self.assertTrue(view.keyed)
        pump(overlay.root, 0.1)
        self.assertEqual((overlay.root.winfo_width(), overlay.root.winfo_height()), (view.envelope.w, view.envelope.h))
        self.assertEqual(overlay.canvas.type(overlay.visual_canvas_item), "image")
        overlay._flag_contract()
        self.assertTrue(until(overlay, lambda: overlay._flag_view is None))
        pump(overlay.root, 0.2)
        self.assertEqual((overlay.root.winfo_width(), overlay.root.winfo_height()), idle)


if __name__ == "__main__":
    unittest.main()
