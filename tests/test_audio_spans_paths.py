"""T9: the fast (numpy) and plain measures agree, so a build without numpy
reports the same spans."""
from __future__ import annotations

import math
import random
import struct
import unittest

from knight_flow.audio_spans import _chunks_numpy, _chunks_plain


class BothPathsAgree(unittest.TestCase):
    def test_the_same_numbers(self):
        rng = random.Random(7)
        samples = [int(max(-1.0, min(1.0, 0.3 * math.sin(i / 7.0) + rng.uniform(-0.05, 0.05))) * 32767)
                   for i in range(16000 * 3)]
        samples[8000:8400] = [32767] * 400
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        fast, plain = _chunks_numpy(pcm, 16000, 1), _chunks_plain(pcm, 16000, 1)
        self.assertEqual(len(fast), len(plain))
        for (fast_rms, fast_clip), (plain_rms, plain_clip) in zip(fast, plain):
            self.assertAlmostEqual(fast_rms, plain_rms, places=9)
            self.assertAlmostEqual(fast_clip, plain_clip, places=12)

    def test_an_odd_byte_and_an_empty_take(self):
        self.assertEqual(_chunks_numpy(b"\x01", 16000, 1), _chunks_plain(b"\x01", 16000, 1))
        self.assertEqual(_chunks_numpy(b"", 16000, 1), [])


if __name__ == "__main__":
    unittest.main()
