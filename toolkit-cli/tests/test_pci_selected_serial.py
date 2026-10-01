"""Independent literal reads, serial-keyed fixture state and durable journal faults."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from cbus_toolkit import pci_selected_serial as implementation
from cbus_toolkit.commissioning_lease import EndpointLease, EndpointLeaseBusy
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
# This helper crosses real TCP sockets and a separately scheduled fixture
# thread. Give every response/quiet phase enough scheduler headroom while
# remaining far below the production native windows. Deterministic deadline
# cases override individual values or the monotonic clock explicitly.
SETTINGS=dict(local_unit=16,expected_local_serial=LOCAL,overall_timeout=5.,observation_timeout=.5,
              confirmation_timeout=.2,mmi_response_timeout=.2,quiet_period=.2,
              options_response_timeout=.2,address_response_timeout=.2)
OPTIONS=b'g.82420537\r\n'
LOCAL_REQUEST=b'\\4610002104g\r'
OPTIONS_REQUEST=b'\\4610001A4201g\r'
MMI_REQUEST=b'\\05FF00FAFF00g\r'


def manager(endpoint,**options): return SelectedSerialCoordinator(*endpoint,**(SETTINGS|options))


def failure_diagnostic(evidence):
    """Keep failed live exchanges useful without disclosing journal/endpoint paths."""
    value=evidence or {};exchange=value.get('exchange') or {};receipt=exchange.get('receipt') or {}
    return json.dumps({'outcome':value.get('outcome'),
        'errors':[{'type':item.get('type')} for item in value.get('errors',[])],
        'exchange':{'termination':exchange.get('termination'),
            'capture_complete':exchange.get('capture_complete'),
            'bytes_received':exchange.get('bytes_received'),
            'receipt_status':receipt.get('status'),'pending_hex':receipt.get('pending_hex')}},sort_keys=True)


def after_responses():
    full=FIRST_MOVED+MIDDLE+LAST
    return [b'g.'+full,b'g.'+SERIAL_A_AT6,b'g.'+BARE_PCI,b'g.'+SERIAL_B,b'g.'+full]


def exchange(*, errors=(), capture=True, received=RECEIPT_A, attempted=True):
    receipt=decode_serial_address_receipt(received,serial=A,destination=6,local_unit=16)
    return SerialAddressExchange(CO_A,received,attempted,attempted,len(received),receipt,
        'response_window_elapsed' if capture else 'send_error',capture,.02,.02,.02,.5,4096,True,tuple(errors))


class SelectedSerialTests(unittest.TestCase):
    def test_cooperating_endpoint_contention_refuses_before_io_or_journal(self):
        initial=successful_responses()+[b'g.'+BARE_PCI,OPTIONS]
        with tempfile.TemporaryDirectory() as tmp,conversation(initial) as (endpoint,state):
            subject=manager(endpoint);plan=subject.plan(A,6)
            path=Path(tmp)/'journal.json'
            baseline=list(state['requests'])
            with EndpointLease(*endpoint):
                with self.assertRaises(EndpointLeaseBusy) as caught:
                    subject.apply(plan,recovery_path=path)
            self.assertEqual(state['requests'],baseline)
            self.assertFalse(path.exists())
            self.assertFalse(subject._apply_used)
            self.assertEqual(caught.exception.selected_serial_evidence['outcome'],'preconditions_failed')
            self.assertFalse(caught.exception.selected_serial_evidence['transport_invoked'])

    def test_cooperating_endpoint_contention_refuses_verify_before_io(self):
        initial=successful_responses()+[b'g.'+BARE_PCI,OPTIONS]
        with tempfile.TemporaryDirectory() as tmp,conversation(initial) as (endpoint,state):
            subject=manager(endpoint);plan=subject.plan(A,6)
            baseline=list(state['requests'])
            with EndpointLease(*endpoint):
                with self.assertRaises(EndpointLeaseBusy) as caught:
                    subject.verify(plan)
            self.assertEqual(state['requests'],baseline)
            self.assertEqual(caught.exception.selected_serial_evidence['outcome'],'uncertain')
            self.assertFalse(caught.exception.selected_serial_evidence['after_collection_complete'])

    def test_canonical_bytes_match_rust_fingerprint_encoder(self):
        # Golden vector shared with cbus-transport's
        # canonical_fingerprint_bytes_match_python_vector: any drift in either
        # encoder splits the cross-implementation attempt-marker namespace.
        raw=(r'{"z":[1.0,-0.0,30.0,0.1,1e-5,1e-6,1.5e-7,1e15,1000000000000000.5,1e16,1.5e20,-2.5,5e-324,'
             r'1.7976931348623157e308,123456.789,-1e-300],"big":123456789012345678901234567890,'
             r'"negbig":-123456789012345678901234567890,"u64":18446744073709551615,"i64":-9223372036854775808,'
             r'"text":"é😀\u0000\u001f\u007f\n\t\b\f\r\"\\\/","endpoint":{"port":10001,'
             r'"host":"::FFFF:10.0.0.1"},"v6":{"host":"2001:DB8:0:0:1:0:0:1","port":1},'
             r'"named":{"host":"localhost","port":1},"nohost":{"host":"127.000.0.1","port":1},'
             r'"noport":{"host":"::FFFF:10.0.0.1"},"flags":[true,false,null]}')
        expected=('{"big":1e+300,"endpoint":{"host":"::ffff:10.0.0.1","port":10001},'
            '"flags":[true,false,null],"i64":-9223372036854775808,'
            '"named":{"host":"localhost","port":1},"negbig":-1e+300,'
            '"nohost":{"host":"127.000.0.1","port":1},"noport":{"host":"::FFFF:10.0.0.1"},'
            '"text":"é\U0001f600\\u0000\\u001f\x7f\\n\\t\\b\\f\\r\\"\\\\/",'
            '"u64":18446744073709551615,"v6":{"host":"2001:db8::1:0:0:1","port":1},'
            '"z":[1,0,30,0.1,0.00001,1e-6,1.5e-7,1000000000000000,1000000000000000.5,'
            '10000000000000000,1.5e+20,-2.5,5e-324,1.7976931348623157e+308,123456.789,-1e-300]}')
        self.assertEqual(implementation._canonical_plan(json.loads(raw)),expected.encode('utf-8'))

    def test_attempt_marker_filename_matches_rust_vector(self):
        # The committed vector plan resolves to the filename the Rust suite
        # pins independently; both sides refuse one canonical plan.
        rows=(Path(__file__).resolve().parents[2]/'rust'/'testdata'/'vectors'
              /'selected_serial_plan.jsonl').read_text().splitlines()
        document=json.loads(rows[0])['document']
        with tempfile.TemporaryDirectory() as tmp:
            marker=implementation.attempt_identity_path(document,Path(tmp)/'probe.json')
        self.assertEqual(marker.name,'.cbus-selected-serial-attempt-sha256-'
            '55af93616aaeacb668e4b52f284a90cba1ccd7792fc77491caf22c44942b98cf.json')

    def test_shared_plan_vectors_including_routed_schema(self):
        # Rows are shared with cbus-transport's selected_serial_plan vectors:
        # accept/reject verdicts, routed reason codes and pinned routed
        # attempt IDs must agree; the direct row keeps its original marker.
        rows=[json.loads(line) for line in (Path(__file__).resolve().parents[2]/'rust'/'testdata'/'vectors'
              /'selected_serial_plan.jsonl').read_text().splitlines() if line.strip()]
        route_reasons={'invalid_route','route_binding','route_proof'}
        self.assertEqual(len(rows),40)
        with tempfile.TemporaryDirectory() as tmp:
            for row in rows:
                if row['kind'] not in ('plan','raw'): continue
                with self.subTest(row=row['id']):
                    if row['kind']=='raw':
                        path=Path(tmp)/'raw.json';path.write_text(row['raw'])
                        with self.assertRaises(ValueError):SelectedSerialPlan.load(path)
                        continue
                    if row['expect']=='accept':
                        document=SelectedSerialPlan.from_dict(row['document']).as_dict()
                        self.assertEqual(document.get('route'),row.get('route'))
                        self.assertEqual(document.get('project_sha256'),row.get('project_sha256'))
                        if 'attempt_id' in row:
                            self.assertEqual('sha256:'+implementation._canonical_fingerprint(document),row['attempt_id'])
                        continue
                    with self.assertRaises(ValueError) as caught:SelectedSerialPlan.from_dict(row['document'])
                    if row['reason'] in route_reasons:
                        self.assertEqual(getattr(caught.exception,'reason',None),row['reason'])
                    else:
                        self.assertNotIsInstance(caught.exception,implementation.SelectedSerialPlanError)
            self.assertEqual(implementation.attempt_identity_path(rows[0]['document'],Path(tmp)/'probe.json').name,
                '.cbus-selected-serial-attempt-sha256-55af93616aaeacb668e4b52f284a90cba1ccd7792fc77491caf22c44942b98cf.json')
        self.assertNotIn('route',SelectedSerialPlan.from_dict(rows[0]['document']).as_dict())

    def test_invalid_routed_plan_fields_refuse_before_io(self):
        # Routed observation, binding and execution are covered by
        # test_pci_selected_serial_routed over scripted bridge peers.
        sha='ab'*32
        with conversation([]) as (endpoint,state):
            subject=manager(endpoint)
            for route,binding,reason in (([],sha,'invalid_route'),([1],None,'route_binding'),
                                         (None,sha,'route_binding'),([16],sha,'route_proof')):
                with self.subTest(route=route,binding=binding),self.assertRaises(implementation.SelectedSerialPlanError) as caught:
                    subject.plan(A,6,route=route,project_sha256=binding)
                self.assertEqual(caught.exception.reason,reason)
        self.assertEqual(state['requests'],[])

    def test_attempt_marker_refuses_repeat_across_journals_before_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.json'
            sim=fixture(state_path=path,faults={A:SerialAddressFault(move=False)})
            with sim.running() as endpoint:
                subject=manager(endpoint);plan=subject.plan(A,6)
                journal_first=Path(tmp)/'first.json';journal_second=Path(tmp)/'second.json'
                marker=implementation.attempt_identity_path(plan.as_dict(),journal_first)
                self.assertEqual(marker.parent,Path(tmp).resolve())
                result=subject.apply(plan,recovery_path=journal_first)
                self.assertEqual(result.outcome,'observed_unchanged')
                self.assertEqual(result.as_dict()['attempt_identity'],str(marker))
                record=json.loads(marker.read_text())
                self.assertEqual(record,{'format':'cbus-selected-serial-attempt-v1','operation':'apply',
                    'attempt_id':'sha256:'+implementation._canonical_fingerprint(plan.as_dict()),
                    'scope':'resolved_journal_directory','journal':str(journal_first.parent.resolve()/'first.json'),
                    'plan':plan.as_dict(),'send_may_have_occurred':True,'read_only_recovery_only':True})
                # A fresh coordinator (a second process) with a different
                # journal in the same directory is refused before PCI I/O.
                retry=manager(endpoint)
                with self.assertRaises(SelectedSerialUncertain) as caught:
                    retry.apply(plan,recovery_path=journal_second)
                self.assertIn('read-only recovery only',str(caught.exception))
                self.assertEqual(caught.exception.selected_serial_evidence['before'],None)
                self.assertFalse(journal_second.exists())
                self.assertEqual(len(sim.co_operations),1)
                # The marker alone resumes read-only recovery; a forged ID fails.
                journal_first.unlink()
                self.assertEqual(SelectedSerialCoordinator.load_recovery(marker).as_dict(),plan.as_dict())
                forged=Path(tmp)/'forged.json'
                forged.write_text(json.dumps(record|{'attempt_id':'sha256:'+'0'*64}))
                with self.assertRaisesRegex(ValueError,'does not match'):
                    SelectedSerialCoordinator.load_recovery(forged)
                forged.write_text(json.dumps(record|{'send_may_have_occurred':False}))
                with self.assertRaisesRegex(ValueError,'ambiguous'):
                    SelectedSerialCoordinator.load_recovery(forged)

    def test_attempt_store_shares_markers_across_journal_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);store=tmp/'store';store.mkdir()
            sim=fixture(state_path=tmp/'fixture.json',faults={A:SerialAddressFault(move=False)})
            with sim.running() as endpoint:
                subject=manager(endpoint);plan=subject.plan(A,6)
                dir_a=tmp/'a';dir_a.mkdir();dir_b=tmp/'b';dir_b.mkdir()
                journal_first=dir_a/'first.json';journal_second=dir_b/'second.json'
                marker=implementation.attempt_identity_path(plan.as_dict(),journal_first,store)
                self.assertEqual(marker.parent,store.resolve())
                self.assertEqual(marker,implementation.attempt_identity_path(plan.as_dict(),journal_second,store))
                result=subject.apply(plan,recovery_path=journal_first,attempt_store=store)
                self.assertEqual(result.outcome,'observed_unchanged')
                self.assertEqual(result.as_dict()['attempt_identity'],str(marker))
                self.assertEqual(json.loads(marker.read_text())['scope'],'operator_selected_attempt_store')
                retry=manager(endpoint)
                with self.assertRaises(SelectedSerialUncertain):
                    retry.apply(plan,recovery_path=journal_second,attempt_store=store)
                self.assertFalse(journal_second.exists())
                self.assertEqual(len(sim.co_operations),1)

    def test_missing_attempt_store_refuses_before_io_or_journal(self):
        with tempfile.TemporaryDirectory() as tmp,conversation(successful_responses()+[b'g.'+BARE_PCI,OPTIONS]) as (endpoint,state):
            subject=manager(endpoint);plan=subject.plan(A,6)
            baseline=list(state['requests'])
            with self.assertRaisesRegex(ValueError,'shared store'):
                subject.apply(plan,recovery_path=Path(tmp)/'journal.json',attempt_store=Path(tmp)/'missing')
            self.assertEqual(state['requests'],baseline)
            self.assertFalse((Path(tmp)/'journal.json').exists())
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_rust_vector_plan_applies_live_cross_implementation(self):
        # Keep the shared vector unchanged; its exact settings and canonical
        # marker are covered above. Adapt only this copied execution plan to
        # the fixture's real TCP/scheduler/persistence headroom, then exercise
        # validation, lease, marker, guards, send and independent observation.
        rows=(Path(__file__).resolve().parents[2]/'rust'/'testdata'/'vectors'
              /'selected_serial_plan.jsonl').read_text().splitlines()
        with tempfile.TemporaryDirectory() as tmp:
            sim=fixture(state_path=Path(tmp)/'fixture.json')
            with sim.running() as endpoint:
                document=json.loads(rows[0])['document']
                document['endpoint']={'host':endpoint[0],'port':endpoint[1]}
                document['before']['endpoint']={'host':endpoint[0],'port':endpoint[1]}
                document['settings'].update({key:value for key,value in SETTINGS.items()
                    if key not in ('local_unit','expected_local_serial')})
                plan=SelectedSerialPlan.from_dict(document)
                subject=SelectedSerialCoordinator(endpoint[0],endpoint[1],local_unit=document['local_unit'],
                    expected_local_serial=document['expected_local_serial'],**document['settings'])
                verified=subject.verify(plan)
                self.assertEqual(verified.outcome,'observed_unchanged',failure_diagnostic(verified.as_dict()))
                try:result=subject.apply(plan,recovery_path=Path(tmp)/'journal.json')
                except SelectedSerialUncertain as error:
                    self.fail(failure_diagnostic(error.selected_serial_evidence))
                self.assertEqual(result.outcome,'observed_expected_change',failure_diagnostic(result.as_dict()))
                self.assertEqual(sim.nodes[A].address,6);self.assertEqual(sim.nodes[B].address,255)
                self.assertEqual(len(sim.co_operations),1)
                self.assertEqual(Path(result.as_dict()['attempt_identity']).name,
                    implementation.attempt_identity_path(document,Path(tmp)/'journal.json').name)

    def test_partial_receipt_preserves_durable_move_journal_without_followup_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path=Path(tmp)/'fixture.json';journal=Path(tmp)/'journal.json'
            sim=fixture(state_path=state_path);native_command=sim._command

            def partial_receipt(line,context):
                response,reason=native_command(line,context)
                # Persist the actual move, then expose a bounded partial frame.
                # No scheduler race is needed to exercise the uncertainty fence.
                return (response[:8],reason) if line==CO_A.rstrip(b'\r') else (response,reason)

            sim._command=partial_receipt
            with sim.running() as endpoint:
                subject=manager(endpoint);plan=subject.plan(A,6)
                with self.assertRaises(SelectedSerialUncertain) as caught:
                    subject.apply(plan,recovery_path=journal)
                evidence=caught.exception.selected_serial_evidence
                self.assertEqual(evidence['outcome'],'uncertain')
                self.assertEqual(evidence['exchange']['received_hex'],RECEIPT_A[:8].hex())
                self.assertEqual(evidence['exchange']['receipt']['pending_hex'],b'860610'.hex())
                self.assertIsNone(evidence['after']);self.assertFalse(evidence['after_collection_complete'])
                self.assertEqual(len(sim.co_operations),1)
                requests=[row['hex'] for row in sim.wire_log if row['direction']=='rx']
                self.assertEqual(requests.count(CO_A.hex()),1);self.assertEqual(requests[-1],CO_A.hex())
                self.assertTrue(Path(evidence['attempt_identity']).exists())
                saved=json.loads(journal.read_text())
                self.assertEqual(saved['outcome'],'uncertain');self.assertEqual(saved['exchange'],evidence['exchange'])
            restarted=SerialAddressFixture.from_state(state_path)
            self.assertEqual(restarted.nodes[A].address,6);self.assertEqual(restarted.nodes[B].address,255)

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
                if label == 'move_and_reply':
                    # A successful fixture move durably persists before its
                    # confirmation and receipt can be sent. Model modest
                    # scheduler/filesystem latency so this real-socket test
                    # cannot silently depend on a 20 ms response turnaround.
                    native_co = sim._co

                    def delayed_co(payload):
                        response = native_co(payload)
                        time.sleep(.03)
                        return response

                    sim._co = delayed_co
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
            # The full wheel suite loads the host while this real TCP fixture
            # is scheduled. Keep enough time to observe the whole 07 reply,
            # so the assertion checks the value rejection rather than a
            # scheduler-dependent incomplete capture.
            with self.assertRaisesRegex(ValueError,'05'):
                manager(endpoint,overall_timeout=8.,observation_timeout=3.,options_response_timeout=1.).plan(A,6)
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
