import unittest
from unittest.mock import patch

from cbus_toolkit.pci_local_options import PCILocalOptionsReader, parse_local_options
from tests.test_pci_serial_address_transport import Clock, FakeSocket, peer


REPLY = b'g.82420537\r\n'
REQUEST = b'\\4610001A4201g\r'


class LocalOptionsTests(unittest.TestCase):
    def test_literal_fragmented_and_checksum_requests_never_write(self):
        for checksum, request in ((False, REQUEST), (True, b'\\4610001A42014Dg\r')):
            with self.subTest(checksum=checksum), peer([REPLY[:1], REPLY[1:5], REPLY[5:]]) as (endpoint, state):
                reader = PCILocalOptionsReader(*endpoint, local_unit=16, response_timeout=.025,
                                               overall_timeout=.5, command_checksum=checksum)
                result = reader.read_options()
            self.assertTrue(result.complete); self.assertEqual(result.value, 5)
            self.assertEqual(state['requests'], [request]); self.assertEqual(state['extra'], b'')
            self.assertFalse(result.as_dict()['options_changed'])
            with self.assertRaises(RuntimeError): reader.read_options()

    def test_whole_capture_rejects_foreign_partial_multiple_wrong_count_and_checksum(self):
        self.assertEqual(parse_local_options(b'g.82420735\r\n', local_unit=16), 7)
        for raw in (b'', b'g.', REPLY+b'82', REPLY+REPLY[2:], b'h.'+REPLY[2:],
                    b'g#'+REPLY[2:], REPLY[2:]+b'g.', b'g.82420538\r\n',
                    b'g.8342050630\r\n', b'g.82110568\r\n', b'g.\\82420537\r\n',
                    b'g.8610100082420537\r\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): parse_local_options(raw,local_unit=16)

    def run_fake(self, reader, clock, sock):
        with patch.object(reader, '_make_socket', return_value=sock), \
                patch('cbus_toolkit.pci_local_options.time.monotonic', side_effect=clock):
            return reader.read_options()

    def test_prefix_on_eof_and_byte_limit_never_completes(self):
        for chunks, termination in (((REPLY,b''),'disconnected'),((REPLY+b' '*4096,),'byte_limit')):
            clock=Clock();sock=FakeSocket(clock,chunks=chunks)
            result=self.run_fake(PCILocalOptionsReader('127.0.0.1',local_unit=16),clock,sock)
            self.assertFalse(result.complete);self.assertEqual(result.termination,termination)
            self.assertEqual(sum(x[0]=='sendall' for x in sock.calls),1)

    def test_late_connect_and_send_never_receive(self):
        for phase in ('connect','send'):
            clock=Clock()
            def delay():clock.value+=5
            sock=FakeSocket(clock,**{phase:delay})
            result=self.run_fake(PCILocalOptionsReader('127.0.0.1',local_unit=16),clock,sock)
            self.assertFalse(result.complete);self.assertFalse(any(x[0]=='recv' for x in sock.calls))
            self.assertEqual(sum(x[0]=='sendall' for x in sock.calls),int(phase=='send'))

    def test_interrupt_retains_first_exception_and_bytes_despite_close_failure(self):
        clock=Clock();interrupt=KeyboardInterrupt('first')
        sock=FakeSocket(clock,chunks=(REPLY,interrupt),close=SystemExit('second'))
        reader=PCILocalOptionsReader('127.0.0.1',local_unit=16)
        with self.assertRaises(KeyboardInterrupt) as caught:self.run_fake(reader,clock,sock)
        self.assertIs(caught.exception,interrupt)
        self.assertEqual(interrupt.pci_local_options_observation['received_hex'],REPLY.hex())
        self.assertFalse(reader.last_observation.connection_closed)
        self.assertEqual([x[0] for x in sock.calls][-1],'close')

    def test_final_clock_interruption_preserves_recorded_byte(self):
        clock=Clock();sock=FakeSocket(clock,chunks=(REPLY,))
        # Trigger only after close, independently of implementation clock count.
        interrupt=KeyboardInterrupt('clock')
        def close():clock.fail_at[clock.calls+1]=interrupt
        sock.close_effect=close;reader=PCILocalOptionsReader('127.0.0.1',local_unit=16)
        with self.assertRaises(KeyboardInterrupt) as caught:self.run_fake(reader,clock,sock)
        self.assertIs(caught.exception,interrupt);self.assertEqual(reader.last_observation.value,5)
        self.assertTrue(reader.last_observation.capture_complete)
