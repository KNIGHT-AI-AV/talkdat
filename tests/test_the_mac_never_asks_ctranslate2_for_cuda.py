"""X-451: CTranslate2 has no Metal backend, so on a Mac a "gpu" request could
only mean CUDA, which fails with a traceback in the log at every warm before
the CPU fallback runs. His Mac's log, 2026-09-04 20:14: "This CTranslate2
package was not compiled with CUDA support". The device is chosen with the
platform in hand now."""
from __future__ import annotations

import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "knight_flow" / "local_stt.py").read_text(encoding="utf-8")


class TheMacNeverAsksCTranslate2ForCuda(unittest.TestCase):
    def test_the_device_choice_knows_the_platform(self) -> None:
        self.assertIn('device = "cuda" if gpu and sys.platform != "darwin" else "cpu"', SOURCE)
        self.assertNotIn('device = "cuda" if gpu else "cpu"', SOURCE)


if __name__ == "__main__":
    unittest.main()
