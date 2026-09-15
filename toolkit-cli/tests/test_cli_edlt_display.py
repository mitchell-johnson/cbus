"""Global eDLT display CLI: option preservation, staging, native save and interruption."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from cbus_toolkit import cli
from cbus_toolkit.edlt_display import EdltDisplaySettings
from tests.test_edlt import Session
from tests.test_edlt_display import fixture


class EdltDisplayCLITests(unittest.TestCase):
    def cli(self,*args,status=0):
        result=subprocess.run([sys.executable,'-m','cbus_toolkit',*map(str,args)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,status,result.stdout+result.stderr)
        return json.loads(result.stdout or result.stderr)

    def invoke(self,args,status=0):
        output,error=io.StringIO(),io.StringIO()
        with redirect_stdout(output),redirect_stderr(error):code=cli.main(list(map(str,args)))
        self.assertEqual(code,status,output.getvalue()+error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def test_offline_real_parser_preserves_omitted_flags_raw_font_and_reports_mra(self):
        spec=fixture();session=Session(spec);editor=EdltDisplaySettings(spec)
        values=session.values();values['FontStyle']='7';values['UseBigIcon']='0'
        values['EnableTimerFlash']='1';values['EnableFanControlLevelWrap']='0'
        for widget,kind,control in ((6,7,0x6d),(7,8,0xb2),(8,9,3)):
            values[f'Widget{widget}WidgetType']=str(kind);values[f'Widget{widget}WidgetByteValue1']=str(control)
        with tempfile.TemporaryDirectory() as directory,patch.object(cli,'_edlt_display',return_value=editor),\
                patch('cbus_toolkit.cgate.CGateClient',side_effect=AssertionError('Offline must not connect')):
            path=Path(directory)/'values.json';path.write_text(json.dumps(values))
            result=self.invoke(('edlt','display-plan',path,'--no-big-icons'))
            self.assertEqual(result['font_style'],7);self.assertEqual(result['large_text'],'label')
            self.assertFalse(result['font_style_ui_canonical']);self.assertFalse(result['big_icons'])
            self.assertTrue(result['timer_flash']);self.assertFalse(result['fan_level_wrap'])
            self.assertTrue(result['applies_to_whole_unit']);self.assertFalse(result['saved'])
            self.assertEqual(result['mra_propagation']['changes'],
                {'Widget7WidgetByteValue1':[0x6a],'Widget8WidgetByteValue1':[0x6b]})
            for text,font in (('label',1),('status',2)):
                result=self.invoke(('edlt','display-plan',path,'--large-text',text,'--big-icons','--no-timer-flash','--fan-level-wrap'))
                self.assertEqual(result['font_style'],font);self.assertTrue(result['font_style_ui_canonical'])
                self.assertTrue(result['big_icons']);self.assertFalse(result['timer_flash']);self.assertTrue(result['fan_level_wrap'])
                self.assertFalse(result['physical_device_verified'])
            self.assertEqual(json.loads(path.read_text()),values)

    def test_wrong_export_profile_rejects_before_schema_or_network_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'wrong.json'
            path.write_text(json.dumps({'format':'cbus-cli-parameters-v1','unit_type':'KEYGL5',
                'firmware':'5.4.00','catalog_number':'5055EDL','parameters':{}}))
            with patch.object(cli,'_edlt_display',side_effect=AssertionError('Wrong profile must fail first')):
                result=self.invoke(('edlt','display-plan',path),status=1)
            self.assertIn('identity differs',result['error'])

    def test_actual_main_retains_nested_interrupt_evidence_and_does_not_save_or_recover(self):
        spec=fixture();session=Session(spec);editor=EdltDisplaySettings(spec);session.connected=True
        interrupted=KeyboardInterrupt('first PP SET');calls=[]
        def fail(name,value):
            calls.append(name);session.current[name]=value;session.connected=False;raise interrupted
        session.set=fail;session.save_to_source=Mock(side_effect=AssertionError('No save after interrupt'))
        loader=Mock(return_value=nullcontext(session));programmer=SimpleNamespace(load=loader)
        args=('cgate','unit','--lock-address','//EDLTTEST/254','--source',session.source,
              'edlt-display','--large-text','status')
        with patch('cbus_toolkit.cgate.CGateClient',return_value=nullcontext(SimpleNamespace())),\
                patch('cbus_toolkit.programming.Programmer',return_value=programmer),\
                patch.object(cli,'_edlt_display',return_value=editor):
            result=self.invoke(args,status=130)
        self.assertEqual(result['error'],'Interrupted');self.assertEqual(len(calls),1)
        self.assertEqual(result['edlt_display_evidence']['attempted_parameters'],calls)
        self.assertTrue(result['edlt_display_evidence']['pp_state_uncertain'])
        self.assertFalse(result['edlt_display_evidence']['saved'])
        self.assertFalse(result['edlt_display_evidence']['verified'])
        self.assertEqual(result['edlt_display_evidence']['automatic_retries'],0)
        self.assertEqual(result['edlt_display_evidence'],interrupted.edlt_display_evidence)
        session.save_to_source.assert_not_called();loader.assert_called_once()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and unit specifications for eDLT display CLI acceptance')
    def test_native_offline_preview_save_reload_and_database_destination_guard(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase,NativeProjects
        from cbus_toolkit.programming import Programmer
        project='DC'+uuid4().hex[:6].upper();network='//'+project+'/254';source='/db'+network+'/p/20'
        host=os.environ['CBUS_CGATE_TEST_HOST'];port=int(os.environ.get('CBUS_CGATE_TEST_PORT','20023'))
        args=('cgate','--host',host,'--port',port,'--timeout',20,'unit','--lock-address',network,'--source',source)
        with tempfile.TemporaryDirectory() as directory,CGateClient(host,port,timeout=30) as client:
            projects,database=NativeProjects(client),NativeDatabase(client);projects.operation('new',project)
            try:
                database.create_network(project,254,'Display_CLI','Cni','127.0.0.1:29999')
                database.create_unit(network,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL')
                projects.operation('save',project)
                with Programmer(client).load(network,source) as session:
                    for widget in range(1,22):session.set(f'Widget{widget}WidgetType','0')
                    for scene in range(1,9):session.set(f'Scene{scene}StartAddress','255')
                    for name,value in (('ConfigVersionMajor',1),('ConfigVersionMinor',0),('FontStyle',7),
                        ('UseBigIcon',0),('EnableTimerFlash',1),('EnableFanControlLevelWrap',0)):
                        session.set(name,str(value))
                    for widget,kind,control in ((6,7,0x6d),(7,8,0xb2),(8,9,3)):
                        session.set(f'Widget{widget}WidgetType',str(kind));session.set(f'Widget{widget}WidgetByteValue1',str(control))
                    session.save_to_source()
                original=self.cli(*args,'show');path=Path(directory)/'before.json';self.cli(*args,'export',path)
                plan=self.cli('edlt','display-plan',path,'--no-big-icons')
                self.assertEqual(plan['font_style'],7);self.assertFalse(plan['font_style_ui_canonical'])
                self.assertTrue(plan['timer_flash']);self.assertFalse(plan['fan_level_wrap'])
                self.assertEqual(plan['mra_propagation']['source_widget'],6)
                self.assertEqual(plan['mra_propagation']['changes'],
                    {'Widget7WidgetByteValue1':[0x6a],'Widget8WidgetByteValue1':[0x6b]})
                preview=self.cli(*args,'--dry-run','edlt-display','--no-big-icons')
                self.assertTrue(preview['verified']);self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'],plan['changes']);self.assertEqual(self.cli(*args,'show'),original)
                result=self.cli(*args,'edlt-display','--large-text','status','--big-icons','--no-timer-flash','--fan-level-wrap')
                self.assertTrue(result['saved']);self.assertTrue(result['verified']);self.assertTrue(result['applies_to_whole_unit'])
                self.assertFalse(result['physical_device_verified']);self.assertEqual(result['destination'],source)
                fields=('FontStyle','UseBigIcon','EnableTimerFlash','EnableFanControlLevelWrap')
                self.assertEqual([int(result['parameters'][name],0) for name in fields],[2,1,0,1])
                self.assertEqual([int(result['parameters'][f'Widget{widget}WidgetByteValue1'],0) for widget in (6,7,8)],[0x6d,0x6a,0x6b])
                for name,value in original.items():
                    if name.startswith('StaticTextString') or (name.startswith('Scene') and name!='ScenesCheckSum'):
                        self.assertEqual(result['parameters'][name],value)
                for action in ('save','close','load'):projects.operation(action,project)
                self.assertEqual(self.cli(*args,'show'),result['parameters'])
                retained=self.cli(*args,'edlt-display','--large-text','label')
                self.assertEqual([int(retained['parameters'][name],0) for name in fields],[1,1,0,1])
                rejected=self.cli(*args,'--destination',network+'/p/20','edlt-display','--large-text','status',status=1)
                self.assertIn('database destinations only',rejected['error'])
                self.assertEqual(self.cli(*args,'show'),retained['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                report={'passed':True,'project':project,'network_opened':False,'saved_reloaded':True,
                    'offline_preview_changes_match':True,'dry_run_database_unchanged':True,
                    'raw_font_preserved':7,'explicit_font_values':[2,1],'omitted_boolean_values_retained':[1,0,1],
                    'mra_first_widget':6,'mra_bytes_after':[0x6d,0x6a,0x6b],
                    'database_destination_guard':True,'physical_device_verified':False}
                runtime=Path(__file__).resolve().parents[1]/'research/runtime';runtime.mkdir(exist_ok=True)
                (runtime/'edlt-display-cli-report.json').write_text(json.dumps(report,indent=2)+'\n')
            finally:
                projects.operation('close',project);projects.operation('delete',project)


if __name__=='__main__':unittest.main()
