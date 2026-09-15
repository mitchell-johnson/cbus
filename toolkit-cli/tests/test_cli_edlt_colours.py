"""Colour CLI option routing, fixed/group guards and native persistence."""
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
from cbus_toolkit.edlt_colours import EdltColours
from tests.test_edlt import Session
from tests.test_edlt_colours import fixture


CUSTOM = ('--text-colour', 'yellow', '--background-colour', 'blue', '--indicator-on-colour', 'orange',
          '--indicator-off-colour', 'cyan', '--page-key-colour', 'red', '--active-screen-brightness', 254,
          '--idle-screen-brightness', 1, '--active-indicator-brightness', 0, '--idle-indicator-brightness', 255)
FIXED_FIELDS = ('LCDForeground', 'LCDBackground', 'IndicatorOnColour', 'IndicatorOffColour',
                'NavigationIndicatorColour', 'ActiveBacklightBrightness', 'IdleBacklightBrightness',
                'ActiveIndicatorBrightness', 'IdleIndicatorBrightness')
GROUPS = ('active-screen-group', 'idle-screen-group', 'active-indicator-group', 'idle-indicator-group',
          'indicator-on-group', 'indicator-off-group')
GROUP_FIELDS = ('BacklightActiveBrightnessControlGroup', 'BacklightIdleBrightnessControlGroup',
                'IndicatorActiveBrightnessControlGroup', 'IndicatorIdleBrightnessControlGroup',
                'IndicatorOnColourControlGroup', 'IndicatorOffColourControlGroup')


class ColourCLITests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): code = cli.main(list(map(str, args)))
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_all_options_fixed_group_conflict_and_export_identity_without_io(self):
        spec = fixture(); session = Session(spec); editor = EdltColours(spec)
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, '_edlt_colours', return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            path = Path(directory) / 'values.json'; path.write_text(json.dumps(session.values()))
            result = self.invoke(('edlt', 'colours-plan', path, *CUSTOM))
            self.assertEqual([result['raw_values'][name] for name in ('text_colour', 'background_colour', 'indicator_on_colour',
                'indicator_off_colour', 'page_key_colour', 'active_screen_brightness', 'idle_screen_brightness',
                'active_indicator_brightness', 'idle_indicator_brightness')], [7, 4, 8, 5, 2, 254, 1, 0, 255])
            options = tuple(item for index, name in enumerate(GROUPS) for item in ('--' + name, index))
            groups = self.invoke(('edlt', 'colours-plan', path, *options))
            self.assertEqual([groups[name.replace('-', '_')] for name in GROUPS], list(range(6)))
            self.assertFalse(groups['database_group_created']); self.assertFalse(groups['group_metadata_verified'])
            self.assertIn('fixed mode', self.invoke(('edlt', 'colours-plan', path, '--active-screen-group', 42,
                '--active-screen-brightness', 100), status=1)['error'])
            path.write_text(json.dumps({**session.values(), 'ActivityDuration': '0'}))
            self.assertIn('Standby', self.invoke(('edlt', 'colours-plan', path, '--idle-screen-group', 255), status=1)['error'])
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            self.assertIn('identity differs', self.invoke(('edlt', 'colours-plan', path), status=1)['error'])

    def test_interrupt_retains_attempt_without_save_or_recovery(self):
        spec = fixture(); session = Session(spec); editor = EdltColours(spec); calls = []
        def fail(name, value):
            calls.append(name); session.current[name] = value; session.connected = False
            raise KeyboardInterrupt('colour SET interrupted')
        session.set = fail; session.save_to_source = Mock(side_effect=AssertionError('No save after interrupt'))
        loader = Mock(return_value=nullcontext(session))
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=loader)), \
                patch.object(cli, '_edlt_colours', return_value=editor):
            result = self.invoke(('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                                  'edlt-colours', '--text-colour', 'yellow'), status=130)
        evidence = result['edlt_colours_evidence']; self.assertEqual(len(calls), 1)
        self.assertEqual(evidence['attempted_parameters'], calls); self.assertTrue(evidence['pp_state_uncertain'])
        self.assertFalse(evidence['saved']); self.assertFalse(evidence['verified']); self.assertEqual(evidence['automatic_retries'], 0)
        session.save_to_source.assert_not_called()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and specifications for colour CLI acceptance')
    def test_native_preview_fixed_group_transitions_preservation_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'CC' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit', '--lock-address', network, '--source', source)
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Colour_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL'); projects.operation('save', project)
                original = self.cli(*args, 'show'); path = Path(directory) / 'original.json'; self.cli(*args, 'export', path)
                plan = self.cli('edlt', 'colours-plan', path, *CUSTOM)
                preview = self.cli(*args, '--dry-run', 'edlt-colours', *CUSTOM)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes']); self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-colours', *CUSTOM)
                self.assertTrue(result['saved']); self.assertEqual(result['parameters'], preview['parameters'])
                self.assertEqual([int(result['parameters'][name], 0) for name in FIXED_FIELDS], [7, 4, 8, 5, 2, 254, 1, 0, 255])
                fixed = result['parameters']
                options = tuple(item for index, name in enumerate(GROUPS) for item in ('--' + name, index))
                result = self.cli(*args, 'edlt-colours', *options)
                self.assertEqual([int(result['parameters'][name], 0) for name in GROUP_FIELDS], list(range(6)))
                self.assertEqual([result['parameters'][name] for name in FIXED_FIELDS], [fixed[name] for name in FIXED_FIELDS])
                self.assertIn('fixed mode', self.cli(*args, 'edlt-colours', '--indicator-on-colour', 'red', status=1)['error'])
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                options = tuple(item for name in GROUPS for item in ('--' + name, 255))
                result = self.cli(*args, 'edlt-colours', *options, *CUSTOM)
                self.assertEqual(result['parameters'], fixed)
                result = self.cli(*args, 'edlt-standby', '--no-enabled')
                hidden = result['parameters']; result = self.cli(*args, 'edlt-colours', '--text-colour', 'white')
                self.assertFalse(result['idle_controls_enabled'])
                self.assertEqual(result['parameters']['IdleBacklightBrightness'], hidden['IdleBacklightBrightness'])
                self.assertIn('Standby', self.cli(*args, 'edlt-colours', '--idle-screen-brightness', 5, status=1)['error'])
                self.assertIn('database destinations only', self.cli(*args, '--destination', network + '/p/20',
                    'edlt-colours', '--text-colour', 'red', status=1)['error'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                runtime = Path(__file__).resolve().parents[1] / 'research/runtime'; runtime.mkdir(exist_ok=True)
                (runtime / 'edlt-colours-cli-report.json').write_text(json.dumps({'passed': True,
                    'all_fifteen_options_exercised': True, 'preview_unchanged': True, 'saved_reloaded': True,
                    'group_values_preserve_hidden_fixed_values': True, 'idle_guard': True, 'database_destination_guard': True,
                    'network_opened': False, 'physical_device_verified': False}, indent=2) + '\n')
            finally:
                projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
