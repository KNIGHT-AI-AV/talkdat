"""The DPI layer that turned 'low-resolution ugliness' back into pixels.

The app never declared DPI awareness, so a display scaled past 100% got a
96-DPI render bitmap-stretched by Windows: blurry text on every window, on
exactly the machines most laptops are. These tests pin the arithmetic that
makes the fix safe -- the awareness call itself is a Windows API and is
exercised by running the app, but a wrong scale factor here would size every
window wrongly on every machine at once.
"""
from __future__ import annotations

import unittest
import ctypes
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

from knight_flow import ui_scale


class ScaleArithmeticTests(unittest.TestCase):
    def setUp(self) -> None:
        ui_scale.reset_for_tests()

    def tearDown(self) -> None:
        ui_scale.reset_for_tests()

    def _aware(self, dpi: float) -> None:
        ui_scale._awareness_applied = True
        self.dpi_patch = mock.patch.object(ui_scale, "system_dpi", return_value=dpi)
        self.dpi_patch.start()
        self.addCleanup(self.dpi_patch.stop)

    def test_the_common_windows_factors_come_out_exact(self) -> None:
        for dpi, expected in ((96, 1.0), (120, 1.25), (144, 1.5), (192, 2.0)):
            ui_scale.reset_for_tests()
            self._aware(dpi)
            self.assertEqual(expected, ui_scale.scale(), f"dpi={dpi}")

    def test_odd_dpi_rounds_to_quarter_steps(self) -> None:
        """1.437x would turn every even margin odd. Windows itself only ships
        quarter steps, so snapping loses nothing real."""
        self._aware(138)  # 1.4375 raw
        self.assertEqual(1.5, ui_scale.scale())

    def test_without_awareness_the_scale_is_exactly_one(self) -> None:
        """If the awareness call failed, Windows is still stretching -- and
        multiplying our own sizes on top would double-scale everything."""
        with mock.patch.object(ui_scale, "system_dpi", return_value=144):
            self.assertEqual(1.0, ui_scale.scale())
            self.assertEqual(192, ui_scale.px(192))

    def test_px_scales_and_never_returns_zero(self) -> None:
        self._aware(144)
        self.assertEqual(288, ui_scale.px(192))
        self.assertEqual(1, ui_scale.px(0.4), "a hairline must stay drawable")

    def test_spacing_scales_pairs_but_preserves_zero(self) -> None:
        self._aware(144)
        self.assertEqual(18, ui_scale.spacing(12))
        self.assertEqual((0, 24), ui_scale.spacing((0, 16)))
        self.assertEqual((0, 6, 0, 12), ui_scale.spacing((0, 4, 0, 8)))

    def test_awareness_success_invalidates_a_provisional_scale_cache(self) -> None:
        ui_scale._cached_scale = 1.0
        api = SimpleNamespace(
            shcore=SimpleNamespace(SetProcessDpiAwareness=mock.Mock(return_value=0)),
        )
        with (
            mock.patch.object(ui_scale.sys, "platform", "win32"),
            mock.patch.object(ctypes, "windll", api, create=True),
            mock.patch.object(ui_scale, "system_dpi", return_value=144.0),
        ):
            self.assertTrue(ui_scale.enable_dpi_awareness())
            self.assertEqual(ui_scale.scale(), 1.5)

    def test_unexpected_awareness_failure_is_not_reported_as_success(self) -> None:
        api = SimpleNamespace(
            shcore=SimpleNamespace(SetProcessDpiAwareness=mock.Mock(return_value=-1)),
        )
        with (
            mock.patch.object(ui_scale.sys, "platform", "win32"),
            mock.patch.object(ctypes, "windll", api, create=True),
        ):
            self.assertFalse(ui_scale.enable_dpi_awareness())

    def test_access_denied_queries_an_existing_aware_mode(self) -> None:
        def aware(_handle, pointer) -> int:
            pointer._obj.value = 1
            return 0

        api = SimpleNamespace(
            shcore=SimpleNamespace(
                SetProcessDpiAwareness=mock.Mock(return_value=-2147024891),
                GetProcessDpiAwareness=mock.Mock(side_effect=aware),
            ),
            kernel32=SimpleNamespace(GetCurrentProcess=mock.Mock(return_value=123)),
        )
        with (
            mock.patch.object(ui_scale.sys, "platform", "win32"),
            mock.patch.object(ctypes, "windll", api, create=True),
        ):
            self.assertTrue(ui_scale.enable_dpi_awareness())
        api.shcore.GetProcessDpiAwareness.assert_called_once()

    def test_access_denied_does_not_promote_an_existing_unaware_mode(self) -> None:
        def unaware(_handle, pointer) -> int:
            pointer._obj.value = 0
            return 0

        api = SimpleNamespace(
            shcore=SimpleNamespace(
                SetProcessDpiAwareness=mock.Mock(return_value=2147942405),
                GetProcessDpiAwareness=mock.Mock(side_effect=unaware),
            ),
            kernel32=SimpleNamespace(GetCurrentProcess=mock.Mock(return_value=123)),
        )
        with (
            mock.patch.object(ui_scale.sys, "platform", "win32"),
            mock.patch.object(ctypes, "windll", api, create=True),
        ):
            self.assertFalse(ui_scale.enable_dpi_awareness())

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows DPI API only")
    def test_real_win64_locked_process_mode_is_detected(self) -> None:
        script = """
import ctypes
from knight_flow import ui_scale
ctypes.windll.shcore.SetProcessDpiAwareness(1)
ui_scale.reset_for_tests()
raise SystemExit(0 if ui_scale.enable_dpi_awareness() else 7)
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"locked Win64 DPI mode was not detected:\n{result.stdout}\n{result.stderr}",
        )

    def test_config_override_wins_and_is_clamped(self) -> None:
        """The escape hatch for a display Windows misreports, bounded so a
        corrupt value cannot make the pill invisible or monitor-sized."""
        self._aware(96)
        self.assertEqual(2.0, ui_scale.scale({"ui": {"scale": 2.0}}))
        self.assertEqual(3.0, ui_scale.scale({"ui": {"scale": 99}}))
        self.assertEqual(1.0, ui_scale.scale({"ui": {"scale": 0.2}}))
        # Junk falls back to detection rather than raising mid-startup.
        self.assertEqual(1.0, ui_scale.scale({"ui": {"scale": "nonsense"}}))

    def test_geometry_strings_scale_their_size_only(self) -> None:
        self._aware(144)
        self.assertEqual("1620x1230", ui_scale.scale_geometry("1080x820"))
        self.assertEqual("300x150+40+60", ui_scale.scale_geometry("200x100+40+60"),
                         "offsets are positions, not sizes; scaling them would fling windows off-screen")
        self.assertEqual("+40+60", ui_scale.scale_geometry("+40+60"))

    def test_junk_geometry_passes_through_unharmed(self) -> None:
        self._aware(144)
        self.assertEqual("banana", ui_scale.scale_geometry("banana"))

    def test_window_size_receipt_survives_a_dpi_change(self) -> None:
        receipt = ui_scale.window_size_receipt(
            1500,
            900,
            {"ui": {"scale": 1.5}},
        )
        self.assertEqual(
            {"width": 1000, "height": 600, "units": "logical-px-v1"},
            receipt,
        )
        self.assertEqual(
            (2000, 1200),
            ui_scale.restore_window_size(receipt, {"ui": {"scale": 2.0}}),
        )

    def test_legacy_window_size_is_read_once_as_physical_pixels(self) -> None:
        self.assertEqual(
            (1180, 940),
            ui_scale.restore_window_size("1180x940", {"ui": {"scale": 2.0}}),
        )
        self.assertIsNone(ui_scale.restore_window_size("broken", {"ui": {"scale": 2.0}}))


class TkFontScalingTests(unittest.TestCase):
    class _Tk:
        def __init__(self, current: float = 2.0) -> None:
            self.current = current
            self.set_values: list[float] = []

        def call(self, *args):
            if args == ("tk", "scaling"):
                return self.current
            if args[:2] == ("tk", "scaling") and len(args) == 3:
                self.current = float(args[2])
                self.set_values.append(self.current)
                return ""
            raise AssertionError(args)

    class _Root:
        def __init__(self, current: float = 2.0) -> None:
            self.tk = TkFontScalingTests._Tk(current)

    def setUp(self) -> None:
        ui_scale.reset_for_tests()

    def tearDown(self) -> None:
        ui_scale.reset_for_tests()

    def test_windows_override_drives_fonts_and_geometry_together(self) -> None:
        root = self._Root()
        with mock.patch.object(ui_scale.sys, "platform", "win32"):
            ui_scale.apply_tk_scaling(root, {"ui": {"scale": 2.0}})
        self.assertAlmostEqual(root.tk.current, 192.0 / 72.0)

    def test_windows_detected_scale_sets_matching_font_scale(self) -> None:
        root = self._Root()
        ui_scale._awareness_applied = True
        with (
            mock.patch.object(ui_scale.sys, "platform", "win32"),
            mock.patch.object(ui_scale, "system_dpi", return_value=144.0),
        ):
            ui_scale.apply_tk_scaling(root)
        self.assertAlmostEqual(root.tk.current, 144.0 / 72.0)

    def test_mac_keeps_native_scaling_without_override(self) -> None:
        root = self._Root(current=2.25)
        with mock.patch.object(ui_scale.sys, "platform", "darwin"):
            ui_scale.apply_tk_scaling(root)
        self.assertEqual(root.tk.set_values, [])
        self.assertEqual(root.tk.current, 2.25)

    def test_mac_override_is_relative_and_idempotent(self) -> None:
        root = self._Root(current=2.0)
        with mock.patch.object(ui_scale.sys, "platform", "darwin"):
            ui_scale.apply_tk_scaling(root, {"ui": {"scale": 1.5}})
            ui_scale.apply_tk_scaling(root, {"ui": {"scale": 1.5}})
        self.assertEqual(root.tk.set_values, [3.0, 3.0])

    def test_mac_removing_an_override_restores_native_scaling(self) -> None:
        root = self._Root(current=2.0)
        with mock.patch.object(ui_scale.sys, "platform", "darwin"):
            ui_scale.apply_tk_scaling(root, {"ui": {"scale": 1.5}})
            ui_scale.apply_tk_scaling(root, {"ui": {}})
        self.assertEqual(root.tk.set_values, [3.0, 2.0])
        self.assertEqual(root.tk.current, 2.0)


class ContextMenuControlTests(unittest.TestCase):
    """Restart and Close on the Pill's own menu, not only in the tray.

    The tray is the surface nobody thinks to open; the Pill is the app's
    visible body. These pin that the rows exist, sit at the top, and dispatch
    to the same callbacks the tray uses -- one behaviour, two doors.
    """

    def _rows(self):
        # Runtime rows, not AST order: the accordion made the source contain
        # a nested conditional list whose tuples walk out of visual order.
        from knight_flow.overlay import Overlay

        overlay = Overlay.__new__(Overlay)
        overlay._menu_show_more = False
        return [row[0] for row in overlay._context_menu_default_rows()]

    def test_every_row_geometry_site_shares_one_origin(self) -> None:
        """The hover plate highlighted one row above the pointer because two
        of four geometry sites did their own row arithmetic after the pinned
        route switch claimed the first pitch. All row math must go through
        MENU_ROWS_Y0; private arithmetic against MENU_ROW_TOP is the bug."""
        from pathlib import Path

        source = Path("knight_flow/overlay.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_context_menu_default_rows":
                keys = [
                    element.elts[0].value
                    for statement in ast.walk(node)
                    if isinstance(statement, ast.List)
                    for element in statement.elts
                    if isinstance(element, ast.Tuple) and element.elts
                ]
                return keys
        raise AssertionError("_context_menu_default_rows not found")

    def test_every_row_geometry_site_shares_one_origin(self) -> None:
        """The hover plate highlighted one row above the pointer because two
        of four geometry sites did their own row arithmetic after the pinned
        route switch claimed the first pitch. All row math must go through
        MENU_ROWS_Y0; private arithmetic against MENU_ROW_TOP is the bug."""
        from pathlib import Path

        source = Path("knight_flow/overlay.py").read_text(encoding="utf-8")

        # X-162: there is now exactly ONE site, `_menu_row_top`, and every
        # caller goes through it. The count used to be 3 because there was no
        # single origin to point at; a cached hover sprite would have made it a
        # fourth. One is the number this test always wanted.
        self.assertEqual(source.count("self.MENU_ROWS_Y0 + index * self.MENU_ROW_PITCH"), 1)
        self.assertIn("def _menu_row_top(self, index: int) -> int:", source)
        self.assertEqual(source.count("self.MENU_ROW_TOP + index * self.MENU_ROW_PITCH"), 0,
                         "a row-geometry site is doing private arithmetic again")
        self.assertIn("content_y = self._context_menu_content_y(viewport_y)", source)
        self.assertIn("(content_y - self.MENU_ROWS_Y0) // self.MENU_ROW_PITCH", source)

    def test_restart_and_close_lead_the_menu(self) -> None:
        keys = self._rows()
        # X-118, his IA: Home leads; destructive app control closes the
        # menu, the way every current tray app orders itself.
        self.assertEqual("settings", keys[0], f"Home must lead the menu, got {keys[:4]}")
        self.assertEqual(["restart_app", "quit_app"], keys[-2:],
                         f"app control must close the menu, got {keys[-4:]}")

    def test_they_dispatch_to_the_trays_callbacks(self) -> None:
        from pathlib import Path

        source = Path("knight_flow/overlay.py").read_text(encoding="utf-8")
        self.assertIn('self.callbacks.get("restart" if action == "restart_app" else "quit")', source,
                      "the menu must reuse the tray's restart/quit callbacks, not invent new ones")


class MenuWidthNeverTrustsPreMapOneTests(unittest.TestCase):
    """X-144, his screenshot: `winfo_width() or fallback` is the truthy-1
    trap -- a pre-layout canvas reports width 1, `1 or x` is 1, and the
    pinned switches rendered one pixel wide with clipped labels. The class
    stays extinct: no menu code may use the `winfo or` idiom again."""

    def test_the_truthy_width_idiom_is_extinct(self) -> None:
        from pathlib import Path as _Path

        source = (_Path(__file__).resolve().parent.parent / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        self.assertNotIn("winfo_width() or", source)
        self.assertNotIn("winfo_height() or", source)
        self.assertIn("_menu_canvas_width", source)

    def test_translation_layouts_reject_the_premap_width_of_one(self) -> None:
        from pathlib import Path as _Path

        source = (_Path(__file__).resolve().parent.parent / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        cases = (
            ("def arrange_route_options", "options.winfo_width()"),
            ("def arrange_action_rows", "controls.winfo_width()"),
        )
        for marker, measurement in cases:
            with self.subTest(layout=marker):
                start = source.index(marker)
                end = source.index("\n        def ", start + len(marker))
                block = source[start:end]
                first_guard = block.index("if width <= 1:")
                measured = block.index(measurement)
                second_guard = block.index("if width <= 1:", first_guard + 1)
                fallback = block.index("ui_scale.px(900, self.config)")
                self.assertLess(first_guard, measured)
                self.assertLess(measured, second_guard)
                self.assertLess(second_guard, fallback)


if __name__ == "__main__":
    unittest.main()


class AWindowOpensOnTheScreenItHasTests(unittest.TestCase):
    """X-535: "the window menu that pops up is gigantic", on a 4K panel at 150%.

    Three origins feed a window's size and none of them was checked against
    the monitor: a default tuned on somebody else's screen, a SAVED size
    measured on whatever monitor and scale the person had last time, and a
    size the wizard grew itself to fit a step. His onboarding window restored
    to 1908x2091 on a 2066px work area -- taller than the screen -- and his
    settings window to 2034px, 98% of it.
    """

    def setUp(self) -> None:
        ui_scale.reset_for_tests()

    def tearDown(self) -> None:
        ui_scale.reset_for_tests()

    #: His measured work area: 3840x2160 panel at 150%, less the taskbar.
    WORK = (0, 0, 3840, 2066)

    def test_the_exact_window_he_photographed_now_fits(self) -> None:
        width, height = ui_scale.clamp_to_work_area(1908, 2091, self.WORK)
        self.assertLessEqual(height, self.WORK[3], "still taller than the screen")
        self.assertLess(height, 2091)
        self.assertEqual(1908, width, "the width fitted; it must not be touched")

    def test_a_near_fullscreen_restore_is_brought_back(self) -> None:
        _width, height = ui_scale.clamp_to_work_area(2655, 2034, self.WORK)
        self.assertLess(
            height / (self.WORK[3] - self.WORK[1]), 0.85,
            "a window that opens at 98% of the screen is the complaint",
        )

    def test_a_size_that_already_fits_is_left_alone(self) -> None:
        """The clamp is a ceiling, not a policy. It must not resize windows
        that were already sensible -- most of his were."""
        for size in ((1050, 750), (1470, 1020), (1620, 1140), (1350, 960)):
            with self.subTest(size=size):
                self.assertEqual(size, ui_scale.clamp_to_work_area(*size, self.WORK))

    def test_no_work_area_means_no_clamp(self) -> None:
        """A headless test or a platform without the monitor API must not have
        its windows silently shrunk to nothing."""
        self.assertEqual((1908, 2091), ui_scale.clamp_to_work_area(1908, 2091, None))

    def test_the_ceiling_never_returns_something_unusable(self) -> None:
        """A tiny or absurd work area still yields a positive size."""
        for area in ((0, 0, 10, 10), (0, 0, 1, 1)):
            with self.subTest(area=area):
                width, height = ui_scale.clamp_to_work_area(1908, 2091, area)
                self.assertGreaterEqual(width, 1)
                self.assertGreaterEqual(height, 1)

    def test_the_share_leaves_the_desktop_visible(self) -> None:
        width, height = ui_scale.clamp_to_work_area(99_999, 99_999, self.WORK)
        self.assertLess(width, self.WORK[2] - self.WORK[0])
        self.assertLess(height, self.WORK[3] - self.WORK[1])


class TheClampIsActuallyWiredInTests(unittest.TestCase):
    """The arithmetic above is only worth having if the windows go through it.

    overlay.py needs a display to construct, so these read the source at the
    one chokepoint every utility window passes through -- which is the reason
    the clamp was put there rather than at thirty call sites.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        cls.overlay = (root / "knight_flow" / "overlay.py").read_text(encoding="utf-8")
        cls.onboarding = (root / "knight_flow" / "ui" / "onboarding.py").read_text(encoding="utf-8")

    def test_every_utility_window_is_clamped_before_it_opens(self) -> None:
        self.assertIn("ui_scale.clamp_to_work_area(", self.overlay)
        self.assertIn("self._active_monitor_work_area()", self.overlay)

    def test_the_clamp_runs_after_the_saved_size_is_read(self) -> None:
        """A restored size is the one most likely to be wrong -- it was
        measured on whatever monitor and scale the person had last time. If
        the clamp ran first it would miss exactly that case."""
        restore = self.overlay.index("restore_window_size(saved")
        clamp = self.overlay.index("ui_scale.clamp_to_work_area(")
        self.assertLess(restore, clamp, "the clamp must come after the restore")

    def test_the_setup_wizard_does_not_remember_a_size(self) -> None:
        """It grew to fit its tallest step, saved that, and then opened that
        big on step one forever."""
        self.assertIn("remember_size=False", self.onboarding)
        self.assertIn("remember_size: bool = True", self.overlay)
        self.assertIn("if resizable and remember_size:", self.overlay)

    def test_a_window_that_forgets_also_never_writes(self) -> None:
        """Reading no receipt while still writing one leaves a growing value
        on disk for some future version to trip over."""
        self.assertEqual(
            2, self.overlay.count("if resizable and remember_size:"),
            "both the restore and the <Configure> receipt must be gated",
        )

    def test_the_wizard_growth_has_a_ceiling(self) -> None:
        self.assertIn("def _grow_ceiling(self)", self.onboarding)
        self.assertIn("ui_scale.OPENING_SHARE_OF_WORK_AREA", self.onboarding)
