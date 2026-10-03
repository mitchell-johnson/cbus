"""Pinned static provenance and independently literal callback contracts."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ANNEX_PATH = ROOT / 'research/fixtures/edlt-label-control-source-annex.json'
VECTOR_PATH = ROOT / 'research/fixtures/edlt-label-control-vectors.json'
spec = importlib.util.spec_from_file_location('edlt_label_control_static', ROOT / 'research/edlt_label_control_static.py')
static = importlib.util.module_from_spec(spec)
spec.loader.exec_module(static)
ANNEX = json.loads(ANNEX_PATH.read_text())


class LabelControlStaticTests(unittest.TestCase):
    def test_managed_source_spans_are_exact_and_never_executed(self):
        methods = ANNEX['managed_method_spans']
        self.assertEqual(len(methods), 29)
        self.assertEqual({row['symbol'] for row in methods},
                         {symbol for symbols in static.METHODS.values() for symbol in symbols})
        for row in methods:
            with self.subTest(symbol=row['symbol']):
                self.assertEqual(row['metadata_runtime'], 'v4.0.30319')
                self.assertEqual(int(row['token'], 16) >> 24, 6)
                self.assertGreaterEqual(row['body_bytes'], row['header_bytes'] + row['code_bytes'])
                self.assertRegex(row['body_sha256'], r'^[0-9a-f]{64}$')
                self.assertRegex(row['il_sha256'], r'^[0-9a-f]{64}$')
                self.assertTrue(row['static_decode_only'])
                self.assertTrue(all(0 <= call['il_offset'] < row['code_bytes'] for call in row['calls']))
        self.assertEqual(len(ANNEX['decompiled_source_symbols']), 23)
        self.assertEqual(len(ANNEX['original_inputs']), 10)
        self.assertEqual({row['sha256'] for row in ANNEX['original_inputs']},
                         {*static.PINS.values(), static.PARSER_PIN})

    def test_source_contract_separates_getters_notifications_and_control_callbacks(self):
        checks = ANNEX['static_checks']
        self.assertEqual(len(checks), 60)
        self.assertTrue(all(row['passed'] for row in checks))
        by_id = {row['id']: row for row in checks}
        self.assertEqual(len(by_id), len(checks))
        self.assertEqual(by_id['list-change-is-read-only']['absent_call_suffixes'], ['WriteValue'])
        self.assertEqual(by_id['update-status-before-label']['ordered_call_suffixes'],
            ['get_StatusDisplayType', 'set_StatusDisplayType', 'get_LabelDisplayType', 'set_LabelDisplayType'])
        self.assertEqual(by_id['unassigned-group-has-no-dynamic-labels']['required_integer_constants'], [255])
        self.assertEqual(by_id['enter-and-four-arrow-keys']['required_integer_constants'], [13, 37, 39, 38, 40])
        self.assertEqual(ANNEX['source_type_choice_values'], {
            'lLabelTypes': [0, 10, 3], 'lLabelTypesScene': [0, 1, 2, 3],
            'lFunctionStatusTypes': [0, 3, 10, 1, 2, 5],
            'lFunctionStatusTypesScenes': [0, 6, 7, 5]})
        self.assertIn('focus Enter', ANNEX['source_contract']['callbacks'])
        self.assertIn('current', ANNEX['source_contract']['dynamic_rows'])

    def test_proof_and_vectors_publish_no_original_bytes_or_private_coordinates(self):
        for path in (ANNEX_PATH, VECTOR_PATH):
            text = path.read_text()
            for forbidden in ('/Users/', '/Volumes/', '/private/', 'il_hex', 'body_hex', '"source_text":'):
                self.assertNotIn(forbidden, text)
            self.assertIsNone(re.search(r'[A-Za-z]:\\(?:Dev|Users|Program Files)', text))
        omissions = ANNEX['omissions']
        self.assertEqual(omissions['local_coordinate_fields_published'], 0)
        self.assertFalse(omissions['raw_instruction_bytes_published'])
        self.assertFalse(omissions['decompiled_source_text_published'])
        self.assertFalse(omissions['original_literal_heaps_published'])
        for name, value in ANNEX['limits'].items():
            self.assertEqual(value, 0 if name.endswith('instructions_executed') else False, name)

    def test_static_regeneration_uses_only_explicit_pinned_private_data(self):
        vendor = os.environ.get('CBUS_LABEL_CONTROL_STATIC_VENDOR_ROOT')
        if not vendor:
            self.skipTest('Explicit pinned private label-control static inputs are not configured')
        rendered = (json.dumps(static.recover(Path(vendor)), indent=2, ensure_ascii=False) + '\n').encode('utf8')
        self.assertEqual(rendered, ANNEX_PATH.read_bytes())

    def test_changed_source_or_order_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            static.require_order(['ReadValue', 'WriteValue'], ['WriteValue', 'ReadValue'], 'write-before-read')
        with self.assertRaises(ValueError):
            static.source_span(b'public int Value { get { return 1; } }\n' * 2,
                               'Value', 'public int Value')
        span = static.source_span(b'public int Value { get { return 1; } }\n',
                                  'Value', 'public int Value')
        self.assertEqual(span['sha256'], hashlib.sha256(b'public int Value { get { return 1; } }').hexdigest())


if __name__ == '__main__':
    unittest.main()
