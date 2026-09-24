from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from knight_flow.reset import (
    CATEGORIES,
    EXPENSIVE,
    ORDINARY,
    PRESETS,
    human_size,
    perform,
    plan,
    prune_config,
)


def scratch() -> Path:
    directory = Path(tempfile.mkdtemp())
    (directory / "history.jsonl").write_text("{}\n", encoding="utf-8")
    (directory / "scratchpad-tabs.json").write_text("[]", encoding="utf-8")
    models = directory / "models"
    models.mkdir()
    (models / "parakeet.bin").write_bytes(b"x" * 2048)
    spool = directory / "audio-spool"
    spool.mkdir()
    (spool / "session.wav").write_bytes(b"y" * 512)
    return directory


class NothingExpensiveIsSelectedByAccidentTests(unittest.TestCase):
    """The two failure modes are not symmetric.

    Not deleting enough costs a second click. Deleting too much costs work
    nobody can get back -- months of dictionary entries, or gigabytes of models
    on a metered connection. So the defaults lean hard one way.
    """

    def test_models_and_sign_in_start_unchecked(self) -> None:
        for key in ("models", "account"):
            with self.subTest(category=key):
                category = next(c for c in CATEGORIES if c.key == key)
                self.assertEqual(category.weight, EXPENSIVE)
                self.assertFalse(category.default_checked)

    def test_things_people_authored_start_unchecked(self) -> None:
        """A dictionary took months to build. It is not a preference."""
        for key in ("dictionary", "snippets", "history", "scratchpad"):
            with self.subTest(category=key):
                self.assertFalse(next(c for c in CATEGORIES if c.key == key).default_checked)

    def test_only_cheap_to_redo_settings_are_preselected(self) -> None:
        preselected = [c.key for c in CATEGORIES if c.default_checked]
        self.assertEqual(sorted(preselected), ["onboarding", "settings"])

    def test_the_default_presets_protect_the_slow_things(self) -> None:
        self.assertNotIn("models", PRESETS["keep_models_and_account"])
        self.assertNotIn("account", PRESETS["keep_models_and_account"])
        self.assertNotIn("account", PRESETS["everything_but_account"])
        # And one preset really does mean everything, or the option is a lie.
        self.assertEqual(set(PRESETS["everything"]), {c.key for c in CATEGORIES})


class ThePreviewMatchesWhatActuallyHappensTests(unittest.TestCase):
    """The preview and the deletion are the same code path, on purpose.

    A preview computed separately from the deletion is a second implementation
    that can disagree with the first, and it will disagree exactly when
    somebody is about to destroy something.
    """

    def test_the_plan_lists_only_files_that_exist(self) -> None:
        directory = scratch()
        (directory / "history.jsonl").unlink()
        listed = plan(["history"], directory)
        self.assertEqual(listed.files, ())
        self.assertEqual(listed.bytes_freed, 0)

    def test_the_plan_reports_a_real_size(self) -> None:
        directory = scratch()
        self.assertEqual(plan(["models"], directory).bytes_freed, 2048)

    def test_what_the_plan_listed_is_what_disappears(self) -> None:
        directory = scratch()
        intended = plan(["history", "scratchpad"], directory)
        self.assertEqual({p.name for p in intended.files},
                         {"history.jsonl", "scratchpad-tabs.json"})
        perform(["history", "scratchpad"], directory,
                read_config=dict, write_config=lambda _c, _f=(): None)
        for path in intended.files:
            self.assertFalse(path.exists())
        # And nothing it did not list was touched.
        self.assertTrue((directory / "models" / "parakeet.bin").exists())

    def test_an_unknown_category_is_ignored_rather_than_raising(self) -> None:
        """A stale preset should cost a checkbox, not crash the reset dialog."""
        self.assertTrue(plan(["nope", "history"], scratch()).categories)
        self.assertTrue(plan(["nope"], scratch()).is_empty)


class ClearingOneSectionLeavesTheOthersAloneTests(unittest.TestCase):
    def test_pruning_removes_only_the_named_keys(self) -> None:
        config = {"dictionary": {"words": ["a"]}, "hotkeys": {"toggle": "F9"}, "cleanup": {}}
        pruned = prune_config(config, ("dictionary",))
        self.assertNotIn("dictionary", pruned)
        self.assertEqual(pruned["hotkeys"], {"toggle": "F9"}, "clearing words took the hotkeys")

    def test_the_original_config_is_not_mutated(self) -> None:
        """If writing the pruned copy fails, the caller still has the real one."""
        config = {"dictionary": {"words": ["a"]}}
        prune_config(config, ("dictionary",))
        self.assertIn("dictionary", config)

    def test_a_missing_section_is_not_an_error(self) -> None:
        self.assertEqual(prune_config({}, ("dictionary", "a.b.c")), {})


class PerformReportsHonestlyTests(unittest.TestCase):
    def test_one_locked_file_does_not_abandon_the_rest(self) -> None:
        """The person asked for this. Clearing most of it beats clearing none."""
        directory = scratch()
        result = perform(["history", "scratchpad", "models"], directory,
                         read_config=dict, write_config=lambda _c, _f=(): None)
        self.assertIn("history.jsonl", result["removed"])
        self.assertIn("models", result["removed"])
        self.assertEqual(result["failed"], [])

    def test_the_licence_is_only_forgotten_when_asked(self) -> None:
        directory = scratch()
        calls = []
        perform(["settings"], directory, read_config=dict, write_config=lambda _c, _f=(): None,
                forget_license=lambda: calls.append(1) or True)
        self.assertEqual(calls, [], "a settings reset signed the machine out")

        perform(["account"], directory, read_config=dict, write_config=lambda _c, _f=(): None,
                forget_license=lambda: calls.append(1) or True)
        self.assertEqual(len(calls), 1)

    def test_a_failed_sign_out_is_reported_not_swallowed(self) -> None:
        result = perform(["account"], scratch(), read_config=dict,
                         write_config=lambda _c, _f=(): None, forget_license=lambda: False)
        self.assertIn("sign-in", result["failed"])

    def test_config_changes_ask_for_a_restart(self) -> None:
        result = perform(["settings"], scratch(), read_config=dict, write_config=lambda _c, _f=(): None)
        self.assertTrue(result["restart_required"])
        result = perform(["history"], scratch(), read_config=dict, write_config=lambda _c, _f=(): None)
        self.assertFalse(result["restart_required"], "deleting a log file needs no restart")

    def test_selecting_nothing_deletes_nothing(self) -> None:
        directory = scratch()
        result = perform([], directory, read_config=dict, write_config=lambda _c, _f=(): None)
        self.assertEqual(result["removed"], [])
        self.assertTrue((directory / "history.jsonl").exists())


class SizesAreReadableTests(unittest.TestCase):
    def test_sizes_are_stated_in_units_people_decide_with(self) -> None:
        self.assertEqual(human_size(4 * 1024 ** 3), "4.0 GB")
        self.assertEqual(human_size(1536), "1.5 KB")
        self.assertEqual(human_size(12), "12 bytes")


if __name__ == "__main__":
    unittest.main()
