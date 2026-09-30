"""eDLT-specific interchange, ordered previews and fail-before-I/O boundary."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt_templates import (
    EdltTemplate, EdltTemplateApplyRefused, EdltTemplateError,
    edlt_template_crc, export_edlt_template, preview_edlt_template,
)
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


def template(payload=(('Application', '48 202'), ('UnitName', 'TEST'), ('Value', '0x12')),
             before=()):
    return EdltTemplate((('UnitType', 'KEYGL5'), ('FirmwareVersion', '5.5.00')) + tuple(before)
                        + (('CRC', str(edlt_template_crc(value for _, value in payload))),) + tuple(payload))


def spec():
    parameters = {}
    for name, kind, count in (('Application', 'int', 2), ('Value', 'int', 1), ('UnitName', 'sixbit', 8)):
        parameters[name] = ParameterSpec(name, kind, 'synthetic', {
            'Type': kind, 'ArraySize': str(count), 'BitSize': '8', 'Address': '0',
            'MinValue': '0', 'MaxValue': '255'})
    return UnitSpec('KEYGL5.xml', {'Type': 'KEYGL5', 'MinVersion': '5.5.00', 'MaxVersion': '5.5.00'},
                    (), parameters)


class EdltTemplateCrcTests(unittest.TestCase):
    def test_original_managed_helper_known_answers(self):
        # Literal results from the pinned original PPHelper, not Python-derived.
        cases = (([], 65261), (['A'], 65261), (['ABC'], 2353),
                 (['0x30 0xca'], 53109), (['48 202'], 53109),
                 ([' 0x30 0xca'], 11695), (['😀Z'], 18221), (['=\0Z'], 18221))
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(edlt_template_crc(values), expected)

    def test_utf16_low_bytes_trimming_concatenation_and_last_byte(self):
        self.assertEqual(edlt_template_crc(['\u0141BC']), edlt_template_crc(['ABC']))
        self.assertEqual(edlt_template_crc(['A', 'BC']), edlt_template_crc(['AB', 'C']))
        self.assertEqual(edlt_template_crc(['ABx']), edlt_template_crc(['ABy']))
        self.assertEqual(edlt_template_crc(['\u0085ABC\u00a0']), edlt_template_crc(['ABC']))
        self.assertNotEqual(edlt_template_crc(['\u001cABC']), edlt_template_crc(['ABC']))
        self.assertNotEqual(edlt_template_crc(['\u200bABC']), edlt_template_crc(['ABC']))
        self.assertNotEqual(edlt_template_crc(['AB', 'CD']), edlt_template_crc(['CD', 'AB']))

    def test_hex_detection_precedes_trim_and_is_case_sensitive(self):
        self.assertNotEqual(edlt_template_crc(['0X30 0xca']), edlt_template_crc(['0x30 0xca']))
        self.assertEqual(edlt_template_crc(['0xffffffff 0x80000000']),
                         edlt_template_crc(['-1 -2147483648']))
        for value in ('0x30  0xca', '0x30 ', '0x30\t0xca', '0x', '0x100000000', '0x1 -2'):
            with self.subTest(value=value), self.assertRaises(EdltTemplateError):
                edlt_template_crc([value])

    def test_original_buffer_limit_counts_utf16_units(self):
        self.assertIsInstance(edlt_template_crc(['x' * 65536]), int)
        self.assertIsInstance(edlt_template_crc(['😀' * 32768]), int)
        for values in (['x' * 65537], ['😀' * 32769], {'A': 'B'}, 'ABC', [1]):
            with self.subTest(length=len(values)), self.assertRaises(EdltTemplateError):
                edlt_template_crc(values)

    def test_culture_sensitive_hex_prefixes_fail_closed(self):
        for value in ('0\u200dx30 0xca', '\0' + '0x30 0xca', '0\0x30 0xca',
                      '0\u200cx30', '\u00ad0x30', '0\u0301x30'):
            with self.subTest(value=value), self.assertRaisesRegex(EdltTemplateError, 'Culture-sensitive'):
                edlt_template_crc([value])


class EdltTemplateFormatTests(unittest.TestCase):
    def test_export_matches_source_order_exclusions_and_extra_identity_duplicates(self):
        attrs = [('UnitAddress', '7'), ('Application', '0xff 0xff'), ('Project', 'PRIVATE'),
                 ('NetworkAddress', '254'), ('UnitName', 'NOTUSED'), ('SerialNumber', 'PRIVATE'),
                 ('Value', '0x12'), ('FirmwareVersion', '5.5.00'), ('UnitType', 'KEYGL5'),
                 ('PrimaryApplication', '0x30'), ('SecondaryApplication', '0xca')]
        original = deepcopy(attrs)
        result = export_edlt_template(description='Demo é 😀', firmware='5.5.00', unit_name='TEST',
                                      primary_application=48, secondary_application=202, pp_attributes=attrs)
        self.assertEqual(attrs, original)
        self.assertEqual([name for name, _ in result.fields], [
            'Description', 'UnitType', 'FirmwareVersion', 'CRC', 'Application', 'FirmwareVersion',
            'UnitName', 'UnitType', 'Value', 'FirmwareVersion', 'UnitType',
            'PrimaryApplication', 'SecondaryApplication'])
        self.assertEqual(result.payload[0], ('Application', '48 202'))
        self.assertNotIn('PRIVATE', result.to_xml())
        self.assertEqual(EdltTemplate.from_xml(result.to_xml().encode()).fields, result.fields)
        self.assertFalse(result.as_dict()['apply_allowed'])

    def test_raw_whitespace_and_order_survive_roundtrip(self):
        result = template((('Value', ' 0x12 '), ('Value', '4'), ('UnitName', 'TEST ')))
        self.assertEqual(EdltTemplate.from_xml(result.to_xml()).fields, result.fields)
        self.assertEqual(result.payload[0][1], ' 0x12 ')
        self.assertEqual(len([n for n, _ in result.fields if n == 'Value']), 2)

    def test_before_crc_values_are_not_checksummed(self):
        result = template(before=(('Description', 'Demo'), ('Value', '13')))
        changed = result.to_xml().replace('<Value>13</Value>', '<Value>14</Value>')
        parsed = EdltTemplate.from_xml(changed)
        self.assertEqual(parsed.crc, result.crc)
        preview = preview_edlt_template(parsed, pp_attribute_names=['Value'])
        self.assertEqual([value for _, _, value in preview.assignments], ['14', '0x12'])

    def test_checksum_and_identity_validation_fail_before_preview(self):
        xml = template().to_xml()
        bad = (
            xml.replace('0x12', '0x22'), xml.replace('KEYGL5', 'KEYGL4'),
            xml.replace('<FirmwareVersion>5.5.00</FirmwareVersion>', '<FirmwareVersion/>'),
            xml.replace('<CRC>', '<CRC>+'), xml.replace('</UnitTemplate>', '<CRC>1</CRC></UnitTemplate>'),
            xml.replace('</UnitTemplate>', '<UnitType>KEYGL4</UnitType></UnitTemplate>'),
            xml.replace('<CRC>', '<UnitType>KEYGL5</UnitType><CRC>'),
        )
        for document in bad:
            with self.subTest(document=document), self.assertRaises(EdltTemplateError):
                EdltTemplate.from_xml(document)

    def test_incomplete_or_degenerate_format_is_not_apply_acceptance(self):
        result = template(())
        preview = preview_edlt_template(result, pp_attribute_names=[])
        self.assertEqual(preview.assignments, ())
        self.assertFalse(preview.as_dict()['apply_allowed'])
        self.assertFalse(preview.as_dict()['post_reset_values_known'])
        with self.assertRaises(EdltTemplateError):
            EdltTemplate((('UnitType', 'KEYGL5'), ('FirmwareVersion', '5.5.00')))

    def test_entities_nested_xml_attributes_and_other_unproven_xml_refused(self):
        xml = template().to_xml()
        bad = (
            xml.replace('TEST', 'A&amp;B'), xml.replace('TEST', '&#65;'),
            xml.replace('TEST', '<b>TEST</b>'), xml.replace('TEST', '<![CDATA[TEST]]>'),
            xml.replace('<UnitName>', '<UnitName id="1">'),
            xml.replace('<UnitTemplate>', '<UnitTemplate xmlns="x">'),
            xml.replace('<UnitTemplate>', '<UnitTemplate><!--comment-->'),
            xml.replace('TEST', 'A>B'), xml.replace('TEST', '  '), xml.replace('TEST', 'A\nB'),
            xml.replace('<UnitTemplate>', '<!DOCTYPE UnitTemplate><UnitTemplate>'),
            xml.replace('<UnitTemplate>', '<?custom test?><UnitTemplate>'),
            xml.replace('utf-8', 'utf-16'), xml.replace('TEST', '\ud800'),
            xml.replace('version="1.0"', 'version="1.1"'),
            xml.replace('version="1.0"', 'version="2.0"'),
            xml.replace('version="1.0"', 'version="1.00"'),
            xml.replace('<UnitTemplate>', '<UnitTemplate>\u0085'),
            xml.replace('</UnitName>', '</UnitName>\u0085'),
        )
        for document in bad:
            with self.subTest(document=repr(document)), self.assertRaises(EdltTemplateError):
                EdltTemplate.from_xml(document)

    def test_export_rejects_ambiguous_collections_and_non_byte_applications(self):
        args = dict(description='Demo', firmware='5.5.00', unit_name='TEST',
                    primary_application=48, secondary_application=202, pp_attributes=[])
        for change in ({'pp_attributes': {'Value': '1'}}, {'pp_attributes': [('Value', '1'), ('Value', '2')]},
                       {'pp_attributes': [('CRC', '1')]}, {'primary_application': True},
                       {'secondary_application': 256}, {'description': '<escaped>'}):
            with self.subTest(change=change), self.assertRaises(EdltTemplateError):
                export_edlt_template(**(args | change))

    def test_constructor_copies_mutable_rows_and_enforces_size(self):
        rows = [list(row) for row in template().fields]
        result = EdltTemplate(rows)
        rows[-1][1] = '0x99'
        self.assertEqual(result.payload[-1], ('Value', '0x12'))
        for document in (b'x' * (1024 * 1024 + 1), 12, b'\xff'):
            with self.assertRaises(EdltTemplateError):
                EdltTemplate.from_xml(document)


class EdltTemplatePreviewTests(unittest.TestCase):
    def test_candidate_order_includes_pre_crc_and_duplicate_pp_fields(self):
        result = template((('Application', '48 202'), ('Value', '2'), ('Value', '3'),
                           ('UnitAddress', '9')), before=(('Value', '1'),))
        preview = preview_edlt_template(result, pp_attribute_names=['UnitAddress', 'Value', 'Application'])
        self.assertEqual([(n, v) for _, n, v in preview.assignments],
                         [('Value', '1'), ('Application', '0x30 0xca'), ('Value', '2'),
                          ('Value', '3'), ('UnitAddress', '9')])
        self.assertEqual(len(preview.warnings), 3)
        self.assertFalse(preview.as_dict()['schema_checked'])

    def test_schema_validation_is_local_only_and_never_infers_final_state(self):
        preview = preview_edlt_template(template(), pp_attribute_names=['Application', 'UnitName', 'Value'],
                                        spec=spec(), target_firmware='5.5.00')
        self.assertFalse(preview.validation_errors)
        report = preview.as_dict()
        self.assertTrue(report['input_validated'])
        self.assertTrue(report['schema_checked'])
        self.assertFalse(report['raw_setter_validated'])
        self.assertEqual(report['validation_scope'], 'individual-local-schema-only')
        for flag in ('apply_allowed', 'parent_lifecycle_executed', 'post_reset_values_known',
                     'mutation_attempted', 'saved', 'native_template_workflow_verified'):
            self.assertFalse(report[flag])
        self.assertNotIn('changes', report)
        self.assertNotIn('after_reset', report)

    def test_schema_rejects_unknown_overflow_and_partial_array(self):
        result = template((('Value', '256'), ('Application', '48'), ('Unproved', '2')))
        preview = preview_edlt_template(result, pp_attribute_names=['Value', 'Application', 'Unproved'],
                                        spec=spec(), target_firmware='6.0.00')
        self.assertEqual(len(preview.validation_errors), 5)
        self.assertFalse(preview.as_dict()['input_validated'])
        self.assertTrue(any('firmware differ' in warning for warning in preview.warnings))

    def test_application_conversion_happens_even_if_attribute_is_absent(self):
        for value in ('48  202', ' 48 202', '48 202 ', '0x30 0xca', '2147483648', '48\t202'):
            with self.subTest(value=value):
                result = template((('Application', value),))
                preview = preview_edlt_template(result, pp_attribute_names=[])
                self.assertTrue(preview.validation_errors)
                self.assertEqual(preview.assignments, ())
        empty = preview_edlt_template(template((('Application', ''),)), pp_attribute_names=['Application'])
        self.assertEqual(empty.assignments[0][2], '')
        negative = preview_edlt_template(template((('Application', '-1 +48'),)),
                                         pp_attribute_names=['Application'])
        self.assertEqual(negative.assignments[0][2], '0xffffffff 0x30')

    def test_no_session_callback_or_network_on_success_or_failure_or_apply(self):
        class PoisonTarget:
            def __getattribute__(self, name):
                raise AssertionError('Target touched: ' + name)
        with patch('socket.create_connection', side_effect=AssertionError('Network touched')):
            for result in (template(), template((('Application', '48  202'),))):
                preview = preview_edlt_template(result, pp_attribute_names=['Application', 'Value'])
                with self.assertRaises(EdltTemplateApplyRefused) as caught:
                    preview.apply(PoisonTarget())
                self.assertFalse(caught.exception.details['mutation_attempted'])
                self.assertFalse(caught.exception.details['saved'])
                self.assertTrue(caught.exception.details['blockers'])

    def test_huge_numeric_text_does_not_escape_structured_validation(self):
        result = template((('Application', '0' * 5000 + '48 202'), ('Value', '0' * 5000 + '1')))
        preview = preview_edlt_template(result, pp_attribute_names=['Application', 'Value'], spec=spec())
        self.assertEqual(preview.assignments[0][2], '0x30 0xca')
        self.assertEqual(len(preview.validation_errors), 1)
        self.assertIn('local schema validation failed', preview.validation_errors[0])
        result = template((('Application', '1' * 5000),))
        preview = preview_edlt_template(result, pp_attribute_names=['Application'])
        self.assertFalse(preview.as_dict()['input_validated'])

    def test_membership_and_spec_identity_are_explicit(self):
        for names in ('Value', {'Value': '1'}, ['Value', 'Value'], ['x:y'], [1]):
            with self.subTest(names=names), self.assertRaises(EdltTemplateError):
                preview_edlt_template(template(), pp_attribute_names=names)
        with self.assertRaises(EdltTemplateError):
            preview_edlt_template(template(), pp_attribute_names=[], spec=replace(spec(), metadata={'Type': 'KEY4'}))


if __name__ == '__main__':
    unittest.main()
