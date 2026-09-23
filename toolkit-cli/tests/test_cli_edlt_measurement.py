"""Measurement CLI acceptance against original records and native persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


DEFAULT = '0C000002010000000000FFFF8740000000000000000000000000000000000000'
SCALED = '0C2A03017D00FEFFE7FFFFFF8740000000000000000000000000000000000000'
CUSTOM = '0C2A03017D00FEFFE7FF123F873E000000000000000000000000000000000000'


class EdltMeasurementCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        process = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, status, process.stdout + process.stderr)
        return json.loads(process.stdout or process.stderr)

    def test_wrong_profile_rejects_offline_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wrong.json'
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            result = self.cli('edlt', 'measurement-plan', path, '--page', 1, '--position', 1,
                              '--device-id', 0, '--channel', 0, status=1)
            self.assertIn('identity differs', result['error'])

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and unit specifications for Measurement icon CLI acceptance')
    def test_original_icon_option_preview_hidden_guards_and_opaque_retention(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'MIC' + uuid4().hex[:5].upper(); network = '//' + project + '/254'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit',
                '--lock-address', network, '--source', '/db' + network + '/p/20')
        settings = ('--page', 1, '--position', 1, '--device-id', 42, '--channel', 3,
                    '--decimal-places', 1, '--gain-mantissa', 125, '--gain-exponent', -2,
                    '--offset-mantissa', -25, '--offset-exponent', -1,
                    '--prefix-text', 'Temperature', '--suffix-text', 'C', '--label-index', 64)
        custom_icon = '0C2A03017D00FEFFE7FF123F2640000000000000000000000000000000000000'
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Measurement_Icon_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL'); projects.operation('save', project)
                original = self.cli(*args, 'show'); path = Path(directory) / 'values.json'; self.cli(*args, 'export', path)
                plan = self.cli('edlt', 'measurement-plan', path, *settings, '--icon-index', 38)
                self.assertEqual(plan['record_hex'].upper(), custom_icon)
                preview = self.cli(*args, '--dry-run', 'edlt-measurement', *settings, '--icon-index', 38)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes']); self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-measurement', *settings, '--icon-index', 38)
                self.assertTrue(result['saved']); self.assertEqual(result['record_hex'].upper(), custom_icon)
                for icon in (0, 254):
                    result = self.cli(*args, 'edlt-measurement', *settings, '--icon-index', icon)
                    self.assertEqual(result['icon_index'], icon); self.assertTrue(result['icon_editable'])
                    self.assertEqual(bytes.fromhex(result['record_hex'])[12], icon)
                for invalid in (39, 255, -1, 256):
                    self.assertIn('error', self.cli(*args, 'edlt-measurement', *settings, '--icon-index', invalid, status=1))
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.cli(*args, 'set', 'UseBigIcon', 0)
                for raw in (39, 255):
                    self.cli(*args, 'set', 'Widget6WidgetByteValue12', raw)
                    result = self.cli(*args, 'edlt-measurement', *settings)
                    self.assertEqual(result['icon_index'], raw); self.assertFalse(result['icon_editable'])
                    rejected = self.cli(*args, 'edlt-measurement', *settings, '--icon-index', 135, status=1)
                    self.assertIn('UseBigIcon', rejected['error']); self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.cli(*args, 'set', 'UseBigIcon', 1)
                for position, raw in ((1, 39), (5, 255)):
                    standby = ('--page', 0, '--position', position, '--device-id', 0, '--channel', 0)
                    self.cli(*args, 'edlt-measurement', *standby)
                    self.cli(*args, 'set', f'Widget{position}WidgetByteValue12', raw)
                    result = self.cli(*args, 'edlt-measurement', *standby)
                    self.assertEqual(result['icon_index'], raw); self.assertFalse(result['icon_editable'])
                    rejected = self.cli(*args, 'edlt-measurement', *standby, '--icon-index', 135, status=1)
                    self.assertIn('functional', rejected['error']); self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
            finally:
                projects.operation('close', project); projects.operation('delete', project)

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and unit specifications for Measurement CLI acceptance')
    def test_original_scaling_text_sentinels_preview_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'ME' + uuid4().hex[:6].upper()
        network = '//' + project + '/254'
        host = os.environ['CBUS_CGATE_TEST_HOST']
        port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20,
                'unit', '--lock-address', network, '--source', '/db' + network + '/p/20')
        location = ('--page', 1, '--position', 1)
        identity = ('--device-id', 42, '--channel', 3)
        scaled = (*location, *identity, '--decimal-places', 1, '--gain-mantissa', 125,
                  '--gain-exponent', -2, '--offset-mantissa', -25, '--offset-exponent', -1)
        custom = (*scaled, '--prefix-text', 'Temperature', '--suffix-text', 'C', '--label-text', 'Room')
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Measurement_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                projects.operation('save', project)
                original = self.cli(*args, 'show')
                path = Path(directory) / 'original.json'
                self.cli(*args, 'export', path)
                default = self.cli('edlt', 'measurement-plan', path, *location, '--device-id', 0, '--channel', 0)
                self.assertEqual(default['record_hex'].upper(), DEFAULT)
                self.assertEqual(default['text_indices'], {'prefix': 255, 'suffix': 255, 'label': 64})
                self.assertEqual(default['allocations'], {'prefix': None, 'suffix': None, 'label': None})
                scale_plan = self.cli('edlt', 'measurement-plan', path, *scaled)
                self.assertEqual(scale_plan['record_hex'].upper(), SCALED)
                self.assertEqual((scale_plan['gain_value'], scale_plan['offset_value']), ('1.25', '-2.5'))
                self.assertFalse(scale_plan['ui_composite_conversion'])
                plan = self.cli('edlt', 'measurement-plan', path, *custom)
                self.assertEqual(plan['record_hex'].upper(), CUSTOM)
                self.assertEqual(plan['text_indices'], {'prefix': 18, 'suffix': 63, 'label': 62})
                preview = self.cli(*args, '--dry-run', 'edlt-measurement', *custom)
                self.assertTrue(preview['verified'])
                self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes'])
                self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-measurement', *custom)
                self.assertTrue(result['saved'])
                self.assertFalse(result['physical_device_verified'])
                self.assertEqual(result['record_hex'].upper(), CUSTOM)
                self.assertEqual(result['parameters'], preview['parameters'])
                for action in ('save', 'close', 'load'):
                    projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                unchanged = self.cli(*args, 'edlt-measurement', *location, *identity)
                self.assertEqual(unchanged['record_hex'].upper(), CUSTOM)
                for sentinel in (64, 255):
                    result = self.cli(*args, 'edlt-measurement', *location, *identity, '--label-index', sentinel)
                    self.assertEqual(result['text_indices']['label'], sentinel)
                    self.assertEqual(result['gain_value'], '1.25')
                    for action in ('save', 'close', 'load'):
                        projects.operation(action, project)
                    self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                result = self.cli(*args, 'edlt-measurement', *location, *identity,
                                  '--prefix-text', '', '--suffix-text', '', '--label-text', '')
                self.assertEqual(result['text_indices'], {'prefix': 255, 'suffix': 255, 'label': 255})
                result = self.cli(*args, 'edlt-measurement', *location, *identity,
                                  '--prefix-index', 18, '--suffix-index', 63, '--label-index', 62)
                self.assertEqual(result['record_hex'].upper(), CUSTOM)
                for invalid in (('--device-id', 255), ('--channel', 255), ('--decimal-places', 6),
                                ('--gain-mantissa', 0), ('--gain-mantissa', -32769), ('--gain-exponent', 128),
                                ('--offset-mantissa', 32768), ('--offset-exponent', -129),
                                ('--prefix-index', 64), ('--suffix-index', 64), ('--label-index', 65),
                                ('--prefix-text', 'X', '--prefix-index', 1), ('--page', -1)):
                    rejected = self.cli(*args, 'edlt-measurement', *location, *identity, *invalid, status=1)
                    self.assertIn('error', rejected)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                rejected = self.cli(*args, '--destination', network + '/p/20',
                                    'edlt-measurement', *location, *identity, status=1)
                self.assertIn('database destinations only', rejected['error'])
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                # Original type12 is also offered on all five standby slots.
                functional = result['parameters']
                standby_path = Path(directory) / 'standby-source.json'
                self.cli(*args, 'export', standby_path)
                standby_args = ('--page', 0, '--position', 1, '--device-id', 0, '--channel', 0)
                plan = self.cli('edlt', 'measurement-plan', standby_path, *standby_args)
                self.assertEqual(plan['record_hex'].upper(), DEFAULT)
                self.assertIsNone(plan['restore_level'])
                preview = self.cli(*args, '--dry-run', 'edlt-measurement', *standby_args)
                self.assertFalse(preview['saved']); self.assertTrue(preview['verified'])
                self.assertEqual(self.cli(*args, 'show'), functional)
                result = self.cli(*args, 'edlt-measurement', *standby_args)
                self.assertTrue(result['saved']); self.assertIsNone(result['restore_level'])
                result = self.cli(*args, 'edlt-measurement', '--page', 0, '--position', 5, *identity,
                                  '--decimal-places', 1, '--gain-mantissa', 125, '--gain-exponent', -2,
                                  '--offset-mantissa', -25, '--offset-exponent', -1,
                                  '--prefix-text', 'Temperature', '--suffix-text', 'C', '--label-index', 64)
                self.assertEqual(result['record_hex'].upper(),
                                 '0C2A03017D00FEFFE7FF123F8740000000000000000000000000000000000000')
                self.assertIsNone(result['restore_level'])
                self.assertFalse(any(f'Widget{n}RestoreLevel' in result['parameters'] for n in range(1, 6)))
                self.assertEqual({k: v for k, v in result['parameters'].items() if k.startswith('Widget6')},
                                 {k: v for k, v in functional.items() if k.startswith('Widget6')})
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                double = self.cli(*args, 'edlt-time-date', '--page', 0, '--position', 1, '--slices', 2, '--display', 'time-date')
                rejected = self.cli(*args, 'edlt-measurement', '--page', 0, '--position', 2, *identity, status=1)
                self.assertIn('covered', rejected['error'])
                rejected = self.cli(*args, 'edlt-measurement', '--page', 0, '--position', 1, *identity, status=1)
                self.assertIn('another type', rejected['error'])
                self.assertEqual(self.cli(*args, 'show'), double['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
            finally:
                projects.operation('close', project)
                projects.operation('delete', project)


if __name__ == '__main__':
    unittest.main()
