"""Timer CLI bounds, original-DLL byte vectors and native persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


class EdltTimerCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_rejects_different_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wrong.json'
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.4.00', 'parameters': {}}))
            result = self.cli('edlt', 'timer-plan', path, '--page', 1, '--position', 1, '--group', 42, status=1)
            self.assertIn('identity differs', result['error'])

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and unit specifications for Timer CLI acceptance')
    def test_defaults_timer_bounds_preview_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'TC' + uuid4().hex[:6].upper()
        network = '//' + project + '/254'
        host, port = os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit',
                '--lock-address', network, '--source', '/db' + network + '/p/20')
        location = ('--page', 1, '--position', 1, '--group', 42)
        options = (*location, '--duration-seconds', 300, '--target-level', 127,
                   '--expiry-level', 100, '--ramp-seconds', 20, '--label-text', 'Timer', '--status-text', 'Ready')
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                db.create_network(project, 254, 'Timer_CLI', 'Cni', '127.0.0.1:29999')
                db.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                projects.operation('save', project)
                original = self.cli(*args, 'show')
                self.assertEqual(bytes(int(v, 0) for v in original['StaticTextString2'].split()), b'Fan' + bytes(61))
                snapshot = Path(folder) / 'before.json'
                self.cli(*args, 'export', snapshot)
                default = self.cli('edlt', 'timer-plan', snapshot, *location)
                # Unchanged Toolkit DLL: SetToDefault, native existing Fan2, GroupAddress42.
                self.assertEqual(bytes.fromhex(default['record_hex'])[:19],
                                 bytes.fromhex('05340e0d00002a2322ff00003c0000000f0200'))
                self.assertEqual((default['duration_seconds'], default['target_level'],
                                  default['expiry_level'], default['ramp_seconds']), (60, 255, 0, 1020))
                plan = self.cli('edlt', 'timer-plan', snapshot, *options)
                preview = self.cli(*args, '--dry-run', 'edlt-timer', *options)
                self.assertFalse(preview['saved'])
                self.assertTrue(preview['verified'])
                self.assertEqual(preview['changes'], plan['changes'])
                self.assertEqual(preview['record_hex'], plan['record_hex'])
                self.assertEqual(self.cli(*args, 'show'), original)
                # Original existing-Fan custom vector, with primary-application bit clear.
                self.assertEqual(bytes.fromhex(plan['record_hex'])[:19],
                                 bytes.fromhex('05350e0d00002a23227f00002c016400043f3e'))
                self.assertEqual(plan['default_label_allocation']['index'], 2)
                self.assertTrue(plan['default_label_allocation']['reused'])
                self.assertEqual(plan['static_allocation']['index'], 63)
                self.assertEqual(plan['status_allocation']['index'], 62)
                applied = self.cli(*args, 'edlt-timer', *options)
                self.assertTrue(applied['saved'])
                self.assertFalse(applied['physical_device_verified'])
                self.assertEqual(applied['parameters'], preview['parameters'])
                projects.operation('save', project)
                projects.operation('close', project)
                projects.operation('load', project)
                self.assertEqual(self.cli(*args, 'show'), applied['parameters'])
                for index, text in ((63, b'Timer'), (62, b'Ready')):
                    raw = bytes(int(v, 0) for v in applied['parameters']['StaticTextString' + str(index)].split())
                    self.assertEqual(raw, text + bytes(64 - len(text)))
                maximum = self.cli(*args, 'edlt-timer', *location, '--duration-seconds', 64800,
                                   '--target-level', 1, '--expiry-level', 255, '--ramp-seconds', 0,
                                   '--status-type', 'timer')
                self.assertEqual(bytes.fromhex(maximum['record_hex'])[9:17], bytes.fromhex('01000020fdff0000'))
                zero = self.cli(*args, 'edlt-timer', *location, '--duration-seconds', 0,
                                '--target-level', 255, '--expiry-level', 0, '--ramp-seconds', 1020)
                self.assertEqual(bytes.fromhex(zero['record_hex'])[9:17], bytes.fromhex('ff0000000000000f'))
                for option, value in (('--duration-seconds', 64801), ('--target-level', 0), ('--ramp-seconds', 1)):
                    self.assertIn('error', self.cli(*args, 'edlt-timer', *location, option, value, status=1))
                self.assertEqual(self.cli(*args, 'show'), zero['parameters'])
                physical = self.cli(*args, '--destination', network + '/p/20', 'edlt-timer', *options, status=1)
                self.assertIn('database destinations only', physical['error'])
                self.assertEqual(self.cli(*args, 'show'), zero['parameters'])
            finally:
                projects.operation('close', project)
                projects.operation('delete', project)


if __name__ == '__main__':
    unittest.main()
