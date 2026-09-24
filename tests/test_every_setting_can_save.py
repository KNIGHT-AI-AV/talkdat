"""X-186: a Settings control that is saved must be able to trigger a save.

Settings autosaves when something marks the page dirty. Marking dirty happens
through a write-trace on the variables in `tracked_vars`. A variable that is read
by `save()` but absent from that list therefore changes the app immediately and
never reaches disk -- unless some OTHER control happens to be dirty at the same
moment, which is why this class of bug always reads as intermittent rather than
broken.

It was reported once, as "color settings does nothing": the theme was the only
control on the Colors page and it was untracked, so it repainted instantly and
was gone on the next launch.

Rather than wait for each of the others to be reported, every PERSISTED variable
was compared against the tracked list. Three more were missing, all real
settings, all silently discarded:

    trigger_style_var        Dictation, the trigger style combo
    format_intensity_var     the Chill / Executive finish switch
    translation_engine_var   Translation, local vs managed engine

The reason they slipped is worth keeping: `combo()` builds a plain
ttk.Combobox with no dirty binding, and `pick_finish` sets its variable directly.
Nothing about either looks wrong at the call site; the omission is only visible
by joining two lists that live 2000 lines apart, which is what this test does.

UI-only variables are deliberately NOT tracked, and each has a reason:

    app_font_var             saves immediately from `change_app_font`
    local_auto_download_var  saves immediately from `set_local_auto_download`
    custom_model_var         a transient "add a model" entry, cleared after use
    settings_search_var      a transient navigation query, never configuration
    save_status_var          transient footer copy, never configuration
    save_status_kind_var     transient footer semantics, never configuration
    slider_var               normalized mirror of persisted `gain_var`
    finish_choice_var        semantic radio mirror of persisted finish label

Tracking those would produce spurious unsaved-changes states, so they are named
here as intentional rather than left to look like oversights.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"

# Saved by their own command the moment they change, so a dirty mark would be
# redundant, or transient scratch fields that are not settings at all.
SAVES_ITSELF = frozenset({
    "app_font_var",
    # X-416: the local live-captions toggle writes stt.local_live_captions and
    # calls save_settings from its own command, the same shape as the rest of
    # this set. Verified by reading the handler, not by assuming.
    "local_live_captions_var",
    "local_auto_download_var",
    "custom_model_var",
    "provider_lane_var",
    "pill_scale_var",
    "settings_search_var",
    "save_status_var",
    "save_status_kind_var",
    "slider_var",
    "finish_choice_var",
})

TRANSIENT_UI_VARS = frozenset({
    "custom_model_var",
    "settings_search_var",
    "save_status_var",
    "save_status_kind_var",
    "slider_var",
    "finish_choice_var",
})


def _settings_source() -> str:
    text = OVERLAY.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "open_settings":
            return ast.get_source_segment(text, node) or ""
    raise AssertionError("open_settings not found")


def declared_variables(source: str) -> set[str]:
    return set(re.findall(r"^\s*(\w+_var)\s*=\s*tk\.(?:String|Boolean|Int|Double)Var\(", source, re.M))


def persisted_variables(source: str) -> set[str]:
    """Variables whose value is read on the way into config."""
    found = set(re.findall(r"(\w+_var)\.get\(\)", source))
    found |= set(re.findall(r"parse_int\((\w+_var)", source))
    found |= set(re.findall(r"parse_float\((\w+_var)", source))
    return found


def tracked_variables(source: str) -> set[str]:
    """The `tracked_vars` list, read with AST.

    Deliberately not by finding the next "]" after the marker: that bracket is
    the one inside `list[tk.Variable]`, and taking it returned an EMPTY set while
    looking like it worked -- which would have made every assertion below pass
    vacuously. It did, on the first attempt.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "tracked_vars" and isinstance(node.value, ast.List):
                return {e.id for e in node.value.elts if isinstance(e, ast.Name)}
    raise AssertionError("tracked_vars list not found")


class EverySavedSettingCanTriggerASaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = _settings_source()

    def test_the_extractors_find_something(self) -> None:
        """A guard whose inputs are empty passes forever and protects nothing."""
        self.assertGreaterEqual(len(declared_variables(self.source)), 60)
        self.assertGreaterEqual(len(persisted_variables(self.source)), 50)
        self.assertGreaterEqual(
            len(tracked_variables(self.source)), 60,
            "tracked_vars came back nearly empty; the extractor is broken and "
            "every assertion in this file would pass for the wrong reason",
        )

    def test_the_four_that_were_silently_discarded_are_tracked(self) -> None:
        tracked = tracked_variables(self.source)
        for name in ("theme_var", "trigger_style_var", "format_intensity_var", "translation_engine_var"):
            with self.subTest(variable=name):
                self.assertIn(
                    name, tracked,
                    f"{name} is written to config by save() but nothing marks the "
                    "page dirty when it changes, so the setting is discarded",
                )

    def test_no_persisted_setting_is_untracked(self) -> None:
        """The general rule, so the next one is caught before it is reported."""
        source = self.source
        untracked = sorted(
            (declared_variables(source) & persisted_variables(source))
            - tracked_variables(source)
            - SAVES_ITSELF
        )
        self.assertEqual(
            untracked, [],
            "these are read by save() but never mark Settings dirty, so changing "
            "them appears to work and is then discarded. Either add them to "
            f"tracked_vars, or to SAVES_ITSELF with the reason: {untracked}",
        )

    def test_the_intentional_exclusions_still_exist(self) -> None:
        """A name in SAVES_ITSELF that no longer exists is a stale exemption,
        and a stale exemption is a hole in the guard."""
        declared = declared_variables(self.source)
        stale = sorted(name for name in SAVES_ITSELF if name not in declared)
        self.assertEqual(stale, [], f"SAVES_ITSELF names variables that are gone: {stale}")

    def test_each_self_saving_control_really_does_save_itself(self) -> None:
        """Otherwise the exemption is just a way to silence the rule."""
        source = self.source
        for name in sorted(SAVES_ITSELF):
            if name in TRANSIENT_UI_VARS:
                continue
            with self.subTest(variable=name):
                uses = [m.start() for m in re.finditer(re.escape(name), source)]
                near_save = any(
                    "save_settings" in source[max(0, at - 900): at + 900]
                    or "mark_dirty" in source[max(0, at - 900): at + 900]
                    for at in uses
                )
                self.assertTrue(
                    near_save,
                    f"{name} is exempt from dirty tracking but nothing near it saves",
                )


if __name__ == "__main__":
    unittest.main()
