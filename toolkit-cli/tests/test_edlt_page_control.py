"""Original eDLT Page Control binding, numeric references and native PP persistence."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_page_control import EdltPageControl
from cbus_toolkit.unitspec import ParameterSpec, UnitSpecStore
from tests.test_edlt import fixture as base_fixture, Session


def fixture():
    spec=base_fixture();parameters=dict(spec.parameters)
    for name,address,default in (('KeySetsEnableGroup',0x131,255),('ActivityDuration',0x11b,0),
                                ('BacklightActiveBrightnessControlGroup',0x130,7),('CorridorLinkingLinkGroup',0x132,42)):
        parameters[name]=ParameterSpec(name,'int','synthetic.xml',dict(Name=name,Type='int',Address=hex(address),DefaultValue=str(default)))
    return replace(spec,parameters=parameters)


def after(plan):return {**plan.expected,**plan.changes}


class PageControlTests(unittest.TestCase):
    def setUp(self):
        self.spec=fixture();self.editor=EdltPageControl(self.spec);self.session=Session(self.spec)

    def plan(self,current=None,**options):
        return self.editor.plan(self.session.values() if current is None else current,**options)

    def test_numeric_group_disabled_and_adjacent_preservation(self):
        original=self.editor.snapshot(self.session.values())
        for group in (0,1,7,42,254,255):
            plan=self.plan(group=group);result=plan.as_dict()
            self.assertEqual(after(plan)['KeySetsEnableGroup'],(group,));self.assertEqual(result['group'],group)
            self.assertEqual(result['application'],203);self.assertEqual(result['enabled'],group!=255)
            self.assertEqual(after(plan)['BacklightActiveBrightnessControlGroup'],(7,))
            self.assertEqual(after(plan)['CorridorLinkingLinkGroup'],(42,))
            self.assertFalse(result['database_group_created']);self.assertFalse(result['database_group_verified'])
            self.assertFalse(result['physical_page_control_verified'])
            self.assertEqual(after(self.plan(after(plan)))['KeySetsEnableGroup'],(group,))
        self.assertEqual(self.editor.snapshot(self.session.values()),original);self.assertFalse(self.session.calls)

    def test_no_primary_standby_or_navigation_selection_dependency(self):
        source=self.editor.snapshot(self.session.values())
        for primary in (56,127,136):
            for nav in (0,1):
                for duration in (0,30):
                    current={**source,'PrimaryApplication':(primary,),'NavWidgetType':(nav,),'ActivityDuration':(duration,)}
                    plan=self.plan(current,group=42);result=after(plan)
                    self.assertEqual(plan.as_dict()['application'],203)
                    self.assertEqual((result['ActivityDuration'],result['NavWidgetType'],result['PrimaryApplication']),((duration,),(nav,),(primary,)))
                    self.assertEqual(result['Application'],(primary,57));self.assertEqual(plan.group,42)

    def test_input_profile_layout_stale_and_forged_plan_guards(self):
        for value in (-1,256,True,1.0,'42',[],{}):
            with self.assertRaises(EdltError):self.plan(group=value)
        for options in (dict(firmware='5.4.00'),dict(catalog_number='OTHER')):
            with self.assertRaises(EdltError):EdltPageControl(self.spec,**options)
        for fields in ({'Address':'0x132'},{'BitAddress':'1'},{'ArraySize':'2'},{'BitSize':'7'}):
            parameters=dict(self.spec.parameters);p=parameters['KeySetsEnableGroup'];parameters['KeySetsEnableGroup']=replace(p,fields={**p.fields,**fields})
            with self.assertRaisesRegex(EdltError,'layout'):EdltPageControl(replace(self.spec,parameters=parameters))
        parameters=dict(self.spec.parameters);del parameters['KeySetsEnableGroup']
        with self.assertRaisesRegex(EdltError,'layout'):EdltPageControl(replace(self.spec,parameters=parameters))
        plan=self.plan(group=42)
        for forged in (None,replace(plan,group=True),replace(plan,group=43),replace(plan,changes={}),replace(plan,options={'unknown':1})):
            with self.assertRaises(EdltError):self.editor.apply(self.session,forged)
        self.session.current['ActivityDuration']=(30,)
        with self.assertRaisesRegex(EdltError,'changed'):self.editor.apply(self.session,plan)
        self.session.identity['UnitType']='KEY4';self.session.values=lambda:(_ for _ in ()).throw(AssertionError('No PP read after identity rejection'))
        with self.assertRaises(EdltError):self.editor.configure(self.session,group=42)
        self.assertFalse(self.session.calls)

    def test_save_normalization_and_successful_readback_rollback(self):
        source=self.editor.snapshot(self.session.values());source.update(Widget6WidgetType=(0,),Widget6RestoreLevel=(123,))
        self.assertEqual(after(self.plan(source,group=42))['Widget6RestoreLevel'],(0,))
        source.update(Widget1WidgetType=(7,),Widget1WidgetByteValue1=(0xed,),Widget6WidgetType=(8,),Widget6WidgetByteValue1=(2,))
        self.assertEqual(after(self.plan(source,group=42))['Widget6WidgetByteValue1'],(0xea,))
        original=self.editor.snapshot(self.session.values());self.session.failure='KeySetsEnableGroup'
        with self.assertRaises(EdltApplyError) as caught:self.editor.configure(self.session,group=42)
        self.assertEqual(self.editor.snapshot(self.session.values()),original);self.assertTrue(caught.exception.details['rollback_verified'])
        original_set=self.session.set
        def drop_value(name,value):
            if name!='KeySetsEnableGroup':original_set(name,value)
        self.session.set=drop_value
        with self.assertRaises(EdltApplyError) as caught:self.editor.configure(self.session,group=42)
        self.assertIn('readback differs',str(caught.exception));self.assertEqual(self.editor.snapshot(self.session.values()),original)
        self.session.set=original_set
        result=self.editor.configure(self.session,group=42);self.assertTrue(result['verified']);self.assertFalse(result['saved'])

    def test_disconnect_primary_and_rollback_interruption_evidence(self):
        for failure in (KeyboardInterrupt('stop'),SystemExit('stop'),TimeoutError('lost')):
            session=Session(self.spec);calls=[]
            def fail(name,value):
                calls.append(name);session.current[name]=value;session.connected=False;raise failure
            session.set=fail
            if isinstance(failure,(KeyboardInterrupt,SystemExit)):
                with self.assertRaises(type(failure)) as caught:self.editor.configure(session,group=42)
                self.assertIs(caught.exception,failure);evidence=failure.edlt_page_control_evidence
                self.assertEqual(evidence['attempted_parameters'],calls);self.assertTrue(evidence['pp_state_uncertain']);self.assertFalse(evidence['saved'])
            else:
                with self.assertRaises(EdltApplyError) as caught:self.editor.configure(session,group=42)
                self.assertIn('Connection lost',caught.exception.rollback_errors[0])
            self.assertEqual(len(calls),1)
        first=RuntimeError('original SET failure');interrupt=KeyboardInterrupt('rollback stop');calls=[]
        def rollback(name,value):
            calls.append(name);raise first if len(calls)==1 else interrupt
        self.session.set=rollback
        with self.assertRaises(KeyboardInterrupt) as caught:self.editor.configure(self.session,group=42)
        self.assertIs(caught.exception,interrupt);self.assertEqual(len(calls),2)
        self.assertEqual(interrupt.edlt_page_control_evidence['original_error'],dict(type='RuntimeError',error=str(first)))
        self.assertEqual(interrupt.edlt_page_control_evidence['rollback_errors'],[])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),'Set original Toolkit for Page Control model acceptance')
class OriginalPageControlTests(unittest.TestCase):
    def test_original_all_group_values_cache_order_and_independent_controls(self):
        root=Path(__file__).resolve().parents[1];app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        if os.environ.get('CBUS_WINDOWS_BRIDGE')=='1':
            from research.windows_bridge import WindowsModelProbe
            output=WindowsModelProbe(root/'research/NativeEdltPageControlProbe.cs',app).run()
        else:
            with tempfile.TemporaryDirectory() as directory:
                Path(directory,'NativeEdltPageControlProbe.cs').write_bytes((root/'research/NativeEdltPageControlProbe.cs').read_bytes())
                result=subprocess.run(['docker','run','--rm','--network','none','-v',str(app)+':/input:ro','-v',directory+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',
                    'mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltPageControlProbe.cs && MONO_PATH=/input mono NativeEdltPageControlProbe.exe'],
                    capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            output=result.stdout
        rows=output.splitlines();self.assertEqual(len(rows),284)
        self.assertEqual(rows[0],'binding:-1:203:256:255:<Disabled>')
        self.assertEqual(rows[1:257],[f'set:{g}:{g}:{g}:True:56:0:0' for g in range(256)])
        expected=[]
        for groups in ((42,7),(7,42),()):
            joined=','.join(map(str,groups));choices=','.join(map(str,(255,*groups)))
            for group in (0,7,42,99,255):
                selected=group if group in groups else 255
                expected.append(f'cache:{joined}:{group}:{group}:{selected}:{selected}:True:list={choices}')
        self.assertEqual(rows[257:272],expected)
        self.assertEqual(rows[272:],[f'independent:{p}:{n}:{d}:42:203' for p in (56,127,136) for n in (0,1) for d in (0,30)])


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),
                     'Set native C-Gate, specifications and Toolkit for Page Control PP acceptance')
class NativePageControlTests(unittest.TestCase):
    def test_full_original_pp_raw_crc_absent_existing_metadata_and_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase,NativeProjects
        from cbus_toolkit.programming import Programmer
        from cbus_toolkit.edlt_scenes import EdltSceneTable,SceneDefinition,SceneItem
        root=Path(__file__).resolve().parents[1];app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve();spec=UnitSpecStore(specs).load('KEYGL5.xml');editor=EdltPageControl(spec)
        project='PAG'+uuid4().hex[:5].upper();network='//'+project+'/254';source='/db'+network+'/p/20'
        report=dict(passed=False,physical_device_verified=False,cases=[],
                    original_runtime='Windows .NET Framework x86' if os.environ.get('CBUS_WINDOWS_BRIDGE')=='1' else 'pinned Docker Mono')
        with tempfile.TemporaryDirectory() as directory:
            for name,path in (('NativeEdltPageControlProbe.cs',root/'research/NativeEdltPageControlProbe.cs'),('KEYGL5.xml',specs/'KEYGL5.xml')):Path(directory,name).write_bytes(path.read_bytes())
            def mono(command):
                result=subprocess.run(['docker','run','--rm','--network','none','-v',str(app)+':/input:ro','-v',directory+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',command],capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr);return result.stdout
            windows=None
            if os.environ.get('CBUS_WINDOWS_BRIDGE')=='1':
                from research.windows_bridge import WindowsModelProbe
                windows=WindowsModelProbe(root/'research/NativeEdltPageControlProbe.cs',app)
            else:mono('mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltPageControlProbe.cs')
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                db=NativeDatabase(client);projects=NativeProjects(client);programmer=Programmer(client);projects.operation('new',project)
                try:
                    db.create_network(project,254,'Page_Control_Fixture','Cni','127.0.0.1:1');db.create_unit(network,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL')
                    db.add(network,'application',56,'Lighting');db.add(network+'/56','group',42,'Keep_Page_Tag');projects.operation('save',project)
                    def applications():
                        reply=db.get(network,xml=True)
                        xml='\n'.join(line[4:] for line in reply.lines if line.startswith('347-'))
                        return tuple(ET.tostring(app,encoding='unicode') for app in ET.fromstring(xml).findall('Application'))
                    baseline=applications();self.assertEqual([ET.fromstring(a).findtext('Address') for a in baseline],['56'])
                    with programmer.load(network,source) as session:
                        session.set('ConfigVersionMajor','1');session.set('ConfigVersionMinor','0')
                        session.set('BacklightActiveBrightnessControlGroup','7');session.set('CorridorLinkingLinkGroup','42')
                        for widget in range(1,22):session.set(f'Widget{widget}WidgetType','0')
                        definitions=[SceneDefinition('primary',42,77,items=(SceneItem(42,127),) if n==0 else (),name_index=1) for n in range(8)]
                        EdltSceneTable(spec).configure(session,scenes=definitions);initial=editor.snapshot(session.values())
                        def case(label,**options):
                            before=editor.snapshot(session.values());plan=editor.plan(before,**options)
                            Path(directory,'values.tsv').write_text(''.join(k+'\t'+(v if isinstance(v,str) else ' '.join(hex(n) for n in v))+'\n' for k,v in before.items()))
                            selection=str(options['group']) if options.get('group') is not None else 'preserve'
                            if windows is not None:
                                out=windows.run(('KEYGL5.xml','values.tsv',selection),files={name:Path(directory,name).read_bytes() for name in ('KEYGL5.xml','values.tsv')})
                            else:out=mono('MONO_PATH=/input mono NativeEdltPageControlProbe.exe KEYGL5.xml values.tsv '+selection)
                            expected=editor.snapshot(dict(line[3:].split('\t',1) for line in out.splitlines() if line.startswith('pp:')))
                            self.assertEqual(after(plan),expected);self.assertEqual({k:expected[k] for k in editor.crcs(expected)},editor.crcs(expected))
                            result=editor.apply(session,plan);self.assertTrue(result['verified']);self.assertFalse(result['database_group_created'])
                            raw=bytes.fromhex(session.get_raw_data(0x130,3).lines[-1].split('RawData=')[1])
                            self.assertEqual(raw,bytes((7,plan.group,42)))
                            for field in ('ActivityDuration','NavWidgetType','TimeoutPage','PrimaryApplication','SecondaryApplication'):
                                self.assertEqual(expected[field],before[field])
                            self.assertEqual(applications(),baseline)
                            report['cases'].append(dict(label=label,group=plan.group,raw_hex=raw.hex(),crcs=editor.crcs(expected),
                                application_addresses=[int(ET.fromstring(a).findtext('Address')) for a in baseline],parameters_compared=len(expected)))
                            return expected
                        case('default-disabled')
                        for group in (0,1,7,254,255):case('absent-203-'+str(group),group=group)
                        session.set('ActivityDuration','0');session.set('NavWidgetType','0');case('single-page-no-standby',group=42)
                        session.set('ActivityDuration','30');session.set('NavWidgetType','1');session.set('PrimaryApplication','136');case('primary-136',group=7)
                        session.set('PrimaryApplication','56');case('preserved-reference')
                        # Explicit test-fixture metadata creation; the helper never performs this step.
                        db.add(network,'application',203,'Owned_Enable');db.add(network+'/203','group',42,'Keep_Enable_Tag')
                        baseline=applications();self.assertEqual([ET.fromstring(a).findtext('Address') for a in baseline],['56','203'])
                        case('existing-203-group42',group=42);case('existing-203-missing99',group=99);case('existing-203-disabled',group=255)
                        session.set('Widget1WidgetType','7');session.set('Widget1WidgetByteValue1','237');session.set('Widget6WidgetType','8');session.set('Widget6WidgetByteValue1','2')
                        final=case('stored-mra',group=42)
                        for name,value in initial.items():
                            if name.startswith('StaticTextString') or (name.startswith('Scene') and name!='ScenesCheckSum'):self.assertEqual(final[name],value)
                        self.assertEqual(final['Widget6WidgetByteValue1'],(234,));session.save_to_source()
                    for action in ('save','close','load'):projects.operation(action,project)
                    with programmer.load(network,source) as session:self.assertEqual(editor.snapshot(session.values()),final)
                    self.assertEqual(applications(),baseline)
                    self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                    report.update(passed=True,saved_reloaded=True,metadata_unchanged=True,absent_application_preserved=True,
                                  existing_group_metadata_preserved=True,network_state='new',network_opened=False)
                finally:
                    projects.operation('close',project);projects.operation('delete',project)
                    if os.environ.get('CBUS_EDLT_PAGE_CONTROL_REPORT'):Path(os.environ['CBUS_EDLT_PAGE_CONTROL_REPORT']).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':unittest.main()
