"""X-535: an update install must answer, or say why it cannot.

The founder asked for 0.4.143 at 22:08:20 and the app quit twelve seconds
later with 382 MB of a 487 MB installer parked as a `.part`. Nothing was
installed, nothing was logged, and the app never came back -- it sat closed
and two versions stale for twelve hours until the next scan found it.

The check worker already learned this lesson. `check_for_update`'s thread
catches `Exception` and says so, because a bare `UpdateError` catch "used to
kill this thread SILENTLY -- no log line, no message, indistinguishable from
the button doing nothing". Its sibling `install_update` never got the same
treatment: it still catches only `UpdateError`, so anything else -- an
`http.client.IncompleteRead` on a truncated 487 MB body is the realistic one,
and it is neither a `URLError` nor an `OSError`, so `download_installer` does
not convert it -- kills the worker before `on_done` is ever called. The update
window then sits on "Downloading update..." forever.

These tests pin the contract: whatever happens, the install worker calls
`on_done` exactly once and writes a line naming the failure.
"""

from __future__ import annotations

import http.client
import logging
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from knight_flow import updater
from knight_flow.app import TalkDatApp


class _Info:
    """The fields install_update reads off an UpdateInfo."""

    latest_version = "9.9.9-beta"
    installer_sha256 = "0" * 64
    installer_size = 487789224
    artifact_signing_enabled = False


class _Answer:
    """Records the on_done call and lets the test wait for it."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.calls: list[tuple[bool, str]] = []

    def __call__(self, ok: bool, message: str) -> None:
        self.calls.append((bool(ok), str(message)))
        self.done.set()

    def wait(self, timeout: float = 5.0) -> bool:
        return self.done.wait(timeout)


def _app() -> TalkDatApp:
    app = TalkDatApp.__new__(TalkDatApp)
    app.config = {}
    return app


class UpdateInstallAlwaysAnswersTests(unittest.TestCase):
    def _run_install(self, app: TalkDatApp, predownloaded: Path | None) -> _Answer:
        answer = _Answer()
        app.install_update(
            _Info(),
            predownloaded,
            lambda *_args: None,   # set_progress
            lambda *_args: None,   # set_status
            answer,
        )
        return answer

    def test_a_truncated_download_still_answers(self) -> None:
        """IncompleteRead is not an OSError, so nothing converts it to
        UpdateError. Before the fix the worker died here and the window sat
        on "Downloading update..." with no error and no log line."""
        def truncated(*_args, **_kwargs):
            raise http.client.IncompleteRead(b"", 105583272)

        with mock.patch("knight_flow.app.download_installer", truncated):
            with self.assertLogs("knight_flow.app", level="WARNING") as logs:
                answer = self._run_install(_app(), None)
                self.assertTrue(
                    answer.wait(),
                    "install_update never called on_done -- the update window is stuck",
                )

        self.assertEqual(len(answer.calls), 1)
        ok, message = answer.calls[0]
        self.assertFalse(ok)
        self.assertTrue(message.strip(), "a failed install must say something")
        self.assertTrue(
            any("update install" in line.lower() for line in logs.output),
            f"the failure must leave a trail, got {logs.output}",
        )

    def test_an_unexpected_launch_failure_still_answers(self) -> None:
        """The handoff is the other half. A non-UpdateError out of
        launch_installer stranded the window in exactly the same way."""
        def boom(*_args, **_kwargs):
            raise RuntimeError("handoff exploded")

        with TemporaryDirectory() as raw:
            installer = Path(raw) / "Talk-Dat-Setup-9.9.9-beta.exe"
            installer.write_bytes(b"x")
            with mock.patch("knight_flow.app.launch_installer", boom), \
                 mock.patch("knight_flow.app.save_config", lambda *_a, **_k: None):
                with self.assertLogs("knight_flow.app", level="WARNING"):
                    answer = self._run_install(_app(), installer)
                    self.assertTrue(
                        answer.wait(),
                        "install_update never called on_done after a launch failure",
                    )

        self.assertEqual(len(answer.calls), 1)
        self.assertFalse(answer.calls[0][0])

    def test_an_update_error_keeps_its_own_message(self) -> None:
        """Widening the catch must not blunt the errors we already word well:
        an UpdateError still reaches the user verbatim."""
        def refused(*_args, **_kwargs):
            raise updater.UpdateError("No SHA256 checksum was published.")

        with mock.patch("knight_flow.app.download_installer", refused):
            with self.assertLogs("knight_flow.app", level="WARNING"):
                answer = self._run_install(_app(), None)
                self.assertTrue(answer.wait())

        self.assertEqual(
            answer.calls, [(False, "No SHA256 checksum was published.")]
        )


class InterruptedDownloadLeavesATrailTests(unittest.TestCase):
    """The other half of the twelve silent hours.

    The worker is a daemon thread, so when the app quits mid-download CPython
    tears it down without unwinding: no `except`, no `finally`, no log line.
    The `.part` on disk is the only evidence the download ever happened, and
    `prune_stale_installers` used to fold it into a bare "pruned 1 stale update
    installer(s)" -- indistinguishable from sweeping up an old `.exe`. The next
    launch is the only place this can still be reported, so it must say so.
    """

    def test_a_part_file_is_reported_as_an_interrupted_download(self) -> None:
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            part = directory / "Talk-Dat-Setup-0.4.143-beta.part"
            part.write_bytes(b"x" * 4096)
            with mock.patch.object(updater, "updates_dir", lambda: directory):
                with self.assertLogs(updater.log, level="INFO") as logs:
                    updater.prune_stale_installers()

        blob = "\n".join(logs.output)
        self.assertIn("0.4.143-beta", blob, f"the version must be named, got {blob}")
        self.assertIn(
            "interrupted", blob.lower(),
            f"a half-downloaded update must be reported as interrupted, got {blob}",
        )

    def test_a_plain_stale_installer_is_not_called_interrupted(self) -> None:
        """Sweeping up a spent .exe is housekeeping, not a failed update."""
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            (directory / "Talk-Dat-Setup-0.3.2-beta.exe").write_bytes(b"x")
            with mock.patch.object(updater, "updates_dir", lambda: directory):
                with self.assertLogs(updater.log, level="INFO") as logs:
                    updater.prune_stale_installers()

        self.assertNotIn("interrupted", "\n".join(logs.output).lower())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    unittest.main()
