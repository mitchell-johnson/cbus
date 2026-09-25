"""Independent literal reads, serial-keyed fixture state and durable journal faults."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from cbus_toolkit import pci_selected_serial as implementation
from cbus_toolkit.pci_selected_serial import SelectedSerialCoordinator, SelectedSerialPlan, SelectedSerialUncertain, _Journal
from cbus_toolkit.pci_serial_address_transport import SerialAddressExchange
from cbus_toolkit.pci_serial_address import decode_serial_address_receipt
from cbus_toolkit.pci_full_inventory import PCIInventoryCollector
from cbus_toolkit.simulator_duplicate_addressing import SerialAddressFixture, SerialAddressFault
from tests.test_simulator_duplicate_addressing import fixture, A, B, CO_A, RECEIPT_A, FIRST, MIDDLE, LAST, FIRST_MOVED, SERIAL_A_AT6
from tests.test_pci_full_inventory import conversation, successful_responses
from tests.test_pci_full_inventory import ERROR_LAST, LOCAL_AT_255
from tests.test_pci_serials import BARE_PCI, SERIAL_B
from tests.test_pci_serial_address_transport import Clock


LOCAL='100966.1187'
SETTINGS=dict(local_unit=16,expected_local_serial=LOCAL,overall_timeout=5.,observation_timeout=.5,
              confirmation_timeout=.1,mmi_response_timeout=.1,quiet_period=.02,
              options_response_timeout=.02,address_response_timeout=.02)
OPTIONS=b'g.82420537\r\n'
LOCAL_REQUEST=b'\\4610002104g\r'
OPTIONS_REQUEST=b'\\4610001A4201g\r'
MMI_REQUEST=b'\\05FF00FAFF00g\r'


def manager(endpoint,**options): return SelectedSerialCoordinator(*endpoint,**(SETTINGS|options))


def after_responses():
    full=FIRST_MOVED+MIDDLE+LAST
    return [b'g.'+full,b'g.'+SERIAL_A_AT6,b'g.'+BARE_PCI,b'g.'+SERIAL_B,b'g.'+full]


def exchange(*, errors=(), capture=True, received=RECEIPT_A, attempted=True):
    receipt=decode_serial_address_receipt(received,serial=A,destination=6,local_unit=16)
    return SerialAddressExchange(CO_A,received,attempted,attempted,len(received),receipt,
        'response_window_elapsed' if capture else 'send_error',capture,.02,.02,.02,.5,4096,True,tuple(errors))


class SelectedSerialTests(unittest.TestCase):
    def test_independent_literal_peer_full_sequence_and_recovery_do_not_replay(self):
        initial=successful_responses()+[b'g.'+BARE_PCI,OPTIONS]
        responses=initial+initial+[RECEIPT_A]+after_responses()+after_responses()
        with tempfile.TemporaryDirectory() as tmp,conversation(responses) as (endpoint,state):
            subject=manager(endpoint);plan=subject.plan(A,6)
            saved=SelectedSerialPlan.from_dict(json.loads(json.dumps(plan.as_dict())))
            result=subject.apply(saved,recovery_path=Path(tmp)/'move.json')
            recovered=subject.load_recovery(Path(tmp)/'move.json')
            observed=subject.verify(recovered)
            with self.assertRaises(RuntimeError):subject.apply(plan,recovery_path=Path(tmp)/'another.json')
        before_requests=[MMI_REQUEST,LOCAL_REQUEST,b'\\46FF002104g\r',MMI_REQUEST,LOCAL_REQUEST,OPTIONS_REQUEST]
        after_requests=[MMI_REQUEST,b'\\4606002104g\r',LOCAL_REQUEST,b'\\46FF002104g\r',MMI_REQUEST]
        self.assertEqual(state['requests'],before_requests*2+[CO_A]+after_requests*2)
        self.assertFalse(any(state['extra']));self.assertTrue(all(state['closed']))
        self.assertEqual(result.outcome,'observed_expected_change');self.assertEqual(observed.outcome,result.outcome)
        evidence=result.as_dict();self.assertTrue(evidence['receipt_matches_request'])
        self.assertTrue(evidence['expected_identity_change']);self.assertEqual(evidence['unexpected_changes'],[])
        self.assertFalse(evidence['atomic_observation']);self.assertFalse(evidence['firmware_persistence_verified'])
        self.assertFalse(evidence['physical_compatibility_verified']);self.assertFalse(observed.as_dict()['send_attempted'])
        self.assertEqual(recovered.as_dict(),saved.as_dict())

    def test_fixture_true_missing_wrong_and_forged_receipts_have_independent_restart_outcomes(self):
        report=[]
        for label,fault,expected,matched in (
            ('move_and_reply',SerialAddressFault(),'observed_expected_change',True),
            ('move_without_reply',SerialAddressFault(reply=False),'observed_expected_change',False),
            ('fake_success',SerialAddressFault(move=False),'observed_unchanged',True),
            ('wrong_source',SerialAddressFault(reported_source=9),'observed_expected_change',False)):
            with self.subTest(case=label),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'fixture.json';sim=fixture(state_path=path,faults={A:fault})
                with sim.running() as endpoint:
                    subject=manager(endpoint);plan=subject.plan(A,6)
                    result=subject.apply(plan,recovery_path=Path(tmp)/'journal.json')
                    self.assertEqual(result.outcome,expected);self.assertEqual(result.as_dict()['receipt_matches_request'],matched)
                    self.assertEqual(len(sim.co_operations),1);self.assertEqual(sim.nodes[B].address,255)
                    self.assertEqual(sim.nodes[A].address,6 if fault.move else 255)
                    requests=[row['data_hex'] for row in sim.wire_log if row['direction']=='client_to_simulator']
                restarted=SerialAddressFixture.from_state(path)
                self.assertEqual(restarted.nodes[A].address,6 if fault.move else 255)
                self.assertEqual(restarted.nodes[B].address,255)
                # Read-only inventory on the independently reloaded fixture (new port).
                with restarted.running() as endpoint:
                    inventory=PCIInventoryCollector(*endpoint,local_unit=16,overall_timeout=2.,observation_timeout=.5,
                        confirmation_timeout=.1,response_timeout=.1,quiet_period=.02).collect_inventory()
                self.assertTrue(inventory.complete)
                mapping={item.address:list(item.serials) for item in inventory.serial_observations}
                self.assertEqual(mapping,{6:[A],16:[LOCAL],255:[B]} if fault.move else {16:[LOCAL],255:[A,B]})
                report.append({'case':label,'outcome':result.outcome,'receipt_matches_request':matched,
                    'restart_identities':mapping,'co_operations':1,'database_updated':False,
                    'firmware_persistence_verified':False})
        # Durable evidence is opt-in so ordinary test runs do not mutate the repository.
        import os
        if os.environ.get('CBUS_SELECTED_SERIAL_REPORT'):
            Path(os.environ['CBUS_SELECTED_SERIAL_REPORT']).write_text(json.dumps({'passed':True,'cases':report},indent=2)+'\n')

    def test_strict_plan_rejects_changed_expected_map_raw_bytes_and_serial_metadata(self):
        sim=fixture()
        with sim.running() as endpoint:plan=manager(endpoint).plan(A,6)
        original=plan.as_dict()
        def expected(value):value['expected_after']['identities'][0]['serials']=[B]
        def raw(value):value['before']['initial_mmi']['received_hex']='672e'+LAST.hex()
        def serial(value):value['before']['serial_observations'][-1]['serials']=[A]
        def local(value):value['local_identity']['serials']=[A]
        def options(value):value['local_options']['value']=7
        def unknown(value):value['unexpected']='field'
        def source(value):value['source']=254
        for mutation in (expected,raw,serial,local,options,unknown,source):
            value=deepcopy(original);mutation(value)
            with self.subTest(mutation=mutation.__name__),self.assertRaises(ValueError):SelectedSerialPlan.from_dict(value)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.json'
            for text in ('{"format":1,"format":2}', '{"value":NaN}', ' '* (implementation.MAX_PLAN_BYTES+1)):
                path.write_text(text)
                with self.assertRaises(ValueError):SelectedSerialPlan.load(path)

    def test_plan_json_has_shared_depth_utf8_and_unicode_bounds(self):
        value = 0
        for _ in range(implementation.MAX_JSON_DEPTH): value = [value]
        self.assertTrue(implementation._json(value).startswith('['))
        with self.assertRaisesRegex(ValueError, 'nesting'):
            implementation._json([value])
        with self.assertRaisesRegex(ValueError, 'Unicode'):
            implementation._json({'value': '\ud800'})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'utf16.json'
            path.write_bytes('{"format":1}'.encode('utf-16'))
            with self.assertRaisesRegex(ValueError, 'UTF-8'):
                SelectedSerialPlan.load(path)

    def test_options07_and_late_changed_local_identity_reject_before_co(self):
        sim=fixture(pci_options=b'\x07')
        with sim.running() as endpoint:
            with self.assertRaisesRegex(ValueError,'05'):manager(endpoint).plan(A,6)
            self.assertEqual(sim.co_operations,[])
        sim=fixture()
        with tempfile.TemporaryDirectory() as tmp,sim.running() as endpoint:
            subject=manager(endpoint);plan=subject.plan(A,6)
            local=deepcopy(plan.as_dict()['local_identity'])
            # Valid exact local reply containing another known serial, after the full inventory.
            raw=b'8D0438FFFFFFFF18B10616A20005AF'
            local['received_hex']=(b'g.'+raw+b'\r\n').hex();local['bytes_received']=len(b'g.'+raw+b'\r\n')
            local['serials']=[A];local['replies'][0].update(serial=A,data_hex='38ffffffff18b10616a20005',raw_hex=raw.hex())
            # This is a structurally valid alternate local serial, observed after full MMI/serial inventory.
            fake=types.SimpleNamespace(last_observation=None,_absolute_deadline=None)
            fake.collect_serials=lambda address:types.SimpleNamespace(as_dict=lambda:local)
            with patch.object(subject,'_local_identity',return_value=fake),self.assertRaisesRegex(ValueError,'Pinned local PCI serial changed') as caught:
                subject.apply(plan,recovery_path=Path(tmp)/'move.json')
            self.assertFalse(Path(tmp,'move.json').exists());self.assertEqual(sim.co_operations,[])
            self.assertIn('local_identity',caught.exception.selected_serial_evidence)

    def test_occupied_destination_stale_source_and_partial_mmi_are_never_authority(self):
        sim=fixture()
        with tempfile.TemporaryDirectory() as tmp,sim.running() as endpoint:
            subject=manager(endpoint);plan=subject.plan(A,6)
            # Independent fixture action consumes the planned target before apply.
            sim._command(b'\\05FF000F0018B106170614g',{'header':None})
            self.assertEqual(sim.nodes[B].address,6)
            with self.assertRaises(ValueError):subject.apply(plan,recovery_path=Path(tmp)/'move.json')
            self.assertEqual(len(sim.co_operations),1);self.assertEqual(sim.nodes[A].address,255)
        with conversation([b'g.'+FIRST+LAST]) as (endpoint,state):
            with self.assertRaises(ValueError):manager(endpoint).plan(A,6)
        self.assertEqual(state['requests'],[MMI_REQUEST])

    def test_send_error_and_interruption_retain_exchange_and_stop_network_io(self):
        for interrupt in (False,True):
            sim=fixture()
            with self.subTest(interrupt=interrupt),tempfile.TemporaryDirectory() as tmp,sim.running() as endpoint:
                subject=manager(endpoint);plan=subject.plan(A,6)
                first=KeyboardInterrupt('send cancelled') if interrupt else None
                recorded=exchange(errors=({'phase':'send','type':'OSError','message':'partial send'},),capture=False)
                fake=types.SimpleNamespace(last_exchange=None,_absolute_deadline=None)
                calls=[]
                def send(serial,destination):
                    calls.append((serial,destination));fake.last_exchange=recorded
                    if first:raise first
                    return recorded
                fake.send_serial_address=send
                original_inventory=subject._inventory;inventory_calls=[]
                def inventory():inventory_calls.append(True);return original_inventory()
                with patch.object(subject,'_transport',return_value=fake),patch.object(subject,'_inventory',side_effect=inventory):
                    with self.assertRaises(KeyboardInterrupt if interrupt else SelectedSerialUncertain) as caught:
                        subject.apply(plan,recovery_path=Path(tmp)/'move.json')
                if first:self.assertIs(caught.exception,first)
                self.assertEqual(inventory_calls,[True]);self.assertEqual(calls,[(A,6)])
                self.assertTrue(caught.exception.selected_serial_evidence['send_attempted'])
                self.assertIsNone(caught.exception.selected_serial_evidence['after'])
                self.assertEqual(subject.load_recovery(Path(tmp)/'move.json').as_dict(),plan.as_dict())

    def test_journal_failure_before_and_after_replacement_never_invokes_transport(self):
        for after_replace in (False,True):
            sim=fixture()
            with self.subTest(after_replace=after_replace),tempfile.TemporaryDirectory() as tmp,sim.running() as endpoint:
                subject=manager(endpoint);plan=subject.plan(A,6);path=Path(tmp)/'journal.json'
                journal=_Journal(path);native_replace=implementation.os.replace;first=KeyboardInterrupt('journal')
                def replacement(source,destination):
                    if after_replace:native_replace(source,destination)
                    raise first
                with patch.object(subject,'_new_journal',return_value=journal),patch('cbus_toolkit.pci_selected_serial.os.replace',side_effect=replacement):
                    with self.assertRaises(KeyboardInterrupt) as caught:subject.apply(plan,recovery_path=path)
                self.assertIs(caught.exception,first);self.assertEqual(sim.co_operations,[])
                self.assertIsNone(caught.exception.selected_serial_evidence['exchange'])
                self.assertEqual(journal.last_update['disk_matches_proposed'],after_replace)
                self.assertFalse(caught.exception.selected_serial_evidence['attempt_durability_verified'])
                disk=json.loads(path.read_text());self.assertEqual(disk['state'],'write_attempted' if after_replace else 'preconditions_checked')

    def test_journal_post_exchange_failure_stops_before_independent_verification(self):
        sim=fixture()
        with tempfile.TemporaryDirectory() as tmp,sim.running() as endpoint:
            subject=manager(endpoint);plan=subject.plan(A,6);journal=_Journal(Path(tmp)/'journal.json')
            original=journal._sync_directory;count=[]
            def sync():
                count.append(True)
                if len(count)==3:raise OSError('directory sync failed after receipt')
                original()
            with patch.object(subject,'_new_journal',return_value=journal),patch.object(journal,'_sync_directory',side_effect=sync):
                with self.assertRaises(OSError) as caught:subject.apply(plan,recovery_path=journal.path)
            self.assertEqual(len(sim.co_operations),1);self.assertEqual(sim.nodes[A].address,6)
            self.assertIsNone(caught.exception.selected_serial_evidence['after'])
            self.assertTrue(caught.exception.selected_serial_evidence['exchange']['receipt']['receipt_matches_request'])
            # Explicit separate recovery reads inventory and cannot construct a writer.
            with patch.object(subject,'_transport',side_effect=AssertionError('No write transport in verify')):
                self.assertEqual(subject.verify(subject.load_recovery(journal.path)).outcome,'observed_expected_change')

    def test_existing_journal_never_overwritten_and_original_interrupt_wins_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'journal.json';path.write_text('KEEP')
            with self.assertRaises(FileExistsError):_Journal(path).write({'value':1})
            self.assertEqual(path.read_text(),'KEEP')
            path.unlink();journal=_Journal(path);journal.write({'value':1})
            first=KeyboardInterrupt('first')
            with patch('cbus_toolkit.pci_selected_serial.os.replace',side_effect=first), \
                    patch.object(journal,'_read_current',side_effect=[journal.expected,SystemExit('probe')]):
                with self.assertRaises(KeyboardInterrupt) as caught:journal.write({'value':2})
            self.assertIs(caught.exception,first);self.assertIsNone(journal.last_update['disk_matches_proposed'])

    def test_first_child_interruption_survives_serialization_and_copy_interruptions(self):
        subject=manager(('127.0.0.1',10001));first=KeyboardInterrupt('child')
        class BadObservation:
            def as_dict(self):raise SystemExit('serialization')
        child=types.SimpleNamespace(last_observation=BadObservation())
        def collect():raise first
        child.collect_inventory=collect
        with patch.object(subject,'_inventory',return_value=child):
            with self.assertRaises(KeyboardInterrupt) as caught:subject.plan(A,6)
        self.assertIs(caught.exception,first)
        self.assertEqual(first.selected_serial_evidence['errors'][0]['phase'],'before_evidence')
        first=KeyboardInterrupt('original');evidence=subject._base('verify')
        with patch('cbus_toolkit.pci_selected_serial._json',side_effect=SystemExit('copy')):
            result=subject._error(first,evidence)
        self.assertIs(result,first);self.assertEqual(first.selected_serial_evidence['outcome'],'uncertain')
        self.assertEqual(first.selected_serial_evidence['errors'][-1]['phase'],'evidence_copy')
        first=KeyboardInterrupt('transport');evidence=subject._base('apply')
        child=types.SimpleNamespace(last_exchange=BadObservation(),send_serial_address=collect)
        with self.assertRaises(KeyboardInterrupt) as caught:
            subject._phase(evidence,'exchange',child,'send_serial_address',float('inf'))
        self.assertIs(caught.exception,first)
        self.assertTrue(evidence['transport_invoked']);self.assertIsNone(evidence['send_attempted'])

    def test_directory_and_file_sync_interruptions_survive_close_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=_Journal(Path(tmp)/'journal.json');first=KeyboardInterrupt('sync')
            with patch('cbus_toolkit.pci_selected_serial.os.open',return_value=999), \
                    patch('cbus_toolkit.pci_selected_serial.os.fsync',side_effect=first), \
                    patch('cbus_toolkit.pci_selected_serial.os.close',side_effect=SystemExit('close')):
                with self.assertRaises(KeyboardInterrupt) as caught:journal._sync_directory()
            self.assertIs(caught.exception,first);self.assertEqual(journal.last_update['cleanup_errors'][0]['type'],'SystemExit')
            handle=types.SimpleNamespace(write=lambda raw:None,flush=lambda:None,fileno=lambda:999)
            def bad_close():raise SystemExit('file close')
            handle.close=bad_close
            with patch('cbus_toolkit.pci_selected_serial.os.fdopen',return_value=handle), \
                    patch('cbus_toolkit.pci_selected_serial.os.fsync',side_effect=first):
                with self.assertRaises(KeyboardInterrupt) as caught:journal._write_descriptor(999,b'payload')
            self.assertIs(caught.exception,first);self.assertEqual(journal.last_update['cleanup_errors'][-1]['message'],'file close')

    def test_verification_interruption_is_uncertain_and_never_constructs_transport(self):
        sim=fixture()
        with sim.running() as endpoint:plan=manager(endpoint).plan(A,6)
        subject=manager(endpoint);first=KeyboardInterrupt('verify')
        child=types.SimpleNamespace(last_observation=None)
        def collect():raise first
        child.collect_inventory=collect
        with patch.object(subject,'_inventory',return_value=child), \
                patch.object(subject,'_transport',side_effect=AssertionError('No recovery writes')):
            with self.assertRaises(KeyboardInterrupt) as caught:subject.verify(plan)
        self.assertIs(caught.exception,first);self.assertEqual(first.selected_serial_evidence['outcome'],'uncertain')
        self.assertFalse(first.selected_serial_evidence['send_attempted'])

    def test_state3_and_cross_address_serial_are_rejected_without_local_options_or_co(self):
        cases=([b'g.'+FIRST+MIDDLE+ERROR_LAST,b'g.'+BARE_PCI,b'g.'+SERIAL_B,b'g.'+FIRST+MIDDLE+ERROR_LAST],
               successful_responses(serial=b'g.'+LOCAL_AT_255))
        for responses in cases:
            with self.subTest(responses=responses),conversation(responses) as (endpoint,state):
                with self.assertRaises(ValueError):manager(endpoint).plan(A,6)
            self.assertEqual(len(state['requests']),4)
            self.assertNotIn(OPTIONS_REQUEST,state['requests']);self.assertNotIn(CO_A,state['requests'])

    def test_missing_final_coverage_preserves_after_identities_but_outcome_uncertain(self):
        initial=successful_responses()+[b'g.'+BARE_PCI,OPTIONS]
        ending=after_responses();ending[-1]=b'g.'+FIRST_MOVED+LAST
        with tempfile.TemporaryDirectory() as tmp,conversation(initial+initial+[RECEIPT_A]+ending) as (endpoint,state):
            subject=manager(endpoint);plan=subject.plan(A,6)
            result=subject.apply(plan,recovery_path=Path(tmp)/'journal.json')
        self.assertEqual(result.outcome,'uncertain');evidence=result.as_dict()
        self.assertTrue(evidence['receipt_matches_request']);self.assertFalse(evidence['after_collection_complete'])
        self.assertEqual([x['serials'] for x in evidence['after']['serial_observations']],[[A],[LOCAL],[B]])
        self.assertEqual(state['requests'].count(CO_A),1)

    def test_malformed_or_truncated_receipt_stops_network_io_after_whole_capture(self):
        initial=successful_responses()+[b'g.'+BARE_PCI,OPTIONS]
        for suffix in (b'XX\r\n',b'86'):
            with self.subTest(suffix=suffix),tempfile.TemporaryDirectory() as tmp, \
                    conversation(initial+initial+[RECEIPT_A+suffix]) as (endpoint,state):
                subject=manager(endpoint);plan=subject.plan(A,6)
                with self.assertRaises(SelectedSerialUncertain) as caught:
                    subject.apply(plan,recovery_path=Path(tmp)/'journal.json')
                evidence=caught.exception.selected_serial_evidence
                self.assertTrue(evidence['exchange']['capture_complete']);self.assertIsNone(evidence['after'])
                self.assertEqual(evidence['exchange']['received_hex'],(RECEIPT_A+suffix).hex())
            self.assertEqual(len(state['requests']),13);self.assertEqual(state['requests'][-1],CO_A)

    def test_unexpected_second_move_is_reported_without_automatic_inverse_operation(self):
        sim=fixture()
        with tempfile.TemporaryDirectory() as tmp,sim.running() as endpoint:
            subject=manager(endpoint);plan=subject.plan(A,6);original=subject._inventory;calls=[]
            def inventory():
                calls.append(True)
                if len(calls)==2:sim._command(b'\\05FF000F0018B106170713g',{'header':None})
                return original()
            with patch.object(subject,'_inventory',side_effect=inventory):
                result=subject.apply(plan,recovery_path=Path(tmp)/'journal.json')
            self.assertEqual(result.outcome,'observed_unexpected_change')
            self.assertEqual([x['address'] for x in result.as_dict()['unexpected_changes']],[7,255])
            self.assertEqual(len(sim.co_operations),2)  # One workflow co plus one independent injected topology change.
            self.assertEqual(sim.nodes[A].address,6);self.assertEqual(sim.nodes[B].address,7)

    def test_parent_deadline_after_durable_marking_does_not_send_and_late_read_is_retained(self):
        sim=fixture()
        # This case exercises parent-deadline bookkeeping after planning, not
        # the simulator's response latency.  The suite-wide 20 ms fixture
        # window is too small to bound a separately scheduled simulator thread
        # under a loaded test runner, so give this setup read a realistic
        # margin before switching to the deterministic clock below.
        with sim.running() as endpoint:
            plan=manager(endpoint,options_response_timeout=.2).plan(A,6)
        value=plan.as_dict();subject=manager(endpoint,options_response_timeout=.2);clock=Clock()
        def before(evidence,deadline):
            for key in ('before','local_identity','local_options'):evidence[key]=deepcopy(value[key])
            return implementation._inventory_proof(value['before'],value['endpoint'],16,False)
        with tempfile.TemporaryDirectory() as tmp:
            journal=_Journal(Path(tmp)/'journal.json');sync=journal._sync_directory;calls=[]
            def delayed_sync():
                sync();calls.append(True)
                if len(calls)==2:clock.value+=5
            child=types.SimpleNamespace(last_exchange=None)
            def forbidden(*args):raise AssertionError('No transport request after parent deadline')
            child.send_serial_address=forbidden
            with patch.object(subject,'_before',side_effect=before),patch.object(subject,'_transport',return_value=child), \
                    patch.object(subject,'_new_journal',return_value=journal),patch.object(journal,'_sync_directory',side_effect=delayed_sync), \
                    patch('cbus_toolkit.pci_selected_serial.time.monotonic',side_effect=clock):
                with self.assertRaises(TimeoutError) as caught:subject.apply(plan,recovery_path=journal.path)
            evidence=caught.exception.selected_serial_evidence
            self.assertTrue(evidence['attempt_durability_verified']);self.assertFalse(evidence['send_attempted'])
            self.assertIsNone(evidence['exchange'])
        clock=Clock();child=types.SimpleNamespace(last_observation=None)
        saved=types.SimpleNamespace(as_dict=lambda:deepcopy(value['before']))
        def late():child.last_observation=saved;clock.value+=5;return saved
        child.collect_inventory=late
        subject=manager(endpoint,options_response_timeout=.2)
        with patch.object(subject,'_inventory',return_value=child),patch('cbus_toolkit.pci_selected_serial.time.monotonic',side_effect=clock):
            with self.assertRaises(TimeoutError) as caught:subject.verify(plan)
        self.assertEqual(caught.exception.selected_serial_evidence['after'],value['before'])
        self.assertEqual(caught.exception.selected_serial_evidence['outcome'],'uncertain')

    def test_external_journal_growth_and_symlink_are_bounded_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'journal.json';journal=_Journal(path);journal.write({'value':1})
            with patch('cbus_toolkit.pci_selected_serial.MAX_JOURNAL_BYTES',128):
                path.write_bytes(b'x'*129)
                with self.assertRaisesRegex(ValueError,'size bound'):journal.write({'value':2})
            self.assertEqual(path.read_bytes(),b'x'*129)
            path.unlink();target=Path(tmp)/'target';target.write_text('KEEP');path.symlink_to(target)
            with self.assertRaises(OSError):journal.write({'value':3})
            self.assertEqual(target.read_text(),'KEEP')

    def test_journal_size_bound_includes_the_trailing_newline(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch('cbus_toolkit.pci_selected_serial.MAX_JOURNAL_BYTES',16):
            accepted=Path(tmp)/'accepted.json'
            _Journal(accepted).write('x'*13)  # quotes + 13 bytes + newline
            self.assertEqual(len(accepted.read_bytes()),16)
            rejected=Path(tmp)/'rejected.json'
            with self.assertRaisesRegex(ValueError,'size bound'):
                _Journal(rejected).write('x'*14)
            self.assertFalse(rejected.exists())

    def test_late_final_journal_sync_is_uncertain_without_losing_after_inventory(self):
        sim=fixture()
        with sim.running() as endpoint:plan=manager(endpoint).plan(A,6)
        value=plan.as_dict();subject=manager(endpoint);clock=Clock()
        def before(evidence,deadline):
            for key in ('before','local_identity','local_options'):evidence[key]=deepcopy(value[key])
            return implementation._inventory_proof(value['before'],value['endpoint'],16,False)
        observed=types.SimpleNamespace(as_dict=lambda:deepcopy(value['before']))
        child=types.SimpleNamespace(last_observation=None)
        def inventory():child.last_observation=observed;return observed
        child.collect_inventory=inventory
        recorded=exchange();transport=types.SimpleNamespace(last_exchange=recorded,send_serial_address=lambda *args:recorded)
        with tempfile.TemporaryDirectory() as tmp:
            journal=_Journal(Path(tmp)/'journal.json');sync=journal._sync_directory;count=[]
            def delayed_sync():
                sync();count.append(True)
                if len(count)==4:clock.value+=5
            with patch.object(subject,'_before',side_effect=before),patch.object(subject,'_inventory',return_value=child), \
                    patch.object(subject,'_transport',return_value=transport),patch.object(subject,'_new_journal',return_value=journal), \
                    patch.object(journal,'_sync_directory',side_effect=delayed_sync), \
                    patch('cbus_toolkit.pci_selected_serial.time.monotonic',side_effect=clock):
                with self.assertRaisesRegex(TimeoutError,'finalization') as caught:subject.apply(plan,recovery_path=journal.path)
            evidence=caught.exception.selected_serial_evidence
            self.assertEqual(evidence['outcome'],'uncertain');self.assertEqual(evidence['after'],value['before'])
            self.assertTrue(evidence['send_attempted']);self.assertTrue(evidence['after_collection_complete'])


if __name__=='__main__':unittest.main()
