from __future__ import annotations

import unittest

from knight_flow.pill_motion import apply_menu_order


class TheMenuStaysTheWayYouLeftItTests(unittest.TestCase):
    """X-06. Mayowa's rule: a reordered menu survives updates, and an update
    that ADDS an item slots the newcomer at its default position without
    disturbing the user's arrangement."""

    DEFAULT = ["restart", "close", "paste", "words", "history", "settings"]

    def test_a_full_saved_order_wins_outright(self) -> None:
        saved = ["paste", "history", "words", "settings", "restart", "close"]
        self.assertEqual(apply_menu_order(self.DEFAULT, saved), saved)

    def test_a_new_item_keeps_its_default_slot(self) -> None:
        """The user ordered five items; the update added 'stats' at default
        position 4. Their five keep their arrangement; stats sits where the
        default puts it."""
        default = ["restart", "close", "paste", "words", "stats", "history"]
        saved = ["paste", "history", "words", "restart", "close"]
        result = apply_menu_order(default, saved)
        self.assertEqual(result.index("stats"), 4)
        self.assertEqual(
            [item for item in result if item != "stats"],
            saved,
        )

    def test_saved_ids_that_no_longer_exist_are_ignored(self) -> None:
        saved = ["ghost_item", "paste", "restart"]
        result = apply_menu_order(self.DEFAULT, saved)
        self.assertNotIn("ghost_item", result)
        self.assertEqual(sorted(result), sorted(self.DEFAULT))
        self.assertEqual(result.index("paste"), 0)

    def test_an_empty_or_junk_save_leaves_the_default_alone(self) -> None:
        self.assertEqual(apply_menu_order(self.DEFAULT, []), self.DEFAULT)
        self.assertEqual(apply_menu_order(self.DEFAULT, ["nope"]), self.DEFAULT)

    def test_every_item_appears_exactly_once(self) -> None:
        saved = ["history", "paste"]
        result = apply_menu_order(self.DEFAULT, saved)
        self.assertEqual(sorted(result), sorted(self.DEFAULT))


if __name__ == "__main__":
    unittest.main()
