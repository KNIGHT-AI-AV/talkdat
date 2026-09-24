import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from knight_flow import logger

class LogRetentionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='talkdat-log-proof-')
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.root = logging.RootLogger(logging.WARNING)
        for target, name, value in (
            (logging, 'root', self.root), (logger, 'app_dir', lambda: self.folder),
            (logger, 'MAX_LOG_BYTES', 1024), (logger, 'MAX_LOG_BACKUPS', 3),
            (logger, 'MAX_RECORD_BYTES', 256),
        ):
            guard = patch.object(target, name, value, create=True)
            guard.start()
            self.addCleanup(guard.stop)
        self.addCleanup(self.close)

    def close(self):
        for handler in self.root.handlers[:]:
            self.root.removeHandler(handler)
            handler.close()

    def managed(self):
        for handler in self.root.handlers:
            handler.flush()
        return sorted(self.folder.glob('talk-dat.log*'))

    def assert_bounded(self):
        files = self.managed()
        self.assertTrue(files)
        self.assertLessEqual(len(files), 4)
        for path in files:
            self.assertLessEqual(path.stat().st_size, 1024, path.name)
            path.read_text(encoding='utf-8')

    def test_many_records_rotate_and_keep_the_newest(self):
        logger.configure_logging()
        for number in range(90):
            self.root.info('event %03d %s', number, 'x' * 70)
        self.assert_bounded()
        self.assertIn('event 089', (self.folder/'talk-dat.log').read_text())
        self.assertGreater(len(self.managed()), 1)

    def test_multibyte_records_obey_byte_limit(self):
        logger.configure_logging()
        for number in range(50):
            self.root.info('event %s %s', number, '\u4e16\u754c\U0001f680' * 30)
        self.assert_bounded()

    def test_single_large_record_is_bounded_and_marked(self):
        logger.configure_logging()
        self.root.error('start %s', 'x' * 20000)
        self.assert_bounded()
        self.assertIn('[log entry truncated]', (self.folder/'talk-dat.log').read_text())

    def test_existing_oversized_logs_keep_recent_tail(self):
        for suffix in ('', '.1', '.2', '.3'):
            (self.folder/('talk-dat.log'+suffix)).write_text('old\n' * 1000 + 'recent marker\n', encoding='utf-8')
        logger.configure_logging()
        self.assert_bounded()
        for path in self.managed():
            self.assertIn('recent marker', path.read_text())

    def test_existing_root_handler_does_not_disable_file_logging(self):
        foreign = logging.NullHandler()
        self.root.addHandler(foreign)
        logger.configure_logging()
        self.root.info('still logged')
        self.assertIn(foreign, self.root.handlers)
        self.assertIn('still logged', (self.folder/'talk-dat.log').read_text())

    def test_reconfiguration_does_not_duplicate_records(self):
        logger.configure_logging()
        logger.configure_logging()
        self.root.info('once only')
        self.assertEqual((self.folder/'talk-dat.log').read_text().count('once only'), 1)

    def test_unwritable_log_does_not_abort_startup(self):
        (self.folder/'talk-dat.log').mkdir()
        logger.configure_logging()
        self.assertTrue((self.folder/'talk-dat.log').is_dir())

    def test_unrelated_files_are_never_trimmed(self):
        other = self.folder/'talk-dat.log.export.txt'
        other.write_text('keep' * 1000)
        logger.configure_logging()
        self.root.info('normal')
        self.assertEqual(other.read_text(), 'keep' * 1000)

    def test_failed_legacy_replacement_preserves_original(self):
        path = self.folder/'talk-dat.log'
        original = b'old\n' * 1000
        path.write_bytes(original)
        with patch('os.replace', side_effect=OSError('fixture')):
            logger.configure_logging()
        self.assertEqual(path.read_bytes(), original)

    def test_logging_invalid_unicode_keeps_a_readable_log(self):
        logger.configure_logging()
        self.root.info('invalid surrogate %s', '\ud800')
        self.assertIn('invalid surrogate', (self.folder/'talk-dat.log').read_text(encoding='utf-8'))

    def test_linked_diagnostic_file_does_not_touch_its_other_name(self):
        original = self.folder/'outside.txt'
        original.write_bytes(b'keep\n' * 1000)
        os.link(original, self.folder/'talk-dat.log')
        self.assertFalse(logger.configure_logging())
        self.assertEqual(original.read_bytes(), b'keep\n' * 1000)

    def test_rotation_failure_does_not_raise_or_print_the_record(self):
        logger.configure_logging()
        self.root.info('first %s', 'a' * 150)
        handler = self.root.handlers[0]
        with patch.object(handler, 'doRollover', side_effect=OSError('fixture')):
            with patch.object(sys, 'stderr') as stderr:
                for _ in range(12):
                    self.root.info('private synthetic fixture %s', 'b' * 150)
                stderr.write.assert_not_called()
        self.assertTrue(handler.write_failed)
        self.assert_bounded()

    def test_formatted_exception_is_also_bounded(self):
        logger.configure_logging()
        try:
            raise ValueError('fixture ' + 'x' * 20000)
        except ValueError:
            self.root.exception('operation failed')
        self.assert_bounded()
        self.assertIn('[log entry truncated]', (self.folder/'talk-dat.log').read_text())

    def test_concurrent_writers_keep_the_file_budget(self):
        logger.configure_logging()
        def write():
            for number in range(100):
                self.root.info('worker %s %s', number, '\u4e16' * 60)
        workers = [threading.Thread(target=write) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(5)
            self.assertFalse(worker.is_alive())
        self.assert_bounded()


if __name__ == '__main__':
    unittest.main()
