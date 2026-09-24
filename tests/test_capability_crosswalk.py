"""X-157: the menu rework cannot quietly lose a feature.

His constraint for the settings and onboarding rework was "ensure no features
or functionality are lost". That is a promise until something enforces it, and
a promise does not survive a large refactor across four navigation surfaces.

tests/capability_manifest.json freezes every reachable capability as it stood
when the audit was taken. These tests re-read the live source and fail on
anything that DISAPPEARED. Adding is free -- new features should not fight the
guard. Removing requires regenerating the manifest via
scripts/build_capability_manifest.py, which prints exactly what is being
dropped, so a deletion has to be typed out and defended in a commit rather
than happening by accident during a move.

Why source text and not imports: the settings console needs tkinter and the
tray needs pystray at import time, and this must run headless, on the Mac over
SSH with a locked display, and in any future CI. A guard that can only run on
a workstation with a screen is a guard that stops running.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.capability_crosswalk import snapshot

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "capability_manifest.json"


def _frozen() -> dict[str, list[str]]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["capabilities"]


class NothingReachableMayDisappearTests(unittest.TestCase):
    """One test per surface, so a failure names the surface that lost something."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.frozen = _frozen()
        cls.live = snapshot()

    def assertKept(self, group: str) -> None:
        frozen = self.frozen.get(group, [])
        live = set(self.live.get(group, []))
        missing = [item for item in frozen if item not in live]
        self.assertEqual(
            missing, [],
            f"{group}: these were reachable and are not any more -> {missing}. "
            "If that is deliberate, run scripts/build_capability_manifest.py and "
            "say in the commit which capability was retired and why.",
        )

    def test_the_pill_menu_keeps_every_action(self) -> None:
        self.assertKept("pill_menu_actions")

    def test_the_tray_keeps_every_command(self) -> None:
        self.assertKept("tray_commands")

    def test_settings_keeps_every_page(self) -> None:
        self.assertKept("settings_pages")

    def test_settings_keeps_every_section(self) -> None:
        self.assertKept("settings_sections")

    def test_the_five_relocated_tools_survive(self) -> None:
        """Account, Words & phrases, Race, Mic Doctor, Share an idea.

        These already moved once (out of the pill menu). The plan moves them
        again, into the pages they belong to, and that is exactly the kind of
        move where one quietly fails to arrive.
        """
        self.assertKept("relocated_tools")

    def test_every_shell_window_still_opens(self) -> None:
        self.assertKept("shell_pages")

    def test_no_command_is_dropped_from_the_registry(self) -> None:
        """The 73 callback keys are the real command surface.

        A menu row is only a door; this is the room behind it. A refactor that
        tidies menus while deleting a handler passes every visual check.
        """
        self.assertKept("app_commands")

    def test_onboarding_keeps_every_step(self) -> None:
        """Steps may be reordered or made optional; content may not vanish.

        The plan makes four steps required and the rest optional, so the ids
        must all still exist even when the flow no longer forces them.
        """
        self.assertKept("onboarding_steps")


class TheGuardItselfMustBeHonestTests(unittest.TestCase):
    def test_the_manifest_is_not_empty(self) -> None:
        """A cleared manifest would make every test above pass vacuously."""
        frozen = _frozen()
        total = sum(len(v) for v in frozen.values())
        self.assertGreater(total, 150, "manifest looks truncated; regenerate deliberately")
        self.assertGreaterEqual(len(frozen), 8, "manifest lost whole groups")

    def test_every_group_the_extractor_reports_is_frozen(self) -> None:
        """A new surface must be added to the baseline, not silently unguarded."""
        missing = sorted(set(snapshot()) - set(_frozen()))
        self.assertEqual(
            missing, [],
            f"these surfaces are extracted but not frozen: {missing}. "
            "Run scripts/build_capability_manifest.py.",
        )

    def test_the_extractor_finds_real_values_everywhere(self) -> None:
        """Guards against a regex that silently starts matching nothing.

        Every group here had contents when the audit was taken, so an empty one
        means the parser broke, not that the app shrank -- and an empty group
        would make its assertKept pass while protecting nothing. This is the
        failure that let RELOCATED_TOOLS report one item instead of five.
        """
        for group, items in snapshot().items():
            with self.subTest(group=group):
                self.assertTrue(items, f"{group} extracted nothing; the parser is broken")


if __name__ == "__main__":
    unittest.main()


class TheCommandListIsBoundToTheRegistryTests(unittest.TestCase):
    """X-184: the manifest counted five things that were never commands.

    `app_commands` matched `"name": self.thing` at eight-plus spaces of indent
    ANYWHERE in app.py, so ordinary dict FIELDS were frozen as capabilities:
    `downloading_model` (a progress-message key), `in_progress` (a field of
    license_activation_status), `language` and `overlay_state` (fields of
    status_snapshot), and `onboarding_incomplete`.

    The manifest exists to prove no capability was lost in a refactor. Padding it
    with entries that were never capabilities does not make that proof stronger,
    it makes the number meaningless -- and the number is the whole mechanism.

    The correction was only safe because NOTHING was missing in the other
    direction: every real registry key was already present. That asymmetry is the
    test below, and it is what distinguishes "the count was inflated" from "a
    capability was lost", which is the distinction that must never be fudged.
    """

    def test_every_manifest_command_is_a_real_registry_key(self) -> None:
        from tests.capability_crosswalk import app_commands

        listed = set(_frozen()["app_commands"])
        real = set(app_commands())
        phantom = sorted(listed - real)
        self.assertEqual(
            phantom, [],
            "these are frozen as commands but are not keys of the callbacks "
            f"registry, so nothing can ever invoke them: {phantom}",
        )

    def test_every_registry_key_is_in_the_manifest(self) -> None:
        """The direction that would mean a real capability went missing."""
        from tests.capability_crosswalk import app_commands

        listed = set(_frozen()["app_commands"])
        missing = sorted(set(app_commands()) - listed)
        self.assertEqual(
            missing, [],
            f"these dispatcher commands are absent from the frozen manifest: {missing}",
        )

    def test_the_extractor_reads_the_registry_and_not_the_whole_file(self) -> None:
        """A regex over app.py is what produced the phantoms."""
        import inspect

        from tests import capability_crosswalk

        source = inspect.getsource(capability_crosswalk.app_commands)
        self.assertIn("ast.parse", source)
        self.assertNotIn("re.findall", source, "app_commands is scanning the whole file again")
