"""Fan CLI compared with original DLL vectors and native database persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


class EdltFanCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        process = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, status, process.stdout + process.stderr)
        return json.loads(process.stdout or process.stderr)

    def test_wrong_profile_and_mutually_exclusive_status_options(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wrong.json'
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.4.00', 'parameters': {}}))
            result = self.cli('edlt', 'fan-plan', path, '--page', 1, '--position', 1, '--group', 42, status=1)
            self.assertIn('identity differs', result['error'])
            process = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'edlt', 'fan-plan', str(path),
                '--page', '1', '--position', '1', '--group', '42', '--off-text', 'Stopped', '--off-index', '4'],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 2)
            self.assertIn('not allowed with argument', process.stderr)

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and unit specifications for Fan CLI acceptance')
    def test_original_vectors_all_speeds_status_slots_preview_and_save(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'FC' + uuid4().hex[:6].upper()
        network = '//' + project + '/254'
        host, port = os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit',
                '--lock-address', network, '--source', '/db' + network + '/p/20')
        location = ('--page', 1, '--position', 1, '--group', 42)
        custom = (*location, '--application', 'secondary', '--speeds', 3,
                  '--low-threshold', 253, '--high-threshold', 254, '--label-text', 'Ceiling',
                  '--off-text', 'Stopped', '--low-text', 'Slow', '--medium-text', 'Normal', '--high-text', 'Fast')
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Fan_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                self.cli(*args, 'set', 'SecondaryApplication', 57)
                projects.operation('save', project)
                original = self.cli(*args, 'show')
                path = Path(folder) / 'before.json'
                self.cli(*args, 'export', path)
                default = self.cli('edlt', 'fan-plan', path, *location)
                self.assertEqual(default['record_hex'].upper(),
                    '0435040300002A54AA020C0D0E0F000000000000000000000000000000000000')
                self.assertEqual([row['index'] for row in default['default_allocations']], [12,13,14,15,2,12,13,14,15])
                self.assertTrue(all(row['reused'] for row in default['default_allocations']))
                plan = self.cli('edlt', 'fan-plan', path, *custom)
                self.assertEqual(plan['record_hex'].upper(),
                    '04B5040300002AFDFE3F3E3D3C3B000000000000000000000000000000000000')
                preview = self.cli(*args, '--dry-run', 'edlt-fan', *custom)
                self.assertTrue(preview['verified'])
                self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes'])
                self.assertEqual(preview['record_hex'], plan['record_hex'])
                self.assertEqual(self.cli(*args, 'show'), original)
                applied = self.cli(*args, 'edlt-fan', *custom)
                self.assertTrue(applied['saved'])
                self.assertFalse(applied['physical_device_verified'])
                self.assertEqual(applied['parameters'], preview['parameters'])
                projects.operation('save', project)
                projects.operation('close', project)
                projects.operation('load', project)
                self.assertEqual(self.cli(*args, 'show'), applied['parameters'])
                for index, text in ((63,b'Ceiling'),(62,b'Stopped'),(61,b'Slow'),(60,b'Normal'),(59,b'Fast')):
                    raw = bytes(int(v, 0) for v in applied['parameters'][f'StaticTextString{index}'].split())
                    self.assertEqual(raw, text.ljust(64, b'\0'))
                for speed, thresholds in ((1, b'\0\0'), (2, b'\x7f\x7f'), (3, b'\x54\xaa')):
                    result = self.cli(*args, 'edlt-fan', *location, '--application', 'secondary', '--speeds', speed)
                    self.assertEqual(bytes.fromhex(result['record_hex'])[7:9], thresholds)
                    self.assertEqual(bytes.fromhex(result['record_hex'])[10:14], bytes((62,61,60,59)))
                explicit = self.cli(*args, 'edlt-fan', *location, '--application', 'secondary',
                    '--off-index', 0, '--low-index', 63, '--medium-index', 0, '--high-index', 63)
                self.assertEqual(bytes.fromhex(explicit['record_hex'])[10:14], bytes((0,63,0,63)))
                for invalid in (('--low-threshold',0), ('--low-threshold',170), ('--high-threshold',84),
                                ('--medium-index',64), ('--speeds',1,'--low-text','Hidden')):
                    self.assertIn('error', self.cli(*args, 'edlt-fan', *location, *invalid, status=1))
                self.assertEqual(self.cli(*args, 'show'), explicit['parameters'])
                physical = self.cli(*args, '--destination', network + '/p/20', 'edlt-fan', *custom, status=1)
                self.assertIn('database destinations only', physical['error'])
                self.assertEqual(self.cli(*args, 'show'), explicit['parameters'])
            finally:
                projects.operation('close', project)
                projects.operation('delete', project)


if __name__ == '__main__':
    unittest.main()
