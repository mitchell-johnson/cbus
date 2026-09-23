"""Original TimeAndDateData vectors, UI locations and isolated PP storage."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_time_date import EdltTimeDateWidget, DISPLAY_TYPES, DATE_FORMATS, TIME_FORMATS
from cbus_toolkit.unitspec import ParameterSpec, UnitSpecStore
from tests.test_edlt import fixture as base_fixture, Session

LITERALS = {
    (1, 'time'): '0A00000000000000000000000000000000000000000000000000000000000000',
    (1, 'date'): '0A01000000000000000000000000000000000000000000000000000000000000',
    (1, 'time-date'): '0A02000000000000000000000000000000000000000000000000000000000000',
    (2, 'time'): '0B00000000000000000000000000000000000000000000000000000000000000',
    (2, 'date'): '0B01000000000000000000000000000000000000000000000000000000000000',
    (2, 'time-date'): '0B02000000000000000000000000000000000000000000000000000000000000',
}
OPAQUE_SINGLE = '0A0102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F'
OPAQUE_DOUBLE = '0B0102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F'
OPAQUE_BLANK = '000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F'


def fixture():
    spec = base_fixture()
    parameters = dict(spec.parameters)
    for name, kind, bit, size, value in (('DateFormat', 'int', 0, 4, 1),
            ('TimeFormat', 'int', 5, 2, 3), ('TimeDateLeadingZero', 'bit', 4, 1, 0),
            ('OpaqueFormatBit', 'bit', 7, 1, 1)):
        parameters[name] = ParameterSpec(name, kind, 'synthetic.xml',
            {'Name': name, 'Type': kind, 'Address': '0x119', 'BitAddress': str(bit),
             'BitSize': str(size), 'DefaultValue': str(value)})
    return replace(spec, parameters=parameters)


def after(plan):
    return {**plan.expected, **plan.changes}


def record(values, widget):
    return bytes([values[f'Widget{widget}WidgetType'][0]] +
                 [values[f'Widget{widget}WidgetByteValue{i}'][0] for i in range(1, 32)])


class TimeDateWidgetTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltTimeDateWidget(self.spec); self.session = Session(self.spec)

    def plan(self, current=None, **options):
        settings = dict(page=0, position=1); settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def test_six_literal_display_vectors_and_opaque_defaults_same_type(self):
        for (slices, display), literal in LITERALS.items():
            plan = self.plan(slices=slices, display=display)
            self.assertEqual(plan.record.hex().upper(), literal)
            self.assertFalse(self.plan(after(plan)).changes)
            self.assertFalse(plan.as_dict()['clock_set'])
        source = self.editor.snapshot(self.session.values())
        for i in range(1, 32): source[f'Widget6WidgetByteValue{i}'] = (i,)
        source['Widget6RestoreLevel'] = (153,)
        plan = self.plan(source, page=1)
        self.assertEqual(plan.record.hex().upper(), OPAQUE_SINGLE)
        self.assertEqual(after(plan)['Widget6RestoreLevel'], (0,))
        current = after(plan); current['Widget6RestoreLevel'] = (155,)
        current.update(self.editor.crcs(current))
        same = self.plan(current, page=1)
        self.assertEqual(after(same)['Widget6RestoreLevel'], (155,))
        self.assertFalse(same.changes)
        self.assertFalse(any(f'Widget{i}RestoreLevel' in source for i in range(1, 6)))

    def test_all_original_locations_and_page_layout_preservation(self):
        for position in range(1, 6):
            self.assertEqual(self.plan(position=position).widget, position)
            self.assertEqual(self.plan(page=1, position=position).widget, position + 5)
        for page in range(1, 5):
            for position in range(1, 5):
                plan = self.plan(page=page, position=position, page_mode='multiple')
                self.assertEqual(plan.widget, 6 + (page - 1) * 4 + position - 1)
                self.assertEqual(after(plan)['NavWidgetType'], (1,))
        for position in range(1, 5):
            self.assertEqual(self.plan(position=position, slices=2).adjacent_widget, position + 1)
        source = after(self.plan(page=4, position=4, page_mode='multiple'))
        standby = self.plan(source, slices=2)
        self.assertEqual(standby.page_mode, 'multiple')
        self.assertEqual(after(standby)['Widget21WidgetType'], (10,))
        self.assertNotIn('Widget21RestoreLevel', standby.changes)

    def test_exact_configured_neighbor_clear_same_type_and_shrink(self):
        for kind in (0, 10, 11, 12, 13, 255):
            source = self.editor.snapshot(self.session.values())
            for widget in (1, 2, 3):
                source[f'Widget{widget}WidgetType'] = (0,)
                for i in range(1, 32): source[f'Widget{widget}WidgetByteValue{i}'] = (i,)
            source['Widget2WidgetType'] = (kind,)
            plan = self.plan(source, slices=2)
            self.assertEqual(plan.record.hex().upper(), OPAQUE_DOUBLE)
            self.assertEqual(plan.adjacent_after.hex().upper(), OPAQUE_BLANK)
            self.assertEqual(record(after(plan), 3), record(source, 3))
            shrunk = self.plan(after(plan), slices=1)
            self.assertEqual(shrunk.record.hex().upper(), OPAQUE_SINGLE)
            self.assertIsNone(shrunk.adjacent_widget)
            self.assertEqual(record(after(shrunk), 2), bytes.fromhex(OPAQUE_BLANK))
            with self.assertRaisesRegex(EdltError, 'covered'): self.plan(after(plan), position=2)
        existing = after(plan); existing['Widget2WidgetType'] = (10,)
        preserved = self.plan(existing, display='time-date')
        self.assertEqual(record(after(preserved), 2), record(existing, 2))
        self.assertIsNone(preserved.adjacent_widget)

    def test_all64_global_formats_and_unrelated_shared_bit(self):
        self.assertEqual(dict(TIME_FORMATS), {'12-hour':3, '24-hour':1,
            '12-hour-lowercase':0, '12-hour-uppercase':2})
        self.assertEqual(len(DATE_FORMATS), 8)
        for date in range(8):
            for time, code in TIME_FORMATS.items():
                for zero in (False, True):
                    plan = self.plan(date_format=date, time_format=time, leading_zero=zero)
                    final = after(plan)
                    self.assertEqual((final['DateFormat'], final['TimeFormat'], final['TimeDateLeadingZero']),
                                     ((date,), (code,), (int(zero),)))
                    self.assertEqual(final['OpaqueFormatBit'], (1,))
                    raw = bytearray(b'\x80')
                    for name in ('DateFormat', 'TimeFormat', 'TimeDateLeadingZero'):
                        for edit in self.editor.codec.encode(name, final[name]).edits:
                            raw[0] = (raw[0] & ~edit.mask) | edit.value
                    self.assertEqual(raw, bytes([0x80 | date | int(zero) << 4 | code << 5]))
                    self.assertTrue(plan.as_dict()['global_formats_apply_to_whole_unit'])

    def test_boundaries_profile_schema_and_invalid_source_require_explicit_choice(self):
        invalid = ({'page':-1}, {'page':True}, {'page':2}, {'position':0}, {'position':6},
            {'slices':True}, {'slices':0}, {'slices':3}, {'slices':2,'position':5},
            {'slices':2,'page':1}, {'display':[]}, {'display':'both'}, {'page_mode':'other'},
            {'date_format':True}, {'date_format':8}, {'date_format':-1}, {'time_format':3},
            {'leading_zero':1}, {'leading_zero':'false'})
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(EdltError): self.plan(**options)
        source = self.editor.snapshot(self.session.values()); source['Widget1WidgetByteValue1'] = (255,)
        with self.assertRaisesRegex(EdltError, 'explicit display'): self.plan(source)
        self.assertEqual(self.plan(source, display='date').record[1], 1)
        for widget, kind in ((1,2), (5,11), (6,11), (7,10)):
            source = self.editor.snapshot(self.session.values()); source[f'Widget{widget}WidgetType'] = (kind,)
            with self.assertRaises(EdltError): self.plan(source)
        with self.assertRaises(EdltError): EdltTimeDateWidget(self.spec, firmware='6.0.00')
        with self.assertRaises(EdltError): EdltTimeDateWidget(base_fixture())
        params = dict(self.spec.parameters); old = params['DateFormat']
        params['DateFormat'] = replace(old, fields={**old.fields,'BitAddress':'1'})
        with self.assertRaises(EdltError): EdltTimeDateWidget(replace(self.spec,parameters=params))
        self.assertFalse(self.session.calls)

    def test_reviewable_conversion_canonical_stale_identity_and_database_guards(self):
        source = self.session.values(); source['Widget1WidgetType'] = (13,)
        self.session.current = source
        plan = self.plan(display='date', slices=2)
        self.assertEqual(plan.record_before[0], 13)
        for forged in (None, replace(plan,widget=True), replace(plan,leading_zero=0),
                       replace(plan,record=b'bad'), replace(plan,adjacent_after=b'bad'),
                       replace(plan,changes={**plan.changes,'SceneCount':(8,)})):
            with self.assertRaises(EdltError): self.editor.apply(self.session,forged)
        self.session.current['SceneCount'] = (8,)
        with self.assertRaisesRegex(EdltError,'changed'): self.editor.apply(self.session,plan)
        self.session.current['SceneCount'] = plan.expected['SceneCount']
        result = self.editor.apply(self.session,plan)
        self.assertTrue(result['verified']); self.assertFalse(result['saved'])
        self.session.source = '//EDLTTEST/254/p/20'
        with self.assertRaisesRegex(EdltError,'database'): self.editor.configure(self.session,page=0,position=1)
        self.session.source = '/db//EDLTTEST/254/p/20'; self.session.identity['UnitType']='KEY4'
        self.session.values=lambda:self.fail('Identity must precede PP reads')
        with self.assertRaisesRegex(EdltError,'identity'): self.editor.configure(self.session)

    def test_failure_rolls_back_neighbor_and_formats_without_recovery_after_disconnect(self):
        self.session.current['Widget2WidgetType'] = (10,)
        plan = self.plan(slices=2, display='time-date', date_format=7)
        source = self.editor.snapshot(self.session.values()); self.session.failure = 'Widget2WidgetType'
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session,plan)
        self.assertTrue(caught.exception.details['rollback_verified'])
        self.assertEqual(self.editor.snapshot(self.session.values()),source)
        self.session.calls.clear(); initial=self.session.set
        def fail(name,value):
            initial(name,value); self.session.connected=False; raise TimeoutError('Injected disconnect')
        self.session.set=fail
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session,plan)
        self.assertEqual(len(self.session.calls),1)
        self.assertIn('Connection lost',caught.exception.rollback_errors[0])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'Set original Toolkit EXE for original time/date acceptance')
class OriginalTimeDateTests(unittest.TestCase):
    def test_unchanged_original_model_vectors_and_ui_available_types(self):
        root=Path(__file__).resolve().parents[1]; app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend()
        if backend == 'windows':
            with OriginalModelOracle(root / 'research/NativeEdltTimeDateProbe.cs', app, backend='windows', references=('eDLT.dll',)) as oracle:
                original_output = oracle.run()
            result = subprocess.CompletedProcess([], 0, original_output, '')
        else:
            with tempfile.TemporaryDirectory() as folder:
                Path(folder,'NativeEdltTimeDateProbe.cs').write_bytes((root/'research/NativeEdltTimeDateProbe.cs').read_bytes())
                result=subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',folder+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',
                    'mcs -r:/input/CBusLogicModel.dll -r:/input/eDLT.dll -r:System.Windows.Forms -r:System.Drawing -r:System.Xml.Linq NativeEdltTimeDateProbe.cs && MONO_PATH=/input mono NativeEdltTimeDateProbe.exe'],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        lines=result.stdout.splitlines(); rows=dict(line.split(':',1) for line in lines if not line.startswith('formats:'))
        for (slices,display),literal in LITERALS.items():
            self.assertIn('1='+literal+'@none',rows[f'display-{9+slices}-{DISPLAY_TYPES[display]}'])
        for number in range(1,22):
            values=set(map(int,rows['ui-types-'+str(number)].split(',')))
            self.assertIn(10,values); self.assertEqual(11 in values,number<5)
        self.assertEqual(rows['ui-types--1'],'')
        self.assertEqual({line for line in lines if line.startswith('formats:')},
            {f'formats:{d},{t},{z}' for d in range(8) for t in range(4) for z in range(2)})
        self.assertIn('notification_suppressed=True',rows['edge-error-21'])
        self.assertIn('2='+OPAQUE_SINGLE+'@none',rows['save-keeps-existing-double-neighbor'])
        self.assertIn('6='+OPAQUE_SINGLE+'@155',rows['same-type-10'])
        self.assertIn('6='+OPAQUE_SINGLE+'@0',rows['explicit-default-10'])
        self.assertIn('7=FF0102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F@0',rows['after-save-trailing'])
        if os.environ.get('CBUS_EDLT_TIME_DATE_REPORT'):
            path=Path(os.environ['CBUS_EDLT_TIME_DATE_REPORT'])
            prior=json.loads(path.read_text()) if path.exists() else {}
            path.write_text(json.dumps({**prior,
                'original_passed':True,'original_output_lines':len(lines),'original_output':result.stdout,'original_backend':backend,
                'dll_sha256':hashlib.sha256((app/'CBusLogicModel.dll').read_bytes()).hexdigest(),
                'ui_dll_sha256':hashlib.sha256((app/'eDLT.dll').read_bytes()).hexdigest()},indent=2)+'\n')


@unittest.skipUnless(all(os.environ.get(name) for name in
    ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),
    'Set native C-Gate, specs and Toolkit EXE for Time/Date PP acceptance')
class NativeTimeDateTests(unittest.TestCase):
    def test_all_formats_locations_original_save_crc_and_native_storage(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects, NativeDatabase
        from cbus_toolkit.programming import Programmer
        root=Path(__file__).resolve().parents[1]; app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve(); editor=EdltTimeDateWidget(UnitSpecStore(specs).load('KEYGL5.xml'))
        project='ETD'+uuid4().hex[:5].upper(); network=f'//{project}/254'; source='/db'+network+'/p/20'
        report={'native_passed':False,'project':project,'scope':'5055EDL5.5 Time/Date database display settings; no hardware clock I/O',
                'global_formats':[], 'locations':[], 'original_full_state_cases':[]}
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'NativeEdltTimeDateProbe.cs').write_bytes((root/'research/NativeEdltTimeDateProbe.cs').read_bytes())
            Path(folder,'KEYGL5.xml').write_bytes((specs/'KEYGL5.xml').read_bytes())
            def mono(command):
                result=subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',folder+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',command],
                    capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltTimeDateProbe.cs', app, backend='windows', references=('eDLT.dll',)) if backend == 'windows' else None
            if oracle is not None: self.addCleanup(oracle.close)
            else:mono('mcs -r:/input/CBusLogicModel.dll -r:/input/eDLT.dll -r:System.Windows.Forms -r:System.Drawing -r:System.Xml.Linq NativeEdltTimeDateProbe.cs')
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                projects,database=NativeProjects(client),NativeDatabase(client);projects.operation('new',project)
                try:
                    database.create_network(project,254,'TimeDate','Cni','127.0.0.1:1')
                    database.create_unit(network,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL')
                    projects.operation('save',project); programmer=Programmer(client)
                    with programmer.load(network,source) as session:
                        for widget in range(1,22):
                            session.set(f'Widget{widget}WidgetType','0')
                            if widget>=6:session.set(f'Widget{widget}RestoreLevel',str(100+widget))
                        # Explicit staged empty-scene representation avoids conflating
                        # this widget edit with the original GUI scene-load compaction.
                        for scene in range(1,9):session.set(f'Scene{scene}StartAddress','255')
                        for name,value in (('ConfigVersionMajor','1'),('ConfigVersionMinor','0'),
                                ('NavWidgetType','0'),('Widget2WidgetType','13'),('Widget2WidgetByteValue31','201')):
                            session.set(name,value)
                        initial=editor.snapshot(session.values())
                        original_format_byte=int(session.get_raw_data(0x119,1).lines[-1].split('RawData=')[1],16)
                        def run_case(label, original=False, **options):
                            before=editor.snapshot(session.values()); plan=editor.plan(before,**options)
                            if original:
                                Path(folder,'values.tsv').write_text(''.join(name+'\t'+(value if isinstance(value,str) else
                                    ' '.join(hex(n) for n in value))+'\n' for name,value in before.items()))
                                if oracle is not None:
                                    args = tuple(str(n) for n in (plan.widget,9+plan.slices,DISPLAY_TYPES[plan.display],
                                        plan.date_format,TIME_FORMATS[plan.time_format],int(plan.leading_zero),int(plan.page_mode=='multiple')))
                                    out = oracle.run(('KEYGL5.xml', 'values.tsv', *args), files={name: Path(folder,name).read_bytes() for name in ('KEYGL5.xml','values.tsv')})
                                else:
                                    out=mono('MONO_PATH=/input mono NativeEdltTimeDateProbe.exe KEYGL5.xml values.tsv '+
                                        ' '.join(str(n) for n in (plan.widget,9+plan.slices,DISPLAY_TYPES[plan.display],
                                            plan.date_format,TIME_FORMATS[plan.time_format],int(plan.leading_zero),int(plan.page_mode=='multiple'))))
                                observed={line[3:].split('\t',1)[0]:line[3:].split('\t',1)[1]
                                          for line in out.splitlines() if line.startswith('pp:')}
                                self.assertEqual(editor.snapshot(observed),after(plan))
                                report['original_full_state_cases'].append({'label':label,'parameters_compared':len(observed),
                                    'crcs':{key:list(value) for key,value in editor.crcs(after(plan)).items()}})
                            result=editor.apply(session,plan);self.assertTrue(result['verified'])
                            raw=session.get_raw_data(0x220+(plan.widget-1)*32,32).lines[-1].split('RawData=')[1]
                            self.assertEqual(raw,plan.record.hex())
                            if plan.adjacent_widget:
                                raw=session.get_raw_data(0x220+(plan.adjacent_widget-1)*32,32).lines[-1].split('RawData=')[1]
                                self.assertEqual(raw,plan.adjacent_after.hex())
                            return plan
                        double=run_case('standby-double-clears-hvac-temperature',original=True,page=0,position=1,slices=2,display='time-date')
                        self.assertEqual(double.record.hex().upper(),LITERALS[(2,'time-date')])
                        self.assertEqual(after(double)['Widget2WidgetByteValue31'],(201,))
                        for date in range(8):
                            for time,code in TIME_FORMATS.items():
                                for zero in (False,True):
                                    plan=run_case('format',page=0,position=1,date_format=date,time_format=time,leading_zero=zero)
                                    raw=int(session.get_raw_data(0x119,1).lines[-1].split('RawData=')[1],16)
                                    self.assertEqual(raw,(original_format_byte&128)|date|(int(zero)<<4)|(code<<5))
                                    report['global_formats'].append({'date':date,'time':code,'leading_zero':zero,'raw':raw})
                        run_case('shrink',page=0,position=1,slices=1)
                        for position in range(1,6):
                            plan=run_case('standby-single',page=0,position=position,display='date')
                            report['locations'].append([0,position,1,plan.widget])
                        for position in range(1,5):
                            plan=run_case('standby-double',page=0,position=position,slices=2,display='time-date')
                            report['locations'].append([0,position,2,plan.widget])
                            run_case('shrink',page=0,position=position,slices=1)
                        for position in range(1,6):
                            plan=run_case('functional-single',page=1,position=position,display='time')
                            report['locations'].append([1,position,1,plan.widget])
                            self.assertEqual(after(plan)[f'Widget{plan.widget}RestoreLevel'],(0,))
                        for page in range(1,5):
                            for position in range(1,5):
                                plan=run_case('functional-multiple',original=page==4 and position==4,
                                    page=page,position=position,page_mode='multiple',display='time-date')
                                report['locations'].append([page,position,1,plan.widget])
                        session.set('Widget6RestoreLevel','155')
                        same=run_case('same-type-nonzero-restore',original=True,page=1,position=1,page_mode='multiple',display='date')
                        self.assertEqual(after(same)['Widget6RestoreLevel'],(155,))
                        self.assertEqual(session.get_raw_data(0x1a0,1).lines[-1].split('RawData=')[1],'9b')
                        final=editor.snapshot(session.values())
                        for name,value in initial.items():
                            if name.startswith('StaticTextString') or (name.startswith('Scene') and name!='ScenesCheckSum'):
                                self.assertEqual(final[name],value)
                        report['parameter_count']=len(final); session.save_to_source()
                    for operation in ('save','close','load'):projects.operation(operation,project)
                    with programmer.load(network,source) as session:
                        self.assertEqual(editor.snapshot(session.values()),final)
                        self.assertEqual(session.get_raw_data(0x119,1).lines[-1].split('RawData=')[1],
                                         bytes([(original_format_byte&128)|7|16|64]).hex())
                    self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                    report.update(native_passed=True,saved_reloaded=True,network_state='new')
                finally:
                    projects.operation('close',project);projects.operation('delete',project)
                    if os.environ.get('CBUS_EDLT_TIME_DATE_REPORT'):
                        path=Path(os.environ['CBUS_EDLT_TIME_DATE_REPORT'])
                        prior=json.loads(path.read_text()) if path.exists() else {}
                        path.write_text(json.dumps({**prior,**report},indent=2)+'\n')

if __name__ == '__main__':
    unittest.main()
