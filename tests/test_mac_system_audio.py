import io,struct,subprocess,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from knight_flow.mac_system_audio import MacLoopbackStream,packets


def packet(kind,body=b''):
    return struct.pack('<I',len(body)+1)+bytes([kind])+body


class MacSystemAudioTests(unittest.TestCase):
    def test_bounded_packets_preserve_pcm_and_control_messages(self):
        raw=b'\0\x01\0\x02'*400
        self.assertEqual(list(packets(io.BytesIO(packet(1)+packet(2,raw)+packet(4)))),[(1,b''),(2,raw),(4,b'')])
    def test_fragmented_reads_are_reassembled(self):
        class Fragmented(io.BytesIO):
            def read(self,count):return super().read(min(2,count))
        self.assertEqual(list(packets(Fragmented(packet(2,b'1234')))),[(2,b'1234')])
    def test_malformed_or_oversized_packets_are_refused(self):
        for raw in (b'a',struct.pack('<I',0),struct.pack('<I',65538),struct.pack('<I',1),packet(9),packet(1,b'a'),packet(2,b'a'),packet(2),packet(3,b'a'*65),packet(4,b'a')):
            with self.subTest(raw=raw[:12]),self.assertRaises(ValueError):list(packets(io.BytesIO(raw)))
    def test_missing_component_never_launches(self):
        stream=MacLoopbackStream(Mock());stream.helper=Mock();stream.helper.is_file.return_value=False
        with patch('knight_flow.mac_system_audio.subprocess.Popen') as launch,self.assertRaisesRegex(RuntimeError,'component is missing'):stream.start()
        launch.assert_not_called()
    def test_permission_error_is_actionable_and_does_not_open_microphone(self):
        stream=MacLoopbackStream(Mock());stream.process=Mock(stdout=io.BytesIO(packet(3,b'permission')))
        stream._receive();self.assertIn('System Settings',stream.error);self.assertFalse(stream.active);stream.callback.assert_not_called()
    def test_unknown_error_does_not_expose_helper_details(self):
        stream=MacLoopbackStream(Mock());stream.process=Mock(stdout=io.BytesIO(packet(3,b'/private/device/trace')))
        stream._receive();self.assertNotIn('/private',stream.error);self.assertTrue(stream.error)
    def test_callback_failure_closes_input_to_end_helper(self):
        stream=MacLoopbackStream(Mock(side_effect=OSError('disk full')));stream.process=Mock(stdout=io.BytesIO(packet(2,b'1234')))
        stream._receive();self.assertTrue(stream.error);stream.process.stdin.close.assert_called_once()
    def test_unexpected_eof_is_never_success(self):
        stream=MacLoopbackStream(Mock());stream.process=Mock(stdout=io.BytesIO())
        stream._receive();self.assertIn('unexpectedly',stream.error)
    def test_requested_stop_does_not_report_false_interruption(self):
        stream=MacLoopbackStream(Mock());stream.process=Mock(stdout=io.BytesIO(packet(4)));stream._stopping.set()
        stream._receive();self.assertEqual(stream.error,'')
    def test_hung_helper_is_terminated_then_killed_before_close_receipt(self):
        stream=MacLoopbackStream(Mock());stream.process=Mock();stream.process.poll.return_value=None
        stream.process.wait.side_effect=[subprocess.TimeoutExpired('helper',3),subprocess.TimeoutExpired('helper',2),0]
        stream.close();stream.process.terminate.assert_called_once();stream.process.kill.assert_called_once();self.assertTrue(stream._closed)
    def test_failed_kill_does_not_claim_closed(self):
        stream=MacLoopbackStream(Mock());stream.process=Mock();stream.process.poll.return_value=None
        stream.process.wait.side_effect=subprocess.TimeoutExpired('helper',3)
        with self.assertRaises(subprocess.TimeoutExpired):stream.close()
        self.assertFalse(stream._closed)
    def test_close_is_idempotent_without_a_process(self):
        stream=MacLoopbackStream(Mock());stream.close();stream.close();self.assertTrue(stream._closed)
    def test_macos_dispatch_uses_native_adapter(self):
        from knight_flow.system_audio import open_loopback_stream
        with patch('knight_flow.system_audio.sys.platform','darwin'):
            self.assertIsInstance(open_loopback_stream(Mock()),MacLoopbackStream)
