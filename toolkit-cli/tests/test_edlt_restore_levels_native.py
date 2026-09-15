"""Independent original-control/native-PP restore-level persistence acceptance."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.edlt_restore_levels import EdltRestoreLevels
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_restore_levels import metadata

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    'edit-false-0', 'edit-false-255', 'edit-true-128',
    'same-value-no-propagation', 'duplicate-groups', 'duplicate-app-groups',
    'hidden-mode-0-sync-True', 'empty-and-end-sync-True', 'secondary-disabled',
    'option-enable-preset-edit', 'option-disable-preset',
    'option-enable-multiple-edit', 'option-enable-single-edit',
    'composition-scene-251-True', 'composition-image-False',
)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _phases(output):
    phases = {}
    for line in output.splitlines():
        stage, separator, text = line.partition(':')
        if separator and '\t' in text:
            name, value = text.split('\t', 1)
            if name in phases.setdefault(stage, {}):
                raise ValueError('Duplicate parameter in original phase: ' + stage + '/' + name)
            phases[stage][name] = value
    return phases


def _options(actions):
    options = {}
    edited = False
    for action in actions:
        words = action.split(' ')
        if words[0] == 'edit':
            if edited or len(words) != 4 or words[3] not in ('true', 'false'):
                raise ValueError('Native case must contain only one supported edit')
            options.update(widget=int(words[1]), level=int(words[2]), synchronise=words[3] == 'true')
            edited = True
        elif words[0] in ('mode', 'restore-mode'):
            if edited or len(words) != 2:
                raise ValueError('Native case changes mode after its edit')
            if words[0] == 'mode':
                if words[1] not in ('0', '1'): raise ValueError('Unsupported native page mode')
                options['page_mode'] = 'multiple' if words[1] == '1' else 'single'
            else:
                if words[1] not in ('preset', 'previous'): raise ValueError('Unsupported native restore mode')
                options['restore_mode'] = words[1]
        elif action not in ('groups', 'refresh', 'validate', 'write'):
            raise ValueError('Unsupported native fixture action')
    return options


@unittest.skipUnless(os.environ.get('CBUS_WINDOWS_BRIDGE') == '1' and all(os.environ.get(name) for name in
    ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')),
    'Select the owned Windows bridge, original Toolkit/spec and native C-Gate')
class NativeRestoreLevelTests(unittest.TestCase):
    def test_original_controls_full_native_pp_crc_raw_save_and_reload(self):
        from research.verify_edlt_restore_levels import cases, tsv
        from research.windows_bridge import WindowsBridge, WindowsModelProbe

        selected = CASES
        supplied = os.environ.get('CBUS_EDLT_RESTORE_NATIVE_CASES')
        if supplied is not None:
            selected = tuple(supplied.split(','))
            self.assertTrue(selected and len(set(selected)) == len(selected) and set(selected) <= set(CASES))
        available = {row['name']: row for row in cases()}
        self.assertTrue(set(CASES) <= set(available))
        selected_cases = [available[name] for name in selected]
        spec_dir = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve()
        app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        editor = EdltRestoreLevels(UnitSpecStore(spec_dir).load('KEYGL5.xml'))
        proof_dir = ROOT / 'research/runtime/edlt-restore-levels' / ('native-' + uuid4().hex[:16])
        proof_dir.mkdir(parents=True, exist_ok=False)
        report_path = Path(os.environ.get('CBUS_EDLT_RESTORE_NATIVE_REPORT', str(
            ROOT / 'research/runtime/edlt-restore-levels' /
            ('native-windows-macos-' + str(sys.version_info.major) + str(sys.version_info.minor) + '-report.json'))))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        document = {'passed': False, 'complete_scope': tuple(selected) == CASES,
                    'selected_cases': list(selected), 'cases': [], 'jobs': [], 'cleanup_errors': [],
                    'python': sys.version, 'proof_directory': str(proof_dir.relative_to(ROOT)),
                    'physical_device_verified': False, 'full_form_initialization_verified': False,
                    'source_sha256': {}, 'source_paths': {}, 'native_host': os.environ['CBUS_CGATE_TEST_HOST'],
                    'native_port': int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))}
        from research.windows_provenance import resolve_windows_provenance
        provenance = resolve_windows_provenance(ROOT, WindowsBridge())
        document['owned_provenance'] = provenance.as_dict()
        paths = {
            'probe.cs': ROOT / 'research/NativeEdltRestoreLevelsProbe.cs',
            'driver.py': ROOT / 'research/verify_edlt_restore_levels.py',
            'native_test.py': Path(__file__).resolve(),
            'pure_test.py': ROOT / 'tests/test_edlt_restore_levels.py',
            'cli.py': ROOT / 'src/cbus_toolkit/cli.py',
            'cli_test.py': ROOT / 'tests/test_cli_edlt_restore_levels.py',
            'vectors_test.py': ROOT / 'tests/test_edlt_restore_levels_vectors.py',
            'vectors.json': ROOT / 'research/fixtures/edlt-restore-levels-windows-vectors.json',
            'lifecycle_test.py': ROOT / 'tests/test_edlt_lifecycle.py',
            'KEYGL5.xml': spec_dir / 'KEYGL5.xml',
            'windows_bridge.py': ROOT / 'research/windows_bridge.py',
            'windows_provenance.py': ROOT / 'research/windows_provenance.py',
            'NativeWindowsBridge.cs': ROOT / 'research/NativeWindowsBridge.cs',
            **provenance.paths,
            **{name + '.py': ROOT / 'src/cbus_toolkit' / (name + '.py') for name in
               ('edlt_restore_levels', 'edlt_lifecycle', 'edlt', 'unitspec', 'programming', 'native', 'cgate')},
        }
        for name, path in paths.items():
            raw = path.read_bytes(); (proof_dir / name).write_bytes(raw)
            document['source_sha256'][name] = _digest(raw); document['source_paths'][name] = str(path)
        for name in ('windows-runtime.json', 'bridge-ready.json'):
            path = provenance.paths[name]
            raw = path.read_bytes(); (proof_dir / name).write_bytes(raw)
            document[name + '_sha256'] = _digest(raw)

        def save():
            raw = json.dumps(document, indent=2) + '\n'
            report_path.write_text(raw); (proof_dir / 'progress.json').write_text(raw)

        def stable():
            provenance.verify(WindowsBridge())
            for name, path in paths.items():
                self.assertEqual(_digest(path.read_bytes()), document['source_sha256'][name],
                                 'Acceptance source changed: ' + name)

        class RecordingBridge(WindowsBridge):
            def run(bridge, script, **kwargs):
                result = super().run(script, **kwargs)
                job = {key: value for key, value in result.items() if key not in ('stdout', 'stderr')}
                job_id = result['job_id']
                raw = script.replace('\r\n', '\n').replace('\n', '\r\n').encode() if isinstance(script, str) else script
                (proof_dir / (job_id + '.cmd')).write_bytes(raw)
                job['command_sha256'] = _digest(raw)
                for channel in ('stdout', 'stderr'):
                    data = result[channel]
                    if data is not None:
                        (proof_dir / (job_id + '.' + channel + '.txt')).write_bytes(data)
                        job[channel + '_sha256'] = _digest(data)
                (proof_dir / (job_id + '.result.json')).write_text(json.dumps(job, indent=2) + '\n')
                document['jobs'].append(job); save()
                return result

        save(); stable()
        probe = WindowsModelProbe(paths['probe.cs'], app, bridge=RecordingBridge(), references=('eDLT.dll',))
        executable = probe.bridge.pull('vendor\\' + probe.prefix + '.exe')
        (proof_dir / 'probe.exe').write_bytes(executable)
        document.update(probe_prefix=probe.prefix, executable_sha256=_digest(executable),
                        vendor_manifest=probe.vendor_manifest)
        save(); stable()
        project = 'RP' + uuid4().hex[:6].upper()
        network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        document.update(project=project, source=source)
        with CGateClient(document['native_host'], document['native_port'], timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                projects.operation('save', project)
                database.create_network(project, 254, 'Restore_Fixture', 'Cni', '127.0.0.1:1')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                with Programmer(client).load(network, source) as session:
                    session.reset_defaults(); baseline = editor.snapshot(session.values())
                self.assertEqual(len(baseline), 874)
                for case in selected_cases:
                    stable(); name = case['name']; options = _options(case['actions'])
                    record = {'case': name, 'passed': False, 'options': options}
                    document['cases'].append(record); save()
                    with Programmer(client).load(network, source) as session:
                        desired = {**baseline, **{key: tuple(value) if isinstance(value, list) else value
                                                for key, value in case['overrides'].items()}}
                        current = editor.snapshot(session.values())
                        for parameter, value in desired.items():
                            if value != current[parameter]:
                                session.set(parameter, value if isinstance(value, str) else ' '.join(map(str, value)))
                        before = editor.snapshot(session.values())
                        files = {'KEYGL5.xml': paths['KEYGL5.xml'].read_bytes(), 'values.tsv': tsv(before),
                                 'overrides.tsv': b'', 'actions.txt': ('\n'.join(case['actions']) + '\n').encode()}
                        for filename, raw in files.items():
                            if filename != 'KEYGL5.xml': (proof_dir / (name + '-' + filename)).write_bytes(raw)
                        record['input_sha256'] = {filename: _digest(raw) for filename, raw in files.items()}; save()
                        observed = probe.run_result(('KEYGL5.xml', 'values.tsv', 'overrides.tsv', 'actions.txt',
                                                     'owned', case['cache']), files=files)
                        record['original_job_id'] = observed['job_id']; save()
                        output = observed['stdout'].decode('utf-8-sig')
                        self.assertEqual(observed['exit_code'], 0, name + output[-1500:])
                        self.assertEqual(observed['stderr'], b'')
                        self.assertIn('complete:true', output.splitlines())
                        phases = _phases(output)
                        control_stage = ('action' + str(len(case['actions']) - 1) + '-' +
                                         case['actions'][-1].split(' ')[0]) if case['actions'] else 'refresh'
                        plan = editor.plan(before, metadata=metadata(editor, before, case['cache']), **options)
                        expected = {**plan.expected, **plan.changes}
                        for stage, wanted in (('afterload', plan.after_load), (control_stage, plan.after_controls),
                                              ('beforesave', plan.before_save), ('crc', expected)):
                            self.assertEqual(len(phases[stage]), 874, name + '/' + stage)
                            actual = editor.snapshot(phases[stage])
                            self.assertEqual({key: (actual[key], wanted[key]) for key in wanted if actual[key] != wanted[key]},
                                             {}, name + '/' + stage)
                        self.assertTrue(editor.apply(session, plan)['verified'])
                        actual = editor.snapshot(session.values()); self.assertEqual(actual, expected)
                        raw = bytes.fromhex(session.get_raw_data(0x1A0, 16).lines[-1].split('RawData=')[1])
                        wanted_raw = bytes(expected[f'Widget{i}RestoreLevel'][0] for i in range(6, 22))
                        self.assertEqual(raw, wanted_raw, name)
                        session.save_to_source()
                    for action in ('save', 'close', 'load'): projects.operation(action, project)
                    with Programmer(client).load(network, source) as session:
                        self.assertEqual(editor.snapshot(session.values()), expected)
                        reloaded_raw = bytes.fromhex(session.get_raw_data(0x1A0, 16).lines[-1].split('RawData=')[1])
                        self.assertEqual(reloaded_raw, wanted_raw, name)
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    record.update(passed=True, original_phase_parameter_comparisons=874 * 4,
                                  native_parameter_comparisons=874, reload_parameter_comparisons=874,
                                  crc_values_compared=5, raw_restore_hex=raw.hex(), saved_reloaded=True,
                                  network_state='new')
                    stable(); save()
            except BaseException as error:
                document['failure_type'] = type(error).__name__; save(); raise
            finally:
                primary = sys.exc_info()[1]; cleanup_first = None
                for action in ('close', 'delete'):
                    if not client.connected:
                        document['cleanup_errors'].append({'action': action, 'reason': 'connection_lost'}); break
                    try: projects.operation(action, project)
                    except BaseException as error:
                        document['cleanup_errors'].append({'action': action, 'type': type(error).__name__})
                        if cleanup_first is None: cleanup_first = error
                save()
                if primary is None and cleanup_first is not None: raise cleanup_first
        stable()
        self.assertFalse(document['cleanup_errors'])
        document['passed'] = True; document['source_unchanged'] = True
        save()


if __name__ == '__main__':
    unittest.main()
