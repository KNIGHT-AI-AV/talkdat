from __future__ import annotations

import unittest

from knight_flow.style_profile import LEDGER_CAP, observe, render_instruction


class ItLearnsYourVoiceQuietlyTests(unittest.TestCase):
    """X-39. Votes, not prose: nothing the user said is stored beyond counts
    and one-word habits, and no instruction renders until the evidence is
    real. A wrong style line is worse than none -- it produces parody."""

    def test_under_twenty_votes_renders_nothing(self) -> None:
        profile: dict = {}
        for _ in range(19):
            observe(profile, "hey there, it's done and I'm happy with it today")
        self.assertEqual(render_instruction(profile), "")

    def test_a_contraction_heavy_writer_is_described(self) -> None:
        profile: dict = {}
        for _ in range(25):
            observe(profile, "hey team, it's ready and I'm sure we're good to ship it")
        line = render_instruction(profile)
        self.assertIn("contractions", line)
        self.assertIn('opens with "hey"', line)
        self.assertTrue(line.startswith("Match this writer's own voice:"))

    def test_short_sentence_writers_are_described(self) -> None:
        profile: dict = {}
        for _ in range(25):
            observe(profile, "Ship it now. Keep it small. Tell the team today.")
        self.assertIn("short and punchy", render_instruction(profile))

    def test_tiny_fragments_never_vote(self) -> None:
        profile: dict = {}
        observe(profile, "ok")
        self.assertEqual(profile, {})

    def test_the_ledger_halves_so_a_style_change_can_win(self) -> None:
        profile: dict = {}
        for _ in range(LEDGER_CAP):
            observe(profile, "hey there, it's done and I'm happy with it now")
        self.assertLess(profile["votes"], LEDGER_CAP)

    def test_no_prose_is_ever_stored(self) -> None:
        """The X-37 fence: counts and single-word habits only."""
        profile: dict = {}
        private_prose = "hey the wire code for the deal is nine nine eight two today"
        for _ in range(30):
            observe(profile, private_prose)
        import json

        flat = json.dumps(profile).lower()
        for word in ("wire", "code", "deal", "nine", "eight"):
            self.assertNotIn(word, flat)


if __name__ == "__main__":
    unittest.main()
