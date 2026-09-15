"""Original general settings: UI time lists, PP state, native CRCs and persistence."""
from dataclasses import replace
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_general import EdltGeneralSettings
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from tests.test_edlt import fixture as common_fixture, Session


def fixture():
    base = common_fixture(); params = dict(base.parameters)
    for name, address, kind, bit, size, default in (
        ('LongPressTime', 0x114, 'int', 0, 8, 16), ('DebounceTime', 0x115, 'int', 0, 8, 3),
        ('StatusRequestInterval', 0x112, 'int', 0, 8, 3), ('ToolsPageLocked', 0x11a, 'bit', 4, 1, 0),
        ('EnableLevelStore', 0x116, 'bit', 1, 1, 0), ('OpaqueGeneralBits', 0x11a, 'int', 5, 3, 5)):
        params[name] = ParameterSpec(name, kind, 'synthetic.xml', {'Name': name, 'Type': kind,
            'Address': hex(address), 'BitAddress': str(bit), 'BitSize': str(size), 'DefaultValue': str(default)})
    return UnitSpec(base.filename, base.metadata, base.sources, params)


class GeneralSettingsTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltGeneralSettings(self.spec); self.session = Session(self.spec)

    def test_all_ui_time_codes_and_interval_bounds_preserve_other_settings(self):
        original = self.editor.snapshot(self.session.values())
        for code in range(256):
            plan = self.editor.plan(original, debounce_ms=25 * code,
                                    long_press_ms=25 * code if code else None)
            after = {**original, **plan.changes}
            self.assertEqual(after['DebounceTime'], (code,))
            self.assertEqual(after['LongPressTime'], (code if code else 16,))
            self.assertEqual(after['OpaqueGeneralBits'], (5,))
            self.assertEqual(after['EnableLevelStore'], original['EnableLevelStore'])
        for seconds in range(3, 256):
            self.assertEqual(self.editor.plan(original, status_report_seconds=seconds).status_report_seconds, seconds)

    def test_modes_preserve_widget_restores_and_omitted_noncanonical_values(self):
        original = self.editor.snapshot(self.session.values())
        for widget in range(6, 22): original[f'Widget{widget}RestoreLevel'] = (100 + widget,)
        for raw in range(3):
            source = {**original, 'LongPressTime': (0,), 'StatusRequestInterval': (raw,)}
            for locked, mode in itertools.product((False, True), ('previous', 'preset')):
                plan = self.editor.plan(source, tools_page_locked=locked, power_restore=mode)
                after = {**source, **plan.changes}
                self.assertEqual(plan.power_restore, mode); self.assertEqual(plan.tools_page_locked, locked)
                self.assertEqual(after['EnableLevelStore'], (int(mode == 'previous'),))
                self.assertFalse(plan.as_dict()['long_press_ui_canonical'])
                self.assertFalse(plan.as_dict()['status_report_ui_canonical'])
                self.assertEqual((plan.long_press_ms, plan.status_report_seconds), (0, raw))
                for widget in range(6, 22): self.assertEqual(after[f'Widget{widget}RestoreLevel'], (100 + widget,))
                self.assertFalse(plan.as_dict()['power_cycle_verified'])

    def test_original_normalization_resets_only_changed_blank_types_and_propagates_stored_mra(self):
        source = self.editor.snapshot(self.session.values())
        for widget in range(1, 22): source[f'Widget{widget}WidgetType'] = (0,)
        source['Widget6RestoreLevel'] = (123,)
        plan = self.editor.plan(source, tools_page_locked=True)
        self.assertEqual(plan.as_dict()['normalization_changes'], {'Widget6WidgetType': [255], 'Widget6RestoreLevel': [0]})
        source.update({'Widget1WidgetType': (7,), 'Widget1WidgetByteValue1': (0xed,),
                       'Widget6WidgetType': (8,), 'Widget6WidgetByteValue1': (2,)})
        plan = self.editor.plan(source, power_restore='previous')
        self.assertEqual(plan.mra_propagation.source_widget, 1)
        self.assertFalse(plan.mra_propagation.as_dict()['multiplexer_ui_canonical'])
        self.assertEqual(plan.changes['Widget6WidgetByteValue1'], (0xea,))

    def test_invalid_input_schema_identity_forged_and_stale_plan(self):
        for option in ({'long_press_ms': 0}, {'long_press_ms': 24}, {'long_press_ms': 6376}, {'long_press_ms': True},
                       {'debounce_ms': 26}, {'debounce_ms': -25}, {'status_report_seconds': 2},
                       {'status_report_seconds': 256}, {'tools_page_locked': 1}, {'power_restore': 'off'}):
            with self.subTest(option=option), self.assertRaises(EdltError): self.editor.plan(self.session.values(), **option)
        with self.assertRaises(EdltError): EdltGeneralSettings(self.spec, firmware='5.4.00')
        params = dict(self.spec.parameters); field = params['ToolsPageLocked']
        params['ToolsPageLocked'] = replace(field, fields={**field.fields, 'BitAddress': '3'})
        with self.assertRaises(EdltError): EdltGeneralSettings(replace(self.spec, parameters=params))
        plan = self.editor.plan(self.session.values(), tools_page_locked=True)
        for forged in (replace(plan, tools_page_locked=1), replace(plan, long_press_ms=True),
                       replace(plan, changes={**plan.changes, 'OpaqueGeneralBits': (0,)})):
            with self.assertRaises(EdltError): self.editor.apply(self.session, forged)
        self.session.identity['FirmwareVersion'] = '5.4.00'
        with self.assertRaises(EdltError): self.editor.apply(self.session, plan)
        self.session.identity['FirmwareVersion'] = '5.5.00'; self.session.current['LongPressTime'] = (30,)
        with self.assertRaises(EdltError): self.editor.apply(self.session, plan)
        self.assertFalse(self.session.calls)

    def test_rollback_interruption_and_lost_connection(self):
        original = self.editor.snapshot(self.session.values()); self.session.failure = 'ToolsPageLocked'
        with self.assertRaises(EdltApplyError) as caught:
            self.editor.configure(self.session, long_press_ms=1000, tools_page_locked=True)
        self.assertTrue(caught.exception.details['rollback_verified'])
        self.assertEqual(self.editor.snapshot(self.session.values()), original)
        for error in (KeyboardInterrupt(), SystemExit(7), ConnectionError('lost')):
            session = Session(self.spec); calls = []
            def fail(name, value):
                calls.append(name); session.current[name] = value; session.connected = False
                raise error
            session.set = fail
            expected = type(error) if not isinstance(error, Exception) else EdltApplyError
            with self.subTest(error=type(error).__name__), self.assertRaises(expected) as caught:
                self.editor.configure(session, long_press_ms=1000)
            self.assertEqual(len(calls), 1)
            if not isinstance(error, Exception):
                self.assertIs(caught.exception, error)
                self.assertEqual(error.edlt_general_evidence['attempted_parameters'], calls)
                self.assertTrue(error.edlt_general_evidence['pp_state_uncertain'])
            else:
                self.assertFalse(caught.exception.details['rollback_verified'])

    def test_interrupted_rollback_retains_original_error_and_stops_recovery(self):
        original_error = RuntimeError('SET failed after partial application')
        interrupted = KeyboardInterrupt('rollback interrupted'); calls = []
        def fail(name, value):
            calls.append(name)
            if len(calls) == 1:
                self.session.current[name] = value
                raise original_error
            raise interrupted
        self.session.set = fail
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.editor.configure(self.session, long_press_ms=1000)
        self.assertIs(caught.exception, interrupted); self.assertEqual(len(calls), 2)
        evidence = interrupted.edlt_general_evidence
        self.assertEqual(evidence['attempted_parameters'], [calls[0]])
        self.assertEqual(evidence['original_error'], {'type': 'RuntimeError', 'error': str(original_error)})
        self.assertEqual(evidence['rollback_errors'], [])
        self.assertTrue(evidence['pp_state_uncertain']); self.assertFalse(evidence['saved'])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'Set original Toolkit for general-settings model acceptance')
class OriginalGeneralTests(unittest.TestCase):
    def test_all_original_timing_lists_scalar_codes_and_complementary_restore_radios(self):
        app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        source = Path(__file__).resolve().parents[1] / 'research/NativeEdltGeneralProbe.cs'
        from research.original_oracle import OriginalModelOracle, selected_backend
        if selected_backend() == 'windows':
            with OriginalModelOracle(source, app, backend='windows') as oracle:
                output = oracle.run()
        else:
            with tempfile.TemporaryDirectory() as directory:
                Path(directory, source.name).write_bytes(source.read_bytes())
                result = subprocess.run(['docker', 'run', '--rm', '-v', str(app) + ':/input:ro', '-v', directory + ':/work', '-w', '/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5', 'sh', '-c',
                    'mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltGeneralProbe.cs && MONO_PATH=/input mono NativeEdltGeneralProbe.exe'],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = result.stdout
        lines = output.splitlines(); self.assertEqual(len(lines), 773)
        for name, first in (('long-list', 1), ('debounce-list', 0)):
            actual = [line for line in lines if line.startswith(name + ':')]
            self.assertEqual(actual, [f'{name}:{code}:{code * 25} ms' for code in range(first, 256)])
        self.assertEqual([line for line in lines if line.startswith('scalars:')],
                         [f'scalars:{code}:{code}:{code}:{0 if code == 0 else max(code, 3)}:173' for code in range(256)])
        for label in ('enable', 'disable'):
            for value in (False, True):
                enabled = value if label == 'enable' else not value
                self.assertIn(f'{label}:{value}:{int(enabled)}:{enabled}:{not enabled}', lines)
        self.assertIn('locked:False:0', lines); self.assertIn('locked:True:1', lines)


@unittest.skipUnless(all(os.environ.get(name) for name in ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')),
                     'Set native C-Gate, specifications and original Toolkit for general-settings acceptance')
class NativeGeneralTests(unittest.TestCase):
    def test_original_full_pp_boundaries_raw_preservation_mra_and_native_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects, NativeDatabase
        from cbus_toolkit.programming import Programmer
        root = Path(__file__).resolve().parents[1]; app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve(); editor = EdltGeneralSettings(UnitSpecStore(specs).load('KEYGL5.xml'))
        project = 'GN' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend()
        report = {'passed': False, 'scope': 'General settings; original save normalization, CRCs and database only', 'cases': [], 'original_backend': backend}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); (folder / 'NativeEdltGeneralProbe.cs').write_bytes((root / 'research/NativeEdltGeneralProbe.cs').read_bytes())
            def mono(command):
                result = subprocess.run(['docker', 'run', '--rm', '-v', str(app) + ':/input:ro', '-v', str(specs) + ':/spec:ro',
                    '-v', directory + ':/work', '-w', '/work', 'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5',
                    'sh', '-c', command], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr); return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltGeneralProbe.cs', app, backend='windows') if backend == 'windows' else None
            if oracle is not None:self.addCleanup(oracle.close)
            else:mono('mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltGeneralProbe.cs')
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
                projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
                try:
                    database.create_network(project, 254, 'General_Fixture', 'Cni', '127.0.0.1:1')
                    database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL'); projects.operation('save', project)
                    with Programmer(client).load(network, source) as session:
                        for widget in range(1, 22): session.set(f'Widget{widget}WidgetType', '0')
                        for widget in range(6, 22): session.set(f'Widget{widget}RestoreLevel', str(100 + widget))
                        for scene in range(1, 9): session.set(f'Scene{scene}StartAddress', '255')
                        session.set('ConfigVersionMajor', '1'); session.set('ConfigVersionMinor', '0')
                        original = editor.snapshot(session.values())
                        def case(label, **options):
                            before = editor.snapshot(session.values()); plan = editor.plan(before, **options)
                            (folder / 'values.tsv').write_text(''.join(name + '\t' + (value if isinstance(value, str) else ' '.join(hex(n) for n in value)) + '\n' for name, value in before.items()))
                            args = [str(options[name] // divisor) if options.get(name) is not None else 'keep'
                                    for name, divisor in (('long_press_ms', 25), ('debounce_ms', 25), ('status_report_seconds', 1))]
                            args += [str(int(options['tools_page_locked'])) if options.get('tools_page_locked') is not None else 'keep',
                                     str(int(options['power_restore'] == 'previous')) if options.get('power_restore') is not None else 'keep']
                            if oracle is not None:
                                output = oracle.run(('KEYGL5.xml', 'values.tsv', *args), files={'KEYGL5.xml': (specs / 'KEYGL5.xml').read_bytes(), 'values.tsv': (folder / 'values.tsv').read_bytes()})
                            else:output = mono('MONO_PATH=/input mono NativeEdltGeneralProbe.exe /spec/KEYGL5.xml values.tsv ' + ' '.join(args))
                            observed = dict(line[3:].split('\t', 1) for line in output.splitlines() if line.startswith('pp:'))
                            self.assertEqual(editor.snapshot(observed), {**before, **plan.changes})
                            self.assertTrue(editor.apply(session, plan)['verified'])
                            raw = bytes.fromhex(session.get_raw_data(0x112, 9).lines[-1].split('RawData=')[1])
                            self.assertEqual((raw[0], raw[2], raw[3], (raw[4] >> 1) & 1, (raw[8] >> 4) & 1),
                                (plan.status_report_seconds, plan.long_press_ms // 25, plan.debounce_ms // 25,
                                 int(plan.power_restore == 'previous'), int(plan.tools_page_locked)))
                            report['cases'].append({'label': label, 'raw_hex': raw.hex(), 'parameters_compared': len(observed),
                                'crcs': {key: list(value) for key, value in editor.crcs({**before, **plan.changes}).items()}})
                            return plan
                        for long, debounce, status, locked, mode in itertools.product((25, 6375), (0, 6375), (3, 255), (False, True), ('previous', 'preset')):
                            case('boundary-combination', long_press_ms=long, debounce_ms=debounce, status_report_seconds=status,
                                 tools_page_locked=locked, power_restore=mode)
                        for raw in range(3):
                            session.set('LongPressTime', '0'); session.set('StatusRequestInterval', str(raw))
                            plan = case('omitted-raw-' + str(raw), power_restore='previous')
                            self.assertEqual((plan.long_press_ms, plan.status_report_seconds), (0, raw))
                        for widget, kind, control in ((1, 7, 0xed), (6, 8, 2), (7, 9, 0)):
                            session.set(f'Widget{widget}WidgetType', str(kind)); session.set(f'Widget{widget}WidgetByteValue1', str(control))
                        plan = case('stored-mra-propagation', tools_page_locked=True)
                        self.assertEqual(plan.changes['Widget6WidgetByteValue1'], (0xea,))
                        final = editor.snapshot(session.values())
                        for name, value in original.items():
                            if name.startswith('StaticTextString') or (name.startswith('Scene') and name != 'ScenesCheckSum'):
                                self.assertEqual(final[name], value)
                        for widget in range(7, 22): self.assertEqual(final[f'Widget{widget}RestoreLevel'], (100 + widget,) if widget != 8 else (0,))
                        session.save_to_source()
                    for action in ('save', 'close', 'load'): projects.operation(action, project)
                    with Programmer(client).load(network, source) as session: self.assertEqual(editor.snapshot(session.values()), final)
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    report.update(passed=True, saved_reloaded=True, physical_device_verified=False, power_cycle_verified=False)
                finally:
                    projects.operation('close', project); projects.operation('delete', project)
        runtime = root / 'research/runtime'; runtime.mkdir(parents=True, exist_ok=True)
        (runtime / 'edlt-general-report.json').write_text(json.dumps(report, indent=2) + '\n')
