"""Independent original-model wake settings and closed native PP acceptance."""
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
from cbus_toolkit.edlt_activation import EdltActivation
from cbus_toolkit.unitspec import ParameterSpec, UnitSpecStore
from tests.test_edlt import fixture as base_fixture, Session


def fixture():
    spec=base_fixture();parameters=dict(spec.parameters)
    for name,address,kind,bit,size,default in (
        ('IgnoreFirstKeyPress',0x116,'bit',0,1,0),('Opaque116',0x116,'int',1,7,85),
        ('ProximityMode',0x117,'int',0,3,1),('Opaque117',0x117,'int',3,5,19),
        ('DeafultPage',0x11a,'int',0,4,1),('ToolsPageLocked',0x11a,'bit',4,1,1),
        ('TimeoutPage',0x11a,'int',5,2,2),('DefaultTempUnit',0x11a,'int',7,1,1),
        ('ActivityDuration',0x11b,'int',0,8,30),('ProximityGroup',0x123,'int',0,8,255),
        ('ProximityLevel',0x124,'int',0,8,255)):
        parameters[name]=ParameterSpec(name,kind,'synthetic.xml',dict(Name=name,Type=kind,Address=hex(address),
            BitAddress=str(bit),BitSize=str(size),DefaultValue=str(default)))
    return replace(spec,parameters=parameters)


def after(plan):return {**plan.expected,**plan.changes}


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.spec=fixture();self.editor=EdltActivation(self.spec);self.session=Session(self.spec)

    def plan(self,current=None,**options):
        return self.editor.plan(self.session.values() if current is None else current,**options)

    def test_modes_values_pages_and_independent_packed_fields(self):
        for mode,name in enumerate(('key-press','wake-unit','primary-event','trigger-event')):
            options=dict(wake_mode=name)
            if mode>=2:options.update(group=42,**({'level':127} if mode==2 else {'action':77}))
            plan=self.plan(**options);result=after(plan)
            self.assertEqual(result['ProximityMode'],(mode,));self.assertEqual(plan.as_dict()['wake_mode'],name)
            self.assertEqual(result['Opaque116'],(85,));self.assertEqual(result['Opaque117'],(19,))
            self.assertEqual(result['ToolsPageLocked'],(1,));self.assertEqual(result['DefaultTempUnit'],(1,))
            self.assertEqual((result['Opaque117'][0]<<3)|mode,(0x98,0x99,0x9a,0x9b)[mode])
            self.assertEqual(plan.as_dict()['event_application'],(None,None,56,202)[mode])
        for value in (0,1,127,128,254,255):
            for group in (0,254,255):
                plan=self.plan(wake_mode='primary-event',group=group,level=value)
                self.assertEqual((plan.group,plan.event_value),(group,value));self.assertTrue(plan.editable['level'])
                if group!=255:self.assertEqual(self.plan(wake_mode='trigger-event',group=group,action=value).event_value,value)
        for value,name in enumerate(('last-active','page-1')):
            plan=self.plan(activation_page=name);self.assertEqual(after(plan)['DeafultPage'],(value,))
            self.assertEqual(plan.as_dict()['activation_page'],name)
        self.assertFalse(self.session.calls)

    def test_all_visibility_dependencies_and_mode_two_unused_group(self):
        source=self.editor.snapshot(self.session.values())
        for timeout in range(4):
            for mode,name in enumerate(('key-press','wake-unit','primary-event','trigger-event')):
                current={**source,'TimeoutPage':(timeout,),'ProximityMode':(mode,),'ProximityGroup':(42,)}
                for option,value,enabled in (('ignore_first_key_press',True,timeout<2 and mode==0),
                    ('activation_page','last-active',timeout==2),('level',127,mode==2),('action',77,mode==3),('group',7,mode>=2)):
                    if enabled:self.assertTrue(self.plan(current,**{option:value}).editable[option])
                    else:
                        with self.assertRaisesRegex(EdltError,'hidden or disabled'):self.plan(current,**{option:value})
                for option,value in (('wake_mode','wake-unit'),('group',255),('level',0),('action',0),
                                     ('activation_page','last-active'),('ignore_first_key_press',False)):
                    with self.assertRaisesRegex(EdltError,'Standby'):self.plan({**current,'ActivityDuration':(0,)},**{option:value})
        self.assertEqual(self.plan(wake_mode='primary-event',group=255,level=255).event_value,255)
        with self.assertRaisesRegex(EdltError,'hidden or disabled'):self.plan(wake_mode='trigger-event',group=255,action=0)
        for mode in ('primary-event','trigger-event'):
            with self.assertRaisesRegex(EdltError,'mutually exclusive'):self.plan(wake_mode=mode,group=7,level=1,action=1)

    def test_retained_hidden_noncanonical_values_and_application_change(self):
        source=self.editor.snapshot(self.session.values())
        for mode in range(4,8):
            for page in (2,3,4):
                current={**source,'ProximityMode':(mode,),'DeafultPage':(page,),'IgnoreFirstKeyPress':(1,),
                         'ProximityGroup':(42,),'ProximityLevel':(173,),'ActivityDuration':(0,)}
                plan=self.plan(current);result=plan.as_dict()
                for field in ('ProximityMode','DeafultPage','IgnoreFirstKeyPress','ProximityGroup','ProximityLevel'):
                    self.assertEqual(after(plan)[field],current[field])
                self.assertIsNone(result['wake_mode']);self.assertFalse(result['wake_mode_ui_canonical'])
                self.assertIsNone(result['activation_page']);self.assertFalse(result['activation_page_ui_canonical'])
                with self.assertRaises(EdltError):self.plan({**current,'ActivityDuration':(30,)},group=7)
        for primary in (56,127,136):
            current={**source,'PrimaryApplication':(primary,),'ProximityMode':(2,),'ProximityGroup':(42,),'ProximityLevel':(173,)}
            plan=self.plan(current,wake_mode='trigger-event');result=plan.as_dict()
            self.assertEqual((plan.group,plan.event_value),(42,173));self.assertTrue(result['reference_application_changed'])
            self.assertEqual((result['previous_reference_application'],result['reference_application']),(primary,202))
            self.assertFalse(result['database_group_created']);self.assertFalse(result['database_group_verified']);self.assertFalse(result['database_action_verified'])
            back=self.plan(after(plan),wake_mode='primary-event');self.assertEqual(back.as_dict()['event_application'],primary)
            self.assertEqual(after(back)['Application'],(primary,57))

    def test_inputs_layout_identity_stale_and_canonical_plan(self):
        for name in ('group','level','action'):
            for value in (-1,256,True,1.0,'1'):
                with self.assertRaises(EdltError):self.plan(**{name:value})
        for option,value in (('wake_mode',0),('wake_mode','Wake'),('activation_page','page-2'),('activation_page',True),
                             ('ignore_first_key_press',1),('ignore_first_key_press','false')):
            with self.assertRaises(EdltError):self.plan(**{option:value})
        parameters=dict(self.spec.parameters);p=parameters['DeafultPage'];parameters['DeafultPage']=replace(p,fields={**p.fields,'BitAddress':'1'})
        with self.assertRaisesRegex(EdltError,'layout'):EdltActivation(replace(self.spec,parameters=parameters))
        parameters=dict(self.spec.parameters);del parameters['ActivityDuration']
        with self.assertRaisesRegex(EdltError,'layout'):EdltActivation(replace(self.spec,parameters=parameters))
        for options in (dict(firmware='5.4.00'),dict(catalog_number='OTHER')):
            with self.assertRaises(EdltError):EdltActivation(self.spec,**options)
        plan=self.plan(wake_mode='primary-event',group=42,level=173)
        for forged in (None,replace(plan,mode=True),replace(plan,event_value=False),replace(plan,page=True),
                       replace(plan,timeout_page=True),replace(plan,ignore_first_key_press=0),replace(plan,editable={}),
                       replace(plan,editable={**plan.editable,'group':1}),replace(plan,changes={}),replace(plan,options={'unknown':1})):
            with self.assertRaises(EdltError):self.editor.apply(self.session,forged)
        self.session.current['ActivityDuration']=(0,)
        with self.assertRaisesRegex(EdltError,'changed'):self.editor.apply(self.session,plan)
        self.session.identity['UnitType']='KEY4';self.session.values=lambda:(_ for _ in ()).throw(AssertionError('No PP read after identity mismatch'))
        with self.assertRaises(EdltError):self.editor.configure(self.session,wake_mode='wake-unit')
        self.assertFalse(self.session.calls)

    def test_save_normalization_success_and_fault_readback_rollback(self):
        source=self.editor.snapshot(self.session.values());source.update(Widget6WidgetType=(0,),Widget6RestoreLevel=(123,))
        self.assertEqual(after(self.plan(source))['Widget6RestoreLevel'],(0,))
        source.update(Widget1WidgetType=(7,),Widget1WidgetByteValue1=(0xed,),Widget6WidgetType=(8,),Widget6WidgetByteValue1=(2,))
        self.assertEqual(after(self.plan(source))['Widget6WidgetByteValue1'],(0xea,))
        original=self.editor.snapshot(self.session.values());self.session.failure='ProximityGroup'
        with self.assertRaises(EdltApplyError) as caught:self.editor.configure(self.session,wake_mode='primary-event',group=42,level=173)
        self.assertEqual(self.editor.snapshot(self.session.values()),original);self.assertTrue(caught.exception.details['rollback_verified'])
        original_set=self.session.set
        def drop_value(name,value):
            if name!='ProximityLevel':original_set(name,value)
        self.session.set=drop_value
        with self.assertRaises(EdltApplyError) as caught:self.editor.configure(self.session,wake_mode='primary-event',group=42,level=173)
        self.assertIn('readback differs',str(caught.exception));self.assertEqual(self.editor.snapshot(self.session.values()),original)
        self.session.set=original_set
        result=self.editor.configure(self.session,wake_mode='trigger-event',group=7,action=77)
        self.assertTrue(result['verified']);self.assertFalse(result['saved']);self.assertFalse(result['wake_event_verified'])

    def test_disconnect_primary_and_rollback_interruption_evidence(self):
        for failure in (KeyboardInterrupt('stop'),SystemExit('stop'),TimeoutError('lost')):
            session=Session(self.spec);calls=[]
            def fail(name,value):
                calls.append(name);session.current[name]=value;session.connected=False;raise failure
            session.set=fail
            if isinstance(failure,(KeyboardInterrupt,SystemExit)):
                with self.assertRaises(type(failure)) as caught:self.editor.configure(session,wake_mode='primary-event',group=42)
                self.assertIs(caught.exception,failure);evidence=failure.edlt_activation_evidence
                self.assertEqual(evidence['attempted_parameters'],calls);self.assertTrue(evidence['pp_state_uncertain']);self.assertFalse(evidence['saved'])
            else:
                with self.assertRaises(EdltApplyError) as caught:self.editor.configure(session,wake_mode='primary-event',group=42)
                self.assertIn('Connection lost',caught.exception.rollback_errors[0])
            self.assertEqual(len(calls),1)
        first=RuntimeError('original SET failure');interrupt=KeyboardInterrupt('rollback stop');calls=[]
        def rollback(name,value):
            calls.append(name);raise first if len(calls)==1 else interrupt
        self.session.set=rollback
        with self.assertRaises(KeyboardInterrupt) as caught:self.editor.configure(self.session,wake_mode='primary-event')
        self.assertIs(caught.exception,interrupt);self.assertEqual(len(calls),2)
        self.assertEqual(interrupt.edlt_activation_evidence['original_error'],dict(type='RuntimeError',error=str(first)))
        self.assertEqual(interrupt.edlt_activation_evidence['rollback_errors'],[])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),'Set original Toolkit for activation model acceptance')
class OriginalActivationTests(unittest.TestCase):
    def test_original_modes_guards_values_and_conditional_metadata(self):
        root=Path(__file__).resolve().parents[1];app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        from research.original_oracle import OriginalModelOracle, selected_backend
        if selected_backend() == 'windows':
            with OriginalModelOracle(root/'research/NativeEdltActivationProbe.cs', app, backend='windows', references=()) as oracle:
                original_output = oracle.run()
        else:
            with tempfile.TemporaryDirectory() as directory:
                Path(directory,'NativeEdltActivationProbe.cs').write_bytes((root/'research/NativeEdltActivationProbe.cs').read_bytes())
                result=subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',directory+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',
                    'mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltActivationProbe.cs && MONO_PATH=/input mono NativeEdltActivationProbe.exe'],
                    capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            original_output = result.stdout
        rows=original_output.splitlines();self.assertEqual(len(rows),422)
        self.assertEqual(rows[:5],['mode-option:1:Wake Unit','mode-option:2:Primary Event','mode-option:3:Trigger Event',
                                  'page-option:0:Last Active Page','page-option:1:Page 1'])
        expected=[]
        for mode in range(8):
            for timeout in range(4):
                for activity in (0,30):expected.append(':'.join(map(str,('guards',mode,timeout,activity,activity,int(mode!=0),
                    int(mode==0),mode>1,mode==2,mode==3,timeout==2,timeout<2 and mode==0))))
        self.assertEqual([r for r in rows if r.startswith('guards:')],expected)
        self.assertEqual([r for r in rows if r.startswith('level:')],[f'level:{n}:{n}:{n}' for n in range(256)])
        self.assertEqual([r for r in rows if r.startswith('page:')],[f'page:{n}:{n}:{n}' for n in range(5)])
        for mode in range(8):
            for value in (0,1):
                self.assertIn(f'radio-proximity:{mode}:{value}:{value}:42:173',rows)
                self.assertIn(f'radio-key:{mode}:{value}:{1-value}:42:173',rows)
        for primary in (56,127,136):
            for mode in range(4):
                app=202 if mode==3 else primary;allowed=(7,77) if mode==3 else (7,42)
                for group in (7,42,77,255):
                    selected=group if group in allowed else 255
                    self.assertIn(f'group:{primary}:{mode}:{group}:{app}:{group}:{selected}:{selected}:True:{selected!=255}:list=255,{allowed[0]},{allowed[1]}',rows)
        self.assertEqual([r for r in rows if r.startswith('switch:')],
                         ['switch:7:7:202:7:173','switch:42:42:202:255:173','switch:77:77:202:77:173','switch:255:255:202:255:173'])
        self.assertEqual(rows[-8:],['application-lists:255:56,57,127,136,48,95,96,126:255,57,127,136,48,95,96,126',
            'application-lists:57:56,127,136,48,95,96,126:255,57,127,136,48,95,96,126',
            'application-lists:136:56,57,127,48,95,96,126:255,57,127,136,48,95,96,126',
            *[f'application-set:{n}:{n}:136:0,1' for n in (48,95,96,127,136)]])


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),
                     'Set native C-Gate, specifications and Toolkit for activation PP acceptance')
class NativeActivationTests(unittest.TestCase):
    def test_full_original_pp_raw_crc_metadata_and_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase,NativeProjects
        from cbus_toolkit.programming import Programmer
        from cbus_toolkit.edlt_scenes import EdltSceneTable,SceneDefinition,SceneItem
        root=Path(__file__).resolve().parents[1];app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve();spec=UnitSpecStore(specs).load('KEYGL5.xml');editor=EdltActivation(spec)
        project='ACT'+uuid4().hex[:5].upper();network='//'+project+'/254';source='/db'+network+'/p/20'
        report=dict(passed=False,physical_device_verified=False,cases=[])
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as directory:
            for name,path in (('NativeEdltActivationProbe.cs',root/'research/NativeEdltActivationProbe.cs'),('KEYGL5.xml',specs/'KEYGL5.xml')):Path(directory,name).write_bytes(path.read_bytes())
            def mono(command):
                result=subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',directory+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',command],capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr);return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltActivationProbe.cs', app, backend='windows', references=()) if backend == 'windows' else None
            if oracle is not None: self.addCleanup(oracle.close)
            else:mono('mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltActivationProbe.cs')
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                db=NativeDatabase(client);projects=NativeProjects(client);programmer=Programmer(client);projects.operation('new',project)
                try:
                    db.create_network(project,254,'Activation_Fixture','Cni','127.0.0.1:1');db.create_unit(network,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL')
                    db.add(network,'application',56,'Lighting');db.add(network+'/56','group',42,'Keep_Activation_Tag');projects.operation('save',project)
                    def applications():
                        reply=db.get(network,xml=True)
                        xml='\n'.join(line[4:] for line in reply.lines if line.startswith('347-'))
                        return tuple(ET.tostring(app,encoding='unicode') for app in ET.fromstring(xml).findall('Application'))
                    # Unit PP changes appear in network XML; compare full app subtrees separately.
                    metadata_app=db.get(network+'/56',xml=True).lines
                    apps_before=applications()
                    self.assertEqual([ET.fromstring(app).findtext('Address') for app in apps_before],['56'])
                    with programmer.load(network,source) as session:
                        session.set('ConfigVersionMajor','1');session.set('ConfigVersionMinor','0');session.set('ActivityDuration','30')
                        for widget in range(1,22):session.set(f'Widget{widget}WidgetType','0')
                        definitions=[SceneDefinition('primary',42,77,items=(SceneItem(42,127),) if n==0 else (),name_index=1) for n in range(8)]
                        EdltSceneTable(spec).configure(session,scenes=definitions);initial=editor.snapshot(session.values())
                        def case(label,**options):
                            before=editor.snapshot(session.values());plan=editor.plan(before,**options)
                            Path(directory,'values.tsv').write_text(''.join(k+'\t'+(v if isinstance(v,str) else ' '.join(hex(n) for n in v))+'\n' for k,v in before.items()))
                            settings=[]
                            for option,value in options.items():
                                field={'wake_mode':'ProximityMode','group':'ProximityGroup','level':'ProximityLevel','action':'ProximityLevel',
                                       'activation_page':'DefaultPage','ignore_first_key_press':'IgnoreFirstKeyPress'}[option]
                                raw={'wake_mode':plan.mode,'activation_page':plan.page,'ignore_first_key_press':int(plan.ignore_first_key_press)}.get(option,value)
                                settings.append(field+'\t'+str(raw)+'\n')
                            Path(directory,'settings.tsv').write_text(''.join(settings))
                            if oracle is not None:
                                out = oracle.run(('KEYGL5.xml', 'values.tsv', 'settings.tsv'), files={name: Path(directory, name).read_bytes() for name in ('KEYGL5.xml', 'values.tsv', 'settings.tsv')})
                            else:out=mono('MONO_PATH=/input mono NativeEdltActivationProbe.exe KEYGL5.xml values.tsv settings.tsv')
                            expected=editor.snapshot(dict(line[3:].split('\t',1) for line in out.splitlines() if line.startswith('pp:')))
                            self.assertEqual(after(plan),expected);self.assertEqual({k:expected[k] for k in editor.crcs(expected)},editor.crcs(expected))
                            result=editor.apply(session,plan);self.assertTrue(result['verified']);self.assertFalse(result['database_group_created'])
                            raw=bytes.fromhex(session.get_raw_data(0x116,15).lines[-1].split('RawData=')[1])
                            self.assertEqual((raw[0]&1,raw[1]&7,raw[4]&15,raw[13],raw[14]),
                                (int(plan.ignore_first_key_press),plan.mode,plan.page,plan.group,plan.event_value))
                            for field in ('EnableLevelStore','EnableTimerFlash','EnableNightlightUserKey','EnableNightlightPageKey',
                                          'NightlightColour','EnableFanControlLevelWrap','ToolsPageLocked','TimeoutPage','DefaultTempUnit'):
                                self.assertEqual(expected[field],before[field])
                            self.assertEqual(db.get(network+'/56',xml=True).lines,metadata_app)
                            self.assertEqual(applications(),apps_before)
                            report['cases'].append(dict(label=label,options=options,raw_hex=raw.hex(),crcs=editor.crcs(expected),
                                event_application=result['event_application'],reference_application_changed=result['reference_application_changed'],parameters_compared=len(expected)))
                            return expected
                        case('default');case('last-active',activation_page='last-active');case('page-one',activation_page='page-1')
                        for timeout in (0,1):
                            session.set('TimeoutPage',str(timeout));case('key-press-'+str(timeout),wake_mode='key-press',ignore_first_key_press=bool(timeout))
                        case('primary-unused-maximum',wake_mode='primary-event',group=255,level=255)
                        case('primary-zero',group=0,level=0);case('primary-254',group=254,level=255)
                        case('trigger-retained',wake_mode='trigger-event');case('trigger-zero',group=7,action=0);case('trigger-maximum',group=77,action=255)
                        for primary in (127,136):
                            session.set('PrimaryApplication',str(primary));case('primary-'+str(primary),wake_mode='primary-event',group=42,level=173)
                        session.set('PrimaryApplication','56');session.set('ActivityDuration','0')
                        for mode in range(4,8):
                            session.set('ProximityMode',str(mode));session.set('DeafultPage',str(2+mode%3));case('omitted-stored-'+str(mode))
                        unchanged=editor.snapshot(session.values())
                        for options in (dict(wake_mode='wake-unit'),dict(group=255),dict(action=0),dict(activation_page='page-1')):
                            with self.assertRaisesRegex(EdltError,'Standby'):editor.configure(session,**options)
                        self.assertEqual(editor.snapshot(session.values()),unchanged)
                        session.set('ActivityDuration','30');session.set('TimeoutPage','2')
                        session.set('Widget1WidgetType','7');session.set('Widget1WidgetByteValue1','237');session.set('Widget6WidgetType','8');session.set('Widget6WidgetByteValue1','2')
                        final=case('stored-mra-wake-unit',wake_mode='wake-unit',activation_page='page-1')
                        for name,value in initial.items():
                            if name.startswith('StaticTextString') or (name.startswith('Scene') and name!='ScenesCheckSum'):self.assertEqual(final[name],value)
                        self.assertEqual(final['Widget6WidgetByteValue1'],(234,));session.save_to_source()
                    for action in ('save','close','load'):projects.operation(action,project)
                    with programmer.load(network,source) as session:self.assertEqual(editor.snapshot(session.values()),final)
                    self.assertEqual(db.get(network+'/56',xml=True).lines,metadata_app)
                    self.assertEqual(applications(),apps_before)
                    self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                    report.update(passed=True,saved_reloaded=True,metadata_unchanged=True,application_addresses=[56],
                                  absent_applications_preserved=[127,136,202],network_state='new',network_opened=False)
                finally:
                    projects.operation('close',project);projects.operation('delete',project)
                    if os.environ.get('CBUS_EDLT_ACTIVATION_REPORT'):Path(os.environ['CBUS_EDLT_ACTIVATION_REPORT']).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':unittest.main()
