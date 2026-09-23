"""Actual Reset handler versus Python raw phases and closed native persistence."""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.edlt_reset import EdltResetControls
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_reset import metadata
from research.verify_edlt_reset_vectors import phases

ROOT = Path(__file__).resolve().parents[1]
CASES = ('default-multi', 'rich-single-colours', 'first-mra-general', 'casing-crossed-status')


def digest(value): return hashlib.sha256(value).hexdigest()
def tsv(values): return ''.join(name + '\t' + value + '\n' for name, value in values.items()).encode()


@unittest.skipUnless(os.environ.get('CBUS_WINDOWS_BRIDGE') == '1' and all(os.environ.get(n) for n in
    ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')), 'Select owned Windows oracle and C-Gate fixtures')
class NativeResetTests(unittest.TestCase):
    def test_original_raw_phases_all_parameters_crcs_and_save_reload(self):
        from research.windows_bridge import WindowsBridge, WindowsModelProbe
        from research.windows_provenance import resolve_windows_provenance
        spec_dir = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve()
        editor = EdltResetControls(UnitSpecStore(spec_dir).load('KEYGL5.xml'))
        vector_path = ROOT / 'research/fixtures/edlt-reset-windows-vectors.json'
        vectors = json.loads(vector_path.read_text())
        cases = {name: next(row for row in vectors['cases'] if row['name'] ==
            'reset-matrix-v1/' + name + '-audited-handler') for name in CASES}
        selected = tuple(os.environ.get('CBUS_EDLT_RESET_NATIVE_CASES', ','.join(CASES)).split(','))
        self.assertTrue(selected and len(set(selected)) == len(selected) and set(selected) <= set(CASES))
        proof = ROOT / 'research/runtime/edlt-reset-controls' / ('native-python-' + uuid4().hex[:16])
        proof.mkdir(parents=True, exist_ok=False)
        output = Path(os.environ.get('CBUS_EDLT_RESET_NATIVE_REPORT', str(proof / 'report.json')))
        output.parent.mkdir(parents=True, exist_ok=True)
        report = {'format': 'cbus-edlt-reset-native-acceptance-v1', 'passed': False,
            'complete_scope': selected == CASES, 'python': sys.version, 'cases': [], 'jobs': [],
            'cleanup_errors': [], 'proof_directory': str(proof), 'physical_device_verified': False,
            'full_form_verified': False, 'renderer_verified': False}
        provenance = resolve_windows_provenance(ROOT, WindowsBridge())
        report['owned_provenance'] = provenance.as_dict()
        paths = {'probe.cs': ROOT / 'research/NativeEdltResetMatrixProbe.cs',
            'KEYGL5.xml': spec_dir / 'KEYGL5.xml', 'native_test.py': Path(__file__),
            'vectors.json': vector_path, **provenance.paths}
        for name in ('edlt_reset', 'edlt_lifecycle', 'edlt_application_cache', 'edlt', 'edlt_mra',
                     'unitspec', 'memory', 'programming', 'native', 'cgate', 'cli', 'edlt_control_cli', 'edlt_reset_cli'):
            paths[name + '.py'] = ROOT / 'src/cbus_toolkit' / (name + '.py')
        for name in ('test_edlt_reset', 'test_edlt_reset_vectors', 'test_cli_edlt_reset'):
            paths[name + '.py'] = ROOT / 'tests' / (name + '.py')
        for name in ('windows_bridge', 'windows_provenance', 'verify_edlt_reset_vectors'):
            paths[name + '.py'] = ROOT / 'research' / (name + '.py')
        captured = {name: path.read_bytes() for name, path in paths.items()}
        report['source_before'] = {name: digest(data) for name, data in captured.items()}
        for name, data in captured.items(): (proof / name).write_bytes(data)
        def save():
            document = json.dumps(report, indent=2) + '\n'
            output.write_text(document); (proof / 'progress.json').write_text(document)
        def stable():
            provenance.verify(WindowsBridge())
            self.assertEqual({name: digest(path.read_bytes()) for name, path in paths.items()}, report['source_before'])
        class RecordingBridge(WindowsBridge):
            def run(bridge, *args, **kwargs):
                result = super().run(*args, **kwargs)
                job = {k: v for k, v in result.items() if k not in ('stdout', 'stderr')}
                for channel in ('stdout', 'stderr'):
                    data = result[channel]; (proof / (result['job_id'] + '.' + channel)).write_bytes(data)
                    job[channel + '_sha256'] = digest(data)
                report['jobs'].append(job); save(); return result
        save(); stable()
        probe = WindowsModelProbe(paths['probe.cs'], Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent,
            bridge=RecordingBridge(), references=('eDLT.dll', 'SharpCGateCommunicator.dll'))
        executable = probe.bridge.pull('vendor\\' + probe.prefix + '.exe')
        (proof / 'probe.exe').write_bytes(executable)
        report.update(vendor_manifest=probe.vendor_manifest, executable_sha256=digest(executable))
        project = 'RS' + uuid4().hex[:6].upper(); network = '//' + project + '/254'
        source = '/db' + network + '/p/20'; report.update(project=project, source=source); save()
        with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                projects.operation('save', project)
                database.create_network(project, 254, 'Reset_Fixture', 'Cni', '127.0.0.1:1')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                with Programmer(client).load(network, source) as session:
                    session.reset_defaults(); baseline = editor.snapshot(session.values())
                for name in selected:
                    stable(); row = cases[name]; record = {'case': name, 'passed': False}
                    report['cases'].append(record); save()
                    desired = editor.snapshot({**vectors['baseline'], **row['source_changes']})
                    desired.update({key: baseline[key] for key in ('UnitAddress', 'Project', 'NetworkAddress', 'UnitName', 'SerialNumber')})
                    with Programmer(client).load(network, source) as session:
                        current = editor.snapshot(session.values())
                        for key, value in desired.items():
                            if value != current[key]: session.set(key, value if isinstance(value, str) else ' '.join(map(str, value)))
                        before = session.values()  # Exact native text, not numeric normalization.
                        files = {'KEYGL5.xml': captured['KEYGL5.xml'], 'values.tsv': tsv(before), 'overrides.tsv': b''}
                        (proof / (name + '.input.tsv')).write_bytes(files['values.tsv'])
                        record['input_sha256'] = {k: digest(v) for k, v in files.items()}; save()
                        tab = {'widgets': 'tpWidgetFunctions', 'general': 'tpGeneralOptions',
                               'standby': 'tpStandbyPage', 'colour': 'tpColourOptions'}[row['active_tab']]
                        result = probe.run_result(('KEYGL5.xml', 'values.tsv', 'overrides.tsv',
                            'handler', 'audited', tab, row['metadata_mode']), files=files)
                        record['job_id'] = result['job_id']; save()
                        self.assertEqual(result['exit_code'], 0, result['stdout'][-2000:])
                        self.assertEqual(result['stderr'], b'')
                        self.assertIn(b'complete:true:', result['stdout'])
                        self.assertIn(b'peer-cleanup:joined=true:accepted=1:received-bytes=72:requests=2:eof=True:pending-bytes=0', result['stdout'])
                        original, flags = phases(proof / (result['job_id'] + '.stdout'))
                        plan = editor.plan(before, metadata=metadata(row['metadata_mode']), active_tab=row['active_tab'],
                            binding_variant='audited-local-wiring', dirty_parameters=('UnitAddress', 'StaticTextString0'))
                        for stage, wanted in original.items():
                            self.assertEqual(len(wanted), 874)
                            actual = plan.phases[stage]
                            self.assertEqual(dict(actual.raw), {key: value[0] for key, value in wanted.items()}, (name, stage))
                            self.assertEqual(set(actual.dirty_parameters), {key for key, value in wanted.items() if value[1]}, (name, stage))
                            self.assertIs(actual.initializing, flags[stage])
                        self.assertTrue(editor.apply(session, plan)['verified'])
                        final = {**plan.expected, **plan.changes}
                        self.assertEqual(editor.snapshot(session.values()), final)
                        fields = ('OverallCRC', 'GlobalParameterCRC', 'WidgetsCRC', 'StaticTextCRC', 'ScenesCheckSum', 'SceneBucket')
                        raw_reads = [(editor.codec.layout(field).address, bytes(final[field])) for field in fields]
                        raw_reads.append((editor.codec.layout('Widget10WidgetType').address,
                            bytes(final['Widget10' + ('WidgetType' if i == 0 else 'WidgetByteValue' + str(i))][0] for i in range(32))))
                        for address, wanted in raw_reads:
                            self.assertEqual(bytes.fromhex(session.get_raw_data(address, len(wanted)).lines[-1].split('RawData=')[1]), wanted)
                        session.save_to_source()
                    for action in ('save', 'close', 'load'): projects.operation(action, project)
                    with Programmer(client).load(network, source) as session:
                        self.assertEqual(editor.snapshot(session.values()), final)
                        for address, wanted in raw_reads:
                            self.assertEqual(bytes.fromhex(session.get_raw_data(address, len(wanted)).lines[-1].split('RawData=')[1]), wanted)
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    record.update(passed=True, original_phase_count=len(original), original_parameter_comparisons=874 * len(original),
                        native_parameter_comparisons=874, reloaded_parameter_comparisons=874,
                        raw_bytes_per_readback=sum(len(value) for _, value in raw_reads), crc_fields=5,
                        saved_reloaded=True, network_state='new'); stable(); save()
            except BaseException as error:
                report['failure_type'] = type(error).__name__; save(); raise
            finally:
                first = sys.exc_info()[1]; cleanup = None
                for action in ('close', 'delete'):
                    if not client.connected:
                        report['cleanup_errors'].append({'action': action, 'reason': 'connection_lost'}); break
                    try: projects.operation(action, project)
                    except BaseException as error:
                        report['cleanup_errors'].append({'action': action, 'type': type(error).__name__}); cleanup = cleanup or error
                save()
                if first is None and cleanup is not None: raise cleanup
        stable(); report['source_after'] = {name: digest(path.read_bytes()) for name, path in paths.items()}
        report['passed'] = all(row['passed'] for row in report['cases']) and len(report['cases']) == len(selected) and not report['cleanup_errors']
        save(); self.assertTrue(report['passed'])
