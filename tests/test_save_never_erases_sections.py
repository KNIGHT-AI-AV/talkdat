from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class SaveNeverErasesUnknownSectionsTests(unittest.TestCase):
    """X-140. The founder's diagnostics flag vanished twice: a process whose
    in-memory config predated an external file edit flushed over it. A save
    now carries forward any top-level section it never loaded; sections the
    caller holds are written exactly as held. config_path is mocked directly
    so the test says the same thing on Windows and the Mac port."""

    def _path(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        return tmp / "config.json"

    def test_a_stale_save_keeps_the_section_it_never_loaded(self) -> None:
        path = self._path()
        path.write_text(json.dumps({
            "diagnostics": {"formatting_journal": True},
            "cleanup": {"format_intensity": "executive"},
        }), encoding="utf-8")
        with mock.patch("knight_flow.config.config_path", return_value=path):
            from knight_flow.config import save_config

            save_config({"cleanup": {"format_intensity": "standard"}})
        on_disk = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertEqual(on_disk["diagnostics"], {"formatting_journal": True})
        self.assertEqual(on_disk["cleanup"], {"format_intensity": "standard"})

    def test_a_held_section_is_written_as_held(self) -> None:
        path = self._path()
        path.write_text(json.dumps({"diagnostics": {"formatting_journal": True}}), encoding="utf-8")
        with mock.patch("knight_flow.config.config_path", return_value=path):
            from knight_flow.config import save_config

            save_config({"diagnostics": {"formatting_journal": False}})
        on_disk = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertEqual(on_disk["diagnostics"], {"formatting_journal": False})

    def test_a_corrupt_file_does_not_block_the_save(self) -> None:
        path = self._path()
        path.write_text("{not json", encoding="utf-8")
        with mock.patch("knight_flow.config.config_path", return_value=path):
            from knight_flow.config import save_config

            save_config({"cleanup": {"format_intensity": "executive"}})
        on_disk = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertEqual(on_disk["cleanup"], {"format_intensity": "executive"})


if __name__ == "__main__":
    unittest.main()
