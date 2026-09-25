"""X-480: two routes, local and bring your own key. Nothing in between.

His call, said twice and not as a question: "BYOK or Local Only ... it is the
options we allow", "We do both". So the product offers exactly two, and the
managed middleman that used to sit between them is not one of the options.

The switch had three positions: cloud, auto, local. "Cloud" meant our managed
service, "auto" existed only to arbitrate between that managed service and a
person's own key, and with the managed service gone there is nothing left to
arbitrate. A three-position switch for a two-choice product is how somebody
ends up on a route nobody meant them to have.

  local  the machine. The default, and what the product is for.
  byok   the person's own key, their own account, their own provider.
         A relationship we are not in the middle of.

WHY THIS IS SAFE FOR PEOPLE ALREADY RUNNING. Configs on disk say "cloud" or
"auto" today, and a switch that silently lands them somewhere is the failure
this file exists to stop. So the migration is explicit and conservative:

  * "auto" becomes LOCAL. It is the current default, most installs are on it,
    and moving someone to a paid or keyed route without asking is not a
    migration, it is a surprise.
  * "cloud" becomes BYOK only when a usable key is actually configured.
    Otherwise it becomes local, because a keyless "cloud" route now points at
    a service that no longer exists, and pointing it at nothing is worse than
    pointing it home.

An unknown mode also lands on local. Under X-465 the local-only switch already
outranks all of this, so the practical answer for almost everybody is local
either way; this is about the config being honest rather than merely harmless.
"""

from __future__ import annotations

import unittest

from knight_flow import platform_copy

from knight_flow import stt_registry


def config(mode: str = "", provider: str = "", key: str = "", local_only: bool = False):
    return {
        "stt": {
            "route_mode": mode,
            "cloud_leg": provider,
            "provider": provider or "local",
            "providers": {provider: {"api_key": key}} if provider else {},
        },
        "privacy": {"local_only": local_only},
    }


class ThereAreExactlyTwoTests(unittest.TestCase):
    def test_the_switch_has_two_positions(self) -> None:
        self.assertEqual(set(stt_registry.ROUTE_MODES), {"local", "byok"})

    def test_the_managed_service_is_not_a_position(self) -> None:
        """It was "cloud". There is no managed cloud any more, so a switch
        that still offers it is offering a route to nowhere."""
        self.assertNotIn("cloud", stt_registry.ROUTE_MODES)

    def test_auto_is_gone(self) -> None:
        """Auto existed to choose between the managed leg and a person's own
        key. With one of those removed it has nothing to decide."""
        self.assertNotIn("auto", stt_registry.ROUTE_MODES)

    def test_local_is_the_default(self) -> None:
        """An empty or unreadable config is a local install."""
        self.assertEqual(stt_registry.route_mode({}), "local")
        self.assertEqual(stt_registry.route_mode(config("")), "local")


class NobodyIsMovedSomewhereTheyDidNotChooseTests(unittest.TestCase):
    def test_auto_becomes_local(self) -> None:
        """The old default. Most installs are on it, and moving them onto a
        keyed route without asking would be a surprise, not a migration."""
        self.assertEqual(stt_registry.route_mode(config("auto")), "local")

    def test_cloud_without_a_key_becomes_local(self) -> None:
        """Their "cloud" pointed at a managed service that is gone. Home is a
        better answer than nowhere."""
        self.assertEqual(stt_registry.route_mode(config("cloud")), "local")

    def test_cloud_with_a_real_key_becomes_byok(self) -> None:
        """Somebody who configured their own provider key chose that, and the
        route that honours the choice is byok."""
        self.assertEqual(
            stt_registry.route_mode(config("cloud", "openai", "sk-live-abcdefghijkl")),
            "byok",
        )

    def test_an_unknown_mode_lands_local(self) -> None:
        self.assertEqual(stt_registry.route_mode(config("something-else")), "local")


class ResolvingTheRouteTests(unittest.TestCase):
    def test_local_only_still_outranks_everything(self) -> None:
        """X-465. The switch is a preference; this is the promise on the front
        page, and it wins even over an explicit byok choice."""
        chosen = config("byok", "openai", "sk-live-abcdefghijkl", local_only=True)
        self.assertEqual(stt_registry.resolve_route(chosen, False), "local")

    def test_byok_resolves_to_the_persons_own_provider(self) -> None:
        chosen = config("byok", "openai", "sk-live-abcdefghijkl")
        self.assertEqual(stt_registry.resolve_route(chosen, False), "openai")

    def test_byok_without_a_usable_key_falls_home(self) -> None:
        """A route with no key cannot transcribe, and failing to local is the
        difference between a slower dictation and no dictation."""
        self.assertEqual(stt_registry.resolve_route(config("byok"), False), "local")

    def test_entitlement_no_longer_decides_anything(self) -> None:
        """It gated the managed leg. With no managed leg, an account's
        entitlement has no say over which engine transcribes."""
        chosen = config("byok", "openai", "sk-live-abcdefghijkl")
        self.assertEqual(
            stt_registry.resolve_route(chosen, True),
            stt_registry.resolve_route(chosen, False),
        )


if __name__ == "__main__":
    unittest.main()


class TheSwitchOFFERSExactlyThoseTwoTests(unittest.TestCase):
    """X-525: X-480 changed the ENGINE and left the switch alone.

    Everything above this class has been true since X-480. The PILL was not:
    it kept drawing Cloud | Auto | Local, and the founder found it by
    right-clicking the pill and seeing a Cloud button.

    Two separate faults, both silent:

      * `set_route_mode` rejects anything outside ROUTE_MODES, so tapping
        Cloud or Auto did NOTHING AT ALL. Two of three positions were inert.
      * `route_state()` answers `route_mode(config)`, which is "local" or
        "byok". The drawing code understood only "cloud"/"auto"/"local" and
        defaulted anything else to "auto" -- so a person actually running on
        their own key was shown a position the engine had also deleted.

    Nothing failed, because nothing in the suite ever compared the switch's
    positions with the engine's. That comparison is the whole point of this
    class. The docstring at the top of this file described the three-position
    switch in the PAST TENSE while it was still on screen, which is its own
    lesson: prose is not a guard.
    """

    def test_the_switch_positions_are_exactly_the_route_modes(self) -> None:
        from knight_flow.overlay import Overlay

        self.assertEqual(
            tuple(segment for _focus, segment in Overlay.MENU_ROUTE_FOCUS_STOPS),
            tuple(stt_registry.ROUTE_MODES),
            "the pill offers a position the engine will not accept, or hides one it will",
        )

    def test_the_hit_test_can_only_ever_name_a_real_route(self) -> None:
        """Across the whole width, including the gutters. A coordinate that
        maps to a mode `set_route_mode` refuses is a click that does nothing
        and says nothing, which is what shipped."""
        from types import SimpleNamespace

        from knight_flow.overlay import Overlay

        stub = SimpleNamespace(
            _route_switch_rect=lambda: (40, 80),
            _menu_main_width=lambda: 356,
        )
        seen = set()
        for x in range(0, 420, 3):
            segment = Overlay._route_segment_at(stub, x, 60)
            if segment:
                self.assertIn(segment, stt_registry.ROUTE_MODES, f"x={x} maps to an unsettable route")
                seen.add(segment)
        self.assertEqual(seen, set(stt_registry.ROUTE_MODES), "some route is unreachable by pointer")


class EverySettableRouteCanActuallyBeSetTests(unittest.TestCase):
    """X-532: the switch saved the route and then raised, silently.

    `TheSwitchOFFERSExactlyThoseTwoTests` above proves a tap lands on a name in
    ROUTE_MODES. It stops one function short of proving the app can ACT on that
    name, and that is exactly where the bug lived: `set_route_mode` guarded
    `mode not in ROUTE_MODES` and then looked the mode up in a labels dict still
    keyed "cloud" / "auto" / "local". Tapping "Your key" wrote route_mode="byok"
    to disk and then raised KeyError before the pill could confirm anything. The
    tap handler catches every exception and logs at DEBUG, so the half of the
    switch he had just been given appeared to do nothing at all.

    Two adjacent tests, each correct, with the defect in the seam between them.
    So this one EXECUTES the setter, for every mode the switch can produce, and
    it iterates ROUTE_MODES rather than naming modes, so adding or renaming one
    cannot leave it half-checked again.
    """

    class _Overlay:
        def __init__(self) -> None:
            self.said: list[tuple[str, str, str]] = []

        def set_state(self, state: str, message: str = "", detail: str = "", **_kwargs) -> None:
            self.said.append((state, message, detail))

        def refresh_route_paint(self) -> None:
            pass

    def _app(self, providers: dict | None = None):
        from knight_flow.app import TalkDatApp

        class _App:
            set_route_mode = TalkDatApp.set_route_mode

            def __init__(inner) -> None:
                inner.config = {
                    "stt": {"provider": "local", "route_mode": "local",
                            "providers": providers or {}},
                    "privacy": {"local_only": False},
                }
                inner.overlay = EverySettableRouteCanActuallyBeSetTests._Overlay()
                inner.warmed = 0
                inner._auto_local_sticky = True

            def save_settings(inner) -> None:
                pass

            def warm_selected_local_model(inner) -> None:
                inner.warmed += 1

        return _App()

    def test_every_mode_completes_and_the_pill_confirms_it(self) -> None:
        for mode in stt_registry.ROUTE_MODES:
            app = self._app({"openai": {"api_key": "sk-test"}})
            app.config["stt"]["cloud_provider"] = "openai"
            self.assertTrue(app.set_route_mode(mode), f"{mode} did not complete")
            self.assertEqual(mode, app.config["stt"]["route_mode"])
            self.assertTrue(app.overlay.said, f"{mode} confirmed nothing to the person")
            state, message, detail = app.overlay.said[-1]
            self.assertEqual("captured", state)
            self.assertTrue(message.startswith("Route: "), message)
            self.assertTrue(detail.strip(), f"{mode} confirmed with an empty detail")

    def test_choosing_a_route_by_hand_ends_an_imposed_rescue(self) -> None:
        """The sticky local rescue is the app overriding the person. The
        person picking a route outranks it, whichever route they pick."""
        for mode in stt_registry.ROUTE_MODES:
            app = self._app({"openai": {"api_key": "sk-test"}})
            app.set_route_mode(mode)
            self.assertFalse(app._auto_local_sticky, f"{mode} left the rescue stuck on")

    def test_byok_without_a_key_says_it_still_runs_on_the_pc(self) -> None:
        """resolve_route sends a keyless byok route home. A person not told
        that reads the fallback as a switch that did not work."""
        app = self._app({})
        app.set_route_mode("byok")
        detail = app.overlay.said[-1][2]
        self.assertIn(platform_copy.THIS_COMPUTER, detail)
        self.assertEqual("local", stt_registry.resolve_route(app.config))
