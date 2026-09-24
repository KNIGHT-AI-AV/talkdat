from __future__ import annotations

import unittest
from unittest import mock
from unittest.mock import patch

from knight_flow.llm import local_formatter_status


# X-465: this module is about the world where local-only is OFF.
#
# Talk DAT! is local-only by default now: the speech route, the formatter and
# the door that lets text leave all read one switch, and a config that has
# never heard of that switch is treated as local-only, which is the right
# answer for a real install upgrading from an older version. The fixtures
# below are bare dicts asking for the managed or bring-your-own-key route, so
# without this they would resolve to local and test nothing they mean to.
#
# That route still exists for anybody who deliberately turns the switch off,
# and it still has to work. Naming the world here is the point: these
# assertions are about the cloud contract, not about whichever default happens
# to be in force.
_LOCAL_ONLY_OFF = mock.patch("knight_flow.stt_registry.local_only", return_value=False)


def setUpModule() -> None:
    _LOCAL_ONLY_OFF.start()


def tearDownModule() -> None:
    _LOCAL_ONLY_OFF.stop()


class TheFormatterSaysWhenItCannotRunTests(unittest.TestCase):
    """Choosing the local AI formatter without Ollama produced rule-formatted
    text forever, silently.

    Translation has shown engine-installed / engine-running / model-downloaded
    since it shipped. The formatter never did, which is the wrong way round:
    translation is occasional and formatting runs on every dictation.

    The failure is nastier than a normal one because the fallback is good. Rule
    formatting produces reasonable sentences, so nothing looks broken -- it
    reads as "this is how well the product writes", which is a worse outcome
    than an error message.
    """

    def status(self, models, executable="C:/ollama.exe", **llm):
        settings = {"provider": "ollama", "model": "qwen3:1.7b"}
        settings.update(llm)
        config = {"transforms": {"llm": settings}}
        with patch("knight_flow.llm._ollama_models", return_value=models), \
             patch("knight_flow.llm._local_ollama_executable", return_value=executable):
            return local_formatter_status(config)

    def test_a_working_setup_reports_ready(self) -> None:
        status = self.status({"qwen3:1.7b"})
        self.assertTrue(status["ready"])
        self.assertTrue(status["local"])

    def test_no_engine_installed_is_distinguishable_from_not_running(self) -> None:
        """They need different advice -- one is a download, the other is a
        launch -- so collapsing them into "unavailable" helps nobody."""
        absent = self.status(None, executable="")
        self.assertFalse(absent["engine_installed"])
        self.assertFalse(absent["ready"])

        stopped = self.status(None, executable="C:/ollama.exe")
        self.assertTrue(stopped["engine_installed"])
        self.assertFalse(stopped["engine_running"])
        self.assertFalse(stopped["ready"])

    def test_a_running_engine_missing_the_model_is_its_own_case(self) -> None:
        status = self.status({"some-other-model"})
        self.assertTrue(status["engine_running"])
        self.assertFalse(status["model_installed"])
        self.assertFalse(status["ready"])

    def test_a_model_tag_still_counts_as_installed(self) -> None:
        """`qwen3:1.7b` and `qwen3:latest` are the same download."""
        self.assertTrue(self.status({"qwen3:latest"})["model_installed"])

    def test_a_cloud_backend_is_never_reported_as_a_local_problem(self) -> None:
        """Someone on OpenRouter or Anthropic has no Ollama to install, and
        telling them to install one would be a bug."""
        for provider in ("openrouter", "anthropic", "gemini", "talk_dat_cloud"):
            with self.subTest(provider=provider):
                status = self.status(None, executable="", provider=provider)
                self.assertFalse(status["local"])
                self.assertTrue(status["ready"], "a cloud backend must not be flagged as unready")

    def test_the_probe_is_cheap_enough_for_a_settings_panel(self) -> None:
        """_ollama_models gives up after 0.35s and caches, so an absent engine
        costs one timeout rather than one per keystroke in the model field."""
        import inspect
        from knight_flow import llm

        signature = inspect.signature(llm._ollama_models)
        self.assertLessEqual(signature.parameters["timeout"].default, 0.5)


class TheSettingsPanelShowsItTests(unittest.TestCase):
    def source(self) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py").read_text(encoding="utf-8")

    def test_settings_reads_the_status_and_names_the_remedy(self) -> None:
        source = self.source()
        self.assertIn("local_formatter_status", source)
        # Each state needs the action that fixes it, not just the diagnosis.
        # The download link is per-platform now -- a Mac user sent to the
        # Windows page has a diagnosis and a dead end -- so the panel is checked
        # for the shared constant rather than one platform's literal URL.
        self.assertIn("OLLAMA_DOWNLOAD_URL", source)
        self.assertIn("Start Ollama", source)

    def test_the_download_link_matches_the_platform(self) -> None:
        from knight_flow.mac_support import IS_MAC
        from knight_flow.translation import OLLAMA_DOWNLOAD_URL

        self.assertTrue(OLLAMA_DOWNLOAD_URL.startswith("https://ollama.com/download/"))
        self.assertEqual(OLLAMA_DOWNLOAD_URL.endswith("/mac"), IS_MAC)
    def _refresh_formatter_ready_body(self) -> str:
        """The whole function, however long it grows.

        This used to be `source[index:][:2600]` and `[:3400]` -- two magic byte
        windows standing in for "near the function". X-366 added a branch to
        the function and pushed the real `trace_add` wiring to 4010 characters,
        so the guard failed while the product was correct. A distance in bytes
        is not a fact about code; extract the block instead.
        """
        source = self.source()
        start = source.index("def refresh_formatter_ready")
        # The nested def sits at 8 spaces, its body at 12. The function ends at
        # the first non-blank line indented no further than the def itself.
        indent = len(source[:start].rsplit("\n", 1)[-1])
        lines = source[start:].splitlines()
        body = [lines[0]]
        for line in lines[1:]:
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            body.append(line)
        return "\n".join(body)

    def test_it_refreshes_when_the_provider_or_model_changes(self) -> None:
        """A status that only reads once is wrong the moment someone switches
        provider in the same visit to Settings.

        The contract is that the callback is BOUND to the vars that feed it,
        which is a fact about the wiring, not about how far apart two strings
        happen to sit in the file.
        """
        source = self.source()
        # assertTrue on a boolean, NOT assertIn against the source: overlay.py
        # is ~1.1 MB, and unittest prints the whole haystack on failure, which
        # buries the one line that says what broke.
        self.assertTrue(
            'trace_add("write", refresh_formatter_ready)' in source,
            "the status must be re-read when the provider/model/base changes, "
            "and nothing in overlay.py binds refresh_formatter_ready to a variable",
        )
        for var in ("llm_provider_var", "llm_model_var", "llm_base_var"):
            with self.subTest(var=var):
                self.assertTrue(var in source, f"{var} is gone from Settings")

        body = self._refresh_formatter_ready_body()
        self.assertIn("engine_installed", body)
        self.assertIn("engine_running", body)


if __name__ == "__main__":
    unittest.main()
