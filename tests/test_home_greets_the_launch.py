"""Home is what a launch opens, and it stays wired the way it was built.

X-172, his report 2026-09-21: "it goes to like this weird menu where settings
has to appear first ... random settings that I had open". Boot called
`open_settings()` with no destination, and the shell's no-destination branch is
`page = self._last_page`, so the app reopened whichever Settings page the
previous session closed on. "Home" was an alias for the General settings page
and had never been a screen.

Home shipped with no test at all, which is the same gap that let a hardcoded
"your PC" survive into a Mac build: nothing was checking. These are the
assertions that would have caught every fault the feature actually had.

Every assertion here is anchored by IDENTITY -- a function's name, a field's
id, a decorator's presence -- and never by position. This repo has been bitten
repeatedly by tests pinned to "the first match in the file", including two
during this very feature: a decorator stolen by an inserted method, and a
`querySelector('.nav-icon')` probe that started reading Home's rail icon.
"""
from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

from knight_flow.config import DEFAULT_CONFIG
from knight_flow.web_shell.home_workspace import HomeWorkspace, home_greeting
from knight_flow.web_shell.shell_backend import PAGES

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "knight_flow" / "web_shell" / "shell_assets"


def _config(**ui):
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config.setdefault("ui", {}).update(ui)
    return config


class HomeIsTheScreenALaunchOpensTests(unittest.TestCase):
    def test_home_is_a_real_page_and_comes_first(self) -> None:
        """PAGES order is also the navigation and search order."""
        self.assertEqual(PAGES[0][0], "home", f"Home is no longer first: {PAGES[0]}")
        identifiers = [page[0] for page in PAGES]
        self.assertEqual(identifiers.count("home"), 1, "Home is declared twice")

    def test_a_launch_opens_home_and_not_a_settings_page(self) -> None:
        """The actual bug: boot must pass an EXPLICIT destination.

        `open_settings()` with no argument falls back to `self._last_page`.
        Reading the source of run() is deliberate -- the alternative is booting
        a real application, and what needs protecting is which call the launch
        path makes.
        """
        from knight_flow.app import TalkDatApp

        source = inspect.getsource(TalkDatApp.run)
        self.assertIn("open_home()", source,
                      "the launch no longer opens Home")
        self.assertNotIn("self.overlay.open_settings()", source,
                         "the launch reopens the last Settings page again (X-172)")

    def test_home_is_an_explicit_destination_in_the_shell(self) -> None:
        """'home' used to be an alias for the General settings page."""
        from knight_flow.web_shell import shell_app

        source = inspect.getsource(shell_app.AppShell.open_settings)
        self.assertIn("'home':'home'", source.replace('"', "'"),
                      "'home' is aliased to another page again")


class TheDecoratorBelongsToOpenSettingsTests(unittest.TestCase):
    """Inserting a method above `def open_settings` steals its decorator.

    That happened while Home was being built. `open_home` silently took
    @_transactional_utility_builder and `open_settings` lost it -- and that
    decorator is what destroys the loading cover when a build raises. It
    compiled, it rendered, and only two gui_shell_page_sizing tests noticed.
    functools.wraps sets __wrapped__, so the decorator is detectable.
    """

    def test_open_settings_is_still_transactional(self) -> None:
        from knight_flow.overlay import Overlay

        self.assertTrue(
            hasattr(Overlay.open_settings, "__wrapped__"),
            "open_settings lost @_transactional_utility_builder -- a failed "
            "build will now leave an orphan loading cover on screen",
        )

    def test_open_home_is_not_decorated(self) -> None:
        """open_home builds no window; it delegates."""
        from knight_flow.overlay import Overlay

        self.assertFalse(
            hasattr(Overlay.open_home, "__wrapped__"),
            "open_home took a decorator that belongs to the method below it",
        )


class HomeShipsInsideTheBundleTests(unittest.TestCase):
    def test_home_js_is_in_both_asset_lists(self) -> None:
        """One list inlines the script; the other strips its <script src> tag.

        Miss the second and the bundled document keeps a tag that its own CSP
        (`default-src 'none'`) refuses to load.
        """
        source = (ROOT / "knight_flow" / "web_shell" / "shell_host.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("'home.js'"), 2,
                         "home.js is missing from one of shell_host's two asset lists")

    def test_the_bundle_carries_home_and_no_stray_tag(self) -> None:
        from knight_flow.web_shell.shell_host import bundled_html

        html = bundled_html(ASSETS)
        self.assertIn("window.TalkDatHome", html, "Home's renderer is not bundled")
        self.assertNotIn('<script src="home.js"', html,
                         "an unloadable <script src> tag survived into the bundle")


class HomeGreetingTests(unittest.TestCase):
    def test_a_blank_name_greets_without_one(self) -> None:
        self.assertEqual(home_greeting(_config(display_name=""))["name"], "")

    def test_a_name_reaches_the_greeting(self) -> None:
        self.assertEqual(home_greeting(_config(display_name="Mayowa"))["name"], "Mayowa")

    def test_a_name_is_tidied_and_bounded(self) -> None:
        """It is free text landing in a heading, so it cannot run off the page."""
        self.assertEqual(home_greeting(_config(display_name="  Mayowa   Adeyemi "))["name"],
                         "Mayowa Adeyemi")
        self.assertEqual(len(home_greeting(_config(display_name="X" * 200))["name"]), 40)

    def test_the_shortcut_reads_as_key_caps_not_config(self) -> None:
        """"cmd" is what the config calls it; nobody has a key labelled cmd."""
        greeting = home_greeting(_config())
        self.assertNotIn("cmd", greeting["shortcuts"]["push_to_talk"].lower())
        self.assertTrue(greeting["shortcuts"]["push_to_talk"],
                        "Home stopped telling anyone which keys to hold")

    def test_the_greeting_survives_a_provider_that_cannot_answer(self) -> None:
        """A broken provider is diagnosed on the Speech page, not by a blank Home."""
        def explode(_config):
            raise RuntimeError("provider is unreachable")

        workspace = HomeWorkspace(_config(), dispatch=lambda fn: fn(), greeter=explode)
        payload = workspace.handle({"operation": "status"})
        self.assertIn("greeting", payload)
        self.assertEqual(payload["greeting"]["name"], "")


class HomeSettingsAreReachableTests(unittest.TestCase):
    """Both switches must be DECLARED, not merely read with a default.

    `ui.show_home_on_start` was read by app.py and declared nowhere, so the
    "turn Home off at launch" setting did not exist in Settings at all.
    """

    def setUp(self) -> None:
        self.fields = json.loads((ASSETS / "settings-fields.json").read_text(encoding="utf-8"))
        self.by_id = {field["id"]: field for field in self.fields}

    def test_every_field_id_is_unique(self) -> None:
        ids = [field["id"] for field in self.fields]
        self.assertEqual(len(ids), len(set(ids)), "a settings field id is declared twice")

    def test_the_name_is_editable(self) -> None:
        field = self.by_id.get("ui.display_name")
        self.assertIsNotNone(field, "there is no way to set the name Home greets you by")
        self.assertEqual(field["type"], "text")
        self.assertEqual(field["default"], "")

    def test_home_on_launch_can_be_turned_off(self) -> None:
        field = self.by_id.get("ui.show_home_on_start")
        self.assertIsNotNone(field, "app.py reads this setting but nothing declares it")
        self.assertEqual(field["type"], "toggle")
        self.assertIs(field["default"], True)

    def test_the_app_reads_the_same_key_the_field_declares(self) -> None:
        """A field and a reader that disagree leave a switch that does nothing."""
        from knight_flow.app import TalkDatApp

        source = inspect.getsource(TalkDatApp.run)
        self.assertIn('"show_home_on_start"', source)


class HomeWorkspaceIsRoutableTests(unittest.TestCase):
    def test_the_home_area_is_allowed(self) -> None:
        """The adapter rejects any area not on its list."""
        source = (ROOT / "knight_flow" / "web_shell" / "workspace_adapter.py").read_text(encoding="utf-8")
        self.assertIn("'home'", source, "the home workspace area is not routable")

    def test_activity_loads_off_the_calling_thread(self) -> None:
        """Home must never be the reason a launch feels slow."""
        calls: list = []
        workspace = HomeWorkspace(_config(), dispatch=calls.append,
                                  loader=lambda _c: {"words": 1, "entries": 1, "streak_days": 1,
                                                     "minutes_saved": 1, "history_enabled": True})
        first = workspace.handle({"operation": "status"})
        self.assertIsNone(first["activity"], "the history store was walked on the calling thread")
        self.assertEqual(first["phase"], "idle")

    def test_an_unknown_operation_is_refused(self) -> None:
        workspace = HomeWorkspace(_config(), dispatch=lambda fn: fn())
        with self.assertRaises(ValueError):
            workspace.handle({"operation": "delete_everything"})


if __name__ == "__main__":
    unittest.main()
