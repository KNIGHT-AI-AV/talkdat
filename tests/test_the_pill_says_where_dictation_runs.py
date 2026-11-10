"""LIST-0476 item (i): the Pill's "Your key" confirmation under Local-only privacy.

With Local-only privacy on, choosing "Your key" on the Pill said "Dictation runs
on your own <provider> key." while dictation stayed on this computer, because
Local-only privacy outranks the switch (stt_registry.resolve_route). The Pill
now says where dictation runs and how to use the key.
"""
from __future__ import annotations

import unittest
from unittest import mock

from knight_flow import platform_copy


def switched_to_your_key(local_only: bool):
    from knight_flow.app import TalkDatApp

    app = object.__new__(TalkDatApp)
    app.config = {
        "privacy": {"local_only": local_only},
        "stt": {"route_mode": "local", "provider": "local", "cloud_provider": "deepgram",
                "providers": {"deepgram": {"api_key": "dg-test-key"}}},
        "deepgram": {"api_key": "dg-test-key"},
    }
    app.save_settings = mock.Mock()
    app.warm_selected_local_model = mock.Mock()
    app.overlay = mock.Mock()
    with mock.patch("knight_flow.net_fence.set_local_only") as fence:
        self_answer = app.set_route_mode("byok")
    return app, self_answer, fence


class ThePillSaysWhereDictationRunsTests(unittest.TestCase):
    def test_with_local_only_on_it_says_dictation_stays_here(self) -> None:
        app, switched, fence = switched_to_your_key(True)
        self.assertTrue(switched)
        fence.assert_called_with(True)
        state, title, detail = app.overlay.set_state.call_args.args[:3]
        self.assertEqual((state, title), ("captured", "Route: Your key"))
        self.assertEqual(detail, f"Local-only privacy is on, so dictation stays on {platform_copy.THIS_COMPUTER}. "
                                 "Your key works once you turn it off in Settings, Privacy.")
        # The route has one name (tests/test_your_key_has_one_name.py).
        self.assertNotIn("use your key", detail.casefold())

    def test_with_local_only_off_it_names_the_key(self) -> None:
        app, switched, fence = switched_to_your_key(False)
        self.assertTrue(switched)
        fence.assert_called_with(False)
        detail = app.overlay.set_state.call_args.args[2]
        self.assertTrue(detail.startswith("Dictation runs on your own "), detail)
        self.assertNotIn("Local-only", detail)


if __name__ == "__main__":
    unittest.main()
