"""The suite gives its own plugin workers room to start (2026-10-25).

A plugin's worker in this suite starts through tests/child_isolation.py, so it
imports the test package (the device guard, the audio stand-in) before the
plugin's code runs. Measured on the PC, interpreter start plus import, warm and
cold: the product's worker (knight_flow.plugin_worker) 0.15 s and 1.2 s, the
suite's (tests.child_isolation) 0.5 s and 1.8 s. The product allows 1.0 s per
plugin and 2.0 s in all, so under load the suite's workers missed it and their
loads never registered: the 0.4.175 full-suite runs logged plugin-host FAILs
(X-720 r6: 8, r10d: 2) and a two-module diagnostic run a third, each time a
different test. So the suite gives its workers room, and the tests that measure
the load budget itself run with the product's values.
"""

from __future__ import annotations

import unittest

from knight_flow import plugins
from tests import child_isolation


class TheSuitesPluginWorkersGetRoomTests(unittest.TestCase):
    def test_the_product_budget_is_unchanged(self) -> None:
        self.assertEqual(
            (child_isolation.PRODUCT_LOAD_SECONDS, child_isolation.PRODUCT_TOTAL_LOAD_SECONDS),
            (1.0, 2.0),
        )

    def test_the_suite_gives_its_workers_room(self) -> None:
        self.assertEqual(plugins.LOAD_SECONDS, child_isolation.SUITE_LOAD_SECONDS)
        self.assertEqual(plugins.TOTAL_LOAD_SECONDS, child_isolation.SUITE_TOTAL_LOAD_SECONDS)
        self.assertGreaterEqual(child_isolation.SUITE_LOAD_SECONDS, 10 * child_isolation.PRODUCT_LOAD_SECONDS)

    def test_the_budget_tests_get_the_product_values_back(self) -> None:
        with child_isolation.product_budget():
            self.assertEqual((plugins.LOAD_SECONDS, plugins.TOTAL_LOAD_SECONDS), (1.0, 2.0))
        self.assertEqual(plugins.LOAD_SECONDS, child_isolation.SUITE_LOAD_SECONDS)


if __name__ == "__main__":
    unittest.main()
