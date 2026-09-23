"""Quick Status original controls, model, native full-PP/CRC and database persistence."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_quick_status import EdltQuickStatus, MODES, FIELDS, _levels
from cbus_toolkit.edlt_colours import KEY_COLOURS, SCREEN_COLOURS
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from tests.test_edlt import fixture as common_fixture, Session
from research.original_oracle import selected_backend
from research.original_source_oracle import OriginalSourceSetOracle

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:23a8bfba16d732eff819f71edeec551e84e576eab40a15ec9e97018f649fb568'


def windows_oracle(app):
    return OriginalSourceSetOracle((ROOT / 'research/NativeEdltQuickStatusProbe.cs', ROOT / 'research/NativeEdltCachedGroupProbe.cs'),
        app, entry_point='NativeEdltQuickStatusProbe', backend='windows', references=('eDLT.dll',), gui=True)

def fixture():
    base = common_fixture(); params = dict(base.parameters)
    for name, address, bit, size, default in (
        ('QuickStatusMode',0x116,3,3,0), ('QuickStatusGroup',0x125,0,8,255),
        ('QuickStatusColour1',0x126,0,8,2), ('QuickStatusColour2',0x127,0,8,7), ('QuickStatusColour3',0x128,0,8,3),
        ('QuickStatusLevel1',0x129,0,8,85), ('QuickStatusLevel2',0x12a,0,8,170), ('OpaqueQuickBits',0x116,0,3,5)):
        params[name] = ParameterSpec(name,'int','synthetic.xml',{'Name':name,'Type':'int','Address':hex(address),
            'BitAddress':str(bit),'BitSize':str(size),'DefaultValue':str(default)})
    return UnitSpec(base.filename,base.metadata,base.sources,params)


def mono(app, directory, command, specs=None):
    args=['docker','run','--rm','--network','none','-v',str(app)+':/input:ro','-v',str(directory)+':/work','-w','/work']
    if specs is not None: args += ['-v',str(specs)+':/spec:ro']
    result=subprocess.run(args+[IMAGE,'sh','-c',command],capture_output=True,text=True,timeout=90)
    if result.returncode: raise AssertionError(result.stdout+result.stderr)
    return result.stdout


def prepare_probe(folder, app):
    for name in ('NativeEdltQuickStatusProbe.cs','NativeEdltCachedGroupProbe.cs'):
        (folder/name).write_bytes((ROOT/'research'/name).read_bytes())
    mono(app,folder,'mcs -r:/input/CBusLogicModel.dll -r:/input/eDLT.dll -r:System.Xml.Linq -r:System.Drawing -r:System.Windows.Forms -main:NativeEdltQuickStatusProbe NativeEdltQuickStatusProbe.cs NativeEdltCachedGroupProbe.cs')


class QuickStatusTests(unittest.TestCase):
    def setUp(self):
        self.spec=fixture(); self.editor=EdltQuickStatus(self.spec); self.session=Session(self.spec)

    def test_modes_palettes_editability_groups_and_raw_preservation(self):
        original=self.editor.snapshot(self.session.values())
        for mode in MODES:
            palette=SCREEN_COLOURS if mode in ('background','text') else KEY_COLOURS
            for colour in palette:
                plan=self.editor.plan(original,mode=mode,group=254,low_colour=colour,middle_colour=colour,high_colour=colour)
                data=plan.as_dict(); after={**original,**plan.changes}
                self.assertEqual(after['OpaqueQuickBits'],(5,)); self.assertEqual(data['mode'],mode)
                self.assertEqual(data['raw_values']['low_colour'],palette.index(colour))
                self.assertTrue(data['group_and_threshold_controls_editable']); self.assertTrue(data['colour_controls_editable'])
                self.assertEqual(data['enabled'],mode!='off'); self.assertFalse(data['group_metadata_verified'])
                self.assertFalse(data['database_group_created']); self.assertFalse(data['saved'])
        for raw in range(8):
            source={**original,'QuickStatusMode':(raw,),'QuickStatusColour1':(8,)}
            plan=self.editor.plan(source); self.assertEqual(plan.values['mode'],raw)
            self.assertEqual(plan.values['low_colour'],8); self.assertEqual(plan.values['group'],255)
            self.assertEqual(plan.as_dict()['colour_ui_canonical']['low_colour'],raw<=1)
        self.assertEqual(self.editor.plan(source,mode='text').values['low_colour'],8)
        self.assertEqual(self.editor.plan(original,mode='off',low_threshold=170).values['high_threshold'],171)

    def test_literal_original_linked_threshold_vectors_and_batch_order(self):
        source=self.editor.snapshot(self.session.values())
        vectors=[(85,170,170,None,170,171),(85,170,None,85,84,85),(85,170,255,None,254,255),
                 (85,170,None,0,0,1),(85,85,86,None,86,86),(170,85,170,None,170,85),
                 (85,170,255,0,0,1),(85,85,255,0,1,1),(85,85,85,170,170,170),
                 (0,0,0,255,254,255),(255,255,255,255,255,255),(85,170,86,86,85,86)]
        for low,high,edit_low,edit_high,want_low,want_high in vectors:
            with self.subTest(vector=(low,high,edit_low,edit_high)):
                plan=self.editor.plan({**source,'QuickStatusLevel1':(low,),'QuickStatusLevel2':(high,)},
                                      low_threshold=edit_low,high_threshold=edit_high)
                self.assertEqual((plan.values['low_threshold'],plan.values['high_threshold']),(want_low,want_high))
                self.assertEqual(plan.as_dict()['threshold_edit_order'],['low_threshold','high_threshold'])

    def test_mra_and_terminator_normalization_preserves_stored_noncanonical_globals(self):
        source=self.editor.snapshot(self.session.values())
        for widget in range(1,22): source[f'Widget{widget}WidgetType']=(0,)
        source['Widget6RestoreLevel']=(123,)
        plan=self.editor.plan(source,mode='text')
        self.assertEqual(plan.as_dict()['normalization_changes'],{'Widget6WidgetType':[255],'Widget6RestoreLevel':[0]})
        source.update({'Widget1WidgetType':(7,),'Widget1WidgetByteValue1':(0xed,),
                       'Widget6WidgetType':(8,),'Widget6WidgetByteValue1':(2,)})
        plan=self.editor.plan(source,group=42)
        self.assertEqual(plan.mra_propagation.source_widget,1)
        self.assertEqual(plan.changes['Widget6WidgetByteValue1'],(0xea,))
        self.assertFalse(plan.mra_propagation.as_dict()['multiplexer_ui_canonical'])

    def test_validation_identity_schema_stale_and_forged_plans(self):
        for options in ({'mode':0},{'mode':True},{'mode':'screen'},{'group':255},{'group':True},{'group':-1},
            {'low_threshold':True},{'high_threshold':256},{'low_threshold':-1},{'low_colour':8},
            {'mode':'background','low_colour':'orange'},{'mode':'text','middle_colour':'none'},
            {'mode':'off','high_colour':'black'}):
            with self.subTest(options=options),self.assertRaises(EdltError): self.editor.plan(self.session.values(),**options)
        params=dict(self.spec.parameters); p=params['QuickStatusMode']; params[p.name]=replace(p,fields={**p.fields,'BitAddress':'2'})
        with self.assertRaises(EdltError): EdltQuickStatus(replace(self.spec,parameters=params))
        with self.assertRaises(EdltError): EdltQuickStatus(self.spec,firmware='5.4.00')
        plan=self.editor.plan(self.session.values(),mode='text')
        for forged in (replace(plan,values={**plan.values,'mode':True}),replace(plan,primary_application=True),
                       replace(plan,changes={**plan.changes,'OpaqueQuickBits':(0,)})):
            with self.assertRaises(EdltError): self.editor.apply(self.session,forged)
        self.session.identity['UnitType']='KEYGL4'
        with self.assertRaises(EdltError): self.editor.apply(self.session,plan)
        self.session.identity['UnitType']='KEYGL5'; self.session.current['QuickStatusGroup']=(4,)
        with self.assertRaises(EdltError): self.editor.apply(self.session,plan)
        self.assertFalse(self.session.calls)
        self.session.source='//LIVE/254/p/1'
        with self.assertRaises(EdltError): self.editor.configure(self.session,mode='off')
        self.assertFalse(self.session.calls)

    def test_rollback_disconnect_and_interruptions(self):
        original=self.editor.snapshot(self.session.values()); self.session.failure='QuickStatusColour1'
        with self.assertRaises(EdltApplyError) as caught: self.editor.configure(self.session,mode='page-key',low_colour='orange')
        self.assertTrue(caught.exception.details['rollback_verified']); self.assertEqual(self.editor.snapshot(self.session.values()),original)
        for error in (KeyboardInterrupt('first'),SystemExit(7),ConnectionError('lost')):
            session=Session(self.spec); calls=[]
            def fail(name,value):
                calls.append(name);session.current[name]=value;session.connected=False;raise error
            session.set=fail
            with self.assertRaises(type(error) if not isinstance(error,Exception) else EdltApplyError) as caught:
                self.editor.configure(session,mode='text')
            self.assertEqual(len(calls),1)
            if not isinstance(error,Exception):
                self.assertIs(caught.exception,error);self.assertEqual(error.edlt_quick_status_evidence['attempted_parameters'],calls)
                self.assertTrue(error.edlt_quick_status_evidence['pp_state_uncertain'])
            else: self.assertFalse(caught.exception.details['rollback_verified'])

    def test_interrupted_rollback_retains_original(self):
        original=RuntimeError('SET partial');interrupted=KeyboardInterrupt('recovery');calls=[]
        def fail(name,value):
            calls.append(name)
            if len(calls)==1: self.session.current[name]=value;raise original
            raise interrupted
        self.session.set=fail
        with self.assertRaises(KeyboardInterrupt) as caught: self.editor.configure(self.session,mode='text')
        self.assertIs(caught.exception,interrupted);self.assertEqual(len(calls),2)
        self.assertEqual(interrupted.edlt_quick_status_evidence['original_error'],{'type':'RuntimeError','error':str(original)})


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),'Set original Toolkit DLLs for Quick Status controls')
class OriginalQuickStatusTests(unittest.TestCase):
    def test_actual_linked_controls_bound_group_and_palette_model(self):
        app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        backend = selected_backend()
        with tempfile.TemporaryDirectory() as directory:
            if backend == 'windows':
                with windows_oracle(app) as oracle:
                    output = oracle.run()
            else:
                folder=Path(directory);prepare_probe(folder,app)
                output=mono(app,folder,'MONO_PATH=/input xvfb-run -a mono NativeEdltQuickStatusProbe.exe')
        editor=EdltQuickStatus(fixture());source=editor.snapshot(Session(fixture()).values()); counts={}
        for line in output.splitlines():
            kind=line.split(':')[0];counts[kind]=counts.get(kind,0)+1
            if kind=='single':
                before,unused,after,events=line[len('single:'):].split(':')
                low,high,which,request=map(int,before.split(','))
                self.assertEqual(_levels(low,high,request if which==0 else None,request if which==1 else None),
                                 tuple(map(int,after.split(',')[-2:])))
                if 0<=request<=255:
                    plan=editor.plan({**source,'QuickStatusLevel1':(low,),'QuickStatusLevel2':(high,)},
                        **{('low_threshold' if which==0 else 'high_threshold'):request})
                    self.assertEqual((plan.values['low_threshold'],plan.values['high_threshold']),tuple(map(int,after.split(',')[-2:])))
            elif kind=='levels':
                _,before,request,after=line.split(':');low,high=map(int,before.split(','));edit_low,edit_high=map(int,request.split(','))
                plan=editor.plan({**source,'QuickStatusLevel1':(low,),'QuickStatusLevel2':(high,)},low_threshold=edit_low,high_threshold=edit_high)
                self.assertEqual((plan.values['low_threshold'],plan.values['high_threshold']),tuple(map(int,after.split(','))))
            elif kind=='palette':
                parts=line.split(':');initial,target,colour=map(int,parts[1].split(','))
                self.assertEqual(int(parts[3].split(',')[0]),colour)
                self.assertEqual(parts[-2],'model-choices='+','.join(map(str,range(8 if target>1 else 9))))
            elif kind=='group':
                self.assertIn(':enabled=True:',line)
                self.assertNotIn('255',line.split(':choices=')[1])
        self.assertEqual({key:counts[key] for key in ('single','levels','palette','group','choices')},
                         {'single':168,'levels':49,'palette':60,'group':9,'choices':3})
        self.assertIn('group:255,0,254,7:7:pp=7:enabled=True:selected=7:choices=0,254,7',output)
        self.assertIn('group:42,7:99:pp=255:enabled=True:selected=:choices=42,7',output)
        runtime=ROOT/'research/runtime';runtime.mkdir(parents=True,exist_ok=True)
        (runtime/'edlt-quick-status-original-controls.txt').write_text(output)
        if os.environ.get('CBUS_EDLT_QUICK_STATUS_VECTOR_REPORT'):
            path=Path(os.environ['CBUS_EDLT_QUICK_STATUS_VECTOR_REPORT']);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps({'passed': True, 'original_backend': backend, 'counts': counts, 'output': output}, indent=2) + '\n')


@unittest.skipUnless(all(os.environ.get(name) for name in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),
                     'Set native C-Gate, specs and original Toolkit for Quick Status acceptance')
class NativeQuickStatusTests(unittest.TestCase):
    def test_original_full_pp_crc_raw_and_database_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects, NativeDatabase
        from cbus_toolkit.programming import Programmer
        app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent;specs=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve()
        editor=EdltQuickStatus(UnitSpecStore(specs).load('KEYGL5.xml'))
        project='QS'+uuid4().hex[:6].upper();network='//'+project+'/254';source='/db'+network+'/p/20'
        report={'passed':False,'scope':'Original Quick Status model, linked controls, full PP/CRC and database only','cases':[]}
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            oracle = windows_oracle(app) if backend == 'windows' else None
            if oracle is not None:
                self.addCleanup(oracle.close)
            else:
                folder=Path(directory);prepare_probe(folder,app)
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                projects,database=NativeProjects(client),NativeDatabase(client);projects.operation('new',project)
                try:
                    database.create_network(project,254,'Quick_Status_Fixture','Cni','127.0.0.1:1')
                    database.create_unit(network,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL');projects.operation('save',project)
                    with Programmer(client).load(network,source) as session:
                        for widget in range(1,22): session.set(f'Widget{widget}WidgetType','0')
                        for widget in range(6,22):session.set(f'Widget{widget}RestoreLevel',str(100+widget))
                        for scene in range(1,9):session.set(f'Scene{scene}StartAddress','255')
                        session.set('ConfigVersionMajor','1');session.set('ConfigVersionMinor','0')
                        original=editor.snapshot(session.values())
                        def case(label,**options):
                            before=editor.snapshot(session.values());plan=editor.plan(before,**options)
                            (folder/'values.tsv').write_text(''.join(name+'\t'+(value if isinstance(value,str) else ' '.join(hex(n) for n in value))+'\n' for name,value in before.items()))
                            arguments=[]
                            palette=SCREEN_COLOURS if plan.values['mode']>1 else KEY_COLOURS
                            for name in ('mode','group','low_threshold','high_threshold','low_colour','middle_colour','high_colour'):
                                value=options.get(name)
                                arguments.append('keep' if value is None else str(MODES.index(value) if name=='mode' else palette.index(value) if name.endswith('_colour') else value))
                            if oracle is not None:
                                output = oracle.run(('KEYGL5.xml', 'values.tsv', *arguments),
                                    files={'KEYGL5.xml': (specs / 'KEYGL5.xml').read_bytes(), 'values.tsv': (folder / 'values.tsv').read_bytes()})
                            else:
                                output=mono(app,folder,'MONO_PATH=/input xvfb-run -a mono NativeEdltQuickStatusProbe.exe /spec/KEYGL5.xml values.tsv '+' '.join(arguments),specs)
                            observed=dict(line[3:].split('\t',1) for line in output.splitlines() if line.startswith('pp:'))
                            self.assertEqual(editor.snapshot(observed),{**before,**plan.changes})
                            self.assertTrue(editor.apply(session,plan)['verified'])
                            raw=bytes.fromhex(session.get_raw_data(0x125,6).lines[-1].split('RawData=')[1])
                            flag=bytes.fromhex(session.get_raw_data(0x116,1).lines[-1].split('RawData=')[1])[0]
                            self.assertEqual(raw,bytes(plan.values[name] for name in ('group','low_colour','middle_colour','high_colour','low_threshold','high_threshold')))
                            self.assertEqual((flag>>3)&7,plan.values['mode'])
                            report['cases'].append({'label':label,'raw_hex':raw.hex(),'flags_hex':f'{flag:02x}',
                                'parameters_compared':len(observed),'crcs':{key:list(value) for key,value in editor.crcs({**before,**plan.changes}).items()}})
                            return plan
                        for mode in MODES:
                            palette=SCREEN_COLOURS if mode in ('background','text') else KEY_COLOURS
                            for colour in (palette[0],palette[-1]):
                                case(mode+'-'+colour,mode=mode,group=0 if colour==palette[0] else 254,
                                     low_colour=colour,middle_colour=colour,high_colour=colour,low_threshold=0,high_threshold=255)
                        for low,high in ((85,170),(85,85),(0,0),(255,255),(170,85)):
                            for edit_low,edit_high in ((170,85),(255,0),(86,86)):
                                session.set('QuickStatusLevel1',str(low));session.set('QuickStatusLevel2',str(high))
                                case(f'linked-{low}-{high}-{edit_low}-{edit_high}',low_threshold=edit_low,high_threshold=edit_high)
                        session.set('QuickStatusMode','7');session.set('QuickStatusColour1','8');session.set('QuickStatusGroup','255')
                        plan=case('omitted-raw',high_colour='red');self.assertEqual(plan.values['mode'],7)
                        plan=case('mode-transition-model-preserves-orange',mode='text');self.assertEqual(plan.values['low_colour'],8)
                        for widget,kind,control in ((1,7,0xed),(6,8,2),(7,9,0)):
                            session.set(f'Widget{widget}WidgetType',str(kind));session.set(f'Widget{widget}WidgetByteValue1',str(control))
                        plan=case('stored-mra-noncanonical-propagation',mode='off')
                        self.assertEqual(plan.changes['Widget6WidgetByteValue1'],(0xea,))
                        final=editor.snapshot(session.values())
                        for name,value in original.items():
                            if name.startswith('StaticTextString') or (name.startswith('Scene') and name!='ScenesCheckSum'):self.assertEqual(final[name],value)
                        session.save_to_source()
                    for action in ('save','close','load'):projects.operation(action,project)
                    with Programmer(client).load(network,source) as session:self.assertEqual(editor.snapshot(session.values()),final)
                    self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                    report.update(passed=True,saved_reloaded=True,physical_device_verified=False,windows_palette_transition_verified=False)
                finally:
                    projects.operation('close',project);projects.operation('delete',project)
        path=Path(os.environ.get('CBUS_EDLT_QUICK_STATUS_REPORT', ROOT/'research/runtime/edlt-quick-status-report.json'));path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,indent=2)+'\n')
