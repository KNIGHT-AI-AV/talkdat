"""Install file/vault isolation before unittest discovery imports any tests."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tests  # noqa: E402,F401: installs the scratch profile and in-memory vault

if __name__ == "__main__":
    unittest.main(module=None, argv=[sys.argv[0], *(sys.argv[1:] or ["discover", "-s", "tests"])])
