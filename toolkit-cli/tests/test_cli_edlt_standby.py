"""Standby CLI: original enable quirks, hidden controls and programming destination."""
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
from cbus_toolkit.edlt_standby import EdltStandby
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from tests.test_edlt import Session, fixture as common_fixture


def fixture():
    base = common_fixture(); params = dict(base.parameters)
    for name, address, kind, bit, size, default in (
        ('ActivityDuration', 0x11b, 'int', 0, 8, 30), ('TimeoutPage', 0x11a, 'int', 5, 2, 2),
        ('EnableNightlightUserKey', 0x116, 'bit', 6, 1, 0), ('EnableNightlightPageKey', 0x116, 'bit', 7, 1, 0),
        ('NightlightColour', 0x117, 'int', 3, 2, 1)):
        params[name] = ParameterSpec(name, kind, 'synthetic.xml', {'Name': name, 'Type': kind,
            'Address': hex(address), 'BitAddress': str(bit), 'BitSize': str(size), 'DefaultValue': str(default)})
    return UnitSpec(base.filename, base.metadata, base.sources, params)


class EdltStandbyCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): code = cli.main(list(map(str, args)))
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def test_offline_defaults_enabled_order_and_export_identity_without_io(self):
        spec = fixture(); session = Session(spec); editor = EdltStandby(spec)
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, '_edlt_standby', return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            path = Path(directory) / 'values.json'; path.write_text(json.dumps(session.values()))
            original = self.invoke(('edlt', 'standby-plan', path))
            self.assertEqual(original['after_seconds'], 30); self.assertEqual(original['timeout_page'], 'standby')
            self.assertEqual(self.invoke(('edlt', 'standby-plan', path, '--enabled'))['after_seconds'], 3)
            result = self.invoke(('edlt', 'standby-plan', path, '--enabled', '--after-seconds', 255, '--timeout-page', 'page-1',
                '--nightlight-user-keys', '--nightlight-page-key', '--nightlight-colour', 'quick-status-colour'))
            self.assertEqual(result['after_seconds'], 255); self.assertEqual(result['timeout_page'], 'page-1')
            self.assertEqual(result['timeout_page_raw'], 0); self.assertTrue(result['nightlight_colour_control_enabled'])
            self.assertEqual(result['nightlight_colour'], 'quick-status-colour')
            self.assertFalse(self.invoke(('edlt', 'standby-plan', path, '--no-enabled'))['enabled'])
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            self.assertIn('identity differs', self.invoke(('edlt', 'standby-plan', path), status=1)['error'])

    def test_main_retains_partial_interrupt_without_save_or_recovery(self):
        spec = fixture(); session = Session(spec); editor = EdltStandby(spec)
        error = KeyboardInterrupt('standby SET interrupted'); calls = []
        def fail(name, value):
            calls.append(name); session.current[name] = value; session.connected = False; raise error
        session.set = fail; session.save_to_source = Mock(side_effect=AssertionError('No save after interrupt'))
        loader = Mock(return_value=nullcontext(session))
        args = ('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                'edlt-standby', '--enabled')
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=loader)), \
                patch.object(cli, '_edlt_standby', return_value=editor):
            result = self.invoke(args, status=130)
        self.assertEqual(result['error'], 'Interrupted'); self.assertEqual(len(calls), 1)
        self.assertEqual(result['edlt_standby_evidence']['attempted_parameters'], calls)
        self.assertTrue(result['edlt_standby_evidence']['pp_state_uncertain'])
        self.assertFalse(result['edlt_standby_evidence']['saved']); self.assertFalse(result['edlt_standby_evidence']['verified'])
        self.assertEqual(result['edlt_standby_evidence']['automatic_retries'], 0)
        session.save_to_source.assert_not_called(); loader.assert_called_once()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and specifications for standby CLI acceptance')
    def test_native_preview_enable_duration_hidden_fields_destinations_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'SC' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit', '--lock-address', network, '--source', source)
        custom = ('--enabled', '--after-seconds', 255, '--timeout-page', 'page-1', '--nightlight-user-keys',
                  '--nightlight-page-key', '--nightlight-colour', 'quick-status-colour')
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Standby_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL'); projects.operation('save', project)
                original = self.cli(*args, 'show'); path = Path(directory) / 'original.json'; self.cli(*args, 'export', path)
                plan = self.cli('edlt', 'standby-plan', path, *custom)
                preview = self.cli(*args, '--dry-run', 'edlt-standby', *custom)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes']); self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-standby', *custom)
                self.assertTrue(result['saved']); self.assertEqual(result['parameters'], preview['parameters'])
                self.assertEqual(result['destination'], source); self.assertEqual(result['timeout_page'], 'page-1')
                fields = ('ActivityDuration', 'TimeoutPage', 'EnableNightlightUserKey', 'EnableNightlightPageKey', 'NightlightColour')
                self.assertEqual([int(result['parameters'][name], 0) for name in fields], [255, 0, 1, 1, 3])
                result = self.cli(*args, 'edlt-standby', '--no-enabled')
                self.assertFalse(result['enabled']); self.assertFalse(result['nightlight_colour_control_enabled'])
                self.assertEqual([int(result['parameters'][name], 0) for name in fields], [0, 0, 1, 1, 3])
                for options in (('--after-seconds', 60), ('--timeout-page', 'current'), ('--no-nightlight-page-key',)):
                    self.assertIn('enabled', self.cli(*args, 'edlt-standby', *options, status=1)['error'])
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                result = self.cli(*args, 'edlt-standby', '--enabled')
                self.assertEqual(result['after_seconds'], 3); self.assertTrue(result['nightlight_user_keys'])
                result = self.cli(*args, 'edlt-standby', '--after-seconds', 1)
                self.assertEqual(self.cli(*args, 'edlt-standby', '--enabled')['after_seconds'], 1)
                self.cli(*args, 'edlt-standby', '--after-seconds', 30)
                self.assertEqual(self.cli(*args, 'edlt-standby', '--enabled')['after_seconds'], 3)
                for destination, value in (('current', 1), ('page-1', 0), ('standby', 2)):
                    result = self.cli(*args, 'edlt-standby', '--timeout-page', destination)
                    self.assertEqual(result['timeout_page'], destination); self.assertEqual(result['timeout_page_raw'], value)
                    self.assertEqual(result['destination'], source)
                result = self.cli(*args, 'edlt-standby', '--no-nightlight-user-keys', '--no-nightlight-page-key')
                self.assertFalse(result['nightlight_colour_control_enabled'])
                self.assertEqual(result['nightlight_colour'], 'quick-status-colour')
                rejected = self.cli(*args, 'edlt-standby', '--nightlight-colour', 'off-colour', status=1)
                self.assertIn('nightlight', rejected['error'])
                for colour in ('off-colour', 'on-colour', 'page-key-colour', 'quick-status-colour'):
                    result = self.cli(*args, 'edlt-standby', '--nightlight-page-key', '--nightlight-colour', colour)
                    self.assertEqual(result['nightlight_colour'], colour)
                for value in (0, 256):
                    self.assertIn('error', self.cli(*args, 'edlt-standby', '--after-seconds', value, status=1))
                rejected = self.cli(*args, '--destination', network + '/p/20', 'edlt-standby', '--enabled', status=1)
                self.assertIn('database destinations only', rejected['error'])
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                report = {'passed': True, 'saved_reloaded': True, 'original_custom_fields': dict(zip(fields, [255, 0, 1, 1, 3])),
                    'offline_preview_changes_match': True, 'preview_database_unchanged': True,
                    'enable_duration_cases': {'from_zero': 3, 'from_one': 1, 'from_thirty': 3},
                    'hidden_nightlight_values_retained': True, 'timeout_page_and_programming_destination_distinct': True,
                    'database_destination_guard': True, 'network_opened': False, 'physical_device_verified': False}
                runtime = Path(__file__).resolve().parents[1] / 'research/runtime'; runtime.mkdir(exist_ok=True)
                (runtime / 'edlt-standby-cli-report.json').write_text(json.dumps(report, indent=2) + '\n')
            finally:
                projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
