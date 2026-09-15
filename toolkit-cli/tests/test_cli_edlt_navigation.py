"""Navigation CLI static names, cached dynamic labels and database persistence."""
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
from cbus_toolkit.edlt_navigation import EdltNavigation
from tests.test_edlt import Session
from tests.test_edlt_navigation import fixture, metadata


STATIC = ('--page-mode', 'multiple', '--variant', 'page-names', '--page-name', 4, 'CLI Living',
          '--page-name', 2, 'CLI Living', '--page-name', 1, 'Entrée', '--page-name', 3, '')


class NavigationCLITests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): code = cli.main(list(map(str, args)))
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_page_order_unicode_reuse_and_duplicate_arguments_without_io(self):
        spec = fixture(); editor = EdltNavigation(spec); session = Session(spec)
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, '_edlt_navigation', return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            path = Path(directory) / 'values.json'; path.write_text(json.dumps(session.values()))
            result = self.invoke(('edlt', 'navigation-plan', path, *STATIC))
            self.assertEqual(result['page_name_indices'], {'1': 63, '2': 62, '3': 255, '4': 62})
            self.assertTrue(result['static_allocations']['4']['reused'])
            self.assertEqual(bytes(result['changes']['StaticTextString63']).rstrip(b'\0').decode('utf-8'), 'Entrée')
            for invalid in (('--page-name', 1, 'A', '--page-name', '0x1', 'B'),
                            ('--page-name-index', 1, 0, '--page-name-index', 1, 1),
                            ('--page-name', 0, 'A'), ('--page-name', 'no', 'A'),
                            ('--page-name-index', 1, 'no'), ('--page-name', 1, 'A', '--page-name-index', 1, 0)):
                self.assertIn('error', self.invoke(('edlt', 'navigation-plan', path, '--page-mode', 'multiple',
                                                  '--variant', 'page-names', *invalid), status=1))
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            self.assertIn('identity differs', self.invoke(('edlt', 'navigation-plan', path), status=1)['error'])

    def test_metadata_file_strictness_and_reference_provenance(self):
        spec = fixture(); editor = EdltNavigation(spec); session = Session(spec)
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, '_edlt_navigation', return_value=editor):
            path, meta = Path(directory) / 'values.json', Path(directory) / 'metadata.json'
            path.write_text(json.dumps(session.values())); meta.write_text(json.dumps(metadata()))
            args = ('edlt', 'navigation-plan', path, '--page-mode', 'multiple', '--variant', 'dynamic-labels',
                    '--dynamic-group', 42, '--page-name-index', 4, 3)
            self.assertIn('metadata', self.invoke(args, status=1)['error'])
            result = self.invoke((*args, '--metadata', meta))
            self.assertEqual(result['page_name_indices'], {'1': 0, '2': 0, '3': 0, '4': 3})
            self.assertEqual(result['dynamic_group_metadata']['status'], 'caller-cache-match')
            self.assertFalse(result['physical_dynamic_labels_verified'])
            for document in (metadata(group=43), metadata(variants=(0,)), metadata(group=255, variants=())):
                meta.write_text(json.dumps(document)); self.assertIn('error', self.invoke((*args, '--metadata', meta), status=1))
            for raw in ('{"format":"x","format":"cbus-edlt-navigation-metadata-v1","groups":[]}',
                        '{"format":"cbus-edlt-navigation-metadata-v1","groups":[{"application":56,"group":42,"group":43,"dynamic_variants":[]}]}',
                        ' ' * (256 * 1024 + 1), '{', '[1]'):
                meta.write_text(raw); self.assertIn('error', self.invoke((*args, '--metadata', meta), status=1))
            loader = Mock(return_value=Mock(__enter__=Mock(side_effect=AssertionError('Invalid metadata must not load PP'))))
            with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                    patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=loader)):
                self.invoke(('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                             'edlt-navigation', '--metadata', meta), status=1)
            loader.return_value.__enter__.assert_not_called()

    def test_interrupt_retains_partial_attempt_without_save(self):
        spec = fixture(); editor = EdltNavigation(spec); session = Session(spec); calls = []
        def fail(name, value):
            calls.append(name); session.current[name] = value; session.connected = False
            raise KeyboardInterrupt('navigation SET interrupted')
        session.set = fail; session.save_to_source = Mock(side_effect=AssertionError('No save after interrupt'))
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=nullcontext(session)))), \
                patch.object(cli, '_edlt_navigation', return_value=editor):
            result = self.invoke(('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                                  'edlt-navigation', *STATIC), status=130)
        evidence = result['edlt_navigation_evidence']; self.assertEqual(len(calls), 1)
        self.assertEqual(evidence['attempted_parameters'], calls); self.assertTrue(evidence['pp_state_uncertain'])
        self.assertFalse(evidence['saved']); self.assertFalse(evidence['verified']); self.assertEqual(evidence['automatic_retries'], 0)
        session.save_to_source.assert_not_called()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and specifications for navigation CLI acceptance')
    def test_native_preview_names_metadata_temperature_hidden_values_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'NC' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit', '--lock-address', network, '--source', source)
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Navigation_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL'); projects.operation('save', project)
                original = self.cli(*args, 'show'); path = Path(directory) / 'original.json'; self.cli(*args, 'export', path)
                plan = self.cli('edlt', 'navigation-plan', path, *STATIC)
                preview = self.cli(*args, '--dry-run', 'edlt-navigation', *STATIC)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes']); self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-navigation', *STATIC)
                self.assertTrue(result['saved']); self.assertEqual(result['parameters'], preview['parameters'])
                self.assertEqual(result['page_name_indices'], {'1': 63, '2': 62, '3': 255, '4': 62})
                result = self.cli(*args, 'edlt-navigation', '--variant', 'page-names')
                self.assertEqual(result['page_name_indices'], {'1': 63, '2': 62, '3': 255, '4': 62})
                meta = Path(directory) / 'metadata.json'; meta.write_text(json.dumps(metadata()))
                dynamic = ('--variant', 'dynamic-labels', '--dynamic-group', 42, '--page-name-index', 1, 3,
                           '--page-name-index', 2, 2, '--page-name-index', 3, 1, '--page-name-index', 4, 0)
                self.assertIn('metadata', self.cli(*args, 'edlt-navigation', *dynamic, status=1)['error'])
                result = self.cli(*args, 'edlt-navigation', *dynamic, '--metadata', meta)
                self.assertEqual(result['page_name_indices'], {'1': 3, '2': 2, '3': 1, '4': 0})
                self.assertEqual(result['dynamic_group_metadata']['status'], 'caller-cache-match')
                self.assertFalse(result['physical_dynamic_labels_verified'])
                result = self.cli(*args, 'edlt-navigation', '--variant', 'time-temperature', '--temperature-source', 'measurement',
                                  '--device-or-group', 255, '--channel-or-zone', 255)
                self.assertEqual((result['device_or_group'], result['channel_or_zone']), (255, 255))
                meta.write_text(json.dumps(metadata(application=172, group=42, variants=())))
                result = self.cli(*args, 'edlt-navigation', '--variant', 'date-temperature', '--temperature-source', 'hvac',
                                  '--device-or-group', 42, '--channel-or-zone', 4, '--metadata', meta)
                self.assertEqual(result['temperature_group_metadata']['status'], 'caller-cache-match')
                self.assertEqual([int(result['parameters'][name], 0) for name in (
                    'NavWidgetType', 'NavWidgetVariant', 'TemperatureApplication', 'NavDevIDZoneGroup', 'NavChannelZoneNumber')], [1, 4, 1, 42, 4])
                self.assertIn('error', self.cli(*args, 'edlt-navigation', '--channel-or-zone', 5, status=1))
                before = result['parameters']; result = self.cli(*args, 'edlt-navigation', '--page-mode', 'single')
                for name in ('NavWidgetVariant', 'TemperatureApplication', 'NavDevIDZoneGroup', 'NavChannelZoneNumber', 'PageNameIndex1'):
                    self.assertEqual(result['parameters'][name], before[name])
                self.assertIn('multiple', self.cli(*args, 'edlt-navigation', '--variant', 'blank', status=1)['error'])
                self.assertIn('database destinations only', self.cli(*args, '--destination', network + '/p/20',
                    'edlt-navigation', '--page-mode', 'multiple', status=1)['error'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                runtime = Path(__file__).resolve().parents[1] / 'research/runtime'; runtime.mkdir(exist_ok=True)
                (runtime / 'edlt-navigation-cli-report.json').write_text(json.dumps({'passed': True, 'saved_reloaded': True,
                    'preview_unchanged': True, 'unicode_static_names_and_sorted_reuse': True, 'metadata_required_for_dynamic_indices': True,
                    'temperature_sources_and_bounds': True, 'hidden_values_preserved': True, 'database_destination_guard': True,
                    'network_opened': False, 'physical_device_verified': False}, indent=2) + '\n')
            finally:
                projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
