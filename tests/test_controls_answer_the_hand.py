"""X-681: every control in the web shell answers the hand.

Polish audit P0-5 and the interaction grid's safety net 7, 2026-09-24:

- hover lived in one rule, `button:hover`, that sat BEFORE `button.primary` and
  `button.quiet` at equal specificity, so a primary or quiet button never changed on
  hover, while a disabled button did;
- nothing had a pressed state;
- the switch track snapped to its new colour while only the knob slid, and the knob
  turned from light to black in the same frame.

These tests resolve the shell's own stylesheets for a described element (see
tests/shell_cascade.py) and ask what a browser would paint: the hovered primary
button, the pressed button, the checked switch's knob.
"""
from __future__ import annotations

import re
import unittest

from knight_flow.themes import SETTINGS_THEME_PALETTES
from tests import shell_css
from tests.shell_cascade import Element, Environment, button, resolve, split_top
from tests.shell_css import ASSETS

NAV = Element("nav", id="navigation")
MENU = Element("div", ("menu-items",), parent=Element("main", parent=Element("body", ("menu-view",))))
FAMILIES = {
    "plain": lambda **kw: button(**kw),
    "primary": lambda **kw: button("primary", **kw),
    "quiet": lambda **kw: button("quiet", **kw),
    "sidebar row": lambda **kw: button(parent=NAV, **kw),
    "menu row": lambda **kw: button("menu-row", parent=MENU, attrs={"role": "menuitem", **kw.pop("attrs", {})}, **kw),
    "list entry": lambda **kw: button("document-entry", **kw),
    "theme card": lambda **kw: button("theme-choice", **kw),
    "switch": lambda **kw: button("switch", attrs={"role": "switch", **kw.pop("attrs", {})}, **kw),
}
DISABLED = {"disabled": ""}


def luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def mix(color: str, other: str, share: float) -> str:
    """color-mix(in srgb, color (1-share), other share), as the browser computes it."""
    return "#" + "".join(f"{round(int(color[i:i + 2], 16) * (1 - share) + int(other[i:i + 2], 16) * share):02x}"
                         for i in (1, 3, 5))


class HoverTests(unittest.TestCase):
    def test_primary_and_quiet_buttons_answer_hover(self):
        for name in ("plain", "primary", "quiet"):
            with self.subTest(button=name):
                rest = resolve(FAMILIES[name](), "background-color")
                hovered = resolve(FAMILIES[name](states={"hover"}), "background-color")
                self.assertNotEqual(hovered, rest, "hover paints the same fill as rest")

    def test_a_disabled_control_does_not_answer_hover(self):
        for name, make in FAMILIES.items():
            with self.subTest(control=name):
                rest = resolve(make(attrs=dict(DISABLED)), "background-color")
                hovered = resolve(make(attrs=dict(DISABLED), states={"hover"}), "background-color")
                self.assertEqual(hovered, rest)

    def test_every_hover_rule_skips_disabled(self):
        stray = [selector for _sheet, _stack, selectors, _body in shell_css.all_rules()
                 for selector in split_top(selectors) if ":hover" in selector and ":not(:disabled)" not in selector]
        self.assertEqual(stray, [])

    def test_the_primary_hover_keeps_its_ink_readable_in_every_theme(self):
        # The hover lifts the accent 12% AWAY from its ink. Toward white alone drops
        # 7 themes below 4.5:1 (Obsidian Gold Dark to 3.81), toward black alone 7 others.
        hovered = resolve(FAMILIES["primary"](states={"hover"}), "background-color")
        self.assertEqual(hovered.replace(" ", ""), "color-mix(insrgb,var(--accent)88%,var(--accent-lift))")
        script = (ASSETS / "shell.js").read_text(encoding="utf-8")
        self.assertRegex(script, r'setProperty\("--accent-lift",\s*palette\.on_accent === "#000000" \? "#ffffff" : "#000000"\)')
        from knight_flow.overlay import Overlay

        palette = object.__new__(Overlay)._settings_palette
        failing = []
        for family, modes in SETTINGS_THEME_PALETTES.items():
            for mode in modes:
                colors = palette(f"{family} {mode}")
                ink = colors["on_accent"]
                lifted = mix(colors["accent"], "#ffffff" if ink == "#000000" else "#000000", .12)
                if contrast(ink, lifted) < 4.5:
                    failing.append(f"{family} {mode}: {contrast(ink, lifted):.2f}")
        self.assertEqual(failing, [])


class PressTests(unittest.TestCase):
    def test_every_control_presses_one_pixel_in_sixty_milliseconds(self):
        for name, make in FAMILIES.items():
            with self.subTest(control=name):
                pressed = make(states={"active"})
                self.assertEqual(resolve(pressed, "transform"), "translateY(1px)")
                self.assertEqual(resolve(pressed, "transition-duration"), "var(--t-press)")

    def test_a_raised_button_drops_to_e0_into_the_press_well(self):
        for name in ("plain", "primary", "theme card"):
            with self.subTest(button=name):
                self.assertIn("var(--e1)", resolve(FAMILIES[name](), "box-shadow"))
                self.assertEqual(resolve(FAMILIES[name](states={"active"}), "box-shadow"), "var(--e0),var(--press)")

    def test_a_disabled_control_does_not_press(self):
        for name, make in FAMILIES.items():
            with self.subTest(control=name):
                self.assertNotEqual(resolve(make(attrs=dict(DISABLED), states={"active"}), "transform"), "translateY(1px)")

    def test_release_springs_back_on_the_key_spring(self):
        transition = resolve(button(), "transition")
        self.assertIn("transform var(--t-key) var(--spring-key)", transition)
        self.assertIn("background-color var(--t-micro) var(--ease-out)", transition)


class SwitchTests(unittest.TestCase):
    def test_the_knob_is_one_lit_object_in_both_states(self):
        off = resolve(FAMILIES["switch"](attrs={"aria-checked": "false"}), "background-color", pseudo="after")
        on = resolve(FAMILIES["switch"](attrs={"aria-checked": "true"}), "background-color", pseudo="after")
        self.assertEqual(off, on, "the knob changes colour when the switch flips")

    def test_the_track_eases_its_fill_while_the_knob_travels(self):
        track = resolve(FAMILIES["switch"](), "transition", pseudo="before") or ""
        knob = resolve(FAMILIES["switch"](), "transition", pseudo="after") or ""
        self.assertIn("background-color var(--t-control) var(--ease-out)", track)
        self.assertIn("transform var(--t-key) var(--spring-key)", knob)

    def test_high_contrast_keeps_the_system_colours(self):
        body = Element("body", ("high-contrast",))
        forced = Environment(forced_colors=True)
        for parent, env in ((body, None), (None, forced)):
            off = resolve(button("switch", parent=parent, attrs={"aria-checked": "false"}), "background-color", env, "after")
            on = resolve(button("switch", parent=parent, attrs={"aria-checked": "true"}), "background-color", env, "after")
            self.assertEqual((off, on), ("var(--text)", "var(--on-accent)"))


class FocusTests(unittest.TestCase):
    def test_one_focus_ring(self):
        rings = set()
        for _sheet, stack, selectors, body in shell_css.all_rules():
            if not re.search(r":focus(-visible|-within)?\b", selectors) or any("forced-colors" in p for p in stack):
                continue
            for name, value in shell_css.declarations(body):
                if name in {"outline", "outline-width", "outline-color", "outline-style"}:
                    rings.add(value)
        self.assertEqual(rings, {"var(--focus-width) solid var(--ring)"})
        block = dict(shell_css.declarations(shell_css.tokens_block()))
        self.assertEqual((block.get("--focus-width"), block.get("--focus-offset")), ("2px", "2px"))


if __name__ == "__main__":
    unittest.main()
