from __future__ import annotations

import json
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


ASSET_DIR = Path(__file__).resolve().parents[1] / "knight_flow" / "assets"


class LoadingVisualTests(unittest.TestCase):
    def test_loading_loop_is_full_spectrum_and_seamless(self) -> None:
        metadata = json.loads((ASSET_DIR / "loading_pill_240.json").read_text(encoding="utf-8"))
        sheet = Image.open(ASSET_DIR / "loading_pill_240.png").convert("RGBA")

        self.assertEqual(metadata["frame_count"], 240)
        self.assertEqual(metadata["frame_width"], 320)
        self.assertEqual(metadata["frame_height"], 58)
        self.assertTrue(metadata["transparent_background"])

        columns = int(metadata["columns"])
        width = int(metadata["frame_width"])
        height = int(metadata["frame_height"])

        def frame(index: int) -> Image.Image:
            x = (index % columns) * width
            y = (index // columns) * height
            return sheet.crop((x, y, x + width, y + height))

        for index in (0, 60, 120, 180):
            current = frame(index)
            hsv = current.convert("RGB").convert("HSV")
            alpha = current.getchannel("A")
            saturated = hsv.getchannel("S").point(lambda value: 255 if value >= 170 else 0)
            saturated_opaque = ImageChops.multiply(saturated, alpha)
            opaque_total = max(1, sum(ImageStat.Stat(alpha).sum))
            saturation_total = sum(ImageStat.Stat(saturated_opaque).sum)
            self.assertGreater(saturation_total / opaque_total, 0.72)

        seam = ImageChops.difference(frame(239).convert("RGB"), frame(0).convert("RGB"))
        self.assertLess(sum(ImageStat.Stat(seam).rms) / 3.0, 42.0)


if __name__ == "__main__":
    unittest.main()
