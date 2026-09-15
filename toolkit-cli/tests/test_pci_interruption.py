"""Child observations survive receive, cleanup and final timing interruptions."""
import socket
import types
import unittest
from unittest.mock import patch

from cbus_toolkit import pci_inventory, pci_serials
from tests.test_pci_inventory import FIRST, FULL, MIDDLE, LAST
from tests.test_pci_serials import SERIAL_A, SERIAL_B


class Clock:
    def __init__(self, final_error=None):
        self.value = 0.0
        self.closed = False
        self.final_error = final_error

    def monotonic(self):
        if self.closed and self.final_error is not None:
            raise self.final_error
        return self.value


class Stream:
    def __init__(self, clock, replies, close_error=None):
        self.clock, self.replies, self.close_error = clock, list(replies), close_error
        self.calls = []

    def settimeout(self, value): self.calls.append(('settimeout', value))
    def connect(self, endpoint): self.calls.append(('connect', endpoint))
    def sendall(self, data): self.calls.append(('sendall', data))

    def recv(self, count):
        self.calls.append(('recv', count))
        self.clock.value += .01 if self.replies else .1
        event = self.replies.pop(0) if self.replies else socket.timeout()
        if isinstance(event, BaseException): raise event
        return event

    def close(self):
        self.calls.append(('close',))
        self.clock.closed = True
        if self.close_error: raise self.close_error


class PCIInterruptionTests(unittest.TestCase):
    def cases(self):
        serial = pci_serials.PCISerialCollector('127.0.0.1', local_unit=16,
                                              quiet_period=.04, overall_timeout=.5, confirmation_timeout=.2)
        mmi = pci_inventory.PCIMMICollector('127.0.0.1', local_unit=16)
        return ((pci_serials, serial, lambda: serial.collect_serials(255), b'g.'+SERIAL_A,
                 b'g.'+SERIAL_A, 'pci_serial_observation'),
                (pci_inventory, mmi, mmi.collect_mmi, b'g.'+FIRST,
                 b'g.'+FULL, 'pci_mmi_observation'))

    def test_receive_interruption_keeps_first_exception_through_close_and_final_clock_failures(self):
        for module, subject, collect, partial, _, attribute in self.cases():
            for error_type in (KeyboardInterrupt, SystemExit):
                with self.subTest(module=module.__name__, error=error_type.__name__):
                    # Build a fresh one-shot subject for each interruption.
                    if module is pci_serials:
                        subject = module.PCISerialCollector('127.0.0.1',local_unit=16)
                        collect = lambda: subject.collect_serials(255)
                    else:
                        subject = module.PCIMMICollector('127.0.0.1',local_unit=16)
                        collect = subject.collect_mmi
                    original = error_type('receive interrupted')
                    clock = Clock(KeyboardInterrupt('final clock interrupted'))
                    stream = Stream(clock, [partial, original], SystemExit('close interrupted'))
                    with patch.object(module, 'time', types.SimpleNamespace(monotonic=clock.monotonic)), \
                            patch.object(subject, '_make_socket', return_value=stream):
                        with self.assertRaises(error_type) as caught: collect()
                    self.assertIs(caught.exception, original)
                    result = subject.last_observation
                    self.assertIsNotNone(result)
                    self.assertEqual(result.received, partial)
                    self.assertFalse(result.complete)
                    self.assertFalse(result.connection_closed)
                    self.assertEqual(result.elapsed, .01)  # Last clock read before the interrupted recv.
                    self.assertEqual(getattr(original, attribute), result.as_dict())
                    self.assertTrue(any('close interrupted' in error for error in result.errors))
                    self.assertTrue(any('final clock interrupted' in error for error in result.errors))
                    self.assertEqual(stream.calls[-1], ('close',))
                    calls = list(stream.calls)
                    with self.assertRaises(RuntimeError): collect()
                    self.assertEqual(stream.calls, calls)
                    self.assertEqual(sum(call[0] == 'sendall' for call in calls), 1)
                    self.assertEqual(sum(call[0] == 'recv' for call in calls), 2)

    def test_final_clock_interruption_retains_successful_payload_and_last_valid_elapsed(self):
        for module, subject, collect, _, complete, attribute in self.cases():
            with self.subTest(module=module.__name__):
                original = KeyboardInterrupt('final clock interrupted')
                clock = Clock(original)
                stream = Stream(clock, [complete])
                with patch.object(module, 'time', types.SimpleNamespace(monotonic=clock.monotonic)), \
                        patch.object(subject, '_make_socket', return_value=stream):
                    with self.assertRaises(KeyboardInterrupt) as caught: collect()
                self.assertIs(caught.exception, original)
                result = subject.last_observation
                self.assertEqual(result.received, complete)
                self.assertEqual(result.termination, 'interrupted')
                self.assertFalse(result.complete)
                self.assertTrue(result.connection_closed)
                self.assertEqual(result.elapsed, clock.value)
                self.assertEqual(getattr(original, attribute), result.as_dict())
                if module is pci_serials: self.assertEqual(result.serials, ('101136.1558',))
                else: self.assertTrue(result.coverage_complete)
                self.assertEqual(stream.calls[-1], ('close',))
                self.assertEqual(sum(call[0] == 'sendall' for call in stream.calls), 1)

    def test_close_interruption_is_preserved_with_completed_payload(self):
        for module, subject, collect, _, complete, attribute in self.cases():
            with self.subTest(module=module.__name__):
                original = SystemExit('close interrupted')
                clock = Clock()
                stream = Stream(clock, [complete], original)
                with patch.object(module, 'time', types.SimpleNamespace(monotonic=clock.monotonic)), \
                        patch.object(subject, '_make_socket', return_value=stream):
                    with self.assertRaises(SystemExit) as caught: collect()
                self.assertIs(caught.exception, original)
                self.assertEqual(subject.last_observation.received, complete)
                self.assertFalse(subject.last_observation.connection_closed)
                self.assertFalse(subject.last_observation.complete)
                self.assertEqual(getattr(original, attribute), subject.last_observation.as_dict())
                self.assertEqual(stream.calls[-1], ('close',))


class PCISharedDeadlineTests(unittest.TestCase):
    def subjects(self):
        serial=pci_serials.PCISerialCollector('127.0.0.1',local_unit=16,overall_timeout=2,
                                            confirmation_timeout=.4,quiet_period=.2)
        mmi=pci_inventory.PCIMMICollector('127.0.0.1',local_unit=16,overall_timeout=2,
                                        confirmation_timeout=.4,response_timeout=.4)
        return ((pci_serials,serial,lambda:serial.collect_serials(255),b'g.'+SERIAL_A,SERIAL_B),
                (pci_inventory,mmi,mmi.collect_mmi,b'g.'+FIRST,MIDDLE+LAST))

    def test_absolute_parent_expiry_before_creation_connect_or_send_never_transmits(self):
        for stage in ('before_creation','before_connect','before_send'):
            for module,subject,collect,_,_ in self.subjects():
                with self.subTest(module=module.__name__,stage=stage):
                    subject._absolute_deadline=.5
                    clock=Clock();stream=Stream(clock,[])
                    if stage=='before_creation':clock.value=.6
                    def make_socket():
                        if stage=='before_connect':clock.value=.6
                        return stream
                    def connect(endpoint):
                        stream.calls.append(('connect',endpoint))
                        if stage=='before_send':clock.value=.6
                    stream.connect=connect
                    with patch.object(module,'time',types.SimpleNamespace(monotonic=clock.monotonic)), \
                            patch.object(subject,'_make_socket',side_effect=make_socket) as factory:
                        result=collect()
                    self.assertEqual(result.termination,'overall_timeout');self.assertEqual(result.request,b'')
                    self.assertTrue(result.connection_closed)
                    self.assertFalse(any(call[0] in ('sendall','recv') for call in stream.calls))
                    if stage=='before_creation':factory.assert_not_called()
                    elif stage=='before_connect':self.assertEqual(stream.calls,[('close',)])
                    else:self.assertEqual(stream.calls[-1],('close',))

    def test_absolute_parent_deadline_limits_receive_window_despite_later_child_start(self):
        for module,subject,collect,first,last in self.subjects():
            with self.subTest(module=module.__name__):
                subject._absolute_deadline=.5
                clock=Clock();stream=Stream(clock,[]);events=iter(((.35,first),(.51,last)))
                def receive(count):
                    stream.calls.append(('recv',count))
                    clock.value,payload=next(events)
                    return payload
                stream.recv=receive
                with patch.object(module,'time',types.SimpleNamespace(monotonic=clock.monotonic)), \
                        patch.object(subject,'_make_socket',return_value=stream):
                    result=collect()
                self.assertEqual(result.termination,'late_data');self.assertFalse(result.complete)
                self.assertEqual(result.received,first+last);self.assertTrue(result.connection_closed)
                self.assertEqual(sum(call[0]=='recv' for call in stream.calls),2)
                self.assertEqual(sum(call[0]=='sendall' for call in stream.calls),1)
                self.assertTrue(all(call[1]<=.5 for call in stream.calls if call[0]=='settimeout'))
                if module is pci_serials:self.assertEqual(result.serials,('101136.1558',))
                else:self.assertEqual(result.missing_ranges,((88,256),))


if __name__ == '__main__': unittest.main()
