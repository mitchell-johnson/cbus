"""MRA CLI acceptance against literal original records and native persistence."""
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
from cbus_toolkit.edlt_mra import EdltMRAWidget
from tests.test_edlt import Session
from tests.test_edlt_hvac import fixture


DEFAULTS = {
    'zone-control': '07001E1D0000000F10030DFFFF00000000000000000000000000000000000000',
    'source-select': '080088880000000000FF0B000000000000000000000000000000000000000000',
    'source-control': '09008A8A000000FF000000000000000000000000000000000000000000000000',
}
ZONE_CUSTOM = '07051E1D0000030F100F0D1A3F00000000000000000000000000000000000000'


class EdltMRACLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = cli.main(list(map(str, args)))
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def test_offline_dispatch_identity_and_distributed_globals_without_io(self):
        spec = fixture(); session = Session(spec); editor = EdltMRAWidget(spec)
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, '_edlt_mra', return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            path = Path(directory) / 'snapshot.json'; path.write_text(json.dumps(session.values()))
            result = self.invoke(('edlt', 'mra-plan', path, '--page', 1, '--position', 1, '--kind', 'zone-control'))
            self.assertEqual(result['record_hex'].upper(), DEFAULTS['zone-control'])
            self.assertEqual((result['globals']['multiplexer'], result['globals']['zone']), (1, 1))
            empty = self.invoke(('edlt', 'mra-globals-plan', path, '--multiplexer', 2), status=1)
            self.assertIn('Create an MRA widget', empty['error'])
            values = editor.snapshot(session.values()); values.update(editor.plan(values, page=1, position=1, kind='zone-control').changes)
            path.write_text(json.dumps(values))
            result = self.invoke(('edlt', 'mra-globals-plan', path, '--multiplexer', 3, '--zone', 8))
            self.assertEqual(result['action'], 'globals'); self.assertIsNone(result['record_hex'])
            self.assertEqual(result['globals']['changes'], {'Widget6WidgetByteValue1': [0xb8]})
            self.assertFalse(result['audio_control_sent']); self.assertFalse(result['physical_device_verified'])
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            for action, options in (('mra-plan', ('--page', 1, '--position', 1, '--kind', 'zone-control')),
                                    ('mra-globals-plan', ())):
                self.assertIn('identity differs', self.invoke(('edlt', action, path, *options), status=1)['error'])

    def test_main_retains_partial_mra_interrupt_and_does_not_save(self):
        spec = fixture(); session = Session(spec); editor = EdltMRAWidget(spec)
        interrupted = KeyboardInterrupt('first MRA PP SET'); calls = []
        def fail(name, value):
            calls.append(name); session.current[name] = value; session.connected = False
            raise interrupted
        session.set = fail; session.save_to_source = Mock(side_effect=AssertionError('No save after interrupt'))
        loader = Mock(return_value=nullcontext(session))
        args = ('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                'edlt-mra', '--page', 1, '--position', 1, '--kind', 'zone-control')
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=loader)), \
                patch.object(cli, '_edlt_mra', return_value=editor):
            result = self.invoke(args, status=130)
        self.assertEqual(len(calls), 1); self.assertEqual(result['error'], 'Interrupted')
        self.assertEqual(result['edlt_mra_evidence']['attempted_parameters'], calls)
        self.assertTrue(result['edlt_mra_evidence']['pp_state_uncertain'])
        self.assertFalse(result['edlt_mra_evidence']['saved']); self.assertFalse(result['edlt_mra_evidence']['verified'])
        self.assertEqual(result['edlt_mra_evidence']['automatic_retries'], 0)
        session.save_to_source.assert_not_called(); loader.assert_called_once()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and specifications for MRA CLI acceptance')
    def test_original_defaults_widgets_shared_globals_preview_save_reload_and_guards(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'MR' + uuid4().hex[:6].upper(); network = '//' + project + '/254'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit',
                '--lock-address', network, '--source', '/db' + network + '/p/20')
        location = ('--page', 1, '--position', 1, '--kind', 'zone-control')
        custom = (*location, '--variant', 'balance', '--ramp-seconds', 1020,
                  '--label-text', 'Kitchen', '--status-type', 'static', '--status-text', 'Audio')
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'MRA_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                projects.operation('save', project)
                original = self.cli(*args, 'show'); path = Path(directory) / 'original.json'
                self.cli(*args, 'export', path)
                for kind, literal in DEFAULTS.items():
                    default = self.cli('edlt', 'mra-plan', path, '--page', 1, '--position', 1, '--kind', kind)
                    self.assertEqual(default['record_hex'].upper(), literal)
                    if kind == 'source-select':
                        self.assertEqual(default['default_status_allocation']['index'], 11)
                        self.assertTrue(default['default_status_allocation']['reused'])
                plan = self.cli('edlt', 'mra-plan', path, *custom)
                self.assertEqual(plan['record_hex'].upper(), ZONE_CUSTOM)
                self.assertEqual(plan['label_allocation']['index'], 26)
                self.assertTrue(plan['label_allocation']['reused'])
                self.assertEqual(plan['status_allocation']['index'], 63)
                preview = self.cli(*args, '--dry-run', 'edlt-mra', *custom)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes']); self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-mra', *custom)
                self.assertTrue(result['saved']); self.assertEqual(result['parameters'], preview['parameters'])
                for kind, position in (('source-select', 2), ('source-control', 3)):
                    result = self.cli(*args, 'edlt-mra', '--page', 1, '--position', position, '--kind', kind)
                    self.assertEqual(result['record_hex'].upper(), DEFAULTS[kind])
                path = Path(directory) / 'three-widgets.json'
                self.cli(*args, 'export', path)
                globals_plan = self.cli('edlt', 'mra-globals-plan', path, '--multiplexer', 3, '--zone', 8)
                self.assertEqual(globals_plan['globals']['changes'], {'Widget6WidgetByteValue1': [0xbd],
                    'Widget7WidgetByteValue1': [0xb8], 'Widget8WidgetByteValue1': [0xb8]})
                globals_preview = self.cli(*args, '--dry-run', 'edlt-mra-globals', '--multiplexer', 3, '--zone', 8)
                self.assertEqual(globals_preview['changes'], globals_plan['changes'])
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                globals_result = self.cli(*args, 'edlt-mra-globals', '--multiplexer', 3, '--zone', 8)
                self.assertEqual(globals_result['parameters'], globals_preview['parameters'])
                self.assertTrue(globals_result['saved']); self.assertFalse(globals_result['audio_control_sent'])
                result = self.cli(*args, 'edlt-mra', '--page', 1, '--position', 2, '--kind', 'source-select',
                    '--variant', 'two-absolute', '--source1', 1, '--source2', 7, '--label-text', 'Kitchen',
                    '--status-text', 'Audio', '--on-icon', 38)
                self.assertEqual(bytes.fromhex(result['record_hex'])[:11], bytes((8, 0xb8, 38, 38, 0, 0, 2, 0, 6, 26, 63)))
                self.assertEqual(result['source_bytes'], [0, 6])
                self.assertEqual((result['globals']['multiplexer'], result['globals']['zone']), (3, 8))
                result = self.cli(*args, 'edlt-mra', '--page', 1, '--position', 3, '--kind', 'source-control',
                    '--variant', 'dynamic-1-and-2', '--on-icon', 254, '--label-text', '')
                self.assertEqual(bytes.fromhex(result['record_hex'])[:8], bytes((9, 0xb8, 254, 254, 0, 0, 2, 255)))
                for invalid in (('--multiplexer', 4), ('--zone', 0), ('--label-index', 64),
                    ('--label-text', 'X', '--label-index', 1), ('--variant', 'two-absolute'),
                    ('--key-mode', 'nudge', '--ramp-seconds', 4), ('--on-icon', 39), ('--source1', 1)):
                    self.assertIn('error', self.cli(*args, 'edlt-mra', *location, *invalid, status=1))
                self.assertIn('error', self.cli(*args, 'edlt-mra', '--page', 0, '--position', 1, '--kind', 'zone-control', status=1))
                for action in ('edlt-mra', 'edlt-mra-globals'):
                    options = location if action == 'edlt-mra' else ('--multiplexer', 2)
                    rejected = self.cli(*args, '--destination', network + '/p/20', action, *options, status=1)
                    self.assertIn('database destinations only', rejected['error'])
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                report = {'passed': True, 'original_default_records': DEFAULTS, 'original_custom_zone_record': ZONE_CUSTOM,
                    'database_saved_reloaded': True, 'offline_preview_changes_match': True, 'preview_database_unchanged': True,
                    'distributed_globals': {'multiplexer': 3, 'zone': 8, 'widgets': [6, 7, 8]},
                    'database_destination_guard': True, 'network_opened': False, 'physical_device_verified': False,
                    'audio_control_sent': False}
                runtime = Path(__file__).resolve().parents[1] / 'research/runtime'; runtime.mkdir(exist_ok=True)
                (runtime / 'edlt-mra-cli-report.json').write_text(json.dumps(report, indent=2) + '\n')
            finally:
                projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
