"""HVAC Temperature CLI: original defaults, placement and native persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


DEFAULT = '0DFF000000871200000000000000000000000000000000000000000000000000'
CUSTOM = '0D2A040201263F00000000000000000000000000000000000000000000000000'


class EdltHVACCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_wrong_profile_rejects_offline_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wrong.json'
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            result = self.cli('edlt', 'hvac-plan', path, '--page', 0, '--position', 1, '--group', 255, status=1)
            self.assertIn('identity differs', result['error'])

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and unit specifications for HVAC CLI acceptance')
    def test_original_defaults_units_icon_visibility_standby_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'HV' + uuid4().hex[:6].upper(); network = '//' + project + '/254'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit',
                '--lock-address', network, '--source', '/db' + network + '/p/20')
        location = ('--page', 1, '--position', 1)
        custom = (*location, '--group', 42, '--zone', 4, '--decimal-places', 2, '--units', 'fahrenheit',
                  '--icon-index', 38, '--label-text', 'Room')
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'HVAC_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                database.add(network, 'application', 172, 'HVAC')
                database.add(network + '/172', 'group', 42, 'HVAC_Communication')
                projects.operation('save', project)
                application_xml = database.get(network + '/172', xml=True).lines
                original = self.cli(*args, 'show'); path = Path(directory) / 'original.json'
                self.cli(*args, 'export', path)
                default = self.cli('edlt', 'hvac-plan', path, *location, '--group', 255)
                self.assertEqual(default['record_hex'].upper(), DEFAULT)
                self.assertEqual(default['label_index'], 18)
                self.assertTrue(default['allocations']['default_label']['reused'])
                plan = self.cli('edlt', 'hvac-plan', path, *custom)
                self.assertEqual(plan['record_hex'].upper(), CUSTOM)
                self.assertEqual((plan['application'], plan['group'], plan['zone'], plan['decimal_places'], plan['units']),
                                 (172, 42, 4, 2, 'fahrenheit'))
                preview = self.cli(*args, '--dry-run', 'edlt-hvac', *custom)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes'])
                self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-hvac', *custom)
                self.assertTrue(result['saved']); self.assertFalse(result['physical_device_verified'])
                self.assertFalse(result['database_group_created']); self.assertFalse(result['hvac_control_sent'])
                self.assertEqual(result['parameters'], preview['parameters'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                unchanged = self.cli(*args, 'edlt-hvac', *location, '--group', 42)
                self.assertEqual(unchanged['record_hex'].upper(), CUSTOM)
                for units, code in (('celsius', 0), ('fahrenheit', 1)):
                    result = self.cli(*args, 'edlt-hvac', *location, '--group', 42, '--units', units)
                    self.assertEqual(bytes.fromhex(result['record_hex'])[4], code)
                for icon in (0, 38, 135, 254):
                    result = self.cli(*args, 'edlt-hvac', *location, '--group', 42, '--icon-index', icon)
                    self.assertEqual(result['icon_index'], icon); self.assertTrue(result['icon_editable'])
                self.cli(*args, 'set', 'UseBigIcon', 0)
                result = self.cli(*args, 'edlt-hvac', *location, '--group', 42)
                self.assertEqual(result['icon_index'], 254); self.assertFalse(result['icon_editable'])
                rejected = self.cli(*args, 'edlt-hvac', *location, '--group', 42, '--icon-index', 38, status=1)
                self.assertIn('error', rejected); self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.cli(*args, 'set', 'UseBigIcon', 1)
                for position in (1, 5):
                    standby = self.cli(*args, 'edlt-hvac', '--page', 0, '--position', position,
                        '--group', 42, '--zone', 4, '--units', 'fahrenheit', '--decimal-places', 2, '--label-text', 'Room')
                    self.assertIsNone(standby['restore_level']); self.assertFalse(standby['icon_editable'])
                    self.assertEqual(standby['widget'], position)
                    self.assertEqual(bytes.fromhex(standby['record_hex'])[:7], bytes((13, 42, 4, 2, 1, 135, 63)))
                    self.assertIn('error', self.cli(*args, 'edlt-hvac', '--page', 0, '--position', position,
                        '--group', 42, '--icon-index', 38, status=1))
                # Group references alone never create or rename application metadata.
                result = self.cli(*args, 'edlt-hvac', *location, '--group', 43, '--label-text', '')
                self.assertEqual(result['label_index'], 255)
                self.assertEqual(database.get(network + '/172', xml=True).lines, application_xml)
                self.assertFalse(result['database_group_created'])
                for invalid in (('--zone', 5), ('--decimal-places', 3), ('--icon-index', 39), ('--icon-index', 255),
                                ('--label-index', 64), ('--label-text', 'X', '--label-index', 1)):
                    self.assertIn('error', self.cli(*args, 'edlt-hvac', *location, '--group', 43, *invalid, status=1))
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                rejected = self.cli(*args, '--destination', network + '/p/20', 'edlt-hvac', *location, '--group', 42, status=1)
                self.assertIn('database destinations only', rejected['error'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
            finally:
                projects.operation('close', project); projects.operation('delete', project)
