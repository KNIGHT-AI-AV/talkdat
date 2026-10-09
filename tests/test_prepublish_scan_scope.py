"""The existing source scan keeps coverage without traversing generated caches."""
from pathlib import Path
from contextlib import ExitStack
import glob
import os
import tempfile
import unittest
from unittest.mock import patch

from scripts import prepublish_check as scanner


class SourceScanScopeTests(unittest.TestCase):
    def tree(self, root):
        paths = ("app.py", ".env.local", "docs/notes.md", "docs/private.p8", "tmp-leftover.txt",
                 "docs/marketing/research/raw/keep.md", "marketing/research/raw/private.md",
                 ".venv/cache/generated.py", ".venv-dmg/site/example.py", "docs/node_modules/lib/index.js")
        for name in paths:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture content", encoding="utf-8")

    def test_eligible_files_and_secret_file_types_remain_in_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.tree(root)
            with patch.object(scanner, "ROOT", root):
                found = {path.relative_to(root).as_posix() for path in scanner.iter_repo_files()}
            self.assertEqual(found, {"app.py", ".env.local", "docs/notes.md", "docs/private.p8",
                                     "tmp-leftover.txt", "docs/marketing/research/raw/keep.md"})
            self.assertTrue(scanner.is_text_file(root / ".env.local"))
            self.assertTrue(scanner.is_text_file(root / "docs/private.p8"))

    def test_excluded_subtrees_are_never_enumerated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.tree(root)
            visited = []
            actual_scandir = os.scandir
            def track(path):
                visited.append(Path(path).relative_to(root).as_posix())
                return actual_scandir(path)
            with ExitStack() as stack:
                stack.enter_context(patch.object(scanner, "ROOT", root))
                stack.enter_context(patch.object(os, "scandir", side_effect=track))
                # Python 3.13's globber captures scandir as a static method.
                # Observe that path too, rather than letting an empty trace pass.
                if hasattr(glob, "_StringGlobber"):
                    stack.enter_context(patch.object(glob._StringGlobber, "scandir", staticmethod(track)))
                scanner.iter_repo_files()
            self.assertTrue(visited, "The traversal observer must actually see directory reads")
            for directory in visited:
                self.assertFalse(any(part.startswith(".venv") or part in scanner.SKIP_DIRS
                                     for part in Path(directory).parts), directory)
                self.assertFalse(directory.startswith("marketing/research/raw"), directory)


if __name__ == "__main__":
    unittest.main()
