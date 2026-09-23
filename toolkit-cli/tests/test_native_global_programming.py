"""Global Programming failure boundaries and independent native persistence."""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4
from xml.dom import minidom

from cbus_toolkit.cgate import CGateClient, CGateResponse
from cbus_toolkit.edlt import EdltError, _render
from cbus_toolkit.edlt_global_programming import CATEGORIES, _issue, _Origin
from cbus_toolkit.native_global_programming import (NativeEdltGlobalProgramming, NativeGlobalPlan,
    NativeGlobalTarget, NativeGlobalProgrammingError, _metadata)
from cbus_toolkit.native import NativeProjects, NativeDatabase
from cbus_toolkit.programming import Programmer, xml_text
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_global_programming import fixture, vectors, categories, VECTOR_PATH
from tests.test_edlt_corridor import cache

ROOT = Path(__file__).resolve().parents[1]


def reply(code=200, text='OK'):
    line = str(code) + ' ' + text
    return CGateResponse((line,), line, code)


class FakeClient:
    def __init__(self):
        self.commands, self.connected, self.failure, self.close_failure = [], True, None, None
    def command(self, command):
        self.commands.append(command)
        if self.failure:
            value = self.failure(command)
            if isinstance(value, BaseException): raise value
            if value is not None: return value
        return reply()
    def close(self):
        self.connected = False
        if self.close_failure: raise self.close_failure


class FakeProjects:
    def __init__(self, client): self.client = client
    def operation(self, operation, name, other=None):
        from cbus_toolkit.native_global_programming import _success
        return _success(self.client.command('PROJECT ' + operation.upper() + ' ' + name + (' ' + other if other else '')), operation)


class NativeGlobalFailureTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.manager = NativeEdltGlobalProgramming(self.client, fixture())
        self.manager.projects = FakeProjects(self.manager._io)
        source = self.manager.engine.prepare_source(vectors()['sources'][1]['input'], metadata=cache().lifecycle)
        payload = self.manager.engine.select(source, categories=('key-settings',))
        before = {**source.final, 'UnitAddress': (21,), 'FontStyle': (2,)}
        merge = self.manager.engine.merge(payload, before)
        self.target = NativeGlobalTarget('//TEST/254/p/21', str(uuid4()), '<Unit/>', _metadata('<Unit/>'), merge,
            bytes(39), bytes(39), bytes(10))
        self.plan = _issue(NativeGlobalPlan('TEST', payload, (self.target,), ('//TEST/254',), None, None, _Origin(self.manager._owner)))
        self.manager._check_source = lambda plan: None
        self.manager._fresh = lambda plan, target: None
        self.manager._networks = lambda project: ('//TEST/254',)
        self.manager._xml = lambda path: '<Unit/>'
        self.manager.engine.common._verify_session = lambda session: None
        self.session_values = dict(before)
        outer = self
        class Session:
            name = 'OWNED'
            def values(self): return dict(outer.session_values)
            def save_to_source(self): return outer.manager._io.command('PP SAVE_TO_SOURCE OWNED')
        @contextmanager
        def session(path):
            try: yield Session()
            except BaseException as error:
                if not isinstance(error, Exception): outer.manager._io.abort(error)
                raise
        self.manager._session = session
        self.manager._raw = lambda session, start, count: bytes(count)
        def apply_set(command):
            match = re.fullmatch(r'PP SET OWNED (\w+) "([0-9a-fx ]+)"', command)
            if match: self.session_values[match[1]] = tuple(int(n,0) for n in match[2].split())
        self.client.failure = apply_set
        self.manager._observe_target = lambda target: {'path': target.path, 'matches_expected':True,
            'parameters_verified':True, 'raw_verified':True, 'crc_bytes_verified':True, 'metadata_verified':True}

    def test_success_forces_all_fields_and_retains_saved_reload_verification(self):
        result = self.manager.apply(self.plan).as_dict()
        self.assertTrue(result['complete']); self.assertTrue(result['targets'][0]['verified_saved'])
        wanted = [k for k, _ in self.plan.payload.ordered_payload]
        self.assertEqual(result['targets'][0]['attempted_parameters'], wanted)
        self.assertEqual(result['targets'][0]['accepted_parameters'], wanted)
        self.assertEqual(sum(c.startswith('PP SET ') for c in self.client.commands), 9)
        self.assertEqual(sum(c.startswith('PP SAVE_TO_SOURCE') for c in self.client.commands), 1)
        self.assertEqual(self.client.commands[-3:], ['PROJECT SAVE TEST','PROJECT CLOSE TEST','PROJECT LOAD TEST'])
        self.assertTrue(result['backup_created'])

    def test_rejected_set_stops_before_save_even_if_later_commands_would_accept(self):
        old = self.client.failure
        def failure(command):
            if ' FontStyle ' in command: return reply(400, 'Owned rejection')
            return old(command)
        self.client.failure = failure
        with self.assertRaises(NativeGlobalProgrammingError) as caught: self.manager.apply(self.plan)
        data = caught.exception.edlt_global_programming_evidence
        self.assertEqual(data['targets'][0]['attempted_parameters'][-1], 'FontStyle')
        self.assertNotIn('FontStyle', data['targets'][0]['accepted_parameters'])
        self.assertFalse(data['target_save_attempted'])
        self.assertFalse(any('SAVE_TO_SOURCE' in c for c in self.client.commands))
        self.assertTrue(self.client.commands[-1].startswith('PP SET OWNED FontStyle '))

    def test_literal_cgate_peer_rejects_one_field_without_following_writes(self):
        from tests.test_cgate import peer
        # Original key-settings source order is independently pinned above.
        responses=[[b'[1] 200 OK.\r\n'],[b'[2] 200 OK.\r\n'],
                   [b'[3] 200 OK.\r\n'],[b'[4] 200 OK.\r\n'],[b'[5] 200 OK.\r\n'],
                   [b'[6] 400 Owned FontStyle rejection\r\n'],[b'[7] 200 OK.\r\n']]
        with peer(responses) as (address,commands):
            with CGateClient(*address) as client:
                self.manager._io.client=client
                with self.assertRaises(NativeGlobalProgrammingError) as caught:
                    self.manager.apply(self.plan,backup_project='OWNBACK')
                self.assertEqual(caught.exception.details['targets'][0]['attempted_parameters'][-1],'FontStyle')
                self.assertFalse(caught.exception.details['target_save_attempted'])
        self.assertEqual(commands,[b'[1] PROJECT SAVE TEST\r\n',b'[2] PROJECT COPY TEST OWNBACK\r\n',
            b'[3] PP SET OWNED OverallCRC "0xd4 0x17"\r\n',b'[4] PP SET OWNED EnableTimerFlash "0x1"\r\n',
            b'[5] PP SET OWNED EnableFanControlLevelWrap "0x1"\r\n',b'[6] PP SET OWNED FontStyle "0x1"\r\n'])

    def test_backup_failure_stale_preconditions_and_forgery_do_not_stage(self):
        self.client.failure = lambda c: reply(408,'already exists') if c.startswith('PROJECT COPY') else None
        with self.assertRaises(NativeGlobalProgrammingError): self.manager.apply(self.plan,backup_project='EXISTS')
        self.assertFalse(any(c.startswith('PP SET') for c in self.client.commands))
        self.client.commands.clear()
        self.manager._fresh = lambda *args: (_ for _ in ()).throw(EdltError('stale'))
        with self.assertRaises(NativeGlobalProgrammingError): self.manager.apply(self.plan)
        self.assertEqual(self.client.commands,[])
        with self.assertRaises(NativeGlobalProgrammingError): self.manager.apply(replace(self.plan))
        self.assertEqual(self.client.commands,[])

    def test_save_failure_records_uncertainty_and_never_replays(self):
        old = self.client.failure
        self.client.failure = lambda c: RuntimeError('response lost') if c.startswith('PP SAVE_TO_SOURCE') else old(c)
        with self.assertRaises(NativeGlobalProgrammingError) as caught: self.manager.apply(self.plan)
        self.assertEqual(caught.exception.edlt_global_programming_evidence['state'],'uncertain')
        self.assertEqual(self.client.commands[-1],'PP SAVE_TO_SOURCE OWNED')
        self.assertEqual(self.client.commands.count('PP SAVE_TO_SOURCE OWNED'),1)

    def test_mixed_error_with_final200_is_not_success(self):
        self.client.failure = lambda c: CGateResponse(('400 rejected','200 OK'),'200 OK',200) if c.startswith('PP SET') else None
        with self.assertRaises(NativeGlobalProgrammingError): self.manager.apply(self.plan)
        self.assertFalse(any(c.startswith('PP SAVE_TO_SOURCE') for c in self.client.commands))

    def test_project_missing_code_or_mixed_reply_is_rejected_before_staging(self):
        for bad in (object(),CGateResponse(('300 unexpected','200 OK'),'200 OK',200)):
            self.client.commands.clear()
            self.manager.projects.operation=lambda *args:bad
            with self.assertRaises(NativeGlobalProgrammingError):self.manager.apply(self.plan)
            self.assertEqual(self.client.commands,[])

    def test_native_raw_reply_requires_exact316_single_complete_frame(self):
        class Session:
            def __init__(self,result):self.result=result
            def get_raw_data(self,*args):return self.result
        for bad in (reply(200,'RawData=0102'),reply(316,'RawData=??02'),
                    reply(316,'RawData=0102junk'),CGateResponse(('316 RawData=0102','316 RawData=0102'),'316 RawData=0102',316)):
            with self.assertRaises(EdltError):NativeEdltGlobalProgramming._raw(self.manager,Session(bad),0,2)
        self.assertEqual(NativeEdltGlobalProgramming._raw(self.manager,Session(reply(316,'RawData=0102')),0,2),b'\x01\x02')

    def test_readback_failure_keeps_prior_verified_targets_and_stops_batch(self):
        second = replace(self.target,path='//TEST/254/p/22')
        plan = _issue(replace(self.plan,targets=(self.target,second),_origin=_Origin(self.manager._owner)))
        self.manager._fresh = lambda *args: self.session_values.update(self.target.merge.expected)
        self.manager._observe_target = lambda target: {'path':target.path,'matches_expected':target is self.target}
        with self.assertRaises(NativeGlobalProgrammingError) as caught: self.manager.apply(plan)
        rows = caught.exception.edlt_global_programming_evidence['targets']
        self.assertTrue(rows[0]['verified_saved']);self.assertFalse(rows[1]['verified_saved'])
        self.assertEqual(len(rows),2)
        self.assertEqual(self.client.commands.count('PP SAVE_TO_SOURCE OWNED'),2)

    def test_first_interruption_cleanup_and_rejected_setattr_identity_are_preserved(self):
        class RejectedAttach(KeyboardInterrupt):
            def __setattr__(self,name,value):
                if name in ('edlt_global_programming_evidence','cgate_cleanup_errors'):
                    raise SystemExit('secondary setattr')
                return super().__setattr__(name,value)
        for original in (KeyboardInterrupt('first'),SystemExit('first'),RejectedAttach('first')):
            with self.subTest(type=type(original)):
                self.client.connected=True;self.client.commands.clear();self.session_values.update(self.target.merge.expected)
                self.client.close_failure=SystemExit('secondary close')
                self.client.failure=lambda c: original if c.startswith('PP SET') else None
                with self.assertRaises(BaseException) as caught:self.manager.apply(self.plan)
                self.assertIs(caught.exception,original)
                self.assertFalse(self.client.connected)
                self.assertTrue(self.client.commands[-1].startswith('PP SET'))
                self.assertEqual(sum(c.startswith('PP SET') for c in self.client.commands),1)
                self.assertEqual(self.manager.last_evidence['cause']['type'],type(original).__name__)

    def test_unprintable_first_error_and_cleanup_details_are_retained(self):
        class Unprintable(RuntimeError):
            def __str__(self): raise KeyboardInterrupt('format failure')
        original = Unprintable();original.cgate_cleanup_errors=(SystemExit('cleanup'),)
        self.client.failure=lambda c: original if c.startswith('PP SET') else None
        with self.assertRaises(NativeGlobalProgrammingError) as caught:self.manager.apply(self.plan)
        self.assertIs(caught.exception.cause,original)
        self.assertEqual(caught.exception.cgate_cleanup_errors,original.cgate_cleanup_errors)
        self.assertIn('unprintable',str(caught.exception))

    def test_verify_is_read_only_different_is_observation_and_failures_uncertain(self):
        self.manager._observe_target=lambda target:{'path':target.path,'matches_expected':False}
        result=self.manager.verify(self.plan).as_dict()
        self.assertEqual(result['state'],'observed_different');self.assertTrue(result['complete'])
        self.assertFalse(result['matches_expected']);self.assertEqual(self.client.commands,[])
        self.manager._observe_target=lambda target: (_ for _ in ()).throw(RuntimeError('read failed'))
        with self.assertRaises(NativeGlobalProgrammingError) as caught:self.manager.verify(self.plan)
        self.assertEqual(caught.exception.details['state'],'uncertain')
        self.assertEqual(caught.exception.details['targets'],[])

    def test_plan_invalid_inputs_and_materialization_are_rejected_before_parameter_io(self):
        for args in (([],True),([self.target.path],False),([self.target.path,self.target.path],True),(['/unit/21'],True)):
            with self.assertRaises(NativeGlobalProgrammingError):self.manager.plan(self.plan.payload,args[0],exclusive_project=args[1])
        self.assertEqual(self.client.commands,[])
        unit='<Unit><Address>21</Address><UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion><CatalogNumber>5055EDL</CatalogNumber><OID>'+str(uuid4())+'</OID></Unit>'
        self.manager._xml=lambda path:unit
        with self.assertRaisesRegex(EdltError,'materialization'):self.manager._read(self.target.path,self.plan.payload)
        self.assertEqual(self.client.commands,[])

    def test_metadata_preserves_unknown_nodes_attributes_comments_and_nested_pp_values(self):
        before='<Unit mark="owned"><OID>x</OID><!--keep--><PP Name="A" Value="1" extra="keep"/><Unknown><PP Value="literal"/></Unknown></Unit>'
        self.assertEqual(_metadata(before),_metadata(before.replace('Value="1"','Value="2"')))
        for modified in (before.replace('literal','changed'),before.replace('keep--','lost--'),before.replace('extra="keep"','extra="lost"')):
            self.assertNotEqual(_metadata(before),_metadata(modified))


@unittest.skipUnless(all(os.environ.get(k) for k in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR')),
    'Select an owned native C-Gate and exact vendor schema for Global Programming acceptance')
class NativeGlobalAcceptanceTests(unittest.TestCase):
    def test_all_masks_source_contexts_order_full_pp_metadata_backup_and_native_reload(self):
        spec_dir=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve()
        spec=UnitSpecStore(spec_dir).load('KEYGL5.xml')
        project='GG'+uuid4().hex[:6].upper();network='//'+project+'/254'
        run=ROOT/'research/runtime/edlt-global-programming'/('implementation-native-'+str(sys.version_info.minor)+'-'+uuid4().hex[:8]);run.mkdir(parents=True)
        paths=[ROOT/'src/cbus_toolkit'/f'{n}.py' for n in ('edlt_global_programming','native_global_programming','edlt_lifecycle','edlt','memory','unitspec','programming','native','cgate')]
        paths += [Path(__file__).resolve(),ROOT/'tests/test_edlt_global_programming.py',ROOT/'tests/test_edlt_corridor.py',VECTOR_PATH,spec_dir/'KEYGL5.xml']
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        report={'passed':False,'python':sys.version,'project':project,'source_hashes':hashes,'cases':[],
                'physical_device_verified':False,'cleanup_errors':[]}
        def write():(run/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        write();backups=[]
        class CaptureClient(CGateClient):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs);self.commands=[];self.raw_replies=[]
            def command(self,command,*args,**kwargs):
                self.commands.append(command)
                answer=super().command(command,*args,**kwargs)
                if command.startswith('PP GET_RAW_DATA') and len(self.raw_replies)<2:self.raw_replies.append(list(answer.lines))
                return answer
        with CaptureClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20033')),timeout=30) as client:
            manager=NativeEdltGlobalProgramming(client,spec);projects,database=NativeProjects(client),NativeDatabase(client)
            projects.operation('new',project)
            try:
                database.create_network(project,254,'Global_Fixture','Cni','127.0.0.1:1')
                for address in (20,21,22):database.create_unit(network,address,'Global_Target_'+str(address),'KEYGL5','5.5.00',catalog_number='5055EDL')
                sample=vectors()['sources'][1];source=manager.engine.prepare_source(sample['input'],metadata=cache().lifecycle)
                payload=manager.engine.select(source,categories=('key-settings',))
                with self.assertRaisesRegex(NativeGlobalProgrammingError,'materialization'):
                    manager.plan(payload,[network+'/p/21'],exclusive_project=True)
                for operation in ('save','close','load'):projects.operation(operation,project)
                seed=manager.engine.snapshot({**sample['input'],**sample['after_load_delta'],**sample['after_save_delta']})
                baseline=dict(seed)
                for name in (name for fields in CATEGORIES.values() for name in fields):
                    layout=manager.engine.codec.layout(name);baseline[name]=((seed[name][0]+1)%(1<<layout.bit_size),)
                baseline.update(Project=project,UnitName='TARGET21',UnitAddress=(21,),SerialNumber=(1,2,3,4),
                                WidgetsCRC=(1,2),StaticTextCRC=(3,4),ScenesCheckSum=(5,6),OverallCRC=(7,8),GlobalParameterCRC=(9,10))
                self.assertEqual(len(baseline),874)
                selected=[]
                for row in vectors()['sources']:
                    for case in row['masks']:selected.append((row,case['mask'],row['parameter_order'],case['ordered_payload']))
                for case in vectors()['reversed_order']:
                    selected.append((sample,case['mask'],case['parameter_order'],case['ordered_payload']))
                for index,(row,mask,order,literal) in enumerate(selected):
                    path=network+'/p/21';source_path='/db'+path
                    with Programmer(client).load(network,source_path) as session:
                        current=manager.engine.snapshot(session.values())
                        for name,value in baseline.items():
                            if current[name]!=value:session.set(name,_render(value))
                        session.save_to_source()
                    projects.operation('save',project)
                    prepared=manager.engine.prepare_source(row['input'],metadata=cache().lifecycle,parameter_order=order)
                    selected_payload=manager.engine.select(prepared,categories=categories(mask))
                    plan=manager.plan(selected_payload,[path],exclusive_project=True)
                    wanted=manager.engine.snapshot({**baseline,**dict(literal)})
                    self.assertEqual(dict(plan.targets[0].merge.final),wanted)
                    backup='B'+uuid4().hex[:7].upper();backups.append(backup)
                    command_start=len(client.commands)
                    result=manager.apply(plan,backup_project=backup).as_dict()
                    self.assertTrue(result['complete']);self.assertTrue(result['targets'][0]['verified_saved'])
                    self.assertEqual(result['targets'][0]['attempted_parameters'],[name for name,_ in literal])
                    sent=[c for c in client.commands[command_start:] if c.startswith('PP SET')]
                    self.assertEqual([c.split(' ',3)[-1] for c in sent],[name+' "'+value+'"' for name,value in literal])
                    verification=manager.verify(plan).as_dict();self.assertTrue(verification['matches_expected'])
                    with Programmer(client).load(network,source_path) as session:self.assertEqual(manager.engine.snapshot(session.values()),wanted)
                    entry={'index':index,'context':row['context'],'mask':mask,'ordered_payload':literal,'result':result,'verify':verification,'sent_pp_set':sent}
                    report['cases'].append(entry);write()
                # Prepare the source once from an explicit separate DB unit;
                # two destinations share that issued payload through reloads.
                for address in (20,21,22):
                    value={**(manager.engine.snapshot(sample['input']) if address==20 else baseline),
                           'UnitAddress':(address,),'Project':project,'UnitName':('SOURCE20' if address==20 else 'TARGET'+str(address))}
                    with Programmer(client).load(network,'/db'+network+'/p/'+str(address)) as session:
                        current=manager.engine.snapshot(session.values())
                        for name,item in value.items():
                            if current[name]!=item:session.set(name,_render(item))
                        session.save_to_source()
                for operation in ('save','close','load'):projects.operation(operation,project)
                with Programmer(client).load(network,'/db'+network+'/p/20') as session: source_values=session.values()
                source=manager.engine.prepare_source(source_values,metadata=cache().lifecycle,parameter_order=sample['parameter_order'])
                payload=manager.engine.select(source,categories=tuple(CATEGORIES))
                source_xml=xml_text(database.get(network+'/p/20',xml=True))
                plan=manager.plan(payload,[network+'/p/21',network+'/p/22'],source_database=network+'/p/20',exclusive_project=True)
                self.assertEqual(xml_text(database.get(network+'/p/20',xml=True)),source_xml)
                backup='B'+uuid4().hex[:7].upper();backups.append(backup)
                result=manager.apply(plan,backup_project=backup).as_dict()
                self.assertEqual([r['verified_saved'] for r in result['targets']],[True,True])
                self.assertEqual(result['targets'][0]['attempted_parameters'],result['targets'][1]['attempted_parameters'])
                self.assertEqual(xml_text(database.get(network+'/p/20',xml=True)),source_xml)
                self.assertTrue(manager.verify(plan).as_dict()['matches_expected'])
                report['cases'].append({'context':'source-database-two-target-sequential','result':result,'source_unchanged':True})
                # Supplied source identity guards are fresh, not just provenance labels.
                database.set(network+'/p/20/Description','Owned stale source')
                before_commands=len(client.commands)
                with self.assertRaisesRegex(NativeGlobalProgrammingError,'Source database XML changed'):
                    manager.apply(plan)
                self.assertFalse(any(c.startswith(('PP SET','PROJECT SAVE','PROJECT COPY')) for c in client.commands[before_commands:]))
                # A newly created source is refused before any PP session can
                # materialize its missing metadata during a read-only plan.
                database.create_unit(network,23,'Unmaterialized_Source','KEYGL5','5.5.00',catalog_number='5055EDL')
                pending_xml=xml_text(database.get(network+'/p/23',xml=True))
                before_commands=len(client.commands)
                with self.assertRaisesRegex(NativeGlobalProgrammingError,'Source requires separate native materialization'):
                    manager.plan(payload,[network+'/p/21'],source_database=network+'/p/23',exclusive_project=True)
                self.assertEqual(xml_text(database.get(network+'/p/23',xml=True)),pending_xml)
                self.assertFalse(any('LOAD ' in c and c.endswith('/p/23') for c in client.commands[before_commands:]))
                database.delete(network+'/p/23')
                # Existing destination backup names fail, even when their copied
                # project is closed. Native must not overwrite a previous backup.
                for loaded in (True,False):
                    if loaded:projects.operation('load',backups[0])
                    else:projects.operation('close',backups[0])
                    with self.assertRaises(Exception) as error:projects.operation('copy',project,backups[0])
                    self.assertIn('Destination project already exists',str(error.exception))
                for path in paths:self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),hashes[str(path)])
                report.update(passed=True,source_hashes_stable=True,backup_collision_rejected_loaded_and_closed=True,
                              raw_replies=client.raw_replies,source_stale_rejected_before_mutation=True,
                              source_plan_xml_unchanged=True,unmaterialized_source_rejected_without_session_load=True,
                              no_physical_commands=not any(c.startswith(('NET OPEN','NET SYNC','NET CHECK')) for c in client.commands))
            except BaseException as error:report['error']={'type':type(error).__name__,'message':str(error)};raise
            finally:
                for name in (*backups,project):
                    try:projects.operation('close',name)
                    except Exception:pass
                    try:projects.operation('delete',name)
                    except Exception as error:report['cleanup_errors'].append({'project':name,'error':str(error)})
                if report['cleanup_errors']:report['passed']=False
                write()
        self.assertEqual(report['cleanup_errors'],[])
        print('Global native evidence: '+str(run/'report.json'))


if __name__=='__main__':unittest.main()
