from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from knight_flow import plugins


ENABLED = {"plugins": {"enabled": True}}
DISABLED = {"plugins": {"enabled": False}}


class PluginAPITests(unittest.TestCase):
    def test_blank_ids_and_non_callables_are_refused(self) -> None:
        api = plugins.PluginAPI()
        api.add_transform("", lambda text, config: text)
        api.add_transform("   ", lambda text, config: text)
        api.add_transform("shout", "not callable")
        api.add_text_filter("not callable")
        self.assertEqual(api.transforms, {})
        self.assertEqual(api.text_filters, [])

    def test_transform_ids_are_normalised(self) -> None:
        api = plugins.PluginAPI()
        api.add_transform("  SHOUT  ", lambda text, config: text.upper())
        self.assertIn("shout", api.transforms)


class PluginLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        previous = os.environ.get("TALK_DAT_HOME")
        os.environ["TALK_DAT_HOME"] = self.home.name

        def restore() -> None:
            if previous is None:
                os.environ.pop("TALK_DAT_HOME", None)
            else:
                os.environ["TALK_DAT_HOME"] = previous

        self.addCleanup(restore)
        # The loader caches on first use, so every test starts from a clean slate.
        plugins.reload_plugins()
        self.addCleanup(plugins.reload_plugins)

    def write_plugin(self, name: str, body: str) -> Path:
        path = plugins.plugins_dir() / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_plugins_are_off_until_explicitly_enabled(self) -> None:
        self.write_plugin("shout.py", "def register(api):\n    api.add_transform('shout', lambda t, c: t.upper())\n")
        self.assertFalse(plugins.plugins_enabled({}))
        self.assertIsNone(plugins.plugin_transform("shout", "hello", DISABLED))
        self.assertEqual(plugins.plugin_text_filters(DISABLED), [])

    def test_a_registered_transform_runs(self) -> None:
        self.write_plugin("shout.py", "def register(api):\n    api.add_transform('shout', lambda t, c: t.upper())\n")
        self.assertEqual(plugins.plugin_transform("shout", "hello", ENABLED), "HELLO")

    def test_registered_text_filters_are_returned_in_order(self) -> None:
        self.write_plugin(
            "filters.py",
            "def register(api):\n"
            "    api.add_text_filter(lambda t, c: t.replace('teh', 'the'))\n"
            "    api.add_text_filter(lambda t, c: t.strip())\n",
        )
        filters = plugins.plugin_text_filters(ENABLED)
        self.assertEqual(len(filters), 2)
        self.assertEqual(filters[0](" teh cat ", {}), " the cat ")

    def test_an_unknown_transform_id_is_simply_absent(self) -> None:
        self.write_plugin("shout.py", "def register(api):\n    api.add_transform('shout', lambda t, c: t.upper())\n")
        self.assertIsNone(plugins.plugin_transform("whisper", "hello", ENABLED))

    def test_a_plugin_that_explodes_on_import_is_recorded_not_raised(self) -> None:
        self.write_plugin("broken.py", "raise RuntimeError('boom')\n")
        self.write_plugin("good.py", "def register(api):\n    api.add_transform('good', lambda t, c: t + '!')\n")
        # The healthy plugin must still load: one bad file cannot disable the rest.
        self.assertEqual(plugins.plugin_transform("good", "hi", ENABLED), "hi!")
        errors = plugins.load_errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("broken.py", errors[0])
        self.assertIn("RuntimeError", errors[0])

    def test_a_transform_that_raises_never_breaks_dictation(self) -> None:
        self.write_plugin(
            "angry.py",
            "def _angry(text, config):\n    raise ValueError('no')\n\n"
            "def register(api):\n    api.add_transform('angry', _angry)\n",
        )
        self.assertIsNone(plugins.plugin_transform("angry", "hello", ENABLED))

    def test_an_empty_result_falls_back_rather_than_pasting_nothing(self) -> None:
        self.write_plugin("blank.py", "def register(api):\n    api.add_transform('blank', lambda t, c: '   ')\n")
        self.assertIsNone(plugins.plugin_transform("blank", "hello", ENABLED))

    def test_a_file_without_register_is_ignored_quietly(self) -> None:
        self.write_plugin("notes.py", "VALUE = 1\n")
        self.assertIsNone(plugins.plugin_transform("anything", "hello", ENABLED))
        self.assertEqual(plugins.load_errors(), [])

    def test_non_python_files_are_never_executed(self) -> None:
        (plugins.plugins_dir() / "readme.txt").write_text("raise RuntimeError('boom')", encoding="utf-8")
        self.assertEqual(plugins.plugin_text_filters(ENABLED), [])
        self.assertEqual(plugins.load_errors(), [])

    def test_reload_picks_up_a_newly_added_plugin(self) -> None:
        self.assertIsNone(plugins.plugin_transform("late", "hi", ENABLED))
        self.write_plugin("late.py", "def register(api):\n    api.add_transform('late', lambda t, c: t + '?')\n")
        self.assertIsNone(plugins.plugin_transform("late", "hi", ENABLED), "cache should hold until reload")
        plugins.reload_plugins()
        self.assertEqual(plugins.plugin_transform("late", "hi", ENABLED), "hi?")


if __name__ == "__main__":
    unittest.main()
