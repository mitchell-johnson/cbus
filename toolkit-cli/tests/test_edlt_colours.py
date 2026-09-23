"""Original eDLT palettes/control bindings and native colour PP acceptance."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_colours import EdltColours, COLOUR_OPTIONS, BRIGHTNESS_OPTIONS, GROUP_OPTIONS, FIELDS
from cbus_toolkit.unitspec import ParameterSpec, UnitSpecStore
from tests.test_edlt import fixture as base_fixture, Session

SCREEN = ('black','white','red','green','blue','cyan','magenta','yellow')
KEY = ('none','white','red','green','blue','cyan','magenta','yellow','orange')


def fixture():
    spec=base_fixture(); parameters=dict(spec.parameters)
    for name,address,bit,size,default in (
        ('LCDForeground',0x113,3,3,1),('LCDBackground',0x113,0,3,0),('OpaqueColourBits',0x113,6,2,3),
        ('ActivityDuration',0x11B,0,8,30),('IndicatorOnColour',0x11C,0,8,6),('IndicatorOffColour',0x11D,0,8,0),
        ('NavigationIndicatorColour',0x11E,0,8,1),('IdleIndicatorBrightness',0x11F,0,8,10),
        ('IdleBacklightBrightness',0x120,0,8,10),('ActiveIndicatorBrightness',0x121,0,8,128),('ActiveBacklightBrightness',0x122,0,8,255),
        ('IndicatorOnColourControlGroup',0x12B,0,8,255),('IndicatorOffColourControlGroup',0x12C,0,8,255),
        ('IndicatorIdleBrightnessControlGroup',0x12D,0,8,255),('BacklightIdleBrightnessControlGroup',0x12E,0,8,255),
        ('IndicatorActiveBrightnessControlGroup',0x12F,0,8,255),('BacklightActiveBrightnessControlGroup',0x130,0,8,255)):
        parameters[name]=ParameterSpec(name,'int','synthetic.xml',dict(Name=name,Type='int',Address=hex(address),
            BitAddress=str(bit),BitSize=str(size),DefaultValue=str(default)))
    return replace(spec,parameters=parameters)


def after(plan): return {**plan.expected,**plan.changes}


class ColourTests(unittest.TestCase):
    def setUp(self):
        self.spec=fixture(); self.editor=EdltColours(self.spec); self.session=Session(self.spec)

    def plan(self,current=None,**options):
        return self.editor.plan(self.session.values() if current is None else current,**options)

    def test_all_palette_options_brightness_boundaries_and_packed_preservation(self):
        original=self.editor.snapshot(self.session.values())
        for option,field,palette in (('text_colour','LCDForeground',SCREEN),('background_colour','LCDBackground',SCREEN),
                                    ('indicator_on_colour','IndicatorOnColour',KEY),('indicator_off_colour','IndicatorOffColour',KEY),
                                    ('page_key_colour','NavigationIndicatorColour',KEY)):
            for index,colour in enumerate(palette):
                plan=self.plan(**{option:colour});self.assertEqual(after(plan)[field],(index,))
                self.assertEqual(plan.as_dict()[option],colour);self.assertTrue(plan.as_dict()['colour_ui_canonical'][option])
                self.assertEqual(after(plan)['OpaqueColourBits'],(3,))
        for option,field in BRIGHTNESS_OPTIONS.items():
            for value in (0,1,127,128,254,255): self.assertEqual(after(self.plan(**{option:value}))[field],(value,))
        both=self.plan(text_colour='black',background_colour='black')
        self.assertEqual((after(both)['LCDForeground'],after(both)['LCDBackground']),((0,),(0,)))
        self.assertEqual(self.editor.snapshot(self.session.values()),original);self.assertFalse(self.session.calls)

    def test_exact_group_fixed_transitions_and_hidden_omitted_fields(self):
        for option,(field,fixed) in GROUP_OPTIONS.items():
            for group in (0,254,255):
                plan=self.plan(**{option:group}); current=after(plan)
                self.assertEqual(current[field],(group,));self.assertEqual(plan.editable[fixed],group==255)
                self.assertFalse(plan.as_dict()['group_metadata_verified']);self.assertFalse(plan.as_dict()['database_group_created'])
                self.assertEqual(plan.as_dict()['control_groups'][option],dict(application=56,group=group,enabled=group!=255))
                value='orange' if fixed.endswith('colour') else 255
                if group!=255:
                    with self.assertRaisesRegex(EdltError,'fixed mode'):self.plan(current,**{fixed:value})
                    with self.assertRaisesRegex(EdltError,'fixed mode'):self.plan(**{option:group,fixed:value})
                fixed_plan=self.plan(current,**{option:255,fixed:value})
                self.assertEqual(after(fixed_plan)[field],(255,));self.assertTrue(fixed_plan.editable[fixed])
                self.assertNotIn(FIELDS[fixed],self.plan(current).changes)
        self.assertFalse(self.session.calls)

    def test_idle_controls_disabled_and_outside_palette_values_retained(self):
        original=self.editor.snapshot(self.session.values());current={**original,'ActivityDuration':(0,)}
        for option,value in (('idle_screen_brightness',0),('idle_indicator_brightness',255),('idle_screen_group',255),('idle_indicator_group',0)):
            self.session.current=current
            with self.assertRaisesRegex(EdltError,'Standby'):self.editor.configure(self.session,**{option:value})
            self.assertFalse(self.session.calls)
        for name in ('IndicatorOnColour','IndicatorOffColour','NavigationIndicatorColour'):
            for raw in (9,254,255):
                source={**current,name:(raw,)};plan=self.plan(source,text_colour='red')
                option=next(key for key,(field,_) in COLOUR_OPTIONS.items() if field==name)
                self.assertEqual(after(plan)[name],(raw,));self.assertIsNone(plan.as_dict()[option])
                self.assertFalse(plan.as_dict()['colour_ui_canonical'][option]);self.assertEqual(plan.as_dict()['raw_values'][option],raw)
                self.assertFalse(plan.as_dict()['idle_controls_enabled'])
        self.assertFalse(self.plan(current).editable['idle_screen_group'])
        self.assertEqual(after(self.plan(current))['ActivityDuration'],(0,))

    def test_inputs_layout_identity_stale_and_forged_plans(self):
        for option in COLOUR_OPTIONS:
            for value in (True,1,'White','invalid'):
                with self.assertRaises(EdltError):self.plan(**{option:value})
        for option in (*BRIGHTNESS_OPTIONS,*GROUP_OPTIONS):
            for value in (-1,256,True,1.0,'42'):
                with self.assertRaises(EdltError):self.plan(**{option:value})
        params=dict(self.spec.parameters);param=params['LCDForeground'];params['LCDForeground']=replace(param,fields={**param.fields,'BitAddress':'4'})
        with self.assertRaisesRegex(EdltError,'layout'):EdltColours(replace(self.spec,parameters=params))
        params=dict(self.spec.parameters);del params['ActivityDuration']
        with self.assertRaisesRegex(EdltError,'layout'):EdltColours(replace(self.spec,parameters=params))
        for options in (dict(firmware='5.4.00'),dict(catalog_number='OTHER')):
            with self.assertRaises(EdltError):EdltColours(self.spec,**options)
        plan=self.plan(text_colour='yellow')
        for forged in (None,replace(plan,values={}),replace(plan,editable={}),replace(plan,primary_application=True),
                       replace(plan,activity_duration=0),replace(plan,values={**plan.values,'text_colour':False}),
                       replace(plan,editable={**plan.editable,'text_colour':1}),replace(plan,changes={})):
            with self.assertRaises(EdltError):self.editor.apply(self.session,forged)
        self.session.current['ActivityDuration']=(0,)
        with self.assertRaisesRegex(EdltError,'changed'):self.editor.apply(self.session,plan)
        self.session.identity['UnitType']='KEY4';self.session.values=lambda:(_ for _ in ()).throw(AssertionError('Do not read PP on identity mismatch'))
        with self.assertRaises(EdltError):self.editor.configure(self.session,text_colour='red')
        self.assertFalse(self.session.calls)

    def test_common_normalization_and_successful_rollback(self):
        current=self.editor.snapshot(self.session.values());current.update(Widget6WidgetType=(0,),Widget6RestoreLevel=(123,))
        plan=self.plan(current,text_colour='blue');self.assertEqual(after(plan)['Widget6RestoreLevel'],(0,))
        current.update(Widget1WidgetType=(7,),Widget1WidgetByteValue1=(0xed,),Widget6WidgetType=(8,),Widget6WidgetByteValue1=(2,))
        plan=self.plan(current,text_colour='blue');self.assertEqual(after(plan)['Widget6WidgetByteValue1'],(0xea,))
        original=self.editor.snapshot(self.session.values());self.session.failure='LCDForeground'
        with self.assertRaises(EdltApplyError) as caught:self.editor.configure(self.session,text_colour='red')
        self.assertEqual(self.editor.snapshot(self.session.values()),original);self.assertTrue(caught.exception.details['rollback_verified'])
        result=self.editor.configure(self.session,text_colour='red');self.assertTrue(result['verified']);self.assertFalse(result['saved'])

    def test_disconnect_primary_and_rollback_interruptions(self):
        for failure in (KeyboardInterrupt('stop'),SystemExit('stop'),TimeoutError('lost')):
            session=Session(self.spec);calls=[]
            def fail(name,value):
                calls.append(name);session.current[name]=value;session.connected=False;raise failure
            session.set=fail
            if isinstance(failure,(KeyboardInterrupt,SystemExit)):
                with self.assertRaises(type(failure)) as caught:self.editor.configure(session,text_colour='red')
                self.assertIs(caught.exception,failure);evidence=failure.edlt_colours_evidence
                self.assertEqual(evidence['attempted_parameters'],calls);self.assertTrue(evidence['pp_state_uncertain']);self.assertFalse(evidence['saved'])
            else:
                with self.assertRaises(EdltApplyError) as caught:self.editor.configure(session,text_colour='red')
                self.assertIn('Connection lost',caught.exception.rollback_errors[0])
            self.assertEqual(len(calls),1)
        first=RuntimeError('original SET failure');interrupt=KeyboardInterrupt('rollback stop');calls=[]
        def rollback(name,value):
            calls.append(name);raise first if len(calls)==1 else interrupt
        self.session.set=rollback
        with self.assertRaises(KeyboardInterrupt) as caught:self.editor.configure(self.session,text_colour='red')
        self.assertIs(caught.exception,interrupt);self.assertEqual(len(calls),2)
        self.assertEqual(interrupt.edlt_colours_evidence['original_error'],dict(type='RuntimeError',error=str(first)))
        self.assertEqual(interrupt.edlt_colours_evidence['rollback_errors'],[])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),'Set original Toolkit for colour model acceptance')
class OriginalColourTests(unittest.TestCase):
    def test_original_all_palettes_scalars_group_bindings_and_standby_getter(self):
        root=Path(__file__).resolve().parents[1];app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        from research.original_oracle import OriginalModelOracle, selected_backend
        if selected_backend() == 'windows':
            with OriginalModelOracle(root/'research/NativeEdltColoursProbe.cs', app, backend='windows', references=()) as oracle:
                original_output = oracle.run()
        else:
            with tempfile.TemporaryDirectory() as directory:
                Path(directory,'NativeEdltColoursProbe.cs').write_bytes((root/'research/NativeEdltColoursProbe.cs').read_bytes())
                result=subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',directory+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',
                    'mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltColoursProbe.cs && MONO_PATH=/input mono NativeEdltColoursProbe.exe'],
                    capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            original_output = result.stdout
        rows=original_output.splitlines();self.assertEqual(len(rows),2894)
        for prefix,palette in (('screen',SCREEN),('key',KEY)):
            self.assertEqual([r for r in rows if r.startswith(prefix+':')],[f'{prefix}:{n}:{name.capitalize()}' for n,name in enumerate(palette)])
        scalar_fields=('ActiveBacklightBrightness','ActiveIndicatorBrightness','IdleBacklightBrightness','IdleIndicatorBrightness',
                       'IndicatorOnColour','IndicatorOffColour','NavigationIndicatorColour','LCDForeground','LCDBackground')
        for field in scalar_fields:
            limit=256 if 'Brightness' in field else 8 if field.startswith('LCD') else 9
            self.assertEqual([r for r in rows if r.startswith('set:'+field+':')],[f'set:{field}:{n}:{n}:{n}:173' for n in range(limit)])
        for field,_ in GROUP_OPTIONS.values():
            self.assertEqual([r for r in rows if r.startswith('group:'+field+':')],
                [f'group:{field}:{n}:{n}:{n!=255}:{n}' for n in range(256)])
            self.assertIn(f'missing:{field}:99:True:255:255:False',rows)
        self.assertEqual([r for r in rows if r.startswith('standby:')],[f'standby:{n}:{n}' for n in range(256)])
        for value in (0,254,255):self.assertIn('fixed:'+str(value)+(':'+str(value==255))*6,rows)
        for field in ('IndicatorOnColour','IndicatorOffColour','NavigationIndicatorColour'):
            for value in (9,254,255):self.assertIn(f'stored:{field}:{value}:{value}',rows)


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),
                     'Set native C-Gate, specifications and original Toolkit for colour PP acceptance')
class NativeColourTests(unittest.TestCase):
    def test_full_original_pp_raw_crc_groups_metadata_and_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase,NativeProjects
        from cbus_toolkit.programming import Programmer
        from cbus_toolkit.edlt_scenes import EdltSceneTable,SceneDefinition,SceneItem
        root=Path(__file__).resolve().parents[1];app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve();spec=UnitSpecStore(specs).load('KEYGL5.xml');editor=EdltColours(spec)
        project='COL'+uuid4().hex[:5].upper();network='//'+project+'/254';source='/db'+network+'/p/20'
        report=dict(passed=False,physical_device_verified=False,cases=[])
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as directory:
            for name,path in (('NativeEdltColoursProbe.cs',root/'research/NativeEdltColoursProbe.cs'),('KEYGL5.xml',specs/'KEYGL5.xml')):Path(directory,name).write_bytes(path.read_bytes())
            def mono(command):
                result=subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',directory+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',command],capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr);return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltColoursProbe.cs', app, backend='windows', references=()) if backend == 'windows' else None
            if oracle is not None: self.addCleanup(oracle.close)
            else:mono('mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltColoursProbe.cs')
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                db=NativeDatabase(client);projects=NativeProjects(client);programmer=Programmer(client);projects.operation('new',project)
                try:
                    db.create_network(project,254,'Colour_Fixture','Cni','127.0.0.1:1');db.create_unit(network,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL')
                    db.add(network,'application',56,'Lighting');db.add(network+'/56','group',42,'Keep_Colour_Tag');projects.operation('save',project)
                    metadata=db.get(network+'/56',xml=True).lines
                    with programmer.load(network,source) as session:
                        session.set('ConfigVersionMajor','1');session.set('ConfigVersionMinor','0');session.set('ActivityDuration','30')
                        for widget in range(1,22):session.set(f'Widget{widget}WidgetType','0')
                        definitions=[SceneDefinition('primary',42,77,items=(SceneItem(42,127),) if n==0 else (),name_index=1) for n in range(8)]
                        # Original LoadScenes represents all eight slots. The fixture
                        # authors all eight explicitly before the direct save-stage comparison.
                        EdltSceneTable(spec).configure(session,scenes=definitions)
                        initial=editor.snapshot(session.values())
                        def case(label,**options):
                            before=editor.snapshot(session.values());plan=editor.plan(before,**options)
                            Path(directory,'values.tsv').write_text(''.join(k+'\t'+(v if isinstance(v,str) else ' '.join(hex(n) for n in v))+'\n' for k,v in before.items()))
                            Path(directory,'settings.tsv').write_text(''.join(FIELDS[name]+'\t'+str(plan.values[name])+'\n' for name,value in options.items() if value is not None))
                            if oracle is not None:
                                out = oracle.run(('KEYGL5.xml', 'values.tsv', 'settings.tsv'), files={name: Path(directory, name).read_bytes() for name in ('KEYGL5.xml', 'values.tsv', 'settings.tsv')})
                            else:out=mono('MONO_PATH=/input mono NativeEdltColoursProbe.exe KEYGL5.xml values.tsv settings.tsv')
                            expected=editor.snapshot(dict(line[3:].split('\t',1) for line in out.splitlines() if line.startswith('pp:')))
                            self.assertEqual(after(plan),expected);self.assertEqual({k:expected[k] for k in editor.crcs(expected)},editor.crcs(expected))
                            result=editor.apply(session,plan);self.assertTrue(result['verified']);self.assertFalse(result['database_group_created'])
                            raw=bytes.fromhex(session.get_raw_data(0x113,30).lines[-1].split('RawData=')[1])
                            self.assertEqual((raw[0]&7,(raw[0]>>3)&7),(expected['LCDBackground'][0],expected['LCDForeground'][0]))
                            for field in FIELDS.values():
                                layout=editor.codec.layout(field)
                                if layout.bit_size==8:self.assertEqual(raw[layout.address-0x113],expected[field][0])
                            self.assertEqual(db.get(network+'/56',xml=True).lines,metadata)
                            report['cases'].append(dict(label=label,options=options,raw_hex=raw.hex(),crcs=editor.crcs(expected),parameters_compared=len(expected)))
                            return expected
                        case('default')
                        case('minimum',text_colour='black',background_colour='black',indicator_on_colour='none',indicator_off_colour='none',page_key_colour='none',
                             active_screen_brightness=0,idle_screen_brightness=0,active_indicator_brightness=0,idle_indicator_brightness=0)
                        case('maximum',text_colour='yellow',background_colour='yellow',indicator_on_colour='orange',indicator_off_colour='orange',page_key_colour='orange',
                             active_screen_brightness=255,idle_screen_brightness=255,active_indicator_brightness=255,idle_indicator_brightness=255)
                        for group in (0,254):case('numeric-group-'+str(group),**{key:group for key in GROUP_OPTIONS})
                        case('return-fixed',**{key:255 for key in GROUP_OPTIONS},active_screen_brightness=1,idle_screen_brightness=128,
                             active_indicator_brightness=254,idle_indicator_brightness=127,indicator_on_colour='red',indicator_off_colour='green')
                        for field,value in (('IndicatorOnColour',9),('IndicatorOffColour',254),('NavigationIndicatorColour',255)):session.set(field,str(value))
                        case('omitted-outside-palette',text_colour='blue')
                        session.set('ActivityDuration','0');case('disabled-idle-preserved',background_colour='cyan')
                        before=editor.snapshot(session.values())
                        for options in (dict(idle_screen_brightness=0),dict(idle_indicator_group=255)):
                            with self.assertRaisesRegex(EdltError,'Standby'):editor.configure(session,**options)
                        self.assertEqual(editor.snapshot(session.values()),before)
                        session.set('Widget1WidgetType','7');session.set('Widget1WidgetByteValue1','237');session.set('Widget6WidgetType','8');session.set('Widget6WidgetByteValue1','2')
                        final=case('stored-mra',text_colour='white')
                        for name,value in initial.items():
                            if name.startswith('StaticTextString') or (name.startswith('Scene') and name!='ScenesCheckSum'):self.assertEqual(final[name],value)
                        self.assertEqual(final['Widget6WidgetByteValue1'],(234,));session.save_to_source()
                    for action in ('save','close','load'):projects.operation(action,project)
                    with programmer.load(network,source) as session:self.assertEqual(editor.snapshot(session.values()),final)
                    self.assertEqual(db.get(network+'/56',xml=True).lines,metadata)
                    self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                    report.update(passed=True,saved_reloaded=True,metadata_unchanged=True,network_state='new',network_opened=False)
                finally:
                    projects.operation('close',project);projects.operation('delete',project)
                    if os.environ.get('CBUS_EDLT_COLOURS_REPORT'):Path(os.environ['CBUS_EDLT_COLOURS_REPORT']).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':unittest.main()
