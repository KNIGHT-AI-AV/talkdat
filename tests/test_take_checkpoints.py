"""T8: a synthetic ten-minute take, interrupted at every stage. Every checkpoint
that reached the disk is recovered as transcribed, the remainder is transcribed
from exactly where the checkpoints end, and no completed span repeats or drops.

The audio is synthetic and so is the engine: each segment's samples carry its
index, and the fake engine "hears" those indexes, so the text of any byte range
is known exactly and a duplicate or a gap would show as a wrong sequence.
"""
from __future__ import annotations

import struct
import unittest

from knight_flow.take_checkpoints import add_checkpoint, resume, resume_plan, verified_checkpoints

RATE = 16000
BYTES_PER_SECOND = RATE * 2
SEGMENT_SECONDS = 6
SEGMENTS = 100  # 100 x 6 s = 10 minutes


def segment_audio(index: int) -> bytes:
    """6 s of one value: index + 1, so every sample says which segment it is."""
    value = index + 1
    return struct.pack("<h", value) * (SEGMENT_SECONDS * RATE)


AUDIO = b"".join(segment_audio(index) for index in range(SEGMENTS))
BOUNDS = [(index * SEGMENT_SECONDS * BYTES_PER_SECOND, (index + 1) * SEGMENT_SECONDS * BYTES_PER_SECOND)
          for index in range(SEGMENTS)]


def hear(pcm: bytes) -> str:
    """The fake engine: one word per distinct segment value present."""
    seen, out = set(), []
    for offset in range(0, len(pcm) - 1, BYTES_PER_SECOND // 4):
        value = struct.unpack_from("<h", pcm, offset)[0]
        if value and value not in seen:
            seen.add(value)
            out.append(f"s{value - 1}")
    return " ".join(out)


FULL = " ".join(f"s{index}" for index in range(SEGMENTS))


def metadata_after(checkpointed: int, *, keep_words: bool = True) -> dict:
    metadata = {"sample_rate": RATE, "channels": 1}
    for index in range(checkpointed):
        start, end = BOUNDS[index]
        metadata = add_checkpoint(metadata, index, start, end, hear(AUDIO[start:end]), keep_words=keep_words)
    return metadata


class EveryInterruption(unittest.TestCase):
    def test_interrupted_after_any_number_of_checkpoints(self):
        for checkpointed in (0, 1, 2, 37, 50, 99, 100):
            with self.subTest(checkpointed=checkpointed):
                plan = resume_plan(metadata_after(checkpointed), len(AUDIO))
                self.assertEqual(len(plan.kept), checkpointed)
                self.assertEqual(resume(plan, AUDIO, hear), FULL)

    def test_audio_cut_short_on_disk(self):
        # The crash came before the last half second reached the disk: the
        # checkpoints past the end of the file are not trusted.
        for cut_segment in (10, 55, 99):
            with self.subTest(cut=cut_segment):
                audio = AUDIO[: BOUNDS[cut_segment][0] + BYTES_PER_SECOND]
                plan = resume_plan(metadata_after(SEGMENTS), len(audio))
                self.assertEqual(len(plan.kept), cut_segment)
                expected = " ".join(f"s{index}" for index in range(cut_segment + 1))
                self.assertEqual(resume(plan, audio, hear), expected)

    def test_only_the_remainder_is_transcribed(self):
        calls = []

        def counting(pcm: bytes) -> str:
            calls.append(len(pcm))
            return hear(pcm)

        plan = resume_plan(metadata_after(90), len(AUDIO))
        resume(plan, AUDIO, counting)
        self.assertEqual(calls, [len(AUDIO) - BOUNDS[89][1]])
        self.assertAlmostEqual(plan.kept_seconds, 540.0)
        self.assertAlmostEqual(plan.remainder_seconds, 60.0)


class WhatIsNotTrusted(unittest.TestCase):
    def test_a_gap_stops_the_run(self):
        metadata = metadata_after(10)
        metadata["checkpoints"] = [item for item in metadata["checkpoints"] if item["index"] != 4]
        plan = resume_plan(metadata, len(AUDIO))
        self.assertEqual(len(plan.kept), 4)
        self.assertEqual(resume(plan, AUDIO, hear), FULL)

    def test_an_overlap_or_a_backwards_range_stops_the_run(self):
        metadata = metadata_after(5)
        metadata["checkpoints"][3]["start"] = metadata["checkpoints"][2]["start"]
        self.assertEqual(len(verified_checkpoints(metadata, len(AUDIO))), 3)
        metadata = metadata_after(5)
        metadata["checkpoints"][1]["end"] = metadata["checkpoints"][1]["start"]
        self.assertEqual(len(verified_checkpoints(metadata, len(AUDIO))), 1)

    def test_a_take_whose_words_are_not_kept(self):
        metadata = metadata_after(20, keep_words=False)
        self.assertTrue(all(item["text"] is None for item in metadata["checkpoints"]))
        plan = resume_plan(metadata, len(AUDIO))
        self.assertEqual(plan.kept, ())
        self.assertEqual(resume(plan, AUDIO, hear), FULL)

    def test_malformed_entries(self):
        metadata = {"checkpoints": [{"index": 0, "start": "x", "end": 1, "text": "a"}, "nope"]}
        self.assertEqual(verified_checkpoints(metadata, 100), [])

    def test_a_repeated_index_replaces_the_earlier_one(self):
        metadata = add_checkpoint({}, 0, 0, 100, "first")
        metadata = add_checkpoint(metadata, 0, 0, 100, "again")
        self.assertEqual([item["text"] for item in metadata["checkpoints"]], ["again"])


if __name__ == "__main__":
    unittest.main()
