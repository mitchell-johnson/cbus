"""Wireless CLI: offline show/plan/boundary, native preview, saved-plan apply and stale refusal."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tests.test_wireless_gateway import NativeProject, fixture as gateway_fixture, native_backend, start_service
from tests.test_wireless_unit_globals import fixture as globals_fixture


def write_spec(folder, spec):
    root = ET.Element('UnitSpecification')
    ET.SubElement(root, 'Type').text = spec.metadata['Type']
    parameters = ET.SubElement(root, 'Parameters')
    for parameter in spec.parameters.values():
        node = ET.SubElement(parameters, 'Param')
        for key, value in parameter.fields.items():
            ET.SubElement(node, key).text = value
    ET.ElementTree(root).write(Path(folder) / spec.filename, encoding='utf-8', xml_declaration=True)


def snapshot(folder, unit_type, firmware, parameters):
    path = Path(folder) / f'{unit_type}-{firmware}.json'
    path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': unit_type, 'firmware': firmware,
                                'catalog_number': None, 'parameters': parameters}))
    return path


class WirelessCliTests(unittest.TestCase):
    host = port = None

    @classmethod
    def setUpClass(cls):
        cls.service = None
        if native_backend() and os.environ.get('CBUS_UNITSPEC_DIR'):
            start_service(cls)

    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_gateway_show_plan_and_refusals(self):
        with tempfile.TemporaryDirectory() as folder:
            spec = gateway_fixture()
            write_spec(folder, spec)
            values = {**spec.defaults(), 'MapWirelessRemotes': '1', 'Application': '56 202',
                      'SceneVectorOffset': '0 255 255 255 255 255 255 255',
                      'SceneTriggerGroup': '9 255 255 255 255 255 255 255'}
            file = snapshot(folder, 'WGATE5F', '2.4.00', values)
            view = self.cli('wireless', '--spec-dir', folder, 'gateway', 'show', file)
            self.assertEqual((view['mode'], len(view['remotes'])), ('remote-switch', 8))
            plan = self.cli('wireless', '--spec-dir', folder, 'gateway', 'plan', file, '--remote', '2',
                            '--serial', '0x10203', '--remote-key', '1=group:7:secondary', '--remote-key', '2=scene-toggle:1',
                            '--remote-slot', '16=group:none')
            self.assertEqual(plan['changes']['RemoteIdentity2'], [3, 2, 1, 0])
            self.assertEqual(plan['changes']['GroupAddress2'][4], 7)
            self.assertEqual(plan['changes']['GroupAddress2'][3], 6)
            self.assertEqual(plan['raw_slot_edits'], [16])
            refused = self.cli('wireless', '--spec-dir', folder, 'gateway', 'plan',
                               snapshot(folder, 'WGATE5N', '2.4.00', values), '--mode', 'network-gateway', status=1)
            self.assertIn('TCBusWirelessGatewayUnit', json.dumps(refused))
            self.cli('wireless', '--spec-dir', folder, 'gateway', 'plan', file, '--remote-key', '1=group:1', status=1)

    def test_offline_globals_and_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            spec = globals_fixture('WRM2D1')
            write_spec(folder, spec)
            file = snapshot(folder, 'WRM2D1', '2.0.0', spec.defaults())
            view = self.cli('wireless', '--spec-dir', folder, 'globals', 'show', file)
            self.assertEqual(view['learn']['mode'], 'any')
            plan = self.cli('wireless', '--spec-dir', folder, 'globals', 'plan', file, '--learn-mode', 'off',
                            '--network-learn', 'off', '--house-code', '0000abcd', '--key-enable-mask', '3=0x00ff')
            self.assertEqual(plan['changes']['HouseCode'], [0xCD, 0xAB, 0, 0])
            self.assertEqual(plan['beyond_dialog'], ['HouseCode', 'KeyEnableMask3'])
            self.cli('wireless', '--spec-dir', folder, 'globals', 'plan',
                     snapshot(folder, 'WRM2D1', '1.9.0', spec.defaults()), '--learn-mode', 'off', status=1)
        boundary = self.cli('wireless', 'boundary', '--unit', '20', '--learn', '56', '1', '10')
        self.assertFalse(boundary['io_performed'])
        self.assertEqual(boundary['net_learn']['command'], '\\05380003010AF5')
        self.assertEqual(boundary['unit_actions']['ResetOpStats']['commands'], ['\\46140008'])

    @unittest.skipUnless(native_backend() and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Select native C-Gate and unit specs for the wireless CLI acceptance')
    def test_native_preview_apply_saved_plan_and_stale_refusal(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        with CGateClient(self.host, self.port, timeout=30) as client, NativeProject(client, 'WC') as project, \
                tempfile.TemporaryDirectory() as folder:
            network = project.network
            NativeDatabase(client).create_unit(network, 30, 'Wg30', 'WGATE5F', '2.4.00', catalog_number='5800WCGA')
            NativeDatabase(client).create_unit(network, 31, 'Wm31', 'WRM4D2', '2.4.00', catalog_number='5854D1L2AA')
            with Programmer(client).load(network, f'/db{network}/p/30') as pp:
                pp.set('Application', '56 202')
                pp.set('MapWirelessRemotes', '1')
                pp.save_to_source()
            base = ['cgate', '--host', self.host, '--port', self.port, 'unit', '--lock-address', network]
            gateway = [*base, '--source', f'/db{network}/p/30']
            view = self.cli(*gateway, 'wireless-gateway', '--show')
            self.assertEqual(view['mode'], 'remote-switch')
            preview = self.cli(*base, '--source', f'/db{network}/p/30', '--dry-run', 'wireless-gateway',
                               '--remote', '1', '--serial', '66051', '--remote-key', '3=group:12:secondary')
            self.assertFalse(preview['saved'])
            self.assertEqual(preview['changes']['RemoteIdentity1'], [3, 2, 1, 0])
            plan = Path(folder) / 'plan.json'
            plan.write_text(json.dumps({k: preview[k] for k in (
                'format', 'unit_type', 'firmware', 'catalog_number', 'remote', 'raw_slot_edits',
                'expected', 'changes')}))
            applied = self.cli(*gateway, 'wireless-gateway', '--plan', plan)
            self.assertTrue(applied['saved'] and applied['verified'])
            stale = self.cli(*gateway, 'wireless-gateway', '--plan', plan, status=1)
            self.assertIn('changed since', json.dumps(stale))
            after = self.cli(*gateway, 'wireless-gateway', '--show')
            self.assertEqual(after['remotes'][0]['keys'][2], {
                'key': 3, 'slot': 3, 'function': 'group', 'label': 'Group Dimmer', 'application': 'secondary',
                'group': 12, 'raw': {'mask': 0, 'secondary': 1, 'value': 12}})
            globals_unit = [*base, '--source', f'/db{network}/p/31']
            result = self.cli(*globals_unit, 'wireless-globals', '--learn-mode', 'current', '--house-code', '00c0ffee')
            self.assertTrue(result['saved'])
            self.assertEqual(self.cli(*globals_unit, 'wireless-globals', '--show')['house_code']['text'], '00c0ffee')
            refused = self.cli(*base, '--source', f'/db{network}/p/30', 'wireless-globals', '--learn-mode', 'off',
                               status=1)
            self.assertIn('WRM', json.dumps(refused))
            physical = self.cli(*base, '--source', f'{network}/p/31', 'wireless-globals', '--learn-mode', 'off',
                                status=1)
            self.assertIn('database destinations only', json.dumps(physical))


if __name__ == '__main__':
    unittest.main()
