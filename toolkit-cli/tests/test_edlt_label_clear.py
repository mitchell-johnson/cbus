"""Clear request identity guards and honest native-acceptance outcomes."""
from dataclasses import replace
import unittest

from cbus_toolkit.cgate import CGateError
from cbus_toolkit.edlt_label_clear import EdltDynamicLabelClear, EdltLabelClearPlan, EdltLabelClearUncertain
from tests.test_physical_addressing import PhysicalClient, NET, reply


class ClearClient(PhysicalClient):
    def __init__(self):
        super().__init__();self.clear_result=reply('200 OK.');self.clear_exception=None
    def command(self, command):
        if command.startswith('LABEL '):
            self.commands.append(command)
            if self.clear_exception is not None:
                self.connected=False;raise self.clear_exception
            return self.clear_result
        return super().command(command)


class LabelClearTests(unittest.TestCase):
    def setUp(self):
        self.client=ClearClient();self.manager=EdltDynamicLabelClear(self.client);self.source=NET+'/p/5'
    def plan(self):return self.manager.plan(self.source,expected_serial='101183.1666')
    def test_plan_and_request_refresh_identity_and_coverage_without_claiming_erasure(self):
        plan=self.plan();self.assertFalse(any(c.startswith(('SET ','LABEL ')) for c in self.client.commands))
        result=self.manager.request(plan)
        self.assertEqual(result['outcome'],'native_accepted');self.assertTrue(result['native_accepted'])
        self.assertFalse(result['labels_cleared_verified']);self.assertFalse(result['label_persistence_verified'])
        self.assertFalse(result['strict_receipt_correlation_verified']);self.assertFalse(result['database_updated'])
        self.assertEqual(result['automatic_retries'],0)
        self.assertEqual(self.client.commands[-2:],[f'NET PINGU {NET}',f'LABEL CLEAREDLT {self.source}'])
        self.assertEqual(sum(c.startswith('LABEL ') for c in self.client.commands),1)
        self.assertEqual(sum(c.startswith('NET SYNC ') for c in self.client.commands),2)
        self.assertEqual(result['pre_request_coverage']['addresses'],[4,5,16])
    def test_invalid_paths_unknown_serial_wrong_profile_and_runtime_stop_before_request(self):
        for source in (None,True,'/db'+self.source,NET+'/p/*',NET+'/p/0',NET+'/p/255',NET+'/p/05',NET+'/p/5 extra'):
            with self.subTest(source=source),self.assertRaises(ValueError):self.manager.plan(source,expected_serial='101183.1666')
        self.assertFalse(self.client.commands)
        for serial in ('bad','0.0','1048575.4095','111.222'):
            with self.subTest(serial=serial),self.assertRaises(ValueError):self.manager.plan(self.source,expected_serial=serial)
        for field,value in (('Retries','2'),('SyncState','busy'),('AutoUnravel','yes'),('AutoUpdate','yes'),('InterfaceState','closed')):
            client=ClearClient();client.network[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):EdltDynamicLabelClear(client).plan(self.source,expected_serial='101183.1666')
            self.assertFalse(any(c.startswith(('NET SYNC ','LABEL ')) for c in client.commands))
        for field,value in (('Type','KEYGL4'),('Version','5.4.00'),('State','sync')):
            client=ClearClient();client.units[5][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):EdltDynamicLabelClear(client).plan(self.source,expected_serial='101183.1666')
            self.assertFalse(any(c.startswith('LABEL ') for c in client.commands))
    def test_forged_stale_and_final_coverage_failure_do_not_attempt_clear(self):
        plan=self.plan();count=len(self.client.commands)
        for forged in (replace(plan,source=NET+'/p/*'),replace(plan,serial='0.0'),replace(plan,firmware='bad'),
                       replace(plan,inventory=((True,'KEYGL5','5.5.00','101183.1666','ok'),))):
            with self.assertRaises(ValueError):self.manager.request(forged)
        self.assertEqual(len(self.client.commands),count)
        self.client.units[5]['SerialNumber']='123.456'
        with self.assertRaises(ValueError):self.manager.request(plan)
        self.client.units[5]['SerialNumber']='101183.1666'
        self.client.pingu_fault_at=self.client.pingu_calls+2;self.client.pingu_reply=reply('302-Units=4, 16','200 OK.')
        with self.assertRaises(ValueError):self.manager.request(plan)
        self.assertFalse(any(c.startswith('LABEL ') for c in self.client.commands))
    def test_complete_native_rejection_has_no_assertion_of_absent_effects(self):
        plan=self.plan();response=reply('408 Operation failed: '+self.source+' (Control failed)')
        self.client.clear_exception=CGateError(response)
        result=self.manager.request(plan)
        self.assertEqual(result['outcome'],'native_rejected');self.assertTrue(result['device_side_effect_possible'])
        self.assertFalse(result['labels_cleared_verified']);self.assertEqual(self.client.commands[-1],'LABEL CLEAREDLT '+self.source)
    def test_noncanonical_plan_shapes_and_duplicate_identities_fail_before_io(self):
        class DerivedPlan(EdltLabelClearPlan):pass
        class Text(str):pass
        plan=self.plan();count=len(self.client.commands)
        duplicate_serial=plan.inventory[:1]+((5,'KEYGL5','5.5.00',plan.inventory[0][3],'ok'),)+plan.inventory[2:]
        changes=(
            DerivedPlan(**plan.__dict__), replace(plan,serial=Text(plan.serial)),
            replace(plan,unit_type=Text(plan.unit_type)),replace(plan,firmware=Text(plan.firmware)),
            replace(plan,source=Text(plan.source)), replace(plan,inventory=list(plan.inventory)),
            replace(plan,inventory=plan.inventory+(plan.inventory[0],)),
            replace(plan,inventory=tuple(reversed(plan.inventory))),
            replace(plan,inventory=duplicate_serial), replace(plan,inventory=(plan.inventory[0],)),
            replace(plan,runtime=plan.runtime+(plan.runtime[0],)),
            replace(plan,runtime=tuple(reversed(plan.runtime))),
            replace(plan,runtime=tuple(r for r in plan.runtime if r[0]!='Retries')),
            replace(plan,runtime=tuple(sorted(plan.runtime+(('Extra','yes'),)))),
            replace(plan,runtime=tuple((key,'2' if key=='Retries' else value) for key,value in plan.runtime)),
            replace(plan,database_hash='A'*64))
        for forged in changes:
            with self.subTest(forged=forged),self.assertRaises(ValueError):self.manager.request(forged)
        self.assertEqual(len(self.client.commands),count)
    def test_clear_specific_guard_messages_and_post_reply_interruption_evidence(self):
        self.client.network['Retries']='2'
        with self.assertRaisesRegex(ValueError,'eDLT label clear requires Retries=0'):
            self.plan()
        self.client.network['Retries']='0';plan=self.plan();first=KeyboardInterrupt('reply access')
        class InterruptedReply:
            @property
            def lines(self):raise first
        self.client.clear_result=InterruptedReply()
        with self.assertRaises(KeyboardInterrupt) as caught:self.manager.request(plan)
        self.assertIs(caught.exception,first)
        self.assertTrue(first.edlt_label_clear_evidence['request_attempted'])
        self.assertEqual(self.client.commands[-1],'LABEL CLEAREDLT '+self.source)
        self.assertEqual(sum(c.startswith('LABEL ') for c in self.client.commands),1)
    def test_secondary_message_export_interruption_keeps_original_failure(self):
        class FirstInterrupt(KeyboardInterrupt):
            def __str__(self):raise SystemExit('secondary')
        first=FirstInterrupt();plan=self.plan();self.client.clear_exception=first
        with self.assertRaises(FirstInterrupt) as caught:self.manager.request(plan)
        self.assertIs(caught.exception,first)
        self.assertEqual(first.edlt_label_clear_evidence['cause_export_error_type'],'SystemExit')
        self.assertEqual(self.client.commands[-1],'LABEL CLEAREDLT '+self.source)
    def test_uncertain_wrapper_retains_native_transport_cleanup_evidence(self):
        first=RuntimeError('command failed');cleanup=(KeyboardInterrupt('secondary close'),)
        first.cgate_cleanup_errors=cleanup;plan=self.plan();self.client.clear_exception=first
        with self.assertRaises(EdltLabelClearUncertain) as caught:self.manager.request(plan)
        self.assertIs(caught.exception.__cause__,first)
        self.assertIs(caught.exception.cgate_cleanup_errors,cleanup)
        self.assertEqual(caught.exception.details['cause'],'command failed')
        self.assertEqual(self.client.commands[-1],'LABEL CLEAREDLT '+self.source)
    def test_lost_unexpected_and_interrupted_response_never_replay_or_query_after_send(self):
        for failure in (ConnectionError('lost'),KeyboardInterrupt('first'),SystemExit(7)):
            client=ClearClient();manager=EdltDynamicLabelClear(client);plan=manager.plan(self.source,expected_serial='101183.1666')
            client.clear_exception=failure
            with self.subTest(failure=type(failure).__name__),self.assertRaises(type(failure) if not isinstance(failure,Exception) else EdltLabelClearUncertain) as caught:manager.request(plan)
            self.assertEqual(client.commands[-1],'LABEL CLEAREDLT '+self.source)
            self.assertEqual(sum(c.startswith('LABEL ') for c in client.commands),1)
            self.assertEqual(manager.last_evidence['outcome'],'outcome_uncertain')
            if not isinstance(failure,Exception):
                self.assertIs(caught.exception,failure);self.assertIs(failure.edlt_label_clear_evidence,manager.last_evidence)
        for response in (reply('600 Queued'),reply('200 OK: '+self.source),reply('200-Unexpected','200 OK.')):
            client=ClearClient();manager=EdltDynamicLabelClear(client);plan=manager.plan(self.source,expected_serial='101183.1666');client.clear_result=response
            with self.assertRaises(EdltLabelClearUncertain):manager.request(plan)
            self.assertEqual(client.commands[-1],'LABEL CLEAREDLT '+self.source)


import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'),'Set isolated C-Gate for eDLT clear acceptance')
class NativeLabelClearTests(unittest.TestCase):
    def test_guarded_native_requests_preserve_outcome_distinctions_and_persist_fixture_policy(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.networks import NativeNetworks
        from cbus_toolkit.programming import xml_text
        from cbus_toolkit.simulator_edlt_labels import EdltLabelClearFixture, LabelClearFault
        from tests.test_simulator_edlt_labels import fixture
        root=Path(__file__).resolve().parents[1]
        report={'passed':False,'physical_device_verified':False,'label_persistence_verified':False,'fixture_policy':EdltLabelClearFixture.POLICY,'cases':[]}
        try:
            for clears,policies in ((True,('ack',)),(False,('ack','extended','wrong_destination','bad_checksum','negative','wrong_tag','wrong_source')),(True,('missing',))):
                project='EC'+uuid4().hex[:6].upper();network='//'+project+'/254';source=network+'/p/5'
                with tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'labels.json';sim=fixture(state_path=path,response_delay=.01)
                    with sim.running('0.0.0.0',0) as (_,port),CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                        projects,database,nets=NativeProjects(client),NativeDatabase(client),NativeNetworks(client);projects.operation('new',project)
                        try:
                            database.create_network(project,254,'eDLT_Clear_Labels','Cni',os.environ.get('CBUS_CGATE_SIMULATOR_HOST','host.docker.internal')+':'+str(port));projects.operation('save',project)
                            client.command('NET LOAD DB '+project);nets.open(network);nets.wait_ready(network,timeout=30)
                            for field,value in (('Retries','0'),('AutoUnravel','no'),('AutoUpdate','no')):
                                self.assertEqual(client.command('SET '+network+' '+field+' '+value).code,200)
                                self.assertEqual(client.command('GET '+network+' '+field).lines,('300 '+network+': '+field+'='+value,))
                            manager=EdltDynamicLabelClear(client);before_db=xml_text(database.get(network,xml=True));before=sim.snapshot()
                            for policy in policies:
                                sim.fault=LabelClearFault(clears,policy)
                                plan=manager.plan(source,expected_serial='101183.1666')
                                count=len(sim.clear_operations);wire=len(sim.wire_log);result=manager.request(plan)
                                accepted=policy in ('ack','extended','wrong_destination','bad_checksum')
                                self.assertEqual(result['outcome'],'native_accepted' if accepted else 'native_rejected')
                                self.assertEqual(len(sim.clear_operations)-count,1)
                                self.assertEqual(sim.unit_labels[5]['labels'],[] if clears else before['unit_labels']['5']['labels'])
                                self.assertEqual(sim.unit_labels[4],before['unit_labels']['4'])
                                self.assertEqual(sim.unit_labels[5]['languages'],before['unit_labels']['5']['languages'])
                                self.assertEqual(sim.snapshot()['base'],before['base'])
                                self.assertEqual(EdltLabelClearFixture.from_state(path).snapshot(),sim.snapshot())
                                self.assertFalse(result['labels_cleared_verified']);self.assertFalse(result['strict_receipt_correlation_verified'])
                                report['cases'].append({'fixture_clear':clears,'fault':policy,'result':result,
                                    'fixture_restart_equal':True,'other_unit_unchanged':True,'pp_unchanged':True,
                                    'operation':sim.clear_operations[-1],'wire':list(sim.wire_log)[wire:]})
                            self.assertEqual(xml_text(database.get(network,xml=True)),before_db)
                            self.assertFalse(any(row.get('reason') for row in sim.wire_log if row['direction']=='rejected'))
                        finally:
                            if client.connected:
                                nets.close(network);projects.operation('close',project);projects.operation('delete',project)
            report['passed']=True
        finally:
            path=root/'research/runtime/edlt-label-clear-acceptance.json';path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(report,indent=2)+'\n')
