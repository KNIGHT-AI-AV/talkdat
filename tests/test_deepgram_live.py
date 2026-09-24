from __future__ import annotations

import asyncio
import json
import queue
import sys
import types
import unittest
from array import array
from typing import Any
from unittest.mock import patch

from knight_flow.audio_input import apply_gain
from knight_flow.deepgram_live import DeepgramLiveSession, raw_rms_level, rms_level


class FakeStream:
    def __init__(self, *, active: bool = True) -> None:
        self.active = active

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakeConnection:
    def __init__(self, websocket: "FakeWebSocket") -> None:
        self.websocket = websocket

    async def __aenter__(self) -> "FakeWebSocket":
        return self.websocket

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeWebSocket:
    def __init__(
        self,
        *,
        receive_outcome: str = "pending",
        fail_audio_send: bool = False,
        fail_keepalive: bool = False,
        finalize_results: list[str] | None = None,
        finalize_gap: float = 0.0,
    ) -> None:
        self.receive_outcome = receive_outcome
        self.fail_audio_send = fail_audio_send
        self.fail_keepalive = fail_keepalive
        # Deepgram's real finalize behaviour: after CloseStream it flushes
        # one Results message per unflushed segment, spaced in time.
        self.finalize_results = finalize_results
        self.finalize_gap = finalize_gap
        self._finalize_index = 0
        self.sent: list[bytes | str] = []
        self._receive_waiter = asyncio.Event()

    def _close_stream_sent(self) -> bool:
        return any(isinstance(p, str) and "CloseStream" in p for p in self.sent)

    def __aiter__(self) -> "FakeWebSocket":
        return self

    async def __anext__(self) -> str:
        if self.finalize_results is not None:
            while not self._close_stream_sent():
                await asyncio.sleep(0.005)
            if self._finalize_index < len(self.finalize_results):
                await asyncio.sleep(self.finalize_gap)
                payload = self.finalize_results[self._finalize_index]
                self._finalize_index += 1
                return payload
            raise StopAsyncIteration
        if self.receive_outcome == "eof":
            raise StopAsyncIteration
        if self.receive_outcome == "failure":
            raise RuntimeError("receive exploded")
        await self._receive_waiter.wait()
        raise StopAsyncIteration

    async def send(self, payload: bytes | str) -> None:
        self.sent.append(payload)
        if isinstance(payload, bytes) and self.fail_audio_send:
            raise RuntimeError("send exploded")
        if isinstance(payload, str) and self.fail_keepalive:
            message = json.loads(payload)
            if message.get("type") == "KeepAlive":
                raise RuntimeError("keepalive exploded")


class DeepgramLiveTransportTests(unittest.IsolatedAsyncioTestCase):
    def test_visual_meter_uses_raw_pcm_dynamics_independent_of_recognition_gain(self) -> None:
        samples = array("h", [900, -900] * 800).tobytes()
        amplified = apply_gain(samples, 16.0)

        self.assertGreater(rms_level(amplified), 0.90)
        self.assertLess(raw_rms_level(samples), 0.04)
        self.assertGreater(raw_rms_level(amplified), raw_rms_level(samples) * 10.0)

    def make_session(
        self,
    ) -> tuple[DeepgramLiveSession, list[str], list[str], list[str]]:
        done: list[str] = []
        errors: list[str] = []
        statuses: list[str] = []
        session = DeepgramLiveSession(
            api_key="test-key",
            params={"sample_rate": 16000, "channels": 1},
            max_seconds=3600,
            no_speech_timeout_seconds=3600,
            silence_timeout_seconds=3600,
            tail_capture_ms=0,
            min_capture_ms=0,
            on_update=lambda text, is_final: None,
            on_status=statuses.append,
            on_level=lambda level: None,
            on_done=done.append,
            on_error=errors.append,
        )
        return session, done, errors, statuses

    async def run_session(
        self,
        session: DeepgramLiveSession,
        websocket: FakeWebSocket,
        stream: FakeStream | None = None,
    ) -> None:
        fake_websockets = types.SimpleNamespace(
            connect=lambda *args, **kwargs: FakeConnection(websocket)
        )
        with (
            patch.dict(sys.modules, {"websockets": fake_websockets}),
            patch(
                "knight_flow.deepgram_live.open_raw_input_stream",
                return_value=(stream or FakeStream(), 16000, 1, None),
            ),
        ):
            try:
                # Windows' Proactor loop can occasionally spend several hundred
                # milliseconds scheduling teardown under debug/CI load.
                await asyncio.wait_for(session._run(), timeout=2.0)
            except TimeoutError:
                session.cancel()
                await asyncio.sleep(0)
                self.fail("A completed transport task left the live session running")

    def assert_degraded(self, session: DeepgramLiveSession, reason: str) -> None:
        self.assertTrue(session.transport_degraded)
        self.assertIn(reason, session.transport_degradation_reasons)

    async def test_slow_finalize_flush_is_drained_not_declared_dead(self) -> None:
        """THE long-dictation regression (field: '45 seconds to transcribe').

        After CloseStream, Deepgram flushes finals for seconds on a long
        talk. The old flat 2.0s window declared those sessions degraded and
        the whole recording was re-transcribed on the local CPU. The drain
        must keep granting windows while messages still arrive.
        """
        session, done, _errors, _statuses = self.make_session()
        session._stop_event.set()
        finals = [
            json.dumps({
                "type": "Results", "is_final": True,
                "channel": {"alternatives": [{"transcript": word}]},
            })
            for word in ("alpha", "beta", "gamma", "delta")
        ]
        with (
            patch("knight_flow.deepgram_live.RECEIVER_DRAIN_STEP", 0.06),
            patch("knight_flow.deepgram_live.RECEIVER_DRAIN_CAP", 1.5),
        ):
            # Each gap fits inside one window, but the TOTAL flush outlasts
            # a single window -- the exact shape that used to fail.
            await self.run_session(
                session,
                FakeWebSocket(finalize_results=finals, finalize_gap=0.04),
            )
        self.assertFalse(
            session.transport_degraded,
            f"drained flush must not degrade: {session.transport_degradation_reasons}",
        )
        self.assertEqual(done, ["alpha beta gamma delta"])

    async def test_genuinely_stalled_finalize_still_times_out(self) -> None:
        session, done, _errors, _statuses = self.make_session()
        session._stop_event.set()
        with (
            patch("knight_flow.deepgram_live.RECEIVER_DRAIN_STEP", 0.05),
            patch("knight_flow.deepgram_live.RECEIVER_DRAIN_CAP", 0.3),
        ):
            await self.run_session(session, FakeWebSocket())
        self.assert_degraded(session, "receiver_timeout")
        self.assertEqual(done, [""])

    async def test_clean_receiver_eof_ends_live_session(self) -> None:
        session, done, errors, _statuses = self.make_session()

        await self.run_session(session, FakeWebSocket(receive_outcome="eof"))

        self.assert_degraded(session, "receiver_eof")
        self.assertEqual(done, [""])
        self.assertTrue(errors)

    async def test_sender_failure_ends_live_session(self) -> None:
        session, done, errors, _statuses = self.make_session()
        session._put_audio(b"audio")

        await self.run_session(session, FakeWebSocket(fail_audio_send=True))

        self.assert_degraded(session, "sender_failure")
        self.assertEqual(done, [""])
        self.assertTrue(any("send exploded" in error for error in errors))

    async def test_receiver_failure_ends_live_session(self) -> None:
        session, done, errors, _statuses = self.make_session()

        await self.run_session(session, FakeWebSocket(receive_outcome="failure"))

        self.assert_degraded(session, "receiver_failure")
        self.assertEqual(done, [""])
        self.assertTrue(any("receive exploded" in error for error in errors))

    async def test_lost_microphone_ends_stream_and_arms_audio_recovery(self) -> None:
        session, done, errors, _statuses = self.make_session()

        await self.run_session(
            session,
            FakeWebSocket(),
            stream=FakeStream(active=False),
        )

        self.assert_degraded(session, "input_lost")
        self.assertEqual(done, [""])
        self.assertTrue(any("Microphone input stopped unexpectedly" in error for error in errors))

    async def test_keepalive_failure_ends_live_session(self) -> None:
        session, done, errors, _statuses = self.make_session()
        websocket = FakeWebSocket(fail_keepalive=True)
        real_sleep = asyncio.sleep

        async def accelerated_sleep(delay: float) -> None:
            await real_sleep(0 if delay == 8 else delay)

        with patch("knight_flow.deepgram_live.asyncio.sleep", new=accelerated_sleep):
            await self.run_session(session, websocket)

        self.assert_degraded(session, "keepalive_failure")
        self.assertEqual(done, [""])
        self.assertTrue(any("keepalive exploded" in error for error in errors))

    async def test_intentional_stop_accepts_clean_keepalive_completion(self) -> None:
        session, _done, errors, _statuses = self.make_session()
        session.stop()
        keepalive = asyncio.create_task(asyncio.sleep(0))
        await keepalive

        failed = session._observe_transport_tasks(
            {"keepalive": keepalive},
            clean_completions={"keepalive"} if session._stop_event.is_set() else None,
        )

        self.assertFalse(failed)
        self.assertEqual(errors, [])
        self.assertFalse(session.transport_degraded)

    async def test_warning_is_surfaced_without_becoming_an_error(self) -> None:
        session, _done, errors, statuses = self.make_session()

        session._handle_message(json.dumps({"type": "Warning", "message": "rate limited soon"}))

        self.assertEqual(statuses, ["warning:rate limited soon"])
        self.assertEqual(errors, [])
        self.assertFalse(session._stop_event.is_set())

        session._handle_message(json.dumps({"type": "Error", "message": "request failed"}))

        self.assertEqual(errors, ["request failed"])

    async def test_full_audio_queue_records_dropped_chunk(self) -> None:
        session, _done, _errors, _statuses = self.make_session()
        session._audio_queue = queue.Queue(maxsize=1)
        session._put_audio(b"first")

        session._put_audio(b"dropped")

        self.assertEqual(session.audio_queue_drops, 1)
        self.assert_degraded(session, "audio_queue_overflow")
        self.assertEqual(session._audio_queue.get_nowait(), b"first")

    async def test_final_sentinel_records_evicted_audio_and_reaches_sender(self) -> None:
        session, _done, _errors, _statuses = self.make_session()
        session._audio_queue = queue.Queue(maxsize=1)
        session._put_audio(b"evicted")

        session._put_audio(None)

        self.assertEqual(session.audio_queue_drops, 1)
        self.assert_degraded(session, "audio_queue_overflow")
        self.assertIsNone(session._audio_queue.get_nowait())


if __name__ == "__main__":
    unittest.main()
