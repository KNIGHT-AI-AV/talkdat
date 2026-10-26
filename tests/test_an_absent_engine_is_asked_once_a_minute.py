"""An engine that is not there is asked about once a minute, not twice a take.

2026-10-24, the owner's PC with Ollama uninstalled: every dictation spent about
0.7 s in formatting (format_ms 720 to 850 in his log), two 0.35 s /api/tags
timeouts against a port nobody listens on (local_finish_target's inventory, then
_ollama_ready), before the built-in rules formatted the words anyway. On Windows a
loopback port nobody listens on does not refuse at once, so each probe costs its
whole timeout.

So an engine that did not answer is remembered for a minute: the takes in that
minute decline at once, without a probe. The background checks (the residency
check at every dictation start, the launch's prepare, the Settings status) still
ask, and the first answer clears it, so an engine that comes back is used again
without waiting out the minute.
"""
from __future__ import annotations

import copy
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from knight_flow import llm
from knight_flow.config import DEFAULT_CONFIG, LOCAL_FORMATTER_MODEL
from knight_flow.local_finish import LOCAL_GPU_MODEL, MachineSpeed

BASE = "http://127.0.0.1:11989"


def config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["transforms"]["llm"].update(provider="ollama", api_base=BASE, model=LOCAL_FORMATTER_MODEL, auto_install=False)
    return cfg


class Clock:
    """time.monotonic on a clock the test moves."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Engine:
    """urllib's urlopen for the engine: away (every call times out) or back (it lists its models)."""

    def __init__(self) -> None:
        self.away = True
        self.calls: list[str] = []

    def __call__(self, request, timeout=None):
        self.calls.append(getattr(request, "full_url", str(request)))
        if self.away:
            raise urllib.error.URLError(TimeoutError("timed out"))
        return io.BytesIO(json.dumps({"models": [{"name": LOCAL_FORMATTER_MODEL}, {"name": LOCAL_GPU_MODEL}]}).encode())


class AnAbsentEngineIsAskedOnceAMinuteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock, self.engine = Clock(), Engine()
        for patcher in (
            mock.patch.dict(os.environ),
            mock.patch.object(llm.time, "monotonic", self.clock),
            mock.patch("knight_flow.llm.urllib.request.urlopen", self.engine),
            mock.patch("knight_flow.llm.keep_local_finisher_resident"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        # The test package keeps every unit test away from a real engine; this one
        # needs the probe itself, against the fake above.
        os.environ.pop(llm.LOCAL_ENGINE_OFFLINE_ENV, None)
        self.addCleanup(self.reset)
        self.reset()

    @staticmethod
    def reset() -> None:
        llm._OLLAMA_READY_CACHE.clear()
        getattr(llm, "_ENGINE_AWAY", {}).clear()
        for model in (LOCAL_FORMATTER_MODEL, LOCAL_GPU_MODEL):
            llm._LOCAL_SPEED.pop(llm.local_finish_key(BASE, model), None)

    def test_a_take_inside_the_minute_asks_nothing(self) -> None:
        self.assertFalse(llm._ollama_ready(BASE, LOCAL_FORMATTER_MODEL))
        self.assertEqual(len(self.engine.calls), 1)
        for later in (5.0, 20.0, 59.0):  # past the 3 s answer cache, inside the minute
            self.clock.now = 1000.0 + later
            self.assertFalse(llm._ollama_ready(BASE, LOCAL_FORMATTER_MODEL))
        self.assertEqual(len(self.engine.calls), 1, "a take inside the minute asked the absent engine again")

    def test_after_the_minute_a_take_asks_again(self) -> None:
        llm._ollama_ready(BASE, LOCAL_FORMATTER_MODEL)
        self.clock.now += 61.0
        llm._ollama_ready(BASE, LOCAL_FORMATTER_MODEL)
        self.assertEqual(len(self.engine.calls), 2)

    def test_a_background_check_still_asks_and_an_answer_ends_the_minute(self) -> None:
        llm._ollama_ready(BASE, LOCAL_FORMATTER_MODEL)
        self.engine.away = False
        self.clock.now += 5.0
        # The residency check and the launch's prepare ask with no cache at all.
        self.assertTrue(llm._ollama_ready(BASE, LOCAL_FORMATTER_MODEL, cache_ttl=0.0))
        self.clock.now += 5.0
        self.assertTrue(llm._ollama_ready(BASE, LOCAL_FORMATTER_MODEL), "the engine came back and the take did not use it")

    def test_the_loaded_models_answer_ends_the_minute_too(self) -> None:
        # The residency check at a dictation start asks /api/ps first and stops there when
        # the model is already loaded, so that answer is the engine coming back too.
        llm._ollama_ready(BASE, LOCAL_FORMATTER_MODEL)
        self.engine.away = False
        self.clock.now += 5.0
        llm._ollama_loaded_on_gpu(BASE, LOCAL_FORMATTER_MODEL)
        self.assertTrue(llm._ollama_ready(BASE, LOCAL_FORMATTER_MODEL), "the engine answered and the take did not use it")

    def test_the_settings_status_always_asks(self) -> None:
        llm._ollama_ready(BASE, LOCAL_FORMATTER_MODEL)
        self.engine.away = False
        self.clock.now += 5.0
        status = llm.local_formatter_status(config())
        self.assertEqual(len(self.engine.calls), 2, "Settings showed the memo instead of asking")
        self.assertTrue(status["engine_running"])

    def test_a_take_while_the_engine_is_away_declines_at_once(self) -> None:
        # The owner's case: the 1.7B measured itself on the GPU earlier in the session,
        # so each take also asked for the inventory before asking whether it was ready.
        llm._LOCAL_SPEED[llm.local_finish_key(BASE, LOCAL_FORMATTER_MODEL)] = MachineSpeed(
            prefill_tps=4000.0, generation_tps=150.0, on_gpu=True)
        self.assertIsNone(llm.local_finish("the words", config(), executive=True, budget_seconds=1.5))
        self.assertEqual(llm.last_local_finish_reason(), "model_unavailable")
        self.assertEqual(len(self.engine.calls), 1, "the first take asked the absent engine twice")
        self.clock.now += 10.0
        self.assertIsNone(llm.local_finish("more words", config(), executive=True, budget_seconds=1.5))
        self.assertEqual(llm.last_local_finish_reason(), "model_unavailable")
        self.assertEqual(len(self.engine.calls), 1, "a take inside the minute asked the absent engine")


if __name__ == "__main__":
    unittest.main()
