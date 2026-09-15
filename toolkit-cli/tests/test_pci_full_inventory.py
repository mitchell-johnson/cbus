"""Independent full-inventory conversations, coordinator limits and native evidence."""
from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import select
import socket
import threading
import time
import types
import unittest
from unittest.mock import patch
from uuid import uuid4

from cbus_toolkit import pci_full_inventory
from cbus_toolkit.pci_full_inventory import PCIInventoryCollector
from cbus_toolkit.pci_inventory import MMIObservation
from cbus_toolkit.pci_serials import SerialObservation, SerialReply
from tests.test_pci_inventory import FIRST, MIDDLE, LAST, FULL, ZERO_FIRST, ZERO_LAST
from tests.test_pci_serials import BARE_PCI, SERIAL_A, SERIAL_B, UNKNOWN_ZERO
from tests.test_simulator_duplicates import fixture


REQUESTS = [b'\\05FF00FAFF00g\r', b'\\4610002104g\r', b'\\46FF002104g\r', b'\\05FF00FAFF00g\r']
ERROR_LAST = b'D6FFB0' + b'00'*19 + b'C0BB\r\n'
STATE_ONE_LAST = b'D6FFB0' + b'00'*19 + b'403B\r\n'
LOCAL_AT_255 = b'86FF10008D04FFFFFF000018A664A3B1000562\r\n'


@contextmanager
def conversation(responses):
    """Each literal response requires a new connection and exactly one request."""
    listener = socket.socket()
    listener.bind(('127.0.0.1',0)); listener.listen(1); listener.settimeout(2)
    state = {'requests':[], 'closed':[], 'extra':[], 'errors':[]}

    def serve():
        try:
            for response in responses:
                with listener.accept()[0] as connection:
                    connection.settimeout(2)
                    request = b''
                    while not request.endswith(b'\r'):
                        chunk = connection.recv(512)
                        if not chunk: raise AssertionError('Disconnected before request')
                        request += chunk
                    state['requests'].append(request)
                    for chunk in response if isinstance(response,list) else [response]:
                        if isinstance(chunk,tuple):
                            delay, chunk = chunk; time.sleep(delay)
                        connection.sendall(chunk)
                    extra = b''
                    while chunk := connection.recv(512): extra += chunk
                    state['extra'].append(extra); state['closed'].append(True)
        except (BrokenPipeError,ConnectionResetError):
            state['closed'].append(True)
        except Exception as error: state['errors'].append(repr(error))

    thread = threading.Thread(target=serve,daemon=True); thread.start()
    try: yield listener.getsockname(),state
    finally:
        thread.join(3)
        pending = select.select([listener],[],[],0)[0]
        listener.close()
        if thread.is_alive(): raise AssertionError('Conversation did not complete')
        if pending: raise AssertionError('Unexpected additional connection')
        if state['errors']: raise AssertionError(state['errors'])


def collector(endpoint=('127.0.0.1',10001), **settings):
    options = dict(local_unit=16, overall_timeout=2, observation_timeout=.5,
                   confirmation_timeout=.1,response_timeout=.1,quiet_period=.025)
    options.update(settings)
    return PCIInventoryCollector(*endpoint,**options)


def successful_responses(serial=b'g.'+SERIAL_A+SERIAL_B, final=b'g.'+FULL):
    return [b'g.'+FULL,b'g.'+BARE_PCI,serial,final]


def mmi_result():
    states = [0]*256; states[16],states[255] = 1,2
    return MMIObservation(16,tuple(states),(),b'mmi',b'', '.',(),(), 'coverage_complete',.01,.5,.1,.1,7,0,True)


def serial_result(address,serial):
    reply = SerialReply(address,16,serial,True,b'',b'',.01)
    return SerialObservation(address,16,b'serial',b'','.',(reply,),(),(),'quiet',.025,.025,.5,.1,7,0,True)


class PCIFullInventoryTests(unittest.TestCase):
    def observe(self,responses=None,**settings):
        with conversation(responses or successful_responses()) as (endpoint,state):
            result = collector(endpoint,**settings).collect_inventory()
        self.assertTrue(all(state['closed'])); self.assertFalse(any(state['extra']))
        return result,state

    def test_literal_complete_duplicate_inventory_is_not_unique_or_atomic(self):
        result,state = self.observe()
        self.assertEqual(state['requests'],REQUESTS)
        self.assertEqual(len(state['closed']),4)
        self.assertTrue(result.collection_complete); self.assertTrue(result.complete)
        self.assertTrue(result.consistent); self.assertTrue(result.membership_unchanged)
        self.assertFalse(result.unique); self.assertFalse(result.healthy); self.assertTrue(result.mmi_healthy)
        self.assertEqual(result.status,'duplicate_address'); self.assertEqual(result.duplicate_addresses,(255,))
        self.assertEqual([item.serials for item in result.serial_observations],
                         [('100966.1187',),('101136.1558','101136.1559')])
        self.assertEqual(result.request_count,4); self.assertEqual(result.unattempted_addresses,())
        document = json.loads(json.dumps(result.as_dict()))
        self.assertFalse(document['atomic_snapshot']); self.assertFalse(document['authorizes_address_mutation'])
        self.assertFalse(document['physical_addresses_changed']); self.assertEqual(document['automatic_retries'],0)
        self.assertEqual(document['timing']['phases'][2]['address'],255)

    def test_unique_inventory_uses_checksum_and_preserves_fragments(self):
        responses = [[b'g',b'.',FIRST[:9],FIRST[9:],MIDDLE,LAST],
                     [b'g.',BARE_PCI[:5],BARE_PCI[5:]],
                     [b'g.',SERIAL_A[:9],SERIAL_A[9:]],b'g.'+FULL]
        result,state = self.observe(responses,command_checksum=True)
        self.assertEqual(state['requests'],[b'\\05FF00FAFF0003g\r',b'\\461000210485g\r',
                                            b'\\46FF00210496g\r',b'\\05FF00FAFF0003g\r'])
        self.assertEqual(result.status,'complete'); self.assertTrue(result.unique); self.assertTrue(result.healthy)

    def test_initial_coverage_faults_stop_before_any_serial_request(self):
        for payload in (FIRST+LAST,FIRST+FIRST+LAST,MIDDLE+FIRST+LAST,ZERO_FIRST+MIDDLE+ZERO_LAST):
            with self.subTest(payload=payload):
                result,state=self.observe([b'g.'+payload])
                self.assertEqual(state['requests'],REQUESTS[:1]); self.assertEqual(result.status,'incomplete')
                self.assertIsNone(result.final_mmi); self.assertEqual(result.serial_observations,())
                self.assertIsNone(result.membership_unchanged)

    def test_partial_final_mmi_cannot_complete_even_after_all_serials(self):
        result,state=self.observe(successful_responses(final=b'g.'+FIRST+LAST))
        self.assertEqual(state['requests'],REQUESTS)
        self.assertEqual(result.unattempted_addresses,()); self.assertFalse(result.complete)
        self.assertEqual(result.termination,'final_mmi_incomplete')
        self.assertEqual(result.final_mmi.states[88:],(None,)*168)

    def test_bookend_presence_or_state_changes_are_inconsistent_without_rescan(self):
        for ending,state_at_255 in ((ZERO_LAST,0),(STATE_ONE_LAST,1)):
            with self.subTest(state=state_at_255):
                result,state=self.observe(successful_responses(final=b'g.'+FIRST+MIDDLE+ending))
                self.assertEqual(state['requests'],REQUESTS)
                self.assertTrue(result.collection_complete); self.assertFalse(result.complete)
                self.assertEqual(result.status,'inconsistent')
                self.assertEqual(result.changed_states,({'address':255,'before':2,'after':state_at_255},))

    def test_empty_serial_window_is_inconsistent_but_final_mmi_is_still_collected(self):
        result,state=self.observe(successful_responses(serial=b'g.'))
        self.assertEqual(state['requests'],REQUESTS); self.assertTrue(result.collection_complete)
        self.assertEqual(result.missing_serial_addresses,(255,)); self.assertEqual(result.status,'inconsistent')

    def test_serial_seen_at_two_addresses_is_ambiguous(self):
        result,state=self.observe(successful_responses(serial=b'g.'+LOCAL_AT_255))
        self.assertEqual(state['requests'],REQUESTS); self.assertTrue(result.collection_complete)
        self.assertEqual(result.serial_conflicts,({'serial':'100966.1187','addresses':[16,255]},))
        self.assertEqual(result.status,'inconsistent'); self.assertFalse(result.unique)

    def test_serial_failure_stops_before_final_mmi_and_retains_partial_identity(self):
        result,state=self.observe(successful_responses(serial=b'g.'+SERIAL_A+UNKNOWN_ZERO)[:3])
        self.assertEqual(state['requests'],REQUESTS[:3]); self.assertIsNone(result.final_mmi)
        self.assertEqual(result.serial_observations[-1].serials,('101136.1558',))
        self.assertEqual(result.termination,'serial_incomplete'); self.assertFalse(result.collection_complete)

    def test_mmi_errors_are_complete_collection_with_explicit_health_flags(self):
        payload=FIRST+MIDDLE+ERROR_LAST
        result,state=self.observe([b'g.'+payload,b'g.'+BARE_PCI,b'g.'+SERIAL_A,b'g.'+payload])
        self.assertEqual(state['requests'],REQUESTS); self.assertTrue(result.complete); self.assertTrue(result.unique)
        self.assertEqual(result.status,'mmi_errors'); self.assertFalse(result.mmi_healthy); self.assertFalse(result.healthy)
        self.assertEqual(result.error_addresses,(255,))

    @contextmanager
    def scripted(self,subject,steps,*,final_clock_error=None, final_clock_after=0):
        clock={'value':0.,'calls':[],'step':0,'final_reads':0}
        def now():
            if clock['step']==len(steps) and final_clock_error:
                clock['final_reads']+=1
                if clock['final_reads']>final_clock_after: raise final_clock_error
            return clock['value']
        def factory(kind,budget):
            expected,result,duration,error=steps[clock['step']]
            self.assertEqual(kind,expected); clock['calls'].append((kind,budget))
            class Child:
                last_observation=None
                def collect(self):
                    self.last_observation=result
                    clock['value']+=duration; clock['step']+=1
                    if error: raise error
                    return result
                def collect_mmi(self): return self.collect()
                def collect_serials(self,address):
                    if result: self_address=result.address
                    else: self_address=address
                    if self_address!=address: raise AssertionError('Wrong requested address')
                    return self.collect()
            return Child()
        with patch.object(pci_full_inventory,'time',types.SimpleNamespace(monotonic=now)), \
                patch.object(subject,'_mmi_collector',side_effect=lambda budget:factory('mmi',budget)), \
                patch.object(subject,'_serial_collector',side_effect=lambda budget:factory('serial',budget)):
            yield clock

    def standard_steps(self):
        return [('mmi',mmi_result(),.01,None),('serial',serial_result(16,'100966.1187'),.03,None),
                ('serial',serial_result(255,'101136.1558'),.03,None),('mmi',mmi_result(),.01,None)]

    def test_overall_budget_stops_before_socket_during_child_and_before_final_mmi(self):
        for budget,steps,count in ((.05,self.standard_steps(),0),
                                   (.2,[('mmi',mmi_result(),.21,None)],1),
                                   (.15,self.standard_steps(),3)):
            with self.subTest(budget=budget):
                subject=collector(overall_timeout=budget)
                with self.scripted(subject,steps) as clock:result=subject.collect_inventory()
                self.assertEqual(len(clock['calls']),count); self.assertEqual(result.termination,'overall_timeout')
                self.assertFalse(result.complete); self.assertIsNone(result.final_mmi)
                if count==1:self.assertEqual(result.unattempted_addresses,(16,255))
                if count==3:
                    self.assertEqual(result.unattempted_addresses,())
                    self.assertEqual(result.serial_observations[-1].quiet_period,.025)

    def test_successful_child_returning_after_deadline_cannot_complete(self):
        subject=collector(overall_timeout=.25)
        steps=self.standard_steps();steps[-1]=('mmi',mmi_result(),.3,None)
        with self.scripted(subject,steps) as clock:result=subject.collect_inventory()
        self.assertEqual(len(clock['calls']),4); self.assertFalse(result.complete)
        self.assertTrue(result.membership_unchanged); self.assertEqual(result.termination,'overall_timeout')

    def test_child_factory_delay_requires_fresh_admission_before_any_child_io(self):
        for delay in (.11,.3):
            with self.subTest(delay=delay):
                subject=collector(overall_timeout=.2);clock={'value':0.}
                child=types.SimpleNamespace(last_observation=None,collect_mmi=lambda:self.fail('Child ran after budget admission failed'))
                def factory(budget):
                    clock['value']+=delay
                    return child
                with patch.object(pci_full_inventory,'time',types.SimpleNamespace(monotonic=lambda:clock['value'])), \
                        patch.object(subject,'_mmi_collector',side_effect=factory) as create:
                    result=subject.collect_inventory()
                create.assert_called_once()
                self.assertEqual(result.request_count,0);self.assertEqual(result.phases,())
                self.assertEqual(result.termination,'overall_timeout');self.assertIsNone(result.initial_mmi)

    def test_interruption_keeps_partial_child_and_stops_without_replay(self):
        subject=collector();original=KeyboardInterrupt('serial interrupted')
        partial=replace(serial_result(16,'100966.1187'),termination='interrupted',errors=('cancelled',))
        steps=[('mmi',mmi_result(),.01,None),('serial',partial,.02,original)]
        with self.scripted(subject,steps) as clock:
            with self.assertRaises(KeyboardInterrupt) as caught:subject.collect_inventory()
        self.assertIs(caught.exception,original);result=subject.last_observation
        self.assertEqual(result.unattempted_addresses,(255,));self.assertEqual(result.serial_observations,(partial,))
        self.assertEqual(original.pci_inventory_observation,result.as_dict());self.assertEqual(len(clock['calls']),2)
        self.assertIsNone(result.final_mmi)
        with self.assertRaises(RuntimeError):subject.collect_inventory()

    def test_clock_interruption_after_child_keeps_its_record_and_first_exception(self):
        for prior in (None,SystemExit('child interrupted')):
            with self.subTest(prior=prior):
                subject=collector();clock_error=KeyboardInterrupt('clock interrupted')
                steps=[('mmi',mmi_result(),.01,prior)]
                with self.scripted(subject,steps,final_clock_error=clock_error) as clock:
                    with self.assertRaises(type(prior or clock_error)) as caught:subject.collect_inventory()
                self.assertIs(caught.exception,prior or clock_error)
                self.assertIsNotNone(subject.last_observation.initial_mmi)
                self.assertEqual(subject.last_observation.unattempted_addresses,(16,255))
                self.assertEqual(len(clock['calls']),1)
                self.assertEqual((prior or clock_error).pci_inventory_observation,subject.last_observation.as_dict())

    def test_final_coordinator_clock_interruption_keeps_all_completed_observations(self):
        subject=collector();original=KeyboardInterrupt('final coordinator clock interrupted')
        with self.scripted(subject,self.standard_steps(),final_clock_error=original,final_clock_after=1) as clock:
            with self.assertRaises(KeyboardInterrupt) as caught:subject.collect_inventory()
        self.assertIs(caught.exception,original);result=subject.last_observation
        self.assertEqual(result.request_count,4);self.assertTrue(result.final_mmi.complete)
        self.assertEqual(result.membership_unchanged,True);self.assertEqual(result.termination,'interrupted')
        self.assertFalse(result.complete);self.assertEqual(result.elapsed,clock['value'])
        self.assertEqual(original.pci_inventory_observation,result.as_dict())

    def test_real_child_interruption_retains_known_identity_and_closes_before_coordinator_returns(self):
        from cbus_toolkit.pci_inventory import PCIMMICollector
        from cbus_toolkit.pci_serials import PCISerialCollector
        from tests.test_pci_interruption import Clock,Stream
        subject=collector();original=KeyboardInterrupt('physical read cancelled')
        initial_stream=Stream(Clock(),[b'g.'+FULL])
        serial_stream=Stream(Clock(),[b'g.'+BARE_PCI,original])
        with patch.object(PCIMMICollector,'_make_socket',return_value=initial_stream) as mmi_socket, \
                patch.object(PCISerialCollector,'_make_socket',return_value=serial_stream) as serial_socket:
            with self.assertRaises(KeyboardInterrupt) as caught:subject.collect_inventory()
        self.assertIs(caught.exception,original);result=subject.last_observation
        mmi_socket.assert_called_once();serial_socket.assert_called_once()
        self.assertEqual(result.serial_observations[0].serials,('100966.1187',))
        self.assertEqual(result.unattempted_addresses,(255,));self.assertIsNone(result.final_mmi)
        self.assertTrue(result.connection_closed)
        self.assertEqual(initial_stream.calls[-1],('close',));self.assertEqual(serial_stream.calls[-1],('close',))
        self.assertEqual(original.pci_serial_observation,result.serial_observations[0].as_dict())
        self.assertEqual(original.pci_inventory_observation,result.as_dict())

    def test_validation_and_oneshot_happen_without_connection(self):
        with patch('cbus_toolkit.pci_inventory.PCIMMICollector._make_socket') as connect:
            for options in ({'overall_timeout':True},{'overall_timeout':3601},{'overall_timeout':float('nan')},
                            {'observation_timeout':1},{'max_serial_frames':0},{'max_mmi_frames':0},
                            {'quiet_period':0},{'max_bytes':0},{'command_checksum':1},{'local_unit':False}):
                with self.subTest(options=options),self.assertRaises(ValueError):
                    PCIInventoryCollector('127.0.0.1',**(dict(local_unit=16)|options))
            with self.assertRaises(ValueError):PCIInventoryCollector('localhost',local_unit=16)
            connect.assert_not_called()
        subject=collector(overall_timeout=.001)
        self.assertEqual(subject.collect_inventory().request_count,0)
        with self.assertRaises(RuntimeError):subject.collect_inventory()
        self.assertFalse(any(hasattr(subject,name) for name in ('write','readdress','send_raw','command')))


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'),'Set CBUS_CGATE_TEST_HOST for full native inventory comparison')
class NativePCIFullInventoryTests(unittest.TestCase):
    def test_full_duplicate_inventory_agrees_with_native_presence_and_serial_seeker(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase,NativeProjects
        from cbus_toolkit.networks import NativeNetworks
        from cbus_toolkit.programming import xml_text

        sim=fixture(response_delay=.01);before=sim.snapshot()
        project='FI'+uuid4().hex[:6].upper();network='//'+project+'/254'
        report={'passed':False,'scope':'Non-atomic direct full MMI/serial inventory versus native PINGU/CHECKUNIT in an explicit duplicate fixture'}
        try:
            with sim.running('0.0.0.0',0) as (_,port):
                result=PCIInventoryCollector('127.0.0.1',port,local_unit=16).collect_inventory()
                self.assertTrue(result.complete);self.assertEqual(result.status,'duplicate_address')
                self.assertEqual(result.planned_addresses,(16,255))
                self.assertEqual([item.serials for item in result.serial_observations],
                                 [('100966.1187',),('101136.1558','101136.1559')])
                self.assertGreaterEqual(result.elapsed,4.)
                direct=list(sim.wire_log)
                self.assertEqual([bytes.fromhex(row['hex']) for row in direct if row['direction']=='rx'],REQUESTS)
                with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=45) as client:
                    projects,db,nets=NativeProjects(client),NativeDatabase(client),NativeNetworks(client);created=False
                    try:
                        projects.operation('new',project);created=True
                        db.create_network(project,254,'Direct_Inventory','Cni',
                            os.environ.get('CBUS_CGATE_SIMULATOR_HOST','host.docker.internal')+':'+str(port))
                        projects.operation('save',project);xml_before=xml_text(db.get(network,xml=True))
                        nets.open(network);nets.wait_ready(network,timeout=30)
                        client.command('SET '+network+' Retries 0')
                        retries=client.command('GET '+network+' Retries')
                        self.assertEqual(retries.lines,('300 '+network+': Retries=0',))
                        start=len(sim.wire_log);presence=client.command('NET PINGU '+network)
                        check=client.command('NET CHECKUNIT '+network+' 255')
                        local=client.command('GET '+network+'/p/16 SerialNumber')
                        self.assertEqual(presence.lines,('302-Units=16, 255','200 OK.'))
                        self.assertEqual(check.lines,('120 Duplicate units detected at address: 255',))
                        self.assertEqual(local.lines,('300 '+network+'/p/16: SerialNumber=100966.1187',))
                        native=list(sim.wire_log[start:])
                        self.assertTrue(any(SERIAL_A in bytes.fromhex(row['hex']) and SERIAL_B in bytes.fromhex(row['hex'])
                                            for row in native if row['direction']=='tx'))
                        self.assertEqual(sim.snapshot(),before);self.assertEqual(xml_text(db.get(network,xml=True)),xml_before)
                        self.assertFalse([row for row in sim.wire_log if row.get('reason')])
                        report.update(passed=True,observation=result.as_dict(),direct_wire=direct,native_wire=native,
                                      native_presence=list(presence.lines),native_check=list(check.lines),native_local_serial=list(local.lines),
                                      post_ready_retries=list(retries.lines),database_unchanged=True,fixture_unchanged=True)
                    finally:
                        report['cleanup_errors']=[]
                        if created:
                            for command in ('NET CLOSE '+network,'PROJECT CLOSE '+project,'PROJECT DELETE '+project):
                                try:client.command(command)
                                except Exception as error:report['cleanup_errors'].append(str(error))
                        if report['passed']:self.assertEqual(report['cleanup_errors'],[])
        finally:
            if output:=os.environ.get('CBUS_PCI_FULL_INVENTORY_REPORT'):
                Path(output).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':unittest.main()
