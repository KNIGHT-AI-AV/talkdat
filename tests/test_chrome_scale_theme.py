"""Run universal chrome and focus-paint regressions at supported scales."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ChromeScaleAndThemeProcessMatrixTests(unittest.TestCase):
    def test_real_chrome_and_theme_repaint_at_every_scale(self) -> None:
        for scale in (1.0, 1.25, 1.5, 2.0):
            with self.subTest(scale=scale):
                environment = os.environ.copy()
                environment["TALKDAT_TEST_UI_SCALE"] = str(scale)
                result = subprocess.run(
                    [sys.executable, "-m", "unittest", "tests.gui_chrome_scale_theme", "-v"],
                    cwd=str(ROOT),
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if result.returncode != 0:
                    self.fail(
                        f"universal chrome/theme repaint failed at {scale:.2f}x:\n"
                        f"--- stdout ---\n{result.stdout[-9000:]}\n"
                        f"--- stderr ---\n{result.stderr[-9000:]}"
                    )


if __name__ == "__main__":
    unittest.main()
