"""Public SENLL repeated-control grammar, producer routing and actual console."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cbus_toolkit.cli import build_parser
from cbus_toolkit.sensor_dialog_cli import _on_off_control, light_level_settings, native, offline
from test_light_level_sensors import fixture
from test_macros import Session
from test_senll_control_history import values


class SENLLControlCLITests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_strict_control_grammar(self):
        for text, expected in (('application=primary', {'application': 'primary'}),
                               ('application=secondary', {'application': 'secondary'}),
                               ('group=20', {'group': 20}), ('group=0x14', {'group': 20}),
                               ('group=none', {'group': 255}), ('group=255', {'group': 255})):
            with self.subTest(text=text):
                self.assertEqual(_on_off_control(text), expected)
        for text in ('primary', 'application=', 'application=PRIMARY', 'group=', 'group=256',
                     'group=-1', 'group=true', 'group=20,application=primary', 'unknown=1',
                     'group=1=2', ' application=primary'):
            with self.subTest(text=text), self.assertRaises(argparse.ArgumentTypeError):
                _on_off_control(text)

    def test_repeated_flags_preserve_order_on_offline_and_native_parsers(self):
        options = ['--on-off-control', 'application=primary', '--on-off-control', 'application=secondary',
                   '--on-off-control', 'group=0x14']
        expected = [{'application': 'primary'}, {'application': 'secondary'}, {'group': 20}]
        for command in (['sensors', 'light-level-plan', 'caller.json'],
                        ['cgate', 'unit', '--lock-address', '//TEST/254', '--source', '/db//TEST/254/p/20',
                         'sensor-light-level']):
            with self.subTest(command=command):
                args = self.parser.parse_args(command + options)
                self.assertEqual(light_level_settings(args)['on_off_controls'], expected)

    def test_any_flat_group_edit_mixed_with_history_refuses_without_model_import(self):
        for option, choice in (('--on-off-group', 'none'), ('--on-off-application', 'primary'),
                               ('--level-group', '21'), ('--broadcast-group', '22'), ('--enable-group', '23')):
            with self.subTest(option=option):
                args = self.parser.parse_args(['sensors', 'light-level-plan', 'caller.json',
                    '--on-off-control', 'application=primary', option, choice])
                with self.assertRaisesRegex(ValueError, 'cannot be mixed'):
                    light_level_settings(args)

    def test_offline_native_adapters_share_history_and_replace_safe_receipt(self):
        current = values()
        options = ['--on-off-control', 'application=primary', '--indicator', 'enable', '--target-lux', '500']
        with tempfile.TemporaryDirectory() as folder, patch('cbus_toolkit.sensor_dialog_cli._store') as store:
            store.return_value.load.return_value = fixture()
            path = Path(folder) / 'sensor.json'
            path.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'SENLL',
                'firmware': '2.3.00', 'catalog_number': '5031PE', 'parameters': current}))
            source_bytes = path.read_bytes()
            args = self.parser.parse_args(['sensors', 'light-level-plan', str(path)] + options)
            planned, status = offline(args)
            self.assertEqual(status, 0)
            session = Session(fixture())
            session.unit_type, session.firmware, session.catalog_number = 'SENLL', '2.3.00', '5031PE'
            session.current.update({name: ' '.join(map(str, value)) for name, value in current.items()})
            args = self.parser.parse_args(['cgate', 'unit', '--lock-address', '//TEST/254',
                '--source', '/db//TEST/254/p/20', 'sensor-light-level'] + options)
            applied = native(args, session)
            self.assertEqual(planned['changes'], applied['changes'])
            self.assertEqual(planned['control_history'], applied['control_history'])
            self.assertTrue(applied['verified'])
            self.assertFalse(applied['saved'] or applied['device_verified'])
            self.assertEqual(path.read_bytes(), source_bytes)
            self.assertFalse(any(name == 'BlockAllocation' for name, _value in session.calls))

    def test_legacy_flat_options_are_still_supported_without_history(self):
        for command in (['sensors', 'light-level-plan', 'caller.json'],
                        ['cgate', 'unit', '--lock-address', '//TEST/254', '--source', '/db//TEST/254/p/20',
                         'sensor-light-level']):
            args = self.parser.parse_args(command + ['--on-off-group', '21', '--on-off-application', 'primary'])
            settings = light_level_settings(args)
            self.assertEqual(settings['on_off_group'], 21)
            self.assertEqual(settings['on_off_application'], 'primary')
            self.assertNotIn('on_off_controls', settings)

    def test_actual_console_uses_synthetic_spec_and_preserves_every_input_file(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            root = ET.Element('UnitSpecification')
            ET.SubElement(root, 'Type').text = 'SENPILL'
            parameters = ET.SubElement(root, 'Parameters')
            for parameter in fixture().parameters.values():
                node = ET.SubElement(parameters, 'Param')
                for field, value in parameter.fields.items():
                    ET.SubElement(node, field).text = value
            spec = directory / 'SENLL_ST7.xml'
            spec.write_bytes(ET.tostring(root, encoding='utf-8'))
            source = directory / 'sensor.json'
            source.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'SENLL',
                'firmware': '2.3.00', 'catalog_number': '5031PE', 'parameters': values()}))
            original = {path: path.read_bytes() for path in (source, spec)}
            command = [sys.executable, '-m', 'cbus_toolkit', '--compact', 'sensors', '--spec-dir', str(directory),
                       'light-level-plan', str(source), '--on-off-control', 'application=primary']
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['changes']['GroupAddress'], [255, 20, 255, 255, 255, 25, 255, 255])
            self.assertEqual(report['control_history']['input_key_count'], 0)
            self.assertFalse(report['saved'] or report['device_verified'])
            refusal = subprocess.run(command + ['--on-off-group', '21'], capture_output=True, text=True, timeout=20)
            self.assertEqual(refusal.returncode, 1, refusal.stdout + refusal.stderr)
            self.assertIn('cannot be mixed', json.loads(refusal.stderr or refusal.stdout)['error'])
            self.assertEqual({path: path.read_bytes() for path in original}, original)


if __name__ == '__main__':
    unittest.main()
