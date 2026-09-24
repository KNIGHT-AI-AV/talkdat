from __future__ import annotations

import sys
import types
import unittest

import knight_flow.audio_input as audio_input
from knight_flow.audio_input import (
    input_callback_problem,
    input_stream_active,
    likely_has_input_signal,
    low_confidence_input_name,
    open_raw_input_stream,
    pcm_rms_level,
    resolve_input_device,
)


class AudioInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_sounddevice = sys.modules.get("sounddevice")

    def tearDown(self) -> None:
        if self._old_sounddevice is None:
            sys.modules.pop("sounddevice", None)
        else:
            sys.modules["sounddevice"] = self._old_sounddevice

    def _fake_sounddevice(self, devices: list[dict[str, object]]) -> None:
        sys.modules["sounddevice"] = types.SimpleNamespace(query_devices=lambda: devices)

    def test_audio_backend_warmup_initializes_portaudio_before_first_capture(self) -> None:
        calls: list[str] = []
        sys.modules["sounddevice"] = types.SimpleNamespace(
            query_devices=lambda: calls.append("query") or [{"name": "Studio Mic", "max_input_channels": 1}]
        )

        self.assertTrue(
            hasattr(audio_input, "warm_audio_input_backend"),
            "The microphone backend must have an explicit startup warmup path.",
        )
        elapsed_ms = audio_input.warm_audio_input_backend()

        self.assertEqual(calls, ["query"])
        self.assertGreaterEqual(elapsed_ms, 0.0)

    def test_numeric_device_is_validated_before_use(self) -> None:
        self._fake_sounddevice(
            [
                {"name": "Speakers", "max_input_channels": 0},
                {"name": "Studio Mic", "max_input_channels": 1},
            ]
        )
        self.assertEqual(resolve_input_device("1"), 1)

    def test_stale_numeric_device_falls_back_to_default(self) -> None:
        self._fake_sounddevice([{"name": "Default Mic", "max_input_channels": 1}])
        self.assertIsNone(resolve_input_device("7"))

    def test_output_only_numeric_device_falls_back_to_default(self) -> None:
        self._fake_sounddevice([{"name": "Speakers", "max_input_channels": 0}])
        self.assertIsNone(resolve_input_device("0"))

    def test_name_lookup_uses_input_devices_only(self) -> None:
        self._fake_sounddevice(
            [
                {"name": "Talk Dat Monitor", "max_input_channels": 0},
                {"name": "Talk Dat Mic", "max_input_channels": 1},
            ]
        )
        self.assertEqual(resolve_input_device("talk dat"), 1)

    def test_labeled_device_uses_matching_index_when_name_still_matches(self) -> None:
        self._fake_sounddevice(
            [
                {"name": "Default Mic", "max_input_channels": 1},
                {"name": "Studio Mic", "max_input_channels": 1},
            ]
        )
        self.assertEqual(resolve_input_device("1: Studio Mic"), 1)

    def test_labeled_device_recovers_when_index_changes(self) -> None:
        self._fake_sounddevice(
            [
                {"name": "Default Mic", "max_input_channels": 1},
                {"name": "Studio Mic", "max_input_channels": 1},
            ]
        )
        self.assertEqual(resolve_input_device("7: Studio Mic"), 1)

    def test_labeled_device_avoids_wrong_mic_when_name_disappears(self) -> None:
        self._fake_sounddevice(
            [
                {"name": "Default Mic", "max_input_channels": 1},
                {"name": "Different Mic", "max_input_channels": 1},
            ]
        )
        self.assertIsNone(resolve_input_device("1: Studio Mic"))

    def test_likely_input_signal_rejects_digital_silence(self) -> None:
        self.assertEqual(pcm_rms_level(b"\x00\x00" * 1600), 0.0)
        self.assertFalse(likely_has_input_signal(b"\x00\x00" * 1600))

    def test_likely_input_signal_detects_quiet_audio(self) -> None:
        quiet_sample = (96).to_bytes(2, "little", signed=True)
        self.assertTrue(likely_has_input_signal(quiet_sample * 1600))

    def test_low_confidence_input_names_cover_controller_virtual_and_loopback(self) -> None:
        self.assertTrue(low_confidence_input_name("Headset Microphone (DualSense Controller)"))
        self.assertTrue(low_confidence_input_name("Loop-back 1/2"))
        self.assertTrue(low_confidence_input_name("Oculus Virtual Audio Device"))
        self.assertFalse(low_confidence_input_name("Studio Mic"))

    def test_raw_stream_falls_back_to_device_native_rate(self) -> None:
        attempts: list[tuple[int | None, int]] = []

        class FakeStream:
            def __init__(self, **kwargs: object) -> None:
                attempts.append((kwargs.get("device"), int(kwargs.get("samplerate", 0))))
                if kwargs.get("samplerate") == 16000:
                    raise RuntimeError("invalid sample rate")

        fake_sd = types.SimpleNamespace(
            default=types.SimpleNamespace(device=[1, 2]),
            query_devices=lambda *args, **kwargs: {"name": "Studio Mic", "max_input_channels": 1, "default_samplerate": 48000},
            RawInputStream=lambda **kwargs: FakeStream(**kwargs),
        )
        sys.modules["sounddevice"] = fake_sd

        stream, rate, channels, device = open_raw_input_stream(
            samplerate=16000,
            channels=1,
            device=1,
            callback=lambda *args: None,
        )

        self.assertIsInstance(stream, FakeStream)
        self.assertEqual(rate, 48000)
        self.assertEqual(channels, 1)
        self.assertEqual(device, 1)
        self.assertEqual(attempts[:2], [(1, 16000), (1, 48000)])

    def test_raw_stream_falls_back_to_default_device_when_selected_device_fails(self) -> None:
        attempts: list[tuple[int | None, int]] = []

        class FakeStream:
            def __init__(self, **kwargs: object) -> None:
                device = kwargs.get("device")
                rate = int(kwargs.get("samplerate", 0))
                attempts.append((device, rate))
                if device == 7:
                    raise RuntimeError("device unavailable")
                if rate == 16000:
                    raise RuntimeError("invalid sample rate")

        fake_sd = types.SimpleNamespace(
            default=types.SimpleNamespace(device=[1, 2]),
            query_devices=lambda *args, **kwargs: {"name": "Default Mic", "max_input_channels": 1, "default_samplerate": 44100},
            RawInputStream=lambda **kwargs: FakeStream(**kwargs),
        )
        sys.modules["sounddevice"] = fake_sd

        _stream, rate, _channels, device = open_raw_input_stream(
            samplerate=16000,
            channels=1,
            device=7,
            callback=lambda *args: None,
        )

        self.assertEqual(rate, 44100)
        self.assertIsNone(device)
        self.assertIn((7, 16000), attempts)
        self.assertIn((None, 44100), attempts)

    def test_low_confidence_default_yields_to_physical_microphone(self) -> None:
        attempts: list[int | None] = []
        devices = [
            {"name": "Headset Microphone (DualSense Controller)", "max_input_channels": 1, "default_samplerate": 48000},
            {"name": "Studio Mic", "max_input_channels": 1, "default_samplerate": 48000},
        ]

        class FakeStream:
            def __init__(self, **kwargs: object) -> None:
                attempts.append(kwargs.get("device"))

        def query_devices(device: object = None, **kwargs: object) -> object:
            if kwargs.get("kind") == "input":
                return devices[0]
            if device is None:
                return devices
            return devices[int(device)]

        sys.modules["sounddevice"] = types.SimpleNamespace(
            default=types.SimpleNamespace(device=[0, 2]),
            query_devices=query_devices,
            RawInputStream=lambda **kwargs: FakeStream(**kwargs),
        )

        _stream, _rate, _channels, device = open_raw_input_stream(
            samplerate=48000,
            channels=1,
            callback=lambda *args: None,
        )

        self.assertEqual(device, 1)
        self.assertEqual(attempts[0], 1)

    def test_input_callback_problem_normalizes_portaudio_status(self) -> None:
        self.assertEqual(input_callback_problem(None), "")
        self.assertEqual(input_callback_problem("input overflow"), "input overflow")

    def test_inactive_stream_is_detected_without_requiring_backend_property(self) -> None:
        self.assertFalse(input_stream_active(types.SimpleNamespace(active=False)))
        self.assertTrue(input_stream_active(object()))


if __name__ == "__main__":
    unittest.main()
