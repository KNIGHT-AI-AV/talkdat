"""T7: synthetic sessions. A locked take resolves every route to this machine,
the fence refuses for the take even when the global route is open, a missing
local model stops the take rather than switching route, and the receipt matches
what ran. No real network: the device guard refuses any socket beyond loopback,
and these tests check the fence refused BEFORE a socket was ever reached.
"""
from __future__ import annotations

import copy
import unittest

from knight_flow import net_fence
from knight_flow.take_receipt import TakeReceipt, finish_receipt, lock_take, planned_routes
from tests import device_guard


def byok_config() -> dict:
    """A person who normally uses their own provider key for speech and text."""
    return {
        "privacy": {"local_only": False},
        "stt": {"route_mode": "byok", "provider": "deepgram", "cloud_provider": "deepgram",
                "providers": {"deepgram": {"api_key": "test-key-not-real", "model": "nova-3"},
                              "local": {"model": "parakeet-tdt-0.6b-v3"}}},
        "transforms": {"llm": {"provider": "openrouter", "api_key": "test-key-not-real"}},
        "translation": {"enabled": False},
    }


class ALockedTakeStaysHere(unittest.TestCase):
    def setUp(self):
        net_fence.set_local_only(False)
        self.addCleanup(net_fence.set_local_only, False)

    def test_the_lock_turns_every_resolver_local(self):
        config = byok_config()
        open_routes = planned_routes(config)
        self.assertNotEqual(open_routes.speech_route, "local")
        locked = planned_routes(lock_take(config))
        self.assertTrue(locked.locked)
        self.assertEqual(locked.speech_route, "local")
        self.assertEqual(locked.speech_model, "parakeet-tdt-0.6b-v3")
        self.assertEqual(locked.formatter_route, "ollama")
        self.assertEqual(locked.translation_route, "off")

    def test_the_stored_config_is_untouched(self):
        config = byok_config()
        before = copy.deepcopy(config)
        lock_take(config)
        planned_routes(lock_take(config))
        planned_routes(config)
        self.assertEqual(config, before)

    def test_the_fence_refuses_for_the_take_with_the_global_route_open(self):
        refusals_before = len(device_guard.REPORT)
        take = net_fence.begin_take(locked=True)
        try:
            with self.assertRaises(net_fence.LocalOnlyBlocked):
                net_fence.assert_cloud_allowed("https://api.deepgram.com/v1/listen", "Speech transcription")
            with self.assertRaises(net_fence.LocalOnlyBlocked):
                net_fence.assert_cloud_allowed("https://openrouter.ai/api/v1/chat", "The formatter")
            net_fence.assert_cloud_allowed("http://127.0.0.1:11434/api/chat", "The formatter")  # this machine
        finally:
            net_fence.end_take(take)
        receipt = finish_receipt(planned_routes(lock_take(byok_config())), take, format_route="ollama")
        self.assertEqual(receipt.remote_used, [])
        self.assertEqual(receipt.remote_refused, ["api.deepgram.com", "openrouter.ai"])
        self.assertEqual(receipt.verdict(), "stayed on this computer; remote attempts were refused")
        # The fence said no before anything reached a socket.
        self.assertEqual(len(device_guard.REPORT), refusals_before)
        # And once the take is over, the open route is open again.
        net_fence.assert_cloud_allowed("https://api.deepgram.com/v1/listen", "Speech transcription")

    def test_an_unlocked_take_records_but_does_not_refuse(self):
        take = net_fence.begin_take(locked=False)
        try:
            net_fence.assert_cloud_allowed("https://api.deepgram.com/v1/listen", "Speech transcription")
        finally:
            net_fence.end_take(take)
        receipt = finish_receipt(planned_routes(byok_config()), take)
        self.assertEqual(receipt.remote_used, ["api.deepgram.com"])
        self.assertEqual(receipt.verdict(), "used a remote service")

    def test_two_open_takes_a_locked_one_holds_the_fence(self):
        first, second = net_fence.begin_take(locked=False), net_fence.begin_take(locked=True)
        try:
            with self.assertRaises(net_fence.LocalOnlyBlocked):
                net_fence.assert_cloud_allowed("api.deepgram.com", "Speech transcription")
            self.assertEqual(len(first.attempts), 1)
            self.assertEqual(len(second.attempts), 1)
        finally:
            net_fence.end_take(first)
            net_fence.end_take(second)
        self.assertFalse(net_fence.take_locked())

    def test_the_global_route_still_works_alone(self):
        net_fence.set_local_only(True)
        with self.assertRaises(net_fence.LocalOnlyBlocked):
            net_fence.assert_cloud_allowed("api.deepgram.com", "Speech transcription")
        net_fence.assert_cloud_allowed("localhost", "The formatter")


class TheReceipt(unittest.TestCase):
    def test_a_stopped_take(self):
        receipt = finish_receipt(TakeReceipt(locked=True), net_fence.TakeNet(True),
                                 stopped="no local speech model is ready")
        self.assertEqual(receipt.verdict(), "stopped")
        self.assertEqual(receipt.as_dict()["stopped"], "no local speech model is ready")

    def test_the_formatter_that_actually_ran(self):
        planned = planned_routes(lock_take(byok_config()))
        ran = finish_receipt(planned, net_fence.TakeNet(True), format_route="rules")
        self.assertEqual((planned.formatter_route, ran.formatter_route), ("ollama", "rules"))
        self.assertEqual(ran.verdict(), "stayed on this computer")

    def test_a_receipt_holds_no_words(self):
        receipt = finish_receipt(planned_routes(lock_take(byok_config())), net_fence.TakeNet(True))
        self.assertNotIn("test-key-not-real", repr(receipt.as_dict()))


if __name__ == "__main__":
    unittest.main()
