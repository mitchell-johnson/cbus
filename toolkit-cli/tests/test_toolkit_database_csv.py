import copy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.toolkit_database_csv import (
    CAPTURE_FORMAT, COLUMNS, COLUMN_LABELS, CSVGroupValue, CSVUnitValues,
    MAX_CAPTURE_BYTES, document_database_csv, loads_capture, parse_capture,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/toolkit-database-csv-original-vectors.json'


def unit(**changes):
    values = dict(address=7, part_name='KEYGL5', tag_name='Living', unit_type='KEYGL5',
                  catalog='5055EDL', serial='1.2', firmware='5.00', primary='Lighting',
                  secondary='', area=None, groups=())
    values.update(changes)
    return CSVUnitValues(**values)


def captured(*units):
    return {'format': CAPTURE_FORMAT, 'units': [item.as_dict() for item in units]}


def original_unit(value):
    return CSVUnitValues(**{k: v for k, v in value.items() if k != 'groups'},
                        groups=tuple(CSVGroupValue(item['tag'], item['used']) for item in value['groups']))


class DatabaseCSVTests(unittest.TestCase):
    def test_seventy_original_row_vectors_all_columns_and_original_unit_order(self):
        fixture = json.loads(FIXTURE.read_text())
        count = 0
        for vector in fixture['vectors']:
            case = vector['input']
            if case['kind'] != 'rows' or not 0 < case['mask'] < (1 << 26):
                continue
            with self.subTest(case=case['id']):
                columns = tuple(name for i, name in enumerate(COLUMNS) if case['mask'] & (1 << i))
                report = document_database_csv(tuple(original_unit(v) for v in case['units']), columns=columns[::-1])
                self.assertEqual(list(report.rows), vector['output'])
                self.assertEqual(report.utf8_bytes, ('\r\n'.join(vector['output']) + '\r\n\r\n').encode())
                count += 1
        self.assertEqual(count, 70)

    def test_thirteen_original_quote_vectors_keep_comma_only_quoting(self):
        count = 0
        for vector in json.loads(FIXTURE.read_text())['vectors']:
            case = vector['input']
            if case['kind'] != 'quote' or '\0' in case['text']:
                continue
            with self.subTest(case=case['id']):
                report = document_database_csv((unit(tag_name=case['text']),), columns=('tag_name',))
                self.assertEqual(report.rows[1], vector['output'] + ',')
                count += 1
        self.assertEqual(count, 13)

    def test_missing_groups_are_deferred_and_are_not_padded_in_place(self):
        source = unit(groups=(CSVGroupValue('missing', False), CSVGroupValue('Second', True)))
        report = document_database_csv((source,), columns=('group_1', 'group_2', 'group_16'))
        self.assertEqual(report.rows, ('Group 1,Group 2,Group 16,', 'Second,<N/A>,<N/A>,'))
        self.assertEqual(report.as_dict()['encoding'], 'utf-8')
        self.assertFalse(report.as_dict()['database_projection_verified'])
        self.assertFalse(report.as_dict()['native_codepage_verified'])

    def test_explicit_columns_required_unknown_duplicate_types_rejected(self):
        with self.assertRaises(TypeError): document_database_csv(())
        for columns in ((), [], ['address'], ('all',), ('Address',), ('address', 'address'), (True,)):
            with self.subTest(columns=columns), self.assertRaises(ValueError):
                document_database_csv((), columns=columns)
        for units in ([], None, (None,), (unit(),) * 4097):
            with self.assertRaises(ValueError): document_database_csv(units, columns=('address',))

    def test_strict_units_unicode_bounds_and_mutated_frozen_objects(self):
        for changes in ({'address': True}, {'address': -1}, {'address': 256}, {'tag_name': None},
                        {'tag_name': '\0'}, {'tag_name': '\ud800'}, {'tag_name': 'x' * 257},
                        {'tag_name': '\U0001f4a1' * 129}, {'groups': []},
                        {'groups': (CSVGroupValue('x', True),) * 17}):
            with self.subTest(changes=repr(changes)[:80]), self.assertRaises(ValueError): unit(**changes)
        self.assertEqual(len(unit(tag_name='\U0001f4a1' * 128).tag_name), 128)
        with self.assertRaises(ValueError): CSVGroupValue('x', 1)
        class Child(CSVUnitValues): pass
        with self.assertRaises(ValueError): Child(**{**unit().as_dict(), 'groups': ()})
        value = unit(); object.__setattr__(value, 'address', False)
        with self.assertRaises(ValueError): document_database_csv((value,), columns=('address',))
        group = CSVGroupValue('x', True); source = unit(groups=(group,))
        object.__setattr__(group, 'interaction', 1)
        with self.assertRaises(ValueError): document_database_csv((source,), columns=('group_1',))

    def test_capture_is_exact_detached_and_does_not_project_project_xml(self):
        source = captured(unit(groups=(CSVGroupValue('First', True),)))
        parsed = parse_capture(source)
        source['units'][0]['groups'][0]['tag'] = 'Changed'
        self.assertEqual(parsed[0].groups[0].tag, 'First')
        exported = parsed[0].as_dict(); exported['groups'].clear()
        self.assertEqual(len(parsed[0].groups), 1)
        for invalid in ({}, [], {'format': CAPTURE_FORMAT, 'units': [], 'project': 'x'},
                        {'format': CAPTURE_FORMAT, 'units': ()}, {'format': 1, 'units': []}):
            with self.assertRaises(ValueError): parse_capture(invalid)
        for name in unit().as_dict():
            invalid = captured(unit()); invalid['units'][0].pop(name)
            with self.assertRaises(ValueError): parse_capture(invalid)
        with self.assertRaises(ValueError): loads_capture(b'<Project/>')

    def test_strict_json_rejects_duplicate_unknown_numeric_depth_and_encoding(self):
        good = json.dumps(captured(unit())).encode()
        self.assertEqual(loads_capture(good), (unit(),))
        invalid = (b'', bytearray(good), b'\xff', good + b'{}',
                   b'{"format":"x","format":"y","units":[]}',
                   good.replace(b'"address": 7', b'"address": 7.0'),
                   good.replace(b'"address": 7', b'"address": NaN'),
                   good.replace(b'"address": 7', b'"address": 99999999999999999999'),
                   good.replace(b'"tag_name": "Living"', b'"tag_name": "\\ud800"'),
                   b'[' * 6 + b']' * 6, b' ' * (MAX_CAPTURE_BYTES + 1))
        for data in invalid:
            with self.subTest(data=repr(data[:40])), self.assertRaises(ValueError): loads_capture(data)
        for group in ({'tag': 'x'}, {'tag': 'x', 'used': True}, {'tag': 'x', 'interaction': 1}):
            bad = captured(unit()); bad['units'][0]['groups'] = [group]
            with self.assertRaises(ValueError): parse_capture(bad)

    def test_output_bound_is_enforced_before_exposing_report(self):
        with patch('cbus_toolkit.toolkit_database_csv.MAX_OUTPUT_BYTES', 32):
            with self.assertRaises(ValueError):
                document_database_csv((unit(tag_name='x' * 40),), columns=('tag_name',))


if __name__ == '__main__': unittest.main()
