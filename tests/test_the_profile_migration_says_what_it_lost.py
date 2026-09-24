"""X-238: a migration that half-works must not look like one that worked.

Moving from the old profile directory to the new one copies config.json,
history.db and the audio spool -- somebody's settings and everything they have
ever dictated. The copy loop was `except OSError: pass`.

So a locked file, a full disk, or a permissions problem produced an app that
came up looking factory-fresh: no error dialog, no log line, nothing to search
for. "Talk DAT! lost my settings after the update" was an unanswerable support
ticket, because the software genuinely did not know.

The fix is not to make it fail hard. An app that refuses to start because one
file would not copy is worse than one that starts without it. The fix is that
soft must stop meaning silent.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.config import (
    LEGACY_APP_NAME,
    _copy_missing_items,
    _migrate_legacy_app_dir,
    _rename_legacy_root,
)


class TheCopyReportsWhatItCouldNotTakeTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        # The real names matter: _migrate_legacy_app_dir derives the old
        # directory from LEGACY_APP_NAME rather than being handed it.
        self.old = self.root / LEGACY_APP_NAME
        self.new = self.root / "TalkDat"
        self.old.mkdir()
        # And the destination must already exist, or migration takes the
        # rename fast-path and never reaches the copy this file is about.
        self.new.mkdir()
        (self.old / "config.json").write_text('{"theme": "bone"}', encoding="utf-8")
        (self.old / "history.db").write_bytes(b"sqlite-ish")

    def test_a_clean_migration_reports_nothing_lost(self) -> None:
        self.assertEqual(_copy_missing_items(self.old, self.new), [])
        self.assertTrue((self.new / "history.db").exists())
        self.assertEqual((self.new / "config.json").read_text(encoding="utf-8"), '{"theme": "bone"}')

    def test_a_file_that_will_not_copy_is_named(self) -> None:
        real = shutil.copy2

        def refuse(source, destination, *args, **kwargs):
            if Path(source).name == "history.db":
                raise OSError(13, "in use by another process")
            return real(source, destination, *args, **kwargs)

        with patch("knight_flow.config.shutil.copy2", side_effect=refuse):
            failed = _copy_missing_items(self.old, self.new)

        self.assertEqual(failed, ["history.db"])
        self.assertTrue(
            (self.new / "config.json").exists(),
            "one bad file must not abandon the rest of the migration",
        )

    def test_the_failure_reaches_the_log(self) -> None:
        """The point of the whole change. A returned list nobody prints is the
        same silence in a different shape."""
        def refuse(*args, **kwargs):
            raise OSError(28, "no space left on device")

        with patch("knight_flow.config.shutil.copy2", side_effect=refuse):
            with patch("knight_flow.config.shutil.copytree", side_effect=refuse):
                with self.assertLogs("knight_flow.config", level=logging.WARNING) as captured:
                    _migrate_legacy_app_dir(self.root, self.new)

        joined = "\n".join(captured.output)
        self.assertIn("config.json", joined)
        self.assertIn("history.db", joined)

    def test_it_still_starts_when_nothing_can_be_copied(self) -> None:
        """Soft, not silent. An unreadable old profile must not brick the app."""
        def refuse(*args, **kwargs):
            raise OSError(13, "denied")

        with patch("knight_flow.config.shutil.copy2", side_effect=refuse):
            with patch("knight_flow.config.shutil.copytree", side_effect=refuse):
                with self.assertLogs("knight_flow.config", level=logging.WARNING):
                    _migrate_legacy_app_dir(self.root, self.new)  # must not raise

        self.assertTrue(self.new.exists())


class TheOldProfileIsSetAsideTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_the_backup_location_is_returned_so_it_can_be_reported(self) -> None:
        legacy = self.root / "TalkDatShi"
        legacy.mkdir()
        kept = _rename_legacy_root(legacy)
        self.assertIsNotNone(kept)
        self.assertTrue(kept.exists())
        self.assertFalse(legacy.exists())

    def test_a_failed_rename_is_logged_rather_than_shrugged_off(self) -> None:
        """It leaves the person with two profile folders and no idea which one
        is live, and the migration re-runs on every launch."""
        legacy = self.root / "TalkDatShi"
        legacy.mkdir()
        with patch("knight_flow.config.Path.rename", side_effect=OSError(13, "denied")):
            with self.assertLogs("knight_flow.config", level=logging.WARNING) as captured:
                kept = _rename_legacy_root(legacy)
        self.assertIsNone(kept)
        self.assertIn("previous profile", "\n".join(captured.output))
