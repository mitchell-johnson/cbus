"""Public offline SENLLA component view, strict identity and read-only boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cbus_toolkit.cli import build_parser
from cbus_toolkit.sensor_dialog_cli import offline
from tests.test_senlla_surface import fixture


class SENLLASurfaceCLITests(unittest.TestCase):
    def run_cli(self, *args, status=0):
        env = {key: value for key, value in os.environ.items() if key != 'CBUS_UNITSPEC_DIR'}
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def snapshot(self, path, values, identity=('SENLLA', '2.4.00', '5754PE')):
        path.write_text(json.dumps({
            'format': 'cbus-cli-parameters-v1', 'unit_type': identity[0],
            'firmware': identity[1], 'catalog_number': identity[2], 'parameters': values,
        }))

    def write_spec(self, path, spec):
        # This small authored fixture contains only the 13 consumed component
        # fields; it is not a retained vendor specification or full sensor PP.
        root = ET.Element('UnitSpecification')
        ET.SubElement(root, 'Type').text = spec.unit_type
        parameters = ET.SubElement(root, 'Parameters')
        for parameter in spec.parameters.values():
            element = ET.SubElement(parameters, 'Param')
            for name, value in parameter.fields.items():
                ET.SubElement(element, name).text = value
        ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)

    def test_public_view_routes_source_pinned_component_without_mutating_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            spec_file, snapshot = directory / 'SENLLA.xml', directory / 'sensor.json'
            self.write_spec(spec_file, fixture())
            values = {**fixture().defaults(),
                      'LightLevelTargetGroup': '7', 'LightLevelMarginGroup': '9',
                      'PECTargetLux': '40', 'PECMarginLux': '8',
                      'LightLevelTargetGroupLevelStore': '1', 'LightLevelMarginGroupLevelStore': '0',
                      'PowerUpTargetGroupLevel': '13', 'PowerUpMarginGroupLevel': '89',
                      'UnconsumedEightKeySentinel': '9 8 7 6 5 4 3 2'}
            original_spec = spec_file.read_bytes()
            for firmware in ('2.4.00', '2.4.99'):
                with self.subTest(firmware=firmware):
                    self.snapshot(snapshot, values, ('SENLLA', firmware, '5754PE'))
                    original_snapshot = snapshot.read_bytes()
                    result = self.run_cli('sensors', '--spec-dir', directory,
                                          'surface-light-level-view', snapshot)
                    self.assertEqual(result['format'], 'cbus-senlla-surface-view-v1')
                    self.assertEqual((result['unit_type'], result['firmware'], result['catalog_number']),
                                     ('SENLLA', firmware, '5754PE'))
                    self.assertEqual(result['expected']['LightLevelTargetGroup'], [7])
                    self.assertEqual(result['expected']['LightLevelMarginGroup'], [9])
                    self.assertEqual(result['expected']['PECTargetLux'], [40])
                    self.assertEqual(result['expected']['PECMarginLux'], [8])
                    overlay = result['component_overlay']
                    self.assertEqual(overlay['LightLevelMarginGroup'], [7])
                    self.assertEqual(overlay['PECTargetLux'], [200])
                    self.assertEqual(overlay['PECMarginLux'], [40])
                    self.assertEqual(overlay['PowerUpMarginGroupLevel'], [13])
                    self.assertEqual(overlay['LightLevelMarginGroupLevelStore'], [1])
                    self.assertNotIn('UnconsumedEightKeySentinel', result['expected'])
                    self.assertFalse(result['complete_toolkit_save'])
                    self.assertFalse(result['original_execution'])
                    self.assertFalse(result['physical_acceptance'])
                    self.assertEqual(snapshot.read_bytes(), original_snapshot)
                    self.assertEqual(spec_file.read_bytes(), original_spec)

    def test_identity_and_bare_mapping_refuse_before_loading_schema(self):
        parser = build_parser()
        with tempfile.TemporaryDirectory() as folder, patch('cbus_toolkit.sensor_dialog_cli._store') as store:
            snapshot = Path(folder) / 'sensor.json'
            for identity in (('SENLL', '2.4.00', '5031PE'), ('SENLLA', '2.3.99', '5754PE'),
                             ('SENLLA', '2.5.00', '5754PE'), ('SENLLA', '2.4.100', '5754PE'),
                             ('SENLLA', '2.4.00', 'SLC5754PE'), ('SENLLA', None, '5754PE')):
                with self.subTest(identity=identity):
                    self.snapshot(snapshot, {}, identity)
                    before = snapshot.read_bytes()
                    args = parser.parse_args(['sensors', 'surface-light-level-view', str(snapshot)])
                    with self.assertRaises(ValueError):
                        offline(args)
                    store.assert_not_called()
                    self.assertEqual(snapshot.read_bytes(), before)
            snapshot.write_text('{}')
            args = parser.parse_args(['sensors', 'surface-light-level-view', str(snapshot)])
            with self.assertRaisesRegex(ValueError, 'PP export'):
                offline(args)
            store.assert_not_called()

    def test_new_view_has_no_edit_flags_and_does_not_broaden_senll_save_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / 'sensor.json'
            self.snapshot(snapshot, {})
            before = snapshot.read_bytes()
            error = self.run_cli('sensors', 'light-level-plan', snapshot, status=1)
            self.assertIn('TSENLLA', error['error'])
            result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'sensors',
                                     'surface-light-level-view', str(snapshot), '--target-lux', '500'],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2)
            self.assertIn('unrecognized arguments', result.stderr)
            self.assertEqual(snapshot.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
