"""X-682: every sheet, panel, dialog, popover, notice and the Pill menu arrives and leaves.

The polish audit (2026-09-24, P0-6) walked every close path: in the web shell the
notice, the help popover, eighteen dialogs, the save strip, sixteen Advanced options
disclosures, the Pill menu window, its submenus and its pages, the Home update offer
and the Account rows all vanished in one frame, and two dialogs were removed from the
page in the same tick they closed, so no exit could ever play.

One recipe now: things arrive on the sheet spring with a short fade (@starting-style)
and leave faster than they came, on the exit curve, while deaf to the pointer, so a
leaving surface never eats the click meant for what is under it. Under reduced motion
(Windows or the app's own switch) they fade only. These tests resolve the stylesheets
for each close path (tests/shell_cascade.py) and read the scripts that close them.
"""
from __future__ import annotations

import re
import unittest

from tests import shell_css
from tests.shell_cascade import Element, Environment, resolve, split_top
from tests.shell_css import ASSETS, ROOT

BODY = Element("body")
WORKSPACE = Element("div", ("workspace",), parent=BODY)
#: (name, the element while shown, the element while leaving)
CLOSE_PATHS = (
    ("dialog", Element("dialog", attrs={"open": ""}, parent=BODY), Element("dialog", parent=BODY)),
    ("help popover", Element("div", ("popover",), id="help-popover", parent=BODY),
     Element("div", ("popover",), {"hidden": ""}, id="help-popover", parent=BODY)),
    # X-744: the floating notice is gone (#notice is only the screen readers' live
    # region now); the header's own strip is the surface that arrives and leaves.
    ("header strip", Element("div", ("say-header",), id="say-header", parent=WORKSPACE),
     Element("div", ("say-header",), {"hidden": ""}, id="say-header", parent=WORKSPACE)),
    ("save strip", Element("footer", id="save-strip", parent=WORKSPACE),
     Element("footer", attrs={"hidden": ""}, id="save-strip", parent=WORKSPACE)),
    ("update offer", Element("section", ("home-offer",), parent=BODY),
     Element("section", ("home-offer",), {"hidden": ""}, parent=BODY)),
    ("sign-in panel", Element("div", ("account-signin",), parent=BODY),
     Element("div", ("account-signin",), {"hidden": ""}, parent=BODY)),
    ("code row", Element("div", ("account-code-row",), parent=BODY),
     Element("div", ("account-code-row",), {"hidden": ""}, parent=BODY)),
)


def ms(value: str) -> float:
    tokens = dict(shell_css.declarations(shell_css.tokens_block()))
    value = value.strip()
    while value.startswith("var("):
        value = tokens[value[4:-1].strip()]
    return float(value[:-2]) if value.endswith("ms") else float(value[:-1]) * 1000


def durations(transition: str) -> dict[str, float]:
    """{property: duration in ms} from a transition shorthand list."""
    result = {}
    for layer in split_top(transition):
        parts = layer.split()
        times = [part for part in parts if re.fullmatch(r"(var\(--t-[\w-]+\)|\d+m?s)", part)]
        if parts and times:
            result[parts[0]] = ms(times[0])
    return result


class EveryClosePathHasAnExitTests(unittest.TestCase):
    def test_each_surface_leaves_deaf_to_the_pointer_and_faster_than_it_came(self):
        for name, shown, leaving in CLOSE_PATHS:
            with self.subTest(surface=name):
                entry = durations(resolve(shown, "transition") or "")
                self.assertIn("opacity", entry, "no fade")
                self.assertIn("display", entry, "display is not held for the exit")
                self.assertIn("allow-discrete", resolve(shown, "transition"))
                self.assertEqual(resolve(leaving, "pointer-events"), "none", "a leaving surface still takes clicks")
                exit_time = ms(resolve(leaving, "transition-duration"))
                self.assertLess(exit_time, min(entry.values()))
                self.assertEqual(resolve(leaving, "transition-timing-function"), "var(--ease-exit)")
                if name != "save strip":
                    self.assertEqual(resolve(leaving, "opacity"), "0")

    def test_each_surface_arrives_from_a_starting_style(self):
        starting = Environment(starting_style=True)
        for name, shown, _leaving in CLOSE_PATHS:
            with self.subTest(surface=name):
                moved = {prop: resolve(shown, prop, starting) for prop in ("opacity", "translate")}
                self.assertTrue(moved["opacity"] == "0" or moved["translate"] not in (None, "none"), moved)

    def test_the_dialog_backdrop_fades_with_it_and_lets_clicks_through_while_leaving(self):
        shown, leaving = CLOSE_PATHS[0][1], CLOSE_PATHS[0][2]
        self.assertIn("display", durations(resolve(shown, "transition", pseudo="backdrop") or ""))
        self.assertEqual(resolve(leaving, "pointer-events", pseudo="backdrop"), "none")
        self.assertEqual(resolve(shown, "background-color", pseudo="backdrop"), "var(--scrim)")

    def test_disclosures_open_and_close_on_the_same_curves(self):
        opened = resolve(Element("details", attrs={"open": ""}), "transition", pseudo="details-content") or ""
        closed = resolve(Element("details"), "transition-duration", pseudo="details-content") or "0s"
        self.assertIn("block-size", durations(opened))
        self.assertLess(ms(closed), durations(opened)["block-size"])


class ReducedMotionFadesOnlyTests(unittest.TestCase):
    def test_under_reduced_motion_nothing_moves_and_everything_still_fades(self):
        for env, parent in ((Environment(reduced_motion=True), BODY), (Environment(), Element("body", ("reduce-motion",)))):
            for name, shown, leaving in CLOSE_PATHS:
                shown = Element(shown.tag, shown.classes, shown.attrs, id=shown.id, parent=parent)
                leaving = Element(leaving.tag, leaving.classes, leaving.attrs, id=leaving.id, parent=parent)
                with self.subTest(surface=name, switch="app" if parent.classes else "windows"):
                    transition = resolve(shown, "transition-property", env) or resolve(shown, "transition", env)
                    self.assertIn("opacity", transition)
                    self.assertNotIn("translate", transition)
                    self.assertIn(resolve(leaving, "translate", env), ("none", None))
                    self.assertLessEqual(ms(resolve(shown, "transition-duration", env)), 120)


class NothingIsRemovedMidExitTests(unittest.TestCase):
    def test_dialogs_wait_for_their_exit_before_leaving_the_page(self):
        reset = (ASSETS / "reset.js").read_text(encoding="utf-8")
        shell = (ASSETS / "shell.js").read_text(encoding="utf-8")
        self.assertNotRegex(reset, r"close\(\);\s*dialog\.remove\(\)")
        self.assertRegex(reset, r"TalkDatAfterExit")
        self.assertNotRegex(shell, r'addEventListener\("close",\s*\(\)\s*=>\s*\{[^}]*dialog\.remove\(\);\}')
        self.assertIn("window.TalkDatAfterExit = afterExit", shell)


class TheMenuLeavesBeforeItHidesTests(unittest.TestCase):
    def test_the_menu_fades_before_its_window_hides(self):
        leaving = Element("div", ("workspace",), parent=Element("body", ("menu-view", "menu-leaving")))
        self.assertEqual(resolve(leaving, "opacity"), "0")
        self.assertEqual(resolve(leaving, "pointer-events"), "none")
        host = (ROOT / "knight_flow" / "web_shell" / "shell_host.py").read_text(encoding="utf-8")
        self.assertRegex(host, r"MENU_EXIT_SECONDS\s*=\s*0\.14\b")
        tokens = dict(shell_css.declarations(shell_css.tokens_block()))
        self.assertEqual(tokens["--t-exit"], "140ms", "the host waits exactly one exit")

    def test_a_submenu_slides_in_from_the_side_it_came_from(self):
        menu = Element("body", ("menu-view",))
        forward = Element("div", ("menu-items",), {"data-enter": "forward"}, parent=menu)
        back = Element("div", ("menu-items",), {"data-enter": "back"}, parent=menu)
        old = Element("div", ("menu-items", "menu-items-leaving"), {"data-leave": "forward"}, parent=menu)
        self.assertTrue((resolve(forward, "animation-name") or "").startswith("menu-in-from-right"))
        self.assertTrue((resolve(back, "animation-name") or "").startswith("menu-in-from-left"))
        self.assertEqual(resolve(old, "pointer-events"), "none")
        self.assertIn("var(--t-exit)", resolve(old, "animation"))
        # The old list still carries its own entrance marker; its exit must win.
        stale = Element("div", ("menu-items", "menu-items-leaving"), {"data-enter": "forward"}, parent=menu)
        self.assertIn("var(--t-exit)", resolve(stale, "animation"))


class TheHostWaitsForTheExitTests(unittest.TestCase):
    def api(self):
        from unittest.mock import Mock

        from knight_flow.web_shell.shell_host import _RendererApi

        api = _RendererApi(Mock(), mode="menu")
        api._window = Mock()
        api._window.get_current_url.return_value = None
        api._guard_ready = True
        return api

    def test_dismiss_hides_after_one_exit_not_before(self):
        import time

        api = self.api()
        self.assertTrue(api.request("dismiss")["ok"])
        api._window.hide.assert_not_called()
        time.sleep(.3)
        api._window.hide.assert_called_once()

    def test_showing_again_cancels_a_pending_hide(self):
        import time

        api = self.api()
        api.request("dismiss")
        api._show()
        time.sleep(.3)
        api._window.hide.assert_not_called()


class EveryMotionReadsTheScaleTests(unittest.TestCase):
    def test_every_transition_and_animation_uses_a_token(self):
        stray = []
        for prop in ("transition", "transition-duration", "transition-timing-function", "animation",
                     "animation-duration", "animation-timing-function"):
            for sheet, _stack, selector, value in shell_css.values(prop):
                cleaned = re.sub(r"var\(--[\w-]+\)|steps\(\d+(,\s*[\w-]+)?\)", "", value.replace("!important", ""))
                if re.search(r"\b\d*\.?\d+m?s\b|\bease(-in|-out|-in-out)?\b|cubic-bezier|linear\(", cleaned):
                    if not re.fullmatch(r"\s*none\s*|.*\b0s\b.*", cleaned):
                        stray.append(f"{sheet} {selector}: {value}")
        self.assertEqual(stray, [])


if __name__ == "__main__":
    unittest.main()
