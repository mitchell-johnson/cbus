"""Global Programming CLI ordering, validation and transport finalization."""
from contextlib import contextmanager,redirect_stderr,redirect_stdout
import io,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from uuid import uuid4
from cbus_toolkit import cli
from cbus_toolkit.edlt_global_programming import EdltGlobalProgramming
from tests.test_edlt import Session
from tests.test_edlt_corridor import cache

@unittest.skipUnless(os.environ.get('CBUS_UNITSPEC_DIR'),'Set exact KEYGL5 specification')
class GlobalCLITests(unittest.TestCase):
    def setUp(self):
        from cbus_toolkit.unitspec import UnitSpecStore
        self.spec=UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.source=self.folder/'source.json';self.metadata=self.folder/'cache.json'
        self.values=Session(self.spec).values();self.source.write_text(json.dumps(self.values))
        self.metadata.write_text(json.dumps(cache().lifecycle.as_dict()))
    def invoke(self,args,status=0):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err):actual=cli.main(list(map(str,args)))
        self.assertEqual(actual,status,out.getvalue()+err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())
    def args(self,*,native=False):
        if native:return ('cgate','edlt-global',self.source,'--metadata',self.metadata,'--destination','//OWNED/254/p/21','--exclusive-project')
        return ('edlt','global-plan',self.source,'--metadata',self.metadata)

    def test_offline_categories_include_forced_crc_writes_and_explicit_order(self):
        with patch('cbus_toolkit.cgate.CGateClient',side_effect=AssertionError('Offline cannot connect')):
            for categories,count in (((),2),(('key-settings',),9),(('standby',),16),(('colour',),20),(('general',),11),(('general','colour','standby','key-settings'),50)):
                flags=tuple(part for name in categories for part in ('--category',name))
                result=self.invoke((*self.args(),*flags));self.assertEqual(result['forced_parameter_count'],count)
                self.assertEqual(result['ordered_payload'][-1]['parameter'],'GlobalParameterCRC')
                self.assertEqual(result['ordered_payload'][-1]['value'],[0,0]);self.assertFalse(result['saved'])
                self.assertEqual(result['source_project_policy'],'preserve');self.assertFalse(result['full_form_preamble_applied'])
            order=list(reversed(self.values));path=self.folder/'order.json';path.write_text(json.dumps(order))
            result=self.invoke((*self.args(),'--category','general','--parameter-order',path))
            allowed={'OverallCRC','CorridorLinkingCorridorGroup','CorridorLinkingOfficeGroup','CorridorLinkingLinkGroup','CorridorLinkingCorridorTime','KeySetsEnableGroup','LongPressTime','DebounceTime','StatusRequestInterval','ToolsPageLocked'}
            self.assertEqual([p['parameter'] for p in result['ordered_payload']],[p for p in order if p in allowed]+['GlobalParameterCRC'])
            self.assertEqual(result['source']['parameter_order'],order)

    def test_invalid_source_metadata_order_and_categories_fail_before_connect(self):
        with patch('cbus_toolkit.cgate.CGateClient',side_effect=AssertionError('Invalid inputs cannot connect')) as connect:
            self.source.write_text('{"x":1,"x":2}');self.assertIn('Duplicate JSON key',self.invoke(self.args(native=True),1)['error'])
            self.source.write_text('{"x":NaN}');self.assertIn('Non-finite JSON',self.invoke(self.args(native=True),1)['error'])
            self.source.write_text(json.dumps(self.values));self.metadata.write_text('{"format":"a","format":"b"}')
            self.assertIn('Duplicate JSON key',self.invoke(self.args(native=True),1)['error'])
            self.metadata.write_text(json.dumps(cache().lifecycle.as_dict()))
            self.assertIn('distinct',self.invoke((*self.args(native=True),'--category','general','--category','general'),1)['error'])
            order=self.folder/'order.json';order.write_text(json.dumps([next(iter(self.values))]*874))
            self.assertIn('exactly once',self.invoke((*self.args(native=True),'--parameter-order',order),1)['error'])
            self.assertIn('exclusive-project',self.invoke(self.args(native=True)[:-1],1)['error'])
            self.assertIn('applies only',self.invoke((*self.args(native=True),'--dry-run','--backup-project','OWNEDBK'),1)['error'])
            connect.assert_not_called()

    def test_native_preview_uses_coordinator_owned_payload_without_apply(self):
        manager=SimpleNamespace(engine=EdltGlobalProgramming(self.spec),last_evidence=None)
        result={'format':'owned-preview','target_saved':False,'targets':[{'path':'//OWNED/254/p/21'}]}
        def plan(payload,destinations,**kwargs):
            manager.engine._payload(payload)
            self.assertEqual(destinations,('//OWNED/254/p/21',));self.assertEqual(kwargs,{'source_database':None,'exclusive_project':True})
            self.assertEqual(payload.categories,('general',));return SimpleNamespace(as_dict=lambda:result)
        manager.plan=Mock(side_effect=plan);manager.apply=Mock(side_effect=AssertionError('Preview cannot apply'))
        @contextmanager
        def connection(*args,**kwargs):yield SimpleNamespace()
        with patch('cbus_toolkit.native_global_programming.NativeEdltGlobalProgramming',return_value=manager), \
                patch('cbus_toolkit.cgate.CGateClient',side_effect=connection):
            actual=self.invoke((*self.args(native=True),'--dry-run','--category','general'))
        self.assertEqual(actual,result);manager.plan.assert_called_once();manager.apply.assert_not_called()

    def test_interruption_fallback_and_socket_cleanup_preserve_completed_targets(self):
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self,name,value):
                if name.startswith('edlt_'):raise SystemExit('Rejected attachment')
                super().__setattr__(name,value)
        for phase in ('apply','connection_cleanup'):
            for error_type in (OSError,RejectEvidence):
                with self.subTest(phase=phase,error=error_type.__name__):
                    error=error_type('Owned failure');saved={'complete':True,'targets':[{'path':'//OWNED/254/p/21','verified_saved':True}],'backup_project':'OWNEDBK','backup_created':True,'target_save_attempted':True}
                    manager=SimpleNamespace(engine=EdltGlobalProgramming(self.spec),last_evidence=None,plan=Mock(return_value=object()))
                    def apply(plan,**kwargs):
                        manager.last_evidence={**saved,'complete':False,'state':'uncertain'}
                        if phase=='apply':raise error
                        return SimpleNamespace(as_dict=lambda:saved)
                    manager.apply=Mock(side_effect=apply)
                    @contextmanager
                    def connection(*args,**kwargs):
                        yield SimpleNamespace()
                        if phase=='connection_cleanup':raise error
                    with patch('cbus_toolkit.native_global_programming.NativeEdltGlobalProgramming',return_value=manager), \
                            patch('cbus_toolkit.cgate.CGateClient',side_effect=connection):
                        actual=self.invoke(self.args(native=True),130 if isinstance(error,KeyboardInterrupt) else 1)
                    evidence=actual['edlt_global_programming_evidence'];self.assertEqual(evidence['targets'],saved['targets'])
                    self.assertTrue(evidence['backup_created']);self.assertTrue(evidence['target_save_attempted'])
                    if phase=='connection_cleanup':self.assertEqual(evidence['failure_phase'],'connection_cleanup');self.assertFalse(evidence['operation_completed'])
                    else:self.assertEqual(evidence['state'],'uncertain')
                    manager.apply.assert_called_once()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'),'Set an owned native C-Gate')
    def test_native_cli_two_targets_preview_backup_full_reload_and_source_preservation(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.edlt import _render
        from cbus_toolkit.native import NativeProjects,NativeDatabase
        from cbus_toolkit.programming import Programmer,xml_text
        from tests.test_edlt_global_programming import vectors
        host=os.environ['CBUS_CGATE_TEST_HOST'];port=int(os.environ.get('CBUS_CGATE_TEST_PORT','20033'))
        project='GC'+uuid4().hex[:6].upper();backup='B'+uuid4().hex[:7].upper()
        network='//'+project+'/254';source_path=network+'/p/20';targets=[network+'/p/'+str(i) for i in (21,22)]
        engine=EdltGlobalProgramming(self.spec);row=vectors()['sources'][1]
        seed=engine.snapshot({**row['input'],**row['after_load_delta'],**row['after_save_delta']})
        def call(*args,status=0):
            result=subprocess.run([sys.executable,'-m','cbus_toolkit',*map(str,args)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,status,result.stdout+result.stderr)
            return json.loads(result.stdout or result.stderr)
        native=('cgate','--host',host,'--port',port,'--timeout',30)
        source_args=(*native,'unit','--lock-address',network,'--source','/db'+source_path)
        with CGateClient(host,port,timeout=30) as client:
            projects,database=NativeProjects(client),NativeDatabase(client)
            def owned_projects():
                names={line.split('project=',1)[1] for line in projects.directory().lines if 'project=' in line}
                return names & {project,backup}
            projects.operation('new',project);backup_created=False
            try:
                database.create_network(project,254,'Global_CLI','Cni','127.0.0.1:1')
                for address in (20,21,22):
                    database.create_unit(network,address,'Global_CLI_'+str(address),'KEYGL5','5.5.00',catalog_number='5055EDL')
                    values={**seed,'Project':project,'UnitAddress':(address,),
                            'UnitName':'SOURCE20' if address==20 else 'TARGET'+str(address),
                            'SerialNumber':(1,2,3,address),'LongPressTime':(address,),
                            'WidgetsCRC':(1,address),'StaticTextCRC':(2,address),'ScenesCheckSum':(3,address)}
                    with Programmer(client).load(network,'/db'+network+'/p/'+str(address)) as session:
                        current=engine.snapshot(session.values())
                        for name,value in values.items():
                            if current[name]!=value:session.set(name,_render(value))
                        session.save_to_source()
                for operation in ('save','close','load'):projects.operation(operation,project)
                self.source.unlink()
                call(*source_args,'export',self.source)
                source_xml=xml_text(database.get(source_path,xml=True))
                before={path:xml_text(database.get(path,xml=True)) for path in targets}
                before_projects=owned_projects()
                offline=call('edlt','global-plan',self.source,'--metadata',self.metadata,'--category','general')
                args=(*native,'edlt-global',self.source,'--metadata',self.metadata,'--category','general',
                      '--source-database',source_path,'--destination',targets[0],'--destination',targets[1],'--exclusive-project')
                preview=call(*args,'--dry-run')
                self.assertEqual(preview['payload']['ordered_payload'],offline['ordered_payload'])
                self.assertFalse(preview['target_saved']);self.assertFalse(preview['batch_atomic'])
                self.assertEqual(before_projects,owned_projects())
                self.assertEqual(source_xml,xml_text(database.get(source_path,xml=True)))
                for path in targets:self.assertEqual(before[path],xml_text(database.get(path,xml=True)))
                result=call(*args,'--backup-project',backup);backup_created=result['backup_created']
                self.assertTrue(result['complete']);self.assertTrue(backup_created);self.assertTrue(result['target_save_attempted'])
                self.assertEqual([item['path'] for item in result['targets']],targets)
                self.assertTrue(all(item['verified_saved'] and item['project_reloaded'] for item in result['targets']))
                for target in preview['targets']:
                    with Programmer(client).load(network,'/db'+target['path']) as session:
                        actual=engine.snapshot(session.values())
                        self.assertEqual(actual,engine.snapshot(target['final']));self.assertEqual(len(actual),874)
                    original=engine.snapshot(target['expected'])
                    for name in ('UnitName','SerialNumber','WidgetsCRC','StaticTextCRC','ScenesCheckSum'):
                        self.assertEqual(actual[name],original[name])
                self.assertEqual(source_xml,xml_text(database.get(source_path,xml=True)))
                self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                projects.operation('load',backup)
                for path in targets:
                    backup_path=path.replace('//'+project+'/', '//'+backup+'/',1)
                    with Programmer(client).load('//'+backup+'/254','/db'+backup_path) as session:
                        actual=engine.snapshot(session.values())
                        original=next(t['expected'] for t in preview['targets'] if t['path']==path)
                        for name in ('LongPressTime','WidgetsCRC','StaticTextCRC','ScenesCheckSum'):
                            self.assertEqual(actual[name],engine.snapshot(original)[name])
            finally:
                remaining=owned_projects()
                for name in (backup,project):
                    if name not in remaining:continue
                    try:projects.operation('close',name)
                    finally:projects.operation('delete',name)
                self.assertEqual(owned_projects(),set())

if __name__=='__main__':unittest.main()
