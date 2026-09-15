"""Independent peer/fault evidence for an explicit one-shot RECALL policy."""
import dataclasses
import json
import socket
import threading
import unittest
from unittest.mock import patch

from cbus_toolkit import pci_routed_recall as module
from cbus_toolkit.pci import IdentifyCAL, PCIRejected, ProtocolError, RecallCAL
from cbus_toolkit.pci_routing import RoutedCALCommand
from cbus_toolkit.pci_routed_recall import RoutedRecallClient, RoutedReplyPath

# Actual unchanged original matrix literals, not product-regenerated checksums.
DIRECT = b'86041000821E00C6\r'
ROUTED = b'861410021504821E009B\r'
NEGATIVE = b'860410003BFF9993\r'
COMMAND = RoutedCALCommand(4, RecallCAL(30, 1))
PATH = RoutedReplyPath(4, 16)


def literal_frame(header=134, outer=4, destination=16, route=(), parameter=30, data=b'\0', payload=None):
    if payload is None:
        payload = bytes((0x81 + len(data), parameter)) + data
    value = bytes((header, outer, destination, len(route), *route)) + payload
    return (value + bytes((-sum(value) & 255,))).hex().upper().encode() + b'\r'


def literal_command(unit=4, parameter=30, count=1, bridges=(), checksum=False):
    addresses=(*bridges,unit)
    value=bytes((70,addresses[0],9*len(bridges),*addresses[1:],26,parameter,count))
    if checksum:value+=bytes((-sum(value)&255,))
    return b'\\'+value.hex().upper().encode()+b'g\r'


class SocketFixture:
    def __init__(self, chunks=(), *, fault=None, close_error=None):
        self.chunks=list(chunks);self.fault=fault or {};self.close_error=close_error
        self.calls=[];self.sent=[]
    def settimeout(self,value):self.calls.append(('timeout',value))
    def connect(self,endpoint):
        self.calls.append(('connect',endpoint))
        if 'connect' in self.fault:raise self.fault['connect']
    def sendall(self,data):
        self.calls.append(('send',data));self.sent.append(data)
        if 'send' in self.fault:raise self.fault['send']
    def recv(self,size):
        self.calls.append(('recv',size))
        if 'recv' in self.fault:raise self.fault['recv']
        return self.chunks.pop(0) if self.chunks else b''
    def close(self):
        self.calls.append(('close',))
        if self.close_error is not None:raise self.close_error


class Peer:
    def __init__(self, command, chunks, *, family=socket.AF_INET):
        self.command=command;self.chunks=chunks;self.error=None;self.received=bytearray();self.eof=False
        self.server=socket.socket(family,socket.SOCK_STREAM);self.server.settimeout(3)
        self.host='127.0.0.1' if family==socket.AF_INET else '::1'
        self.server.bind((self.host,0));self.server.listen(1);self.port=self.server.getsockname()[1]
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        try:
            connection,_=self.server.accept()
            with connection:
                connection.settimeout(3)
                while not self.received.endswith(b'\r'):
                    data=connection.recv(256)
                    if not data:raise AssertionError('EOF before intended command')
                    self.received.extend(data)
                    if len(self.received)>87:raise AssertionError('Unexpected command bytes')
                if self.received!=self.command:raise AssertionError((bytes(self.received),self.command))
                for chunk in self.chunks:connection.sendall(chunk)
                tail=connection.recv(256)
                self.eof=tail==b''
                if tail:raise AssertionError('A second command was sent')
        except BaseException as error:self.error=error
        finally:self.server.close()
    def finish(self):
        self.thread.join(4)
        if self.thread.is_alive():raise AssertionError('Owned peer did not stop')
        if self.error is not None:raise self.error
        if not self.eof:raise AssertionError('Owned peer did not observe close')


class RoutedRecallTests(unittest.TestCase):
    def exchange(self, chunks, *, command=COMMAND, expected=PATH, options=None, fault=None, close_error=None):
        fixture=SocketFixture(chunks,fault=fault,close_error=close_error)
        client=RoutedRecallClient('127.0.0.1',**(options or {}))
        with patch.object(module.socket,'socket',return_value=fixture) as factory, \
             patch.object(module.socket,'getaddrinfo',side_effect=AssertionError('No resolver')):
            value=client.exchange(command,expected=expected)
        self.assertEqual(factory.call_args.args,(socket.AF_INET,socket.SOCK_STREAM))
        self.assertEqual(fixture.sent,[literal_command(command.unit,command.cal.parameter,command.cal.count,command.bridges,client.command_checksum)])
        self.assertEqual([c for c in fixture.calls if c[0]=='close'],[('close',)])
        return value,client,fixture

    def test_original_literals_both_event_orders_and_all_split_positions(self):
        for frame in (b'06041000821E0046\r',DIRECT):
            for joined in (b'g.'+frame,frame+b'g.'):
                for cut in range(1,len(joined)):
                    # An incomplete suffix after complete success is intentionally
                    # rejected. All cuts here precede full dual success.
                    with self.subTest(frame=frame,cut=cut):
                        result,client,_=self.exchange([joined[:cut],joined[cut:]])
                        self.assertEqual(result.data,b'\0')
                        self.assertTrue(client.last_evidence['complete'])
        result,_,_=self.exchange([b'\r\ng.\r\n'+DIRECT+b'\r\n'])
        self.assertEqual(result.response.raw,DIRECT)

    def test_all_route_depths_counts_bytes_and_explicit_checksum_modes(self):
        for depth in range(7):
            for count in range(1,31):
                bridges=tuple(range(40,40+depth));route=tuple(range(21,20+depth))+(4,) if depth else ()
                outer=20 if depth else 4
                command=RoutedCALCommand(4,RecallCAL(255,count),bridges=bridges)
                path=RoutedReplyPath(outer,0,route)
                frame=literal_frame(outer=outer,destination=0,route=route,parameter=255,data=bytes(range(count)))
                result,_,_=self.exchange([b'g.'+frame],command=command,expected=path,options={'command_checksum':bool(count%2)})
                self.assertEqual(result.data,bytes(range(count)))
                self.assertEqual(result.response.route_entries,route)
        for unit in (0,1,127,128,255):
            command=RoutedCALCommand(unit,RecallCAL(0,1));path=RoutedReplyPath(unit,255)
            result,_,_=self.exchange([literal_frame(outer=unit,destination=255,parameter=0,data=b'\xff').lower()+b'g.'],command=command,expected=path)
            self.assertEqual(result.as_dict()['raw_zero_address_ambiguous'],unit==0)

    def test_unmatched_valid_events_keep_literal_full_path_and_do_not_complete(self):
        chunks=[b'h#'+literal_frame(destination=99)+literal_frame(parameter=31)+literal_frame(payload=b'\x21\x1e')+b'g.'+DIRECT]
        result,_,_=self.exchange(chunks)
        self.assertEqual([v.matched for v in result.events],[False,False,False,False,True,True])
        for raw in (literal_frame(outer=5),literal_frame(destination=99),literal_frame(route=(4,)),literal_frame(parameter=31)):
            fixture=SocketFixture([b'g.'+raw]);client=RoutedRecallClient('127.0.0.1')
            with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(ConnectionError):
                client.exchange(COMMAND,expected=PATH)
            self.assertFalse(client.last_evidence['response_received'])

    def test_stronger_final_chunk_duplicate_negative_and_incomplete_policies(self):
        variants=[b'g.'+DIRECT+DIRECT,b'g.'+DIRECT+b'g.',b'g.'+DIRECT+b'g#',
                  b'g.'+DIRECT+b'g',b'g.'+DIRECT+b'86',b'g.'+DIRECT+b'!',
                  b'g.'+DIRECT+NEGATIVE]
        for chunk in variants:
            client=RoutedRecallClient('127.0.0.1');fixture=SocketFixture([chunk])
            with self.subTest(chunk=chunk),patch.object(module.socket,'socket',return_value=fixture),self.assertRaises((ProtocolError,PCIRejected)):
                client.exchange(COMMAND,expected=PATH)
            self.assertFalse(client.last_evidence['complete'])
            self.assertEqual(len(fixture.sent),1)
        # Bytes delivered only by a later recv are outside the declared boundary.
        result,_,fixture=self.exchange([b'g.'+DIRECT,b'g#'])
        self.assertEqual(fixture.chunks,[b'g#'])
        self.assertIn('final received chunk',result.as_dict()['completion_boundary'])

    def test_original_negative_prefix_is_rejection_not_new_cal_shape(self):
        for raw in (b'860410003B2B\r',NEGATIVE,literal_frame(payload=b'\x3b'),literal_frame(payload=b'\x3b'+bytes(range(30)))):
            fixture=SocketFixture([raw]);client=RoutedRecallClient('127.0.0.1')
            with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(PCIRejected):client.exchange(COMMAND,expected=PATH)
            self.assertEqual(client.last_evidence['events'][0]['kind'],'observed_negative_prefix')
            self.assertFalse(client.last_evidence['response_received'])
        result,_,_=self.exchange([literal_frame(destination=99,payload=b'\x3b')+b'g.'+DIRECT])
        self.assertEqual(result.events[0].kind,'observed_negative_prefix')
        self.assertFalse(result.events[0].matched)

    def test_invalid_frame_and_unsupported_receiver_forms_never_fall_back(self):
        bad=[DIRECT[:-3]+b'00\r',b'821E0060\r',literal_frame(header=70),literal_frame(route=(1,)*7),
             literal_frame(payload=b'\x82\x1e\x00\x82\x1e\x00'),literal_frame(data=b'\x00\x01'),
             b'g\r',b'g!',b'+',b'=',b'\x11',b'\x13',DIRECT.replace(b'\r',b'\n'),b'F'*87,
             DIRECT[:5]+b'\x11'+DIRECT[5:]]
        for raw in bad:
            client=RoutedRecallClient('127.0.0.1');fixture=SocketFixture([raw])
            with self.subTest(raw=raw),patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(ProtocolError):
                client.exchange(COMMAND,expected=PATH)
            self.assertEqual(len(fixture.sent),1)
        for status in b"#$%&'":
            fixture=SocketFixture([b'g'+bytes((status,))]);client=RoutedRecallClient('127.0.0.1')
            with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(PCIRejected):client.exchange(COMMAND,expected=PATH)

    def test_resource_bounds_and_eof_timeout_no_resubmission(self):
        for options,chunks in [({'max_events':1},[b'h.g.'+DIRECT]),({'max_received_bytes':2},[b'g.']),({},[b'g.']),({},[DIRECT]),({},[b'g'])]:
            fixture=SocketFixture(chunks);client=RoutedRecallClient('127.0.0.1',**options)
            with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises((ProtocolError,ConnectionError)):
                client.exchange(COMMAND,expected=PATH)
            self.assertFalse(client.last_evidence['resubmitted']);self.assertEqual(len(fixture.sent),1)
        error=TimeoutError('owned receive deadline');fixture=SocketFixture(fault={'recv':error});client=RoutedRecallClient('127.0.0.1')
        with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(TimeoutError) as caught:client.exchange(COMMAND,expected=PATH)
        self.assertIs(caught.exception,error);self.assertIs(client.last_error,error)

    def test_validation_and_revalidation_finish_before_socket_or_resolver(self):
        with patch.object(module.socket,'socket',side_effect=AssertionError('No socket')),patch.object(module.socket,'getaddrinfo',side_effect=AssertionError('No resolver')):
            for host in ('localhost','https://127.0.0.1','::1%lo0','127.000.0.1','',None):
                with self.assertRaises((ValueError,TypeError)):RoutedRecallClient(host)
            for options in ({'port':True},{'port':0},{'timeout':True},{'timeout':float('nan')},{'timeout':10**500},
                            {'max_events':0},{'max_received_bytes':1048577},{'command_checksum':1}):
                with self.assertRaises(ValueError):RoutedRecallClient('127.0.0.1',**options)
            for command,path in ((RoutedCALCommand(4,IdentifyCAL(30)),PATH),(RoutedCALCommand(4,RecallCAL(30,31)),PATH),
                                 (RoutedCALCommand(4,RecallCAL(30,1),addressing='programming'),PATH),(COMMAND,RoutedReplyPath(5,16))):
                client=RoutedRecallClient('127.0.0.1')
                with self.assertRaises(ValueError):client.exchange(command,expected=path)
                self.assertFalse(client.last_evidence['connect_attempted'])
            client=RoutedRecallClient('127.0.0.1');client.host='localhost'
            with self.assertRaises(ValueError):client.exchange(COMMAND,expected=PATH)
            forged=RoutedCALCommand(4,RecallCAL(30,1));object.__setattr__(forged.cal,'count',True)
            with self.assertRaises(ValueError):RoutedRecallClient('127.0.0.1').exchange(forged,expected=PATH)
            for args in ((True,16,()),(4,256,()),(4,16,[4]),(4,16,(4,)*7)):
                with self.assertRaises(ValueError):RoutedReplyPath(*args)

    def test_first_error_identity_close_prefix_and_refused_attachment(self):
        class Refusal(KeyboardInterrupt):
            def __setattr__(self,name,value):
                if name=='pci_routed_recall_evidence':raise SystemExit('attachment secondary')
                super().__setattr__(name,value)
            def __str__(self):raise SystemExit('text secondary')
        for stage in ('connect','send','recv'):
            for original in (OSError('original'),Refusal(),SystemExit('original')):
                secondary=KeyboardInterrupt('close secondary');fixture=SocketFixture(fault={stage:original},close_error=secondary)
                client=RoutedRecallClient('127.0.0.1')
                with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(BaseException) as caught:
                    client.exchange(COMMAND,expected=PATH)
                self.assertIs(caught.exception,original);self.assertIs(client.last_error,original)
                self.assertEqual(client.last_evidence['stage'],'receive' if stage=='recv' else stage)
                self.assertEqual(client.last_evidence['cleanup_errors'][0]['type'],'KeyboardInterrupt')
                self.assertEqual([x for x in fixture.calls if x[0]=='close'],[('close',)])
                self.assertFalse(client.last_evidence['complete'])
        error=OSError('close first');fixture=SocketFixture([b'g.'+DIRECT],close_error=error);client=RoutedRecallClient('127.0.0.1')
        with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(OSError) as caught:client.exchange(COMMAND,expected=PATH)
        self.assertIs(caught.exception,error);self.assertEqual(client.last_evidence['stage'],'close')

    def test_evidence_export_failure_preserves_first_and_is_not_success(self):
        for original in (KeyboardInterrupt('original'),None):
            export=SystemExit('export');fixture=SocketFixture([b'g.'+DIRECT],fault={'recv':original} if original else {})
            client=RoutedRecallClient('127.0.0.1')
            with patch.object(module.socket,'socket',return_value=fixture),patch.object(module,'_copy',side_effect=export),self.assertRaises(BaseException) as caught:
                client.exchange(COMMAND,expected=PATH)
            self.assertIs(caught.exception,original or export)
            self.assertIs(client.last_error,original or export)
            self.assertTrue(client.last_evidence['evidence_export_failed'])

    def test_late_final_chunk_keeps_bytes_but_cannot_succeed(self):
        fixture=SocketFixture([b'g.'+DIRECT]);client=RoutedRecallClient('127.0.0.1',timeout=1)
        with patch.object(module.socket,'socket',return_value=fixture), \
             patch.object(module.time,'monotonic',side_effect=[0,0,0,0,2]),self.assertRaises(TimeoutError):
            client.exchange(COMMAND,expected=PATH)
        self.assertEqual(client.last_evidence['received_chunks_hex'],[(b'g.'+DIRECT).hex().upper()])
        self.assertFalse(client.last_evidence['complete']);self.assertTrue(client.last_evidence['close_completed'])

    def test_overridden_with_traceback_cannot_replace_first_interruption(self):
        class Refusal(KeyboardInterrupt):
            def with_traceback(self,value):raise SystemExit('secondary dispatch')
        original=Refusal('original');fixture=SocketFixture(fault={'recv':original})
        client=RoutedRecallClient('127.0.0.1')
        caught=None
        with patch.object(module.socket,'socket',return_value=fixture):
            try:client.exchange(COMMAND,expected=PATH)
            except BaseException as error:caught=error
        self.assertIs(caught,original);self.assertIs(client.last_error,original)

    def test_detached_receipt_and_second_use_stale_evidence_reset(self):
        result,client,_=self.exchange([b'g.'+DIRECT])
        exported=result.as_dict();exported['events'].clear();exported['expected']['route_entries'].append(9)
        client.last_evidence['events'].clear()
        self.assertEqual(len(result.events),2);self.assertEqual(result.expected.route_entries,())
        with self.assertRaises(dataclasses.FrozenInstanceError):result.sent=b''
        with patch.object(module.socket,'socket',side_effect=AssertionError('No reconnect')),self.assertRaises(RuntimeError):
            client.exchange(COMMAND,expected=PATH)
        self.assertEqual(client.last_evidence['events'],[])
        self.assertFalse(client.last_evidence['connect_attempted']);self.assertFalse(client.last_evidence['complete'])


class RoutedRecallPeerTests(unittest.TestCase):
    def test_owned_ipv4_peer_independent_bytes_all_depths_and_orders(self):
        for depth in range(7):
            for count in (1,30):
                bridges=tuple(range(40,40+depth));route=tuple(range(21,20+depth))+(4,) if depth else ()
                path=RoutedReplyPath(20 if depth else 4,16,route)
                frame=literal_frame(header=6 if count==1 else 134,outer=path.outer_source_byte,route=route,data=bytes(range(count)))
                chunks=[b'g',b'.',frame[:5],frame[5:]] if count==1 else [frame[:4],frame[4:],b'g.']
                peer=Peer(literal_command(count=count,bridges=bridges),chunks)
                try:
                    client=RoutedRecallClient(peer.host,peer.port,timeout=2)
                    with patch.object(module.socket,'getaddrinfo',side_effect=AssertionError('No resolver')):
                        result=client.exchange(RoutedCALCommand(4,RecallCAL(30,count),bridges=bridges),expected=path)
                    self.assertEqual(result.data,bytes(range(count)))
                finally:peer.finish()
                self.assertEqual(bytes(peer.received),literal_command(count=count,bridges=bridges))

    def test_owned_peer_rejections_and_timeout_still_receive_only_one_command(self):
        for chunks,error_type,timeout in (([b'g#'],PCIRejected,1),([NEGATIVE],PCIRejected,1),
                                         ([DIRECT[:-3]+b'00\r'],ProtocolError,1),([],TimeoutError,.03)):
            peer=Peer(literal_command(),chunks)
            try:
                client=RoutedRecallClient(peer.host,peer.port,timeout=timeout)
                with self.assertRaises(error_type):client.exchange(COMMAND,expected=PATH)
                self.assertFalse(client.last_evidence['complete'])
                self.assertTrue(client.last_evidence['close_completed'])
            finally:peer.finish()
            self.assertEqual(bytes(peer.received),literal_command())

    def test_owned_peer_unmatched_path_then_exact_original_reply(self):
        peer=Peer(literal_command(),[b'h#'+literal_frame(destination=99)+DIRECT+b'g.'])
        try:
            client=RoutedRecallClient(peer.host,peer.port)
            result=client.exchange(COMMAND,expected=PATH)
            self.assertEqual([e.matched for e in result.events],[False,False,True,True])
            self.assertEqual(result.data,b'\0')
        finally:peer.finish()

    def test_owned_ipv6_peer_explicit_family_no_resolver(self):
        peer=Peer(literal_command(),[DIRECT,b'g.'],family=socket.AF_INET6)
        try:
            client=RoutedRecallClient(peer.host,peer.port)
            with patch.object(module.socket,'getaddrinfo',side_effect=AssertionError('No resolver')):
                result=client.exchange(COMMAND,expected=PATH)
            self.assertEqual(result.response.raw,DIRECT)
        finally:peer.finish()


if __name__=='__main__':unittest.main()
