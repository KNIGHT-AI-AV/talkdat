"""X-340 + X-341: captions get an unmissable close and live font control;
choosing a local model stops hijacking the route; every chromeless
surface still shows a way back.

His reports, verbatim: "I don't see an X once it's live"; "the user
should still be able to edit the size of the window and edit the size of
the font ... at all times"; "when users changing what their local model
is, it shouldn't automatically make local model active".
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


def block(text: str, pattern: str) -> str:
    found = re.search(pattern, text, re.S)
    assert found, "anchor moved: " + pattern
    return found.group(0)


class TheCaptionsCloseIsUnmissableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.overlay = OVERLAY.read_text(encoding="utf-8")
        cls.captions = block(cls.overlay, r"def toggle_captions\(self\) -> None:.*?window\.after\(200, banner_tick\)")

    def test_a_corner_x_floats_over_the_glass(self) -> None:
        # FlatButton: tk.Button itself off macOS, a styled Label on Aqua, where
        # a native button paints its face white (tests/test_aqua_rendering.py).
        self.assertIn("corner_close = FlatButton(", self.captions)
        self.assertIn('anchor="ne"', self.captions)
        self.assertIn("corner_close.lift()", self.captions)

    def test_the_corner_x_survives_both_modes(self) -> None:
        mode = block(self.captions, r"def apply_mode\(\) -> None:.*?mode_button\.configure")
        self.assertIn("corner_close", mode)
        self.assertIn("*font_buttons", mode)

    def test_every_close_path_still_stops_the_microphone(self) -> None:
        """X-175's funnel is the guarantee; losing the disposer would leave
        the capture thread running with no visible owner."""
        self.assertIn('self.add_window_disposer("captions", stop_captions_engine)', self.captions)


class TheFontIsThePersonsAtAllTimesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.captions = block(OVERLAY.read_text(encoding="utf-8"),
                             r"def toggle_captions\(self\) -> None:.*?window\.after\(200, banner_tick\)")

    def test_the_scale_is_bounded_and_persisted(self) -> None:
        self.assertIn('captions_config["font_scale"] = state["font_scale"]', self.captions)
        self.assertEqual(self.captions.count("max(0.7, min(1.8,"), 2,
                         "load and nudge must share the same clamp")

    def test_one_sizing_brain_serves_resize_and_buttons(self) -> None:
        self.assertIn("def apply_caption_layout(", self.captions)
        self.assertIn('size * state["font_scale"]', self.captions)
        rescale = block(self.captions, r"def rescale\(event: tk\.Event\) -> None:.*?apply_caption_layout\(event\.width, event\.height\)")
        self.assertNotIn("label.configure(font=", rescale,
                         "rescale grew its own sizing math again; the brain must stay single")


class ChoosingAModelIsNotChoosingARouteTests(unittest.TestCase):
    def test_set_local_active_leaves_the_provider_alone(self) -> None:
        overlay = OVERLAY.read_text(encoding="utf-8")
        body = block(overlay, r"def set_local_active\(model: Any\) -> None:.*?Your Cloud/Auto/Local route is unchanged")
        self.assertNotIn('["provider"] = "local"', body)
        self.assertNotIn('provider_lane_var.set("local")', body)
        self.assertIn('settings["model"] = model.id', body)


class EverySurfaceShowsAWayBackTests(unittest.TestCase):
    def test_a_bar_failure_places_a_fallback_close(self) -> None:
        overlay = OVERLAY.read_text(encoding="utf-8")
        fallback = block(overlay, r"could not fit a title bar to the %s window.*?fallback_close\.lift\(\)")
        self.assertIn("fallback_close = FlatButton(", fallback)
        self.assertIn("_request_utility_close(window)", fallback)


if __name__ == "__main__":
    unittest.main()
