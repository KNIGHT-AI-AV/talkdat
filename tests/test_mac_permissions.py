from __future__ import annotations

import sys
import unittest

from knight_flow import mac_support
from knight_flow.onboarding import (
    MAC_PERMISSION_PAGES,
    permission_is_satisfied,
    permission_pages,
    permissions_outstanding,
)

VOCABULARY = {"granted", "denied", "not asked", "unknown"}


class PermissionReadingTests(unittest.TestCase):
    """X-23 rests on these answers being true rather than merely present.

    The first microphone check written for this port returned a bool, could not
    import AVFoundation because pyobjc ships it separately, fell into its own
    except clause and answered True on every machine. A check that always
    passes is worse than no check: it reads as evidence.
    """

    def test_every_permission_answers_from_the_same_small_vocabulary(self) -> None:
        for name in mac_support.PERMISSION_ORDER:
            with self.subTest(permission=name):
                self.assertIn(mac_support.permission_state(name), VOCABULARY)

    def test_the_report_covers_exactly_the_declared_permissions(self) -> None:
        self.assertEqual(tuple(mac_support.permission_report()), mac_support.PERMISSION_ORDER)

    def test_an_unreadable_permission_is_not_a_verified_grant(self) -> None:
        """An unavailable check earns neither a success mark nor a denial."""
        self.assertFalse(permission_is_satisfied("unknown"))
        self.assertTrue(permission_is_satisfied("granted"))
        self.assertFalse(permission_is_satisfied("denied"))
        self.assertFalse(permission_is_satisfied("not asked"))

    @unittest.skipUnless(sys.platform == "darwin", "macOS privacy permissions have no Windows counterpart")

    def test_outstanding_keeps_the_order_the_app_will_trip_them_in(self) -> None:
        outstanding = permissions_outstanding(
            {"microphone": "denied", "accessibility": "granted", "input_monitoring": "not asked"}
        )
        self.assertEqual(outstanding, ("microphone", "input_monitoring"))

    @unittest.skipUnless(mac_support.IS_MAC, "macOS only")
    def test_input_monitoring_is_read_from_iokit_not_guessed(self) -> None:
        """There is no AX-style trusted check for Input Monitoring.

        Without IOHIDCheckAccess the only remaining signal is a global hotkey
        that never fires while every call reports success, so a wrong answer
        here is undetectable from inside the app.
        """
        import ctypes
        import ctypes.util

        self.assertTrue(ctypes.util.find_library("IOKit"), "IOKit is not loadable")
        self.assertIn(mac_support.input_monitoring_permission(), VOCABULARY)


class PermissionCopyTests(unittest.TestCase):
    def test_every_permission_the_app_depends_on_has_a_page(self) -> None:
        """A TCC gate added without a page is a feature that silently dies.

        This is the guard that matters over time: the pages and the checked
        permissions are two lists, and the day they diverge is the day someone
        hits a dialog nobody warned them about.
        """
        if not mac_support.IS_MAC:
            self.assertEqual(permission_pages(), ())
            return
        self.assertEqual(
            tuple(page.key for page in MAC_PERMISSION_PAGES),
            mac_support.PERMISSION_ORDER,
        )

    def test_every_page_can_deep_link_to_its_settings_pane(self) -> None:
        """The checklist is only actionable because of these links.

        Told to open System Settings, then Privacy & Security, then find a list
        and a switch, most people stop at step two.
        """
        for page in MAC_PERMISSION_PAGES:
            with self.subTest(permission=page.key):
                self.assertIn(page.key, mac_support._PRIVACY_PANES)

    def test_each_page_names_the_button_on_the_real_dialog(self) -> None:
        """The page exists so the pop-up is recognised, not merely expected."""
        for page in MAC_PERMISSION_PAGES:
            with self.subTest(permission=page.key):
                self.assertTrue(page.dialog_title.strip())
                self.assertTrue(page.dialog_button.strip())
                self.assertIn("Talk DAT!", page.dialog_title)
                self.assertTrue(page.breaks.strip(), "a permission with no stated consequence reads as optional")

    def test_no_page_promises_a_permission_can_be_skipped(self) -> None:
        for page in MAC_PERMISSION_PAGES:
            with self.subTest(permission=page.key):
                self.assertNotIn("optional", page.why.lower())


class MicrophoneCheckIsNotInertTests(unittest.TestCase):
    """microphone_permission answers "unknown" when AVFoundation is missing.

    That is the honest fallback, but it is also a permanently blank answer: the
    checklist can never tick, X-23's first page can never fire its prompt, and
    `_check_macos_input_permission` loses the one signal that distinguishes a
    refused microphone from a quiet room. pyobjc ships AVFoundation as its own
    distribution, so it is absent unless something asks for it -- which is
    exactly how this shipped inert the first time.
    """

    @unittest.skipUnless(mac_support.IS_MAC, "macOS only")
    def test_avfoundation_is_installed(self) -> None:
        try:
            import AVFoundation  # noqa: F401
        except Exception as error:
            self.fail(
                "AVFoundation is not importable, so every microphone permission check "
                f"answers 'unknown' forever: {type(error).__name__}: {error}"
            )

    @unittest.skipUnless(mac_support.IS_MAC, "macOS only")
    def test_the_microphone_check_reaches_a_real_answer(self) -> None:
        self.assertIn(mac_support.microphone_permission(), {"granted", "denied", "not asked"})

    def test_the_mac_spec_collects_avfoundation(self) -> None:
        """Importable in the venv is not importable in the .app.

        PyInstaller follows imports, and every AVFoundation call in this
        codebase is inside a function, behind a try, precisely so a missing
        framework cannot crash anything -- which also means the bundle can drop
        it and nothing raises until a permission check quietly returns unknown.
        """
        from pathlib import Path

        spec = (Path(__file__).resolve().parents[1] / "TalkDat-mac.spec").read_text(encoding="utf-8")
        self.assertIn("AVFoundation", spec)


class StartupNudgeNamesTheRightSwitchTests(unittest.TestCase):
    """The nudge used to check Accessibility and blame it for everything.

    Accessibility and Input Monitoring are two switches in two separate lists,
    and pynput needs Input Monitoring to *see* the trigger while Accessibility
    is what lets the result be *typed*. Granting one and not the other is the
    ordinary outcome, and it produced a Pill telling the user to fix something
    that was already correct while the trigger went on doing nothing.
    """

    def nudge(self, report: dict[str, str]) -> tuple[str, ...]:
        from unittest import mock

        with mock.patch.object(mac_support, "permission_report", return_value=report):
            from knight_flow.onboarding import permissions_outstanding as outstanding

            return outstanding(mac_support.permission_report())

    @unittest.skipUnless(mac_support.IS_MAC, "macOS only")
    def test_accessibility_granted_but_input_monitoring_refused_is_reported(self) -> None:
        missing = self.nudge(
            {"microphone": "granted", "accessibility": "granted", "input_monitoring": "denied"}
        )
        self.assertEqual(missing, ("input_monitoring",))

    @unittest.skipUnless(mac_support.IS_MAC, "macOS only")
    def test_nothing_is_reported_when_every_permission_is_in_place(self) -> None:
        self.assertEqual(
            self.nudge(
                {"microphone": "granted", "accessibility": "granted", "input_monitoring": "granted"}
            ),
            (),
        )

    @unittest.skipUnless(mac_support.IS_MAC, "macOS only")
    def test_an_unreadable_check_never_produces_a_false_alarm(self) -> None:
        """A machine that cannot answer must not be told to fix its settings."""
        self.assertEqual(
            self.nudge(
                {"microphone": "unknown", "accessibility": "unknown", "input_monitoring": "unknown"}
            ),
            (),
        )


class TheStatusWindowKeepsTheChecklistTests(unittest.TestCase):
    """These grants are bound to the app's code signature.

    Replacing the app clears them, and the symptom is never an error -- it is
    dictation that records silence or delivers nothing. So the checklist has to
    be readable long after onboarding is finished, without rerunning setup.
    """

    def source(self) -> str:
        from pathlib import Path

        return (Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py").read_text(encoding="utf-8")

    def test_status_reports_every_permission(self) -> None:
        # The Tk window (the fallback) and, since X-613, the web Status on Help
        # both carry the checklist. The Tk block grew by the web-first guard.
        block = self.source()
        block = block[block.index("def open_status"):][:4800]
        self.assertIn("permission_report", block)
        self.assertIn("permissions_outstanding", block)
        from pathlib import Path

        shell = (Path(__file__).resolve().parents[1] / "knight_flow" / "web_shell" / "shell_app.py").read_text(encoding="utf-8")
        web = shell[shell.index("def _permissions"):][:1600]
        self.assertIn("permission_report", web)
        self.assertIn("permissions_outstanding", web)

    def test_status_offers_a_way_into_system_settings(self) -> None:
        source = self.source()
        self.assertIn("_open_permission_settings_for_first_gap", source)
        block = source[source.index("def _open_permission_settings_for_first_gap"):][:900]
        self.assertIn("open_privacy_settings", block)


class ReopeningJustThePermissionPageTests(unittest.TestCase):
    """A cleared permission must not cost the user the whole wizard again.

    The grants are bound to the app's code signature, so every rebuild and every
    reinstall clears them -- which during this port meant roughly thirty times.
    Bumping ONBOARDING_VERSION to force setup again would have re-asked for the
    account choice, the speech route and the writing preset that were already
    settled, every single time.
    """

    @unittest.skipUnless(mac_support.IS_MAC, "macOS only")
    def test_the_wizard_can_open_directly_on_the_permission_page(self) -> None:
        import tkinter as tk

        from knight_flow.config import load_config
        from knight_flow.onboarding import ONBOARDING_STEPS
        from knight_flow.overlay import Overlay
        from knight_flow.ui.onboarding import open_onboarding_wizard
        from tests.tk_support import acquire_root, probe_error, release_root

        if probe_error is not None:
            self.skipTest(f"no usable Tk display: {probe_error}")

        root = acquire_root()
        overlay = Overlay(config=load_config(), callbacks={}, root=root)
        try:
            wizard = open_onboarding_wizard(overlay, step="permissions")
            root.update()
            expected = [step.id for step in ONBOARDING_STEPS].index("permissions")
            self.assertEqual(wizard.step_index, expected)
            self.assertTrue(
                getattr(wizard, "_permission_rows", None),
                "the page opened but built no permission rows",
            )
        finally:
            for child in list(root.winfo_children()):
                if isinstance(child, tk.Toplevel):
                    try:
                        child.destroy()
                    except Exception:
                        pass
            release_root(root)

    def test_the_shared_onboarding_version_was_left_alone(self) -> None:
        """Windows users gained nothing from this item and must not redo setup."""
        from knight_flow.onboarding import ONBOARDING_VERSION

        self.assertEqual(ONBOARDING_VERSION, 3)


if __name__ == "__main__":
    unittest.main()
