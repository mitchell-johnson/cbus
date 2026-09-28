"""Source-pinned DIMDN8F DIN output report associations."""
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
FIXTURE = ROOT / 'research/fixtures/toolkit-database-csv-dimdn8f-synthetic.xml'
REVIEW = ROOT / 'research/experiments/2026-09-28/csv-dimdn8f-profile-review.json'
UNIT = '//CSVTEST/254/p/4'
HEADER = ('Unit Address,Part Name,Tag Name,Unit Type,Catalog Number,Serial Number,'
          'Firmware Version,Primary Application,Secondary Application,Area,'
          + ''.join(f'Group {number},' for number in range(1, 17)))
ROW = ('4,DIN Frost Synthetic,Frost dimmer,DIMDN8F,SYNTHETIC,No serial #,'
       '2.7.00,Lighting,,<Unused>,Circuit 08,"Kitchen, east",Circuit 08,'
       'Circuit 04,Circuit 03,Circuit 02,Circuit 07,Circuit 06,'
       + '<N/A>,' * 8)
CSV_BYTES = (HEADER + '\r\n' + ROW + '\r\n\r\n').encode()
RELAY_ROW = ('2,Relay Synthetic,Relay companion,RELAY4,SYNTHETIC,No serial #,'
             '4.4,Lighting,,<Unused>,"Kitchen, east",Circuit 02,Circuit 03,'
             'Circuit 04,Circuit 05,Circuit 06,' + '<N/A>,' * 10)


def synthetic():
    return FIXTURE.read_text(encoding='utf-8')


def edited(change):
    root = ET.fromstring(synthetic())
    change(root)
    return ET.tostring(root, encoding='unicode')


def parameter(root, name):
    return next(node for node in root.iter('PP') if node.get('Name') == name)


def project_with_relay(*, address=2, kind='RELAY4'):
    root = ET.fromstring(synthetic())
    unit = ET.SubElement(root.find('./Project/Network'), 'Unit')
    for name, value in (('Address', str(address)), ('UnitType', kind),
                        ('UnitName', 'Relay Synthetic'),
                        ('TagName', 'Relay companion'),
                        ('CatalogNumber', 'SYNTHETIC'),
                        ('SerialNumber', 'No serial #'),
                        ('FirmwareVersion', '4.4')):
        ET.SubElement(unit, name).text = value
    for name, value in (('Application', '56 255'),
                        ('AreaGroupAddress', '255'),
                        ('GroupAddress', '1 2 3 4 5 6 7 8 ' + '255 ' * 7 + '255')):
        ET.SubElement(unit, 'PP', Name=name, Value=value)
    return ET.tostring(root, encoding='unicode')


class DIMDN8FCSVTests(unittest.TestCase):
    def test_original_source_review_pins_class_agent_and_fixture(self):
        review = json.loads(REVIEW.read_text(encoding='utf-8'))
        self.assertFalse(review['original_execution'])
        self.assertEqual(review['registration']['selected_class'], 'TDIMDN8F')
        self.assertEqual(review['registration']['agent_class'], 'TDinRailOutputCGateAgent')
        self.assertTrue(review['unit_vmt']['report_slots_match_dimdn8'])
        self.assertEqual(review['unit_vmt']['max_channels'], '0x12298b0')
        self.assertEqual(review['synthetic_fixture']['sha256'],
                         hashlib.sha256(FIXTURE.read_bytes()).hexdigest())

    def test_native_and_cached_projection_keep_sixteen_associations(self):
        outcome = project_native_xml_unit(synthetic(), UNIT, columns=COLUMNS)
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.cached.selected_class, 'TDIMDN8F')
        self.assertEqual(outcome.report.rows, (HEADER, ROW))
        self.assertEqual(len(outcome.cached.unit.group_identities), 16)
        self.assertEqual(outcome.cached.unit.group_identities[0],
                         outcome.cached.unit.group_identities[2])
        self.assertNotEqual(outcome.cached.unit.group_identities[8],
                            outcome.cached.unit.group_identities[9])
        self.assertEqual(outcome.cached.raw_area, '255')
        self.assertFalse(outcome.as_dict()['native_database_mutated'])
        cached = project_cached_csv_unit(outcome.cached.unit,
            group_cache=tuple(replace(group, references=())
                              for group in outcome.cached.groups),
            area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
            columns=COLUMNS)
        self.assertEqual(cached.rows, (HEADER, ROW))

    def test_offline_unit_and_whole_project_emit_exact_bytes_without_network(self):
        selection = project_native_xml_selection(synthetic(), project_path='//CSVTEST',
                                                 columns=COLUMNS)
        self.assertEqual(selection.report.rows, (HEADER, ROW))
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'synthetic.xml'
            source.write_text(synthetic(), encoding='utf-8')
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            for mode, value in (('--native-xml-unit', UNIT),
                                ('--native-xml-project', '//CSVTEST')):
                with self.subTest(mode=mode):
                    output = Path(folder) / (mode + '.csv')
                    out, err = io.StringIO(), io.StringIO()
                    with (redirect_stdout(out), redirect_stderr(err),
                          patch('socket.socket', side_effect=AssertionError('No network'))):
                        code = cli.main(['toolkit-database-csv', str(source),
                                         '--output', str(output), mode, value])
                    self.assertEqual(code, 0, err.getvalue())
                    self.assertEqual(output.read_bytes(), CSV_BYTES)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_whole_project_composes_original_unit_order_and_rejects_later_failure(self):
        text = project_with_relay()
        outcome = project_native_xml_selection(text, project_path='//CSVTEST',
                                               columns=COLUMNS)
        self.assertEqual(outcome.report.rows, (HEADER, RELAY_ROW, ROW))
        self.assertEqual(outcome.unit_paths, ('//CSVTEST/254/p/2', UNIT))
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'mixed.xml', Path(folder) / 'mixed.csv'
            source.write_text(text, encoding='utf-8')
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(['toolkit-database-csv', str(source), '--output',
                                 str(output), '--native-xml-project', '//CSVTEST'])
            self.assertEqual(code, 0, err.getvalue())
            self.assertEqual(output.read_bytes(),
                             (HEADER + '\r\n' + RELAY_ROW + '\r\n' + ROW + '\r\n\r\n').encode())
        # The valid DIN row projects first, but a later unsupported unit must
        # prevent creating any report rather than leaving a partial file.
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'mixed.xml', Path(folder) / 'mixed.csv'
            source.write_text(project_with_relay(address=9, kind='UNKNOWN'), encoding='utf-8')
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(['toolkit-database-csv', str(source), '--output',
                                 str(output), '--native-xml-project', '//CSVTEST'])
            self.assertEqual(code, 1)
            self.assertFalse(output.exists())
            self.assertFalse(json.loads(err.getvalue())[
                'toolkit_database_csv_evidence']['output_create_attempted'])

    def test_live_export_reads_one_snapshot_without_physical_access(self):
        xml_line = synthetic().replace('\n', '')
        response = (b'[1] 343-Begin XML snippet\r\n[1] 347-'
                    + xml_line.encode() + b'\r\n[1] 344 End XML snippet\r\n')
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
            self.assertEqual(report['database_command'], 'DBGETXML //CSVTEST')
            self.assertFalse(report['physical_device_accessed'])
            self.assertFalse(report['native_database_mutated'])
            self.assertEqual(sent, [b'[1] DBGETXML //CSVTEST\r\n'])
            self.assertEqual(output.read_bytes(), CSV_BYTES)

    def test_unsupported_or_incomplete_native_profiles_reject_atomically(self):
        def wrong_firmware(root):
            root.find('.//Unit/FirmwareVersion').text = '2.8.00'

        def wrong_type(root):
            root.find('.//Unit/UnitType').text = 'DIMDN8X'

        def secondary_application(root):
            parameter(root, 'Application').set('Value', '56 57')

        def different_area(root):
            parameter(root, 'AreaGroupAddress').set('Value', '13')

        def missing_group(root):
            app = root.find('.//Application')
            app.remove(next(group for group in app.findall('Group')
                            if group.findtext('Address') == '8'))

        def missing_area(root):
            app = root.find('.//Application')
            app.remove(next(group for group in app.findall('Group')
                            if group.findtext('Address') == '255'))

        def short_slots(root):
            parameter(root, 'GroupAddress').set('Value', '8 1 8 4 3 2 7 6')

        def duplicate_pp(root):
            root.find('.//Unit').append(ET.Element('PP', Name='GroupAddress', Value='8'))

        for name, change in (
            ('firmware', wrong_firmware), ('type', wrong_type),
            ('secondary', secondary_application), ('Area13', different_area),
            ('missing selected group', missing_group), ('missing Area255', missing_area),
            ('short group array', short_slots), ('duplicate PP', duplicate_pp),
        ):
            with self.subTest(name=name):
                text = edited(change)
                with self.assertRaises(ValueError):
                    project_native_xml_unit(text, UNIT, columns=COLUMNS)
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

    def test_cached_profile_rejects_fifteen_stored_groups(self):
        outcome = project_native_xml_unit(synthetic(), UNIT, columns=COLUMNS)
        unit = replace(outcome.cached.unit,
                       group_identities=outcome.cached.unit.group_identities[:-1])
        with self.assertRaisesRegex(ValueError, 'exactly sixteen|16|group'):
            project_cached_csv_unit(unit, group_cache=outcome.cached.groups,
                area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
                columns=COLUMNS)


if __name__ == '__main__':
    unittest.main()
