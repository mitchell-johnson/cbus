"""Source-pinned four/eight-channel DIN output CSV report profiles."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from cbus_toolkit import cli
from cbus_toolkit.toolkit_database_csv import COLUMNS
from cbus_toolkit.toolkit_database_csv_native import (
    project_native_xml_selection,
    project_native_xml_unit,
)
from cbus_toolkit.toolkit_database_csv_projection import (
    CSVAreaObservation,
    project_cached_csv_unit,
)
from tests.test_cgate import peer


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/toolkit-database-csv-din4-rel4-rel8-synthetic.xml'
REVIEW = ROOT / 'research/experiments/2026-09-28/csv-din4-rel4-rel8-profile-review.json'
VENDOR = Path('/private/tmp/cbus-toolkit-installer-audit/extracted-20260926/app')
HEADER = ('Unit Address,Part Name,Tag Name,Unit Type,Catalog Number,Serial Number,'
          'Firmware Version,Primary Application,Secondary Application,Area,'
          + ''.join(f'Group {number},' for number in range(1, 17)))
PREFIX = 'DIN Four/Eight Synthetic'
ROWS = (
    '4,' + PREFIX + ',Four dimmer,DIMDN4,SYNTHETIC,No serial #,2.7.00,Lighting,,<Unused>,'
    + 'Circuit 08,"Kitchen, east",Circuit 08,Circuit 04,' + '<N/A>,' * 12,
    '5,' + PREFIX + ',Four frost,DIMDN4F,SYNTHETIC,No serial #,2.7.00,Lighting,,<Unused>,'
    + 'Circuit 04,Circuit 03,Circuit 02,"Kitchen, east",' + '<N/A>,' * 12,
    '6,' + PREFIX + ',Four relay,RELDN4,SYNTHETIC,No serial #,2.7.00,Lighting,,<Unused>,'
    + '"Kitchen, east",Circuit 02,Circuit 03,Circuit 04,' + '<N/A>,' * 12,
    '7,' + PREFIX + ',Eight relay,RELDN8,SYNTHETIC,No serial #,2.7.00,Lighting,,<Unused>,'
    + ','.join(f'Circuit {number:02d}' for number in range(16, 8, -1)) + ','
    + '<N/A>,' * 8,
)
CSV_BYTES = ('\r\n'.join((HEADER, *ROWS)) + '\r\n\r\n').encode()
CLASSES = ('TDIMDN4', 'TDIMDN4F', 'TRELDN4', 'TRELDN8')


def synthetic():
    return FIXTURE.read_text(encoding='utf-8')


def edited(kind, change):
    root = ET.fromstring(synthetic())
    unit = next(row for row in root.iter('Unit') if row.findtext('UnitType') == kind)
    change(root, unit)
    return ET.tostring(root, encoding='unicode')


def parameter(unit, name):
    return next(node for node in unit.findall('PP') if node.get('Name') == name)


class DINFourEightCSVTests(unittest.TestCase):
    def test_original_source_review_pins_all_four_classes_and_fixture(self):
        review = json.loads(REVIEW.read_text(encoding='utf-8'))
        self.assertFalse(review['original_execution'])
        self.assertEqual([row['selected_class'] for row in review['registrations']],
                         list(CLASSES))
        self.assertEqual([row['max_channels'] for row in review['registrations']],
                         [4, 4, 4, 8])
        self.assertEqual([row['firmware_min'] for row in review['registrations']],
                         ['0'] * 4)
        self.assertEqual([row['firmware_max'] for row in review['registrations']],
                         ['9'] * 4)
        self.assertTrue(review['unit_vmt']['dimdn4f_report_slots_match_dimdn4'])
        self.assertEqual(review['synthetic_fixture']['sha256'],
                         hashlib.sha256(FIXTURE.read_bytes()).hexdigest())

    @unittest.skipUnless((VENDOR / 'CBusToolkit.exe').exists()
                         and (VENDOR / 'CBusToolkit.map').exists(),
                         'Pinned original Toolkit EXE/MAP not provisioned')
    def test_fresh_original_exe_map_review_matches_committed_receipt(self):
        from research.csv_din4_rel4_rel8_profile_review import source_review
        actual = source_review(VENDOR / 'CBusToolkit.exe',
                               VENDOR / 'CBusToolkit.map', FIXTURE)
        self.assertEqual(actual, json.loads(REVIEW.read_text(encoding='utf-8')))

    def test_native_and_cached_project_all_sixteen_stored_associations(self):
        for address, selected_class, expected in zip(range(4, 8), CLASSES, ROWS):
            with self.subTest(selected_class=selected_class):
                native = project_native_xml_unit(synthetic(),
                    f'//CSVTEST/254/p/{address}', columns=COLUMNS)
                self.assertTrue(native.complete)
                self.assertEqual(native.cached.selected_class, selected_class)
                self.assertEqual(native.report.rows, (HEADER, expected))
                self.assertEqual(len(native.cached.unit.group_identities), 16)
                self.assertEqual(native.cached.raw_area, '255')
                self.assertFalse(native.as_dict()['native_database_mutated'])
                cached = project_cached_csv_unit(native.cached.unit,
                    group_cache=tuple(replace(group, references=())
                                      for group in native.cached.groups),
                    area_observations=(CSVAreaObservation('255'),
                                       CSVAreaObservation('255')),
                    columns=COLUMNS)
                self.assertEqual(cached.rows, (HEADER, expected))

    def test_whole_project_sorts_four_units_and_cli_writes_exact_bytes(self):
        result = project_native_xml_selection(synthetic(), project_path='//CSVTEST',
                                              columns=COLUMNS)
        self.assertEqual(result.report.rows, (HEADER, *ROWS))
        self.assertEqual(result.unit_paths,
            tuple(f'//CSVTEST/254/p/{address}' for address in range(4, 8)))
        # The fixture deliberately puts the four Units in descending XML order.
        self.assertEqual([unit.findtext('Address') for unit in ET.fromstring(synthetic()).iter('Unit')],
                         ['7', '6', '5', '4'])
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'synthetic.xml'
            source.write_text(synthetic(), encoding='utf-8')
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            for mode, value, expected in (
                ('--native-xml-project', '//CSVTEST', CSV_BYTES),
                ('--native-xml-unit', '//CSVTEST/254/p/4',
                 (HEADER + '\r\n' + ROWS[0] + '\r\n\r\n').encode()),
            ):
                with self.subTest(mode=mode):
                    output = Path(folder) / (mode + '.csv')
                    out, err = io.StringIO(), io.StringIO()
                    with (redirect_stdout(out), redirect_stderr(err),
                          patch('socket.socket', side_effect=AssertionError('No network'))):
                        code = cli.main(['toolkit-database-csv', str(source),
                                         '--output', str(output), mode, value])
                    self.assertEqual(code, 0, err.getvalue())
                    self.assertEqual(output.read_bytes(), expected)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_live_export_reads_one_snapshot_and_stays_read_only(self):
        response = (b'[1] 343-Begin XML snippet\r\n[1] 347-'
                    + synthetic().replace('\n', '').encode()
                    + b'\r\n[1] 344 End XML snippet\r\n')
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'live.csv'
            with peer([[response]]) as ((host, port), sent):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = cli.main(['cgate', '--host', host, '--port', str(port),
                                     'database-csv', '--project', '//CSVTEST',
                                     '--output', str(output)])
            self.assertEqual(code, 0, err.getvalue())
            report = json.loads(out.getvalue())
            self.assertFalse(report['physical_device_accessed'])
            self.assertFalse(report['native_database_mutated'])
            self.assertEqual(sent, [b'[1] DBGETXML //CSVTEST\r\n'])
            self.assertEqual(output.read_bytes(), CSV_BYTES)

    def test_unsupported_profile_rejects_before_output_creation(self):
        def firmware(_, unit): unit.find('FirmwareVersion').text = '2.8.00'
        def variant(_, unit): unit.find('UnitType').text = 'RELDN8B'
        def secondary(_, unit): parameter(unit, 'Application').set('Value', '56 57')
        def area(_, unit): parameter(unit, 'AreaGroupAddress').set('Value', '13')
        def short(_, unit): parameter(unit, 'GroupAddress').set('Value', '8 1 8 4')
        def duplicate(_, unit): unit.append(ET.Element('PP', Name='GroupAddress', Value='8'))
        def missing(root, _):
            application = root.find('./Project/Network/Application')
            application.remove(next(group for group in application.findall('Group')
                                    if group.findtext('Address') == '8'))

        for name, kind, change in (
            ('firmware', 'DIMDN4', firmware), ('variant', 'RELDN8', variant),
            ('secondary', 'DIMDN4F', secondary), ('Area13', 'RELDN4', area),
            ('short group array', 'RELDN8', short),
            ('duplicate PP', 'DIMDN4', duplicate), ('missing group', 'RELDN8', missing),
        ):
            with self.subTest(name=name):
                text = edited(kind, change)
                with self.assertRaises(ValueError):
                    project_native_xml_selection(text, project_path='//CSVTEST',
                                                 columns=COLUMNS)
                with tempfile.TemporaryDirectory() as folder:
                    source, output = Path(folder) / 'in.xml', Path(folder) / 'out.csv'
                    source.write_text(text, encoding='utf-8')
                    out, err = io.StringIO(), io.StringIO()
                    with (redirect_stdout(out), redirect_stderr(err),
                          patch('socket.socket', side_effect=AssertionError('No network'))):
                        code = cli.main(['toolkit-database-csv', str(source),
                                         '--output', str(output),
                                         '--native-xml-project', '//CSVTEST'])
                    self.assertEqual(code, 1)
                    self.assertFalse(output.exists())
                    self.assertFalse(json.loads(err.getvalue())[
                        'toolkit_database_csv_evidence']['output_create_attempted'])

    def test_cached_profile_requires_sixteen_stored_groups(self):
        native = project_native_xml_unit(synthetic(), '//CSVTEST/254/p/4',
                                         columns=COLUMNS)
        unit = replace(native.cached.unit,
                       group_identities=native.cached.unit.group_identities[:-1])
        with self.assertRaisesRegex(ValueError, 'exactly sixteen'):
            project_cached_csv_unit(unit, group_cache=native.cached.groups,
                area_observations=(CSVAreaObservation('255'),
                                   CSVAreaObservation('255')), columns=COLUMNS)


if __name__ == '__main__':
    unittest.main()
