"""General eDLT CLI: original time units, omitted values and database persistence."""
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
from cbus_toolkit.edlt_general import EdltGeneralSettings
from tests.test_edlt import Session
from tests.test_edlt_general import fixture


class EdltGeneralCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): code = cli.main(list(map(str, args)))
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def test_offline_dispatch_omitted_flags_timing_units_and_identity(self):
        spec = fixture(); editor = EdltGeneralSettings(spec); session = Session(spec)
        values = session.values(); values.update(LongPressTime='0', StatusRequestInterval='2', ToolsPageLocked='1')
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, '_edlt_general', return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            path = Path(directory) / 'values.json'; path.write_text(json.dumps(values))
            plan = self.invoke(('edlt', 'general-plan', path, '--debounce-ms', 6375))
            self.assertEqual((plan['long_press_ms'], plan['debounce_ms'], plan['status_report_seconds']), (0, 6375, 2))
            self.assertTrue(plan['tools_page_locked']); self.assertEqual(plan['power_restore'], 'preset')
            self.assertFalse(plan['long_press_ui_canonical']); self.assertFalse(plan['status_report_ui_canonical'])
            result = self.invoke(('edlt', 'general-plan', path, '--long-press-ms', 400, '--status-report-seconds', 3,
                                  '--no-tools-page-locked', '--power-restore', 'previous'))
            self.assertEqual(result['changes']['LongPressTime'], [16]); self.assertFalse(result['tools_page_locked'])
            self.assertEqual(result['changes']['EnableLevelStore'], [1]); self.assertFalse(result['power_cycle_verified'])
            self.assertEqual(json.loads(path.read_text()), values)
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            self.assertIn('identity differs', self.invoke(('edlt', 'general-plan', path), status=1)['error'])

    def test_actual_main_retains_partial_interrupt_without_save_or_recovery(self):
        spec = fixture(); session = Session(spec); editor = EdltGeneralSettings(spec)
        error = KeyboardInterrupt('first general SET'); calls = []
        def fail(name, value):
            calls.append(name); session.current[name] = value; session.connected = False; raise error
        session.set = fail; session.save_to_source = Mock(side_effect=AssertionError('No save after interrupt'))
        loader = Mock(return_value=nullcontext(session))
        args = ('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                'edlt-general', '--long-press-ms', 1000)
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=loader)), \
                patch.object(cli, '_edlt_general', return_value=editor):
            result = self.invoke(args, status=130)
        self.assertEqual(result['error'], 'Interrupted'); self.assertEqual(len(calls), 1)
        self.assertEqual(result['edlt_general_evidence']['attempted_parameters'], calls)
        self.assertTrue(result['edlt_general_evidence']['pp_state_uncertain'])
        self.assertFalse(result['edlt_general_evidence']['saved']); self.assertFalse(result['edlt_general_evidence']['verified'])
        self.assertEqual(result['edlt_general_evidence']['automatic_retries'], 0)
        session.save_to_source.assert_not_called(); loader.assert_called_once()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and specifications for general CLI acceptance')
    def test_native_preview_full_save_restore_mode_and_input_guards(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'GC' + uuid4().hex[:6].upper(); network = '//' + project + '/254'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit',
                '--lock-address', network, '--source', '/db' + network + '/p/20')
        custom = ('--long-press-ms', 6375, '--debounce-ms', 0, '--status-report-seconds', 255,
                  '--tools-page-locked', '--power-restore', 'previous')
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'General_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL'); projects.operation('save', project)
                original = self.cli(*args, 'show'); path = Path(directory) / 'original.json'; self.cli(*args, 'export', path)
                plan = self.cli('edlt', 'general-plan', path, *custom)
                preview = self.cli(*args, '--dry-run', 'edlt-general', *custom)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes']); self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-general', *custom)
                self.assertTrue(result['saved']); self.assertEqual(result['parameters'], preview['parameters'])
                fields = ('LongPressTime', 'DebounceTime', 'StatusRequestInterval', 'ToolsPageLocked', 'EnableLevelStore')
                self.assertEqual([int(result['parameters'][name], 0) for name in fields], [255, 0, 255, 1, 1])
                previous_restores = {name: value for name, value in result['parameters'].items() if name.endswith('RestoreLevel')}
                result = self.cli(*args, 'edlt-general', '--power-restore', 'preset', '--no-tools-page-locked')
                self.assertEqual([int(result['parameters'][name], 0) for name in fields], [255, 0, 255, 0, 0])
                self.assertEqual({name: value for name, value in result['parameters'].items() if name.endswith('RestoreLevel')}, previous_restores)
                for option in (('--long-press-ms', 0), ('--long-press-ms', 26), ('--debounce-ms', 6400),
                               ('--debounce-ms', -25), ('--status-report-seconds', 2), ('--status-report-seconds', 256)):
                    self.assertIn('error', self.cli(*args, 'edlt-general', *option, status=1))
                rejected = self.cli(*args, '--destination', network + '/p/20', 'edlt-general', '--power-restore', 'previous', status=1)
                self.assertIn('database destinations only', rejected['error'])
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                report = {'passed': True, 'saved_reloaded': True, 'offline_preview_changes_match': True,
                    'preview_database_unchanged': True, 'omitted_settings_preserved': True, 'power_restore_presets_preserved': True,
                    'database_destination_guard': True, 'network_opened': False, 'physical_device_verified': False, 'power_cycle_verified': False}
                runtime = Path(__file__).resolve().parents[1] / 'research/runtime'; runtime.mkdir(exist_ok=True)
                (runtime / 'edlt-general-cli-report.json').write_text(json.dumps(report, indent=2) + '\n')
            finally:
                projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
