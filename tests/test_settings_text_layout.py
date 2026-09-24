"""Run Settings text-layout contracts at every supported application scale."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SettingsTextLayoutProcessMatrixTests(unittest.TestCase):
    def test_real_settings_footer_and_constrained_tooltip_layout(self) -> None:
        for scale in (1.0, 1.25, 1.5, 2.0):
            with self.subTest(scale=scale):
                environment = os.environ.copy()
                environment["TALKDAT_TEST_UI_SCALE"] = str(scale)
                result = subprocess.run(
                    [sys.executable, "-m", "unittest", "tests.gui_settings_text_layout", "-v"],
                    cwd=str(ROOT),
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if result.returncode != 0:
                    self.fail(
                        f"Settings text layout failed at {scale:.2f}x:\n"
                        f"--- stdout ---\n{result.stdout[-9000:]}\n"
                        f"--- stderr ---\n{result.stderr[-9000:]}"
                    )


if __name__ == "__main__":
    unittest.main()
