"""X-481: the invariant that made the dead branch safe to remove.

`resolved_llm_provider` used to reach the managed cloud when, and only when,
the SPEECH route resolved there. X-192 made that a rule rather than an
assumption, after the formatter had been posting whole transcripts to
/v1/cloud/rewrite while the pill read Local.

X-480 then cut the speech route to two, local or the person's own key, and
`byok_provider` excludes the managed service by name. So the managed value can
no longer occur, and the branch guarded by it was unreachable code sitting in
a privacy path.

Removing it is only safe while THIS holds, so it is pinned here rather than
trusted. If somebody ever reintroduces a managed route, this fails first and
tells them the formatter branch has to come back with it.
"""

from __future__ import annotations

import unittest

from knight_flow.stt_registry import PROVIDER_BY_ID, byok_provider, resolve_route


def a_config(mode: str, provider: str = "", key: str = "", local_only: bool = False):
    return {
        "stt": {
            "route_mode": mode,
            "provider": provider,
            "cloud_provider": provider,
            "providers": {provider: {"api_key": key}} if provider else {},
        },
        "privacy": {"local_only": local_only},
    }


class TheManagedRouteCannotOccurTests(unittest.TestCase):
    def test_no_config_resolves_to_the_managed_service(self) -> None:
        """Swept rather than argued. Every mode, every provider we know, with
        and without a key, entitled and not."""
        modes = ["local", "byok", "cloud", "auto", "", "nonsense"]
        providers = [""] + sorted(PROVIDER_BY_ID)
        for mode in modes:
            for provider in providers:
                for key in ("", "sk-live-abcdefghijkl"):
                    for entitled in (True, False):
                        for local_only in (True, False):
                            config = a_config(mode, provider, key, local_only)
                            with self.subTest(mode=mode, provider=provider,
                                              key=bool(key), entitled=entitled,
                                              local_only=local_only):
                                self.assertNotEqual(
                                    resolve_route(config, entitled), "talk_dat_cloud",
                                    "the managed route came back; the formatter branch "
                                    "removed in X-481 has to come back with it",
                                )

    def test_byok_never_names_the_managed_service(self) -> None:
        """The other half of the same invariant. If byok_provider could return
        it, resolve_route could too."""
        for provider in sorted(PROVIDER_BY_ID):
            with self.subTest(provider=provider):
                config = a_config("byok", provider, "sk-live-abcdefghijkl")
                self.assertNotEqual(byok_provider(config), "talk_dat_cloud")

    def test_the_dead_branch_is_actually_gone(self) -> None:
        """Because leaving it would make this whole file decorative."""
        import inspect

        from knight_flow import llm

        import re

        # Comments stripped first. The removal is EXPLAINED in a comment that
        # quotes the removed line, so a naive search finds the documentation
        # and reports the code. This suite has produced that failure before
        # and it is the reason code_only() exists in the keyboard tests.
        raw = inspect.getsource(llm.resolved_llm_provider)
        source = re.sub(r"^\s*#.*$", "", raw, flags=re.M)
        self.assertNotIn('return "talk_dat_cloud" if entitled else "ollama"', source)
        self.assertNotIn('if route != "talk_dat_cloud"', source)


class TheFormatterStillFollowsTheSpeechRouteTests(unittest.TestCase):
    """The rule X-192 established survives the removal: what finishes your
    text is what heard it, and nothing else."""

    def test_a_local_route_formats_locally(self) -> None:
        from knight_flow.llm import resolved_llm_provider

        config = a_config("local")
        config["transforms"] = {"llm": {"provider": "auto"}}
        self.assertEqual(resolved_llm_provider(config), "ollama")

    def test_a_byok_route_formats_on_that_same_key(self) -> None:
        """Nothing reaches a party the person had not already chosen."""
        from knight_flow.llm import resolved_llm_provider

        config = a_config("byok", "openrouter", "sk-or-abcdefghijkl")
        config["transforms"] = {"llm": {"provider": "auto"}}
        self.assertEqual(resolved_llm_provider(config), "openrouter")


if __name__ == "__main__":
    unittest.main()
