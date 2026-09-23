"""Original application controls and closed C-Gate database persistence."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.edlt_applications import EdltApplications, ApplicationEdit
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_applications import captured_cache

ROOT = Path(__file__).resolve().parents[1]
CASES = ('primary-noop-ui-commit', 'primary-special-ui-commit', 'secondary-disable-standby',
    'secondary-disable-widget-missing-group', 'secondary-disable-enable-fixed',
    'secondary-disable-scene-current', 'secondary-disable-scene-missing-action',
    'global-QuickStatusGroup-missing', 'swap-via-disable-ui-commit',
    'mra7-disable-restore-scene', 'mra8-disable-restore-scene', 'mra9-disable-restore-scene',
    'status6-type4-disable-restore-scene', 'status6-type16-disable-restore-scene')


def sha(raw): return hashlib.sha256(raw).hexdigest()


def tsv(values):
    # Original scalar getters accept decimal, but its memory/CRC array path
    # parses tokens as hexadecimal. Supply the native PP representation.
    return ''.join(name + '\t' + (value if isinstance(value, str) else ' '.join(map(hex, value))) + '\n'
                   for name, value in values.items()).encode()


@unittest.skipUnless(os.environ.get('CBUS_WINDOWS_BRIDGE') == '1' and all(os.environ.get(name) for name in
    ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')),
    'Select the owned Windows bridge, original Toolkit/spec and native C-Gate')
class NativeApplicationTests(unittest.TestCase):
    def test_original_controls_native_parameters_raw_bytes_and_save_reload(self):
        from research.compact_edlt_application_vectors import parse
        from research.verify_edlt_application_phases import cases, rows
        from research.windows_bridge import WindowsModelProbe
        selected = {row['id']: row for row in cases()}
        self.assertTrue(set(CASES) <= set(selected))
        directory = ROOT / 'research/runtime/edlt-application-phases' / ('native-' + uuid4().hex[:12])
        directory.mkdir(parents=True)
        report_path = Path(os.environ.get('CBUS_EDLT_APPLICATION_NATIVE_REPORT', str(directory / 'result.json')))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve()
        vendor = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        editor = EdltApplications(UnitSpecStore(specs).load('KEYGL5.xml'))
        paths = {'probe.cs': ROOT / 'research/NativeEdltApplicationPhasesProbe.cs',
            'driver.py': ROOT / 'research/verify_edlt_application_phases.py',
            'parser.py': ROOT / 'research/compact_edlt_application_vectors.py',
            'windows_bridge.py': ROOT / 'research/windows_bridge.py',
            'KEYGL5.xml': specs / 'KEYGL5.xml', 'native_test.py': Path(__file__),
            'pure_test.py': ROOT / 'tests/test_edlt_applications.py',
            'case_inputs.json': ROOT / 'research/fixtures/edlt-application-observations.json',
            'common_test.py': ROOT / 'tests/test_edlt.py',
            **{name + '.py': ROOT / 'src/cbus_toolkit' / (name + '.py') for name in
               ('edlt_applications', 'edlt_application_cache', 'edlt_lifecycle', 'edlt', 'unitspec', 'programming', 'native', 'cgate')}}
        proof = {'passed': False, 'python': sys.version, 'cases': [], 'cleanup_errors': [],
            'source_sha256': {}, 'source_paths': {k: str(v.resolve()) for k, v in paths.items()},
            'proof_directory': str(directory.relative_to(ROOT)), 'physical_device_verified': False,
            'full_form_initialization_verified': False, 'dependency_getters_invoked': False,
            'native_host': os.environ['CBUS_CGATE_TEST_HOST'],
            'native_port': int(os.environ.get('CBUS_CGATE_TEST_PORT', '20033'))}
        for name, path in paths.items():
            raw = path.read_bytes(); (directory / name).write_bytes(raw); proof['source_sha256'][name] = sha(raw)
        def save():
            raw = json.dumps(proof, indent=2) + '\n'; report_path.write_text(raw); (directory / 'progress.json').write_text(raw)
        def stable():
            for name, path in paths.items(): self.assertEqual(sha(path.read_bytes()), proof['source_sha256'][name], name)
        save(); probe = WindowsModelProbe(paths['probe.cs'], vendor, references=('eDLT.dll',))
        executable = probe.bridge.pull('vendor\\' + probe.prefix + '.exe')
        (directory / 'probe.exe').write_bytes(executable)
        proof.update(executable_sha256=sha(executable), vendor_manifest=probe.vendor_manifest)
        project = 'AP' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/255'
        proof.update(project=project, source=source); save(); stable()
        with CGateClient(proof['native_host'], proof['native_port'], timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                projects.operation('save', project)
                database.create_network(project, 254, 'Application_Fixture', 'Cni', '127.0.0.1:1')
                database.create_unit(network, 255, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                with Programmer(client).load(network, source) as session:
                    session.reset_defaults(); baseline = editor.snapshot(session.values())
                self.assertEqual(len(baseline), 874)
                for name in CASES:
                    stable(); case = selected[name]; record = {'case': name, 'passed': False}; proof['cases'].append(record); save()
                    files = {'KEYGL5.xml': paths['KEYGL5.xml'].read_bytes(), 'values.tsv': tsv(baseline), 'cases.tsv': rows([case])}
                    for filename, raw in files.items(): (directory / (name + '-' + filename)).write_bytes(raw)
                    record['input_sha256'] = {key: sha(raw) for key, raw in files.items()}
                    result = probe.run_result(('KEYGL5.xml', 'values.tsv', 'cases.tsv', 'global'), files=files)
                    for channel in ('stdout', 'stderr'):
                        raw = result.pop(channel); (directory / (name + '.' + channel + '.txt')).write_bytes(raw)
                        result[channel + '_sha256'] = sha(raw)
                    record['original'] = result; save()
                    self.assertEqual(result['exit_code'], 0); self.assertTrue(result['complete'])
                    self.assertEqual((directory / (name + '.stderr.txt')).read_bytes(), b'')
                    observed = parse(directory / (name + '.stdout.txt'))['global', name]
                    self.assertTrue(observed['complete']); self.assertTrue(observed['ended'])
                    self.assertFalse(any(row['kind'] in ('metadata-request', 'failure', 'cleanup-failure', 'action-unavailable')
                                         for row in observed['observations']))
                    raw_input = editor.snapshot(observed['phases']['raw-input'])
                    document = {'observation_values': [row['value'] for row in observed['observations']]}
                    row = {'observations': [[item['kind'], item['stage'], index]
                           for index, item in enumerate(observed['observations'])]}
                    cache = captured_cache(document, row)
                    action = case['action']; actions = action['steps'] if action['kind'] == 'sequence' else [action]
                    edits = [ApplicationEdit(item['field'], item['value']) for item in actions if item['kind'] != 'bind-only']
                    plan = editor.plan(raw_input, cache=cache, edits=edits); expected = {**plan.expected, **plan.changes}
                    for stage, wanted in (('after-original-load', plan.after_load), ('validation', plan.after_controls),
                        ('original-save', plan.before_save), ('crc', expected)):
                        self.assertEqual(len(observed['phases'][stage]), 874)
                        actual = editor.snapshot(observed['phases'][stage])
                        self.assertEqual({key: (actual[key], value) for key, value in wanted.items() if actual[key] != value}, {}, name + '/' + stage)
                    widget = case['fixture'].get('widget_number', 6)
                    control_name = f'Widget{widget}WidgetByteValue1'; control_address = editor.codec.layout(control_name).address
                    raw_expected = ((272, bytes(expected['PrimaryApplication'] + expected['SecondaryApplication'])),
                                    (33, bytes(expected['Application'])), (control_address, bytes(expected[control_name])))
                    def check_raw(session):
                        for address, wanted in raw_expected:
                            actual = bytes.fromhex(session.get_raw_data(address, len(wanted)).lines[-1].split('RawData=')[1])
                            self.assertEqual(actual, wanted, name + '/raw/' + str(address))
                    with Programmer(client).load(network, source) as session:
                        current = editor.snapshot(session.values())
                        for parameter, value in raw_input.items():
                            if value != current[parameter]: session.set(parameter, value if isinstance(value, str) else ' '.join(map(str, value)))
                        self.assertEqual(editor.snapshot(session.values()), raw_input)
                        self.assertTrue(editor.apply(session, plan)['verified'])
                        self.assertEqual(editor.snapshot(session.values()), expected); check_raw(session); session.save_to_source()
                    for operation in ('save', 'close', 'load'): projects.operation(operation, project)
                    with Programmer(client).load(network, source) as session:
                        self.assertEqual(editor.snapshot(session.values()), expected); check_raw(session)
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    record.update(passed=True, full_parameters=874, original_phases=4, crc_values=5,
                        native_full_readback=True, save_close_load_full_readback=True, network_state='new',
                        raw_ranges=[{'address': address, 'hex': value.hex()} for address, value in raw_expected])
                    stable(); save()
            except BaseException as error:
                proof['failure_type'] = type(error).__name__; save(); raise
            finally:
                primary = sys.exc_info()[1]; cleanup_first = None
                for operation in ('close', 'delete'):
                    if not client.connected:
                        proof['cleanup_errors'].append({'operation': operation, 'reason': 'connection_lost'}); break
                    try: projects.operation(operation, project)
                    except BaseException as error:
                        proof['cleanup_errors'].append({'operation': operation, 'type': type(error).__name__})
                        if cleanup_first is None: cleanup_first = error
                save()
                if primary is None and cleanup_first is not None: raise cleanup_first
        stable(); self.assertFalse(proof['cleanup_errors']); proof['passed'] = True; save()


if __name__ == '__main__': unittest.main()
