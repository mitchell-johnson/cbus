"""Enable Off/Preset CLI planning, shared labels and native persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


class EdltEnableCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        process = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, status, process.stdout + process.stderr)
        return json.loads(process.stdout or process.stderr)

    def test_offline_rejects_different_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wrong.json'
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.4.00', 'parameters': {}}))
            result = self.cli('edlt', 'enable-plan', path, '--page', 1, '--position', 1,
                              '--variable', 42, '--level', 173, status=1)
            self.assertIn('identity differs', result['error'])

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and unit specifications for Enable CLI acceptance')
    def test_preview_save_reload_cross_application_restore_and_dynamic_reference_guard(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'EV' + uuid4().hex[:6].upper()
        network = '//' + project + '/254'
        host, port = os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit',
                '--lock-address', network, '--source', '/db' + network + '/p/20')
        options = ('--page', 1, '--position', 1, '--variable', 42, '--level', 173,
                   '--label-text', 'Māori Mode', '--status-text', 'Māori Mode')
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                db.create_network(project, 254, 'Enable_CLI', 'Cni', '127.0.0.1:29999')
                db.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                projects.operation('save', project)
                original = self.cli(*args, 'show')
                snapshot = Path(folder) / 'before.json'
                self.cli(*args, 'export', snapshot)
                plan = self.cli('edlt', 'enable-plan', snapshot, *options)
                preview = self.cli(*args, '--dry-run', 'edlt-enable', *options)
                self.assertFalse(preview['saved'])
                self.assertTrue(preview['verified'])
                self.assertEqual(preview['changes'], plan['changes'])
                self.assertEqual(preview['record_hex'], plan['record_hex'])
                self.assertEqual(self.cli(*args, 'show'), original)
                record = bytes.fromhex(plan['record_hex'])
                self.assertEqual(record[:4], bytes((14, 0x35, 34, 33)))
                self.assertEqual(record[6:10], bytes((42, 10, 23, 173)))
                self.assertEqual(plan['static_allocation']['index'], plan['status_allocation']['index'])
                applied = self.cli(*args, 'edlt-enable', *options)
                self.assertTrue(applied['saved'])
                self.assertFalse(applied['physical_device_verified'])
                self.assertEqual(applied['parameters'], preview['parameters'])
                projects.operation('save', project)
                projects.operation('close', project)
                projects.operation('load', project)
                self.assertEqual(self.cli(*args, 'show'), applied['parameters'])
                self.cli(*args, 'edlt-enable', '--page', 1, '--position', 1, '--variable', 42,
                         '--level', 173, '--label-type', 'dynamic-text', '--label-index', 0)
                before_rejection = self.cli(*args, 'show')
                error = self.cli(*args, 'edlt-enable', '--page', 1, '--position', 1, '--variable', 43,
                                 '--level', 173, status=1)
                self.assertIn('explicit label_type', error['error'])
                self.assertEqual(self.cli(*args, 'show'), before_rejection)
                self.cli(*args, 'edlt-lighting', '--page', 1, '--position', 2, '--group', 43,
                         '--mode', 'off-on', '--restore-level', 88)
                restored = self.cli(*args, 'edlt-enable', '--page', 1, '--position', 1, '--variable', 43,
                                    '--level', 174, '--label-type', 'dynamic-icon', '--label-index', 1)
                self.assertEqual((restored['restore_level'], restored['restore_source_widget']), (88, 7))
                self.assertEqual(restored['application'], 203)
                self.assertEqual(self.cli(*args, 'show'), restored['parameters'])
                rejected = self.cli(*args, '--destination', network + '/p/20', 'edlt-enable', *options, status=1)
                self.assertIn('database destinations only', rejected['error'])
                self.assertEqual(self.cli(*args, 'show'), restored['parameters'])
            finally:
                projects.operation('close', project)
                projects.operation('delete', project)


if __name__ == '__main__':
    unittest.main()
