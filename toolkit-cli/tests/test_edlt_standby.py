"""Independent original standby setters, field masks and full native save."""
from dataclasses import replace
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_standby import EdltStandby, DESTINATIONS, NIGHTLIGHT_COLOURS
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from tests.test_edlt import fixture as common_fixture, Session


def fixture():
    base = common_fixture(); params = dict(base.parameters)
    for name, address, kind, bit, size, default in (
        ('ActivityDuration', 0x11B, 'int', 0, 8, 30), ('TimeoutPage', 0x11A, 'int', 5, 2, 2),
        ('EnableNightlightUserKey', 0x116, 'bit', 6, 1, 0), ('EnableNightlightPageKey', 0x116, 'bit', 7, 1, 0),
        ('NightlightColour', 0x117, 'int', 3, 2, 1),
        ('OpaqueNightlightBits', 0x117, 'int', 5, 3, 5), ('HiddenBrightness', 0x112, 'int', 0, 8, 91)):
        params[name] = ParameterSpec(name, kind, 'synthetic.xml', {'Name': name, 'Type': kind,
            'Address': hex(address), 'BitAddress': str(bit), 'BitSize': str(size), 'DefaultValue': str(default)})
    return UnitSpec(base.filename, base.metadata, base.sources, params)


class StandbyTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltStandby(self.spec); self.session = Session(self.spec)

    def test_original_enable_setter12_literal_outcomes_and_omitted_delay(self):
        for duration, disabled, enabled in ((0, 0, 3), (1, 0, 1), (2, 0, 3), (3, 0, 3), (30, 0, 3), (255, 0, 3)):
            source = self.editor.snapshot(self.session.values()); source['ActivityDuration'] = (duration,)
            for option, expected in ((None, duration), (False, disabled), (True, enabled)):
                with self.subTest(duration=duration, enabled=option):
                    self.assertEqual(self.editor.plan(source, enabled=option).activity_duration, expected)
            self.assertEqual(self.editor.plan(source, enabled=True, after_seconds=255).activity_duration, 255)

    def test_choices_boundaries_and_hidden_nightlight_preservation(self):
        original = self.editor.snapshot(self.session.values())
        for seconds, destination, user, page, colour in itertools.product((1, 255), DESTINATIONS, (False, True), (False, True), NIGHTLIGHT_COLOURS):
            if not (user or page): continue
            plan = self.editor.plan(original, after_seconds=seconds, destination=destination,
                nightlight_user_keys=user, nightlight_page_key=page, nightlight_colour=colour)
            after = {**original, **plan.changes}
            self.assertEqual((after['ActivityDuration'], after['TimeoutPage'], after['EnableNightlightUserKey'], after['EnableNightlightPageKey'], after['NightlightColour']),
                ((seconds,), (DESTINATIONS[destination],), (int(user),), (int(page),), (NIGHTLIGHT_COLOURS[colour],)))
            self.assertEqual((after['HiddenBrightness'], after['OpaqueNightlightBits']), ((91,), (5,)))
            for name, value in original.items():
                if name.startswith(('StaticTextString', 'Scene', 'ConfigVersion')) and name not in ('ScenesCheckSum',): self.assertEqual(after[name], value)
        source = {**original, 'TimeoutPage': (3,), 'EnableNightlightUserKey': (1,), 'NightlightColour': (3,)}
        plan = self.editor.plan(source, enabled=False)
        self.assertFalse(plan.as_dict()['enabled']); self.assertFalse(plan.as_dict()['timeout_page_ui_canonical'])
        self.assertIsNone(plan.as_dict()['timeout_page']); self.assertEqual(plan.nightlight_colour, 'quick-status-colour')
        self.assertTrue(plan.nightlight_user_keys); self.assertFalse(plan.as_dict()['nightlight_colour_control_enabled'])

    def test_visible_dependencies_and_strict_arguments(self):
        disabled = self.editor.snapshot(self.session.values()); disabled['ActivityDuration'] = (0,)
        for options in ({'after_seconds': 1}, {'destination': 'page-1'}, {'nightlight_user_keys': True}, {'nightlight_page_key': False}, {'nightlight_colour': 'off-colour'}):
            with self.subTest(options=options), self.assertRaisesRegex(EdltError, 'Standby must be enabled'):
                self.editor.plan(disabled, **options)
        invalid = ({'enabled': 1}, {'nightlight_user_keys': 0}, {'nightlight_page_key': 'false'}, {'after_seconds': 0},
            {'after_seconds': 256}, {'after_seconds': True}, {'after_seconds': 1.0}, {'destination': 3}, {'destination': 'page-2'},
            {'nightlight_colour': 'red'}, {'nightlight_colour': True}, {'enabled': False, 'after_seconds': 5},
            {'nightlight_user_keys': False, 'nightlight_page_key': False, 'nightlight_colour': 'off-colour'})
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(EdltError): self.editor.plan(self.session.values(), **options)
        # The original page-key checkbox has no multipage dependency.
        source = self.editor.snapshot(self.session.values()); source['NavWidgetType'] = (0,)
        self.assertTrue(self.editor.plan(source, nightlight_page_key=True, nightlight_colour='page-key-colour').nightlight_page_key)

    def test_shared_original_mra_and_terminator_normalization(self):
        source = self.editor.snapshot(self.session.values())
        for widget in range(1, 22): source[f'Widget{widget}WidgetType'] = (0,)
        source['Widget6RestoreLevel'] = (106,); source['Widget7RestoreLevel'] = (107,)
        plan = self.editor.plan(source)
        self.assertEqual(plan.as_dict()['normalization_changes'], {'Widget6WidgetType': [255], 'Widget6RestoreLevel': [0]})
        after = {**source, **plan.changes}; self.assertEqual(after['Widget7RestoreLevel'], (107,))
        self.assertFalse(self.editor.plan(after).changes)
        for widget, kind, control in ((1, 7, 0xe5), (6, 8, 0xb2), (7, 9, 3)):
            source[f'Widget{widget}WidgetType'] = (kind,); source[f'Widget{widget}WidgetByteValue1'] = (control,)
        plan = self.editor.plan(source, after_seconds=7)
        self.assertEqual(plan.changes['Widget6WidgetByteValue1'], (0xe2,)); self.assertEqual(plan.changes['Widget7WidgetByteValue1'], (0xe3,))
        self.assertFalse(plan.mra_propagation.as_dict()['multiplexer_ui_canonical'])

    def test_schema_profile_canonical_stale_and_database_guards(self):
        with self.assertRaises(EdltError): EdltStandby(self.spec, firmware='5.4.00')
        params = dict(self.spec.parameters); attr = params['TimeoutPage']
        params['TimeoutPage'] = replace(attr, fields={**attr.fields, 'BitAddress': '4'})
        with self.assertRaises(EdltError): EdltStandby(replace(self.spec, parameters=params))
        plan = self.editor.plan(self.session.values(), after_seconds=20)
        for forged in (replace(plan, activity_duration=5), replace(plan, changes={**plan.changes, 'HiddenBrightness': (0,)}), replace(plan, options={'enabled': 1})):
            with self.assertRaises(EdltError): self.editor.apply(self.session, forged)
        self.assertEqual(self.session.calls, [])
        self.session.current['HiddenBrightness'] = (0,)
        with self.assertRaises(EdltError): self.editor.apply(self.session, plan)
        self.session.source = '//NOTADB/254/p/20'
        with self.assertRaises(EdltError): self.editor.configure(self.session, after_seconds=20)
        self.assertEqual(self.session.calls, [])

    def test_forged_boolean_integer_equivalence_rejected_before_io(self):
        plan = self.editor.plan(self.session.values(), after_seconds=1, destination='current', nightlight_user_keys=True)
        for forged in (replace(plan, activity_duration=True), replace(plan, destination_raw=True),
                       replace(plan, nightlight_user_keys=1), replace(plan, nightlight_page_key=0)):
            with self.subTest(forged=forged), self.assertRaises(EdltError): self.editor.apply(self.session, forged)
        self.assertFalse(self.session.calls)

    def test_identity_apply_and_verified_rollback(self):
        before = self.editor.snapshot(self.session.values())
        self.session.identity['FirmwareVersion'] = '5.4.00'
        with self.assertRaises(EdltError): self.editor.configure(self.session, after_seconds=5)
        self.assertFalse(self.session.calls); self.session.identity['FirmwareVersion'] = '5.5.00'
        self.session.failure = 'ActivityDuration'
        with self.assertRaises(EdltApplyError) as caught: self.editor.configure(self.session, after_seconds=5)
        self.assertTrue(caught.exception.details['rollback_verified']); self.assertEqual(self.editor.snapshot(self.session.values()), before)
        self.assertTrue(self.editor.configure(self.session, after_seconds=5)['verified'])

    def test_interrupted_apply_and_disconnect_perform_no_recovery_io(self):
        for error in (KeyboardInterrupt(), SystemExit(7), ConnectionError('lost')):
            session = Session(self.spec); calls = []
            def fail(name, value):
                calls.append(name); session.current[name] = value; session.connected = False; raise error
            session.set = fail
            with self.assertRaises(type(error) if not isinstance(error, Exception) else EdltApplyError) as caught:
                self.editor.configure(session, after_seconds=5)
            self.assertEqual(calls, ['Application'])
            if not isinstance(error, Exception):
                self.assertIs(caught.exception, error); self.assertTrue(error.edlt_standby_evidence['pp_state_uncertain'])
                self.assertEqual(error.edlt_standby_evidence['attempted_parameters'], calls)
            else: self.assertFalse(caught.exception.details['rollback_verified'])

    def test_rollback_interruption_keeps_original_failure(self):
        interruption = KeyboardInterrupt(); calls = []
        def fail(name, value):
            calls.append(name)
            if len(calls) == 1: raise RuntimeError('primary mutation failure')
            raise interruption
        self.session.set = fail
        with self.assertRaises(KeyboardInterrupt) as caught: self.editor.configure(self.session, after_seconds=5)
        self.assertIs(caught.exception, interruption); self.assertEqual(calls, ['Application', 'Application'])
        self.assertEqual(interruption.edlt_standby_evidence['original_error']['error'], 'primary mutation failure')


ROOT = Path(__file__).resolve().parents[1]
MONO = 'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5'


def mono(test, folder, command, *, specs=None):
    app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
    argv = ['docker', 'run', '--rm', '--network', 'none', '-v', str(app) + ':/input:ro', '-v', str(folder) + ':/work', '-w', '/work']
    if specs: argv += ['-v', str(specs) + ':/spec:ro']
    result = subprocess.run(argv + [MONO, 'sh', '-c', command], capture_output=True, text=True, timeout=60)
    test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    return result.stdout


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'Set original Toolkit for standby setter acceptance')
class OriginalStandbyTests(unittest.TestCase):
    def test_original84_model_vectors_and_offered_standby_choices(self):
        from research.original_oracle import OriginalModelOracle, selected_backend
        if selected_backend() == 'windows':
            with OriginalModelOracle(ROOT / 'research/NativeEdltStandbyProbe.cs', Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent, backend='windows') as oracle:
                output = oracle.run()
        else:
            with tempfile.TemporaryDirectory() as directory:
                folder = Path(directory); (folder / 'NativeEdltStandbyProbe.cs').write_bytes((ROOT / 'research/NativeEdltStandbyProbe.cs').read_bytes())
                output = mono(self, folder, 'mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltStandbyProbe.cs && MONO_PATH=/input mono NativeEdltStandbyProbe.exe')
        rows = dict(line.split(':', 1) for line in output.splitlines()); self.assertEqual(len(rows), 84)
        self.assertEqual(rows['choices-NightlightColourVariants'], '0=Off Colour|1=On Colour|2=Page Key Colour|3=Quick Status Colour')
        self.assertEqual(rows['choices-TimeoutPage'], '0=Page 1|2=Standby Page')
        self.assertEqual([int(item.split('=')[0]) for item in rows['choices-ActivityDuration'].split('|')], list(range(1, 256)))
        editor = EdltStandby(fixture()); source = editor.snapshot(fixture().defaults())
        for initial in (0, 1, 2, 3, 30, 255):
            for enabled in (False, True):
                values = dict(item.split('=') for item in rows[f'standby-{initial}-{int(enabled)}'].split('|'))
                plan = editor.plan({**source, 'ActivityDuration': (initial,)}, enabled=enabled)
                self.assertEqual(plan.activity_duration, int(values['ActivityDuration']))
                self.assertEqual((values['TimeoutPage'], values['NightlightColour']), ('2', '1'))
        for initial in (0, 1, 2, 3, 255):
            for value in (0, 1):
                for kind, expected in (('stay', 1 if value else 2), ('change', 2 if value else 1)):
                    fields = dict(item.split('=') for item in rows[f'{kind}-{initial}-{value}'].split('|'))
                    self.assertEqual(int(fields['TimeoutPage']), expected)
        for user, page in itertools.product((0, 1), repeat=2): self.assertEqual(rows[f'nightlight-{user}-{page}'], str(bool(user or page)))
        runtime = ROOT / 'research/runtime/edlt-standby'; runtime.mkdir(parents=True, exist_ok=True)
        path = Path(os.environ.get('CBUS_EDLT_STANDBY_VECTOR_REPORT', runtime / 'original-vectors.txt'))
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(output)


@unittest.skipUnless(all(os.environ.get(name) for name in ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')),
                     'Set native C-Gate, specifications and original Toolkit for full standby acceptance')
class NativeStandbyTests(unittest.TestCase):
    def test_original_full_pp_raw_masks_boundaries_hidden_fields_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects, NativeDatabase
        from cbus_toolkit.programming import Programmer
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve(); editor = EdltStandby(UnitSpecStore(specs).load('KEYGL5.xml'))
        project = 'SB' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        report = {'passed': False, 'project': project, 'cases': [], 'scope': 'Standby settings, original direct before-save and native database only'}
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); (folder / 'NativeEdltStandbyProbe.cs').write_bytes((ROOT / 'research/NativeEdltStandbyProbe.cs').read_bytes())
            oracle = OriginalModelOracle(ROOT / 'research/NativeEdltStandbyProbe.cs', Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent, backend='windows') if backend == 'windows' else None
            if oracle is not None: self.addCleanup(oracle.close)
            else:mono(self, folder, 'mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltStandbyProbe.cs')
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
                projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
                projects.operation('save', project)
                try:
                    database.create_network(project, 254, 'Standby_CLI_Fixture', 'Cni', '127.0.0.1:1')
                    database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                    with Programmer(client).load(network, source) as session:
                        for widget in range(1, 22): session.set(f'Widget{widget}WidgetType', '0')
                        for scene in range(1, 9): session.set(f'Scene{scene}StartAddress', '255')
                        original = editor.snapshot(session.values())
                        def case(label, **options):
                            before = editor.snapshot(session.values()); plan = editor.plan(before, **options)
                            raw_base = bytes.fromhex(session.get_raw_data(0x116, 6).lines[-1].split('RawData=')[1])
                            (folder / 'values.tsv').write_text(''.join(name + '\t' + (value if isinstance(value, str) else ' '.join(hex(n) for n in value)) + '\n' for name, value in before.items()))
                            args = []
                            for name in ('enabled', 'after_seconds', 'destination', 'nightlight_user_keys', 'nightlight_page_key', 'nightlight_colour'):
                                value = options.get(name)
                                if value is None: args.append('keep')
                                elif name == 'destination': args.append(str(DESTINATIONS[value]))
                                elif name == 'nightlight_colour': args.append(str(NIGHTLIGHT_COLOURS[value]))
                                else: args.append(str(int(value)))
                            if oracle is not None:
                                output = oracle.run(('KEYGL5.xml', 'values.tsv', *args), files={'KEYGL5.xml': (specs / 'KEYGL5.xml').read_bytes(), 'values.tsv': (folder / 'values.tsv').read_bytes()})
                            else:output = mono(self, folder, 'MONO_PATH=/input mono NativeEdltStandbyProbe.exe /spec/KEYGL5.xml values.tsv ' + ' '.join(args), specs=specs)
                            observed = dict(line[3:].split('\t', 1) for line in output.splitlines() if line.startswith('pp:'))
                            after = {**before, **plan.changes}; self.assertEqual(editor.snapshot(observed), after, label)
                            self.assertTrue(editor.apply(session, plan)['verified'])
                            raw = bytes.fromhex(session.get_raw_data(0x116, 6).lines[-1].split('RawData=')[1])
                            expected = bytearray(raw_base)
                            expected[0] = (expected[0] & 0x3f) | int(plan.nightlight_user_keys) << 6 | int(plan.nightlight_page_key) << 7
                            expected[1] = (expected[1] & 0xe7) | NIGHTLIGHT_COLOURS[plan.nightlight_colour] << 3
                            expected[4] = (expected[4] & 0x9f) | plan.destination_raw << 5; expected[5] = plan.activity_duration
                            self.assertEqual(raw, bytes(expected), label)
                            for name, value in before.items():
                                if name.startswith(('StaticTextString', 'Scene', 'ConfigVersion')) and name != 'ScenesCheckSum': self.assertEqual(after[name], value)
                            report['cases'].append({'label': label, 'raw_hex': raw.hex(), 'parameters_compared': len(observed), 'crcs': {name: list(value) for name, value in editor.crcs(after).items()}})
                            return plan
                        case('omitted-defaults')
                        for initial in (0, 1, 2, 3, 30, 255):
                            for enabled in (False, True):
                                session.set('ActivityDuration', str(initial)); case(f'enable-{initial}-{enabled}', enabled=enabled)
                        for delay, destination in itertools.product((1, 255), DESTINATIONS): case('duration-destination', after_seconds=delay, destination=destination)
                        for user, page, colour in itertools.product((False, True), (False, True), NIGHTLIGHT_COLOURS):
                            if user or page: case('nightlight-combination', nightlight_user_keys=user, nightlight_page_key=page, nightlight_colour=colour)
                        case('disable-preserves-hidden', enabled=False)
                        session.set('TimeoutPage', '3'); case('unoffered-destination-preserved')
                        for widget, kind, control in ((1, 7, 0xe5), (6, 8, 0xb2), (7, 9, 3)):
                            session.set(f'Widget{widget}WidgetType', str(kind)); session.set(f'Widget{widget}WidgetByteValue1', str(control))
                        plan = case('standby-mra-raw3-propagation', enabled=True)
                        self.assertEqual(plan.changes['Widget6WidgetByteValue1'], (0xe2,))
                        final = editor.snapshot(session.values()); session.save_to_source()
                    for action in ('save', 'close', 'load'): projects.operation(action, project)
                    with Programmer(client).load(network, source) as session: self.assertEqual(editor.snapshot(session.values()), final)
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    report.update(passed=True, saved_reloaded=True, network_state='new', physical_device_verified=False)
                finally:
                    projects.operation('close', project); projects.operation('delete', project)
        path = Path(os.environ.get('CBUS_EDLT_STANDBY_REPORT', ROOT / 'research/runtime/edlt-standby/native-report.json'))
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(report, indent=2) + '\n')
