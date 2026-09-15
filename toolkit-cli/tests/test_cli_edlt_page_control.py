"""Page Control CLI boundaries, cancellation evidence and database persistence."""
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
from cbus_toolkit.edlt_page_control import EdltPageControl
from tests.test_edlt import Session
from tests.test_edlt_page_control import fixture


class PageControlCLITests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): code = cli.main(list(map(str, args)))
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_groups_no_standby_dependency_and_profile_guard_without_io(self):
        spec = fixture(); editor = EdltPageControl(spec); session = Session(spec)
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, '_edlt_page_control', return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            path = Path(directory) / 'values.json'; path.write_text(json.dumps(session.values()))
            for group in (0, 1, 42, 254, 255):
                result = self.invoke(('edlt', 'page-control-plan', path, '--group', group))
                self.assertEqual((result['group'], result['application'], result['enabled']), (group, 203, group != 255))
                self.assertFalse(result['database_group_created']); self.assertFalse(result['physical_page_control_verified'])
                self.assertNotIn('ActivityDuration', result['changes'])
                self.assertNotIn('BacklightActiveBrightnessControlGroup', result['changes'])
                self.assertNotIn('CorridorLinkingLinkGroup', result['changes'])
            self.assertEqual(self.invoke(('edlt', 'page-control-plan', path))['group'], 255)
            for value in ('-1', '256', 'true'):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    cli.build_parser().parse_args(['edlt', 'page-control-plan', str(path), '--group', value])
                self.assertEqual(caught.exception.code, 2)
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            self.assertIn('identity differs', self.invoke(('edlt', 'page-control-plan', path), status=1)['error'])

    def test_interrupt_retains_first_attempt_and_does_not_save(self):
        spec = fixture(); editor = EdltPageControl(spec); session = Session(spec); calls = []
        def fail(name, value):
            calls.append(name); session.current[name] = value; session.connected = False
            raise KeyboardInterrupt('Page Control SET interrupted')
        session.set = fail; session.save_to_source = Mock(side_effect=AssertionError('No save after interrupt'))
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=nullcontext(session)))), \
                patch.object(cli, '_edlt_page_control', return_value=editor):
            result = self.invoke(('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                                  'edlt-page-control', '--group', 42), status=130)
        evidence = result['edlt_page_control_evidence']; self.assertEqual(len(calls), 1)
        self.assertEqual(evidence['attempted_parameters'], calls); self.assertTrue(evidence['pp_state_uncertain'])
        self.assertFalse(evidence['saved']); self.assertFalse(evidence['verified']); self.assertEqual(evidence['automatic_retries'], 0)
        session.save_to_source.assert_not_called()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and specifications for Page Control CLI acceptance')
    def test_native_preview_groups_disabled_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'PC' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit', '--lock-address', network, '--source', source)
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Page_Control_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL'); projects.operation('save', project)
                self.cli(*args, 'edlt-standby', '--no-enabled')
                original = self.cli(*args, 'show'); path = Path(directory) / 'original.json'; self.cli(*args, 'export', path)
                plan = self.cli('edlt', 'page-control-plan', path, '--group', 42)
                preview = self.cli(*args, '--dry-run', 'edlt-page-control', '--group', 42)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved']); self.assertEqual(preview['changes'], plan['changes'])
                self.assertEqual(self.cli(*args, 'show'), original)
                for group in (0, 1, 42, 254, 255):
                    result = self.cli(*args, 'edlt-page-control', '--group', group)
                    self.assertTrue(result['saved']); self.assertEqual(int(result['parameters']['KeySetsEnableGroup'], 0), group)
                    self.assertEqual(result['enabled'], group != 255); self.assertEqual(result['application'], 203)
                    self.assertFalse(result['database_group_verified']); self.assertFalse(result['physical_page_control_verified'])
                    self.assertEqual(result['parameters']['ActivityDuration'], original['ActivityDuration'])
                    for name in ('BacklightActiveBrightnessControlGroup', 'CorridorLinkingLinkGroup'):
                        self.assertEqual(result['parameters'][name], original[name])
                self.assertIn('database destinations only', self.cli(*args, '--destination', network + '/p/20',
                    'edlt-page-control', '--group', 42, status=1)['error'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                runtime = Path(__file__).resolve().parents[1] / 'research/runtime'; runtime.mkdir(exist_ok=True)
                (runtime / 'edlt-page-control-cli-report.json').write_text(json.dumps({'passed': True,
                    'group_boundaries_and_disabled': True, 'standby_disabled_allowed': True, 'preview_unchanged': True,
                    'saved_reloaded': True, 'adjacent_parameters_unchanged': True, 'database_destination_guard': True,
                    'network_opened': False, 'physical_device_verified': False}, indent=2) + '\n')
            finally:
                projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
