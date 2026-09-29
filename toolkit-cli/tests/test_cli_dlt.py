"""DLT CLI: registry lookup, offline label-variant show/plan and native database apply."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

from test_dlt_labels import fixture
from test_macros import NATIVE, NATIVE_REASON


def write_spec(folder, filename='KEYL5.xml', spec_type='KEYL5'):
    spec = fixture(filename, spec_type)
    root = ET.Element('UnitSpecification')
    ET.SubElement(root, 'Type').text = spec_type
    parameters = ET.SubElement(root, 'Parameters')
    for parameter in spec.parameters.values():
        node = ET.SubElement(parameters, 'Param')
        for key, value in parameter.fields.items():
            ET.SubElement(node, key).text = value
    ET.ElementTree(root).write(Path(folder) / filename, encoding='utf-8', xml_declaration=True)
    return spec


def snapshot(folder, unit_type='KEYML5', firmware='3.0.00', catalog='5055DL', parameters=None):
    path = Path(folder) / f'{unit_type}-{firmware}-{catalog}.json'
    path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': unit_type, 'firmware': firmware,
                                'catalog_number': catalog,
                                'parameters': fixture().defaults() if parameters is None else parameters}))
    return path


class DltCliTests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_profiles_registry_and_identity_lookup(self):
        document = self.cli('dlt', 'profiles')
        self.assertEqual(document['format'], 'cbus-dlt-profile-registry-v1')
        self.assertEqual({row['unit_type'] for row in document['profiles']}, {'KEYBL5', 'KEYML5', 'KEYDL4', 'KEYGL5'})
        self.assertIn('5505ED', document['findings']['help_only_catalog_names'])
        view = self.cli('dlt', 'profiles', '--unit-type', 'KEYGL5', '--firmware', '5.5.00',
                        '--catalog-number', 'R5045EDL')
        self.assertFalse(view['workflows']['edlt-database-widgets']['admitted'])
        self.assertIn('only 5055EDL', view['workflows']['edlt-database-widgets']['reason'])
        self.assertTrue(view['workflows']['edlt-label-clear']['admitted'])
        self.assertIn('--unit-type', self.cli('dlt', 'profiles', '--firmware', '1', status=1)['error'])

    def test_offline_show_plan_xml_and_refusals(self):
        with tempfile.TemporaryDirectory() as folder:
            write_spec(folder)
            write_spec(folder, 'KEYL4.xml', 'KEYDL4')
            base = ('dlt', '--spec-dir', folder, 'labels')
            file = snapshot(folder)
            view = self.cli(*base, 'show', '--file', file)
            self.assertEqual([row['variant'] for row in view['slots']], [1] * 8)
            plan = self.cli(*base, 'plan', '--file', file, '--variant', '1=4', '--variant', '8=3')
            self.assertEqual(plan['variants_after'], [4, 1, 1, 1, 1, 1, 1, 3])
            self.assertEqual((plan['firmware'], plan['catalog_number']), ('3.0.00', '5055DL'))
            self.assertEqual({row['changed_mask'] for row in plan['raw_preview']}, {0, 0x48, 0x40})
            self.assertFalse(plan['saved'])
            decorator = self.cli(*base, 'plan', '--file', snapshot(folder, 'KEYDL4', '2.1.00', 'E5084DL'),
                                 '--variant', '4=2')
            self.assertEqual(decorator['spec_filename'], 'KEYL4.xml')
            rows = ''.join(f'<PP Name="{k}" Value="{v}"/>' for k, v in fixture().defaults().items())
            xml = Path(folder) / 'project.xml'
            xml.write_text('<Installation><Project><Address>P1</Address><Network><Address>254</Address>'
                           '<Unit><Address>20</Address><UnitType>KEYBL5</UnitType><FirmwareVersion>2.1.00'
                           f'</FirmwareVersion>{rows}</Unit></Network></Project></Installation>')
            from_xml = self.cli(*base, 'plan', '--project-xml', xml, '--unit', '//P1/254/p/20', '--variant', '2=2')
            self.assertEqual((from_xml['unit_type'], from_xml['catalog_number']), ('KEYBL5', None))
            bare = Path(folder) / 'bare.json'
            bare.write_text(json.dumps(fixture().defaults()))
            for args, message in (
                    (('plan', '--file', snapshot(folder, 'KEYML5', '1.4.00'), '--variant', '1=2'), 'MinVersion'),
                    (('plan', '--file', snapshot(folder, 'KEYGL5', '5.5.00', '5055EDL'), '--variant', '1=2'),
                     'LabelFlavour'),
                    (('plan', '--file', snapshot(folder, 'KEYML5', '3.0.00', 'SLC5055DL'), '--variant', '1=2'),
                     'help catalogue name'),
                    (('plan', '--file', file, '--variant', '1=5'), '1..4'),
                    (('plan', '--file', file, '--variant', '9=1'), '1..8'),
                    (('plan', '--file', file, '--variant', '1=2', '--variant', '1=3'), 'more than once'),
                    (('plan', '--file', file), 'at least one'),
                    (('show', '--file', bare), '--unit-type'),
                    (('show', '--project-xml', xml), '--unit'),
                    (('show', '--file', file, '--firmware', '2.1.00'), 'differs')):
                with self.subTest(args=args):
                    self.assertIn(message, self.cli(*base, *args, status=1)['error'])
            unbound = self.cli(*base, 'show', '--file', bare, '--unit-type', 'KEYML5', '--firmware', '2.1.00')
            self.assertIsNone(unbound['catalog_number'])

    @unittest.skipUnless(NATIVE, NATIVE_REASON)
    def test_native_show_preview_apply_saved_plan_and_refusals(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from test_macros import closed_network_project, native_endpoint
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, 'DC') as project, tempfile.TemporaryDirectory() as folder:
            network = f'//{project}/254'
            database = NativeDatabase(client)
            database.create_unit(network, 20, 'Neo_20', 'KEYML5', '2.1.00', catalog_number='5055DL')
            database.create_unit(network, 21, 'Old_21', 'KEYBL5', '1.4.00', catalog_number='5085DL')
            database.create_unit(network, 22, 'Edlt_22', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
            client.command('PROJECT SAVE ' + project)
            args = ('cgate', '--host', host, '--port', port, '--timeout', '20', 'unit', '--lock-address', network)
            prefix = (*args, '--source', f'/db{network}/p/20')
            original = self.cli(*prefix, 'show')
            view = self.cli(*prefix, 'dlt-labels', '--show')
            self.assertEqual([row['variant'] for row in view['slots']], [1] * 8)
            exported = Path(folder) / 'neo.json'
            self.cli(*prefix, 'export', exported)
            plan = self.cli('dlt', 'labels', 'plan', '--file', exported, '--variant', '3=4', '--variant', '6=2')
            preview = self.cli(*prefix, '--dry-run', 'dlt-labels', '--variant', '3=4', '--variant', '6=2')
            self.assertEqual(preview['changes'], plan['changes'])
            self.assertTrue(preview['verified'] and preview['raw_bytes_verified'])
            self.assertFalse(preview['saved'])
            self.assertEqual(self.cli(*prefix, 'show'), original)
            plan_file = Path(folder) / 'plan.json'
            plan_file.write_text(json.dumps(plan))
            applied = self.cli(*prefix, 'dlt-labels', '--plan', plan_file)
            self.assertTrue(applied['saved'])
            self.assertEqual(applied['parameters']['IndicatorFunction'], original['IndicatorFunction'])
            self.assertEqual([row['variant'] for row in self.cli(*prefix, 'dlt-labels', '--show')['slots']],
                             [1, 1, 4, 1, 1, 2, 1, 1])
            self.assertIn('changed since', self.cli(*prefix, 'dlt-labels', '--plan', plan_file, status=1)['error'])
            self.assertIn('database destinations', self.cli(
                *args, '--source', f'/db{network}/p/20', '--destination', f'{network}/p/20', 'dlt-labels',
                '--variant', '1=2', status=1)['error'])
            for address, message in ((21, 'MinVersion'), (22, 'LabelFlavour')):
                unit = (*args, '--source', f'/db{network}/p/{address}')
                before = self.cli(*unit, 'show')
                self.assertIn(message, self.cli(*unit, 'dlt-labels', '--variant', '1=2', status=1)['error'])
                self.assertEqual(self.cli(*unit, 'show'), before)


if __name__ == '__main__':
    unittest.main()
