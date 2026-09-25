"""The update download pile must not grow forever.

Thirty downloaded installers -- 6.5 GB -- were found parked in the updates
folder of the founder's machine, one per release since July, because nothing
ever deleted them. Each is useful for exactly one hop: the moment a newer
release exists it can never be installed again.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from knight_flow import updater
from knight_flow.version import APP_VERSION


def _older() -> str:
    major, minor, patch = (APP_VERSION.split("-")[0]).split(".")
    return f"{major}.{minor}.{max(0, int(patch) - 1)}-beta"


def _newer() -> str:
    major, minor, patch = (APP_VERSION.split("-")[0]).split(".")
    return f"{major}.{minor}.{int(patch) + 5}-beta"


class PruneStaleInstallersTests(unittest.TestCase):
    def run_prune(self, names: list[str], keep: str | None = None) -> set[str]:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            for name in names:
                (directory / name).write_bytes(b"x")
            with mock.patch.object(updater, "updates_dir", lambda: directory):
                updater.prune_stale_installers(
                    keep=(directory / keep) if keep else None
                )
            return {p.name for p in directory.iterdir()}

    def test_old_installers_are_removed(self) -> None:
        survivors = self.run_prune([
            f"Talk-Dat-Setup-{_older()}.exe",
            "Talk-Dat-Setup-0.3.2-beta.exe",
        ])
        self.assertEqual(survivors, set())

    def test_the_just_downloaded_installer_survives(self) -> None:
        keep = f"Talk-Dat-Setup-{APP_VERSION}.exe"
        survivors = self.run_prune([keep, "Talk-Dat-Setup-0.3.2-beta.exe"], keep=keep)
        self.assertEqual(survivors, {keep})

    def test_a_predownload_newer_than_the_running_version_survives(self) -> None:
        """A future installer is a predownload waiting for its moment."""
        future = f"Talk-Dat-Setup-{_newer()}.exe"
        survivors = self.run_prune([future, "Talk-Dat-Setup-0.3.2-beta.exe"])
        self.assertEqual(survivors, {future})

    def test_part_files_are_always_removed(self) -> None:
        """A crash mid-download is the only way a .part survives; it can never
        be trusted again, whatever version its name claims."""
        survivors = self.run_prune([
            f"Talk-Dat-Setup-{_newer()}.part",
            "Talk-Dat-Setup-0.3.2-beta.part",
        ])
        self.assertEqual(survivors, set())

    def test_the_download_path_prunes_after_success(self) -> None:
        source = (Path(updater.__file__)).read_text(encoding="utf-8")
        download = source[source.index("def download_installer"):source.index("def launch_installer")]
        self.assertIn("prune_stale_installers(keep=destination)", download)

    def test_startup_prunes_too(self) -> None:
        app_source = (Path(updater.__file__).parent / "app.py").read_text(encoding="utf-8")
        self.assertIn("prune_stale_installers()", app_source)


if __name__ == "__main__":
    unittest.main()



class StoreCopyNeverSelfUpdatesTests(unittest.TestCase):
    """X-116, Store policy 10.2.5 -- the certification failure. A copy with
    package identity must never download our installer; its updates belong
    to the Store."""

    def test_running_from_store_answers_without_crashing(self) -> None:
        from knight_flow.updater import running_from_store

        self.assertIn(running_from_store(), (True, False))

    def test_a_store_copy_routes_the_manual_check_to_the_store(self) -> None:
        import contextlib as _ctx
        import threading
        from unittest import mock

        from knight_flow.app import TalkDatApp

        app = TalkDatApp.__new__(TalkDatApp)
        app.update_lock = threading.Lock()
        app.update_in_progress = False
        states = []

        class Overlay:
            def set_state(self, *args, **_kwargs):
                states.append(args)

        app.overlay = Overlay()
        with mock.patch("knight_flow.updater.running_from_store", return_value=True), \
             mock.patch("knight_flow.app.webbrowser.open") as opened:
            app.check_updates(silent=False)
        self.assertTrue(opened.called, "the manual check must open the Store page")
        self.assertTrue(any("Store" in str(s) for s in states))

    def test_a_store_copy_background_check_stands_down_silently(self) -> None:
        import threading
        from unittest import mock

        from knight_flow.app import TalkDatApp

        app = TalkDatApp.__new__(TalkDatApp)
        app.update_lock = threading.Lock()
        app.update_in_progress = False
        with mock.patch("knight_flow.updater.running_from_store", return_value=True), \
             mock.patch("knight_flow.app.webbrowser.open") as opened, \
             mock.patch("knight_flow.updater.check_for_update") as checked:
            app.check_updates(silent=True)
        self.assertFalse(opened.called)
        self.assertFalse(checked.called)
