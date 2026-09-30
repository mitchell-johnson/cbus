"""Public CLI plans and native database application of classic display controls."""
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from test_cli_dlt import snapshot
from test_cli_dlt_controls import cli
from test_dlt_display import fixture
from test_macros import NATIVE, NATIVE_REASON, closed_network_project, native_endpoint


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


class DisplayCliTests(unittest.TestCase):
    def test_offline_show_plan_pp_export_bare_mapping_and_project_xml(self):
        with tempfile.TemporaryDirectory() as folder:
            spec = write_spec(folder)
            values = spec.defaults()
            values.update(IndicatorMode='3', HideClock='1')
            source = snapshot(folder, parameters=values)
            base = ('dlt', '--spec-dir', folder, 'display')
            shown = cli(*base, 'show', '--file', source)
            self.assertEqual(shown['controls'], {'indicator_mode': 'on', 'invert_display': False, 'show_clock': False})
            plan = cli(*base, 'plan', '--file', source, '--show-clock', 'yes')
            self.assertEqual(plan['format'], 'cbus-classic-dlt-display-plan-v1')
            self.assertEqual(plan['changes'], {'HideClock': [0]})
            self.assertEqual(plan['expected']['IndicatorMode'], [3])
            normalized = cli(*base, 'plan', '--file', source, '--indicator-mode', 'on', '--invert-display', 'yes')
            self.assertEqual(normalized['changes'], {'IndicatorMode': [2], 'InvertDisplay': [1]})
            bare = Path(folder) / 'bare.json'
            bare.write_text(json.dumps(values))
            self.assertEqual(cli(*base, 'show', '--file', bare, '--unit-type', 'KEYML5', '--firmware', '3.0.00')['controls'],
                             shown['controls'])
            rows = ''.join(f'<PP Name="{k}" Value="{v}"/>' for k, v in values.items())
            project = Path(folder) / 'project.xml'
            project.write_text('<Installation><Project><Address>P1</Address><Network><Address>254</Address>'
                               '<Unit><Address>20</Address><UnitType>KEYBL5</UnitType>'
                               f'<FirmwareVersion>2.1.00</FirmwareVersion>{rows}</Unit></Network></Project></Installation>')
            self.assertEqual(cli(*base, 'show', '--project-xml', project, '--unit', '//P1/254/p/20')['controls'],
                             shown['controls'])
            for arguments, message in (
                    (('plan', '--file', source), 'Select'),
                    (('show', '--file', source, '--firmware', '2.1.00'), 'differs'),
                    (('show', '--file', bare), '--unit-type'),
                    (('show', '--project-xml', project), '--unit'),
                    (('plan', '--file', snapshot(folder, firmware='1.4.00', parameters=values),
                      '--show-clock', 'no'), 'MinVersion')):
                with self.subTest(arguments=arguments):
                    self.assertIn(message, cli(*base, *arguments, status=1)['error'])

    @unittest.skipUnless(NATIVE, NATIVE_REASON)
    def test_native_show_preview_plan_stale_mixing_destination_guards_and_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, 'DS') as project, tempfile.TemporaryDirectory() as folder:
            network = f'//{project}/254'
            NativeDatabase(client).create_unit(network, 20, 'DltDisplay', 'KEYML5', '2.1.00', catalog_number='5055DL')
            prefix = ('cgate', '--host', host, '--port', port, '--timeout', '30', 'unit',
                      '--lock-address', network, '--source', f'/db{network}/p/20')
            before = cli(*prefix, 'dlt-labels', '--show-display')
            source = Path(folder) / 'unit.json'
            cli(*prefix, 'export', source)
            plan = cli('dlt', 'display', 'plan', '--file', source,
                       '--indicator-mode', 'on', '--invert-display', 'yes', '--show-clock', 'no')
            plan_file = Path(folder) / 'display-plan.json'
            plan_file.write_text(json.dumps(plan))
            preview = cli(*prefix, '--dry-run', 'dlt-labels', '--plan', plan_file)
            self.assertTrue(preview['verified'] and preview['raw_bytes_verified'])
            self.assertFalse(preview['saved'] or preview['device_verified'])
            self.assertEqual(cli(*prefix, 'dlt-labels', '--show-display'), before)
            for flags in (('--show-display', '--show'), ('--show-display', '--invert-display', 'yes'),
                          ('--show-display', '--plan', plan_file), ('--indicator-mode', 'off', '--variant', '1=3'),
                          ('--show-clock', 'yes', '--block-dynamic-updates', 'yes'),
                          ('--plan', plan_file, '--show-clock', 'yes'),
                          ('--show', '--indicator-mode', 'off'), ('--plan', plan_file, '--variant', '1=4')):
                with self.subTest(flags=flags):
                    self.assertIn('cannot be combined', cli(*prefix, 'dlt-labels', *flags, status=1)['error'])
            self.assertEqual(cli(*prefix, 'dlt-labels', '--show-display'), before)
            guard = cli(*prefix, '--destination', network + '/p/20', 'dlt-labels', '--show-clock', 'no', status=1)
            self.assertIn('database', guard['error'].lower())
            applied = cli(*prefix, 'dlt-labels', '--plan', plan_file)
            self.assertTrue(applied['saved'])
            self.assertEqual(cli(*prefix, 'dlt-labels', '--show-display')['controls'], plan['after'])
            self.assertIn('changed since', cli(*prefix, 'dlt-labels', '--plan', plan_file, status=1)['error'])
            client.command('PROJECT SAVE ' + project)
            client.command('PROJECT CLOSE ' + project)
            client.command('PROJECT LOAD ' + project)
            client.command('PROJECT USE ' + project)
            self.assertEqual(cli(*prefix, 'dlt-labels', '--show-display')['controls'], plan['after'])
            direct = cli(*prefix, 'dlt-labels', '--indicator-mode', 'off', '--invert-display', 'no', '--show-clock', 'yes')
            self.assertTrue(direct['saved'])
            self.assertEqual(cli(*prefix, 'dlt-labels', '--show-display')['controls'],
                             {'indicator_mode': 'off', 'invert_display': False, 'show_clock': True})
