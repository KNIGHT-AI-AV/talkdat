"""X-680: the web shell draws every corner and every shadow from one scale.

The polish audit (2026-09-24, section 4) counted 21 distinct corner radii in the
shell's two stylesheets (2, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 20, 24, 30, 60 and
999 px, 50%, "5px 5px 0 0", 0, and var(--radius,12px) which nothing defines) and five
one-off drop shadows in black at 8 to 47%. Nothing tied them together, so every new
surface invented its own, and light themes wore dark-mode shadows.

The scale now lives in one tokens block in shell.css: six radii, e0 to e4 plus the
pressed inset and two edge arrises, one scrim, three easings, three springs and the
durations. These tests hold the stylesheets to it:

- every border-radius is a token (or 0);
- every drop shadow is a token (the only literal insets left are the accent bars,
  which are emissive marks, not shadows);
- every var(--x) the CSS reads is defined somewhere (CSS or the script that sets it),
  so a name cannot silently fall back the way --radius did;
- light themes scale the shadows down (the page says which mode it is in).
"""
from __future__ import annotations

import re
import unittest

from tests import shell_css
from tests.shell_css import ASSETS

TOKEN = re.compile(r"var\(--(?:r-(?:xs|sm|md|lg|xl|full))\)")
SHADOW_TOKEN = re.compile(r"var\(--(?:e[0-4]|press|edge-light|edge-shade)\)")


def script_set_properties() -> set[str]:
    """Custom properties the page's scripts set at run time."""
    names = set()
    for path in ASSETS.glob("*.js"):
        text = path.read_text(encoding="utf-8")
        names.update(re.findall(r"setProperty\(\s*[\"'](--[\w-]+)", text))
        names.update(re.findall(r"[`\"'{;](--[\w-]+)\s*:", text))
        for keys in re.findall(r"for \(const key of \[([^\]]+)\]\)[^\n]*setProperty\(\"--\"\s*\+\s*key", text):
            names.update("--" + key for key in re.findall(r"\"([\w-]+)\"", keys))
    return names


class TheScaleIsDefinedOnceTests(unittest.TestCase):
    def test_the_tokens_block_carries_the_audits_scale(self):
        block = shell_css.tokens_block()
        self.assertTrue(block, "no :root block defines --r-md")
        declared = dict(shell_css.declarations(block))
        for name, value in {"--r-xs": "4px", "--r-sm": "8px", "--r-md": "12px", "--r-lg": "16px",
                            "--r-xl": "24px", "--r-full": "999px", "--t-press": "60ms", "--t-micro": "90ms",
                            "--t-control": "140ms", "--t-exit": "140ms", "--t-key": "260ms",
                            "--t-sheet": "380ms", "--t-settle": "470ms",
                            "--ease-out": "cubic-bezier(.16,1,.3,1)", "--ease-exit": "cubic-bezier(.3,0,1,1)",
                            "--ease-move": "cubic-bezier(.2,0,0,1)"}.items():
            with self.subTest(token=name):
                self.assertEqual(declared.get(name), value)
        for name in ("--e0", "--e1", "--e2", "--e3", "--e4", "--press", "--edge-light", "--edge-shade", "--scrim"):
            self.assertIn(name, declared)
        for spring in ("--spring-key", "--spring-sheet", "--spring-settle"):
            stops = re.fullmatch(r"linear\(([^)]*)\)", declared.get(spring, ""))
            self.assertIsNotNone(stops, spring)
            points = [float(value) for value in stops.group(1).split(",")]
            self.assertEqual((points[0], points[-1], len(points)), (0.0, 1.0, 19), spring)
        # Shadows fall down: no elevation casts upward or leans left.
        for level in ("--e1", "--e2", "--e3", "--e4"):
            for x, y in re.findall(r"(-?\d+)(?:px)? (-?\d+)px \d+px rgb", declared[level]):
                self.assertGreaterEqual(int(y), 0, level)
                self.assertIn(int(x), (0, 1), level)

    def test_light_themes_scale_the_shadows_down(self):
        light = [body for _name, stack, selector, body in shell_css.all_rules()
                 if selector == ":root[data-mode=light]" and not stack]
        self.assertTrue(light, "no light-mode override of the shadow ink")
        self.assertIn("--sh-k:.45", light[0].replace(" ", ""))
        script = (ASSETS / "shell.js").read_text(encoding="utf-8")
        self.assertRegex(script, r"dataset\.mode\s*=", "applyPalette must tell the CSS which mode it is in")


class EverySurfaceReadsTheScaleTests(unittest.TestCase):
    def test_every_radius_is_a_token(self):
        stray = [f"{sheet} {selector}: {value}" for sheet, _stack, selector, value in shell_css.values("border-radius")
                 if any(part not in {"0"} and not TOKEN.fullmatch(part)
                        for part in value.replace("!important", "").split())]
        self.assertEqual(stray, [])

    def test_every_drop_shadow_is_a_token(self):
        stray = []
        for sheet, _stack, selector, value in shell_css.values("box-shadow"):
            for layer in re.split(r",(?![^(]*\))", value.replace("!important", "")):
                layer = layer.strip()
                if layer == "none" or SHADOW_TOKEN.fullmatch(layer):
                    continue
                # The accent bars (the current nav row, the setup chapter, a
                # pressed segment) and the danger bar on an armed Quit are
                # emissive marks drawn as insets.
                if layer.startswith("inset") and ("var(--accent)" in layer or "var(--danger)" in layer):
                    continue
                if layer.startswith(("inset", "0 0 0")) and ("color-mix" in layer or "var(--ring)" in layer):
                    continue
                stray.append(f"{sheet} {selector}: {layer}")
        self.assertEqual(stray, [])

    def test_no_literal_shadow_ink_outside_the_tokens(self):
        for sheet in shell_css.SHEETS:
            text = shell_css.source(sheet).replace(shell_css.tokens_block(), "")
            self.assertIsNone(re.search(r"box-shadow:[^;}]*#[0-9a-fA-F]{3,8}", text), sheet)


class EveryNameIsDefinedTests(unittest.TestCase):
    def test_every_custom_property_the_css_reads_is_defined(self):
        defined = shell_css.defined_properties() | script_set_properties()
        missing = sorted(shell_css.used_properties() - defined)
        self.assertEqual(missing, [], "each of these silently uses its fallback, or nothing")

    def test_the_guard_sees_an_undefined_name(self):
        self.assertIn("--radius", {"--radius"} - shell_css.defined_properties())


if __name__ == "__main__":
    unittest.main()
