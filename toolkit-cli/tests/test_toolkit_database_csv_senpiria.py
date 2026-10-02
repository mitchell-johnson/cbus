"""Source-pinned SENPIRIA sensor CSV group/Area associations."""
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
FIXTURE = ROOT / 'research/fixtures/toolkit-database-csv-senpiria-synthetic.xml'
REVIEW = ROOT / 'research/experiments/2026-09-28/csv-senpiria-profile-review.json'
UNIT = '//CSVTEST/254/p/4'
HEADER = ('Unit Address,Part Name,Tag Name,Unit Type,Catalog Number,Serial Number,'
          'Firmware Version,Primary Application,Secondary Application,Area,'
          + ''.join(f'Group {number},' for number in range(1, 17)))
ROW = ('4,Sensor Synthetic,Synthetic Sensor,SENPIRIA,5751L,No serial #,2.4.00,'
       'Lighting,Secondary,<Unused>,S1,P2,S3,P4,S5,P6,S7,P8,'
       + '<N/A>,' * 8)


def synthetic():
    return FIXTURE.read_text()


def edited(change):
    root = ET.fromstring(synthetic())
    change(root)
    return ET.tostring(root, encoding='unicode')


def parameter(root, name):
    return next(node for node in root.iter('PP') if node.get('Name') == name)


class SENPIRIACSVTests(unittest.TestCase):
    def test_original_source_receipt_pins_synthetic_profile(self):
        review = json.loads(REVIEW.read_text())
        self.assertFalse(review['original_execution'])
        self.assertEqual(review['registration']['selected_class'], 'TST7SENPIRSS')
        self.assertEqual(review['synthetic_fixture']['sha256'], hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
        self.assertEqual(review['agent_vmt']['load_unit_group_addresses'], '0xcecbbc')

    def test_native_and_cached_projection_preserve_cross_application_groups(self):
        outcome = project_native_xml_unit(synthetic(), UNIT, columns=COLUMNS)
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.cached.selected_class, 'TST7SENPIRSS')
        self.assertEqual(outcome.report.rows, (HEADER, ROW))
        self.assertEqual(outcome.cached.unit.secondary, 'Secondary')
        self.assertEqual(len(outcome.cached.unit.group_identities), 8)
        self.assertEqual(outcome.cached.unit.group_identities[:2],
                         ('00000000-0000-0000-0000-000000000201',
                          '00000000-0000-0000-0000-000000000102'))
        self.assertEqual(outcome.cached.raw_area, '255')
        self.assertFalse(outcome.as_dict()['native_database_mutated'])
        cached = project_cached_csv_unit(outcome.cached.unit,
            group_cache=tuple(replace(group, references=())
                              for group in outcome.cached.groups),
            area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
            columns=COLUMNS)
        self.assertEqual(cached.rows, (HEADER, ROW))

    def test_offline_cli_and_selection_emit_exact_bytes_without_network(self):
        selection = project_native_xml_selection(synthetic(), unit_paths=(UNIT,),
                                                 columns=COLUMNS)
        self.assertEqual(selection.report.rows, (HEADER, ROW))
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'synthetic.xml', Path(folder) / 'report.csv'
            source.write_text(synthetic())
            out, err = io.StringIO(), io.StringIO()
            with (redirect_stdout(out), redirect_stderr(err),
                  patch('socket.socket', side_effect=AssertionError('No network'))):
                code = cli.main(['toolkit-database-csv', str(source), '--output',
                                 str(output), '--native-xml-unit', UNIT])
            self.assertEqual(code, 0, err.getvalue())
            self.assertEqual(json.loads(out.getvalue())['projection'][
                'cached_projection']['selected_class'], 'TST7SENPIRSS')
            self.assertEqual(output.read_bytes(),
                             (HEADER + '\r\n' + ROW + '\r\n\r\n').encode())

    def test_live_cgate_export_reads_one_snapshot_without_physical_access(self):
        xml_line = synthetic().replace('\n', '')
        response = (b'[1] 343-Begin XML snippet\r\n[1] 347-'
                    + xml_line.encode() + b'\r\n[1] 344 End XML snippet\r\n')
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'live.csv'
            with peer([[response]]) as ((host, port), sent):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = cli.main(['cgate', '--host', host, '--port', str(port),
                                     'database-csv', UNIT, '--output', str(output)])
            self.assertEqual(code, 0, err.getvalue())
            report = json.loads(out.getvalue())
            self.assertEqual(report['database_command'], 'DBGETXML //CSVTEST')
            self.assertFalse(report['physical_device_accessed'])
            self.assertFalse(report['native_database_mutated'])
            self.assertEqual(sent, [b'[1] DBGETXML //CSVTEST\r\n'])
            self.assertEqual(output.read_bytes(),
                             (HEADER + '\r\n' + ROW + '\r\n\r\n').encode())

    def test_malformed_or_unsupported_profiles_reject_before_output(self):
        def wrong_firmware(root):
            # Older 2.0.00 now has its separate recovered PIR profile.
            root.find('.//Unit/FirmwareVersion').text = '99'

        def wrong_type(root):
            root.find('.//Unit/UnitType').text = 'SENPIRSS'

        def missing_secondary_application(root):
            parameter(root, 'Application').set('Value', '56 255')

        def missing_secondary_group(root):
            app = next(item for item in root.iter('Application')
                       if item.findtext('Address') == '57')
            group = next(item for item in app.iter('Group')
                         if item.findtext('Address') == '1')
            app.remove(group)

        def missing_area_group(root):
            app = next(item for item in root.iter('Application')
                       if item.findtext('Address') == '56')
            group = next(item for item in app.iter('Group')
                         if item.findtext('Address') == '255')
            app.remove(group)

        def bad_area(root):
            parameter(root, 'AreaGroupAddress').set('Value', '12')

        def bad_mask(root):
            parameter(root, 'SecondApplicationBlocks').set('Value', '256')

        def ninth_group(root):
            parameter(root, 'GroupAddress').set('Value', '1 2 3 4 5 6 7 8 9')

        def duplicate_pp(root):
            root.find('.//Unit').append(ET.Element('PP', Name='GroupAddress', Value='1'))

        for name, change in (
            ('firmware', wrong_firmware), ('type', wrong_type),
            ('disabled secondary', missing_secondary_application),
            ('missing selected group', missing_secondary_group),
            ('missing Area255', missing_area_group), ('Area12', bad_area),
            ('mask out of range', bad_mask), ('nine groups', ninth_group),
            ('duplicate PP', duplicate_pp),
        ):
            with self.subTest(name=name):
                text = edited(change)
                with self.assertRaises(ValueError):
                    project_native_xml_unit(text, UNIT, columns=COLUMNS)
                with tempfile.TemporaryDirectory() as folder:
                    source, output = Path(folder) / 'synthetic.xml', Path(folder) / 'out.csv'
                    source.write_text(text)
                    out, err = io.StringIO(), io.StringIO()
                    with (redirect_stdout(out), redirect_stderr(err),
                          patch('socket.socket', side_effect=AssertionError('No network'))):
                        code = cli.main(['toolkit-database-csv', str(source), '--output',
                                         str(output), '--native-xml-unit', UNIT])
                    self.assertEqual(code, 1)
                    self.assertFalse(output.exists())
                    self.assertFalse(json.loads(err.getvalue())[
                        'toolkit_database_csv_evidence']['output_create_attempted'])

    def test_mask_free_primary_only_sensor_is_admitted(self):
        def only_primary(root):
            parameter(root, 'Application').set('Value', '56 255')
            parameter(root, 'SecondApplicationBlocks').set('Value', '0')

        outcome = project_native_xml_unit(edited(only_primary), UNIT, columns=COLUMNS)
        self.assertEqual(outcome.cached.unit.secondary, '')
        self.assertEqual([group.tag for group in outcome.cached.groups
                          if group.identity in outcome.cached.unit.group_identities][:8],
                         ['P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8'])

    def test_cached_sensor_rejects_extra_stored_group_before_projection(self):
        outcome = project_native_xml_unit(synthetic(), UNIT, columns=COLUMNS)
        unit = replace(outcome.cached.unit,
                       group_identities=outcome.cached.unit.group_identities
                       + (outcome.cached.unit.group_identities[0],))
        with self.assertRaisesRegex(ValueError, 'exactly eight stored groups'):
            project_cached_csv_unit(
                unit, group_cache=outcome.cached.groups,
                area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
                columns=COLUMNS)


if __name__ == '__main__':
    unittest.main()
