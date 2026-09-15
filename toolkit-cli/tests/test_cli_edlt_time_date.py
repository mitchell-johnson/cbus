"""Time/Date CLI: original slice semantics and native database persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


DOUBLE_TIME_DATE = '0B02000000000000000000000000000000000000000000000000000000000000'


class EdltTimeDateCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_wrong_profile_rejects_offline_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wrong.json'
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
                'firmware': '5.4.00', 'catalog_number': '5055EDL', 'parameters': {}}))
            result = self.cli('edlt', 'time-date-plan', path, '--page', 0, '--position', 1, status=1)
            self.assertIn('identity differs', result['error'])

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and unit specifications for Time/Date CLI acceptance')
    def test_standby_slices_globals_functional_restore_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'TD' + uuid4().hex[:6].upper()
        network = '//' + project + '/254'
        host = os.environ['CBUS_CGATE_TEST_HOST']
        port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20,
                'unit', '--lock-address', network, '--source', '/db' + network + '/p/20')
        options = ('--page', 0, '--position', 1, '--slices', 2, '--display', 'time-date',
                   '--date-format', 7, '--time-format', '12-hour-uppercase', '--leading-zero')
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Time_Date_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                projects.operation('save', project)
                self.cli(*args, 'edlt-time-date', '--page', 0, '--position', 2, '--display', 'date')
                for name, value in (('Widget2WidgetByteValue31', 99), ('Widget6WidgetType', 0),
                                    ('Widget6RestoreLevel', 106), ('Widget7RestoreLevel', 107)):
                    self.cli(*args, 'set', name, value)
                original = self.cli(*args, 'show')
                path = Path(directory) / 'original.json'
                self.cli(*args, 'export', path)
                plan = self.cli('edlt', 'time-date-plan', path, *options)
                self.assertEqual(plan['record_hex'].upper(), DOUBLE_TIME_DATE)
                self.assertEqual(plan['widget'], 1)
                self.assertEqual(plan['adjacent_widget'], 2)
                before, after = bytes.fromhex(plan['adjacent_before_hex']), bytes.fromhex(plan['adjacent_after_hex'])
                self.assertEqual((before[0], after[0], before[1], after[31]), (10, 0, 1, 99))
                self.assertEqual(before[1:], after[1:])
                self.assertEqual(plan['restore_reset_widgets'], [6])
                self.assertEqual(plan['changes']['Widget6RestoreLevel'], [0])
                self.assertNotIn('Widget7RestoreLevel', plan['changes'])
                self.assertTrue(plan['global_formats_apply_to_whole_unit'])
                self.assertFalse(plan['clock_set'])
                preview = self.cli(*args, '--dry-run', 'edlt-time-date', *options)
                self.assertTrue(preview['verified'])
                self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes'])
                self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-time-date', *options)
                self.assertTrue(result['saved'])
                self.assertFalse(result['physical_device_verified'])
                self.assertEqual(result['parameters'], preview['parameters'])
                for action in ('save', 'close', 'load'):
                    projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                rejected = self.cli(*args, 'edlt-time-date', '--page', 0, '--position', 2, status=1)
                self.assertIn('covered', rejected['error'])
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                # A repeated two-slice assignment preserves an already configured
                # hidden neighbor, exactly as the original property setter does.
                self.cli(*args, 'set', 'Widget2WidgetType', 10)
                result = self.cli(*args, 'edlt-time-date', *options)
                self.assertIsNone(result['adjacent_widget'])
                self.assertEqual(int(result['parameters']['Widget2WidgetType'], 0), 10)
                self.assertEqual(int(result['parameters']['Widget2WidgetByteValue31'], 0), 99)
                result = self.cli(*args, 'edlt-time-date', '--page', 0, '--position', 1, '--slices', 1)
                self.assertEqual(bytes.fromhex(result['record_hex'])[:2], b'\x0a\x02')
                self.assertIsNone(result['adjacent_widget'])
                self.assertEqual(int(result['parameters']['Widget2WidgetType'], 0), 10)
                self.cli(*args, 'edlt-time-date', '--page', 0, '--position', 2, '--display', 'time')
                self.cli(*args, 'set', 'Widget21RestoreLevel', 155)
                functional = ('--page-mode', 'multiple', '--page', 4, '--position', 4)
                result = self.cli(*args, 'edlt-time-date', *functional, '--display', 'time-date')
                self.assertEqual(result['widget'], 21)
                self.assertEqual(int(result['parameters']['Widget21RestoreLevel'], 0), 0)
                self.cli(*args, 'set', 'Widget21RestoreLevel', 155)
                result = self.cli(*args, 'edlt-time-date', *functional, '--display', 'date')
                self.assertEqual(int(result['parameters']['Widget21RestoreLevel'], 0), 155)
                for name, code in (('12-hour', 3), ('24-hour', 1), ('12-hour-lowercase', 0), ('12-hour-uppercase', 2)):
                    result = self.cli(*args, 'edlt-time-date', *functional, '--time-format', name, '--no-leading-zero')
                    self.assertEqual(result['time_format'], name)
                    self.assertFalse(result['leading_zero'])
                    self.assertEqual(int(result['parameters']['TimeFormat'], 0), code)
                    self.assertEqual(int(result['parameters']['TimeDateLeadingZero'], 0), 0)
                for invalid in (('--page', 0, '--position', 5, '--slices', 2),
                                ('--page', 1, '--position', 1, '--slices', 2)):
                    self.assertIn('error', self.cli(*args, 'edlt-time-date', *invalid, status=1))
                rejected = self.cli(*args, '--destination', network + '/p/20',
                                    'edlt-time-date', *functional, status=1)
                self.assertIn('database destinations only', rejected['error'])
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                for action in ('save', 'close', 'load'):
                    projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
            finally:
                projects.operation('close', project)
                projects.operation('delete', project)


if __name__ == '__main__':
    unittest.main()
