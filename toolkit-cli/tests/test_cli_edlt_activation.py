"""Activation CLI event selectors, standby dependencies and native persistence."""
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
from cbus_toolkit.edlt_activation import EdltActivation
from tests.test_edlt import Session
from tests.test_edlt_activation import fixture


CUSTOM = ('--wake-mode', 'primary-event', '--group', 255, '--level', 255, '--activation-page', 'page-1')
FIELDS = ('ProximityMode', 'ProximityGroup', 'ProximityLevel', 'DeafultPage', 'IgnoreFirstKeyPress')


class ActivationCLITests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): code = cli.main(list(map(str, args)))
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_event_action_routing_and_existing_state_dependencies_without_io(self):
        spec = fixture(); editor = EdltActivation(spec); session = Session(spec)
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, '_edlt_activation', return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            path = Path(directory) / 'values.json'; path.write_text(json.dumps(session.values()))
            result = self.invoke(('edlt', 'activation-plan', path, *CUSTOM))
            self.assertEqual([result['raw_values'][name] for name in FIELDS], [2, 255, 255, 1, 0])
            self.assertTrue(result['editable']['level']); self.assertFalse(result['event_configured'])
            self.assertEqual(result['event_application'], 56)
            result = self.invoke(('edlt', 'activation-plan', path, '--wake-mode', 'trigger-event', '--group', 7, '--action-selector', 0))
            self.assertEqual((result['action'], result['event_value'], result['event_application']), (0, 0, 202))
            self.assertFalse(result['database_group_created']); self.assertFalse(result['database_action_verified'])
            for options in (('--wake-mode', 'trigger-event', '--group', 255, '--action-selector', 1),
                            ('--wake-mode', 'primary-event', '--action-selector', 1),
                            ('--wake-mode', 'trigger-event', '--group', 7, '--level', 0, '--action-selector', 1),
                            ('--wake-mode', 'key-press', '--ignore-first-key-press')):
                self.assertIn('error', self.invoke(('edlt', 'activation-plan', path, *options), status=1))
            path.write_text(json.dumps({**session.values(), 'TimeoutPage': '1'}))
            result = self.invoke(('edlt', 'activation-plan', path, '--wake-mode', 'key-press', '--ignore-first-key-press'))
            self.assertTrue(result['ignore_first_key_press'])
            self.assertIn('hidden or disabled', self.invoke(('edlt', 'activation-plan', path, '--activation-page', 'last-active'), status=1)['error'])
            path.write_text(json.dumps({**session.values(), 'ActivityDuration': '0'}))
            self.assertFalse(self.invoke(('edlt', 'activation-plan', path))['activation_controls_enabled'])
            self.assertIn('Standby', self.invoke(('edlt', 'activation-plan', path, '--wake-mode', 'wake-unit'), status=1)['error'])
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            self.assertIn('identity differs', self.invoke(('edlt', 'activation-plan', path), status=1)['error'])

    def test_interrupt_retains_attempt_without_save_or_recovery(self):
        spec = fixture(); editor = EdltActivation(spec); session = Session(spec); calls = []
        def fail(name, value):
            calls.append(name); session.current[name] = value; session.connected = False
            raise KeyboardInterrupt('activation SET interrupted')
        session.set = fail; session.save_to_source = Mock(side_effect=AssertionError('No save after interrupt'))
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=nullcontext(session)))), \
                patch.object(cli, '_edlt_activation', return_value=editor):
            result = self.invoke(('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                                  'edlt-activation', *CUSTOM), status=130)
        evidence = result['edlt_activation_evidence']; self.assertEqual(len(calls), 1)
        self.assertEqual(evidence['attempted_parameters'], calls); self.assertTrue(evidence['pp_state_uncertain'])
        self.assertFalse(evidence['saved']); self.assertFalse(evidence['verified']); self.assertEqual(evidence['automatic_retries'], 0)
        session.save_to_source.assert_not_called()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and specifications for activation CLI acceptance')
    def test_native_preview_event_modes_hidden_values_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'AC' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit', '--lock-address', network, '--source', source)
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Activation_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL'); projects.operation('save', project)
                original = self.cli(*args, 'show'); path = Path(directory) / 'original.json'; self.cli(*args, 'export', path)
                plan = self.cli('edlt', 'activation-plan', path, *CUSTOM)
                preview = self.cli(*args, '--dry-run', 'edlt-activation', *CUSTOM)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes']); self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-activation', *CUSTOM)
                self.assertTrue(result['saved']); self.assertEqual(result['parameters'], preview['parameters'])
                self.assertEqual([int(result['parameters'][name], 0) for name in FIELDS], [2, 255, 255, 1, 0])
                result = self.cli(*args, 'edlt-activation', '--group', 42, '--level', 173)
                result = self.cli(*args, 'edlt-activation', '--wake-mode', 'trigger-event')
                self.assertEqual([int(result['parameters'][name], 0) for name in FIELDS], [3, 42, 173, 1, 0])
                self.assertTrue(result['reference_application_changed']); self.assertEqual(result['previous_reference_application'], 56)
                self.assertEqual(result['reference_application'], 202); self.assertFalse(result['database_group_verified'])
                result = self.cli(*args, 'edlt-activation', '--group', 7, '--action-selector', 42)
                self.assertEqual((result['group'], result['action']), (7, 42))
                self.assertIn('error', self.cli(*args, 'edlt-activation', '--group', 255, '--action-selector', 0, status=1))
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.cli(*args, 'edlt-standby', '--timeout-page', 'current')
                result = self.cli(*args, 'edlt-activation', '--wake-mode', 'key-press', '--ignore-first-key-press')
                self.assertEqual([int(result['parameters'][name], 0) for name in FIELDS], [0, 7, 42, 1, 1])
                self.assertIn('hidden or disabled', self.cli(*args, 'edlt-activation', '--activation-page', 'last-active', status=1)['error'])
                result = self.cli(*args, 'edlt-activation', '--no-ignore-first-key-press')
                self.assertFalse(result['ignore_first_key_press'])
                self.cli(*args, 'edlt-standby', '--timeout-page', 'standby')
                result = self.cli(*args, 'edlt-activation', '--wake-mode', 'wake-unit', '--activation-page', 'last-active')
                self.assertEqual([int(result['parameters'][name], 0) for name in FIELDS], [1, 7, 42, 0, 0])
                self.cli(*args, 'edlt-standby', '--no-enabled')
                result = self.cli(*args, 'edlt-activation')
                self.assertFalse(result['activation_controls_enabled'])
                self.assertEqual([int(result['parameters'][name], 0) for name in FIELDS], [1, 7, 42, 0, 0])
                self.assertIn('Standby', self.cli(*args, 'edlt-activation', '--wake-mode', 'primary-event', status=1)['error'])
                self.assertIn('database destinations only', self.cli(*args, '--destination', network + '/p/20',
                    'edlt-activation', status=1)['error'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                runtime = Path(__file__).resolve().parents[1] / 'research/runtime'; runtime.mkdir(exist_ok=True)
                (runtime / 'edlt-activation-cli-report.json').write_text(json.dumps({'passed': True,
                    'all_six_options_exercised': True, 'preview_unchanged': True, 'saved_reloaded': True,
                    'action_selector_does_not_overwrite_command': True, 'unused_primary_group_level_editable': True,
                    'retained_numeric_group_application_change_reported': True, 'hidden_values_preserved': True,
                    'database_destination_guard': True, 'network_opened': False, 'physical_device_verified': False}, indent=2) + '\n')
            finally:
                projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
