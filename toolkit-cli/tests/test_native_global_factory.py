"""Factory payload native guards, literal rendering and owned DB persistence."""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from xml.dom import minidom

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.edlt import _render
from cbus_toolkit.edlt_global_preparation import EdltGlobalPreparation, GlobalPreparationContext
from cbus_toolkit.edlt_global_programming import CATEGORIES, _issue, _Origin, _payload_native_value
from cbus_toolkit.native_global_programming import NativeEdltGlobalProgramming, NativeGlobalProgrammingError
from cbus_toolkit.native import NativeProjects, NativeDatabase
from cbus_toolkit.programming import Programmer, xml_text
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_global_factory import fixture, vectors, VECTOR_PATH
from tests import test_native_global_programming as native_support
from tests.test_native_global_programming import reply

ROOT=Path(__file__).resolve().parents[1]


class FactoryNativeGuards(unittest.TestCase):
    def setUp(self):
        base=native_support.NativeGlobalFailureTests();base.setUp()
        self.base=base;self.manager=base.manager;self.client=base.client
        row=vectors()['cases'][0]
        preparer=EdltGlobalPreparation(self.manager.engine.spec)
        prepared=preparer.prepare_factory(row['raw_input'],metadata=vectors()['metadata'],
            context=GlobalPreparationContext('//TEST/254/p/20','TEST','NetPrj'),global_engine=self.manager.engine)
        source=self.manager.engine.prepare_factory_source(prepared)
        payload=self.manager.engine.select(source,categories=tuple(CATEGORIES))
        self.target=replace(base.target,merge=self.manager.engine.merge(payload,base.target.merge.expected))
        self.plan=_issue(replace(base.plan,payload=payload,targets=(self.target,),source_database='//TEST/254/p/20',
            source_xml='<Unit/>',_origin=_Origin(self.manager._owner)))
        def set_value(command):
            if command.startswith('PP SET '):
                name,text=command.split(' ',3)[-1].split(' ',1)
                base.session_values[name]=tuple(int(t,16) if t.lower().startswith('0x') else int(t) for t in text.strip('"').split())
        self.client.failure=set_value

    def test_native_renderer_sends_every_original_literal_in_order(self):
        result=self.manager.apply(self.plan).as_dict()
        self.assertTrue(result['complete']);self.assertTrue(result['factory_model_preparation_applied'])
        sent=[c.split(' ',3)[-1] for c in self.client.commands if c.startswith('PP SET ')]
        wanted=[name+' "'+_payload_native_value(self.plan.payload,name,value)+'"' for name,value in self.plan.payload.ordered_payload]
        self.assertEqual(sent,wanted);self.assertIn('EnableTimerFlash "1"',sent)
        self.assertEqual(self.base.session_values,dict(self.target.merge.final))
        self.assertEqual(sum(c.startswith('PP SAVE_TO_SOURCE') for c in self.client.commands),1)

    def test_exact_source_binding_required_before_any_request(self):
        for source in (None,'//TEST/254/p/21','//OTHER/254/p/20','//test/254/p/20'):
            with self.assertRaisesRegex(NativeGlobalProgrammingError,'exact original source'):
                self.manager.plan(self.plan.payload,['//TEST/254/p/21'],source_database=source,exclusive_project=True)
        self.assertEqual(self.client.commands,[])
        invalid=_issue(replace(self.plan,source_database=None,_origin=_Origin(self.manager._owner)))
        with self.assertRaisesRegex(NativeGlobalProgrammingError,'exact original source'):self.manager.apply(invalid)
        self.assertEqual(self.client.commands,[])

    def test_definite_rejection_and_interruption_do_not_save_or_replay(self):
        initial=self.client.failure
        self.client.failure=lambda c:reply(400,'Owned rejected FontStyle') if ' FontStyle ' in c else initial(c)
        with self.assertRaises(NativeGlobalProgrammingError):self.manager.apply(self.plan)
        self.assertFalse(any(c.startswith('PP SAVE_TO_SOURCE') for c in self.client.commands))
        self.assertTrue(self.client.commands[-1].startswith('PP SET'))
        self.client.commands.clear();self.base.session_values.update(self.target.merge.expected)
        original=KeyboardInterrupt('owned interrupted write')
        self.client.failure=lambda c:original if c.startswith('PP SET') else None
        with self.assertRaises(KeyboardInterrupt) as caught:self.manager.apply(self.plan)
        self.assertIs(caught.exception,original);self.assertFalse(self.client.connected)
        self.assertEqual(sum(c.startswith('PP SET') for c in self.client.commands),1)


@unittest.skipUnless(all(os.environ.get(k) for k in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR')),
    'Select an owned native C-Gate and exact vendor schema')
class FactoryNativeAcceptance(unittest.TestCase):
    def test_factory_all_empty_two_targets_raw_source_guard_and_full_reload(self):
        specdir=Path(os.environ['CBUS_UNITSPEC_DIR']);spec=UnitSpecStore(specdir).load('KEYGL5.xml')
        project='GB'+uuid4().hex[:6].upper();network='//'+project+'/254';source_path=network+'/p/20'
        run=ROOT/'research/runtime/edlt-global-preamble'/('bridge-native-'+str(sys.version_info.minor)+'-'+uuid4().hex[:8]);run.mkdir(parents=True)
        paths=[ROOT/'src/cbus_toolkit'/f'{n}.py' for n in ('edlt_global_preparation','edlt_global_programming','native_global_programming','edlt_reset','edlt_lifecycle','edlt','memory','unitspec','programming','native','cgate')]
        paths += [Path(__file__).resolve(),ROOT/'tests/test_edlt_global_factory.py',VECTOR_PATH,specdir/'KEYGL5.xml']
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        report={'passed':False,'python':sys.version,'project':project,'source_hashes':hashes,'cases':[],'cleanup_errors':[],'physical_device_verified':False}
        def write():(run/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        write();backups=[]
        class Capture(CGateClient):
            def __init__(self,*a,**k):
                super().__init__(*a,**k);self.commands=[];self.session_sources={};self.reject_destination=None;self.rejections=[]
            def command(self,text,*a,**k):
                self.commands.append(text)
                if text.startswith('PP LOAD '):
                    parts=text.split();self.session_sources[parts[2]]=parts[3]
                if text.startswith('PP SET '):
                    parts=text.split(' ',4)
                    if parts[3]=='FontStyle' and self.session_sources.get(parts[2])=='/db'+str(self.reject_destination):
                        actual='PP SET '+parts[2]+' CLI_TEST_INVALID_FACTORY_PARAMETER "0"'
                        self.rejections.append({'planned':text,'sent':actual})
                        return super().command(actual,*a,**k)
                return super().command(text,*a,**k)
        with Capture(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20033')),timeout=30) as client:
            manager=NativeEdltGlobalProgramming(client,spec);projects=NativeProjects(client);database=NativeDatabase(client)
            projects.operation('new',project)
            try:
                database.create_network(project,254,'Factory_Global_Owned','Cni','127.0.0.1:1')
                for address in (20,21,22):database.create_unit(network,address,'Factory_'+str(address),'KEYGL5','5.5.00',catalog_number='5055EDL')
                for operation in ('save','close','load'):projects.operation(operation,project)
                row=vectors()['cases'][0];seed=manager.engine.snapshot(row['raw_input'])
                for address in (20,21,22):
                    values={**seed,'UnitAddress':(address,), 'UnitName':'SOURCE20' if address==20 else 'TARGET'+str(address)}
                    if address!=20:
                        for name in (n for fields in CATEGORIES.values() for n in fields):
                            bits=manager.engine.codec.layout(name).bit_size;values[name]=((seed[name][0]+1)%(1<<bits),)
                        values.update(Project=project,SerialNumber=(address,2,3,4),OverallCRC=(1,2),GlobalParameterCRC=(3,4),WidgetsCRC=(5,6),StaticTextCRC=(7,8),ScenesCheckSum=(9,10))
                    with Programmer(client).load(network,'/db'+network+'/p/'+str(address)) as session:
                        current=manager.engine.snapshot(session.values())
                        for name,value in values.items():
                            if current[name]!=value:session.set(name,_render(value))
                        session.save_to_source()
                for operation in ('save','close','load'):projects.operation(operation,project)
                with Programmer(client).load(network,'/db'+source_path) as session:raw=session.values()
                prep=EdltGlobalPreparation(spec).prepare_factory(raw,metadata=vectors()['metadata'],
                    context=GlobalPreparationContext(source_path,project,'NetPrj'),global_engine=manager.engine)
                source=manager.engine.prepare_factory_source(prep)
                source_xml=xml_text(database.get(source_path,xml=True))
                for mask in (0,15):
                    payload=manager.engine.select(source,categories=tuple(CATEGORIES) if mask else ())
                    before={address:xml_text(database.get(network+'/p/'+str(address),xml=True)) for address in (21,22)}
                    start=len(client.commands)
                    plan=manager.plan(payload,[network+'/p/21',network+'/p/22'],source_database=source_path,exclusive_project=True)
                    self.assertFalse(any(c.startswith(('PP SET','PP SAVE','PROJECT SAVE','PROJECT COPY')) for c in client.commands[start:]))
                    self.assertEqual(source_xml,xml_text(database.get(source_path,xml=True)))
                    for address,xml in before.items():self.assertEqual(xml,xml_text(database.get(network+'/p/'+str(address),xml=True)))
                    # Numerically equivalent respelling is not the exact raw source baseline.
                    original_session=manager._session
                    @contextmanager
                    def changed_source(path):
                        with original_session(path) as session:
                            class Proxy:
                                def __getattr__(self,name):return getattr(session,name)
                                def values(self):
                                    value=session.values()
                                    if path==source_path:value={**value,'NavWidgetType':'255'}
                                    return value
                            yield Proxy()
                    manager._session=changed_source
                    try:
                        start=len(client.commands)
                        with self.assertRaisesRegex(NativeGlobalProgrammingError,'raw programming strings'):
                            manager.plan(payload,[network+'/p/21'],source_database=source_path,exclusive_project=True)
                        self.assertFalse(any(c.startswith(('PP SET','PP SAVE','PROJECT SAVE','PROJECT COPY')) for c in client.commands[start:]))
                    finally:manager._session=original_session
                    backup='B'+uuid4().hex[:7].upper();backups.append(backup);start=len(client.commands)
                    result=manager.apply(plan,backup_project=backup).as_dict()
                    sent=[c.split(' ',3)[-1] for c in client.commands[start:] if c.startswith('PP SET')]
                    wanted=[name+' "'+_payload_native_value(payload,name,value)+'"' for name,value in payload.ordered_payload]
                    self.assertEqual(sent,wanted*2);self.assertTrue(result['complete'])
                    self.assertEqual([r['verified_saved'] for r in result['targets']],[True,True])
                    for target in plan.targets:
                        with Programmer(client).load(network,'/db'+target.path) as session:self.assertEqual(manager.engine.snapshot(session.values()),dict(target.merge.final))
                    projects.operation('load',backup)
                    for target in plan.targets:
                        backup_path=target.path.replace('//'+project+'/', '//'+backup+'/', 1)
                        xml=xml_text(database.get(backup_path,xml=True))
                        nodes=minidom.parseString(xml).documentElement.getElementsByTagName('PP')
                        old={node.getAttribute('Name'):node.getAttribute('Value') for node in nodes}
                        self.assertEqual(manager.engine.snapshot(old),dict(target.merge.expected))
                    projects.operation('close',backup)
                    self.assertEqual(source_xml,xml_text(database.get(source_path,xml=True)))
                    self.assertTrue(manager.verify(plan).as_dict()['matches_expected'])
                    report['cases'].append({'mask':mask,'ordered_literal_payload':wanted,'result':result,'source_xml_unchanged':True,'all874_reload_verified':True,'backup_original874_verified':True,'raw_respelling_rejected':True});write()
                # The second owned target receives a real native rejected SET.
                # The first target is already saved/verified; no later replay
                # or target2 save may be inferred from the vendor's weak worker.
                payload=manager.engine.select(source,categories=tuple(CATEGORIES))
                other=(payload.values['FontStyle'][0]+1)%8
                for address in (21,22):
                    with Programmer(client).load(network,'/db'+network+'/p/'+str(address)) as session:
                        session.set('FontStyle',str(other));session.save_to_source()
                for operation in ('save','close','load'):projects.operation(operation,project)
                plan=manager.plan(payload,[network+'/p/21',network+'/p/22'],source_database=source_path,exclusive_project=True)
                backup='B'+uuid4().hex[:7].upper();backups.append(backup)
                client.reject_destination=network+'/p/22';start=len(client.commands)
                with self.assertRaises(NativeGlobalProgrammingError) as rejected:
                    manager.apply(plan,backup_project=backup)
                client.reject_destination=None
                evidence=rejected.exception.edlt_global_programming_evidence
                self.assertEqual([row['verified_saved'] for row in evidence['targets']],[True,False])
                self.assertFalse(evidence['targets'][1]['save_attempted'])
                self.assertEqual(len(client.rejections),1)
                self.assertEqual(sum(c.startswith('PP SAVE_TO_SOURCE') for c in client.commands[start:]),1)
                for index,target in enumerate(plan.targets):
                    expected=target.merge.final if index==0 else target.merge.expected
                    with Programmer(client).load(network,'/db'+target.path) as session:self.assertEqual(manager.engine.snapshot(session.values()),dict(expected))
                self.assertEqual(source_xml,xml_text(database.get(source_path,xml=True)))
                report['native_rejection']={'result':evidence,'injected_literal':client.rejections[0],
                    'prior_target_saved_full874':True,'rejected_target_unchanged_full874':True,
                    'source_xml_unchanged':True,'target_save_count':1,'replayed':False}
                self.assertFalse(any(c.startswith(('NET OPEN','NET SYNC','NET CHECK')) for c in client.commands))
                self.assertEqual(hashes,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
                report.update(passed=True,source_hashes_stable=True,no_physical_commands=True)
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
        print('Factory Global native evidence: '+str(run/'report.json'))


if __name__=='__main__':unittest.main()
