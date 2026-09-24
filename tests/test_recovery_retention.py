"""A user's configured protected-recording limit also applies at startup."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.audio_spool import list_safety_sessions, recover_interrupted_sessions, save_safety_recording


class RecoveryRetentionTests(unittest.TestCase):
    def test_recovery_uses_the_chosen_limit_with_the_existing_five_session_floor(self):
        for limit, expected in ((10, 7), (5, 5), (1, 5)):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as directory:
                with patch('knight_flow.audio_spool.app_dir', return_value=Path(directory)):
                    for index in range(7):
                        save_safety_recording(b'\x01\x08'*1600, sample_rate=16000,
                                              channels=1, reason='synthetic-'+str(index), limit=10)
                    self.assertEqual(len(list_safety_sessions(20)), 7)
                    self.assertEqual(recover_interrupted_sessions(limit=limit), 0)
                    self.assertEqual(len(list_safety_sessions(20)), expected)


if __name__ == '__main__':
    unittest.main()
