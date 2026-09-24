"""X-540: the History menu reopens on one click after every way it can close.

X-537 gave the whole app one popup contract (ui/flyout.py) and made History's
"Export and clear..." its first consumer. The contract is a state machine with
no display; the adapter in overlay.py (`_attach_flyout`) turns Tk events into
questions for it and carries out the answers. The adapter wired the TRIGGER:
hover, click, and the timers. It did not wire the POPUP. History went on
closing its menu the way it always had, calling `_request_popup_close` itself
for a row choice, for Escape and for lost focus, and clearing its window
reference when the popup died. None of that reached the state machine, so it
went on believing the menu was open, and sometimes pinned.

What that costs a person: after Escape, the next click on the button says
"pin what is open" and opens nothing; after a click-open and Escape, the next
click says "close" and closes nothing; only the click after THAT opens. A
menu that needs two or three presses reads as broken, and nobody files a bug
that says "the state object's pinned flag is stale".

The brief called the extra-click reopen a hypothesis. This file is the
reproduction: it drives the real adapter and the real `_request_popup_close`
with fake widgets and a hand-driven clock, closes the menu every way the view
can, and asks for it back with one click. Written against the disconnected
adapter first, where every reopen row fails; the fix that makes them pass gives
the adapter the popup's lifetime (its Enter, Leave and Destroy), a named close
for the view to call, a pointer re-check when the grace period expires, and
retirement when the trigger dies.

WHAT THE FAKES ARE. A Tk-shaped surface and nothing more: `bind`/`fire`,
`after`/`after_cancel` on a clock the test advances, `winfo_containing` that
answers with wherever the test put the pointer, `attributes` for alpha and
disabled, `destroy` that delivers `<Destroy>`. The opener and `popup_of` are
History's, in miniature: a singleton the opener refuses to duplicate, cleared
on Destroy, and an opener that can be made to fail the way a Tk error in
`open_more_menu` fails (no popup, nothing to show for it).

WHAT THIS CANNOT PROVE: pixel positions, focus traversal between rows, the
work-area clamp, or that Tk delivers Enter/Leave to a toplevel for its
children (it does, through bindtags, and tests/gui_popup_lifecycle.py runs
the real menu on the offscreen desktop).
"""

from __future__ import annotations

import ast
import unittest
from collections import defaultdict
from pathlib import Path
from typing import Callable

from knight_flow.overlay import Overlay
from knight_flow.ui import flyout as contract

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"

FADE_MS = 72  # _request_popup_close's default duration


class Clock:
    """Tk's after/after_cancel, driven by hand."""

    def __init__(self) -> None:
        self.now = 0
        self.seq = 0
        self.pending: dict[str, tuple[int, Callable[[], None]]] = {}

    def after(self, ms: int, callback: Callable[[], None]) -> str:
        self.seq += 1
        receipt = f"after#{self.seq}"
        self.pending[receipt] = (self.now + int(ms), callback)
        return receipt

    def after_idle(self, callback: Callable[[], None]) -> str:
        return self.after(0, callback)

    def after_cancel(self, receipt: str) -> None:
        self.pending.pop(receipt, None)

    def advance(self, ms: int) -> None:
        target = self.now + int(ms)
        while True:
            due = sorted((when, receipt) for receipt, (when, _) in self.pending.items() if when <= target)
            if not due:
                break
            when, receipt = due[0]
            self.now = max(self.now, when)
            _, callback = self.pending.pop(receipt)
            callback()
        self.now = target


class Event:
    def __init__(self, widget: "Widget") -> None:
        self.widget = widget


class Widget:
    def __init__(self, world: "World", name: str, toplevel: "Widget | None" = None) -> None:
        self.world = world
        self.name = name
        self.handlers: dict[str, list[Callable]] = defaultdict(list)
        self.alive = True
        self._toplevel = toplevel or self
        self.children: list[Widget] = []

    # -- bindings ----------------------------------------------------------
    def bind(self, sequence: str, handler: Callable, add: str | None = None) -> str:
        self.handlers[sequence].append(handler)
        return f"{self.name}:{sequence}:{len(self.handlers[sequence])}"

    def fire(self, sequence: str, event: Event | None = None) -> None:
        for handler in list(self.handlers.get(sequence, [])):
            handler(event if event is not None else Event(self))

    # -- timers ------------------------------------------------------------
    def after(self, ms: int, callback: Callable[[], None]) -> str:
        return self.world.clock.after(ms, callback)

    def after_idle(self, callback: Callable[[], None]) -> str:
        return self.world.clock.after_idle(callback)

    def after_cancel(self, receipt: str) -> None:
        self.world.clock.after_cancel(receipt)

    # -- geometry and pointer ---------------------------------------------
    def winfo_exists(self) -> bool:
        return self.alive

    def winfo_toplevel(self) -> "Widget":
        return self._toplevel

    def winfo_pointerx(self) -> int:
        return 0

    def winfo_pointery(self) -> int:
        return 0

    def winfo_containing(self, x: int, y: int) -> "Widget | None":
        return self.world.under

    # -- lifetime ----------------------------------------------------------
    def destroy(self) -> None:
        if not self.alive:
            return
        self.alive = False
        for child in list(self.children):
            child.destroy()
        self.fire("<Destroy>", Event(self))


class Trigger(Widget):
    """A ttk.Button: it has a command, and invoke() runs it."""

    def __init__(self, world: "World") -> None:
        super().__init__(world, "trigger")
        self.command: Callable[[], object] | None = None

    def configure(self, **options: object) -> None:
        if "command" in options:
            self.command = options["command"]  # type: ignore[assignment]

    def invoke(self) -> object:
        return self.command() if self.command else None


class Popup(Widget):
    """A tk.Toplevel with rows, alpha, and a disabled flag."""

    def __init__(self, world: "World") -> None:
        super().__init__(world, "popup")
        self.alpha = 0.98
        self.attrs: dict[str, object] = {}
        self.rows = [Widget(world, f"row{i}", toplevel=self) for i in range(3)]
        self.children.extend(self.rows)

    def attributes(self, *args: object) -> object:
        if len(args) == 1:
            return self.alpha if args[0] == "-alpha" else self.attrs.get(str(args[0]))
        key, value = args[0], args[1]
        if key == "-alpha":
            self.alpha = float(value)  # type: ignore[arg-type]
        else:
            self.attrs[str(key)] = value
        return None

    def focus_get(self) -> Widget | None:
        return self.world.focus


class World:
    """History's side of the wiring, in miniature."""

    def __init__(self) -> None:
        self.clock = Clock()
        self.trigger = Trigger(self)
        self.under: Widget | None = None
        self.focus: Widget | None = None
        self.popup: Popup | None = None
        self.opens = 0
        self.fail_next_open = False
        self.actions: list[str] = []

    def opener(self) -> None:
        """open_more_menu_safely: one singleton, or a swallowed failure."""
        existing = self.popup
        if existing is not None and existing.winfo_exists():
            return  # the singleton stands, closing or not
        if self.fail_next_open:
            self.fail_next_open = False
            # The real one destroys the half-built candidate and clears the
            # reference, so there is nothing for popup_of to return.
            self.popup = None
            return
        popup = Popup(self)
        self.popup = popup

        def forget(event: Event) -> None:
            if event.widget is popup and self.popup is popup:
                self.popup = None

        popup.bind("<Destroy>", forget, add="+")
        self.opens += 1

    def popup_of(self) -> Popup | None:
        return self.popup


class Harness:
    """The real adapter and the real close path on a fake Overlay."""

    _attach_flyout = Overlay._attach_flyout
    _request_popup_close = Overlay._request_popup_close

    def __init__(self, world: World) -> None:
        self.world = world
        self.fades = 0

    def _animate_window_alpha(
        self,
        window: Popup,
        *,
        start: float,
        target: float,
        duration_ms: int,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """A fade takes time, and the popup is alive until it ends."""
        self.fades += 1
        window.attributes("-alpha", target)
        if on_complete is not None:
            self.world.clock.after(duration_ms, on_complete)


class MenuCase(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World()
        self.overlay = Harness(self.world)
        self.wiring = self.overlay._attach_flyout(  # type: ignore[arg-type]
            self.world.trigger,
            opener=self.world.opener,
            popup_of=self.world.popup_of,
        )
        self.state = getattr(self.wiring, "state", self.wiring)

    # -- the person's hand -------------------------------------------------
    def pointer_to_trigger(self) -> None:
        self.world.under = self.world.trigger
        self.world.trigger.fire("<Enter>")

    def pointer_into_the_gap(self) -> None:
        """Off the trigger, not yet on the popup: what every diagonal does."""
        self.world.under = None
        self.world.trigger.fire("<Leave>")

    def pointer_into_popup(self) -> None:
        popup = self.world.popup
        assert popup is not None
        self.world.under = popup.rows[0]
        popup.fire("<Enter>")

    def pointer_between_rows(self) -> None:
        popup = self.world.popup
        assert popup is not None
        popup.fire("<Leave>", Event(popup.rows[0]))
        self.world.under = popup.rows[1]
        popup.fire("<Enter>", Event(popup.rows[1]))

    def pointer_away_from_everything(self) -> None:
        self.world.under = None
        popup = self.world.popup
        if popup is not None:
            popup.fire("<Leave>")

    def hover_open(self) -> Popup:
        self.pointer_to_trigger()
        self.world.clock.advance(contract.OPEN_DELAY_MS)
        popup = self.world.popup
        self.assertIsNotNone(popup, "hovering for the delay opened nothing")
        return popup  # type: ignore[return-value]

    def click_open(self) -> Popup:
        self.world.trigger.invoke()
        popup = self.world.popup
        self.assertIsNotNone(popup, "a click opened nothing")
        return popup  # type: ignore[return-value]

    def let_the_fade_finish(self) -> None:
        self.world.clock.advance(FADE_MS + 1)

    # -- History's own close paths, as the view performs them ----------------
    def view_closes_directly(self, popup: Popup, on_complete: Callable[[], None] | None = None) -> None:
        """What History did before the adapter owned the popup: close it
        itself, telling the adapter nothing."""
        self.overlay._request_popup_close(popup, on_complete=on_complete)  # type: ignore[arg-type]
        self.let_the_fade_finish()

    # -- what must be true after any close -----------------------------------
    def rest_problems(self) -> list[str]:
        """Everything that should not survive a close, named."""
        problems: list[str] = []
        if self.world.popup is not None:
            problems.append("the popup is still owned")
        if self.world.clock.pending:
            problems.append(f"a timer survived the close ({sorted(self.world.clock.pending)})")
        flags = (self.state.open, self.state.pinned, self.state.open_pending, self.state.close_pending)
        if flags != (False, False, False, False):
            problems.append(f"stale flags (open, pinned, open_pending, close_pending)={flags}")
        return problems

    def assert_at_rest(self, *, why: str) -> None:
        problems = self.rest_problems()
        self.assertEqual(problems, [], f"{why}: " + "; ".join(problems))

    def assert_one_click_reopens(self, *, after: str) -> Popup:
        """The symptom first, the cause beside it."""
        problems = self.rest_problems()
        before = self.world.opens
        self.world.trigger.invoke()
        cause = f" (before the click: {'; '.join(problems)})" if problems else ""
        self.assertEqual(
            self.world.opens, before + 1,
            f"after {after}, one click on the trigger did not reopen the menu{cause}",
        )
        self.assertEqual(problems, [], f"after {after}, the menu reopened but not from rest: {'; '.join(problems)}")
        self.assertIsNotNone(self.world.popup)
        self.assertTrue(self.state.open and self.state.pinned, "a click-open is pinned")
        return self.world.popup  # type: ignore[return-value]


class HoverAndClickTests(MenuCase):
    def test_leaving_before_the_delay_opens_nothing_and_cancels_the_intent(self) -> None:
        self.pointer_to_trigger()
        self.world.clock.advance(contract.OPEN_DELAY_MS // 2)
        self.pointer_into_the_gap()
        self.world.clock.advance(contract.OPEN_DELAY_MS)
        self.assertIsNone(self.world.popup, "a pass over the trigger flashed a menu")
        self.assertEqual(self.world.clock.pending, {}, "the open timer was left armed")

    def test_staying_through_the_delay_opens_it_and_both_sides_agree(self) -> None:
        self.hover_open()
        self.assertTrue(self.state.open)
        self.assertFalse(self.state.pinned)

    def test_a_click_opens_now_and_pins(self) -> None:
        self.click_open()
        self.assertTrue(self.state.open and self.state.pinned)
        self.assertEqual(self.world.opens, 1)

    def test_a_click_on_a_hovered_menu_pins_it_rather_than_fighting(self) -> None:
        self.hover_open()
        self.world.trigger.invoke()
        self.assertEqual(self.world.opens, 1, "the click reopened instead of pinning")
        self.assertTrue(self.state.pinned)
        self.pointer_into_the_gap()
        self.pointer_away_from_everything()
        self.world.clock.advance(contract.CLOSE_GRACE_MS * 2)
        self.assertIsNotNone(self.world.popup, "a pinned menu closed on hover-out")


class ThePointerMayTravelTests(MenuCase):
    def test_the_diagonal_through_the_gap_keeps_the_menu(self) -> None:
        """Leave the trigger, cross the gap, land on a row, read for a while.
        The grace timer fires with the pointer on the popup: it must not close."""
        self.hover_open()
        self.pointer_into_the_gap()
        self.world.clock.advance(contract.CLOSE_GRACE_MS // 3)
        self.pointer_into_popup()
        self.world.clock.advance(contract.CLOSE_GRACE_MS * 2)
        self.assertIsNotNone(self.world.popup, "the menu closed under a pointer that was on it")
        self.assertTrue(self.state.open)

    def test_moving_between_rows_keeps_the_menu(self) -> None:
        self.hover_open()
        self.pointer_into_the_gap()
        self.pointer_into_popup()
        for _ in range(4):
            self.pointer_between_rows()
            self.world.clock.advance(contract.CLOSE_GRACE_MS // 2)
        self.world.clock.advance(contract.CLOSE_GRACE_MS * 2)
        self.assertIsNotNone(self.world.popup, "row-to-row crossing closed the menu")

    def test_a_late_arrival_on_the_popup_is_seen_at_grace_expiry(self) -> None:
        """No Enter ever reached the popup (it appeared under the pointer),
        so the adapter must ask the pointer itself when the grace runs out."""
        self.hover_open()
        self.pointer_into_the_gap()
        self.world.under = self.world.popup.rows[0]  # type: ignore[union-attr]
        self.world.clock.advance(contract.CLOSE_GRACE_MS * 2)
        self.assertIsNotNone(self.world.popup, "the grace timer trusted the event stream over the pointer")

    def test_leaving_both_surfaces_closes_after_the_grace_with_nothing_left_behind(self) -> None:
        self.hover_open()
        self.pointer_into_the_gap()
        self.pointer_into_popup()
        self.pointer_away_from_everything()
        self.world.clock.advance(contract.CLOSE_GRACE_MS - 1)
        self.assertIsNotNone(self.world.popup, "closed before the grace elapsed")
        self.world.clock.advance(1)
        self.let_the_fade_finish()
        self.assert_one_click_reopens(after="a hover-out close")


class EveryCloseReopensOnOneClickTests(MenuCase):
    """The reproduction. Each row closes the menu the way the view does and
    asks for it back with one click."""

    def test_after_escape_on_a_hovered_menu(self) -> None:
        popup = self.hover_open()
        self.view_closes_directly(popup)
        self.assert_one_click_reopens(after="Escape on a hovered menu")

    def test_after_escape_on_a_clicked_menu(self) -> None:
        popup = self.click_open()
        self.view_closes_directly(popup)
        self.assert_one_click_reopens(after="Escape on a clicked (pinned) menu")

    def test_after_focus_leaves_the_popup(self) -> None:
        popup = self.click_open()
        self.world.focus = None
        self.view_closes_directly(popup)
        self.assert_one_click_reopens(after="focus loss")

    def test_after_a_row_is_chosen_the_action_runs_once_and_the_menu_reopens(self) -> None:
        popup = self.click_open()
        self.view_closes_directly(popup, on_complete=lambda: self.world.actions.append("Export Markdown"))
        self.assertEqual(self.world.actions, ["Export Markdown"])
        self.assert_one_click_reopens(after="a row choice")

    def test_after_the_popup_is_destroyed_from_outside(self) -> None:
        """A host teardown, or the failure path's own destroy: no fade, no
        request, just Destroy. The trigger survives and must work."""
        popup = self.hover_open()
        popup.destroy()
        self.assert_one_click_reopens(after="an outside destroy")

    def test_after_a_creation_failure_there_is_no_invisible_open_menu(self) -> None:
        self.world.fail_next_open = True
        self.world.trigger.invoke()
        self.assertIsNone(self.world.popup)
        self.assert_one_click_reopens(after="a creation failure")

    def test_after_a_hover_open_that_failed_to_build(self) -> None:
        self.world.fail_next_open = True
        self.pointer_to_trigger()
        self.world.clock.advance(contract.OPEN_DELAY_MS)
        self.assertIsNone(self.world.popup)
        self.assert_one_click_reopens(after="a failed hover-open")

    def test_four_closes_in_a_row_each_reopen_on_one_click(self) -> None:
        popup = self.click_open()
        for round_number in range(4):
            self.view_closes_directly(popup)
            popup = self.assert_one_click_reopens(after=f"close number {round_number + 1}")


class TheAdapterOwnsTheCloseTests(MenuCase):
    """The named close the view calls instead of closing behind the adapter's
    back. State is reconciled before the action runs, closing twice runs the
    action once, and a close with no popup is a harmless no-op."""

    def close(self) -> Callable[..., None]:
        close = getattr(self.wiring, "close", None)
        self.assertIsNotNone(close, "the adapter hands back no close path; History has to close behind its back")
        return close  # type: ignore[return-value]

    def test_escape_through_the_adapter(self) -> None:
        self.click_open()
        self.close()("escape")
        self.let_the_fade_finish()
        self.assert_one_click_reopens(after="close('escape')")

    def test_focus_loss_through_the_adapter(self) -> None:
        self.hover_open()
        self.close()("focus")
        self.let_the_fade_finish()
        self.assert_one_click_reopens(after="close('focus')")

    def test_a_choice_reconciles_state_before_the_action_runs(self) -> None:
        self.click_open()
        seen: list[tuple[bool, bool, bool]] = []

        def action() -> None:
            seen.append((self.state.open, self.state.pinned, self.world.popup is None))

        self.close()("chose", on_complete=action)
        self.let_the_fade_finish()
        self.assertEqual(seen, [(False, False, True)], "the action ran before the state and the view were reconciled")
        self.assert_one_click_reopens(after="close('chose')")

    def test_closing_twice_runs_the_action_once(self) -> None:
        self.click_open()
        self.close()("chose", on_complete=lambda: self.world.actions.append("Stats"))
        self.close()("escape")
        self.close()("chose", on_complete=lambda: self.world.actions.append("Clear text history"))
        self.let_the_fade_finish()
        self.assertEqual(self.world.actions, ["Stats"], "a second close ran a second action, or the first ran twice")
        self.assert_one_click_reopens(after="two closes")

    def test_closing_with_no_popup_is_a_no_op(self) -> None:
        self.close()("escape")
        self.assert_at_rest(why="after closing nothing")
        self.assert_one_click_reopens(after="closing nothing")

    def test_a_close_cancels_a_pending_hover_close(self) -> None:
        self.hover_open()
        self.pointer_into_the_gap()
        self.assertTrue(self.state.close_pending)
        self.close()("escape")
        self.let_the_fade_finish()
        self.assert_one_click_reopens(after="Escape during the grace period")


class RetirementTests(MenuCase):
    def test_destroying_the_trigger_retires_every_timer_and_ignores_the_past(self) -> None:
        self.pointer_to_trigger()
        self.assertTrue(self.world.clock.pending, "no open timer was armed")
        self.world.trigger.destroy()
        self.assertEqual(self.world.clock.pending, {}, "a timer outlived its trigger")
        # Events after retirement do nothing and raise nothing.
        self.world.trigger.fire("<Enter>")
        self.world.trigger.fire("<Leave>")
        self.world.clock.advance(contract.OPEN_DELAY_MS * 2)
        self.assertIsNone(self.world.popup, "a retired trigger opened a menu")
        self.assertEqual(self.world.opens, 0)

    def test_destroying_the_trigger_while_the_menu_is_open_leaves_no_timer(self) -> None:
        self.hover_open()
        self.pointer_into_the_gap()
        self.assertTrue(self.world.clock.pending, "no grace timer was armed")
        self.world.trigger.destroy()
        self.assertEqual(self.world.clock.pending, {})


class HistoryIsWiredThroughTheAdapterTests(unittest.TestCase):
    """Source pins on overlay.py: the fakes cannot run open_history, so the
    view's three close paths are read rather than driven."""

    @classmethod
    def setUpClass(cls) -> None:
        source = OVERLAY.read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = {
            node.name: ast.get_source_segment(source, node) or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name in {"open_history", "_attach_flyout"}
        }
        cls.history = methods["open_history"]
        cls.adapter = methods["_attach_flyout"]

    def test_history_keeps_what_the_adapter_returns(self) -> None:
        self.assertIn("more_flyout = self._attach_flyout(", self.history)

    def test_the_three_view_closes_go_through_the_adapter(self) -> None:
        menu = self.history[self.history.index("def open_more_menu()"):self.history.index("def open_more_menu_safely()")]
        self.assertIn('more_flyout.close("chose", on_complete=action)', menu)
        self.assertIn('more_flyout.close("escape")', menu)
        self.assertIn('more_flyout.close("focus")', menu)
        self.assertNotIn("self._request_popup_close(pop", menu, "History is closing behind the adapter's back again")

    def test_the_eight_commands_and_their_callbacks_survive(self) -> None:
        for label in (
            "Export report (PDF)", "Report design: next", "Export Markdown", "Subtitle draft (estimated)",
            "Open history file", "Stats", "Clear text history", "Clear recordings",
        ):
            with self.subTest(label=label):
                self.assertIn(f'("{label}", ', self.history)

    def test_the_adapter_owns_the_popups_lifetime(self) -> None:
        for sequence in ("<Enter>", "<Leave>", "<Destroy>"):
            with self.subTest(sequence=sequence):
                self.assertIn(f'popup.bind("{sequence}"', self.adapter)
        self.assertIn("state.popup_gone()", self.adapter)
        self.assertIn("state.dismissed(reason)", self.adapter)


if __name__ == "__main__":
    unittest.main()
