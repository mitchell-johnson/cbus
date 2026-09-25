"""Retained Scene Manager CLI state, partial outcomes, finalization and native save."""
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
import io,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from uuid import uuid4
from cbus_toolkit import cli
from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_manager import SceneManagerCache
from cbus_toolkit.edlt_scene_manager_cli import SceneCLIEditor
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import fixture
from tests.test_edlt_scene_manager import cache,operations,vectors


class SceneManagerCLITests(unittest.TestCase):
    def setUp(self):
        self.spec=fixture();self.editor=SceneCLIEditor(self.spec);self.session=Session(self.spec)
        self.session.current.update({k:v for k,v in vectors()['input'].items() if k in self.spec.parameters})
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.source=self.folder/'source.json';self.metadata=self.folder/'cache.json';self.ops=self.folder/'operations.json'
        self.source.write_text(json.dumps(self.session.values()));self.metadata.write_text(json.dumps(cache()));self.ops.write_text('[]')

    def invoke(self,args,status=0):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err):result=cli.main(list(map(str,args)))
        self.assertEqual(result,status,out.getvalue()+err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())

    def flags(self):return ('--metadata',self.metadata,'--operations',self.ops)
    def offline(self,state=False):return ('edlt','scene-manager-state' if state else 'scene-manager-plan',self.source,*self.flags())
    def native(self):return ('cgate','unit','--lock-address','//EDLTTEST/254','--source',self.session.source,'edlt-scene-manager',*self.flags())

    def test_offline_retained_state_getters_groups_validation_and_plan(self):
        self.ops.write_text(json.dumps(operations('sync')))
        with patch('cbus_toolkit.edlt_scene_manager_cli.editor',return_value=self.editor), \
                patch('cbus_toolkit.cgate.CGateClient',side_effect=AssertionError('Offline cannot connect')):
            result=self.invoke((*self.offline(True),'--validate','--list-groups',1))
            self.assertTrue(result['complete']);self.assertFalse(result['saved'])
            self.assertTrue(result['export_is_review_only']);self.assertIn('1',result['available_groups'])
            self.assertEqual({item['level'] for item in result['state']['scenes'][0]['items']},{127})
            self.assertFalse(result['validation']['save_blocking'])
            used={item['group_reference']['group'] for item in result['state']['scenes'][0]['items']}
            self.assertTrue(used.isdisjoint({g['address'] for g in result['available_groups']['1']}))
            plan=self.invoke((*self.offline(),'--validate'))
            self.assertEqual(plan['source']['scenes'],result['state']['scenes'])
            self.assertFalse(plan['saved']);self.assertFalse(plan['physical_device_verified'])
            self.assertIn('crc_projection',plan)

    def test_offline_static_name_allocation_evidence_and_order(self):
        self.ops.write_text(json.dumps([
            {'op':'set-name-text','scene':1,'text':'CLI scene'},
            {'op':'set-name-text','scene':2,'text':'CLI scene'},
            {'op':'set-name-index','scene':1,'index':255},
        ]))
        with patch('cbus_toolkit.edlt_scene_manager_cli.editor',return_value=self.editor), \
                patch('cbus_toolkit.cgate.CGateClient',side_effect=AssertionError('Offline cannot connect')):
            state=self.invoke(self.offline(True));plan=self.invoke(self.offline())
        static=state['state']['static_text']
        self.assertEqual([(row['index'],row['reused']) for row in static['allocations']],[(63,False),(63,True)])
        self.assertEqual(state['state']['scenes'][0]['name_index'],255)
        self.assertEqual(state['state']['scenes'][1]['name_index'],63)
        self.assertEqual(plan['static_text']['fingerprint'],static['fingerprint'])
        self.assertEqual(plan['static_text']['overlay_changes'],static['overlay_changes'])
        self.assertTrue(plan['static_text_allocated']);self.assertEqual(plan['scene_pointers'],[0,11,19,24,29,34,39,44])

    def test_strict_inputs_and_unavailable_operations_reject_without_writes(self):
        with patch('cbus_toolkit.edlt_scene_manager_cli.editor',return_value=self.editor):
            self.source.write_text('{"x":1,"x":2}');self.assertIn('Duplicate JSON key',self.invoke(self.offline(),1)['error'])
            self.source.write_text(json.dumps(self.session.values()));self.metadata.write_text('{"x":1,"x":2}')
            self.assertIn('Duplicate JSON key',self.invoke(self.offline(),1)['error'])
            self.metadata.write_text(json.dumps(cache()))
            for document,message in (('[{"op":"clear-scene","op":"copy","scene":1}]','Duplicate JSON key'),
                ('[NaN]','Non-finite JSON'),('{"op":"copy"}','array'),
                ('[{"op":"broadcast","scene":1}]','Invalid scene operation'),
                ('[{"op":"set-name-text","scene":1,"text":""}]','nonblank'),
                (json.dumps([{'op':'clear-scene','scene':1}]*257),'256')):
                self.ops.write_text(document);self.assertIn(message,self.invoke(self.offline(),1)['error'])
            self.ops.write_text('[]');self.assertIn('at most once',self.invoke((*self.offline(True),'--list-groups',1,'--list-groups',1),1)['error'])
            self.source.write_text(json.dumps({'format':'cbus-cli-parameters-v1','unit_type':'KEYGL5','firmware':'1','catalog_number':'5055EDL','parameters':self.session.values()}))
            self.assertIn('source profile',self.invoke(self.offline(),1)['error'])

    def test_static_name_exhaustion_does_not_stage_pp(self):
        session=Session(self.spec);session.current.update(self.session.current)
        for widget in range(1,14):
            session.current[f'Widget{widget}WidgetType']=(4,);session.current[f'Widget{widget}WidgetByteValue1']=(53,)
            for slot,offset in enumerate((9,10,11,12,13)):
                session.current[f'Widget{widget}WidgetByteValue{offset}']=(min(63,(widget-1)*5+slot),)
        session.current['Widget14WidgetType']=(255,)
        for widget in range(15,22):session.current[f'Widget{widget}WidgetType']=(0,)
        with self.assertRaisesRegex(EdltError,'full'):
            self.editor.configure(session,metadata=SceneManagerCache.from_dict(cache()),
                                  operations=({'op':'set-name-text','scene':1,'text':'No free slot'},),validate=False)
        self.assertEqual(session.calls,[])

    def test_capacity_partial_state_is_reviewable_and_never_staged_or_saved(self):
        self.ops.write_text(json.dumps(operations('capacity-add')))
        with patch('cbus_toolkit.edlt_scene_manager_cli.editor',return_value=self.editor):
            state=self.invoke(self.offline(True));self.assertFalse(state['complete'])
            self.assertEqual(state['state']['item_count'],64);self.assertFalse(state['operation_results'][-1]['complete'])
            result=self.invoke(self.offline(),1);self.assertIn('edlt_scene_manager_evidence',result)
            self.assertEqual(result['edlt_scene_manager_evidence']['state']['item_count'],64)
        self.session.set=Mock(side_effect=AssertionError('Partial edit cannot stage'));self.session.save_to_source=Mock()
        with patch.object(cli,'_edlt_scene_manager',return_value=self.editor), \
                patch('cbus_toolkit.cgate.CGateClient',return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer',return_value=SimpleNamespace(load=Mock(return_value=nullcontext(self.session)))):
            result=self.invoke(self.native(),1)
        evidence=result['edlt_scene_manager_evidence'];self.assertFalse(evidence['save_attempted'])
        self.assertEqual(evidence['attempted_parameters'],[]);self.assertFalse(evidence['pp_state_uncertain'])
        self.session.set.assert_not_called();self.session.save_to_source.assert_not_called()

    def test_save_readback_and_cleanup_failures_keep_original_evidence(self):
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self,name,value):
                if name.startswith('edlt_'):raise SystemExit('Rejected attachment')
                super().__setattr__(name,value)
        self.ops.write_text(json.dumps(operations('sync')))
        for phase in ('configure','readback','save','cleanup','connection_cleanup'):
            for error_type in (OSError,RejectEvidence):
                with self.subTest(phase=phase,error=error_type.__name__):
                    session=Session(self.spec);session.current.update(self.session.current)
                    editor=SceneCLIEditor(self.spec);original=editor.configure;error=error_type('Owned failure');completed=[]
                    if phase=='configure':session.set=Mock(side_effect=error)
                    def configure(*args,**kwargs):
                        result=original(*args,**kwargs);completed.append(result)
                        if phase=='readback':session.values=Mock(side_effect=error)
                        return result
                    session.save_to_source=Mock(side_effect=error if phase=='save' else None,return_value=object())
                    @contextmanager
                    def context():
                        yield session
                        if phase=='cleanup':raise error
                    @contextmanager
                    def connection():
                        yield SimpleNamespace()
                        if phase=='connection_cleanup':raise error
                    with patch.object(editor,'configure',side_effect=configure),patch.object(cli,'_edlt_scene_manager',return_value=editor), \
                            patch('cbus_toolkit.cgate.CGateClient',return_value=connection()), \
                            patch('cbus_toolkit.programming.Programmer',return_value=SimpleNamespace(load=Mock(return_value=context()))):
                        result=self.invoke(self.native(),130 if isinstance(error,KeyboardInterrupt) else 1)
                    evidence=result['edlt_scene_manager_evidence'];self.assertEqual(evidence['failure_phase'],phase)
                    self.assertFalse(evidence['operation_completed']);self.assertEqual(evidence['saved'],phase in ('cleanup','connection_cleanup'))
                    self.assertEqual(evidence['save_attempted'],phase not in ('configure','readback'))
                    self.assertEqual(evidence['save_outcome_uncertain'],phase=='save')
                    if phase=='configure':session.save_to_source.assert_not_called()
                    else:self.assertEqual(evidence['changes'],completed[0]['changes'])

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),'Set owned C-Gate and exact vendor schema')
    def test_native_cli_preview_complete64_original_crc_save_close_load_and_guard(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.edlt import _render
        from cbus_toolkit.native import NativeProjects,NativeDatabase
        from cbus_toolkit.programming import Programmer
        from cbus_toolkit.unitspec import UnitSpecStore
        host=os.environ['CBUS_CGATE_TEST_HOST'];port=int(os.environ.get('CBUS_CGATE_TEST_PORT','20033'))
        project='SC'+uuid4().hex[:6].upper();network='//'+project+'/254';source='/db'+network+'/p/20'
        spec=UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml');engine=SceneCLIEditor(spec).engine
        def call(*args,status=0):
            r=subprocess.run([sys.executable,'-m','cbus_toolkit',*map(str,args)],capture_output=True,text=True,timeout=60)
            self.assertEqual(r.returncode,status,r.stdout+r.stderr);return json.loads(r.stdout or r.stderr)
        args=('cgate','--host',host,'--port',port,'--timeout',30,'unit','--lock-address',network,'--source',source)
        self.ops.write_text(json.dumps([{'op':'clear-items','scene':s} for s in range(1,9)]+[
            {'op':'add-groups','scene':1,'groups':list(range(64))},
            {'op':'set-name-text','scene':1,'text':'Native full scene'}]))
        with CGateClient(host,port,timeout=30) as client:
            projects,database=NativeProjects(client),NativeDatabase(client);projects.operation('new',project)
            try:
                database.create_network(project,254,'Scene_CLI','Cni','127.0.0.1:1')
                database.create_unit(network,20,'Scene_Manager','KEYGL5','5.5.00',catalog_number='5055EDL')
                with Programmer(client).load(network,source) as session:
                    current=engine.snapshot(session.values());seed=engine.snapshot(vectors()['input'])
                    seed.update(Project=project,UnitAddress=(20,),UnitName='SCENECLI')
                    for name,value in seed.items():
                        if value!=current[name]:session.set(name,_render(value))
                    session.save_to_source()
                for action in ('save','close','load'):projects.operation(action,project)
                self.source.unlink();call(*args,'export',self.source);original=call(*args,'show')
                plan=call(*self.offline());self.assertEqual(plan['crc_projection']['original_scene_bucket_tokens'],233)
                self.assertTrue(plan['static_text_allocated']);self.assertEqual(plan['static_text']['allocations'][0]['index'],63)
                preview=call(*args,'--dry-run','edlt-scene-manager',*self.flags())
                self.assertEqual(preview['changes'],plan['changes']);self.assertFalse(preview['saved'])
                self.assertEqual(original,call(*args,'show'))
                saved=call(*args,'edlt-scene-manager',*self.flags());self.assertTrue(saved['saved'])
                self.assertEqual(len(saved['parameters']),874);self.assertEqual(saved['parameters'],preview['parameters'])
                self.assertIn('database destinations only',call(*args,'--destination',network+'/p/20','edlt-scene-manager',*self.flags(),status=1)['error'])
                for action in ('save','close','load'):projects.operation(action,project)
                self.assertEqual(call(*args,'show'),saved['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
            finally:
                try:projects.operation('close',project)
                finally:projects.operation('delete',project)


if __name__=='__main__':unittest.main()
