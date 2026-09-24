from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from knight_flow.mac_support import IS_MAC


@unittest.skipUnless(IS_MAC, "system-audio capture on macOS")
class ExplicitMacSystemAudioTests(unittest.TestCase):
    """Virtual inputs stay selectable; system capture uses the native adapter.

    The old implicit microphone fallback was deliberately retired by X588.
    Missing system capture must never quietly become a one-sided recording.
    """

    def test_a_virtual_device_is_recognised(self) -> None:
        from knight_flow import mac_support as ms

        devices = [
            {"name": "MacBook Air Microphone", "max_input_channels": 1},
            {"name": "BlackHole 2ch", "max_input_channels": 2},
        ]
        sd = MagicMock()
        sd.query_devices.return_value = devices
        with patch.dict("sys.modules", {"sounddevice": sd}):
            self.assertEqual(ms.find_loopback_input_device(), 1)

    def test_output_only_virtual_devices_are_skipped(self) -> None:
        """A device with no input channels cannot be recorded from, whatever
        it is called."""
        from knight_flow import mac_support as ms

        sd = MagicMock()
        sd.query_devices.return_value = [{"name": "BlackHole 2ch", "max_input_channels": 0}]
        with patch.dict("sys.modules", {"sounddevice": sd}):
            self.assertIsNone(ms.find_loopback_input_device())

    def test_a_machine_without_one_reports_none(self) -> None:
        from knight_flow import mac_support as ms

        sd = MagicMock()
        sd.query_devices.return_value = [
            {"name": "MacBook Air Microphone", "max_input_channels": 1},
            {"name": "Scarlett Solo 4th Gen", "max_input_channels": 4},
        ]
        with patch.dict("sys.modules", {"sounddevice": sd}):
            self.assertIsNone(ms.find_loopback_input_device())

    def test_meeting_uses_the_native_system_adapter(self):
        from knight_flow.meeting import MeetingRecorder
        recorder=MeetingRecorder({'meeting':{'source':'system'}},on_status=MagicMock(),on_line=MagicMock())
        stream=MagicMock(samplerate=48000,channels=2)
        with patch('knight_flow.mac_system_audio.MacLoopbackStream',return_value=stream) as native:
            self.assertIs(recorder._open_stream(MagicMock()),stream)
        native.assert_called_once()
        self.assertTrue(recorder.using_loopback)
        self.assertEqual((recorder.sample_rate,recorder.channels),(48000,2))

    def test_system_audio_failure_never_falls_back_to_a_microphone(self):
        from knight_flow.meeting import MeetingRecorder
        recorder=MeetingRecorder({'meeting':{'source':'system'}},on_status=MagicMock(),on_line=MagicMock())
        with patch('knight_flow.mac_system_audio.MacLoopbackStream',side_effect=RuntimeError('fixture unavailable')):
            with patch('knight_flow.audio_input.open_raw_input_stream') as microphone:
                with self.assertRaisesRegex(RuntimeError,'fixture unavailable'):
                    recorder._open_stream(MagicMock())
                microphone.assert_not_called()

    def test_scribe_system_source_uses_the_same_native_adapter(self):
        import tempfile
        from pathlib import Path
        from knight_flow.scribe import ScribeRecorder
        from knight_flow.mic_registry import MicrophoneRegistry
        stream=MagicMock(samplerate=48000,channels=2,active=True)
        registry=MicrophoneRegistry()
        with tempfile.TemporaryDirectory() as folder:
            with patch('knight_flow.config.app_dir',return_value=Path(folder)),patch('knight_flow.mic_registry.microphone_registry',return_value=registry):
                with patch('knight_flow.mac_system_audio.MacLoopbackStream',return_value=stream) as native:
                    with patch('knight_flow.audio_input.open_raw_input_stream') as microphone:
                        recorder=ScribeRecorder({'scribe':{'source':'system'}})
                        try:recorder.start()
                        finally:recorder.stop()
                        native.assert_called_once();microphone.assert_not_called()
                        stream.start.assert_called_once();stream.close.assert_called_once()
                        self.assertFalse(registry.is_active())

    def test_missing_native_component_has_an_explicit_remedy(self):
        from knight_flow.mac_system_audio import MacLoopbackStream
        stream=MacLoopbackStream(MagicMock())
        stream.helper=MagicMock();stream.helper.is_file.return_value=False
        with self.assertRaisesRegex(RuntimeError,'Repair or update Talk DAT'):
            stream.start()


if __name__=='__main__':unittest.main()
