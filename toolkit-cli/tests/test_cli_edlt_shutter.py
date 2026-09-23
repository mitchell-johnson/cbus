"""Shutter CLI defaults, preset modes, offline previews and native persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


class EdltShutterCLITests(unittest.TestCase):
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
            result = self.cli('edlt', 'shutter-plan', path, '--page', 1, '--position', 1, '--group', 42, status=1)
            self.assertIn('identity differs', result['error'])

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and unit specifications for Shutter CLI acceptance')
    def test_default_label_allocation_presets_preview_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'SC' + uuid4().hex[:6].upper()
        network = '//' + project + '/254'
        host, port = os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit',
                '--lock-address', network, '--source', '/db' + network + '/p/20')
        options = ('--page', 1, '--position', 1, '--group', 42, '--mode', 'two-key-presets',
                   '--preset-left', 6, '--preset-right', 248, '--label-text', 'Shade', '--status-text', 'Ready')
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                db.create_network(project, 254, 'Shutter_CLI', 'Cni', '127.0.0.1:29999')
                db.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                projects.operation('save', project)
                original = self.cli(*args, 'show')
                self.assertEqual(bytes(int(v, 0) for v in original['StaticTextString5'].split()), b'Blind' + bytes(59))
                snapshot = Path(folder) / 'before.json'
                self.cli(*args, 'export', snapshot)
                plan = self.cli('edlt', 'shutter-plan', snapshot, *options)
                preview = self.cli(*args, '--dry-run', 'edlt-shutter', *options)
                self.assertFalse(preview['saved'])
                self.assertTrue(preview['verified'])
                self.assertEqual(preview['changes'], plan['changes'])
                self.assertEqual(preview['record_hex'], plan['record_hex'])
                self.assertEqual(self.cli(*args, 'show'), original)
                record = bytes.fromhex(plan['record_hex'])
                self.assertEqual(record[:4], bytes((3, 0x35, 18, 17)))
                self.assertEqual(record[6:12], bytes((42, 1, 6, 248, 63, 62)))
                self.assertEqual(plan['default_label_allocation']['index'], 5)
                self.assertTrue(plan['default_label_allocation']['reused'])
                self.assertEqual(plan['static_allocation']['index'], 63)
                self.assertEqual(plan['status_allocation']['index'], 62)
                applied = self.cli(*args, 'edlt-shutter', *options)
                self.assertTrue(applied['saved'])
                self.assertFalse(applied['physical_device_verified'])
                self.assertEqual(applied['parameters'], preview['parameters'])
                projects.operation('save', project)
                projects.operation('close', project)
                projects.operation('load', project)
                self.assertEqual(self.cli(*args, 'show'), applied['parameters'])
                for index, text in ((63, b'Shade'), (62, b'Ready')):
                    raw = bytes(int(v, 0) for v in applied['parameters']['StaticTextString' + str(index)].split())
                    self.assertEqual(raw, text + bytes(64 - len(text)))
                plain = self.cli(*args, 'edlt-shutter', '--page', 1, '--position', 1, '--group', 42,
                                 '--mode', 'two-key', '--status-type', 'percent')
                self.assertEqual(bytes.fromhex(plain['record_hex'])[7:10], bytes((0, 6, 248)))
                self.assertIsNone(plain['default_label_allocation'])
                error = self.cli(*args, 'edlt-shutter', '--page', 1, '--position', 1, '--group', 42,
                                 '--mode', 'two-key-presets', '--preset-left', 5, status=1)
                self.assertIn('error', error)
                self.assertEqual(self.cli(*args, 'show'), plain['parameters'])
                physical = self.cli(*args, '--destination', network + '/p/20', 'edlt-shutter', *options, status=1)
                self.assertIn('database destinations only', physical['error'])
                self.assertEqual(self.cli(*args, 'show'), plain['parameters'])
            finally:
                projects.operation('close', project)
                projects.operation('delete', project)


if __name__ == '__main__':
    unittest.main()
