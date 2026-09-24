"""X-365: a BYOK route that can finish text should finish it.

Reported by the founder: Chill and Executive do nothing on the Local route,
and nothing on a Deepgram bring-your-own-key route either.

The cause was not a bug in the formatter. X-192 made the formatter FOLLOW the
speech route, which is right -- before it, someone who chose Local kept their
audio on their machine and then had the whole transcript POSTed to Google,
while the pill still said Local. But "follow the speech route" was implemented
as "anything that is not our managed cloud goes to the local engine", and the
local engine needs Ollama installed with a model pulled. Almost nobody has
that. So a person who brought their own OpenRouter key paid for speech AND
had a perfectly capable text model sitting behind the same key, and still got
rules-only cleanup with no explanation.

The rule this file defends:

  THE SAME KEY THAT HEARD YOU CAN FINISH YOU. When the speech route is a BYOK
  provider that also serves text, the formatter uses that provider and that
  key. X-192 is honoured rather than bent: it is the same party the audio
  already went to, so nothing reaches anyone the person had not chosen, and
  Knight is still not in the path.

  LOCAL STAYS LOCAL. A local speech route formats locally, whatever keys are
  configured. net_fence enforces it at the socket; this keeps the routing
  from ever asking.

  A PROVIDER WITHOUT A TEXT MODEL IS NOT PRETENDED INTO ONE. Deepgram has no
  text model. It must fall to the local engine, which is why Deepgram BYOK
  users need Ollama or a different route -- and why the settings panel has to
  say so rather than degrade in silence.
"""

from __future__ import annotations

import unittest
from unittest import mock

from knight_flow import llm


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


def config_for(route_mode: str, provider: str, key: str = "k-test") -> dict:
    return {
        "transforms": {"llm": {"provider": "auto"}},
        "stt": {
            "route_mode": route_mode,
            "provider": provider,
            "providers": {provider: {"api_key": key}},
        },
    }


class TheSameKeyThatHeardYouFinishesYouTests(unittest.TestCase):
    def test_openrouter_speech_formats_on_openrouter(self) -> None:
        self.assertEqual(
            llm.resolved_llm_provider(config_for("cloud", "openrouter")), "openrouter")

    def test_openai_speech_formats_on_openai(self) -> None:
        self.assertEqual(
            llm.resolved_llm_provider(config_for("cloud", "openai")), "openai")

    def test_the_speech_key_is_the_one_actually_used(self) -> None:
        """The formatter's own settings hold a single key belonging to
        whatever provider was last chosen by hand -- usually nothing on a
        BYOK install. Reading it instead of the speech key would send an
        empty Authorization header and fall back to rules anyway."""
        config = config_for("cloud", "openrouter", key="or-secret")
        self.assertEqual(llm.byok_text_key(config, "openrouter"), "or-secret")

    def test_a_missing_function_is_not_reported_as_a_missing_key(self) -> None:
        """An earlier draft wrapped this in a bare except, so importing the
        helper from the wrong module looked exactly like "no key configured"
        and the whole feature stayed silently off."""
        with mock.patch.dict("sys.modules", {"knight_flow.stt_sessions": None}):
            with self.assertRaises(Exception):
                llm.byok_text_key(config_for("cloud", "openrouter"), "openrouter")


class LocalStaysLocalTests(unittest.TestCase):
    def test_a_local_route_never_reaches_for_a_cloud_key(self) -> None:
        config = config_for("local", "openrouter", key="or-secret")
        self.assertEqual(llm.resolved_llm_provider(config), "ollama")

    def test_the_helper_refuses_local_outright(self) -> None:
        self.assertEqual(llm.byok_text_provider(config_for("local", "openrouter"), "local"), "")


class AProviderWithoutTextIsNotPretendedIntoOneTests(unittest.TestCase):
    def test_deepgram_falls_to_the_local_engine(self) -> None:
        """Deepgram transcribes and nothing else. There is no arrangement of
        routing that lets a Deepgram key finish a sentence."""
        self.assertEqual(
            llm.resolved_llm_provider(config_for("cloud", "deepgram")), "ollama")

    def test_deepgram_is_absent_from_the_text_capable_map(self) -> None:
        self.assertNotIn("deepgram", llm.TEXT_CAPABLE_SPEECH_PROVIDERS)

    def test_every_mapped_provider_is_a_real_formatter_backend(self) -> None:
        """A mapping to a provider the formatter cannot speak would resolve to
        a backend with no implementation and fail at call time."""
        for speech, text in llm.TEXT_CAPABLE_SPEECH_PROVIDERS.items():
            self.assertIn(text, llm.PROVIDER_DEFAULTS, f"{speech} maps to unknown {text}")


class TheFormatterStillHasAManagedOptionTests(unittest.TestCase):
    """X-480: the SPEECH route is two now, local or the person's own key. The
    FORMATTER route has not been cut yet and still has a managed option.

    This test is kept and renamed rather than deleted, because it is the
    honest record of work that is outstanding. Deleting it would make the
    formatter look finished when it is not. When the formatter is cut to the
    same two routes, this becomes the test that proves it."""

    def test_a_managed_config_now_formats_locally(self) -> None:
        """X-480, and this was better news than expected.

        The formatter on "auto" follows the SPEECH route. Cutting speech to
        two routes therefore cut this as well: a config still naming the
        managed service resolves its speech home, so its formatting goes home
        with it, even with the managed service reachable and the local-only
        switch off.

        So the managed formatter was not merely discouraged, it was
        unreachable through the route. X-516 then removed the code, which is
        what this test predicted would change no behaviour: the assertion is
        unchanged, and only the patch that made a now-deleted service look
        reachable has gone."""
        config = {"transforms": {"llm": {"provider": "auto"}},
                  "stt": {"route_mode": "byok", "provider": "talk_dat_cloud", "providers": {}}}
        self.assertEqual(llm.resolved_llm_provider(config), "ollama")

    def test_an_explicit_choice_still_wins(self) -> None:
        """Only "auto" routes. Someone who named a provider keeps it."""
        config = config_for("cloud", "openrouter")
        config["transforms"]["llm"]["provider"] = "anthropic"
        self.assertEqual(llm.resolved_llm_provider(config), "anthropic")


if __name__ == "__main__":
    unittest.main()
