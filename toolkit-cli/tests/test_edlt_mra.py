"""Original MRA record vectors and shared global propagation."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from cbus_toolkit.edlt import EdltApplyError, _field
from cbus_toolkit.edlt_mra import EdltMRAWidget, MRA_WIDGET_TYPES, MRA_VARIANTS, BUILTIN_ICON_INDICES
from tests.test_edlt_hvac import fixture
from tests.test_edlt import Session


from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_mra import normalize_mra_globals


def globals_fixture():
    source={f'Widget{i}WidgetType':(0,) for i in range(1,22)}
    for widget,kind,control in ((8,8,0x58),(10,9,0xb8)):
        source[f'Widget{widget}WidgetType']=(kind,)
        source[f'Widget{widget}WidgetByteValue1']=(control,)
    return source


class MRAPropagationTests(unittest.TestCase):
    def test_original_first_existing_values_before_new_earlier_record(self):
        original=globals_fixture(); current={**original,'Widget6WidgetType':(7,),'Widget6WidgetByteValue1':(5,)}
        plan=normalize_mra_globals(current,source=original)
        self.assertEqual((plan.multiplexer,plan.zone,plan.source_widget),(2,4,8))
        self.assertEqual(plan.widgets,(6,8,10))
        self.assertEqual(dict(plan.changes),{'Widget6WidgetByteValue1':(0x5d,),'Widget10WidgetByteValue1':(0x58,)})
        self.assertEqual(original,globals_fixture())
        self.assertEqual(normalize_mra_globals({**current,**plan.changes}).changes,{})

    def test_all24_literal_global_pairs_preserve_status_bits(self):
        current=globals_fixture(); current.update({'Widget6WidgetType':(7,),'Widget6WidgetByteValue1':(5,)})
        for mux in range(1,4):
            for zone in range(1,9):
                plan=normalize_mra_globals(current,multiplexer=mux,zone=zone)
                final={**current,**plan.changes}; upper=(mux-1)*64+(zone-1)*8
                self.assertEqual(final['Widget6WidgetByteValue1'],(upper+5,))
                self.assertEqual(final['Widget8WidgetByteValue1'],(upper,))
                self.assertEqual(final['Widget10WidgetByteValue1'],(upper,))
                self.assertTrue(all(name.endswith('WidgetByteValue1') for name in plan.changes))

    def test_no_widgets_and_invalid_first_multiplexer_require_explicit_repair(self):
        empty={f'Widget{i}WidgetType':(0,) for i in range(1,22)}
        plan=normalize_mra_globals(empty)
        self.assertEqual((plan.multiplexer,plan.zone,plan.source_widget,plan.widgets,dict(plan.changes)),(1,1,None,(),{}))
        current=globals_fixture();current['Widget8WidgetByteValue1']=(0xff,)
        with self.assertRaisesRegex(EdltError,'explicit'):normalize_mra_globals(current)
        fixed=normalize_mra_globals(current,multiplexer=3)
        self.assertEqual((fixed.multiplexer,fixed.zone),(3,8))
        self.assertEqual(fixed.changes['Widget8WidgetByteValue1'],(0xbf,))
        for settings in ({'multiplexer':True},{'zone':True},{'multiplexer':0},{'multiplexer':4},{'zone':0},{'zone':9}):
            with self.subTest(settings=settings),self.assertRaises(EdltError):normalize_mra_globals(empty,**settings)
        for bad in ({}, {'Widget1WidgetType':(7,)}, {**empty,'Widget8WidgetType':(8,),'Widget8WidgetByteValue1':(True,)}):
            with self.assertRaises(EdltError):normalize_mra_globals(bad)


DEFAULTS = {
 'zone-control':'07001E1D0000000F10030DFFFF00000000000000000000000000000000000000',
 'source-select':'080088880000000000FF3F000000000000000000000000000000000000000000',
 'source-control':'09008A8A000000FF000000000000000000000000000000000000000000000000'}
ZONE_CUSTOM='07051E1D0000030F100F0D3F3E00000000000000000000000000000000000000'


def after(plan): return {**plan.expected,**plan.changes}


class MRAWidgetTests(unittest.TestCase):
    def setUp(self):
        self.editor=EdltMRAWidget(fixture());self.session=Session(self.editor.spec)

    def plan(self,current=None,**options):
        settings=dict(page=1,position=1,kind='zone-control');settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current,**settings)

    def test_three_original_defaults_same_type_and_opaque_preservation(self):
        for kind,literal in DEFAULTS.items():
            with self.subTest(kind=kind):
                plan=self.plan(kind=kind);self.assertEqual(plan.record.hex().upper(),literal)
                self.assertFalse(self.plan(after(plan),kind=kind).changes)
                current=after(plan);current['Widget6RestoreLevel']=(155,);current[_field(6,31)]=(201,)
                retained=self.plan(current,kind=kind)
                self.assertEqual(retained.restore_level,155);self.assertEqual(retained.record[31],201)
                self.assertFalse(retained.changes.keys()-self.editor.crcs(current).keys())
                self.assertFalse(plan.as_dict()['audio_control_sent'])
        original=self.editor.snapshot(self.session.values())
        for i in range(1,32):original[_field(6,i)]=(i,)
        for kind in DEFAULTS:
            plan=self.plan(original,kind=kind)
            self.assertEqual(plan.record[4:6],bytes((4,5)));self.assertEqual(plan.record[13:],bytes(range(13,32)))
        source=dict(original);source['StaticTextString11']=tuple(b'Source'.ljust(64,b'\0'))
        reuse=self.plan(source,kind='source-select')
        self.assertEqual(reuse.default_status_allocation.index,11);self.assertTrue(reuse.default_status_allocation.reused)

    def test_zone_variants_macros_status_and_hidden_controls(self):
        custom=self.plan(variant='balance',ramp_seconds=1020,label_text='Kitchen',status_type='static',status_text='Audio')
        self.assertEqual(custom.record.hex().upper(),ZONE_CUSTOM)
        for variant,value in MRA_VARIANTS['zone-control'].items():
            self.assertEqual(self.plan(after(custom),variant=variant).record[6],value)
        for status,value in [('blank',0),('level',1),('percent',2),('bar',3),('static',5)]:
            plan=self.plan(after(custom),status_type=status)
            self.assertEqual(plan.record[1]&7,value);self.assertEqual(plan.record[12],62)
        nudge=self.plan(after(custom),key_mode='nudge');self.assertEqual(nudge.record[7:9],bytes((21,22)))
        self.assertEqual(nudge.record[9:11],bytes((15,13)))
        with self.assertRaisesRegex(EdltError,'hidden'):self.plan(after(nudge),ramp_seconds=4)
        current=after(custom);current[_field(6,7)]=(254,);current[_field(6,8)]=(253,)
        repaired=self.plan(current);self.assertTrue(repaired.macro_normalized);self.assertEqual(repaired.record[7:9],bytes((15,16)))
        for settings in ({'status_text':'Hidden'},{'status_index':0}):
            with self.assertRaisesRegex(EdltError,'hidden'):self.plan(**settings)

    def test_source_variants_all49_pairs_and_hidden_bytes(self):
        fresh=self.plan(kind='source-select')
        for first in range(1,8):
            for second in range(1,8):
                plan=self.plan(after(fresh),kind='source-select',variant='two-absolute',source1=first,source2=second)
                self.assertEqual(plan.record[6:9],bytes((2,first-1,second-1)))
        hidden=after(fresh);hidden[_field(6,7)]=(201,);hidden[_field(6,8)]=(202,)
        self.assertEqual(self.plan(hidden,kind='source-select').record[7:9],bytes((201,202)))
        for settings in ({'source1':1},{'source2':1},{'status_text':'Hidden'}):
            with self.assertRaisesRegex(EdltError,'hidden'):self.plan(after(fresh),kind='source-select',**settings)
        with self.assertRaisesRegex(EdltError,'existing absolute'):self.plan(hidden,kind='source-select',variant='one-absolute')
        repaired=self.plan(hidden,kind='source-select',variant='one-absolute',source1=7,status_text='Source')
        self.assertEqual(repaired.record[7:9],bytes((6,202)))
        for variant,value in MRA_VARIANTS['source-control'].items():
            self.assertEqual(self.plan(kind='source-control',variant=variant).record[6],value)

    def test_text_allocation_order_hidden_refs_blank_dedup_and_indexes(self):
        selected=self.plan(kind='source-select',variant='two-absolute',label_text='Music',status_text='Track')
        self.assertEqual(selected.default_status_allocation.index,63)
        self.assertEqual(selected.label_allocation.index,62);self.assertEqual(selected.status_allocation.index,61)
        hidden=self.plan(after(selected),kind='source-select',variant='next-previous')
        self.assertTrue({61,62}.issubset(self.editor.common.static_references(after(hidden))))
        same=self.plan(kind='source-select',variant='one-absolute',label_text='Source',status_text='Source')
        self.assertEqual(same.record[9:11],bytes((63,63)))
        blank=self.plan(after(selected),kind='source-select',label_text='',status_text='  ')
        self.assertEqual(blank.record[9:11],bytes((255,255)))
        explicit=self.plan(after(selected),kind='source-select',label_index=0,status_index=63)
        self.assertEqual(explicit.record[9:11],bytes((0,63)))
        for bad in (-1,64,254,256,True):
            with self.assertRaises(EdltError):self.plan(label_index=bad)

    def test_profile_and_required_global_layout_are_exact(self):
        for settings in ({'catalog_number':'5085EDL'},{'firmware':'5.4.00'}):
            with self.assertRaises(EdltError):EdltMRAWidget(self.editor.spec,**settings)
        parameters=dict(self.editor.spec.parameters);parameter=parameters['UseBigIcon']
        parameters['UseBigIcon']=replace(parameter,fields={**parameter.fields,'BitAddress':'3'})
        with self.assertRaisesRegex(EdltError,'UseBigIcon'):EdltMRAWidget(replace(self.editor.spec,parameters=parameters))

    def test_transitional_status_capacity_counts_real_unused_label_sentinel(self):
        for count in (61,62):
            current=self.editor.snapshot(self.session.values())
            for w in range(1,22):current[_field(w)]=(0,)
            index=0
            for w in range(7,22):
                current[_field(w)]=(16,);current[_field(w,1)]=(5,)
                for b in range(10,14):current[_field(w,b)]=(index,);index+=1
            current[_field(5)]=(12,)
            for b in (10,11,13):current[_field(5,b)]=(count-1 if b==11 else 60,)
            current[_field(6,10)]=(200,)
            before=dict(current)
            if count==61:
                plan=self.plan(current,kind='source-select')
                self.assertEqual(plan.record[9:11],bytes((255,63)))
                self.assertEqual(plan.default_status_allocation.used_indices,tuple([*range(61),200,255]))
            else:
                with self.assertRaisesRegex(EdltError,'full'):self.plan(current,kind='source-select')
            self.assertEqual(current,before)

    def test_icon_choices_coupling_and_hidden_display_setting(self):
        for icon in sorted(BUILTIN_ICON_INDICES):
            for kind in ('source-select','source-control'):
                plan=self.plan(kind=kind,on_icon=icon)
                self.assertEqual(plan.record[2:4],bytes((icon,icon)))
        separate=self.plan(on_icon=0,off_icon=252);self.assertEqual(separate.record[2:4],bytes((0,252)))
        for icon in (39,127,142,251,255,True):
            with self.assertRaises(EdltError):self.plan(on_icon=icon)
        current=self.editor.snapshot(self.session.values());current['UseBigIcon']=(0,)
        with self.assertRaisesRegex(EdltError,'UseBigIcon'):self.plan(current,on_icon=0)
        self.assertEqual(self.plan(current).record[2:4],bytes((30,29)))

    def test_page_locations_globals_and_first_existing_before_new_earlier(self):
        for mode,pages,positions in [('single',range(1,2),range(1,6)),('multiple',range(1,5),range(1,5))]:
            for page in pages:
                for position in positions:
                    plan=self.plan(page=page,position=position,page_mode=mode)
                    self.assertEqual(plan.widget,6+(page-1)*4+position-1)
        later=self.plan(position=3,kind='source-control',multiplexer=2,zone=4)
        earlier=self.plan(after(later),kind='zone-control',status_type='static')
        self.assertEqual(earlier.propagation.source_widget,8);self.assertEqual(earlier.record[1],93)
        globalplan=self.editor.plan_globals(after(earlier),multiplexer=3,zone=8)
        final=after(globalplan)
        self.assertEqual(final[_field(6,1)],(189,));self.assertEqual(final[_field(8,1)],(184,))
        self.assertIsNone(globalplan.record);self.assertEqual(globalplan.action,'globals')
        for settings in ({'page':0},{'page':2},{'position':6},{'page':True},{'multiplexer':4},{'zone':9}):
            with self.assertRaises(EdltError):self.plan(**settings)
        with self.assertRaises(EdltError):self.editor.plan_globals(self.session.values(),multiplexer=1)

    def test_canonical_stale_identity_rollback_and_connection_loss(self):
        plan=self.plan(label_text='Audio')
        for forged in (replace(plan,record=b'\0'*32),replace(plan,changes={}),replace(plan,widget=True),replace(plan,macro_normalized=1)):
            with self.assertRaises(EdltError):self.editor.apply(self.session,forged)
        self.assertFalse(self.session.calls)
        self.session.failure='WidgetsCRC'
        with self.assertRaises(EdltApplyError) as caught:self.editor.apply(self.session,plan)
        self.assertTrue(caught.exception.details['rollback_verified'])
        self.assertEqual(self.editor.snapshot(self.session.values()),dict(plan.expected))
        self.session.identity['FirmwareVersion']='5.4.00'
        with self.assertRaises(EdltError):self.editor.apply(self.session,plan)
        self.session.identity['FirmwareVersion']='5.5.00'
        self.session.current['Widget6RestoreLevel']='1'
        with self.assertRaisesRegex(EdltError,'changed'):self.editor.apply(self.session,plan)
        self.session.current['Widget6RestoreLevel']='0'
        self.assertTrue(self.editor.apply(self.session,plan)['verified'])
        nextplan=self.plan(self.session.values(),label_text='Changed')
        calls=[]
        def fail(name,value):
            calls.append(name);self.session.connected=False;raise OSError('Disconnected')
        self.session.set=fail
        with self.assertRaises(EdltApplyError) as caught:self.editor.apply(self.session,nextplan)
        self.assertEqual(len(calls),1);self.assertFalse(caught.exception.details['rollback_verified'])


    def test_interruptions_preserve_partial_evidence_and_stop_recovery_io(self):
        for interruption in (KeyboardInterrupt('stop'),SystemExit('stop')):
            session=Session(self.editor.spec);plan=self.plan();calls=[]
            def stop(name,value):calls.append(name);raise interruption
            session.set=stop
            with self.assertRaises(type(interruption)) as caught:self.editor.apply(session,plan)
            self.assertIs(caught.exception,interruption);self.assertEqual(len(calls),1)
            evidence=interruption.edlt_mra_evidence
            self.assertEqual(evidence['attempted_parameters'],calls);self.assertTrue(evidence['pp_state_uncertain'])
            self.assertFalse(evidence['saved']);self.assertEqual(evidence['automatic_retries'],0)
        session=Session(self.editor.spec);calls=[];original=OSError('primary');interruption=KeyboardInterrupt('during rollback')
        def fail_then_stop(name,value):
            calls.append(name)
            if len(calls)==1:raise original
            raise interruption
        session.set=fail_then_stop
        with self.assertRaises(KeyboardInterrupt) as caught:self.editor.apply(session,self.plan())
        self.assertIs(caught.exception,interruption);self.assertEqual(len(calls),2)
        self.assertEqual(interruption.edlt_mra_evidence['original_error'],{'type':'OSError','error':'primary'})


def mono(folder,app,command):
    result=subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',str(folder)+':/work',
      '-w','/work','mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5',
      'sh','-c',command],capture_output=True,text=True,timeout=60)
    if result.returncode:raise AssertionError(result.stdout+result.stderr)
    return result.stdout


def compile_probe(folder,app):
    root=Path(__file__).resolve().parents[1]
    Path(folder,'NativeEdltMRAProbe.cs').write_bytes((root/'research/NativeEdltMRAProbe.cs').read_bytes())
    mono(folder,app,'mcs -r:/input/CBusLogicModel.dll -r:/input/eDLT.dll -r:System.Windows.Forms -r:System.Drawing -r:System.Xml.Linq NativeEdltMRAProbe.cs')


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),'Set original Toolkit DLL fixture')
class OriginalMRAWidgetTests(unittest.TestCase):
    def test_original_model_ui_and_independent_record_vectors(self):
        app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend()
        if backend == 'windows':
            root = Path(__file__).resolve().parents[1]
            with OriginalModelOracle(root / 'research/NativeEdltMRAProbe.cs', app, backend='windows', references=('eDLT.dll',)) as oracle:
                output = oracle.run()
        else:
            with tempfile.TemporaryDirectory() as folder:
                compile_probe(folder,app);output=mono(folder,app,'MONO_PATH=/input mono NativeEdltMRAProbe.exe')
        rows={}
        for line in output.splitlines():
            key,value=line.split(':',1);self.assertNotIn(key,rows);rows[key]=value
        for kind,code in MRA_WIDGET_TYPES.items():
            self.assertEqual(rows[f'default-{code}-False'].split('=')[1].split('@')[0],DEFAULTS[kind])
        self.assertEqual(rows['zone-custom'].split('=')[1].split('@')[0],ZONE_CUSTOM)
        self.assertEqual(rows['select-transient-invalid-default'].split('=')[1].split('@')[0],DEFAULTS['source-select'])
        for widget in range(1,22):
            offered=set(map(int,rows[f'ui-types-{widget}'].split(',')))
            self.assertEqual({7,8,9}.issubset(offered),widget>=6)
        self.assertEqual(len([key for key in rows if key.startswith('source-pair-')]),49)
        for first in range(7):
            for second in range(7):
                record=bytes.fromhex(rows[f'source-pair-{first}-{second}'].split('=')[1].split('@')[0])
                self.assertEqual(record[6:9],bytes((2,first,second)))
        for mux in range(3):
            for zone in range(8):
                value=rows[f'global-pair-{mux}-{zone}'].split(':global')[0]
                records=[bytes.fromhex(row.split('=')[1].split('@')[0]) for row in value.split('|')]
                self.assertEqual([r[1] for r in records],[mux*64+zone*8+5,mux*64+zone*8,mux*64+zone*8])
        self.assertEqual(rows['transient-capacity-61'],'ok:'+DEFAULTS['source-select'])
        self.assertEqual(rows['transient-capacity-62'],'error:Static Text Table is full')
        self.assertEqual(rows['editable-15|16'],'True,False');self.assertEqual(rows['editable-21|22'],'False,True')
        if os.environ.get('CBUS_EDLT_MRA_REPORT'):
            report_path=Path(os.environ['CBUS_EDLT_MRA_REPORT'])
            report=json.loads(report_path.read_text()) if report_path.exists() else {}
            report.update(original_model_passed=True,original_vector_count=len(rows),original_backend=backend,
                original_dll_sha256=hashlib.sha256((app/'CBusLogicModel.dll').read_bytes()).hexdigest(),original_stdout=output)
            report_path.write_text(json.dumps(report,indent=2)+'\n')


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR') and os.environ.get('CBUS_TOOLKIT_EXE'),
                     'Set native C-Gate, specifications and Toolkit DLL fixture')
class NativeMRAWidgetTests(unittest.TestCase):
    def test_original_full_pp_raw_bytes_crc_globals_and_save_reload(self):
        from uuid import uuid4
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects,NativeDatabase
        from cbus_toolkit.programming import Programmer
        from cbus_toolkit.unitspec import UnitSpecStore
        from cbus_toolkit.edlt_mra import MRA_KEY_MODES,MRA_STATUS_TYPES,RAMP_SECONDS
        root=Path(__file__).resolve().parents[1];app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs=Path(os.environ['CBUS_UNITSPEC_DIR']);editor=EdltMRAWidget(UnitSpecStore(specs).load('KEYGL5.xml'))
        project='EMR'+uuid4().hex[:5].upper();network='//'+project+'/254';source='/db'+network+'/p/20'
        report={'native_passed':False,'project':project,'scope':'5055EDL5.5 MRA database records/globals; no Audio Control messages or hardware I/O',
                'original_full_state_cases':[],'global_pairs':[],'source_pairs':[]}
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as folder:
            oracle = OriginalModelOracle(root / 'research/NativeEdltMRAProbe.cs', app, backend='windows', references=('eDLT.dll',)) if backend == 'windows' else None
            if oracle is not None: self.addCleanup(oracle.close)
            else: compile_probe(folder,app)
            Path(folder,'KEYGL5.xml').write_bytes((specs/'KEYGL5.xml').read_bytes())
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                projects,database=NativeProjects(client),NativeDatabase(client);projects.operation('new',project);projects.operation('save',project)
                try:
                    database.create_network(project,254,'MRAFixture','Cni','127.0.0.1:1')
                    database.create_unit(network,20,'MRA','KEYGL5','5.5.00',catalog_number='5055EDL')
                    projects.operation('save',project);programmer=Programmer(client)
                    with programmer.load(network,source) as session:
                        for w in range(1,22):session.set(_field(w),'0')
                        for n in range(1,9):session.set(f'Scene{n}StartAddress','255')
                        session.set('ConfigVersionMajor','1');session.set('ConfigVersionMinor','0');session.set('UseBigIcon','1')
                        initial=editor.snapshot(session.values())
                        def run(label,original=False,globals_only=False,**options):
                            before=editor.snapshot(session.values())
                            plan=editor.plan_globals(before,**options) if globals_only else editor.plan(before,**{'page':1,'position':1,**options})
                            if original:
                                Path(folder,'values.tsv').write_text(''.join(name+'\t'+(value if isinstance(value,str) else ' '.join(hex(n) for n in value))+'\n' for name,value in before.items()))
                                native={}
                                if not globals_only:
                                    native.update(widget=plan.widget,kind=MRA_WIDGET_TYPES[plan.kind],variant=MRA_VARIANTS[plan.kind][plan.variant])
                                    native['page-mode']=int(plan.page_mode=='multiple')
                                    if options.get('key_mode') is not None:native['key']='|'.join(map(str,MRA_KEY_MODES[options['key_mode']]))
                                    if options.get('ramp_seconds') is not None:native['ramp']=RAMP_SECONDS.index(options['ramp_seconds'])
                                    if options.get('status_type') is not None:native['status']=MRA_STATUS_TYPES[options['status_type']]
                                    for key in ('label_text','status_text'):
                                        if options.get(key) is not None:native[key.replace('_','-')]=options[key]
                                    for key in ('source1','source2'):
                                        if options.get(key) is not None:native[key]=options[key]-1
                                    for key in ('on_icon','off_icon'):
                                        if options.get(key) is not None:native[key[:key.index('_')]]=options[key]
                                if options.get('multiplexer') is not None:native['multiplexer']=options['multiplexer']-1
                                if options.get('zone') is not None:native['zone']=options['zone']-1
                                Path(folder,'options.tsv').write_text(''.join(key+'\t'+str(value)+'\n' for key,value in native.items()))
                                if oracle is not None:
                                    output = oracle.run(('KEYGL5.xml', 'values.tsv', 'options.tsv'), files={name: Path(folder,name).read_bytes() for name in ('KEYGL5.xml','values.tsv','options.tsv')})
                                else:
                                    output=mono(folder,app,'MONO_PATH=/input mono NativeEdltMRAProbe.exe KEYGL5.xml values.tsv options.tsv')
                                observed={line[3:].split('\t',1)[0]:line[3:].split('\t',1)[1] for line in output.splitlines() if line.startswith('pp:')}
                                for line in output.splitlines():
                                    if line.startswith('memory-static:'):
                                        index,value=line[14:].split('\t',1);observed['StaticTextString'+index]=value
                                actual=editor.snapshot(observed)
                                diff={name:(actual[name],after(plan)[name]) for name in actual if actual[name]!=after(plan)[name]}
                                self.assertFalse(diff,(label,diff))
                                report['original_full_state_cases'].append({'label':label,'parameters_compared':len(actual),'crcs':{k:list(v) for k,v in editor.crcs(actual).items()}})
                            self.assertTrue(editor.apply(session,plan)['verified'])
                            if plan.widget:
                                raw=session.get_raw_data(0x220+(plan.widget-1)*32,32).lines[-1].split('RawData=')[1]
                                self.assertEqual(raw,plan.record.hex())
                            return plan
                        zone=run('zone-default',original=True,kind='zone-control')
                        self.assertEqual(zone.record.hex().upper(),DEFAULTS['zone-control'])
                        run('zone-custom',original=True,kind='zone-control',variant='balance',ramp_seconds=1020,status_type='static',label_text='Kitchen',status_text='Audio',on_icon=0,off_icon=252)
                        selected=run('select-default',original=True,kind='source-select')
                        self.assertEqual(selected.default_status_allocation.index,11)
                        run('select-custom',original=True,kind='source-select',variant='two-absolute',source1=1,source2=7,label_text='Music',status_text='Track',on_icon=38)
                        for first,second in ((1,1),(7,7),(7,1)):
                            plan=run('sources',kind='source-select',source1=first,source2=second)
                            self.assertEqual(plan.record[7:9],bytes((first-1,second-1)));report['source_pairs'].append([first,second])
                        run('control-default',original=True,kind='source-control')
                        run('control-custom',original=True,kind='source-control',variant='dynamic-1-and-2',label_text='Playback',on_icon=254)
                        run('later-select',kind='source-select',position=3,multiplexer=2,zone=4)
                        run('later-zone',kind='zone-control',position=5,status_type='static')
                        session.set(_field(8,1),'178');session.set(_field(10,1),'3')
                        run('mixed-global-normalization',original=True,globals_only=True)
                        for mux in range(1,4):
                            for zone in range(1,9):
                                plan=run('globals',globals_only=True,multiplexer=mux,zone=zone)
                                raw=session.get_raw_data(0x2c1,1).lines[-1].split('RawData=')[1]
                                self.assertEqual(int(raw,16),(mux-1)*64+(zone-1)*8)
                                report['global_pairs'].append([mux,zone])
                        session.set('Widget6RestoreLevel','155')
                        retained=run('same-type-restore',original=True,kind='source-control')
                        self.assertEqual(retained.restore_level,155)
                        final=editor.snapshot(session.values());session.save_to_source()
                    for operation in ('save','close','load'):projects.operation(operation,project)
                    with programmer.load(network,source) as session:self.assertEqual(editor.snapshot(session.values()),final)
                    self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                    report.update(native_passed=True,saved_reloaded=True,network_state='new',parameter_count=len(final))
                finally:
                    projects.operation('close',project);projects.operation('delete',project)
        if os.environ.get('CBUS_EDLT_MRA_REPORT'):
            path=Path(os.environ['CBUS_EDLT_MRA_REPORT']);existing=json.loads(path.read_text()) if path.exists() else {}
            path.write_text(json.dumps({**existing,**report},indent=2)+'\n')


if __name__=='__main__':unittest.main()
