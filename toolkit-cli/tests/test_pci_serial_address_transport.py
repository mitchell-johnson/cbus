"""One co transport: literal peers, deadlines, interruptions and independent topology."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import threading
import time
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.pci_serial_address_transport import PCISerialAddressTransport
from cbus_toolkit.pci_full_inventory import PCIInventoryCollector
from cbus_toolkit.simulator_duplicate_addressing import SerialAddressFixture, SerialAddressFault
from tests.test_simulator_duplicate_addressing import fixture, A, B, CO_A, RECEIPT_A


WRONG_SOURCE=b'g.86091000870018B106160000F5\r\n'


@contextmanager
def peer(responses, *, close_early=False):
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(3)
    state={'requests':[],'extra':b'','closed':False,'errors':[]}
    def serve():
        try:
            with listener.accept()[0] as connection:
                connection.settimeout(3);request=b''
                while not request.endswith(b'\r'):
                    data=connection.recv(1024)
                    if not data:raise AssertionError('Disconnected before complete request')
                    request+=data
                state['requests'].append(request)
                for item in responses:
                    if isinstance(item,tuple):time.sleep(item[0]);item=item[1]
                    connection.sendall(item)
                if close_early:return
                while data:=connection.recv(1024):state['extra']+=data
                state['closed']=True
        except (BrokenPipeError,ConnectionResetError):state['closed']=True
        except BaseException as error:state['errors'].append(repr(error))
    thread=threading.Thread(target=serve);thread.start()
    try:yield listener.getsockname(),state
    finally:
        thread.join(4);listener.close()
        if thread.is_alive():raise AssertionError('Literal peer thread did not finish')
        if state['errors']:raise AssertionError(state['errors'])


class Clock:
    def __init__(self):self.value=100.;self.calls=0;self.fail_at={}
    def __call__(self):
        self.calls+=1
        if self.calls in self.fail_at:raise self.fail_at[self.calls]
        return self.value


class FakeSocket:
    def __init__(self,clock,*,chunks=(RECEIPT_A,),connect=None,send=None,close=None,settimeout=None):
        self.clock=clock;self.chunks=list(chunks);self.calls=[];self.timeout=1.
        self.connect_effect=connect;self.send_effect=send;self.close_effect=close;self.timeout_effect=settimeout
    def effect(self,value):
        if isinstance(value,BaseException):raise value
        if callable(value):value()
    def settimeout(self,value):
        self.calls.append(('settimeout',value));self.timeout=value;self.effect(self.timeout_effect)
    def connect(self,endpoint):self.calls.append(('connect',endpoint));self.effect(self.connect_effect)
    def sendall(self,data):self.calls.append(('sendall',data));self.effect(self.send_effect)
    def recv(self,size):
        self.calls.append(('recv',size))
        if self.chunks:
            value=self.chunks.pop(0)
            if isinstance(value,BaseException):raise value
            if callable(value):return value()
            if len(value)>size:self.chunks.insert(0,value[size:]);return value[:size]
            return value
        self.clock.value+=self.timeout
        raise socket.timeout('window')
    def close(self):self.calls.append(('close',));self.effect(self.close_effect)


def transport(endpoint=('127.0.0.1',10001),**options):
    return PCISerialAddressTransport(*endpoint,**(dict(local_unit=16,response_timeout=.04,overall_timeout=1)|options))


class SerialAddressTransportTests(unittest.TestCase):
    def fake(self,**options):
        clock=Clock();sock=FakeSocket(clock,**options);client=transport()
        return clock,sock,client

    def run_fake(self,clock,sock,client):
        with patch.object(client,'_make_socket',return_value=sock),\
                patch('cbus_toolkit.pci_serial_address_transport.time.monotonic',side_effect=clock):
            return client.send_serial_address(A,6)

    def test_native_default_window_waits_after_one_literal_receipt_and_never_retries(self):
        with peer([RECEIPT_A]) as (endpoint,state):
            client=PCISerialAddressTransport(*endpoint,local_unit=16)
            start=time.monotonic();result=client.send_serial_address(A,6);elapsed=time.monotonic()-start
        self.assertEqual(state['requests'],[CO_A]);self.assertEqual(state['extra'],b'');self.assertTrue(state['closed'])
        self.assertGreaterEqual(elapsed,2.);self.assertLess(elapsed,3.)
        self.assertTrue(result.capture_complete);self.assertTrue(result.receipt.matched)
        self.assertTrue(result.send_attempted);self.assertTrue(result.send_completed)
        self.assertEqual(result.termination,'response_window_elapsed');self.assertTrue(result.connection_closed)
        self.assertFalse(result.movement_verified);self.assertFalse(result.persistence_verified)
        document=json.loads(json.dumps(result.as_dict()))
        self.assertEqual(document['correlation_status'],'matched');self.assertIsNone(document['sent_byte_count'])
        self.assertFalse(document['inventory_performed']);self.assertEqual(document['automatic_retries'],0)
        self.assertTrue(document['timing']['native_response_timeout'])
        with self.assertRaises(RuntimeError):client.send_serial_address(A,6)

    def test_fragmented_srchk_and_late_conflicting_frame_are_whole_capture(self):
        with peer([RECEIPT_A[:1],RECEIPT_A[1:5],RECEIPT_A[5:17],RECEIPT_A[17:],(.025,WRONG_SOURCE[2:])]) as (endpoint,state):
            result=transport(endpoint,command_checksum=True,response_timeout=.08).send_serial_address(A,6)
        self.assertEqual(state['requests'],[b'\\05FF000F0018B106160615EDg\r'])
        self.assertTrue(result.capture_complete);self.assertEqual(result.receipt.status,'ambiguous')
        self.assertEqual(len(result.receipt.replies),2);self.assertFalse(result.receipt.matched)

    def test_valid_prefix_does_not_hide_trailing_partial_or_malformed_data(self):
        for suffix,status in ((b'86','incomplete'),(b'XX\r\n','invalid')):
            with self.subTest(suffix=suffix),peer([RECEIPT_A,(.015,suffix)]) as (endpoint,state):
                result=transport(endpoint).send_serial_address(A,6)
            self.assertTrue(result.capture_complete);self.assertEqual(result.receipt.status,status)
            self.assertEqual(result.received,RECEIPT_A+suffix);self.assertEqual(len(state['requests']),1)

    def test_missing_wrong_and_rejected_receipts_wait_full_window_without_followup(self):
        for response,status in ((b'g.','incomplete'),(WRONG_SOURCE,'unverified'),(b'g#','rejected'),(b'','incomplete')):
            with self.subTest(response=response),peer([response]) as (endpoint,state):
                start=time.monotonic();result=transport(endpoint).send_serial_address(A,6)
            self.assertGreaterEqual(time.monotonic()-start,.04)
            self.assertTrue(result.capture_complete);self.assertEqual(result.receipt.status,status)
            self.assertEqual(state['requests'],[CO_A]);self.assertFalse(result.movement_verified)

    def test_eof_after_matched_prefix_is_incomplete_even_with_correlated_packet(self):
        with peer([RECEIPT_A],close_early=True) as (endpoint,state):
            result=transport(endpoint).send_serial_address(A,6)
        self.assertEqual(result.termination,'disconnected');self.assertFalse(result.capture_complete)
        self.assertTrue(result.receipt.matched);self.assertEqual(state['requests'],[CO_A])

    def test_byte_limit_keeps_prefix_correlation_separate_from_capture_completeness(self):
        clock,sock,client=self.fake(chunks=(RECEIPT_A+b'86',));client.max_bytes=len(RECEIPT_A)
        result=self.run_fake(clock,sock,client)
        self.assertEqual(result.termination,'byte_limit');self.assertFalse(result.capture_complete)
        self.assertEqual(result.received,RECEIPT_A);self.assertEqual(result.bytes_received,len(RECEIPT_A)+1)
        self.assertTrue(result.receipt.matched);self.assertTrue(result.connection_closed)
        self.assertEqual([call for call in sock.calls if call[0]=='sendall'],[('sendall',CO_A)])

    def test_invalid_constructor_and_request_preflight_never_create_socket(self):
        bad=({'host':'localhost'},{'host':'127.0.0.1%scope'},{'port':True},{'local_unit':True},
             {'response_timeout':0},{'response_timeout':float('nan')},{'overall_timeout':.04},
             {'max_bytes':4097},{'max_bytes':True},{'confirmation':b'gg'},{'command_checksum':1})
        with patch('cbus_toolkit.pci_serial_address_transport.socket.socket',side_effect=AssertionError('No socket')):
            for values in bad:
                args=dict(host='127.0.0.1',port=10001,local_unit=16,response_timeout=.04,overall_timeout=1);args.update(values)
                with self.subTest(values=values),self.assertRaises(ValueError):PCISerialAddressTransport(**args)
            client=transport()
            for serial,target in (('0.0',6),(A,255),(A,True),('1.4096',6)):
                with self.subTest(serial=serial,target=target),self.assertRaises(ValueError):client.send_serial_address(serial,target)
        self.assertFalse(client._used)

    def test_connection_errors_have_no_send_and_partial_send_errors_never_replay(self):
        for phase in ('connect','send'):
            error=OSError(phase);clock,sock,client=self.fake(**{phase:error})
            result=self.run_fake(clock,sock,client)
            self.assertEqual(result.send_attempted,phase=='send');self.assertFalse(result.send_completed)
            self.assertFalse(result.capture_complete);self.assertEqual(result.received,b'')
            self.assertFalse([call for call in sock.calls if call[0]=='recv'])
            self.assertEqual(sum(call[0]=='sendall' for call in sock.calls),int(phase=='send'))
            self.assertEqual(sock.calls[-1],('close',));self.assertIs(client.last_error,error)
            self.assertIsNone(result.as_dict()['sent_byte_count'])

    def test_close_failure_keeps_complete_capture_and_first_transport_error(self):
        clock,sock,client=self.fake(close=OSError('close'))
        result=self.run_fake(clock,sock,client)
        self.assertTrue(result.capture_complete);self.assertTrue(result.receipt.matched)
        self.assertFalse(result.connection_closed);self.assertEqual(result.errors[0]['phase'],'close')
        original=OSError('send');clock,sock,client=self.fake(send=original,close=OSError('close'))
        result=self.run_fake(clock,sock,client)
        self.assertIs(client.last_error,original);self.assertEqual([e['phase'] for e in result.errors],['send','close'])

    def test_interruption_keeps_original_after_secondary_close_and_clock_failure(self):
        clock,sock,client=self.fake(chunks=(RECEIPT_A,KeyboardInterrupt('receive')),close=SystemExit('close'))
        original=sock.chunks[-1]
        # Final clock only raises once the receive interruption happened.
        original_clock=clock.__call__
        def now():
            if not sock.chunks and any(call[0]=='close' for call in sock.calls):raise RuntimeError('final clock')
            return original_clock()
        with patch.object(client,'_make_socket',return_value=sock),\
                patch('cbus_toolkit.pci_serial_address_transport.time.monotonic',side_effect=now):
            with self.assertRaises(KeyboardInterrupt) as raised:client.send_serial_address(A,6)
        self.assertIs(raised.exception,original);self.assertIs(client.last_error,original)
        self.assertEqual(client.last_exchange.received,RECEIPT_A);self.assertTrue(client.last_exchange.receipt.matched)
        self.assertEqual(original.pci_serial_address_exchange,client.last_exchange.as_dict())
        self.assertEqual([e['phase'] for e in client.last_exchange.errors],['receive','close','final_clock'])
        self.assertEqual(sum(call[0]=='sendall' for call in sock.calls),1);self.assertEqual(sock.calls[-1],('close',))

    def test_bytes_are_retained_before_an_arrival_clock_interrupt(self):
        clock,sock,client=self.fake()
        def now():
            if sock.calls and sock.calls[-1][0]=='recv':raise KeyboardInterrupt('arrival clock')
            return clock()
        with patch.object(client,'_make_socket',return_value=sock),\
                patch('cbus_toolkit.pci_serial_address_transport.time.monotonic',side_effect=now):
            with self.assertRaises(KeyboardInterrupt) as raised:client.send_serial_address(A,6)
        self.assertEqual(client.last_exchange.received,RECEIPT_A)
        self.assertTrue(raised.exception.pci_serial_address_exchange['retained_receipt_matches_request'])
        self.assertEqual(sum(call[0]=='recv' for call in sock.calls),1)

    def test_initial_clock_failure_retains_no_send_evidence(self):
        clock,sock,client=self.fake();error=KeyboardInterrupt('initial clock');clock.fail_at[1]=error
        with self.assertRaises(KeyboardInterrupt) as raised:self.run_fake(clock,sock,client)
        self.assertIs(raised.exception,error);self.assertEqual(sock.calls,[])
        self.assertIsNone(client.last_exchange.elapsed);self.assertFalse(client.last_exchange.send_attempted)

    def test_interrupted_send_and_final_clock_keep_original_exception_and_evidence(self):
        original=KeyboardInterrupt('send');clock,sock,client=self.fake(send=original,close=SystemExit('close'))
        with self.assertRaises(KeyboardInterrupt) as raised:self.run_fake(clock,sock,client)
        self.assertIs(raised.exception,original);self.assertTrue(client.last_exchange.send_attempted)
        self.assertFalse(client.last_exchange.send_completed);self.assertIsNone(original.pci_serial_address_exchange['sent_byte_count'])
        self.assertEqual(sum(call[0]=='sendall' for call in sock.calls),1)
        self.assertFalse([call for call in sock.calls if call[0]=='recv'])
        clock,sock,client=self.fake();original=KeyboardInterrupt('final clock')
        def now():
            if sock.calls and sock.calls[-1][0]=='close':raise original
            return clock()
        with patch.object(client,'_make_socket',return_value=sock),\
                patch('cbus_toolkit.pci_serial_address_transport.time.monotonic',side_effect=now):
            with self.assertRaises(KeyboardInterrupt) as raised:client.send_serial_address(A,6)
        self.assertIs(raised.exception,original);self.assertEqual(client.last_exchange.received,RECEIPT_A)
        self.assertTrue(client.last_exchange.capture_complete);self.assertTrue(client.last_exchange.connection_closed)

    def test_full_exact_byte_capacity_can_complete_without_discarding_any_wire_data(self):
        # Whitespace is legal framing separation; no extra frame is invented.
        payload=RECEIPT_A+b'\r\n'*((4096-len(RECEIPT_A))//2)
        payload+=b'\r'*(4096-len(payload))
        clock,sock,client=self.fake(chunks=(payload,));result=self.run_fake(clock,sock,client)
        self.assertEqual(len(result.received),4096);self.assertEqual(result.bytes_received,4096)
        self.assertTrue(result.capture_complete);self.assertTrue(result.receipt.matched)

    def test_timeout_setting_delay_is_rechecked_before_connect_and_send(self):
        for step in (1,2):
            clock,sock,client=self.fake()
            def delay():
                if sum(call[0]=='settimeout' for call in sock.calls)==step:clock.value=101.
            sock.timeout_effect=delay;result=self.run_fake(clock,sock,client)
            self.assertEqual(result.termination,'overall_timeout');self.assertFalse(result.send_attempted)
            self.assertEqual(sum(call[0]=='connect' for call in sock.calls),int(step==2))
            self.assertFalse([call for call in sock.calls if call[0]=='recv'])

    def test_absolute_deadline_and_slow_connect_do_not_admit_a_write(self):
        for value in (100.,100.5):
            clock,sock,client=self.fake();client._absolute_deadline=value
            if value>100:sock.connect_effect=lambda:setattr(clock,'value',100.5)
            result=self.run_fake(clock,sock,client)
            self.assertEqual(result.termination,'overall_timeout');self.assertFalse(result.send_attempted)
            self.assertFalse([call for call in sock.calls if call[0] in ('sendall','recv')])
        clock,sock,client=self.fake();client._absolute_deadline=100.5
        sock.connect_effect=lambda:setattr(clock,'value',100.49)
        result=self.run_fake(clock,sock,client)
        self.assertEqual(result.termination,'insufficient_response_budget');self.assertFalse(result.send_attempted)

    def test_late_send_or_parent_tie_does_not_start_receiving(self):
        for after,termination in ((101.,'overall_timeout'),(100.97,'insufficient_response_budget')):
            clock,sock,client=self.fake(send=lambda:None)
            sock.send_effect=lambda:setattr(clock,'value',after)
            result=self.run_fake(clock,sock,client)
            self.assertEqual(result.termination,termination);self.assertTrue(result.send_completed)
            self.assertTrue(result.send_attempted);self.assertFalse(result.capture_complete)
            self.assertFalse([call for call in sock.calls if call[0]=='recv'])
        clock,sock,client=self.fake();client.response_timeout=.25;client._absolute_deadline=100.5
        sock.send_effect=lambda:setattr(clock,'value',100.25)
        result=self.run_fake(clock,sock,client)
        self.assertEqual(result.termination,'insufficient_response_budget');self.assertFalse(result.capture_complete)

    def test_late_data_is_preserved_but_cannot_complete_capture(self):
        clock,sock,client=self.fake()
        def late():clock.value+=.05;return RECEIPT_A
        sock.chunks=[late]
        result=self.run_fake(clock,sock,client)
        self.assertEqual(result.termination,'late_data');self.assertEqual(result.received,RECEIPT_A)
        self.assertFalse(result.capture_complete);self.assertTrue(result.receipt.matched)

    def test_fake_ipv6_uses_one_numeric_address_without_dns(self):
        clock,sock,_=self.fake();client=transport(('::1',10001))
        with patch('cbus_toolkit.pci_serial_address_transport.socket.getaddrinfo',side_effect=AssertionError('No DNS')):
            result=self.run_fake(clock,sock,client)
        self.assertIn(('connect',('::1',10001,0,0)),sock.calls);self.assertTrue(result.capture_complete)

    def test_persistent_fixture_outcomes_are_verified_independently_of_transport_receipt(self):
        report={'passed':False,'scope':'One-request transport on owned synthetic fixture; no coordinator or physical hardware','cases':[]}
        with tempfile.TemporaryDirectory() as directory:
            for index,fault in enumerate((SerialAddressFault(),SerialAddressFault(reply=False),
                                         SerialAddressFault(move=False),SerialAddressFault(reported_source=9))):
                with self.subTest(fault=fault):
                    path=Path(directory)/str(index)/'state.json';sim=fixture(state_path=path,faults={A:fault},response_delay=.001)
                    def inventory(endpoint):
                        return PCIInventoryCollector(*endpoint,local_unit=16,overall_timeout=5,observation_timeout=.5,
                            confirmation_timeout=.1,response_timeout=.1,quiet_period=.025).collect_inventory()
                    with sim.running() as endpoint:
                        before=inventory(endpoint);start=len(sim.wire_log)
                        result=transport(endpoint).send_serial_address(A,6);move_wire=sim.wire_log[start:]
                        after=inventory(endpoint)
                    loaded=SerialAddressFixture.from_state(path,response_delay=.001)
                    with loaded.running() as endpoint:restarted=inventory(endpoint)
                    self.assertTrue(result.capture_complete);self.assertFalse(result.movement_verified)
                    self.assertTrue(before.complete);self.assertTrue(after.complete);self.assertTrue(restarted.complete)
                    serial_map=lambda r:{reply.serial:item.address for item in r.serial_observations for reply in item.replies}
                    self.assertEqual(serial_map(before),{'100966.1187':16,A:255,B:255})
                    expected={'100966.1187':16,A:6 if fault.move else 255,B:255}
                    self.assertEqual(serial_map(after),expected);self.assertEqual(serial_map(restarted),expected)
                    self.assertEqual(len(sim.co_operations),1)
                    receives=[bytes.fromhex(item['hex']) for item in move_wire if item['direction']=='rx']
                    self.assertEqual(receives,[CO_A])
                    if not fault.move:self.assertTrue(result.receipt.matched)
                    report['cases'].append({'exchange':result.as_dict(),'before':before.as_dict(),'after':after.as_dict(),
                        'restarted':restarted.as_dict(),'operation':sim.co_operations[0],'request_wire':move_wire,
                        'state':loaded.snapshot()})
            report['passed']=True
            if destination:=os.environ.get('CBUS_SERIAL_ADDRESS_TRANSPORT_REPORT'):
                path=Path(destination);path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':unittest.main()
