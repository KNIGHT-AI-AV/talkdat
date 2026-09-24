from __future__ import annotations

import unittest

from knight_flow.mac_support import FONT_MONO, FONT_UI, FONT_UI_SEMIBOLD, IS_MAC
from tests.tk_support import acquire_root, probe_error, release_root


@unittest.skipUnless(IS_MAC, "describes how the Windows families degrade on Aqua")
@unittest.skipIf(probe_error is not None, "no usable Tk display")
class TheWindowsFontsDoNotSurviveTkOnAquaTests(unittest.TestCase):
    """Tk resolves an unknown family to the system font without complaining.

    That silence is the problem. "Segoe UI Semibold" carries its weight in the
    family name, so it became the system font at weight=normal and 80 headings,
    buttons and emphasised labels lost every bit of contrast against body text.
    "Consolas" became the *proportional* system font, so the licence key, the
    redeem field and every text box stopped lining up.
    """

    def setUp(self) -> None:
        self.root = acquire_root()
        self.addCleanup(lambda: release_root(self.root))
        import tkinter.font as tkfont

        self.tkfont = tkfont

    def test_emphasis_is_actually_heavier_than_body(self) -> None:
        body = self.tkfont.Font(root=self.root, family=FONT_UI, size=12)
        strong = self.tkfont.Font(root=self.root, family=FONT_UI_SEMIBOLD, size=12)
        self.assertEqual(strong.actual("weight"), "bold")
        self.assertNotEqual(strong.actual("weight"), body.actual("weight"))

    def test_the_monospace_font_is_monospaced(self) -> None:
        mono = self.tkfont.Font(root=self.root, family=FONT_MONO, size=12)
        self.assertEqual(mono.measure("iiiiiiii"), mono.measure("WWWWWWWW"))

    def test_the_windows_families_would_not_have_worked(self) -> None:
        """Proves the fix is needed rather than defensive. If a future macOS
        ships Segoe UI, this fails and the mapping can be reconsidered."""
        segoe_semibold = self.tkfont.Font(root=self.root, family="Segoe UI Semibold", size=12)
        consolas = self.tkfont.Font(root=self.root, family="Consolas", size=12)
        self.assertEqual(segoe_semibold.actual("weight"), "normal")
        self.assertNotEqual(consolas.measure("iiiiiiii"), consolas.measure("WWWWWWWW"))

    def test_no_windows_font_names_are_left_in_the_ui(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "knight_flow"
        offenders = []
        for path in (root / "overlay.py", root / "ui_scale.py",
                     root / "ui" / "onboarding.py", root / "ui" / "flow_console.py"):
            text = path.read_text(encoding="utf-8")
            for name in ('"Segoe UI Semibold"', '"Segoe UI"', '"Consolas"'):
                if name in text:
                    offenders.append(f"{path.name}: {name}")
        self.assertEqual(offenders, [], "font families must go through mac_support constants")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(IS_MAC, "macOS platform behaviour")
class TheDuckGuardIsHonestAboutWhatItCanDoTests(unittest.TestCase):
    """"Mute speaker output while recording" is on by default.

    On macOS it did nothing at all -- OutputMuteGuard.start returned
    immediately off win32 -- so the setting was checked, described in Settings,
    and inert. It now ducks through the system volume, and on devices with no
    software volume (audio interfaces, most USB DACs) it does nothing *and does
    not pretend*, which matters because restoring a volume that was never read
    would set a level the person never chose.
    """

    def test_a_device_without_volume_control_leaves_no_state_behind(self) -> None:
        from unittest.mock import patch

        from knight_flow import mac_support as ms
        from knight_flow.windows_audio import OutputMuteGuard

        guard = OutputMuteGuard()
        with patch.object(ms, "system_output_volume", return_value=None), \
             patch.object(ms, "set_system_output_volume") as setter:
            guard.start(enabled=True, target=0.0)
            import time as _t
            _t.sleep(0.3)
            setter.assert_not_called()
        self.assertIsNone(guard._original_volume)

    def test_the_original_volume_is_restored(self) -> None:
        import time as _t
        from unittest.mock import patch

        from knight_flow import mac_support as ms
        from knight_flow.windows_audio import OutputMuteGuard

        guard = OutputMuteGuard()
        with patch.object(ms, "system_output_volume", return_value=0.62), \
             patch.object(ms, "set_system_output_volume") as setter:
            guard.start(enabled=True, target=0.0)
            _t.sleep(0.3)
            guard.stop()
            _t.sleep(0.3)
        levels = [call.args[0] for call in setter.call_args_list]
        self.assertEqual(levels, [0.0, 0.62], "must duck to the target then restore what was there")

    def test_disabled_means_disabled(self) -> None:
        from unittest.mock import patch

        from knight_flow import mac_support as ms
        from knight_flow.windows_audio import OutputMuteGuard

        with patch.object(ms, "set_system_output_volume") as setter:
            OutputMuteGuard().start(enabled=False)
            import time as _t
            _t.sleep(0.2)
            setter.assert_not_called()


@unittest.skipUnless(IS_MAC, "Aqua window transparency")
@unittest.skipIf(probe_error is not None, "no usable Tk display")
class ThePillWindowMustBeTransparentTests(unittest.TestCase):
    """The flagship overlay rendered as an opaque near-black rectangle.

    Windows gets per-pixel transparency by nominating a key colour with the
    -transparentcolor wm attribute. That attribute does not exist on Aqua: it
    raises TclError, and the call site swallowed it, so the window kept the key
    colour #010203 as an ordinary background. The "floating pill" was a dark bar
    with square corners, and the same pattern hit the context menu, tooltips and
    the hover panel.
    """

    def test_the_windows_attribute_really_is_unavailable(self) -> None:
        """Proves the fix is needed rather than defensive."""
        import tkinter as tk

        from tests.tk_support import acquire_root, release_root

        root = acquire_root()
        self.addCleanup(lambda: release_root(root))
        with self.assertRaises(tk.TclError):
            root.attributes("-transparentcolor", "#010203")

    def test_the_aqua_pair_is_applied(self) -> None:
        from tests.tk_support import acquire_root, release_root

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(lambda: release_root(overlay.root))
        overlay.root.update()

        self.assertEqual(overlay.root.cget("bg"), "systemTransparent")
        self.assertTrue(overlay.root.attributes("-transparent"))
        # The canvas the artwork is blitted onto must be transparent too, or the
        # window is see-through and the drawing surface is not.
        self.assertEqual(overlay.canvas.cget("bg"), "systemTransparent")
        self.assertEqual(overlay.container.cget("bg"), "systemTransparent")

    def test_corners_are_not_hand_carved(self) -> None:
        """X-10, per the Windows agent's instruction: NSWindow gives rounded
        corners and the shadow for free once the window is really transparent.
        Carving a region would replace both with jagged edges and no shadow."""
        from tests.tk_support import acquire_root, release_root

        from knight_flow.config import load_config
        from knight_flow.overlay import Overlay

        overlay = Overlay(config=load_config(), callbacks={}, root=acquire_root())
        self.addCleanup(lambda: release_root(overlay.root))
        # Must return without touching ctypes.windll, which would raise here.
        overlay._apply_window_region(overlay.root, 200, 40, 20)


@unittest.skipUnless(IS_MAC, "Apple silicon acceleration")
class TheGpuSettingMustNameCoreMLTests(unittest.TestCase):
    """CoreML was doing the work by accident.

    _gpu_providers listed only CUDA and DirectML, so on a Mac it returned [],
    the caller passed no providers at all, and onnxruntime's default order --
    which happens to put CoreML first on macOS -- picked it up anyway. The
    acceleration was real but unnamed, so the "use GPU" setting controlled and
    reported nothing.
    """

    def test_coreml_is_offered_when_available(self) -> None:
        import onnxruntime

        from knight_flow.local_stt import _gpu_providers

        if "CoreMLExecutionProvider" not in onnxruntime.get_available_providers():
            self.skipTest("this onnxruntime build has no CoreML provider")
        providers = _gpu_providers()
        self.assertIn("CoreMLExecutionProvider", providers)
        # CPU must remain as the fallback for nodes CoreML cannot take -- it
        # takes about half of Parakeet's graph, not all of it.
        self.assertEqual(providers[-1], "CPUExecutionProvider")

    def test_it_stays_empty_when_nothing_is_available(self) -> None:
        """An empty list means "let onnxruntime choose", which is the right
        behaviour on a machine with no accelerator."""
        from unittest.mock import patch

        from knight_flow import local_stt

        with patch("onnxruntime.get_available_providers", return_value=["CPUExecutionProvider"]):
            self.assertEqual(local_stt._gpu_providers(), [])
