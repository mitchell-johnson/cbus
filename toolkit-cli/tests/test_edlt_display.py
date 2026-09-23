"""Original global display setters, full PP transformations and rollback."""
from dataclasses import replace
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError, _render
from cbus_toolkit.edlt_display import EdltDisplaySettings
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from tests.test_edlt import fixture as common_fixture, Session


def fixture():
    base = common_fixture(); params = dict(base.parameters)
    for name, address, kind, bit, size, default in (
        ('FontStyle', 0x118, 'int', 0, 3, 1), ('UseBigIcon', 0x118, 'bit', 4, 1, 1),
        ('EnableTimerFlash', 0x116, 'bit', 2, 1, 1), ('EnableFanControlLevelWrap', 0x117, 'bit', 5, 1, 1),
        ('OpaqueDisplayBits', 0x118, 'int', 5, 3, 5)):
        params[name] = ParameterSpec(name, kind, 'synthetic.xml', {'Name': name, 'Type': kind,
            'Address': hex(address), 'BitAddress': str(bit), 'BitSize': str(size), 'DefaultValue': str(default)})
    return UnitSpec(base.filename, base.metadata, base.sources, params)


class DisplaySettingsTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltDisplaySettings(self.spec); self.session = Session(self.spec)

    def test_all16_original_valid_combinations_and_unrelated_fields(self):
        original = self.editor.snapshot(self.session.values())
        for font, big, flash, wrap in itertools.product(('label', 'status'), (False, True), (False, True), (False, True)):
            plan = self.editor.plan(original, large_text=font, big_icons=big, timer_flash=flash, fan_level_wrap=wrap)
            after = {**plan.expected, **plan.changes}
            self.assertEqual((after['FontStyle'], after['UseBigIcon'], after['EnableTimerFlash'], after['EnableFanControlLevelWrap']),
                             ((1 if font == 'label' else 2,), (int(big),), (int(flash),), (int(wrap),)))
            self.assertEqual(after['OpaqueDisplayBits'], (5,))
            self.assertTrue(plan.as_dict()['applies_to_whole_unit'])
            for name, value in original.items():
                if name.startswith(('StaticTextString', 'Scene', 'Widget')) and name not in ('WidgetsCRC', 'ScenesCheckSum'):
                    self.assertEqual(after[name], value)

    def test_all_original_font_getters_preserve_omitted_raw_style_and_explicit_selection(self):
        for font in range(8):
            source = self.editor.snapshot(self.session.values()); source['FontStyle'] = (font,)
            plan = self.editor.plan(source, big_icons=False)
            self.assertEqual(plan.font_style, font)
            self.assertEqual(plan.as_dict()['large_text'], 'status' if font == 2 else 'label')
            self.assertEqual(plan.as_dict()['font_style_ui_canonical'], font in (1, 2))
            for option, value in (('label', 1), ('status', 2)):
                self.assertEqual(self.editor.plan(source, large_text=option).font_style, value)

    def test_normalization_changes_only_type_transitions_and_their_restore_levels(self):
        source = self.editor.snapshot(self.session.values())
        for widget in range(1, 22): source[f'Widget{widget}WidgetType'] = (0,)
        source['Widget6RestoreLevel'] = (106,); source['Widget7RestoreLevel'] = (107,)
        plan = self.editor.plan(source)
        self.assertEqual(plan.as_dict()['normalization_changes'], {'Widget6WidgetType': [255], 'Widget6RestoreLevel': [0]})
        after = {**source, **plan.changes}
        self.assertEqual(after['Widget7RestoreLevel'], (107,))
        self.assertFalse(self.editor.plan(after).changes)

    def test_existing_mra_globals_follow_first_widget_and_keep_each_status(self):
        source = self.editor.snapshot(self.session.values())
        for widget, kind, control in ((6, 7, 0x6d), (7, 8, 0xb2), (8, 9, 3)):
            source[f'Widget{widget}WidgetType'] = (kind,)
            source[f'Widget{widget}WidgetByteValue1'] = (control,)
        plan = self.editor.plan(source, timer_flash=False)
        after = {**source, **plan.changes}
        self.assertEqual([after[f'Widget{widget}WidgetByteValue1'][0] for widget in (6, 7, 8)], [0x6d, 0x6a, 0x6b])
        self.assertEqual((plan.mra_propagation.source_widget, plan.mra_propagation.multiplexer, plan.mra_propagation.zone), (6, 2, 6))
        self.assertEqual(plan.as_dict()['mra_propagation']['changes'],
                         {'Widget7WidgetByteValue1': [0x6a], 'Widget8WidgetByteValue1': [0x6b]})
        source['Widget6WidgetByteValue1'] = (0xed,)
        plan = self.editor.plan(source, timer_flash=False)
        self.assertFalse(plan.as_dict()['mra_propagation']['multiplexer_ui_canonical'])
        self.assertEqual(plan.mra_propagation.multiplexer, 4)
        self.assertEqual(plan.changes['Widget7WidgetByteValue1'], (0xea,))
        # Original save iterates all stored MRA records, including placements
        # that its new-widget UI does not offer.
        source['Widget1WidgetType'] = (7,)
        source['Widget1WidgetByteValue1'] = (0x25,)
        plan = self.editor.plan(source, big_icons=False)
        self.assertEqual(plan.mra_propagation.source_widget, 1)
        self.assertEqual(plan.mra_propagation.widgets, (1, 6, 7, 8))
        self.assertEqual(plan.changes['Widget6WidgetByteValue1'], (0x25,))
        self.assertEqual(plan.changes['Widget7WidgetByteValue1'], (0x22,))
        self.assertEqual(plan.changes['Widget8WidgetByteValue1'], (0x23,))

    def test_invalid_settings_schema_profile_and_forged_or_stale_plan(self):
        for options in ({'large_text': 'small'}, {'large_text': True}, {'big_icons': 1}, {'timer_flash': 'false'}, {'fan_level_wrap': 0}):
            with self.subTest(options=options), self.assertRaises(EdltError): self.editor.plan(self.session.values(), **options)
        with self.assertRaises(EdltError): EdltDisplaySettings(self.spec, firmware='5.4.00')
        params = dict(self.spec.parameters); field = params['FontStyle']
        params['FontStyle'] = replace(field, fields={**field.fields, 'BitAddress': '1'})
        with self.assertRaises(EdltError): EdltDisplaySettings(replace(self.spec, parameters=params))
        plan = self.editor.plan(self.session.values(), big_icons=False)
        with self.assertRaises(EdltError): self.editor.apply(self.session, replace(plan, big_icons=True))
        with self.assertRaises(EdltError): self.editor.apply(self.session, replace(plan, changes={**plan.changes, 'OpaqueDisplayBits': (0,)}))
        self.assertEqual(self.session.calls, [])
        self.session.current['OpaqueDisplayBits'] = (0,)
        with self.assertRaises(EdltError): self.editor.apply(self.session, plan)
        self.assertEqual(self.session.calls, [])

    def test_native_identity_guard_apply_and_verified_rollback(self):
        source = self.editor.snapshot(self.session.values())
        self.session.identity['FirmwareVersion'] = '5.4.00'
        with self.assertRaises(EdltError): self.editor.configure(self.session, big_icons=False)
        self.assertFalse(self.session.calls)
        self.session.identity['FirmwareVersion'] = '5.5.00'
        self.session.failure = 'UseBigIcon'
        with self.assertRaises(EdltApplyError) as caught: self.editor.configure(self.session, big_icons=False)
        self.assertTrue(caught.exception.details['rollback_verified'])
        self.assertEqual(self.editor.snapshot(self.session.values()), source)
        result = self.editor.configure(self.session, large_text='status', big_icons=False)
        self.assertTrue(result['verified']); self.assertFalse(result['saved'])

    def test_interrupt_and_disconnection_preserve_partial_state_without_recovery_io(self):
        for error in (KeyboardInterrupt(), SystemExit(7), ConnectionError('lost')):
            session = Session(self.spec); calls = []
            def fail(name, value):
                calls.append(name); session.current[name] = value; session.connected = False
                raise error
            session.set = fail
            expected = type(error) if not isinstance(error, Exception) else EdltApplyError
            with self.subTest(error=type(error).__name__), self.assertRaises(expected) as caught:
                self.editor.configure(session, large_text='status')
            self.assertEqual(len(calls), 1)
            if not isinstance(error, Exception):
                self.assertIs(caught.exception, error)
                self.assertEqual(error.edlt_display_evidence['attempted_parameters'], calls)
                self.assertTrue(error.edlt_display_evidence['pp_state_uncertain'])
            else:
                self.assertFalse(caught.exception.details['rollback_verified'])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'Set the original Toolkit executable for display model acceptance')
class OriginalDisplayTests(unittest.TestCase):
    def test_56_unchanged_original_getter_setter_vectors(self):
        app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        source = Path(__file__).resolve().parents[1] / 'research/NativeEdltDisplayProbe.cs'
        from research.original_oracle import OriginalModelOracle, selected_backend
        if selected_backend() == 'windows':
            with OriginalModelOracle(source, app, backend='windows', references=()) as oracle:
                original_output = oracle.run()
        else:
            with tempfile.TemporaryDirectory() as directory:
                Path(directory, source.name).write_bytes(source.read_bytes())
                result = subprocess.run(['docker', 'run', '--rm', '-v', str(app) + ':/input:ro', '-v', directory + ':/work', '-w', '/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5', 'sh', '-c',
                    'mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltDisplayProbe.cs && MONO_PATH=/input mono NativeEdltDisplayProbe.exe'],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            original_output = result.stdout
        lines = original_output.splitlines(); self.assertEqual(len(lines), 56)
        for line in lines:
            label, fields, label_state, status_state = line.split(':')
            values = {key: int(value, 0) for key, value in (item.split('=') for item in fields.split(','))}
            self.assertEqual(values['Untouched'], 173)
            if label.startswith('get-'):
                font = int(label[4:]); self.assertEqual(values['FontStyle'], font)
                self.assertEqual(label_state, 'label=' + str(font != 2)); self.assertEqual(status_state, 'status=' + str(font == 2))
            elif label.startswith(('label-', 'status-')):
                selector, font, value = label.split('-')
                expected = (1 if value == 'True' else 2) if selector == 'label' else (2 if value == 'True' else 1)
                self.assertEqual(values['FontStyle'], expected)
            else:
                self.assertEqual([values[name] for name in ('FontStyle', 'UseBigIcon', 'EnableTimerFlash', 'EnableFanControlLevelWrap')],
                                 list(map(int, label.split('-')[1])))


@unittest.skipUnless(all(os.environ.get(name) for name in ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')),
                     'Set native C-Gate, specifications and original Toolkit for full display acceptance')
class NativeDisplayTests(unittest.TestCase):
    def test_original_full_pp_all_combinations_omitted_fonts_mra_raw_bits_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects, NativeDatabase
        from cbus_toolkit.programming import Programmer
        root = Path(__file__).resolve().parents[1]
        app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve()
        editor = EdltDisplaySettings(UnitSpecStore(specs).load('KEYGL5.xml'))
        project = 'DP' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        report = {'passed': False, 'project': project, 'scope': 'Four unit-wide display fields, original save normalization/CRCs and database only', 'cases': []}
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'NativeEdltDisplayProbe.cs').write_bytes((root / 'research/NativeEdltDisplayProbe.cs').read_bytes())
            def mono(command):
                result = subprocess.run(['docker', 'run', '--rm', '-v', str(app) + ':/input:ro', '-v', str(specs) + ':/spec:ro',
                    '-v', directory + ':/work', '-w', '/work', 'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5',
                    'sh', '-c', command], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltDisplayProbe.cs', app, backend='windows', references=()) if backend == 'windows' else None
            if oracle is not None: self.addCleanup(oracle.close)
            else:mono('mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltDisplayProbe.cs')
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
                projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
                try:
                    database.create_network(project, 254, 'Display_CLI_Fixture', 'Cni', '127.0.0.1:1')
                    database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                    projects.operation('save', project)
                    with Programmer(client).load(network, source) as session:
                        for widget in range(1, 22): session.set(f'Widget{widget}WidgetType', '0')
                        for scene in range(1, 9): session.set(f'Scene{scene}StartAddress', '255')
                        session.set('ConfigVersionMajor', '1'); session.set('ConfigVersionMinor', '0')
                        original = editor.snapshot(session.values())
                        raw_base = bytes.fromhex(session.get_raw_data(0x116, 3).lines[-1].split('RawData=')[1])
                        def case(label, **options):
                            before = editor.snapshot(session.values()); plan = editor.plan(before, **options)
                            (folder / 'values.tsv').write_text(''.join(name + '\t' + (value if isinstance(value, str) else ' '.join(hex(n) for n in value)) + '\n' for name, value in before.items()))
                            font = 'keep' if options.get('large_text') is None else str(1 if options['large_text'] == 'label' else 2)
                            if oracle is not None:
                                output = oracle.run(('KEYGL5.xml', 'values.tsv', font, str(int(plan.big_icons)), str(int(plan.timer_flash)), str(int(plan.fan_level_wrap))), files={'KEYGL5.xml': (specs / 'KEYGL5.xml').read_bytes(), 'values.tsv': (folder / 'values.tsv').read_bytes()})
                            else:output = mono('MONO_PATH=/input mono NativeEdltDisplayProbe.exe /spec/KEYGL5.xml values.tsv ' +
                                ' '.join((font, str(int(plan.big_icons)), str(int(plan.timer_flash)), str(int(plan.fan_level_wrap)))))
                            observed = dict(line[3:].split('\t', 1) for line in output.splitlines() if line.startswith('pp:'))
                            self.assertEqual(editor.snapshot(observed), {**before, **plan.changes})
                            self.assertTrue(editor.apply(session, plan)['verified'])
                            raw = bytes.fromhex(session.get_raw_data(0x116, 3).lines[-1].split('RawData=')[1])
                            self.assertEqual(raw, bytes(((raw_base[0] & ~4) | int(plan.timer_flash) << 2,
                                (raw_base[1] & ~32) | int(plan.fan_level_wrap) << 5,
                                (raw_base[2] & ~23) | plan.font_style | int(plan.big_icons) << 4)))
                            report['cases'].append({'label': label, 'raw_hex': raw.hex(), 'parameters_compared': len(observed),
                                'crcs': {key: list(value) for key, value in editor.crcs({**before, **plan.changes}).items()}})
                            return plan
                        for font, big, flash, wrap in itertools.product(('label', 'status'), (False, True), (False, True), (False, True)):
                            case('valid-combination', large_text=font, big_icons=big, timer_flash=flash, fan_level_wrap=wrap)
                        for raw_font in range(8):
                            session.set('FontStyle', str(raw_font))
                            self.assertEqual(case('omitted-font-' + str(raw_font), big_icons=False).font_style, raw_font)
                        for widget, kind, control in ((6, 7, 0x6d), (7, 8, 0xb2), (8, 9, 3)):
                            session.set(f'Widget{widget}WidgetType', str(kind))
                            session.set(f'Widget{widget}WidgetByteValue1', str(control))
                        plan = case('mra-first-widget-propagation', large_text='status', timer_flash=False)
                        self.assertEqual((plan.mra_propagation.multiplexer, plan.mra_propagation.zone), (2, 6))
                        applied = editor.snapshot(session.values())
                        self.assertEqual([applied[f'Widget{widget}WidgetByteValue1'][0] for widget in (6, 7, 8)], [0x6d, 0x6a, 0x6b])
                        session.set('Widget6WidgetByteValue1', str(0xed))
                        plan = case('mra-stored-multiplexer3-preserved', big_icons=True)
                        self.assertFalse(plan.as_dict()['mra_propagation']['multiplexer_ui_canonical'])
                        applied = editor.snapshot(session.values())
                        self.assertEqual([applied[f'Widget{widget}WidgetByteValue1'][0] for widget in (6, 7, 8)], [0xed, 0xea, 0xeb])
                        session.set('Widget1WidgetType', '7')
                        session.set('Widget1WidgetByteValue1', str(0x25))
                        plan = case('mra-stored-standby-placement-preserved', timer_flash=True)
                        self.assertEqual(plan.mra_propagation.source_widget, 1)
                        final = editor.snapshot(session.values())
                        self.assertEqual([final[f'Widget{widget}WidgetByteValue1'][0] for widget in (1, 6, 7, 8)], [0x25, 0x25, 0x22, 0x23])
                        for name, value in original.items():
                            if name.startswith('StaticTextString') or (name.startswith('Scene') and name != 'ScenesCheckSum'):
                                self.assertEqual(final[name], value)
                        session.save_to_source()
                    for action in ('save', 'close', 'load'): projects.operation(action, project)
                    with Programmer(client).load(network, source) as session: self.assertEqual(editor.snapshot(session.values()), final)
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    report.update(passed=True, saved_reloaded=True, network_state='new', physical_device_verified=False)
                finally:
                    projects.operation('close', project); projects.operation('delete', project)
        runtime = root / 'research/runtime'; runtime.mkdir(parents=True, exist_ok=True)
        path = Path(os.environ.get('CBUS_EDLT_DISPLAY_REPORT', runtime / 'edlt-display-report.json'))
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(report, indent=2) + '\n')
