from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.mac_support import IS_MAC


@unittest.skipUnless(IS_MAC, "the login item is macOS only")
class TheLoginItemManagesItselfTests(unittest.TestCase):
    """Windows registers a Startup shortcut from its installer. A .dmg
    drag-install has no installer step, so the app owns its own login item -- a
    LaunchAgent plist it installs and loads.
    """

    def _as_installed_bundle(self):
        """Pretend to be running from /Applications/Talk DAT!.app."""
        fake = Path("/Applications/Talk DAT!.app/Contents/MacOS/Talk DAT!")
        patcher = patch("knight_flow.mac_login_item.sys")
        s = patcher.start()
        self.addCleanup(patcher.stop)
        s.frozen = True
        s.executable = str(fake)
        s.platform = "darwin"
        return s

    def test_enabling_from_a_checkout_is_refused(self) -> None:
        """A login item pointing at a source tree launches nothing useful, so
        it is refused rather than installed broken."""
        from knight_flow import mac_login_item as li

        with patch("knight_flow.mac_login_item.sys") as s:
            s.frozen = False
            ok, message = li.enable()
        self.assertFalse(ok)
        self.assertIn("installed app", message)

    def test_enable_installs_a_plist_that_points_at_the_bundle(self) -> None:
        from knight_flow import mac_login_item as li

        self._as_installed_bundle()
        with patch("knight_flow.mac_login_item.subprocess.run") as run, \
             patch("knight_flow.mac_login_item.Path.write_text") as write, \
             patch("knight_flow.mac_login_item.Path.mkdir"):
            run.return_value.returncode = 0
            ok, _message = li.enable()

        self.assertTrue(ok)
        written = write.call_args.args[0]
        self.assertIn("com.knightaiav.talkdat.login", written)
        self.assertIn("/Applications/Talk DAT!.app", written)
        self.assertIn("<key>RunAtLoad</key><true/>", written)
        # Aqua only: a login item, not a headless daemon.
        self.assertIn("<string>Aqua</string>", written)

    def test_a_failed_bootstrap_still_reports_it_will_load_next_login(self) -> None:
        """The plist is on disk, so it loads at the next login regardless of
        whether the immediate bootstrap succeeded -- the message must not claim
        failure the user will see disproven tomorrow."""
        from knight_flow import mac_login_item as li

        self._as_installed_bundle()
        with patch("knight_flow.mac_login_item.subprocess.run") as run, \
             patch("knight_flow.mac_login_item.Path.write_text"), \
             patch("knight_flow.mac_login_item.Path.mkdir"):
            run.return_value.returncode = 1
            ok, message = li.enable()
        self.assertTrue(ok)
        self.assertIn("next sign-in", message)

    def test_disable_removes_the_plist(self) -> None:
        from knight_flow import mac_login_item as li

        with patch("knight_flow.mac_login_item.subprocess.run"), \
             patch("knight_flow.mac_login_item.Path.exists", return_value=True), \
             patch("knight_flow.mac_login_item.Path.unlink") as unlink:
            ok, _message = li.disable()
        self.assertTrue(ok)
        unlink.assert_called_once()


if __name__ == "__main__":
    unittest.main()
