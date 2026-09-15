"""Original HVAC model/graphics vectors and native database PP acceptance."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError, _field, _render
from cbus_toolkit.edlt_hvac import EdltHVACTemperatureWidget, BUILTIN_ICON_INDICES
from cbus_toolkit.unitspec import ParameterSpec, UnitSpecStore
from tests.test_edlt import fixture as base_fixture, Session

DEFAULT = '0DFF000000873F00000000000000000000000000000000000000000000000000'
CUSTOM = '0D2A040201263E00000000000000000000000000000000000000000000000000'
NATIVE_DEFAULT = '0DFF000000871200000000000000000000000000000000000000000000000000'
NATIVE_CUSTOM = '0D2A040201263F00000000000000000000000000000000000000000000000000'
STANDBY_CUSTOM = '0D2A040201873F00000000000000000000000000000000000000000000000000'
UNICODE = '0DFE000100FE3F00000000000000000000000000000000000000000000000000'
EMPTY_LAST = '0D0001020100FF00000000000000000000000000000000000000000000000000'
OPAQUE = '0DFF000000873F0708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F'


def fixture():
    spec = base_fixture(); parameters = dict(spec.parameters)
    parameters['UseBigIcon'] = ParameterSpec('UseBigIcon', 'bit', 'synthetic.xml',
        {'Name': 'UseBigIcon', 'Type': 'bit', 'Address': '0x118', 'BitAddress': '4',
         'BitSize': '1', 'DefaultValue': '1'})
    return replace(spec, parameters=parameters)


def after(plan):
    return {**plan.expected, **plan.changes}


def record(values, widget):
    return bytes(values[_field(widget, i)][0] for i in range(32))


class HVACTemperatureTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltHVACTemperatureWidget(self.spec); self.session = Session(self.spec)

    def plan(self, current=None, **options):
        settings = dict(page=1, position=1, group=255); settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def test_original_literals_defaults_preservation_and_no_control_claims(self):
        plan = self.plan(); self.assertEqual(plan.record.hex().upper(), DEFAULT)
        self.assertEqual(plan.allocations['default_label'].index, 63)
        custom = self.plan(group=42, zone=4, decimal_places=2, units='fahrenheit', icon_index=38, label_text='Room')
        self.assertEqual(custom.record.hex().upper(), CUSTOM)
        self.assertEqual(custom.allocations['label'].used_indices, (63, 255))
        self.assertEqual(custom.as_dict()['application'], 172)
        for key in ('group_metadata_verified', 'database_group_created', 'hvac_control_sent', 'physical_device_verified', 'saved'):
            self.assertFalse(custom.as_dict()[key])
        self.assertFalse(self.plan(after(custom), group=42).changes)
        native = self.editor.snapshot(self.session.values()); native['StaticTextString18'] = tuple(b'Temperature'.ljust(64, b'\0'))
        self.assertEqual(self.plan(native).record.hex().upper(), NATIVE_DEFAULT)
        self.assertEqual(self.plan(native, group=42, zone=4, decimal_places=2, units='fahrenheit', icon_index=38, label_text='Room').record.hex().upper(), NATIVE_CUSTOM)

    def test_all_zones_units_precision_icons_and_hidden_icon_guards(self):
        for zone in range(5):
            for units, code in (('celsius', 0), ('fahrenheit', 1)):
                for precision in range(3):
                    self.assertEqual(self.plan(zone=zone, units=units, decimal_places=precision).record[2:5], bytes((zone, precision, code)))
        expected = set(range(39)) | set(range(128, 142)) | {252, 253, 254}
        self.assertEqual(set(BUILTIN_ICON_INDICES), expected)
        for icon in range(256):
            if icon in expected: self.assertEqual(self.plan(icon_index=icon).record[5], icon)
            else:
                with self.assertRaises(EdltError): self.plan(icon_index=icon)
        current = self.editor.snapshot(self.session.values()); current['UseBigIcon'] = (0,)
        with self.assertRaisesRegex(EdltError, 'UseBigIcon'): self.plan(current, icon_index=135)
        self.assertFalse(self.plan(current).icon_editable)
        for position in range(1, 6):
            with self.assertRaisesRegex(EdltError, 'functional'): self.plan(page=0, position=position, icon_index=135)
        existing = after(self.plan()); existing[_field(6, 5)] = (200,)
        self.assertEqual(self.plan(existing).icon_index, 200)  # No editor access implies no hidden normalization.
        self.assertNotIn('UseBigIcon', self.plan(existing).changes)

    def test_original_locations_opaque_restore_and_shrink_semantics(self):
        for position in range(1, 6):
            standby = self.plan(page=0, position=position)
            self.assertEqual(standby.widget, position); self.assertIsNone(standby.restore_level)
            self.assertNotIn(f'Widget{position}RestoreLevel', after(standby))
            self.assertEqual(self.plan(position=position).widget, position + 5)
        for page in range(1, 5):
            for position in range(1, 5):
                self.assertEqual(self.plan(page=page, position=position, page_mode='multiple').widget, 6+(page-1)*4+position-1)
        original = self.editor.snapshot(self.session.values())
        for i in range(1, 32): original[_field(6, i)] = (i,)
        original['Widget6RestoreLevel'] = (153,)
        plan = self.plan(original); self.assertEqual(plan.record.hex().upper(), OPAQUE); self.assertEqual(plan.restore_level, 0)
        current = after(plan); current['Widget6RestoreLevel'] = (155,); current.update(self.editor.crcs(current))
        same = self.plan(current, group=42); self.assertEqual(same.restore_level, 155)
        self.assertEqual(same.record[7:], plan.record[7:]); self.assertNotIn('Widget6RestoreLevel', same.changes)
        current = self.editor.snapshot(self.session.values()); current[_field(1)] = (11,); current[_field(2)] = (0,)
        for i in range(1, 32): current[_field(2, i)] = (i,)
        with self.assertRaisesRegex(EdltError, 'covered'): self.plan(current, page=0, position=2)
        shrunk = self.plan(current, page=0); self.assertEqual(record(after(shrunk), 2), record(current, 2))
        self.assertEqual(shrunk.record[0], 13)

    def test_text_defaults_reuse_exact_indexes_clear_and_utf8(self):
        current = after(self.plan(label_text='Māori'))
        self.assertEqual(current['StaticTextString62'], tuple('Māori'.encode().ljust(64, b'\0')))
        self.assertEqual(self.plan(current, label_text='Māori').record[6], 62)
        current['StaticTextString61'] = current['StaticTextString62']
        explicit = self.plan(current, label_index=62); self.assertEqual(explicit.record[6], 62)
        self.assertEqual(self.plan(current, label_text='Māori').record[6], 61)
        for text in ('', ' \t'):
            plan = self.plan(label_text=text); self.assertEqual(plan.record[6], 255)
            self.assertEqual(plan.allocations['default_label'].index, 63)
            self.assertIn('StaticTextString63', plan.changes)
        self.assertEqual(self.plan(label_text='X'*63).record[6], 62)
        for text in ('X'*64, 'é'*32, 'bad\0text', '\ud800'):
            with self.assertRaises(EdltError): self.plan(label_text=text)
        self.assertEqual(self.plan(label_index=255).record[6], 255)
        for index in range(64): self.assertEqual(self.plan(label_index=index).record[6], index)

    def test_full_references_capacity_and_measurement64_remain_exact(self):
        current = after(self.plan()); reference = 0
        for widget in range(7, 22):
            current[_field(widget)] = (16,); current[_field(widget, 1)] = (0x35,)
            for offset in range(9, 14):
                current[_field(widget, offset)] = (min(reference, 62),); reference += 1
        original = dict(current)
        with self.assertRaisesRegex(EdltError, 'full'): self.plan(current, label_text='Full')
        self.assertEqual(current, original)
        self.assertEqual(self.plan(current, label_text='Lamp').record[6], 1)
        # Valid Measurement sentinel64 is counted; HVAC64 remains rejected.
        current = after(self.plan()); current[_field(1)] = (12,)
        for offset in (10, 11): current[_field(1, offset)] = (255,)
        current[_field(1, 13)] = (64,)
        plan = self.plan(current, label_text='Neighbor'); self.assertIn(64, plan.allocations['label'].used_indices)
        current = after(plan); current[_field(6, 6)] = (64,)
        with self.assertRaisesRegex(EdltError, 'static reference'): self.plan(current)

    def test_validation_profile_layout_and_no_mutation(self):
        original = self.editor.snapshot(self.session.values())
        for options in ({'group': True}, {'group': -1}, {'group': 256}, {'zone': 5}, {'decimal_places': 3},
                        {'units': 'kelvin'}, {'icon_index': True}, {'icon_index': 39}, {'icon_index': 255},
                        {'label_index': 64}, {'label_index': False}, {'label_text': 5},
                        {'label_text': 'Room', 'label_index': 1}, {'page': -1}, {'page': 2},
                        {'position': 6}, {'page_mode': 'bad'}, {'page_mode': 'multiple', 'position': 5}):
            with self.assertRaises(EdltError): self.plan(**options)
        self.assertEqual(self.editor.snapshot(self.session.values()), original)
        current = after(self.plan()); current[_field(6, 2)] = (255,)
        with self.assertRaises(EdltError): self.plan(current)
        self.assertEqual(self.plan(current, zone=4).zone, 4)
        for widget, kind in ((1, 2), (5, 11), (6, 11)):
            current = dict(original); current[_field(widget)] = (kind,)
            with self.assertRaises(EdltError): self.plan(current)
        with self.assertRaises(EdltError): EdltHVACTemperatureWidget(self.spec, firmware='5.4.00')
        parameters = dict(self.spec.parameters); param = parameters['UseBigIcon']
        parameters['UseBigIcon'] = replace(param, fields={**param.fields, 'BitAddress': '3'})
        with self.assertRaisesRegex(EdltError, 'layout'): EdltHVACTemperatureWidget(replace(self.spec, parameters=parameters))
        with self.assertRaisesRegex(EdltError, 'layout'): EdltHVACTemperatureWidget(base_fixture())

    def test_canonical_stale_identity_and_verified_apply(self):
        plan = self.plan(group=42, label_text='Room')
        for forged in (replace(plan, record=bytes(32)), replace(plan, group=True),
                       replace(plan, icon_editable=1), replace(plan, allocations={}),
                       replace(plan, changes={}), replace(plan, widget=0)):
            with self.assertRaises(EdltError): self.editor.apply(self.session, forged)
        self.assertFalse(self.session.calls)
        self.session.current['SceneCount'] = (1,)
        with self.assertRaisesRegex(EdltError, 'changed'): self.editor.apply(self.session, plan)
        self.session.current['SceneCount'] = (0,)
        result = self.editor.apply(self.session, plan); self.assertTrue(result['verified']); self.assertFalse(result['saved'])
        self.session.identity['UnitType'] = 'KEY4'; self.session.values = lambda: self.fail('Identity guard must precede PP read')
        with self.assertRaisesRegex(EdltError, 'identity'): self.editor.configure(self.session)

    def test_rollback_failure_and_disconnect_stop(self):
        plan = self.plan(group=42, label_text='Room'); original = self.editor.snapshot(self.session.values())
        self.session.failure = _field(6, 1)
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertTrue(caught.exception.details['rollback_verified']); self.assertFalse(caught.exception.details['saved'])
        self.assertEqual(self.editor.snapshot(self.session.values()), original)
        self.session.calls.clear(); initial = self.session.set
        def fail(name, value):
            initial(name, value); self.session.connected = False; raise TimeoutError('Injected disconnect')
        self.session.set = fail
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertEqual(len(self.session.calls), 1); self.assertIn('Connection lost', caught.exception.rollback_errors[0])


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')),
                     'Set native C-Gate, specifications and Toolkit EXE for HVAC acceptance')
class NativeHVACTemperatureTests(unittest.TestCase):
    def test_original_graphics_selector_indices(self):
        import sys
        root = Path(__file__).resolve().parents[1]
        app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'graphics.json'
            result = subprocess.run([sys.executable, str(root/'research/NativeEdltGraphicsProbe.py'),
                                     str(app/'EDLT_graphics.dll'), str(output)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            evidence = json.loads(output.read_text())
            self.assertEqual(evidence['dll_sha256'], 'e319379709c47f97dca477c4f631880f231c060530cb2ec45a3f731b1a5d1991')
            self.assertEqual(evidence['import_calls'], {'memset': 1})
            self.assertEqual(len(evidence['rows']), 255)
            expected = list(range(1, 39)) + list(range(128, 142)) + [252, 253, 254]
            self.assertEqual(evidence['icon_indices'], expected)
            self.assertEqual(set(BUILTIN_ICON_INDICES), {0, *expected})

    def test_original_model_bytes_crc_and_native_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects, NativeDatabase
        from cbus_toolkit.programming import Programmer
        root = Path(__file__).resolve().parents[1]; app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve(); editor = EdltHVACTemperatureWidget(UnitSpecStore(specs).load('KEYGL5.xml'))
        project = 'EHV'+uuid4().hex[:5].upper(); network = '//'+project+'/254'; unit = network+'/p/20'
        report = {'passed': False, 'project': project, 'physical_device_verified': False, 'cases': []}
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'NativeEdltHVACProbe.cs').write_bytes((root/'research/NativeEdltHVACProbe.cs').read_bytes())
            Path(folder, 'KEYGL5.xml').write_bytes((specs/'KEYGL5.xml').read_bytes())
            def mono(command):
                result = subprocess.run(['docker', 'run', '--rm', '-v', str(app)+':/input:ro', '-v', folder+':/work', '-w', '/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5', 'sh', '-c', command], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr); return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltHVACProbe.cs', app, backend='windows', references=('eDLT.dll',)) if backend == 'windows' else None
            baseline = OriginalModelOracle(root / 'research/NativeEdltHVACBaselineProbe.cs', app, backend='windows', references=('eDLT.dll',)) if backend == 'windows' else None
            if oracle is not None:
                self.addCleanup(oracle.close); self.addCleanup(baseline.close)
                original = oracle.run()
                self.assertEqual(baseline.run(), original)
                report['baseline_zero_argument_equivalent'] = True
            else:
                original = mono('mcs -r:/input/CBusLogicModel.dll -r:/input/eDLT.dll -r:System.Windows.Forms -r:System.Drawing -r:System.Xml.Linq NativeEdltHVACProbe.cs && MONO_PATH=/input mono NativeEdltHVACProbe.exe')
            for literal in (DEFAULT, CUSTOM, NATIVE_DEFAULT, NATIVE_CUSTOM, OPAQUE): self.assertIn(':'+literal+':', original)
            for number in range(1, 22): self.assertIn('ui-available-'+str(number)+':True', original)
            for literal in ('isolated-application:172', 'isolated-missing-group-get:255', 'native-unset-get:255',
                            'has-restore-1:False', 'has-restore-5:False', 'has-restore-6:True'):
                self.assertIn(literal, original.splitlines())
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
                projects = NativeProjects(client); db = NativeDatabase(client); programmer = Programmer(client)
                projects.operation('new', project)
                try:
                    db.create_network(project, 254, 'HVAC_Acceptance', 'Cni', '127.0.0.1:1'); projects.operation('save', project)
                    db.add(network, 'application', 172, 'HVAC'); db.add(network+'/172', 'group', 42, 'SyntheticZone')
                    db.create_unit(network, 20, 'EDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL'); projects.operation('save', project)
                    client.command('NET LOAD DB '+project)
                    cases = ((1, dict(group=255), NATIVE_DEFAULT),
                             (5, dict(group=42, zone=4, decimal_places=2, units='fahrenheit', label_text='Room'), STANDBY_CUSTOM),
                             (6, dict(group=255), NATIVE_DEFAULT),
                             (6, dict(group=42, zone=4, decimal_places=2, units='fahrenheit', icon_index=38, label_text='Room'), NATIVE_CUSTOM),
                             (10, dict(group=254, zone=0, decimal_places=1, units='celsius', icon_index=254, label_text='Māori'), UNICODE),
                             (21, dict(group=0, zone=1, decimal_places=2, units='fahrenheit', icon_index=0, label_text=''), EMPTY_LAST))
                    if oracle is not None:
                        cases += tuple((6, dict(group=42,zone=4,decimal_places=2,units='fahrenheit',icon_index=38,label_text=text), NATIVE_CUSTOM) for text in ('-','@1'))
                    report['baseline_ascii_full_pp_cases'] = 0
                    for widget, settings, literal in cases:
                        with programmer.load(network, '/db'+unit) as session:
                            session.reset_defaults()
                            # Original AfterLoadPPData initializes these before the widget model is edited.
                            session.set('ConfigVersionMajor', '1'); session.set('ConfigVersionMinor', '0')
                            # Exact fixture state isolates widgets from original SaveScenes'65535→255 normalization.
                            for slot in range(1, 9): session.set(f'Scene{slot}StartAddress', '255')
                            if widget == 21: session.set('NavWidgetType', '1')
                            if widget >= 6: session.set(f'Widget{widget}RestoreLevel', '153')
                            current = editor.snapshot(session.values())
                            page, position = (0, widget) if widget < 6 else (4, 4) if widget == 21 else (1, widget-5)
                            plan = editor.plan(current, page=page, position=position, **settings)
                            self.assertEqual(plan.record.hex().upper(), literal)
                            Path(folder, 'values.tsv').write_text(''.join(key+'\t'+(value if isinstance(value, str) else ' '.join(hex(n) for n in value))+'\n' for key, value in current.items()))
                            import shlex
                            label = settings.get('label_text', '-')
                            args = [str(widget), str(plan.group), str(plan.zone), str(plan.decimal_places), str(0 if plan.units == 'celsius' else 1),
                                    str(settings.get('icon_index', '-')), label]
                            if oracle is not None:
                                files = {name: Path(folder,name).read_bytes() for name in ('KEYGL5.xml','values.tsv')}
                                if label == 'Room':
                                    legacy = baseline.run(('KEYGL5.xml','values.tsv',*args), files=files)
                                    self.assertEqual(oracle.run(('KEYGL5.xml','values.tsv',*args), files=files), legacy)
                                    report['baseline_ascii_full_pp_cases'] += 1
                                if 'label_text' in settings:
                                    files['label.txt'] = settings['label_text'].encode('utf-8')
                                    output = oracle.run(('KEYGL5.xml','values.tsv',*args[:-1],'label-file','label.txt'), files=files)
                                    if label == 'Room': self.assertEqual(output, legacy)
                                else:
                                    output = oracle.run(('KEYGL5.xml','values.tsv',*args), files=files)
                            else:
                                output = mono('MONO_PATH=/input mono NativeEdltHVACProbe.exe KEYGL5.xml values.tsv '+shlex.join(args))
                            parsed = {line[3:].split('\t', 1)[0]: line.split('\t', 1)[1] for line in output.splitlines() if line.startswith('pp:')}
                            for line in output.splitlines():
                                if line.startswith('memory-static:'):
                                    index, value = line[14:].split('\t', 1); parsed['StaticTextString'+index] = value
                            native_expected = editor.snapshot(parsed)
                            self.assertEqual({k: (v, native_expected[k]) for k,v in after(plan).items() if v != native_expected[k]}, {})
                            self.assertEqual({key: native_expected[key] for key in editor.crcs(native_expected)}, editor.crcs(native_expected))
                            editor.apply(session, plan)
                            self.assertEqual(session.get_raw_data(0x220+(widget-1)*32, 32).lines[-1].split('RawData=')[1], literal.lower())
                            if plan.record[6] < 64:
                                index = plan.record[6]
                                self.assertEqual(session.get_raw_data(0x1100+index*64, 64).lines[-1].split('RawData=')[1], bytes(native_expected['StaticTextString'+str(index)]).hex())
                            session.save_to_source()
                        for action in ('save', 'close', 'load'): projects.operation(action, project)
                        client.command('NET LOAD DB '+project)
                        with programmer.load(network, '/db'+unit) as session: self.assertEqual(editor.snapshot(session.values()), native_expected)
                        report['cases'].append(dict(widget=widget, literal=literal, crcs=editor.crcs(native_expected), saved_reloaded=True,
                                                    label_text=settings.get('label_text'), label_file_used=oracle is not None and 'label_text' in settings, parameters_compared=len(native_expected)))
                    report['network_state'] = client.command('GET '+network+' state').lines
                    self.assertTrue(any('state=new' in line for line in report['network_state']))
                    report.update(passed=True, original_output=original,
                                  dll_sha256=hashlib.sha256((app/'CBusLogicModel.dll').read_bytes()).hexdigest())
                finally:
                    projects.operation('close', project); projects.operation('delete', project)
                    if os.environ.get('CBUS_EDLT_HVAC_REPORT'):
                        Path(os.environ['CBUS_EDLT_HVAC_REPORT']).write_text(json.dumps(report, indent=2)+'\n')


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'Set original Toolkit for HVAC probe input adapter acceptance')
class OriginalHVACProbeAdapterTests(unittest.TestCase):
    def test_preserved_baseline_vectors_and_strict_utf8_before_fixture_access(self):
        from research.original_oracle import OriginalModelOracle, selected_backend
        root=Path(__file__).resolve().parents[1]; app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        backend=selected_backend()
        with OriginalModelOracle(root/'research/NativeEdltHVACBaselineProbe.cs',app,backend=backend,references=('eDLT.dll',)) as baseline, \
             OriginalModelOracle(root/'research/NativeEdltHVACProbe.cs',app,backend=backend,references=('eDLT.dll',)) as oracle:
            before=baseline.run(); after_output=oracle.run(); self.assertEqual(before,after_output)
            # No specification or PP file is uploaded: invalid UTF-8 must fail
            # in the input adapter before the original fixture can read either.
            failure=oracle.run_result(('missing.xml','missing.tsv','6','42','4','2','1','38','label-file','label.txt'),files={'label.txt':b'\xc3'})
            self.assertEqual(failure.returncode,2)
            self.assertEqual(failure.stdout,'')
            self.assertEqual(failure.stderr.strip(),'Invalid UTF-8 label file')
            if os.environ.get('CBUS_EDLT_HVAC_ADAPTER_REPORT'):
                Path(os.environ['CBUS_EDLT_HVAC_ADAPTER_REPORT']).write_text(json.dumps({
                    'passed':True,'original_backend':backend,'zero_argument_output_lines':len(before.splitlines()),
                    'zero_argument_output_sha256':hashlib.sha256(before.encode()).hexdigest(),
                    'baseline_source_sha256':baseline.source_sha256,'extended_source_sha256':oracle.source_sha256,
                    'invalid_utf8_exit_code':failure.returncode,'invalid_utf8_rejected_before_fixture_access':True,
                },indent=2)+'\n')


if __name__ == '__main__': unittest.main()
