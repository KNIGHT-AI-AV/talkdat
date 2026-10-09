from pathlib import Path
import subprocess
import unittest

class StatsDisclosureTests(unittest.TestCase):
    def test_refresh_retains_the_persons_disclosure_choice(self):
        result = subprocess.run(['node', str(Path(__file__).with_name('stats_disclosure_check.mjs'))],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == '__main__':
    unittest.main()
