"""The vectorized caustic must be the OLD caustic, faster.

The per-pixel Python loop was the measured reason live dictation animated at
14fps (scripts/profile_pill.py: ~28ms of every frame). The numpy rewrite is
only safe because it is the same arithmetic; this test keeps the original
loop as the reference and holds the rewrite to it pixel by pixel.
"""
from __future__ import annotations

import unittest

from PIL import Image

from knight_flow.overlay import caustic_masks
from knight_flow.pill_motion import faceted_voice_trace, microphone_energy_envelope


def reference_masks(values, trace, width, height, center_y):
    """The original per-pixel loop, verbatim from pre-vectorization overlay.py."""
    light_mask = Image.new("L", (width, height), 0)
    depth_mask = Image.new("L", (width, height), 0)
    light_values = []
    depth_values = []
    for y_index in range(height):
        for x_index in range(width):
            energy = values[x_index]
            ridge_y = center_y + trace[x_index] * height * 0.29
            distance = abs(y_index - ridge_y)
            ridge_width = max(0.85, height * (0.032 + energy * 0.035))
            ridge = max(0.0, 1.0 - distance / max(1.0, ridge_width * 2.4))
            ridge *= ridge
            shoulder = max(0.0, 1.0 - distance / max(1.0, ridge_width * 5.2))
            shoulder = shoulder * shoulder * (3.0 - 2.0 * shoulder)
            light_values.append(round(min(238.0, energy * (ridge * 190.0 + shoulder * 66.0))))
            depth_values.append(round(min(180.0, energy * max(0.0, shoulder - ridge) * 150.0)))
    light_mask.putdata(light_values)
    depth_mask.putdata(depth_values)
    return light_mask, depth_mask


class CausticEquivalenceTests(unittest.TestCase):
    def masks_for(self, raw_levels, width=96, height=28):
        values = list(microphone_energy_envelope(raw_levels, width))
        trace = list(faceted_voice_trace(values))
        center_y = (height - 1) / 2.0
        fast = caustic_masks(values, trace, width, height, center_y)
        slow = reference_masks(values, trace, width, height, center_y)
        return fast, slow

    def assert_equivalent(self, fast, slow):
        for fast_mask, slow_mask, name in [
            (fast[0], slow[0], "light"),
            (fast[1], slow[1], "depth"),
        ]:
            fast_px = list(fast_mask.getdata())
            slow_px = list(slow_mask.getdata())
            worst = max(abs(a - b) for a, b in zip(fast_px, slow_px))
            self.assertLessEqual(
                worst, 1,
                f"{name} mask drifted from the original math by {worst} levels",
            )

    def test_a_speaking_envelope_matches_the_original_loop(self) -> None:
        fast, slow = self.masks_for([0.05, 0.4, 0.9, 0.6, 0.2, 0.75, 0.35, 0.1])
        self.assert_equivalent(fast, slow)

    def test_a_quiet_envelope_matches_too(self) -> None:
        fast, slow = self.masks_for([0.02, 0.03, 0.05, 0.04])
        self.assert_equivalent(fast, slow)

    def test_a_clipping_envelope_matches_at_the_clamps(self) -> None:
        """Full-scale voice drives both mask formulas into their min() clamps;
        the clamps must land on the same pixels."""
        fast, slow = self.masks_for([1.0] * 8)
        self.assert_equivalent(fast, slow)


if __name__ == "__main__":
    unittest.main()
