"""X-491: five features stop asking for a service that is being retired.

Rewrite, Fix That, Scribe, Live captions and Ramble were gated on whether the
person had an account with us, and served by the managed rewrite endpoint.
X-480 cut the speech route to local or the person's own key and X-481 did the
same for the formatter; these five were the last of it in the desktop app.

TWO OF THE STRINGS WERE WRONG, not stale. Ramble quoted "$11.99/mo" and
"$4.99/mo on top of Local Forever" after X-483 replaced that pricing and X-486
retired the add-on: a shipped button quoting a retired price for a retired
product. That is the privacy-notice defect in a different window.

The gate and the call site had to move together. A gate changed on its own
would let someone with a local model through a door into a body that still
called the managed service, which passes the check and then fails -- worse
than the thing being fixed.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8")


class TheGatesAskTheAnswerableQuestion(unittest.TestCase):
    def test_no_feature_advertises_the_managed_service(self) -> None:
        """Five buttons told people to go and get a thing we are retiring."""
        self.assertNotIn("runs on Talk DAT! Managed", APP)
        self.assertNotIn("run on Talk DAT! Managed", APP)

    def test_no_retired_price_is_quoted(self) -> None:
        """The Ramble gate named two prices that no longer exist. A wrong
        number in front of a person is worse than a vague sentence."""
        self.assertNotIn("$11.99", APP)
        self.assertNotIn("$4.99", APP)

    def test_the_gate_and_the_body_moved_together(self) -> None:
        """THE POINT OF THIS TEST. A gate that opens onto the old call is a
        worse failure than the one being fixed: it passes, then breaks."""
        self.assertNotIn("rewrite_text(", APP)
        self.assertEqual(APP.count("if not self._has_a_writing_model():"), 5)

    def test_both_lanes_are_named_to_the_person(self) -> None:
        """His instruction was that the product offers lanes. The refusal
        says what to do and names both, and quotes no price at all."""
        self.assertIn(
            "Choose a local model or add your own provider key in Settings.", APP)


class TheRetiredProviderIsNotABackend(unittest.TestCase):
    """Behaviour, not spelling. A legacy config can still NAME the managed
    provider, and the question is what the code does when it reads one."""

    def test_a_config_naming_the_retired_provider_is_not_configured(self) -> None:
        """The install has to be off local-only for the named provider to be
        read at all -- see the test below, which is why this one says so
        explicitly rather than relying on a default."""
        from knight_flow.llm import llm_configured

        self.assertFalse(llm_configured({
            "privacy": {"local_only": False},
            "llm": {"provider": "talk_dat_cloud"},
        }))

    def test_local_only_outranks_a_named_provider(self) -> None:
        """X-465, and worth pinning on its own: on a local-only install the
        formatter is the LOCAL engine whatever the config names. The first
        version of the test above missed this and read the resulting True as
        a bug in the code, when it is the behaviour the switch exists for."""
        from knight_flow.llm import llm_configured, resolved_llm_provider

        config = {"privacy": {"local_only": True}, "llm": {"provider": "talk_dat_cloud"}}
        self.assertEqual(resolved_llm_provider(config), "ollama")
        self.assertTrue(llm_configured(config))

    def test_a_local_engine_still_counts(self) -> None:
        """The refusal must not be indiscriminate: Ollama needs no key and is
        a perfectly good answer to 'is there a model to write with'."""
        from knight_flow.llm import llm_configured

        self.assertTrue(llm_configured({"llm": {"provider": "ollama"}}))

    def test_the_rewrite_carries_the_persons_voice(self) -> None:
        """Quick Fix passes a rendered style profile, and reached the managed
        service to do it. If the parameter were dropped the rewrite would
        still work and would silently stop sounding like them."""
        import inspect

        from knight_flow.llm import llm_rewrite

        self.assertIn("system", inspect.signature(llm_rewrite).parameters)


if __name__ == "__main__":
    unittest.main()
