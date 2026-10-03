"""Static MRA source facts and literal provenance; never execute vendor code."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ANNEX_PATH = ROOT / 'research/fixtures/edlt-mra-control-source-annex.json'
VECTOR_PATH = ROOT / 'research/fixtures/edlt-mra-control-literal-vectors.json'
NOTES_PATH = ROOT / 'research/fixtures/edlt-mra-control-provenance.json'
ANNEX = json.loads(ANNEX_PATH.read_text())
VECTORS = json.loads(VECTOR_PATH.read_text())
NOTES = json.loads(NOTES_PATH.read_text())
_spec = importlib.util.spec_from_file_location('edlt_mra_control_static', ROOT / 'research/edlt_mra_control_static.py')
static = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(static)


class MRAStaticEvidenceTests(unittest.TestCase):
    def test_exact_managed_spans_and_proved_source_order(self):
        self.assertEqual(len(ANNEX['managed_method_spans']), 122)
        self.assertEqual(len(ANNEX['decompiled_source_symbols']), 79)
        self.assertEqual(len(ANNEX['static_checks']), 166)
        for row in ANNEX['managed_method_spans']:
            with self.subTest(symbol=row['symbol'], token=row['token']):
                self.assertEqual(int(row['token'], 16) >> 24, 6)
                self.assertEqual(row['metadata_runtime'], 'v4.0.30319')
                self.assertRegex(row['body_sha256'], r'^[0-9a-f]{64}$')
                self.assertRegex(row['il_sha256'], r'^[0-9a-f]{64}$')
                self.assertGreaterEqual(row['body_bytes'], row['header_bytes'] + row['code_bytes'])
                self.assertTrue(row['static_decode_only'])
        self.assertTrue(all(row['passed'] for row in ANNEX['static_checks']))
        self.assertEqual(ANNEX['metadata_type_relationships'][0]['base_type'],
            'CBusLogicModel.Units.EDLT.WidgetData.BaseObjects.WidgetBaseData')
        checks = {row['id']: row for row in ANNEX['static_checks']}
        self.assertEqual(checks['save-propagates-zone-before-multiplexer']['ordered_call_suffixes'],
            ['get_Widgets', 'OfType', 'get_MRAZone', 'set_Zone', 'get_MRAMultiplexer', 'set_Multiplexer'])
        self.assertTrue(checks['all-three-use-inherited-empty-SetForcedValues']['passed'])

    def test_actual_bindings_choices_and_qualified_declaration_phases(self):
        bindings = ANNEX['ordered_panel_bindings']
        self.assertEqual(len(bindings), 25)
        for panel, count in (('MRAZoneWidget', 11), ('MRASourceSelectWidget', 10), ('MRASourceControlWidget', 4)):
            rows = [row for row in bindings if row['panel'] == panel]
            self.assertEqual(len(rows), count)
            self.assertFalse(any(row['source_property'] == 'Offset' for row in rows))
        self.assertEqual([row['value'] for row in ANNEX['source_choices']['lFunctionStatusTypesMRA']], [0, 3, 1, 2, 5])
        self.assertEqual([row['value'] for row in ANNEX['source_choices']['lMRAAbsoluteSource']], list(range(7)))
        self.assertEqual(NOTES['form_binding_phase'], 'activation-context-only-not-declaration-or-callback-order')
        self.assertIn('InitializeComponent', NOTES['form_binding_phase_explanation'])
        for case in VECTORS['form_binding_cases']:
            panel = case['panel']
            self.assertIn(panel, ('MRAZoneWidget', 'MRASourceSelectWidget', 'MRASourceControlWidget'))

    def test_complete_literal_roster_and_no_original_execution_promotion(self):
        self.assertEqual(len(VECTORS['cases']), 325)
        self.assertEqual(sum(len(case['steps']) for case in VECTORS['cases']), 595)
        self.assertEqual(len(VECTORS['refusal_candidates']), 19)
        self.assertEqual(len(VECTORS['ordered_lifecycle_cases']), 2)
        self.assertEqual(len(VECTORS['form_binding_cases']), 3)
        self.assertEqual(hashlib.sha256(VECTOR_PATH.read_bytes()).hexdigest(), NOTES['frozen_literal_sha256'])
        for case in VECTORS['cases']:
            with self.subTest(case=case['case_id']):
                self.assertEqual(len(bytes.fromhex(case['record_before_hex'])), 32)
                self.assertEqual(len(bytes.fromhex(case['expected_record_after_hex'])), 32)
                self.assertFalse(case['original_instructions_executed'])
        self.assertEqual(ANNEX['limits']['original_instructions_executed'], 0)
        self.assertEqual(ANNEX['limits']['framework_instructions_executed'], 0)
        self.assertFalse(ANNEX['limits']['current_release_acceptance'])
        self.assertFalse(NOTES['original_instructions_executed'])
        self.assertEqual(NOTES['enter_means'], 'Enter key; never focus Enter')

    def test_source_pins_and_no_raw_code_or_private_coordinates(self):
        self.assertEqual(len(ANNEX['original_inputs']), 18)
        self.assertEqual(len(static.PINS), 17)
        for row in ANNEX['original_inputs']:
            self.assertRegex(row['sha256'], r'^[0-9a-f]{64}$')
            self.assertFalse(row['logical_name'].startswith('/'))
        for path in (ANNEX_PATH, VECTOR_PATH, NOTES_PATH):
            text = path.read_text()
            for coordinate in ('/private/', '/Users/', '/Volumes/', 'il_hex'):
                self.assertNotIn(coordinate, text)
        self.assertFalse(ANNEX['omissions']['vendor_source_text_published'])
        self.assertFalse(ANNEX['omissions']['raw_il_bytes_published'])

    def test_static_only_pinned_regeneration(self):
        vendor = os.environ.get('CBUS_MRA_CONTROL_STATIC_VENDOR_ROOT')
        if not vendor:
            self.skipTest('Explicit private pinned MRA static source is not configured')
        rendered = (json.dumps(static.recover(ROOT.parent, Path(vendor)), indent=2) + '\n').encode()
        self.assertEqual(rendered, ANNEX_PATH.read_bytes())
