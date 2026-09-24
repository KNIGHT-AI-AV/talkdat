from __future__ import annotations

import ast
import hashlib
import inspect
from pathlib import Path
import unittest

from PIL import Image

from knight_flow.overlay import Overlay
from knight_flow.ui.iconography import ICON_NAMES, render_icon


ROOT = Path(__file__).resolve().parents[1]
ICON_ROOT = ROOT / "knight_flow" / "assets" / "ui" / "icons" / "imagegen-v1"
LOCKED_BRAND_ASSETS = {
    "logo.png": "".join((
        "6049d3252b8e7bbcc5d5d8ca5808aa8",
        "602e05ff61bfcd42fb66550bcee196d07",
    )),
    "flow_pill_240.png": "".join((
        "c765dd32c83bbaa8a916f3832c7bacf8",
        "a6586dc72bde5fe4175f283e9b697ecb",
    )),
    "loading_pill_240.png": "".join((
        "ef78b0993e9ec7ccec17518ba4f97778",
        "887a1f432a771b821abbd57c39af335e",
    )),
}


class GeneratedIconAssetTests(unittest.TestCase):
    def test_master_and_runtime_sets_are_complete_and_exact(self) -> None:
        expected = {f"{name}.png" for name in ICON_NAMES}
        self.assertEqual({path.name for path in (ICON_ROOT / "masters").glob("*.png")}, expected)
        self.assertEqual({path.name for path in (ICON_ROOT / "runtime").glob("*.png")}, expected)
        self.assertGreaterEqual(len(expected), 32)

    def test_generated_control_masters_have_real_alpha(self) -> None:
        for name in ("checkbox_off", "checkbox_on", "drag_handle", "resize_handle"):
            with self.subTest(icon=name):
                with Image.open(ICON_ROOT / "masters" / f"{name}.png") as source:
                    icon = source.convert("RGBA")
                alpha = icon.getchannel("A")
                self.assertEqual(alpha.getpixel((0, 0)), 0)
                self.assertEqual(alpha.getpixel((icon.width - 1, icon.height - 1)), 0)
                self.assertEqual(alpha.getextrema(), (0, 255))

    def test_runtime_assets_have_real_alpha_and_one_normalized_size(self) -> None:
        for name in sorted(ICON_NAMES):
            with self.subTest(icon=name):
                with Image.open(ICON_ROOT / "runtime" / f"{name}.png") as source:
                    icon = source.convert("RGBA")
                self.assertEqual(icon.size, (384, 384))
                alpha = icon.getchannel("A")
                self.assertEqual(alpha.getpixel((0, 0)), 0)
                self.assertEqual(alpha.getpixel((383, 383)), 0)
                extrema = alpha.getextrema()
                self.assertEqual(extrema[0], 0)
                self.assertEqual(extrema[1], 255)
                self.assertTrue(any(0 < value < 255 for value in alpha.getdata()))

    def test_theme_renderer_stays_visible_at_real_menu_sizes(self) -> None:
        palettes = (
            ("#f4eee2", "#35d5c8"),
            ("#172225", "#b36b32"),
        )
        for name in sorted(ICON_NAMES):
            for size in (20, 24, 32):
                for primary, detail in palettes:
                    with self.subTest(icon=name, size=size, primary=primary):
                        icon = render_icon(name, size, primary, detail)
                        self.assertEqual(icon.size, (size, size))
                        visible = sum(value > 16 for value in icon.getchannel("A").getdata())
                        self.assertGreater(visible, max(6, size))

    def test_every_generated_icon_recolours_across_every_theme(self) -> None:
        overlay = Overlay.__new__(Overlay)
        overlay.config = {"ui": {"settings_theme": "Flow Dark"}}
        themes = overlay._settings_theme_options()
        # Derived, not written down. A count in an assertion goes stale the
        # first time the catalogue grows, and reports a healthy addition as
        # a failure (X-538, 25 families to 40).
        from knight_flow.themes import SETTINGS_THEME_FAMILIES
        self.assertEqual(len(themes), len(SETTINGS_THEME_FAMILIES) * 2)
        for name in sorted(ICON_NAMES):
            variants: set[bytes] = set()
            for theme in themes:
                with self.subTest(icon=name, theme=theme):
                    palette = overlay._settings_palette(theme)
                    icon = render_icon(name, 24, palette["text"], palette["accent"])
                    self.assertGreater(
                        sum(value > 16 for value in icon.getchannel("A").getdata()),
                        24,
                    )
                    variants.add(hashlib.sha256(icon.tobytes()).digest())
            self.assertGreaterEqual(len(variants), 20, name)

    def test_logo_and_pill_brand_assets_are_not_part_of_icon_churn(self) -> None:
        asset_root = ROOT / "knight_flow" / "assets"
        for filename, expected in LOCKED_BRAND_ASSETS.items():
            with self.subTest(asset=filename):
                actual = hashlib.sha256((asset_root / filename).read_bytes()).hexdigest()
                self.assertEqual(actual, expected)

    def test_review_proofs_cover_dark_light_and_real_menu_geometry(self) -> None:
        with Image.open(ICON_ROOT / "contact-sheet.png") as source:
            self.assertGreaterEqual(source.width, 1000)
            self.assertGreaterEqual(source.height, 1500)
        for proof in ("menu-proof-dark.png", "menu-proof-light.png"):
            with self.subTest(proof=proof):
                with Image.open(ICON_ROOT / proof) as source:
                    self.assertEqual(source.size, (320, 768))


class GeneratedIconWiringTests(unittest.TestCase):
    def test_pill_destinations_use_semantic_assets_instead_of_reused_drawings(self) -> None:
        overlay = Overlay.__new__(Overlay)
        # X-339: the occasional rows live in the Features SIDE PANEL now;
        # the union is every drawn destination.
        rows = overlay._context_menu_default_rows() + overlay._context_menu_feature_rows()
        drawers = {action: drawer.__name__ for action, _title, _subtitle, drawer in rows}
        self.assertEqual(drawers["ramble"], "_draw_ramble_icon")
        self.assertEqual(drawers["captions"], "_draw_captions_icon")
        self.assertEqual(drawers["scribe"], "_draw_scribe_icon")
        self.assertEqual(drawers["local_models"], "_draw_offline_icon")
        self.assertEqual(drawers["restart_app"], "_draw_restart_icon")
        self.assertNotEqual(drawers["restart_app"], drawers["check_updates"])

    def test_context_icon_methods_do_not_draw_font_or_canvas_approximations(self) -> None:
        methods = (
            "_draw_gear_icon",
            "_draw_paste_icon",
            "_draw_history_icon",
            "_draw_scratchpad_icon",
            "_draw_stats_icon",
            "_draw_chip_icon",
            "_draw_update_icon",
            "_draw_close_icon",
            "_draw_translate_icon",
            "_draw_ramble_icon",
            "_draw_captions_icon",
            "_draw_scribe_icon",
            "_draw_offline_icon",
            "_draw_restart_icon",
        )
        forbidden = ("create_line", "create_arc", "create_oval", "create_polygon", "create_text")
        for method in methods:
            source = inspect.getsource(getattr(Overlay, method))
            with self.subTest(method=method):
                self.assertIn("_draw_menu_asset", source)
                for primitive in forbidden:
                    self.assertNotIn(primitive, source)

    def test_custom_control_affordances_use_generated_masters(self) -> None:
        style_source = inspect.getsource(Overlay._style_settings_widgets)
        menu_source = inspect.getsource(Overlay._draw_context_menu)
        resize_source = inspect.getsource(Overlay._install_utility_resize_grip)
        self.assertIn('"checkbox_off"', style_source)
        self.assertIn('"checkbox_on"', style_source)
        self.assertNotIn("draw_box", style_source)
        self.assertIn('"drag_handle"', menu_source)
        self.assertNotIn("create_oval", menu_source)
        self.assertIn('"resize_handle"', resize_source)
        self.assertNotIn("create_line", resize_source)

    def test_icon_calls_do_not_embed_fixed_hex_colours(self) -> None:
        for path in (
            ROOT / "knight_flow" / "overlay.py",
            ROOT / "knight_flow" / "ui" / "onboarding.py",
        ):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
                function_name = ""
                if isinstance(call.func, ast.Attribute):
                    function_name = call.func.attr
                elif isinstance(call.func, ast.Name):
                    function_name = call.func.id
                if function_name not in {"_ui_icon_photo", "_set_button_icon", "render_icon"}:
                    continue
                constants = (
                    node.value
                    for node in ast.walk(call)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                )
                fixed_colours = [value for value in constants if value.startswith("#")]
                self.assertFalse(
                    fixed_colours,
                    f"{path.name}:{call.lineno} freezes an icon to {fixed_colours}",
                )

    def test_action_controls_no_longer_embed_symbol_font_icons(self) -> None:
        overlay_source = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        onboarding_source = (ROOT / "knight_flow" / "ui" / "onboarding.py").read_text(encoding="utf-8")
        for glyph in ("🎙", "◐", "▭", "×", "☰", "«", "▮"):
            with self.subTest(glyph=glyph):
                self.assertNotIn(glyph, overlay_source)
        self.assertNotIn("⚠", onboarding_source)

    def test_packaged_build_includes_only_runtime_icon_assets(self) -> None:
        spec = (ROOT / "Talk Dat!.spec").read_text(encoding="utf-8")
        self.assertIn('"knight_flow/assets/ui/icons/imagegen-v1/runtime"', spec)
        self.assertNotIn('"knight_flow/assets/ui/icons/imagegen-v1/masters"', spec)


if __name__ == "__main__":
    unittest.main()
