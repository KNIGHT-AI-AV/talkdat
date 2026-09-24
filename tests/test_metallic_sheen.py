from __future__ import annotations

import unittest

from PIL import Image

from knight_flow.overlay import apply_metallic_sheen


def solid(size, colour):
    return Image.new("RGBA", size, colour)


def gradient(size):
    """A vertical light-to-dark ramp, standing in for the Pill's shading."""
    width, height = size
    image = Image.new("RGBA", size)
    pixels = image.load()
    for y in range(height):
        value = int(255 * (1 - y / max(1, height - 1)))
        for x in range(width):
            pixels[x, y] = (value, value, value, 255)
    return image


class MetallicSheenTests(unittest.TestCase):
    """The rainbow took the Pill's alpha but not its shading.

    That gave it the Pill's outline with flat colour inside, which is why the
    processing state looked pasted on rather than machined from the same object.
    Carrying the Pill's luminance across as highlight and shadow makes the
    rainbow read as the same piece of metal, lit the same way.
    """

    def test_the_result_keeps_the_rainbow_size(self) -> None:
        out = apply_metallic_sheen(solid((32, 16), (200, 30, 90, 255)), gradient((32, 16)))
        self.assertEqual(out.size, (32, 16))

    def test_the_result_is_rgba(self) -> None:
        out = apply_metallic_sheen(solid((8, 8), (10, 200, 180, 255)), gradient((8, 8)))
        self.assertEqual(out.mode, "RGBA")

    def test_a_lit_area_ends_brighter_than_a_shadowed_one(self) -> None:
        """This is the whole point: the shape must gain form."""
        out = apply_metallic_sheen(solid((4, 32), (120, 60, 200, 255)), gradient((4, 32))).convert("RGB")
        top = sum(out.getpixel((2, 1)))
        bottom = sum(out.getpixel((2, 30)))
        self.assertGreater(top, bottom)

    def test_the_hue_survives(self) -> None:
        """Metal shading must not wash the colour out to grey, or the rainbow
        stops being a rainbow."""
        out = apply_metallic_sheen(solid((16, 16), (220, 20, 40, 255)), gradient((16, 16))).convert("RGB")
        r, g, b = out.getpixel((8, 8))
        self.assertGreater(r, g + 20, "red no longer dominates")
        self.assertGreater(r, b + 20, "red no longer dominates")

    def test_a_flat_grey_sheen_darkens_evenly_without_shifting_the_hue(self) -> None:
        """Flat shading has no highlight to give, so all it should do is deepen.

        This previously asserted the colour came back within 40 of the source,
        from when the sheen was a light finish over the original brightness.
        The surface is deliberately darker now -- metal is a dark body carrying
        a bright highlight, and keeping the body bright is what made the old
        treatment read as a backlit sticker. What still has to hold is that the
        darkening is even: the channels keep their relationship to each other,
        so the colour deepens instead of drifting toward another hue.
        """
        source = (90, 160, 210)
        base = solid((12, 12), (*source, 255))
        out = apply_metallic_sheen(base, solid((12, 12), (128, 128, 128, 255))).convert("RGB")
        result = out.getpixel((6, 6))

        self.assertLess(sum(result), sum(source), "flat shading should deepen the surface")

        # Channel order is the invariant, not equal ratios. A multiply-biased
        # blend is non-linear -- brighter channels lose more than darker ones --
        # so demanding even scaling would be demanding the effect not work.
        # What must not happen is the colour becoming a different colour.
        self.assertEqual(
            sorted(range(3), key=lambda i: result[i]),
            sorted(range(3), key=lambda i: source[i]),
            f"channel order changed: {source} -> {result}, so the hue moved",
        )
        # And it must still be a colour rather than collapsing toward grey.
        self.assertGreater(max(result) - min(result), 30, "washed out to grey")

    def test_mismatched_sizes_are_handled_rather_than_raising(self) -> None:
        """Frame sizes change as the Pill expands; a raise here kills the
        animation mid-transition."""
        out = apply_metallic_sheen(solid((20, 10), (10, 10, 200, 255)), gradient((7, 3)))
        self.assertEqual(out.size, (20, 10))

    def test_a_degenerate_image_does_not_raise(self) -> None:
        for size in ((1, 1), (1, 8), (8, 1)):
            self.assertEqual(apply_metallic_sheen(solid(size, (5, 5, 5, 255)), gradient(size)).size, size)

    def test_transparency_is_preserved(self) -> None:
        base = Image.new("RGBA", (8, 8), (200, 40, 40, 0))
        out = apply_metallic_sheen(base, gradient((8, 8)))
        self.assertEqual(out.getpixel((4, 4))[3], 0)


if __name__ == "__main__":
    unittest.main()
