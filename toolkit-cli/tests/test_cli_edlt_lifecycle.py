"""CLI routing of explicit model phases and caller-supplied metadata facts."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from cbus_toolkit import cli
from cbus_toolkit.edlt_lifecycle import EdltLifecycle
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import fixture, cache


class LifecycleCLITests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): code = cli.main(list(map(str, args)))
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_requirements_phases_and_missing_fact_details_without_io(self):
        spec = fixture(); editor = EdltLifecycle(spec); session = Session(spec)
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, '_edlt_lifecycle', return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            path = Path(directory) / 'values.json'; path.write_text(json.dumps(session.values()))
            metadata = Path(directory) / 'metadata.json'; document = cache(editor, session.values()); metadata.write_text(json.dumps(document))
            required = self.invoke(('edlt', 'lifecycle-requirements', path))
            self.assertTrue(required['no_io']); self.assertTrue(required['groups'])
            self.assertFalse(required['cache_freshness_verified'])
            plan = self.invoke(('edlt', 'lifecycle-plan', path, '--metadata', metadata))
            self.assertEqual(set(plan['phases']), {'after_load', 'before_save', 'crc'})
            self.assertEqual(len(plan['phases']['crc']), 5); self.assertTrue(plan['model_cycle_complete'])
            self.assertFalse(plan['database_metadata_created']); self.assertFalse(plan['saved'])
            self.assertFalse(plan['cache_freshness_verified']); self.assertFalse(plan['physical_device_verified'])
            metadata.write_text(json.dumps({**document, 'groups': []}))
            error = self.invoke(('edlt', 'lifecycle-plan', path, '--metadata', metadata), status=1)
            self.assertEqual(error['type'], 'LifecycleMetadataError'); self.assertTrue(error['required_fact'])
            self.assertIn('original_stage', error); self.assertFalse(error['saved'])
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            self.assertIn('identity differs', self.invoke(('edlt', 'lifecycle-requirements', path), status=1)['error'])

    def test_metadata_schema_duplicate_keys_and_size_rejected_before_pp_context(self):
        editor = EdltLifecycle(fixture()); context = Mock(); context.__enter__ = Mock(side_effect=AssertionError('No PP context'))
        with tempfile.TemporaryDirectory() as directory, \
                patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=context))), \
                patch.object(cli, '_edlt_lifecycle', return_value=editor):
            metadata = Path(directory) / 'metadata.json'
            cases = (('{"format":"cbus-edlt-lifecycle-cache-v1","applications":[],"groups":[],"groups":[]}', 'Duplicate key'),
                     ('{"format":"cbus-edlt-lifecycle-cache-v1","applications":[56],"groups":[{"application":56,"group":0,"exists":true,"exists":false}]}', 'Duplicate key'),
                     (' ' * (256 * 1024 + 1), 'exceeds 256 KiB'), ('{"format":"unknown"}', 'format'))
            for raw, message in cases:
                metadata.write_text(raw)
                error = self.invoke(('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', '/db//EDLTTEST/254/p/20',
                    'edlt-lifecycle', '--metadata', metadata), status=1)
                self.assertIn(message, error['error'])
            context.__enter__.assert_not_called()

    def test_interrupt_preserves_phase_plan_without_save(self):
        spec = fixture(); editor = EdltLifecycle(spec); session = Session(spec); calls = []
        def fail(name, value):
            calls.append(name); session.current[name] = value; session.connected = False
            raise KeyboardInterrupt('Lifecycle SET interrupted')
        session.set = fail; session.save_to_source = Mock(side_effect=AssertionError('No save after interrupt'))
        with tempfile.TemporaryDirectory() as directory, \
                patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=nullcontext(session)))), \
                patch.object(cli, '_edlt_lifecycle', return_value=editor):
            metadata = Path(directory) / 'metadata.json'; metadata.write_text(json.dumps(cache(editor, session.values())))
            result = self.invoke(('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                'edlt-lifecycle', '--metadata', metadata), status=130)
        evidence = result['edlt_lifecycle_evidence']; self.assertEqual(len(calls), 1)
        self.assertEqual(evidence['attempted_parameters'], calls); self.assertTrue(evidence['pp_state_uncertain'])
        self.assertEqual(set(evidence['phases']), {'after_load', 'before_save', 'crc'})
        self.assertFalse(evidence['saved']); self.assertFalse(evidence['verified']); self.assertEqual(evidence['automatic_retries'], 0)
        session.save_to_source.assert_not_called()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and specifications for lifecycle CLI acceptance')
    def test_native_preview_full_parameter_save_reload_and_destination_guard(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.unitspec import UnitSpecStore
        editor = EdltLifecycle(UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml'))
        project = 'LC' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit', '--lock-address', network, '--source', source)
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Lifecycle_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL'); projects.operation('save', project)
                original = self.cli(*args, 'show'); path = Path(directory) / 'original.json'; self.cli(*args, 'export', path)
                metadata = Path(directory) / 'metadata.json'; metadata.write_text(json.dumps(cache(editor, original)))
                self.assertTrue(self.cli('edlt', 'lifecycle-requirements', path)['no_io'])
                plan = self.cli('edlt', 'lifecycle-plan', path, '--metadata', metadata)
                preview = self.cli(*args, '--dry-run', 'edlt-lifecycle', '--metadata', metadata)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes']); self.assertEqual(preview['phases'], plan['phases'])
                self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-lifecycle', '--metadata', metadata)
                self.assertTrue(result['saved']); self.assertEqual(result['parameters'], preview['parameters'])
                self.assertEqual(len(result['parameters']), 874); self.assertFalse(result['database_metadata_created'])
                self.assertEqual(int(result['parameters']['SceneCount'], 0), 8)
                self.assertEqual(int(result['parameters']['InvertDisplay'], 0), 0)
                self.assertFalse(result['cache_freshness_verified']); self.assertFalse(result['physical_device_verified'])
                self.assertIn('database destinations only', self.cli(*args, '--destination', network + '/p/20',
                    'edlt-lifecycle', '--metadata', metadata, status=1)['error'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                runtime = Path(__file__).resolve().parents[1] / 'research/runtime'; runtime.mkdir(exist_ok=True)
                (runtime / 'edlt-lifecycle-cli-report.json').write_text(json.dumps({'passed': True,
                    'explicit_metadata': True, 'phase_plan_matches_preview': True, 'preview_unchanged': True,
                    'all_parameters': 874, 'saved_reloaded': True, 'database_destination_guard': True,
                    'network_opened': False, 'physical_device_verified': False}, indent=2) + '\n')
            finally:
                projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
