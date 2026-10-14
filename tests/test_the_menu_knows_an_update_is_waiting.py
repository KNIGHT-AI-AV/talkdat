"""The Pill menu says an update is waiting, from the check that already ran.

The owner, 2026-10-09: "I couldn't find the update button... When there's an
active update, it should probably appear somewhere obvious in the menu and also
on the pill when you right-click it." Updating from the menu took four clicks
(right-click, App controls, Check for updates, Install now), and the web menu
did not know an update was waiting at all.

Overwatch's rule for this: only the EXISTING update check, no new endpoints or
network calls, and never claim an update the check did not confirm. So the menu
reads `app.pending_update`, which app.check_updates sets only after it found a
newer release and clears when it finds none, and its row installs THAT release.
The Pill's dot is cleared when the check finds nothing or the person skips the
version; before this nothing ever cleared it during a session.
"""
from __future__ import annotations

import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.overlay import Overlay
from knight_flow.web_shell.shell_app import AppShell

ASSETS = Path(__file__).resolve().parents[1] / "knight_flow" / "web_shell" / "shell_assets"


class Inline:
    """threading.Thread that runs its target on start(), so the check finishes in the test."""

    def __init__(self, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()


def make_shell(pending=None, skip=""):
    overlay = Mock()
    overlay._settings_palette = object.__new__(Overlay)._settings_palette
    rows = object.__new__(Overlay)._context_menu_default_rows()
    overlay._context_menu_rows.return_value = rows
    overlay._context_menu_default_rows.return_value = rows
    overlay._context_menu_access_rows.return_value = rows
    overlay._context_menu_feature_rows.return_value = []
    overlay.MENU_SAFETY_ZONE_ACTIONS = Overlay.MENU_SAFETY_ZONE_ACTIONS
    app = Mock()
    app.config = copy.deepcopy(DEFAULT_CONFIG)
    app.config.setdefault("updates", {})["skip_version"] = skip
    app.overlay = overlay
    app.pending_update = pending
    shell = AppShell(app, assets=ASSETS, controller_factory=lambda *args, **kwargs: Mock())
    return app, shell


class TheMenuSeesTheUpdateTests(unittest.TestCase):
    def test_a_found_release_reaches_the_menu(self):
        _app, shell = make_shell(SimpleNamespace(latest_version="0.4.171-beta", forced=False))
        self.assertEqual(shell.backend.snapshot()["update"],
                         {"version": "0.4.171-beta", "required": False, "skipped": False})

    def test_no_release_found_means_no_update_row(self):
        _app, shell = make_shell(None)
        self.assertIsNone(shell.backend.snapshot()["update"])

    def test_the_version_a_check_saw_is_not_a_release_waiting(self):
        # Review M10 (2026-10-10): a check that finds nothing still saves the version it
        # saw as updates.latest_version, which is this very version. Only the release
        # the check confirmed (pending_update) is a row; the saved value never is.
        app, shell = make_shell(None)
        app.config["updates"].update(latest_version="0.4.170-beta", latest_release_url="https://example.invalid/r")
        self.assertIsNone(shell.backend.snapshot()["update"])

    def test_a_required_release_is_marked(self):
        _app, shell = make_shell(SimpleNamespace(latest_version="0.4.171-beta", forced=True))
        self.assertTrue(shell.backend.snapshot()["update"]["required"])

    def test_a_skipped_version_is_marked(self):
        _app, shell = make_shell(SimpleNamespace(latest_version="0.4.171-beta", forced=False), skip="0.4.171-beta")
        self.assertTrue(shell.backend.snapshot()["update"]["skipped"])

    def test_only_a_real_version_is_an_update(self):
        # A version that is not text is not a release the check confirmed: the row
        # must never read "Update to <object>" or claim a required update.
        for odd in (Mock(), 171, b"0.4.171", "   "):
            with self.subTest(version=odd):
                _app, shell = make_shell(SimpleNamespace(latest_version=odd, forced=True))
                self.assertIsNone(shell.backend.snapshot()["update"])

    def offer_on_home(self, app, shell, *, checksum=True):
        """What App.install_or_check_update does with a pending release: offer it on Home."""
        started = []

        def offer():
            shell.update_offer.offer({"current_version": "0.4.170", "latest_version": "0.4.171-beta",
                                      "has_installer": True, "has_checksum": checksum},
                                     lambda progress, status, done: started.append(True), lambda: None)

        app.install_or_check_update.side_effect = offer
        return started

    def test_install_on_the_menu_installs_in_one_click(self):
        # The row's button says Install; it starts the app's own verified install,
        # whose progress Home shows. Before, it only opened the offer, and the person
        # had to press Install a second time.
        app, shell = make_shell(SimpleNamespace(latest_version="0.4.171-beta", forced=False))
        started = self.offer_on_home(app, shell)
        shell.backend.handle("action", {"name": "menu:install_update"})
        self.assertEqual(started, [True])
        self.assertEqual(shell.update_offer.snapshot()["phase"], "installing")

    def test_a_release_that_cannot_be_verified_is_shown_not_installed(self):
        app, shell = make_shell(SimpleNamespace(latest_version="0.4.171-beta", forced=False))
        started = self.offer_on_home(app, shell, checksum=False)
        shell.backend.handle("action", {"name": "menu:install_update"})
        self.assertEqual(started, [])
        self.assertEqual(shell.update_offer.snapshot()["phase"], "blocked")

    def test_with_no_release_waiting_the_menu_starts_no_check(self):
        app, shell = make_shell(None)
        shell.backend.handle("action", {"name": "menu:install_update"})
        app.install_or_check_update.assert_not_called()
        app.check_updates.assert_not_called()

    def test_a_stale_install_row_is_answered_on_the_pill(self):
        # Review B9 (2026-10-10): Install on a row from an older view, after the release
        # stopped waiting. The menu closes on every action, so "No update is waiting."
        # returned to the page was never seen; the Pill says it instead.
        app, shell = make_shell(None)
        app._cross_thread_calls = SimpleNamespace(put=lambda work: work())
        shell.backend.handle("action", {"name": "menu:install_update"})
        app.overlay.set_state.assert_called_once_with("captured", "No update is waiting.", "")

    def test_install_uses_the_release_the_check_found(self):
        app, shell = make_shell(SimpleNamespace(latest_version="0.4.171-beta", forced=False))
        with patch("knight_flow.updater.check_for_update", side_effect=AssertionError("no new network call")):
            shell.backend.handle("action", {"name": "menu:install_update"})
        app.install_or_check_update.assert_called_once_with()
        # Review M11 (2026-10-10): nor a second check through the app on the way.
        app.check_updates.assert_not_called()


class TheDotClearsTests(unittest.TestCase):
    def app(self):
        from knight_flow.app import TalkDatApp

        app = TalkDatApp.__new__(TalkDatApp)
        app.config = {"updates": {"channel": "stable"}}
        app.overlay = SimpleNamespace(root=SimpleNamespace(after=lambda _delay, fn: fn()),
                                      set_update_flag=Mock(), set_state=Mock(), flag=Mock())
        app.tray = SimpleNamespace(set_update_available=Mock())
        app.pending_update = SimpleNamespace(latest_version="0.4.171-beta", forced=False)
        app.update_in_progress = False
        import threading

        app.update_lock = threading.Lock()
        return app

    def test_up_to_date_clears_the_dot(self):
        app = self.app()
        current = SimpleNamespace(available=False, latest_version="0.4.170-beta", release_url="", forced=False)
        with patch("knight_flow.app.check_for_update", return_value=current), \
             patch("knight_flow.app.save_config"), \
             patch("knight_flow.app.running_from_store", return_value=False, create=True), \
             patch("knight_flow.updater.running_from_store", return_value=False), \
             patch("knight_flow.app.threading.Thread", Inline):
            app.check_updates(silent=True)
        self.assertIsNone(app.pending_update)
        app.overlay.set_update_flag.assert_called_with("")

    def test_a_failed_check_keeps_the_dot_and_the_release(self):
        # Review M08 (2026-10-10): a check that never reached the server learned nothing,
        # so the release an earlier check found is still waiting and the dot stays lit.
        from knight_flow.updater import UpdateError

        for failure in (UpdateError("GitHub could not be reached."), OSError("the network is down")):
            with self.subTest(failure=type(failure).__name__):
                app = self.app()
                waiting = app.pending_update
                with patch("knight_flow.app.check_for_update", side_effect=failure), \
                     patch("knight_flow.app.save_config"), \
                     patch("knight_flow.updater.running_from_store", return_value=False), \
                     patch("knight_flow.app.threading.Thread", Inline):
                    app.check_updates(silent=True)
                self.assertIs(app.pending_update, waiting)
                self.assertNotIn(call(""), app.overlay.set_update_flag.call_args_list)
                app.tray.set_update_available.assert_not_called()

    def check(self, app, info, *, silent, download=None):
        with patch("knight_flow.app.check_for_update", return_value=info), \
             patch("knight_flow.app.download_installer", side_effect=download or AssertionError("no download")), \
             patch("knight_flow.app.save_config"), \
             patch("knight_flow.updater.running_from_store", return_value=False), \
             patch("knight_flow.app.threading.Thread", Inline):
            app.check_updates(silent=silent)

    @staticmethod
    def release(**overrides):
        fields = dict(available=True, latest_version="0.4.171-beta", release_url="", forced=False,
                      installer_url="", installer_sha256="", installer_size=0, artifact_signing_enabled=False)
        fields.update(overrides)
        return SimpleNamespace(**fields)

    def test_a_manual_check_lights_no_dot_for_a_skipped_release(self):
        # Review B8 (2026-10-10): the menu hides a skipped release's row, so its dot stays
        # off too, whoever asked. Asked by hand, the check still shows the release.
        app = self.app()
        app.config["updates"]["skip_version"] = "0.4.171-beta"
        app.overlay.set_update_flag.reset_mock()
        app.show_update_window = Mock()
        self.check(app, self.release(), silent=False)
        app.show_update_window.assert_called_once()
        for lit in ("green", "red"):
            self.assertNotIn(call(lit), app.overlay.set_update_flag.call_args_list)
        # A release that was not skipped still lights it.
        app = self.app()
        app.show_update_window = Mock()
        self.check(app, self.release(), silent=False)
        app.overlay.set_update_flag.assert_called_with("green")

    def test_a_required_release_installs_the_installer_its_check_downloaded(self):
        # Review B14 (2026-10-10): a required release is downloaded by the check, but
        # Install (the menu's, Home's or the tray's) downloaded it a second time. The
        # installer is still verified before it runs (launch_installer).
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            installer = Path(folder) / "TalkDAT-0.4.171-beta.exe"
            installer.write_bytes(b"MZ")
            app = self.app()
            app.show_update_window = Mock()
            required = self.release(forced=True, installer_url="https://example.invalid/i.exe", installer_sha256="ab" * 32)
            self.check(app, required, silent=True, download=lambda *_a, **_k: installer)
            app.show_update_window.assert_called_once_with(required, installer)
            app.show_update_window.reset_mock()
            app.install_or_check_update()
            app.show_update_window.assert_called_once_with(required, installer)
            # Gone from disk: download again.
            app.show_update_window.reset_mock()
            installer.unlink()
            app.install_or_check_update()
            app.show_update_window.assert_called_once_with(required, None)

    def test_a_predownload_is_reused_only_for_the_same_build(self):
        # Review N3/T-3 (2026-10-10): matched on the version, the SHA-256 and the size.
        # Another release, or the same version published again, downloads afresh.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            installer = Path(folder) / "Talk-Dat-Setup-0.4.171-beta.exe"
            installer.write_bytes(b"MZ")
            app = self.app()
            app.show_update_window = Mock()
            build = dict(forced=True, installer_url="https://example.invalid/i.exe", installer_sha256="ab" * 32,
                         installer_size=2)
            self.check(app, self.release(**build), silent=True, download=lambda *_a, **_k: installer)
            for change in ({"latest_version": "0.4.172-beta"}, {"installer_sha256": "cd" * 32}, {"installer_size": 3}):
                other = self.release(**{**build, **change})
                with self.subTest(change=change):
                    app.pending_update = other
                    app.show_update_window.reset_mock()
                    app.install_or_check_update()
                    app.show_update_window.assert_called_once_with(other, None)

    CHECKED = {"expected_sha256": "ab" * 32, "expected_size": 2, "require_authenticode": False}

    def test_a_fresh_installer_that_fails_its_check_is_said_not_retried(self):
        # Review F3/T3-3 (I04): only an installer KEPT from the check is downloaded again.
        # A fresh download that fails its check is said, after one download and one launch.
        import tempfile
        from pathlib import Path

        from knight_flow.updater import UpdateError

        with tempfile.TemporaryDirectory() as folder:
            fresh = Path(folder) / "fresh.exe"
            app = self.app()
            app.quit = Mock()
            info = self.release(forced=True, installer_url="https://example.invalid/i.exe",
                                installer_sha256="ab" * 32, installer_size=2)
            checked = []

            def launch(_path, **kwargs):
                checked.append(kwargs)
                raise UpdateError("The downloaded installer does not match the published SHA-256.")

            done = Mock()
            with patch("knight_flow.app.download_installer", return_value=fresh) as download, \
                 patch("knight_flow.app.launch_installer", side_effect=launch), \
                 patch("knight_flow.app.save_config"), \
                 patch("knight_flow.app.threading.Thread", Inline):
                app.install_update(info, None, Mock(), Mock(), done)
            download.assert_called_once()
            self.assertEqual(checked, [self.CHECKED])
            self.assertIs(done.call_args.args[0], False)
            app.quit.assert_not_called()

    def test_a_reused_installer_that_fails_its_check_is_downloaded_again_once(self):
        # Review N3: a cached file that fails the check is dropped and downloaded once
        # more, instead of failing every Install until a restart.
        import tempfile
        from pathlib import Path

        from knight_flow.updater import UpdateError

        with tempfile.TemporaryDirectory() as folder:
            stale, fresh = Path(folder) / "stale.exe", Path(folder) / "fresh.exe"
            stale.write_bytes(b"MZ")
            app = self.app()
            app.quit = Mock()
            app._predownloaded_update = ("0.4.171-beta", "ab" * 32, 2, stale)
            info = self.release(forced=True, installer_url="https://example.invalid/i.exe",
                                installer_sha256="ab" * 32, installer_size=2)
            launched = []
            checked = []

            def launch(path, **kwargs):
                launched.append(path)
                checked.append(kwargs)
                if path == stale:
                    raise UpdateError("The downloaded installer does not match the published SHA-256.")

            done = Mock()
            with patch("knight_flow.app.download_installer", return_value=fresh) as download, \
                 patch("knight_flow.app.launch_installer", side_effect=launch), \
                 patch("knight_flow.app.save_config"), \
                 patch("knight_flow.app.threading.Thread", Inline):
                app.install_update(info, stale, Mock(), Mock(), done)
            self.assertEqual(launched, [stale, fresh])
            # Review F3/T3-3 (A13, A16): both launches are checked against the release.
            self.assertEqual(checked, [self.CHECKED] * 2)
            download.assert_called_once()
            self.assertIs(done.call_args.args[0], True)
            self.assertIsNone(getattr(app, "_predownloaded_update", None))
            # A fresh download that fails too is reported, not retried for ever.
            launched.clear()
            done.reset_mock()
            with patch("knight_flow.app.download_installer", return_value=stale) as download, \
                 patch("knight_flow.app.launch_installer", side_effect=launch), \
                 patch("knight_flow.app.save_config"), \
                 patch("knight_flow.app.threading.Thread", Inline):
                app._predownloaded_update = ("0.4.171-beta", "ab" * 32, 2, stale)
                app.install_update(info, stale, Mock(), Mock(), done)
            self.assertEqual(launched, [stale, stale])
            self.assertIs(done.call_args.args[0], False)

    def test_skipping_the_version_clears_the_dot(self):
        app = self.app()
        with patch("knight_flow.app.save_config"):
            app.skip_update_version("0.4.171-beta")
        app.overlay.set_update_flag.assert_called_with("")


if __name__ == "__main__":
    unittest.main()
