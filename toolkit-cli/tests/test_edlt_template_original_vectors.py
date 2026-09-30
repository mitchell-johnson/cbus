"""Literal unchanged-original CRC and exact-framework-operation comparisons.

The fixture was captured independently of production code by
research/edlt_template_original.py. Original form/lifecycle execution is not
claimed. Error classes are intentionally normalized to the public safe error.
"""
import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt_templates import (
    EdltTemplate, EdltTemplateError, _assignment_value, edlt_template_crc,
)


FIXTURE = json.loads((Path(__file__).resolve().parents[1] /
                     'research/fixtures/edlt-template-original-vectors.json').read_text())
CASES = FIXTURE['cases']


def values(row):
    if 'values' in row:
        return row['values']
    return [item['text'] * item['count'] for item in row['values_repeated']]


class EdltTemplateOriginalVectorsTests(unittest.TestCase):
    def test_fixture_is_the_executed_original_scope(self):
        self.assertEqual(FIXTURE['case_count'], 73)
        self.assertEqual(len(CASES), 73)
        self.assertTrue(FIXTURE['original_static_helpers_executed'])
        self.assertTrue(FIXTURE['network_denied'])
        self.assertTrue(FIXTURE['unchanged_inputs'])
        self.assertFalse(FIXTURE['original_template_dialog_executed'])
        self.assertFalse(FIXTURE['original_parent_lifecycle_executed'])
        self.assertFalse(FIXTURE['physical_io'])
        self.assertEqual(FIXTURE['runtime_pins']['CBusLogicModel.dll'],
                         '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823')

    def test_all_original_crc_string_vectors(self):
        rows = [row for row in CASES if row['kind'] == 'crc']
        self.assertEqual(len(rows), 50)
        # Original invariant StartsWith has culture-ignorable-prefix behavior.
        # The portable API deliberately refuses the wider ambiguous-prefix
        # class, including these two literal original successes, instead of
        # claiming an arbitrary-culture collation implementation.
        portable_scope_refusals = {'hex-prefix-zero-width-space', 'hex-prefix-soft-hyphen'}
        for row in rows:
            with self.subTest(case=row['id']):
                self.assertEqual(len(row['observations']), 1)
                original = row['observations'][0]
                if 'error' in original or row['id'] in portable_scope_refusals:
                    with self.assertRaises(EdltTemplateError):
                        edlt_template_crc(values(row))
                else:
                    self.assertEqual(edlt_template_crc(values(row)), original['value'])

    def test_lower_helper_vectors_as_equivalent_wrapper_inputs(self):
        # Production exposes the wrapper rather than CalculateCrcForTemplate.
        # These synthetic bytes are non-whitespace, so projecting the original
        # [start, len) input interval to code units retains the observed helper
        # bound and final-byte omission without supplying an expected algorithm.
        rows = [row for row in CASES if row['kind'] == 'raw']
        self.assertEqual(len(rows), 4)
        for row in rows:
            with self.subTest(case=row['id']):
                interval = row['bytes'][row['start']:row['length']]
                self.assertEqual(edlt_template_crc([''.join(map(chr, interval))]),
                                 row['observations'][0]['value'])

    def test_all_original_application_framework_vectors(self):
        rows = [row for row in CASES if row['kind'] == 'application']
        self.assertEqual(len(rows), 11)
        for row in rows:
            with self.subTest(case=row['id']):
                original = row['observations'][0]
                if 'error' in original:
                    with self.assertRaises(EdltTemplateError):
                        _assignment_value('Application', row['value'])
                else:
                    self.assertEqual(_assignment_value('Application', row['value']),
                                     original['value'])

    def test_original_scalar_xml_values_and_checksum(self):
        row = next(row for row in CASES if row['id'] == 'xml-scalar-template')
        expected_crc = row['observations'][-1]['post_first_crc_checksum']
        # Only the literal dummy CRC marker is filled with the independently
        # observed original result. All ordered field values remain untouched.
        document = row['value'].replace('<CRC>0</CRC>', f'<CRC>{expected_crc}</CRC>', 1)
        result = EdltTemplate.from_xml(document.encode('utf-8'))
        expected_fields = tuple((item['name'], item['inner_xml'])
                                for item in row['observations'] if 'node_type' in item)
        expected_fields = tuple((name, str(expected_crc) if name == 'CRC' else value)
                                for name, value in expected_fields)
        self.assertEqual(result.fields, expected_fields)
        self.assertEqual(result.crc, 10852)
        self.assertEqual(result.payload[0], ('Application', '48 202'))
        self.assertEqual(EdltTemplate.from_xml(result.to_xml()).fields, expected_fields)

    def test_other_original_xml_vectors_have_explicit_safe_refusals(self):
        unsupported = {
            'xml-inner': 'entities, nested element, CDATA, comment and processing instruction',
            'xml-preserve': 'xml:space root attribute and significant whitespace',
            'xml-line-endings': 'multiline text and entity normalization',
            'xml-duplicate-headers': 'multiple and conflicting identity headers',
            'xml-entity-dtd': 'DTD and retained general entity reference',
            'xml-scalar-entities': 'entity normalization and multiline text',
            'xml-second-crc': 'more than one CRC marker',
        }
        rows = [row for row in CASES if row['kind'] == 'xml' and row['id'] != 'xml-scalar-template']
        self.assertEqual({row['id'] for row in rows}, set(unsupported))
        for row in rows:
            with self.subTest(case=row['id'], scope_restriction=unsupported[row['id']]):
                document = row['value']
                for item in row['observations']:
                    if 'post_first_crc_checksum' in item:
                        document = document.replace('<CRC>0</CRC>',
                                                    f"<CRC>{item['post_first_crc_checksum']}</CRC>", 1)
                with self.assertRaises(EdltTemplateError):
                    EdltTemplate.from_xml(document)


if __name__ == '__main__':
    unittest.main()
