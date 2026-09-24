from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AppTextScalingProcessMatrixTests(unittest.TestCase):
    def test_real_controls_at_every_supported_scale(self) -> None:
        for scale in (1.0, 1.25, 1.5, 2.0):
            with self.subTest(scale=scale):
                environment = os.environ.copy()
                environment["TALKDAT_TEST_UI_SCALE"] = str(scale)
                result = subprocess.run(
                    [sys.executable, "-m", "unittest", "tests.gui_app_text_scaling", "-v"],
                    cwd=str(ROOT),
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    self.fail(
                        f"app text scaling failed at {scale:.2f}x:\n"
                        f"--- stdout ---\n{result.stdout[-7000:]}\n"
                        f"--- stderr ---\n{result.stderr[-7000:]}"
                    )


if __name__ == "__main__":
    unittest.main()
