"""Independent peer/fault checks for strict, raw-byte routed IDENTIFY."""
import dataclasses
import socket
import unittest
from unittest.mock import patch

from cbus_toolkit import pci_routed_identify as module
from cbus_toolkit.pci import IdentifyCAL, RecallCAL, ReplyCAL, PCIRejected, ProtocolError
from cbus_toolkit.pci_routing import RoutedCALCommand
from cbus_toolkit.pci_routed_identify import RoutedIdentifyClient, RoutedReplyPath
from tests.test_pci_routed_recall import SocketFixture, Peer, literal_frame as _frame

# Literal original bB/cj matrix responses; no product-generated checksums.
DIRECT=b'860410008201A53E\r'
ZERO=b'860410008101E4\r'
ROUTED=b'8614100215048201A513\r'
SHORT_COLLISION=b'860410003B002B\r'
COMMAND=RoutedCALCommand(4,IdentifyCAL(1))
PATH=RoutedReplyPath(4,16)

def literal_frame(*,attribute=1,**options):return _frame(parameter=attribute,**options)
def literal_command(unit=4,attribute=1,bridges=(),checksum=False):
    addresses=(*bridges,unit)
    raw=bytes((0x46,addresses[0],9*len(bridges),*addresses[1:],0x21,attribute))
    if checksum:raw+=bytes((-sum(raw)&255,))
    return b'\\'+raw.hex().upper().encode()+b'g\r'

class RoutedIdentifyTests(unittest.TestCase):
    def exchange(self,chunks,*,command=COMMAND,expected=PATH,expected_count=None,options=None):
        fixture=SocketFixture(chunks);client=RoutedIdentifyClient('127.0.0.1',**(options or {}))
        with patch.object(module.socket,'socket',return_value=fixture) as factory,patch.object(module.socket,'getaddrinfo',side_effect=AssertionError('No resolver')):
            result=client.exchange(command,expected=expected,expected_count=expected_count)
        self.assertEqual(factory.call_args.args,(socket.AF_INET,socket.SOCK_STREAM))
        self.assertEqual(fixture.sent,[literal_command(command.unit,command.cal.attribute,command.bridges,client.command_checksum)])
        self.assertEqual([c for c in fixture.calls if c[0]=='close'],[('close',)])
        return result,client,fixture

    def test_literal_frames_zero_data_orders_and_every_split(self):
        for frame,data in ((b'0604100082010063\r',b'\0'),(DIRECT,b'\xa5'),(ZERO,b'')):
            for joined in (b'g.'+frame,frame+b'g.'):
                for cut in range(1,len(joined)):
                    with self.subTest(frame=frame,cut=cut):
                        result,client,_=self.exchange([joined[:cut],joined[cut:]])
                        self.assertEqual(result.data,data);self.assertTrue(client.last_evidence['complete'])
                        self.assertEqual(result.as_dict()['actual_count'],len(data))
        result,_,_=self.exchange([b'\r\ng.\r\n'+ZERO+b'\r\n'],expected_count=0)
        self.assertEqual(result.data,b'');self.assertEqual(result.expected_count,0)
        self.assertFalse(result.as_dict()['original_typed_getter_used'])

    def test_all_attribute_bytes_and_count_policies(self):
        for attribute in range(256):
            command=RoutedCALCommand(4,IdentifyCAL(attribute));data=bytes((attribute,))
            result,_,_=self.exchange([b'g.'+literal_frame(attribute=attribute,data=data)],command=command)
            self.assertEqual(result.data,data)
        for count in range(31):
            data=bytes(range(count));frame=literal_frame(attribute=255,data=data)
            for expected_count in (None,count):
                result,_,_=self.exchange([frame+b'g.'],command=RoutedCALCommand(4,IdentifyCAL(255)),expected_count=expected_count)
                self.assertEqual(result.data,data);self.assertEqual(result.expected_count,expected_count)
        for count in (0,2,30):
            client=RoutedIdentifyClient('127.0.0.1');fixture=SocketFixture([b'g.'+DIRECT])
            with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(ProtocolError):
                client.exchange(COMMAND,expected=PATH,expected_count=count)
            self.assertFalse(client.last_evidence['response_received']);self.assertEqual(len(fixture.sent),1)

    def test_all_routes_terminal_bytes_and_checksum_modes(self):
        for depth in range(7):
            for count in (0,1,30):
                bridges=tuple(range(40,40+depth));route=tuple(range(21,20+depth))+(4,) if depth else ()
                expected=RoutedReplyPath(20 if depth else 4,0,route)
                frame=literal_frame(outer=expected.outer_source_byte,destination=0,route=route,data=bytes(range(count)))
                result,_,_=self.exchange([b'g.'+frame],command=RoutedCALCommand(4,IdentifyCAL(1),bridges=bridges),expected=expected,expected_count=count,options={'command_checksum':bool(count%2)})
                self.assertEqual(result.data,bytes(range(count)));self.assertEqual(result.response.route_entries,route)
        for unit in (0,1,127,128,255):
            result,_,_=self.exchange([literal_frame(outer=unit,destination=255,data=b'\xff').lower()+b'g.'],command=RoutedCALCommand(unit,IdentifyCAL(1)),expected=RoutedReplyPath(unit,255))
            self.assertEqual(result.as_dict()['raw_zero_address_ambiguous'],unit==0)

    def test_every_literal_path_field_and_attribute_is_required(self):
        unmatched=[literal_frame(outer=5),literal_frame(destination=99),literal_frame(route=(4,)),literal_frame(attribute=2),literal_frame(payload=b'\x21\x01')]
        result,_,_=self.exchange([b'h#'+b''.join(unmatched)+b'g.'+DIRECT])
        self.assertEqual([e.matched for e in result.events],[False]*6+[True,True])
        for frame in unmatched:
            fixture=SocketFixture([b'g.'+frame]);client=RoutedIdentifyClient('127.0.0.1')
            with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(ConnectionError):client.exchange(COMMAND,expected=PATH)
            self.assertFalse(client.last_evidence['response_received'])

    def test_3b_and_original_short_coincidence_are_protocol_failures(self):
        for frame in (b'860410003B2B\r',SHORT_COLLISION,b'860410003B00002B\r',literal_frame(destination=99,payload=b'\x3b'),b'8201A5D8\r'):
            fixture=SocketFixture([frame]);client=RoutedIdentifyClient('127.0.0.1')
            with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(ProtocolError) as caught:
                client.exchange(RoutedCALCommand(4,IdentifyCAL(4)),expected=PATH)
            self.assertNotIsInstance(caught.exception,PCIRejected)
            self.assertFalse(client.last_evidence['response_received'])
            self.assertFalse(client.last_evidence['original_short_matcher_used'])
            self.assertEqual(client.last_evidence['received_chunks_hex'],[frame.hex().upper()])

    def test_final_chunk_duplicates_partial_and_unsupported_suffix_never_succeed(self):
        for chunk in (b'g.'+DIRECT+DIRECT,b'g.'+DIRECT+b'g.',b'g.'+DIRECT+b'g#',b'g.'+DIRECT+b'g',b'g.'+DIRECT+b'86',b'g.'+DIRECT+b'!',b'g.'+DIRECT+SHORT_COLLISION):
            client=RoutedIdentifyClient('127.0.0.1');fixture=SocketFixture([chunk])
            with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises((ProtocolError,PCIRejected)):
                client.exchange(COMMAND,expected=PATH)
            self.assertFalse(client.last_evidence['complete']);self.assertEqual(len(fixture.sent),1)
        result,_,fixture=self.exchange([b'g.'+DIRECT,b'g#']);self.assertEqual(fixture.chunks,[b'g#'])
        self.assertIn('final received chunk',result.as_dict()['completion_boundary'])

    def test_malformed_count_checksum_and_unsupported_framing_never_fall_back(self):
        bad=[DIRECT[:-3]+b'00\r',b'86041000830100E2\r',b'860410008201-100\r',b'860410008201ZZ00\r',
             literal_frame(header=70),literal_frame(route=(1,)*7),literal_frame(payload=b'\x82\x01\0\x82\x01\0'),
             b'g\r',b'g!',b'+',b'=',b'\x11',b'\x13',DIRECT.replace(b'\r',b'\n'),b'F'*87]
        for frame in bad:
            client=RoutedIdentifyClient('127.0.0.1');fixture=SocketFixture([frame])
            with self.subTest(frame=frame),patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(ProtocolError):client.exchange(COMMAND,expected=PATH)
            self.assertEqual(len(fixture.sent),1)
        for status in b"#$%&'":
            fixture=SocketFixture([b'g'+bytes((status,))]);client=RoutedIdentifyClient('127.0.0.1')
            with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(PCIRejected):client.exchange(COMMAND,expected=PATH)

    def test_bounds_eof_timeout_preserve_one_send(self):
        for options,chunks in [({'max_events':1},[b'h.g.'+DIRECT]),({'max_received_bytes':2},[b'g.']),({},[DIRECT]),({},[b'g.']),({},[b'g'])]:
            client=RoutedIdentifyClient('127.0.0.1',**options);fixture=SocketFixture(chunks)
            with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises((ProtocolError,ConnectionError)):client.exchange(COMMAND,expected=PATH)
            self.assertFalse(client.last_evidence['resubmitted']);self.assertEqual(len(fixture.sent),1)
        error=TimeoutError('owned deadline');fixture=SocketFixture(fault={'recv':error});client=RoutedIdentifyClient('127.0.0.1')
        with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(TimeoutError) as caught:client.exchange(COMMAND,expected=PATH)
        self.assertIs(caught.exception,error);self.assertIs(client.last_error,error)

    def test_preflight_and_mutated_config_fail_before_socket_or_resolver(self):
        with patch.object(module.socket,'socket',side_effect=AssertionError('No socket')),patch.object(module.socket,'getaddrinfo',side_effect=AssertionError('No resolver')):
            for host in ('localhost','https://127.0.0.1','::1%lo0','127.000.0.1','',None):
                with self.assertRaises((ValueError,TypeError)):RoutedIdentifyClient(host)
            for opts in ({'port':True},{'port':0},{'timeout':True},{'timeout':float('nan')},{'timeout':10**500},{'max_events':0},{'max_received_bytes':1048577},{'command_checksum':1}):
                with self.assertRaises(ValueError):RoutedIdentifyClient('127.0.0.1',**opts)
            for count in (True,False,-1,31,1.0,'0',[],object()):
                client=RoutedIdentifyClient('127.0.0.1')
                with self.assertRaises(ValueError):client.exchange(COMMAND,expected=PATH,expected_count=count)
                self.assertFalse(client.last_evidence['connect_attempted'])
            for command,path in ((RoutedCALCommand(4,RecallCAL(1,1)),PATH),(RoutedCALCommand(4,IdentifyCAL(1),addressing='programming'),PATH),(COMMAND,RoutedReplyPath(5,16))):
                with self.assertRaises(ValueError):RoutedIdentifyClient('127.0.0.1').exchange(command,expected=path)
            forged=RoutedCALCommand(4,IdentifyCAL(1));object.__setattr__(forged.cal,'attribute',True)
            with self.assertRaises(ValueError):RoutedIdentifyClient('127.0.0.1').exchange(forged,expected=PATH)
            client=RoutedIdentifyClient('127.0.0.1');client.host='localhost'
            with self.assertRaises(ValueError):client.exchange(COMMAND,expected=PATH)

    def test_first_exception_survives_close_and_hostile_attachment(self):
        class Refusal(KeyboardInterrupt):
            def __setattr__(self,name,value):
                if name=='pci_routed_identify_evidence':raise SystemExit('attachment')
                super().__setattr__(name,value)
            def __str__(self):raise SystemExit('text')
        for stage in ('connect','send','recv'):
            for original in (OSError('original'),Refusal(),SystemExit('original')):
                fixture=SocketFixture(fault={stage:original},close_error=KeyboardInterrupt('secondary'));client=RoutedIdentifyClient('127.0.0.1')
                with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(BaseException) as caught:client.exchange(COMMAND,expected=PATH)
                self.assertIs(caught.exception,original);self.assertIs(client.last_error,original)
                self.assertEqual(client.last_evidence['stage'],'receive' if stage=='recv' else stage)
                self.assertEqual(client.last_evidence['cleanup_errors'][0]['type'],'KeyboardInterrupt')
                self.assertEqual([c for c in fixture.calls if c[0]=='close'],[('close',)])
        error=OSError('close');fixture=SocketFixture([b'g.'+DIRECT],close_error=error);client=RoutedIdentifyClient('127.0.0.1')
        with patch.object(module.socket,'socket',return_value=fixture),self.assertRaises(OSError) as caught:client.exchange(COMMAND,expected=PATH)
        self.assertIs(caught.exception,error);self.assertEqual(client.last_evidence['stage'],'close')

    def test_evidence_failure_and_overridden_traceback_keep_first(self):
        class Refusal(KeyboardInterrupt):
            def with_traceback(self,_):raise SystemExit('secondary')
        for original in (Refusal('original'),None):
            export=SystemExit('export');fixture=SocketFixture([b'g.'+DIRECT],fault={'recv':original} if original else {});client=RoutedIdentifyClient('127.0.0.1');caught=None
            with patch.object(module.socket,'socket',return_value=fixture),patch.object(module,'_copy',side_effect=export):
                try:client.exchange(COMMAND,expected=PATH)
                except BaseException as error:caught=error
            self.assertIs(caught,original or export);self.assertIs(client.last_error,original or export);self.assertTrue(client.last_evidence['evidence_export_failed'])
        fixture=SocketFixture(fault={'recv':Refusal('first')});original=fixture.fault['recv'];caught=None
        with patch.object(module.socket,'socket',return_value=fixture):
            try:RoutedIdentifyClient('127.0.0.1').exchange(COMMAND,expected=PATH)
            except BaseException as error:caught=error
        self.assertIs(caught,original)

    def test_late_final_chunk_is_preserved_but_rejected(self):
        fixture=SocketFixture([b'g.'+DIRECT]);client=RoutedIdentifyClient('127.0.0.1',timeout=1)
        with patch.object(module.socket,'socket',return_value=fixture),patch.object(module.time,'monotonic',side_effect=[0,0,0,0,2]),self.assertRaises(TimeoutError):client.exchange(COMMAND,expected=PATH)
        self.assertEqual(client.last_evidence['received_chunks_hex'],[(b'g.'+DIRECT).hex().upper()]);self.assertTrue(client.last_evidence['close_completed'])

    def test_detached_receipt_single_use_and_active_evidence(self):
        result,client,_=self.exchange([b'g.'+DIRECT]);exported=result.as_dict();exported['events'].clear();exported['expected']['route_entries'].append(9)
        self.assertEqual(len(result.events),2);self.assertEqual(result.expected.route_entries,())
        with self.assertRaises(dataclasses.FrozenInstanceError):result.expected_count=0
        with patch.object(module.socket,'socket',side_effect=AssertionError('No reconnect')),self.assertRaises(RuntimeError):client.exchange(COMMAND,expected=PATH)
        self.assertFalse(client.last_evidence['connect_attempted']);self.assertEqual(client.last_evidence['events'],[])
        other=RoutedIdentifyClient('127.0.0.1');sentinel={'active':True};other.last_evidence=sentinel;other._lock.acquire()
        try:
            with self.assertRaises(RuntimeError):other.exchange(COMMAND,expected=PATH)
            self.assertIs(other.last_evidence,sentinel)
        finally:other._lock.release()

class RoutedIdentifyPeerTests(unittest.TestCase):
    def test_owned_peers_all_counts_raw_results_and_literal_request(self):
        for count in range(31):
            frame=literal_frame(data=bytes(range(count)));parts=[b'g.',frame] if count%2 else [frame,b'g.']
            peer=Peer(b'\\4604002101g\r',parts)
            try:
                with patch.object(module.socket,'getaddrinfo',side_effect=AssertionError('No resolver')):
                    result=RoutedIdentifyClient(peer.host,peer.port,timeout=2).exchange(COMMAND,expected=PATH,expected_count=count)
                self.assertEqual(result.data,bytes(range(count)))
            finally:peer.finish()

    def test_owned_routed_literal_checksum_modes_and_ipv6(self):
        for family in (socket.AF_INET,socket.AF_INET6):
            for checksum in (False,True):
                raw=b'\\4614121504210159g\r' if checksum else b'\\46141215042101g\r'
                peer=Peer(raw,[b'g',b'.',ROUTED[:5],ROUTED[5:]],family=family)
                try:
                    client=RoutedIdentifyClient(peer.host,peer.port,timeout=2,command_checksum=checksum)
                    with patch.object(module.socket,'getaddrinfo',side_effect=AssertionError('No resolver')):
                        result=client.exchange(RoutedCALCommand(4,IdentifyCAL(1),bridges=(20,21)),expected=RoutedReplyPath(20,16,(21,4)))
                    self.assertEqual(result.data,b'\xa5');self.assertEqual(result.response.raw,ROUTED)
                finally:peer.finish()

    def test_owned_failures_observe_one_command_and_close(self):
        for frames,error,timeout in (([b'g#'],PCIRejected,1),([SHORT_COLLISION],ProtocolError,1),([DIRECT[:-3]+b'00\r'],ProtocolError,1),([],TimeoutError,.03)):
            peer=Peer(b'\\4604002101g\r',frames)
            try:
                client=RoutedIdentifyClient(peer.host,peer.port,timeout=timeout)
                with self.assertRaises(error):client.exchange(COMMAND,expected=PATH)
                self.assertFalse(client.last_evidence['complete']);self.assertTrue(client.last_evidence['close_completed'])
            finally:peer.finish()
            self.assertEqual(bytes(peer.received),b'\\4604002101g\r')

if __name__=='__main__':unittest.main()
