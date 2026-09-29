"""DIN output settings CLI: offline show/plan, native preview, apply and saved-plan staleness."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

from tests.test_din_output_settings import fixture, native_backend


def write_spec(folder, unit_type):
    """Render the synthetic layout fixture as a decoded-spec XML file."""
    spec = fixture(unit_type)
    root = ET.Element('UnitSpecification')
    ET.SubElement(root, 'Type').text = unit_type
    parameters = ET.SubElement(root, 'Parameters')
    for parameter in spec.parameters.values():
        node = ET.SubElement(parameters, 'Param')
        for key, value in parameter.fields.items():
            ET.SubElement(node, key).text = value
    ET.ElementTree(root).write(Path(folder) / spec.filename, encoding='utf-8', xml_declaration=True)
    return spec


def snapshot(folder, unit_type, firmware='2.7.00', parameters=None):
    path = Path(folder) / f'{unit_type}-{firmware}.json'
    path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': unit_type, 'firmware': firmware,
                                'catalog_number': None,
                                'parameters': fixture(unit_type).defaults() if parameters is None else parameters}))
    return path


class DinCliTests(unittest.TestCase):
    host = port = None

    @classmethod
    def setUpClass(cls):
        cls.service = None
        if native_backend() == 'local' and os.environ.get('CBUS_UNITSPEC_DIR'):
            from research.local_cgate import LocalCGate
            cls.service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
            cls.addClassCleanup(cls.service.close)
            (cls.service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
            cls.service.start()
            cls.host, cls.port = '127.0.0.1', cls.service.port
        elif native_backend() == 'host':
            cls.host = os.environ['CBUS_CGATE_TEST_HOST']
            cls.port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))

    def cli(self, *args, status=0, env=None):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_show_plan_and_identity_gates(self):
        with tempfile.TemporaryDirectory() as folder:
            write_spec(folder, 'DIMDN8')
            write_spec(folder, 'RELDN8')
            file = snapshot(folder, 'DIMDN8')
            view = self.cli('din-settings', '--spec-dir', folder, 'show', file)
            self.assertEqual((view['unit_type'], len(view['channels'])), ('DIMDN8', 8))
            plan = self.cli('din-settings', '--spec-dir', folder, 'plan', file, '--channel', '2',
                            '--min-percent', '40', '--max-percent', '80', '--level-store', 'off',
                            '--recovery-percent', '50', '--recovery-delay', '61')
            self.assertEqual(plan['firmware'], '2.7.00')
            self.assertEqual(plan['changes']['MinDimmingLevel'][1], 102)
            self.assertEqual(plan['changes']['MaxDimmingLevel'][1], 204)
            self.assertEqual(plan['changes']['LightLevel'][1], 127)
            self.assertFalse(plan['saved'])
            relay = self.cli('din-settings', '--spec-dir', folder, 'plan', snapshot(folder, 'RELDN8'),
                             '--channel', '1', '--restrike', 'on', '--restrike-delay', '6')
            self.assertEqual(relay['changes']['RestrikeChannel'][1], 1)
            special = snapshot(folder, 'RELDN8SP', parameters=fixture('RELDN8').defaults())
            for args, message in (((special,), 'nine channels'),
                                  ((snapshot(folder, 'DIMDN8', '2.6.99'),), '2.7.00'),
                                  ((file, '--channel', '1', '--restrike', 'on'), 'only on relay'),
                                  ((file, '--channel', '9', '--min-percent', '1'), 'Channel must')):
                with self.subTest(args=args):
                    error = self.cli('din-settings', '--spec-dir', folder, 'plan', *args, status=1)
                    self.assertIn(message, error['error'])
            bare = Path(folder) / 'bare.json'
            bare.write_text(json.dumps(fixture('DIMDN8').defaults()))
            self.assertIn('--unit-type', self.cli('din-settings', '--spec-dir', folder, 'show', bare, status=1)['error'])
            unbound = self.cli('din-settings', '--spec-dir', folder, 'plan', bare, '--unit-type', 'DIMDN8',
                               '--channel', '1', '--min-level', '3')
            self.assertIsNone(unbound['firmware'])

    @unittest.skipUnless(native_backend() and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Select native C-Gate and unit specifications for DIN CLI acceptance')
    def test_native_preview_apply_saved_plan_and_stale_refusal(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = 'DC' + uuid4().hex[:6].upper()
        network = '//' + project + '/254'
        args = ('cgate', '--host', self.host, '--port', self.port, '--timeout', '20', 'unit', '--lock-address', network)
        options = ('--channel', '3', '--min-percent', '20', '--max-percent', '90', '--level-store', 'off',
                   '--recovery-percent', '30', '--recovery-delay', '100')
        with tempfile.TemporaryDirectory() as folder, CGateClient(self.host, self.port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Din_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'Dimmer_20', 'DIMDN8', '2.7.00', catalog_number='5508D1A')
                database.create_unit(network, 21, 'Relay_21', 'RELDN12', '2.7.00', catalog_number='5512RVF')
                database.create_unit(network, 22, 'Special_22', 'RELDN8SP', '2.7.00')
                projects.operation('save', project)
                prefix = (*args, '--source', '/db' + network + '/p/20')
                original = self.cli(*prefix, 'show')
                exported = Path(folder) / 'dimmer.json'
                self.cli(*prefix, 'export', exported)
                plan = self.cli('din-settings', 'plan', exported, *options)
                preview = self.cli(*prefix, '--dry-run', 'din-settings', *options)
                self.assertEqual(plan['changes'], preview['changes'])
                self.assertTrue(preview['verified'])
                self.assertFalse(preview['saved'])
                self.assertEqual(self.cli(*prefix, 'show'), original)
                view = self.cli(*prefix, 'din-settings', '--show')
                self.assertEqual(view['channels'][2]['min_percent'], 0)
                plan_file = Path(folder) / 'plan.json'
                plan_file.write_text(json.dumps(plan))
                applied = self.cli(*prefix, 'din-settings', '--plan', plan_file)
                self.assertTrue(applied['saved'])
                self.assertEqual(applied['parameters']['UnitName'], original['UnitName'])
                stale = self.cli(*prefix, 'din-settings', '--plan', plan_file, status=1)
                self.assertIn('changed since', stale['error'])
                relay = (*args, '--source', '/db' + network + '/p/21')
                result = self.cli(*relay, 'din-settings', '--channel', '12', '--restrike', 'on',
                                  '--restrike-delay', '254', '--interlock', '8')
                self.assertEqual(result['changes']['InterLockingChannel'], [7])
                special = (*args, '--source', '/db' + network + '/p/22')
                before = self.cli(*special, 'show')
                refused = self.cli(*special, 'din-settings', '--channel', '1', '--restrike', 'on', status=1)
                self.assertIn('nine channels', refused['error'])
                self.assertEqual(self.cli(*special, 'show'), before)
                projects.operation('save', project)
                projects.operation('close', project)
                projects.operation('load', project)
                self.assertEqual(self.cli(*prefix, 'show'), applied['parameters'])
                self.assertEqual(self.cli(*relay, 'show'), result['parameters'])
            finally:
                projects.operation('close', project)
                try:
                    projects.operation('delete', project)
                except Exception:  # noqa: BLE001 - owned temporary project cleanup
                    pass


if __name__ == '__main__':
    unittest.main()
