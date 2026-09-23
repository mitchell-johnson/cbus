"""Blank widget CLI parsing, retained staging, finalization and persistence."""
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
import io,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from uuid import uuid4
from cbus_toolkit import cli
from cbus_toolkit.edlt_blank import EdltBlankWidget
from tests.test_edlt import Session
from tests.test_edlt_corridor import fixture,cache

class BlankCLITests(unittest.TestCase):
    def invoke(self,args,status=0):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err):actual=cli.main(list(map(str,args)))
        self.assertEqual(actual,status,out.getvalue()+err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())

    def test_offline_plan_and_strict_source_cache_and_placement_guards(self):
        spec=fixture();editor=EdltBlankWidget(spec);session=Session(spec)
        session.set('NavWidgetType','1');session.set('Widget6WidgetType','2');session.set('Widget6WidgetByteValue6','42')
        session.set('Widget7WidgetType','2');session.set('Widget7WidgetByteValue6','12')
        with tempfile.TemporaryDirectory() as folder,patch.object(cli,'_edlt_blank',return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient',side_effect=AssertionError('Offline must not connect')):
            source=Path(folder)/'source.json';source.write_text(json.dumps(session.values()))
            metadata=Path(folder)/'metadata.json';metadata.write_text(json.dumps(cache().lifecycle.as_dict()))
            args=('edlt','blank-plan',source,'--metadata',metadata,'--page',1,'--position',1)
            result=self.invoke(args)
            self.assertEqual(result['widget'],6);self.assertEqual(result['requested_type'],0)
            self.assertTrue(result['type_changed']);self.assertEqual(result['stored_type_after_save'],0)
            self.assertFalse(result['saved']);self.assertFalse(result['physical_device_verified'])
            self.assertTrue(result['scene_references_retained'])
            source.write_text('{"Widget6WidgetType":[2],"Widget6WidgetType":[0]}')
            self.assertIn('Duplicate JSON key',self.invoke(args,1)['error'])
            source.write_text(json.dumps(session.values()));metadata.write_text('{"format":"a","format":"b"}')
            self.assertIn('Duplicate key',self.invoke(args,1)['error'])
            metadata.write_text(json.dumps(cache().lifecycle.as_dict()))
            self.assertIn('navigation position',self.invoke((*args[:-1],5),1)['error'])
            source.write_text(json.dumps({'format':'cbus-cli-parameters-v1','unit_type':'KEYGL5','firmware':'5.5.00','catalog_number':'wrong','parameters':session.values()}))
            self.assertIn('source profile',self.invoke(args,1)['error'])

    def test_post_staging_and_cleanup_failures_retain_save_outcomes(self):
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self,name,value):
                if name.startswith('edlt_'):raise SystemExit('Evidence attachment rejected')
                super().__setattr__(name,value)
        for phase in ('readback','save','cleanup','connection_cleanup'):
            for error_type in (OSError,RejectEvidence):
                with self.subTest(phase=phase,error=error_type.__name__):
                    spec=fixture();editor=EdltBlankWidget(spec);session=Session(spec)
                    session.set('NavWidgetType','1');session.set('Widget6WidgetType','2');session.set('Widget6WidgetByteValue6','42')
                    error=error_type('Owned finalization failure');configure=editor.configure;completed=[]
                    def staged(*args,**kwargs):
                        result=configure(*args,**kwargs);completed.append(result)
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
                    with tempfile.TemporaryDirectory() as folder:
                        metadata=Path(folder)/'cache.json';metadata.write_text(json.dumps(cache().lifecycle.as_dict()))
                        with patch.object(editor,'configure',side_effect=staged),patch.object(cli,'_edlt_blank',return_value=editor), \
                                patch('cbus_toolkit.cgate.CGateClient',return_value=connection()), \
                                patch('cbus_toolkit.programming.Programmer',return_value=SimpleNamespace(load=Mock(return_value=context()))):
                            result=self.invoke(('cgate','unit','--lock-address','//EDLTTEST/254','--source',session.source,
                                'edlt-blank','--metadata',metadata,'--page',1,'--position',1),130 if isinstance(error,KeyboardInterrupt) else 1)
                    evidence=result['edlt_blank_evidence'];self.assertEqual(len(completed),1)
                    self.assertEqual(evidence['phases'],completed[0]['phases']);self.assertEqual(evidence['failure_phase'],phase)
                    self.assertTrue(evidence['staging_verified']);self.assertFalse(evidence['operation_completed'])
                    self.assertEqual(evidence['save_attempted'],phase!='readback')
                    self.assertEqual(evidence['saved'],phase in ('cleanup','connection_cleanup'))
                    self.assertEqual(evidence['save_outcome_uncertain'],phase=='save')
                    self.assertEqual(session.save_to_source.call_count,int(phase!='readback'))

    def test_first_write_interruption_never_saves_and_preserves_fallback_evidence(self):
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self,name,value):
                if name.startswith('edlt_'):raise SystemExit('Evidence attachment rejected')
                super().__setattr__(name,value)
        spec=fixture();editor=EdltBlankWidget(spec);session=Session(spec)
        session.set('NavWidgetType','1');session.set('Widget6WidgetType','2');session.set('Widget6WidgetByteValue6','42')
        session.set=Mock(side_effect=RejectEvidence('Owned first write interruption'));session.save_to_source=Mock()
        with tempfile.TemporaryDirectory() as folder:
            metadata=Path(folder)/'cache.json';metadata.write_text(json.dumps(cache().lifecycle.as_dict()))
            with patch.object(cli,'_edlt_blank',return_value=editor), \
                    patch('cbus_toolkit.cgate.CGateClient',return_value=nullcontext(SimpleNamespace())), \
                    patch('cbus_toolkit.programming.Programmer',return_value=SimpleNamespace(load=Mock(return_value=nullcontext(session)))):
                result=self.invoke(('cgate','unit','--lock-address','//EDLTTEST/254','--source',session.source,
                    'edlt-blank','--metadata',metadata,'--page',1,'--position',1),130)
        evidence=result['edlt_blank_evidence'];self.assertEqual(evidence['failure_phase'],'configure')
        self.assertEqual(len(evidence['attempted_parameters']),1);self.assertTrue(evidence['pp_state_uncertain'])
        self.assertFalse(evidence['saved']);session.save_to_source.assert_not_called();self.assertEqual(session.set.call_count,1)

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),'Set owned native C-Gate and unit specification')
    def test_native_preview_save_close_load_and_destination_guard(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects,NativeDatabase
        from cbus_toolkit.programming import Programmer
        host=os.environ['CBUS_CGATE_TEST_HOST'];port=int(os.environ.get('CBUS_CGATE_TEST_PORT','20033'))
        project='BL'+uuid4().hex[:6].upper();network='//'+project+'/254';source='/db'+network+'/p/20'
        def call(*args,status=0):
            result=subprocess.run([sys.executable,'-m','cbus_toolkit',*map(str,args)],capture_output=True,text=True,timeout=40)
            self.assertEqual(result.returncode,status,result.stdout+result.stderr)
            return json.loads(result.stdout or result.stderr)
        args=('cgate','--host',host,'--port',port,'--timeout',20,'unit','--lock-address',network,'--source',source)
        with tempfile.TemporaryDirectory() as folder,CGateClient(host,port,timeout=30) as client:
            projects=NativeProjects(client);database=NativeDatabase(client);projects.operation('new',project)
            try:
                database.create_network(project,254,'Blank_CLI','Cni','127.0.0.1:1')
                database.create_unit(network,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL')
                with Programmer(client).load(network,source) as session:
                    session.reset_defaults();session.set('NavWidgetType','1');session.set('Widget6WidgetType','2');session.set('Widget6WidgetByteValue6','42')
                    session.set('Widget7WidgetType','7');session.set('Widget7WidgetByteValue1','237')
                    session.set('Widget8WidgetType','8');session.set('Widget8WidgetByteValue1','18');session.save_to_source()
                projects.operation('save',project)
                original=call(*args,'show');source_file=Path(folder)/'source.json';call(*args,'export',source_file)
                metadata=Path(folder)/'cache.json';metadata.write_text(json.dumps(cache().lifecycle.as_dict()))
                flags=('--metadata',metadata,'--page',1,'--position',1)
                plan=call('edlt','blank-plan',source_file,*flags)
                preview=call(*args,'--dry-run','edlt-blank',*flags)
                self.assertFalse(preview['saved']);self.assertTrue(preview['verified']);self.assertEqual(plan['changes'],preview['changes'])
                self.assertEqual(original,call(*args,'show'))
                saved=call(*args,'edlt-blank',*flags);self.assertTrue(saved['saved'])
                self.assertEqual(len(saved['parameters']),874);self.assertEqual(saved['parameters'],preview['parameters'])
                self.assertEqual(saved['stored_type_after_save'],0)
                self.assertIn('database destinations only',call(*args,'--destination',network+'/p/20','edlt-blank',*flags,status=1)['error'])
                for op in ('save','close','load'):projects.operation(op,project)
                self.assertEqual(call(*args,'show'),saved['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
            finally:
                projects.operation('close',project);projects.operation('delete',project)

if __name__=='__main__':unittest.main()
