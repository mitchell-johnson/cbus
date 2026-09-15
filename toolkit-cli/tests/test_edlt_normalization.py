"""Original save-hook terminator changes, including nonzero restore values."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from cbus_toolkit.edlt import EdltLighting, EdltApplyError, EdltError
from tests.test_edlt import fixture, Session


# Exact changed fields observed from unchanged BeforeSavePPData. Selected
# widgets in these fixtures have already had their original setter applied.
CHANGES = {
    'no-active': {'Widget6WidgetType': (255,), 'Widget6RestoreLevel': (0,)},
    'no-active-existing-terminator': {},
    'all-terminators': {},
    'standby-only': {'Widget6WidgetType': (255,), 'Widget6RestoreLevel': (0,)},
    'new-trailing-terminator': {'Widget7WidgetType': (255,), 'Widget7RestoreLevel': (0,)},
    'existing-trailing-terminator': {},
    'earlier-terminators': {'Widget6WidgetType': (0,), 'Widget6RestoreLevel': (0,),
                          'Widget8WidgetType': (0,), 'Widget8RestoreLevel': (0,),
                          'Widget10WidgetType': (255,), 'Widget10RestoreLevel': (0,)},
    'last-functional-active': {},
}


def values_for(case):
    result = {}
    for widget in range(1, 22):
        result[f'Widget{widget}WidgetType'] = (0,)
        for offset in range(1, 32):
            result[f'Widget{widget}WidgetByteValue{offset}'] = (offset,)
        if widget >= 6:
            result[f'Widget{widget}RestoreLevel'] = (100 + widget,)
    if case in ('no-active-existing-terminator', 'all-terminators'):
        for widget in (range(6, 22) if case == 'all-terminators' else (6,)):
            result[f'Widget{widget}WidgetType'] = (255,)
    elif case == 'standby-only':
        result['Widget1WidgetType'] = (10,)
    elif case in ('new-trailing-terminator', 'existing-trailing-terminator'):
        result['Widget6WidgetType'] = (10,)
        result['Widget6RestoreLevel'] = (0,)
        if case == 'existing-trailing-terminator':
            result['Widget7WidgetType'] = (255,)
    elif case == 'earlier-terminators':
        result['Widget6WidgetType'] = result['Widget8WidgetType'] = (255,)
        result['Widget9WidgetType'] = (10,)
        result['Widget9RestoreLevel'] = (0,)
    elif case == 'last-functional-active':
        result['Widget21WidgetType'] = (10,)
        result['Widget21RestoreLevel'] = (0,)
    return result


def record(values, widget=1):
    return bytes([values[f'Widget{widget}WidgetType'][0]] +
                 [values[f'Widget{widget}WidgetByteValue{offset}'][0] for offset in range(1, 32)])


def parse_native_widgets(text):
    result = {}
    for entry in text.split('|'):
        number, contents = entry.split('=')
        kind, restore, opaque = contents.split('/')
        result[f'Widget{number}WidgetType'] = (int(kind),)
        if restore != 'none':
            result[f'Widget{number}RestoreLevel'] = (int(restore),)
        for offset, value in enumerate(opaque.split(','), 1):
            result[f'Widget{number}WidgetByteValue{offset}'] = (int(value),)
    return result


class NormalizationTests(unittest.TestCase):
    def test_literal_transitions_preservation_and_idempotence(self):
        for case, changes in CHANGES.items():
            with self.subTest(case=case):
                source = values_for(case)
                before = dict(source)
                result = EdltLighting._place_record(source, 1, record(source))
                self.assertEqual(result, {**source, **changes})
                self.assertEqual(source, before)
                self.assertEqual(EdltLighting._place_record(result, 1, record(result)), result)
                self.assertFalse(any(f'Widget{widget}RestoreLevel' in result for widget in range(1, 6)))

    def test_lighting_apply_permits_only_canonical_normalization_restore_edits(self):
        spec = fixture()
        editor, session = EdltLighting(spec), Session(spec)
        for widget in range(6, 22):
            session.current[f'Widget{widget}WidgetType'] = (0,)
            session.current[f'Widget{widget}RestoreLevel'] = (100 + widget,)
        source = editor.snapshot(session.values())
        plan = editor.plan(source, page=1, position=1, group=42, mode='off-on')
        self.assertEqual(plan.changes['Widget7WidgetType'], (255,))
        self.assertEqual(plan.changes['Widget7RestoreLevel'], (0,))
        self.assertNotIn('Widget8RestoreLevel', plan.changes)
        forged = replace(plan, changes={**plan.changes, 'Widget8RestoreLevel': (0,)})
        with self.assertRaises(EdltError):
            editor.apply(session, forged)
        self.assertEqual(editor.snapshot(session.values()), source)
        result = editor.apply(session, plan)
        self.assertTrue(result['verified'])
        self.assertEqual(editor.snapshot(session.values()), {**source, **plan.changes})

    def test_normalization_failure_restores_original_type_and_restore_together(self):
        spec = fixture()
        editor, session = EdltLighting(spec), Session(spec)
        for widget in range(6, 22):
            session.current[f'Widget{widget}WidgetType'] = (0,)
            session.current[f'Widget{widget}RestoreLevel'] = (100 + widget,)
        source = editor.snapshot(session.values())
        plan = editor.plan(source, page=1, position=1, group=42, mode='off-on')
        session.failure = 'Widget7RestoreLevel'
        with self.assertRaises(EdltApplyError) as caught:
            editor.apply(session, plan)
        self.assertTrue(caught.exception.details['rollback_verified'])
        self.assertEqual(editor.snapshot(session.values()), source)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),
                     'Set Toolkit EXE for original DLL save normalization acceptance')
class OriginalNormalizationTests(unittest.TestCase):
    def test_unchanged_original_before_save_literal_eight_cases(self):
        root = Path(__file__).resolve().parents[1]
        app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend()
        if backend == 'windows':
            with OriginalModelOracle(root / 'research/NativeEdltNormalizationProbe.cs', app, backend='windows') as oracle:
                original_output = oracle.run()
            result = subprocess.CompletedProcess([], 0, original_output, '')
        else:
            with tempfile.TemporaryDirectory() as folder:
                Path(folder, 'NativeEdltNormalizationProbe.cs').write_bytes(
                    (root / 'research/NativeEdltNormalizationProbe.cs').read_bytes())
                result = subprocess.run(['docker', 'run', '--rm', '-v', str(app) + ':/input:ro',
                    '-v', folder + ':/work', '-w', '/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5',
                    'sh', '-c', 'mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms -r:System.Drawing NativeEdltNormalizationProbe.cs && MONO_PATH=/input mono NativeEdltNormalizationProbe.exe'],
                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        cases, case = {}, None
        for line in result.stdout.splitlines():
            key, value = line.split(':', 1)
            if key == 'case':
                case = value
                self.assertNotIn(case, cases)
                cases[case] = {}
            else:
                self.assertIn(key, ('before', 'after', 'again'))
                cases[case][key] = parse_native_widgets(value)
        self.assertEqual(set(cases), set(CHANGES))
        for name, observed in cases.items():
            with self.subTest(case=name):
                self.assertEqual(observed['before'], values_for(name))
                self.assertEqual(observed['after'], {**values_for(name), **CHANGES[name]})
                self.assertEqual(observed['again'], observed['after'])
                self.assertEqual(EdltLighting._place_record(observed['before'], 1,
                                 record(observed['before'])), observed['after'])
        if os.environ.get('CBUS_EDLT_NORMALIZATION_REPORT'):
            import hashlib
            report = {'passed': True, 'scope': 'original DLL BeforeSavePPData terminator normalization; no device I/O',
                      'cases': {name: {'changes': CHANGES[name], 'idempotent': True} for name in cases},
                      'original_backend': backend,
                      'dll_sha256': hashlib.sha256((app / 'CBusLogicModel.dll').read_bytes()).hexdigest(),
                      'stdout': result.stdout}
            Path(os.environ['CBUS_EDLT_NORMALIZATION_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                     'Set native C-Gate and specifications for normalization PP acceptance')
class NativeNormalizationTests(unittest.TestCase):
    def test_nonzero_restore_normalization_raw_bytes_and_full_database_reload(self):
        from uuid import uuid4
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer
        from cbus_toolkit.unitspec import UnitSpecStore
        project = 'ENM' + uuid4().hex[:5].upper()
        network = '//' + project + '/254'
        source = '/db' + network + '/p/20'
        editor = EdltLighting(UnitSpecStore(Path(os.environ['CBUS_UNITSPEC_DIR'])).load('KEYGL5.xml'))
        host, port = os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        with CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Normalization', 'Cni', '127.0.0.1:1')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                programmer = Programmer(client)
                with programmer.load(network, source) as session:
                    for widget in range(6, 22):
                        session.set(f'Widget{widget}WidgetType', '0')
                        session.set(f'Widget{widget}RestoreLevel', str(100 + widget))
                    before = editor.snapshot(session.values())
                    plan = editor.plan(before, page=1, position=1, group=42, mode='off-on')
                    self.assertEqual(plan.changes['Widget7RestoreLevel'], (0,))
                    editor.apply(session, plan)
                    final = editor.snapshot(session.values())
                    expected_restore = bytes((0, 0, *range(108, 122))).hex()
                    self.assertEqual(session.get_raw_data(0x1a0, 16).lines[-1].split('RawData=')[1], expected_restore)
                    self.assertEqual(session.get_raw_data(0x2e0, 1).lines[-1].split('RawData=')[1], 'ff')
                    for widget in range(8, 22):
                        self.assertEqual(final[f'Widget{widget}RestoreLevel'], before[f'Widget{widget}RestoreLevel'])
                    session.save_to_source()
                for operation in ('save', 'close', 'load'):
                    projects.operation(operation, project)
                with programmer.load(network, source) as session:
                    self.assertEqual(editor.snapshot(session.values()), final)
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                if os.environ.get('CBUS_EDLT_NORMALIZATION_NATIVE_REPORT'):
                    Path(os.environ['CBUS_EDLT_NORMALIZATION_NATIVE_REPORT']).write_text(json.dumps({
                        'passed': True, 'scope': 'Existing native normalization fixture; no hardware I/O',
                        'parameters_compared': len(final), 'crcs': editor.crcs(final),
                        'expected_restore_raw': expected_restore, 'terminator_raw': 'ff',
                        'saved_reloaded': True, 'network_state': 'new', 'physical_device_verified': False,
                    }, indent=2) + '\n')
            finally:
                projects.operation('close', project)
                projects.operation('delete', project)


if __name__ == '__main__':
    unittest.main()
