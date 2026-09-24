"""Run the update transaction proof in a clean native-Tk process."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


def function_source(name: str) -> str:
    source = OVERLAY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {name}, found {len(matches)}")
    return ast.get_source_segment(source, matches[0]) or ""


class UpdateWindowTransactionHarnessTests(unittest.TestCase):
    def test_busy_reentrant_open_keeps_the_transaction_owner(self) -> None:
        block = function_source("open_update_window")
        start = block.index('existing = self.utility_windows.get("update")')
        end = block.index('window = self._utility_window(', start)
        reentry = block[start:end]

        self.assertIn('getattr(existing, "_close_locked"', reentry)
        self.assertIn('getattr(existing, "_navigation_locked"', reentry)
        self.assertIn('self._focus_utility_window("update")', reentry)
        self.assertIn("self._request_utility_close(", reentry)
        self.assertLess(
            reentry.index("return"),
            reentry.index("self._request_utility_close("),
            "the busy transaction must return before the replaceable-window close path",
        )

    def test_real_tk_update_transaction_contract(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        completed = subprocess.run(
            [sys.executable, "-m", "tests.gui_update_window_transaction"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
