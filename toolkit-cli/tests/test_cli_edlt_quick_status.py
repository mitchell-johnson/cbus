"""Quick Status CLI linked thresholds, palettes and native database persistence."""
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
from cbus_toolkit.edlt_quick_status import EdltQuickStatus
from tests.test_edlt import Session
from tests.test_edlt_quick_status import fixture


CUSTOM = ('--mode', 'background', '--group', 42, '--high-threshold', 85, '--low-threshold', 170,
          '--low-colour', 'black', '--middle-colour', 'blue', '--high-colour', 'white')
FIELDS = ('QuickStatusMode', 'QuickStatusGroup', 'QuickStatusColour1', 'QuickStatusColour2',
          'QuickStatusColour3', 'QuickStatusLevel1', 'QuickStatusLevel2')


class QuickStatusCLITests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): code = cli.main(list(map(str, args)))
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_link_order_effective_values_mode_palettes_and_identity_without_io(self):
        spec = fixture(); editor = EdltQuickStatus(spec); session = Session(spec)
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, '_edlt_quick_status', return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            path = Path(directory) / 'values.json'; path.write_text(json.dumps(session.values()))
            result = self.invoke(('edlt', 'quick-status-plan', path, *CUSTOM))
            self.assertEqual([result['raw_values'][name] for name in ('mode', 'group', 'low_colour', 'middle_colour',
                'high_colour', 'low_threshold', 'high_threshold')], [2, 42, 0, 4, 1, 84, 85])
            self.assertEqual(result['threshold_adjustments']['low_threshold'], {'requested': 170, 'effective': 84})
            self.assertEqual(result['threshold_edit_order'], ['low_threshold', 'high_threshold'])
            self.assertFalse(result['database_group_created']); self.assertFalse(result['group_metadata_verified'])
            for options in (('--mode', 'background', '--low-colour', 'orange'), ('--mode', 'off', '--middle-colour', 'black'),
                            ('--group', 255)):
                self.assertIn('error', self.invoke(('edlt', 'quick-status-plan', path, *options), status=1))
            source = {**session.values(), 'QuickStatusLevel1': '170', 'QuickStatusLevel2': '85'}
            path.write_text(json.dumps(source))
            result = self.invoke(('edlt', 'quick-status-plan', path, '--low-threshold', 170))
            self.assertEqual((result['low_threshold'], result['high_threshold']), (170, 85))
            self.assertFalse(result['thresholds_strictly_ordered'])
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            self.assertIn('identity differs', self.invoke(('edlt', 'quick-status-plan', path), status=1)['error'])

    def test_interrupt_retains_attempt_without_save_or_recovery(self):
        spec = fixture(); editor = EdltQuickStatus(spec); session = Session(spec); calls = []
        def fail(name, value):
            calls.append(name); session.current[name] = value; session.connected = False
            raise KeyboardInterrupt('Quick Status SET interrupted')
        session.set = fail; session.save_to_source = Mock(side_effect=AssertionError('No save after interrupt'))
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=nullcontext(session)))), \
                patch.object(cli, '_edlt_quick_status', return_value=editor):
            result = self.invoke(('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                                  'edlt-quick-status', *CUSTOM), status=130)
        evidence = result['edlt_quick_status_evidence']; self.assertEqual(len(calls), 1)
        self.assertEqual(evidence['attempted_parameters'], calls); self.assertTrue(evidence['pp_state_uncertain'])
        self.assertFalse(evidence['saved']); self.assertFalse(evidence['verified']); self.assertEqual(evidence['automatic_retries'], 0)
        session.save_to_source.assert_not_called()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and specifications for Quick Status CLI acceptance')
    def test_native_preview_link_order_palettes_raw_preservation_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'QC' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit', '--lock-address', network, '--source', source)
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'QuickStatus_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL'); projects.operation('save', project)
                original = self.cli(*args, 'show'); path = Path(directory) / 'original.json'; self.cli(*args, 'export', path)
                plan = self.cli('edlt', 'quick-status-plan', path, *CUSTOM)
                preview = self.cli(*args, '--dry-run', 'edlt-quick-status', *CUSTOM)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes']); self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-quick-status', *CUSTOM)
                self.assertTrue(result['saved']); self.assertEqual(result['parameters'], preview['parameters'])
                self.assertEqual([int(result['parameters'][name], 0) for name in FIELDS], [2, 42, 0, 4, 1, 84, 85])
                result = self.cli(*args, 'edlt-quick-status', '--mode', 'page-key', '--low-colour', 'orange')
                self.assertEqual(result['raw_values']['low_colour'], 8)
                result = self.cli(*args, 'edlt-quick-status', '--mode', 'text')
                self.assertEqual(result['raw_values']['low_colour'], 8); self.assertIsNone(result['low_colour'])
                self.assertFalse(result['colour_ui_canonical']['low_colour'])
                self.assertFalse(result['windows_palette_transition_verified'])
                self.assertIn('error', self.cli(*args, 'edlt-quick-status', '--low-colour', 'orange', status=1))
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                result = self.cli(*args, 'edlt-quick-status', '--mode', 'off', '--group', 254,
                                  '--high-threshold', 0, '--low-threshold', 255, '--low-colour', 'none')
                self.assertFalse(result['enabled']); self.assertTrue(result['group_and_threshold_controls_editable'])
                self.assertEqual([int(result['parameters'][name], 0) for name in FIELDS], [0, 254, 0, 4, 1, 0, 1])
                self.assertEqual((result['low_threshold'], result['high_threshold']), (0, 1))
                self.assertIn('error', self.cli(*args, 'edlt-quick-status', '--group', 255, status=1))
                self.assertIn('database destinations only', self.cli(*args, '--destination', network + '/p/20',
                    'edlt-quick-status', '--group', 42, status=1)['error'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                runtime = Path(__file__).resolve().parents[1] / 'research/runtime'; runtime.mkdir(exist_ok=True)
                (runtime / 'edlt-quick-status-cli-report.json').write_text(json.dumps({'passed': True,
                    'all_seven_options_exercised': True, 'preview_unchanged': True, 'saved_reloaded': True,
                    'low_then_high_independent_of_flag_order': True, 'omitted_raw_colour_preserved_by_model': True,
                    'windows_palette_transition_verified': False, 'database_destination_guard': True,
                    'network_opened': False, 'physical_device_verified': False}, indent=2) + '\n')
            finally:
                projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
