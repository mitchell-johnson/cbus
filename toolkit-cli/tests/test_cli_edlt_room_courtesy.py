"""Room Courtesy CLI: original literal records and native database persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


DEFAULT = '0F00848400002A19000000000000000000000000000000000000000000000000'
CUSTOM = '0FB5848400002AFF3F3E02030000000000000000000000000000000000000000'
COLOURS = ('none', 'white', 'red', 'green', 'blue', 'cyan', 'magenta', 'yellow', 'orange')


class EdltRoomCourtesyCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_wrong_profile_rejects_offline_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wrong.json'
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.4.00', 'parameters': {}}))
            result = self.cli('edlt', 'room-courtesy-plan', path, '--page', 1,
                              '--position', 1, '--group', 42, status=1)
            self.assertIn('identity differs', result['error'])

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and unit specifications for Room Courtesy CLI acceptance')
    def test_original_modes_colours_preview_and_full_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'RC' + uuid4().hex[:6].upper()
        network = '//' + project + '/254'
        host = os.environ['CBUS_CGATE_TEST_HOST']
        port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20,
                'unit', '--lock-address', network, '--source', '/db' + network + '/p/20')
        location = ('--page', 1, '--position', 1, '--group', 42)
        custom = (*location, '--application', 'secondary', '--mode', 'unused',
                  '--off-colour', 'red', '--on-colour', 'green',
                  '--label-text', 'Courtesy', '--status-text', 'Available')
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Room_Courtesy_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                self.cli(*args, 'set', 'SecondaryApplication', 57)
                original = self.cli(*args, 'show')
                snapshot = Path(folder) / 'original.json'
                self.cli(*args, 'export', snapshot)
                default = self.cli('edlt', 'room-courtesy-plan', snapshot, *location)
                self.assertEqual(default['record_hex'].upper(), DEFAULT)
                self.assertEqual((default['mode'], default['off_colour'], default['on_colour']),
                                 ('bell-press', 'none', 'none'))
                self.assertIsNone(default['static_allocation'])
                self.assertIsNone(default['status_allocation'])
                plan = self.cli('edlt', 'room-courtesy-plan', snapshot, *custom)
                self.assertEqual(plan['record_hex'].upper(), CUSTOM)
                self.assertEqual((plan['static_allocation']['index'], plan['status_allocation']['index']), (63, 62))
                preview = self.cli(*args, '--dry-run', 'edlt-room-courtesy', *custom)
                self.assertFalse(preview['saved'])
                self.assertTrue(preview['verified'])
                self.assertEqual(preview['changes'], plan['changes'])
                self.assertEqual(self.cli(*args, 'show'), original)
                applied = self.cli(*args, 'edlt-room-courtesy', *custom)
                self.assertTrue(applied['saved'])
                self.assertFalse(applied['physical_device_verified'])
                self.assertEqual(applied['record_hex'].upper(), CUSTOM)
                self.assertEqual(applied['parameters'], preview['parameters'])
                for action in ('save', 'close', 'load'):
                    projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), applied['parameters'])
                for mode, code in (('bell-press', 25), ('unused', 255)):
                    value = self.cli(*args, 'edlt-room-courtesy', *location,
                                     '--application', 'secondary', '--mode', mode)
                    record = bytes.fromhex(value['record_hex'])
                    self.assertEqual(record[7], code)
                    self.assertEqual(record[8:12], bytes((63, 62, 2, 3)))
                dynamic_cases = (
                    ('dynamic-icon', 1, 'dynamic-icon', 3,
                     '0FA7848400002A19010302030000000000000000000000000000000000000000'),
                    ('dynamic-text', 2, 'dynamic-text', 0,
                     '0F96848400002A19020002030000000000000000000000000000000000000000'),
                    ('dynamic-icon', 2, 'dynamic-icon', 0,
                     '0FA7848400002A19020002030000000000000000000000000000000000000000'),
                )
                for label_type, label_index, status_type, status_index, literal in dynamic_cases:
                    value = self.cli(*args, 'edlt-room-courtesy', *location,
                        '--application', 'secondary', '--mode', 'bell-press',
                        '--label-type', label_type, '--label-index', label_index,
                        '--status-type', status_type, '--status-index', status_index)
                    self.assertEqual(value['record_hex'].upper(), literal)
                for flag, index in (('--label-index', 2), ('--status-index', 0)):
                    result = self.cli(*args, 'edlt-room-courtesy', *location,
                                     '--application', 'secondary', flag, index, status=1)
                    self.assertIn('explicit', result['error'])
                self.assertEqual(self.cli(*args, 'show'), value['parameters'])
                self.cli(*args, 'edlt-room-courtesy', *custom)
                for code, colour in enumerate(COLOURS):
                    value = self.cli(*args, 'edlt-room-courtesy', *location,
                                     '--application', 'secondary', '--off-colour', colour, '--on-colour', colour)
                    self.assertEqual(value['off_colour'], colour)
                    self.assertEqual(value['on_colour'], colour)
                    self.assertEqual(bytes.fromhex(value['record_hex'])[8:12], bytes((63, 62, code, code)))
                for application in (127, 136):
                    self.cli(*args, 'set', 'SecondaryApplication', application)
                    value = self.cli(*args, 'edlt-room-courtesy', *location, '--application', 'secondary')
                    self.assertEqual(value['application'], application)
                    self.assertEqual(self.cli(*args, 'show'), value['parameters'])
                for invalid in (('--group', 255), ('--label-index', 64), ('--status-index', 64),
                                ('--label-text', 'X', '--label-index', 1),
                                ('--status-text', 'X', '--status-index', 1)):
                    result = self.cli(*args, 'edlt-room-courtesy', *location, *invalid, status=1)
                    self.assertIn('error', result)
                self.assertEqual(self.cli(*args, 'show'), value['parameters'])
                result = self.cli(*args, '--destination', network + '/p/20',
                                  'edlt-room-courtesy', *location, status=1)
                self.assertIn('database destinations only', result['error'])
                self.assertEqual(self.cli(*args, 'show'), value['parameters'])
                for action in ('save', 'close', 'load'):
                    projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), value['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
            finally:
                projects.operation('close', project)
                projects.operation('delete', project)


if __name__ == '__main__':
    unittest.main()
