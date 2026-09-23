"""Independent co vectors, serial-keyed persistence and deliberately false receipts."""
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from cbus_toolkit.pci_full_inventory import PCIInventoryCollector
from cbus_toolkit.pci_serial_address import decode_serial_address_receipt
from cbus_toolkit.simulator import PCISimulator
from cbus_toolkit.simulator_duplicate_addressing import SerialAddressFixture, SerialAddressFault
from tests.test_simulator_duplicates import fixture_units, SERIAL_A, SERIAL_B


A, B = '101136.1558', '101136.1559'
CO_A = b'\\05FF000F0018B106160615g\r'
CO_B = b'\\05FF000F0018B106170713g\r'
RECEIPT_A = b'g.86061000870018B106160000F8\r\n'
RECEIPT_B = b'g.86071000870018B106170000F6\r\n'
SERIAL_A_AT6 = b'860610008D0438FFFFFFFF18B10616A2000513\r\n'
FIRST = b'D8FF00' + b'00'*4 + b'01' + b'00'*17 + b'28\r\n'
MIDDLE = b'D8FF58' + b'00'*22 + b'D1\r\n'
LAST = b'D6FFB0' + b'00'*19 + b'80FB\r\n'
FIRST_MOVED = b'D8FF000020000001' + b'00'*17 + b'08\r\n'
FIRST_BOTH = b'D8FF0000A0000001' + b'00'*17 + b'88\r\n'
LAST_EMPTY = b'D6FFB0' + b'00'*20 + b'7B\r\n'


def fixture(*,pci_options=b'\x05',**options):
    nodes, pci = fixture_units()
    # Explicit fixture choice; the co fixture never changes PCI option bytes.
    pci.parameters[66] = pci_options
    settings = dict(allowed_destinations=[6,7], address_memory_policy='bus_only',
                    reply_tails={A:b'\0\0', B:b'\0\0'})
    settings.update(options)
    return SerialAddressFixture(nodes,pci,**settings)


def command(sim,data):
    return sim._command(data.rstrip(b'\r'),{'header':None})


def exchange(endpoint,request,expected):
    """One literal request; read exactly the independently expected response."""
    with socket.create_connection(endpoint,timeout=2) as stream:
        stream.sendall(request); received=b''
        while len(received)<len(expected):
            chunk=stream.recv(4096)
            if not chunk:raise AssertionError('Early fixture disconnect')
            received+=chunk
        if received!=expected:raise AssertionError((received,expected))
        return received


class SerialAddressFixtureTests(unittest.TestCase):
    def test_literal_selection_moves_only_one_serial_and_preserves_unknown_blocks(self):
        sim=fixture();before=sim.snapshot()
        self.assertEqual(command(sim,b'\\46FF002104g'),(b'g.'+SERIAL_A+SERIAL_B,None))
        self.assertEqual(command(sim,CO_A),(RECEIPT_A,None))
        self.assertEqual(command(sim,b'\\46FF002104g'),(b'g.'+SERIAL_B,None))
        self.assertEqual(command(sim,b'\\4606002104g'),(b'g.'+SERIAL_A_AT6,None))
        self.assertEqual(command(sim,b'\\4607002104g'),(b'g.',None))
        after=sim.snapshot();expected=deepcopy(before)
        expected['revision']=1;expected['physical_nodes'][A]['address']=6
        self.assertEqual(after,expected)
        self.assertEqual(sim.nodes[A].parameters[32],b'\xff')
        self.assertEqual(sim.co_operations[0]['persistence'],'memory_only')
        self.assertEqual(sim.co_operations[0]['outcome'],'moved')

    def test_literal_mmi_after_each_move_and_srchk_inner_outer_validation(self):
        sim=fixture(command_checksum=True)
        self.assertEqual(command(sim,b'\\05FF00FAFF0003g'),(b'g.'+FIRST+MIDDLE+LAST,None))
        self.assertEqual(command(sim,b'\\05FF000F0018B106160615EDg'),(RECEIPT_A,None))
        self.assertEqual(command(sim,b'\\05FF00FAFF0003g'),(b'g.'+FIRST_MOVED+MIDDLE+LAST,None))
        self.assertEqual(command(sim,b'\\05FF000F0018B106170713EDg'),(RECEIPT_B,None))
        self.assertEqual(command(sim,b'\\05FF00FAFF0003g'),(b'g.'+FIRST_BOTH+MIDDLE+LAST_EMPTY,None))
        # Outer sum valid, deliberately wrong inner sum: no node can move.
        for request,status in ((b'\\05FF000F0018B106160615ECg',b'g$'),
                               (b'\\05FF000F0018B106160614EEg',b'g#')):
            snapshot=sim.snapshot();count=len(sim.co_operations)
            self.assertEqual(command(sim,request)[0],status)
            self.assertEqual(sim.snapshot(),snapshot);self.assertEqual(len(sim.co_operations),count)

    def test_parameter32_is_an_explicit_independent_fixture_policy(self):
        sim=fixture(address_memory_policy='parameter32');before=sim.snapshot()
        self.assertEqual(command(sim,CO_A),(RECEIPT_A,None))
        expected=deepcopy(before);expected['revision']=1
        expected['physical_nodes'][A]['address']=6;expected['physical_nodes'][A]['parameters']['32']='06'
        self.assertEqual(sim.snapshot(),expected)
        self.assertFalse(sim.snapshot()['firmware_persistence_verified'])

    def test_fault_receipts_cannot_substitute_for_observed_movement(self):
        cases=((SerialAddressFault(move=False),RECEIPT_A,255,'matched'),
               (SerialAddressFault(reply=False),b'g.',6,'incomplete'),
               (SerialAddressFault(reported_source=9),b'g.86091000870018B106160000F5\r\n',6,'unverified'),
               (SerialAddressFault(reported_serial='101136.1689'),b'g.86061000870018B10699000075\r\n',6,'unverified'),
               (SerialAddressFault(move=False,bare=True),b'g.870018B10616000094\r\n',255,'unverified'))
        for fault,expected,address,status in cases:
            with self.subTest(fault=fault):
                sim=fixture(faults={A:fault})
                self.assertEqual(command(sim,CO_A),(expected,None))
                self.assertEqual(sim.nodes[A].address,address);self.assertEqual(sim.nodes[B].address,255)
                parsed=decode_serial_address_receipt(expected,serial=A,destination=6,local_unit=16)
                self.assertEqual(parsed.status,status);self.assertFalse(parsed.movement_verified)
                self.assertEqual(sim.co_operations[0]['fault'],sim.snapshot()['faults'][A])
        sim=fixture(reply_tails={A:b'\xfa\xce',B:b'\0\0'})
        self.assertEqual(command(sim,CO_A),(b'g.86061000870018B10616FACE30\r\n',None))

    def test_serial_lookup_empty_target_allowlist_and_exact_shape_fail_closed(self):
        sim=fixture()
        # Unknown serial is one broadcast with no matching physical node.
        self.assertEqual(command(sim,b'\\05FF000F000000000106F9g'),(b'g.',None))
        self.assertEqual(sim.co_operations[0]['outcome'],'no_matching_serial')
        before=sim.snapshot()
        for request in (b'\\05FF000F0018B106160814g', # invalid checksum
                        b'\\05FF000F0018B106160813g', # valid target8 outside explicit scope
                        b'\\05FF000F0018B10616FF1Cg', # occupied source255
                        b'\\05FF000F0018B10616100Bg', # occupied local16
                        b'\\05FF000F0018B10616061500g', # trailing CAL
                        b'05FF000F0018B106160615g'): # no explicit route
            with self.subTest(request=request):
                self.assertEqual(command(sim,request)[0],b'g#');self.assertEqual(sim.snapshot(),before)
        command(sim,CO_A);before=sim.snapshot()
        self.assertEqual(command(sim,CO_A)[0],b'g#')
        self.assertEqual(command(sim,b'\\05FF000F0018B106170614g')[0],b'g#')
        self.assertEqual(sim.snapshot(),before)

    def test_generic_writes_and_unknown_reads_remain_rejected(self):
        sim=fixture();before=sim.snapshot()
        for request in (b'\\46FF001120g',b'\\46FF00A3204E065Ag',b'\\461000A3429705g',
                        b'\\46FF002104A3204E065Ag',b'@A22006g',b'\\053800790101g',
                        b'\\46FF002199g',b'\\46FF001A2201g'):
            context={'header':None}
            with self.subTest(request=request):
                self.assertEqual(sim._command(request,context)[0],b'g#')
                self.assertEqual(context,{'header':None});self.assertEqual(sim.snapshot(),before)
        self.assertEqual(command(sim,b'\\4610001A4201g'),(b'g.82420537\r\n',None))
        self.assertEqual(sim.co_operations,[])

    def test_detached_node_inputs_and_snapshot_do_not_alias_physical_state(self):
        nodes,pci=fixture_units()
        sim=SerialAddressFixture(nodes,pci,allowed_destinations=[6],address_memory_policy='bus_only',
                                 reply_tails={A:b'\0\0',B:b'\0\0'})
        before=sim.snapshot();nodes[0].attributes[1]=b'OTHER';pci.parameters[66]=b'\0'
        sim.nodes[A].address=4;sim.nodes[B].parameters[32]=b'\0'
        snapshot=sim.snapshot();snapshot['physical_nodes'][A]['attributes']['4']='00'
        self.assertEqual(sim.snapshot(),before)

    def test_constructor_rejects_ambiguous_profiles_and_fault_contracts(self):
        changes=(lambda n,p:setattr(n[0],'address',1),lambda n,p:setattr(n[0],'address',16),
            lambda n,p:(setattr(n[0],'address',6),setattr(n[1],'address',6)),
            lambda n,p:n[0].attributes.update({1:b'KEYGL5  '}),
            lambda n,p:n[1].attributes.update({4:n[0].attributes[4]}),
            lambda n,p:n[0].attributes.update({4:bytes(12)}),
            lambda n,p:n[0].write_tags.update({32:78}),
            lambda n,p:n[1].parameters.update({34:b'\0'}),
            lambda n,p:p.parameters.update({66:b'\x03'}),
            lambda n,p:p.attributes.update({4:n[0].attributes[4]}))
        for change in changes:
            nodes,pci=fixture_units();change(nodes,pci)
            with self.subTest(change=change),self.assertRaises(ValueError):
                SerialAddressFixture(nodes,pci,allowed_destinations=[6,7],address_memory_policy='bus_only',
                                     reply_tails={A:b'\0\0',B:b'\0\0'})
        for options in ({'allowed_destinations':[]},{'allowed_destinations':[True]},
                        {'allowed_destinations':[255]},{'address_memory_policy':'guess'},
                        {'reply_tails':{A:b'\0\0'}},{'faults':{A:{'move':False}}}):
            with self.subTest(options=options),self.assertRaises(ValueError):fixture(**options)
        for options in ({'move':1},{'reply':None},{'bare':1},{'reported_source':False},
                        {'reported_source':256},{'reported_serial':'01.2'},
                        {'reply':False,'reported_serial':A},{'bare':True,'reported_source':6}):
            with self.subTest(options=options),self.assertRaises(ValueError):SerialAddressFault(**options)

    def test_persistence_is_serial_keyed_and_retains_order_profiles_and_faults(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json'
            nodes,pci=fixture_units()
            sim=SerialAddressFixture(nodes[::-1],pci,allowed_destinations=[7,6],address_memory_policy='parameter32',
                reply_tails={A:b'\xfa\xce',B:b'\0\0'},faults={B:SerialAddressFault(reply=False)},state_path=path)
            self.assertEqual(command(sim,b'\\46FF002104g'),(b'g.'+SERIAL_B+SERIAL_A,None))
            command(sim,CO_A);expected=sim.snapshot()
            loaded=SerialAddressFixture.from_state(path,fragment_sizes=(1,3,7))
            self.assertEqual(loaded.snapshot(),expected);self.assertEqual(list(loaded.nodes),[B,A])
            self.assertEqual(loaded.nodes[A].address,6);self.assertEqual(loaded.nodes[A].parameters[32],b'\x06')
            self.assertEqual(command(loaded,CO_B),(b'g.',None))
            final=SerialAddressFixture.from_state(path)
            self.assertEqual(final.nodes[B].address,7);self.assertEqual(final.nodes[A].address,6)
            self.assertEqual(final.revision,2);self.assertEqual(final.nodes[B].parameters[32],b'\x07')
            self.assertEqual(loaded.co_operations[-1]['persistence'],'committed')
            with self.assertRaises(ValueError):fixture(state_path=path)
            with self.assertRaises(ValueError):PCISimulator(state_path=path)
            self.assertFalse(list(Path(directory).glob('.serial-fixture-*')))

    def test_failed_persistence_before_replace_retains_old_disk_and_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path)
            before=sim.snapshot();raw=path.read_bytes()
            with patch('cbus_toolkit.simulator_duplicate_addressing.os.replace',side_effect=OSError('before replace')):
                self.assertEqual(command(sim,CO_A)[0],b'g#')
            self.assertEqual(sim.snapshot(),before);self.assertEqual(path.read_bytes(),raw)
            self.assertFalse(list(Path(directory).glob('.serial-fixture-*')))
            record=sim.co_operations[-1]
            self.assertEqual(record['outcome'],'persistence_error');self.assertFalse(record['disk_matches_proposed_state'])
            self.assertEqual(record['persistence'],'not_confirmed_memory_restored')

    def test_error_after_replace_keeps_committed_state_and_reports_uncertainty(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path)
            real_replace=os.replace
            def replace_then_fail(source,target):
                real_replace(source,target);raise OSError('after replace')
            with patch('cbus_toolkit.simulator_duplicate_addressing.os.replace',side_effect=replace_then_fail):
                self.assertEqual(command(sim,CO_A)[0],b'g#')
            self.assertEqual(sim.nodes[A].address,6)
            self.assertEqual(SerialAddressFixture.from_state(path).snapshot(),sim.snapshot())
            record=sim.co_operations[-1]
            self.assertEqual(record['persistence'],'committed_despite_error');self.assertTrue(record['disk_matches_proposed_state'])

    def test_interruption_preserves_original_and_secondary_probe_failure_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path)
            interrupt=KeyboardInterrupt('original');probe=SystemExit('secondary')
            with patch.object(sim,'_persist',side_effect=interrupt),patch.object(Path,'read_bytes',side_effect=probe):
                with self.assertRaises(KeyboardInterrupt) as raised:command(sim,CO_A)
            self.assertIs(raised.exception,interrupt)
            evidence=interrupt.serial_address_fixture_operation
            self.assertIsNone(evidence['disk_matches_proposed_state']);self.assertIn('SystemExit',evidence['persistence_probe_error'])
            self.assertEqual(sim.nodes[A].address,255);self.assertEqual(len(sim.co_operations),1)

    def test_external_state_change_and_revision_exhaustion_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path);before=sim.snapshot()
            path.write_bytes(b'external\n')
            self.assertEqual(command(sim,CO_A)[0],b'g#')
            self.assertEqual(path.read_bytes(),b'external\n');self.assertEqual(sim.snapshot(),before)
        sim=fixture();sim.revision=2**63-1;before=sim.snapshot()
        self.assertEqual(command(sim,CO_A)[0],b'g#');self.assertEqual(sim.snapshot(),before)
        self.assertEqual(sim.co_operations[-1]['outcome'],'revision_exhausted')

    def test_pre_persist_interruption_restores_bus_memory_and_leaves_disk_untouched(self):
        for method in ('_rebuild','_document','_bytes'):
            with self.subTest(method=method),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'state.json';sim=fixture(state_path=path,address_memory_policy='parameter32')
                before=sim.snapshot();disk=path.read_bytes();interruption=KeyboardInterrupt(method)
                with patch.object(sim,method,side_effect=interruption),patch.object(sim,'_persist') as persist,\
                        patch.object(Path,'read_bytes',side_effect=AssertionError('No disk probe before persistence')):
                    with self.assertRaises(KeyboardInterrupt) as raised:command(sim,CO_A)
                self.assertIs(raised.exception,interruption);persist.assert_not_called()
                self.assertEqual(sim.snapshot(),before);self.assertEqual(path.read_bytes(),disk)
                evidence=interruption.serial_address_fixture_operation
                self.assertFalse(evidence['persistence_attempted']);self.assertFalse(evidence['disk_matches_proposed_state'])
                self.assertEqual(evidence['old_address'],255);self.assertEqual(evidence['new_address'],255)

    def test_persistence_cleanup_interruption_cannot_replace_original_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path);before=sim.snapshot()
            original=KeyboardInterrupt('replace');secondary=SystemExit('unlink')
            with patch('cbus_toolkit.simulator_duplicate_addressing.os.replace',side_effect=original),\
                    patch('cbus_toolkit.simulator_duplicate_addressing.os.unlink',side_effect=secondary):
                with self.assertRaises(KeyboardInterrupt) as raised:command(sim,CO_A)
            self.assertIs(raised.exception,original);self.assertEqual(sim.snapshot(),before)
            self.assertEqual(SerialAddressFixture.from_state(path).snapshot(),before)
            self.assertIn('SystemExit',original.serial_address_fixture_operation['persistence_cleanup_error'])

    def test_cleanup_interruption_after_ordinary_error_is_not_swallowed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path);before=sim.snapshot()
            interruption=KeyboardInterrupt('cleanup')
            with patch('cbus_toolkit.simulator_duplicate_addressing.os.replace',side_effect=OSError('replace')),\
                    patch('cbus_toolkit.simulator_duplicate_addressing.os.unlink',side_effect=interruption):
                with self.assertRaises(KeyboardInterrupt) as raised:command(sim,CO_A)
            self.assertIs(raised.exception,interruption);self.assertEqual(sim.snapshot(),before)
            self.assertIn('OSError',interruption.serial_address_fixture_operation['persistence_prior_error'])

    def test_whole_state_loader_rejects_corruption_ambiguity_and_unsupported_topology(self):
        original=fixture().snapshot()
        mutations=(lambda d:d.update(extra=True),lambda d:d.update(format='other'),
            lambda d:d.update(fixture_only=1),lambda d:d.update(firmware_persistence_verified=True),
            lambda d:d.update(revision=True),lambda d:d.update(revision=2**63),
            lambda d:d.update(response_order=[A,A]),lambda d:d['physical_nodes'].pop(A),
            lambda d:d['physical_nodes'][A].update(extra=True),lambda d:d['physical_nodes'][A].update(address=True),
            lambda d:d['physical_nodes'][A].update(mmi_state=1),
            lambda d:d['physical_nodes'][A]['attributes'].update({'04':'00'}),
            lambda d:d['physical_nodes'][A]['attributes'].update({'256':'00'}),
            lambda d:d['physical_nodes'][A]['attributes'].update({'4':'00'}),
            lambda d:d['physical_nodes'][A]['parameters'].update({'32':'f'}),
            lambda d:d['physical_nodes'][A]['parameters'].update({'32':'gg'}),
            lambda d:d['physical_nodes'][A]['parameters'].update({'32':'00 '*10}),
            lambda d:d['physical_nodes'][A]['parameters'].update({'256':'00'}),
            lambda d:d['physical_nodes'][A]['parameters'].update({'0':'00'*31}),
            lambda d:d.update(address_memory_policy='unknown'),lambda d:d.update(allowed_destinations=[6,6]),
            lambda d:d.update(allowed_destinations=[16]),lambda d:d.update(allowed_destinations=[True]),
            lambda d:d['reply_tails'].update({A:'00'}),lambda d:d['reply_tails'].update({'1.2':'0000'}),
            lambda d:d['faults'].pop(A),lambda d:d['faults'][A].update(move=1),
            lambda d:d['faults'][A].update(reply=False,bare=True),
            lambda d:d['faults'][A].update(reported_serial='0101136.1558'),
            lambda d:d['pci']['parameters'].update({'66':'03'}))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json'
            for change in mutations:
                document=deepcopy(original);change(document);raw=json.dumps(document).encode();path.write_bytes(raw)
                with self.subTest(change=change),self.assertRaises(ValueError):SerialAddressFixture.from_state(path)
                self.assertEqual(path.read_bytes(),raw)
            for raw in (b'{"format":1,"format":2}',b'\xff',b'[]',b'{',b' '*1048577):
                path.write_bytes(raw)
                with self.subTest(raw=raw[:20]),self.assertRaises(ValueError):SerialAddressFixture.from_state(path)
            path.write_text(json.dumps(original))
            with self.assertRaises(ValueError):SerialAddressFixture.from_state(path,allowed_destinations=[8])

    def test_inventory_and_restarted_fixture_independently_expose_real_and_fake_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            report={'passed':False,'scope':'Synthetic fixture persistence; no hardware EEPROM claim','cases':[]}
            for index,fault in enumerate((SerialAddressFault(),SerialAddressFault(reply=False),SerialAddressFault(move=False))):
                with self.subTest(fault=fault):
                    path=Path(directory)/str(index)/'state.json'
                    sim=fixture(state_path=path,faults={A:fault},fragment_sizes=(1,3,7),response_delay=.001)
                    def inventory(endpoint):
                        return PCIInventoryCollector(*endpoint,local_unit=16,overall_timeout=5,
                            observation_timeout=.5,confirmation_timeout=.1,response_timeout=.1,quiet_period=.025).collect_inventory()
                    with sim.running() as endpoint:
                        before=inventory(endpoint);self.assertTrue(before.complete);self.assertEqual(before.duplicate_addresses,(255,))
                        expected=RECEIPT_A if fault.reply else b'g.'
                        receipt=exchange(endpoint,CO_A,expected)
                        after=inventory(endpoint);self.assertTrue(after.complete)
                    restored=SerialAddressFixture.from_state(path,response_delay=.001)
                    with restored.running() as endpoint:restarted=inventory(endpoint)
                    self.assertTrue(restarted.complete)
                    serial_map=lambda result:{reply.serial:observation.address for observation in result.serial_observations for reply in observation.replies}
                    self.assertEqual(serial_map(before),{'100966.1187':16,A:255,B:255})
                    expected_map={'100966.1187':16,A:6 if fault.move else 255,B:255}
                    self.assertEqual(serial_map(after),expected_map);self.assertEqual(serial_map(restarted),expected_map)
                    self.assertEqual(len(sim.co_operations),1);self.assertEqual(restored.co_operations,[])
                    requests=[bytes.fromhex(item['hex']) for item in sim.wire_log if item['direction']=='rx']
                    self.assertEqual(sum(CO_A.rstrip(b'\r') in request for request in requests),1)
                    self.assertFalse(any(b'A3204E' in request or b'1120' in request or b'A342' in request for request in requests))
                    self.assertFalse([item for item in sim.wire_log+restored.wire_log if item.get('reason')])
                    report['cases'].append({'fault':sim.snapshot()['faults'][A],'before':before.as_dict(),
                        'receipt':decode_serial_address_receipt(receipt,serial=A,destination=6,local_unit=16).as_dict(),
                        'after':after.as_dict(),'restart':restarted.as_dict(),'operation':sim.co_operations[0],
                        'persisted_state':restored.snapshot(),'wire':sim.wire_log,'restart_wire':restored.wire_log})
            report['passed']=True
            if destination:=os.environ.get('CBUS_DUPLICATE_ADDRESS_FIXTURE_REPORT'):
                output=Path(destination);output.parent.mkdir(parents=True,exist_ok=True)
                output.write_text(json.dumps(report,indent=2)+'\n')


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'),'Set CBUS_CGATE_TEST_HOST for native restarted-fixture reads')
class NativeSerialAddressFixtureTests(unittest.TestCase):
    def test_exact_vendor_reads_both_persisted_serials_without_addressing_or_database_writes(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects,NativeDatabase
        from cbus_toolkit.networks import NativeNetworks
        from cbus_toolkit.programming import xml_text
        project='DS'+uuid4().hex[:6].upper();network='//'+project+'/254'
        report={'passed':False,'scope':'Literal co fixture mutation; original C-Gate read-only discovery after fixture reload'}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path,response_delay=.01,pci_options=b'\x07')
            with sim.running() as endpoint:exchange(endpoint,CO_A,RECEIPT_A)
            restored=SerialAddressFixture.from_state(path,response_delay=.01);before=restored.snapshot()
            with restored.running('0.0.0.0',0) as (_,fixture_port),CGateClient(
                os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=45) as client:
                projects=NativeProjects(client);db=NativeDatabase(client);networks=NativeNetworks(client);created=False
                try:
                    projects.operation('new',project);created=True
                    db.create_network(project,254,'Serial_Restart','Cni',
                        os.environ.get('CBUS_CGATE_SIMULATOR_HOST','host.docker.internal')+':'+str(fixture_port))
                    projects.operation('save',project);xml_before=xml_text(db.get(network,xml=True))
                    for name,value in (('AutoUnravel','no'),('AutoUpdate','no'),('Retries','0')):
                        self.assertEqual(client.command('SET '+network+' '+name+' '+value).code,200)
                    networks.open(network)
                    deadline=time.monotonic()+25
                    while time.monotonic()<deadline:
                        if any('InterfaceState=running' in line for line in client.command('GET '+network+' InterfaceState').lines):break
                        time.sleep(.1)
                    else:self.fail('Native interface did not start')
                    self.assertEqual(client.command('SET '+network+' Retries 0').code,200)
                    retries=client.command('GET '+network+' Retries')
                    self.assertEqual(retries.lines,('300 '+network+': Retries=0',))
                    start=len(restored.wire_log);checks={}
                    for address in (6,255):
                        result=client.command('NET CHECKUNIT '+network+' '+str(address))
                        self.assertEqual(result.lines,('120 Single unit detected at address: '+str(address),))
                        checks[str(address)]=list(result.lines)
                    self.assertEqual(xml_text(db.get(network,xml=True)),xml_before)
                    self.assertEqual(restored.snapshot(),before);self.assertEqual(restored.co_operations,[])
                    replies=[bytes.fromhex(item['hex']) for item in restored.wire_log[start:] if item['direction']=='tx']
                    self.assertTrue(any(SERIAL_A_AT6 in reply for reply in replies));self.assertTrue(any(SERIAL_B in reply for reply in replies))
                    requests=[bytes.fromhex(item['hex']).upper() for item in restored.wire_log if item['direction']=='rx']
                    self.assertFalse(any(b'05FF000F' in request or b'A3204E' in request or b'1120' in request for request in requests))
                    self.assertFalse([item for item in restored.wire_log if item.get('reason')])
                    report.update(passed=True,checks=checks,retries=list(retries.lines),persisted_state=before,
                        after_state=restored.snapshot(),before_database_xml=xml_before,after_database_xml=xml_text(db.get(network,xml=True)),
                        literal_move_wire=sim.wire_log,literal_move_operation=sim.co_operations[0])
                finally:
                    cleanup=[]
                    if created:
                        for command_text in ('NET CLOSE '+network,'PROJECT CLOSE '+project,'PROJECT DELETE '+project):
                            try:client.command(command_text)
                            except Exception as error:cleanup.append(str(error))
                    report['cleanup_errors']=cleanup;report['native_read_wire']=restored.wire_log
                    if destination:=os.environ.get('CBUS_NATIVE_DUPLICATE_ADDRESS_FIXTURE_REPORT'):
                        output=Path(destination);output.parent.mkdir(parents=True,exist_ok=True)
                        output.write_text(json.dumps(report,indent=2)+'\n')
                    if report['passed']:self.assertEqual(cleanup,[])


if __name__=='__main__':unittest.main()
