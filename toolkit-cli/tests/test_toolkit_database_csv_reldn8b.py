"""Source-pinned RELDN8B report visibility and fail-closed boundaries."""
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
    project_native_xml_selection, project_native_xml_unit,
)
from cbus_toolkit.toolkit_database_csv_projection import (
    CSVAreaObservation, project_cached_csv_unit,
)
from tests.test_cgate import peer


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/toolkit-database-csv-reldn8b-synthetic.xml'
REVIEW = ROOT / 'research/experiments/2026-09-28/csv-reldn8-variants-profile-review.json'
VENDOR = Path('/private/tmp/cbus-toolkit-installer-audit/extracted-20260926/app')
HEADER = ('Unit Address,Part Name,Tag Name,Unit Type,Catalog Number,Serial Number,'
          'Firmware Version,Primary Application,Secondary Application,Area,'
          + ''.join(f'Group {number},' for number in range(1, 17)))
ROW = ('8,DIN Relay B Synthetic,Eight relay B,RELDN8B,SYNTHETIC,No serial #,'
       '2.7.00,Lighting,,<Unused>,Circuit 08,"Kitchen, east",Circuit 08,'
       'Circuit 04,Circuit 03,Circuit 02,Circuit 07,Circuit 06,' + '<N/A>,' * 8)
CSV_BYTES = (HEADER + '\r\n' + ROW + '\r\n\r\n').encode()
PATH = '//CSVTEST/254/p/8'


def synthetic():
    return FIXTURE.read_text(encoding='utf-8')


def edited(change):
    root = ET.fromstring(synthetic())
    change(root, root.find('./Project/Network/Unit'))
    return ET.tostring(root, encoding='unicode')


def parameter(unit, name):
    return next(node for node in unit.findall('PP') if node.get('Name') == name)


class RELDN8BCSVTests(unittest.TestCase):
    def test_pinned_original_review_distinguishes_large_sp_profile(self):
        review = json.loads(REVIEW.read_text(encoding='utf-8'))
        self.assertFalse(review['original_execution'])
        self.assertEqual([row['selected_class'] for row in review['registrations']],
                         ['TRELDN8B', 'TRELDN8SP'])
        self.assertEqual([row['max_channels'] for row in review['registrations']],
                         [8, 9])
        self.assertEqual([row['class_agent'] for row in review['registrations']],
                         ['TDinRailOutputCGateAgent', 'TMarshallingBoxCGateAgent'])
        self.assertIn('up to 25 associations', review['static_facts']['reldn8sp'])
        self.assertEqual(review['synthetic_fixture']['sha256'],
                         hashlib.sha256(FIXTURE.read_bytes()).hexdigest())

    @unittest.skipUnless((VENDOR / 'CBusToolkit.exe').exists()
                         and (VENDOR / 'CBusToolkit.map').exists(),
                         'Pinned original Toolkit EXE/MAP not provisioned')
    def test_fresh_original_review_matches_committed_receipt(self):
        from research.csv_reldn8_variants_profile_review import source_review
        self.assertEqual(source_review(VENDOR / 'CBusToolkit.exe',
                                       VENDOR / 'CBusToolkit.map', FIXTURE),
                         json.loads(REVIEW.read_text(encoding='utf-8')))

    def test_native_and_cached_retain_sixteen_associations_but_expose_eight(self):
        native = project_native_xml_unit(synthetic(), PATH, columns=COLUMNS)
        self.assertTrue(native.complete)
        self.assertEqual(native.cached.selected_class, 'TRELDN8B')
        self.assertEqual(native.report.rows, (HEADER, ROW))
        self.assertEqual(native.cached.raw_area, '255')
        self.assertEqual([event.event for event in native.cached.events].count('area_load'), 2)
        group_by_id = {group.identity: group for group in native.cached.groups}
        self.assertEqual(tuple(group_by_id[identity].address for identity
                               in native.cached.unit.group_identities),
                         (8, 1, 8, 4, 3, 2, 7, 6, 16, 15, 14, 13, 12, 11, 10, 9))
        self.assertEqual(tuple(group.interaction for group in native.cached.csv_unit.groups),
                         (True,) * 8 + (False,) * 8)
        cached = project_cached_csv_unit(native.cached.unit,
            group_cache=tuple(replace(group, references=()) for group in native.cached.groups),
            area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
            columns=COLUMNS)
        self.assertEqual(cached.rows, native.report.rows)

    def test_public_offline_cached_native_and_live_export_exact_bytes(self):
        native = project_native_xml_unit(synthetic(), PATH, columns=COLUMNS)
        cache = {
            'format': 'cbus-toolkit-database-cached-projection-v1',
            'unit': native.cached.unit.as_dict(),
            'group_cache': [replace(group, references=()).as_dict()
                            for group in native.cached.groups],
            'area_observations': [{'raw': '255', 'completed': True}] * 2,
            'group_save': None,
        }
        response = (b'[1] 343-Begin XML snippet\r\n[1] 347-'
                    + synthetic().replace('\n', '').encode()
                    + b'\r\n[1] 344 End XML snippet\r\n')
        with tempfile.TemporaryDirectory() as folder:
            native_source = Path(folder) / 'synthetic.xml'
            native_source.write_text(synthetic(), encoding='utf-8')
            cached_source = Path(folder) / 'cached.json'
            cached_source.write_text(json.dumps(cache), encoding='utf-8')
            before = hashlib.sha256(native_source.read_bytes()).hexdigest()
            for source, mode in ((native_source, ('--native-xml-unit', PATH)),
                                 (native_source, ('--native-xml-project', '//CSVTEST')),
                                 (cached_source, ('--cached-projection',))):
                output = Path(folder) / ('out' + str(len(mode)) + source.suffix + '.csv')
                stdout, stderr = io.StringIO(), io.StringIO()
                with (redirect_stdout(stdout), redirect_stderr(stderr),
                      patch('socket.socket', side_effect=AssertionError('No network'))):
                    code = cli.main(['toolkit-database-csv', str(source),
                                     '--output', str(output), *mode])
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertEqual(output.read_bytes(), CSV_BYTES)
                output.unlink()
            self.assertEqual(hashlib.sha256(native_source.read_bytes()).hexdigest(), before)

            output = Path(folder) / 'live.csv'
            with peer([[response]]) as ((host, port), sent):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = cli.main(['cgate', '--host', host, '--port', str(port),
                                     'database-csv', PATH, '--output', str(output)])
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(sent, [b'[1] DBGETXML //CSVTEST\r\n'])
            self.assertEqual(output.read_bytes(), CSV_BYTES)
            receipt = json.loads(stdout.getvalue())
            self.assertFalse(receipt['native_database_mutated'])
            self.assertFalse(receipt['physical_device_accessed'])

    def test_sp_and_incomplete_b_shapes_reject_before_output_creation(self):
        def sp(_, unit): unit.find('UnitType').text = 'RELDN8SP'
        def firmware(_, unit): unit.find('FirmwareVersion').text = '2.8.00'
        def secondary(_, unit): parameter(unit, 'Application').set('Value', '56 57')
        def area(_, unit): parameter(unit, 'AreaGroupAddress').set('Value', '13')
        def short(_, unit): parameter(unit, 'GroupAddress').set('Value', '8 1 8 4')
        def duplicate(_, unit): unit.append(ET.Element('PP', Name='GroupAddress', Value='8'))
        def missing(root, _):
            application = root.find('./Project/Network/Application')
            application.remove(next(group for group in application.findall('Group')
                                    if group.findtext('Address') == '8'))
        for name, change in (('SP class', sp), ('firmware', firmware),
                             ('secondary', secondary), ('Area13', area),
                             ('short groups', short), ('duplicate PP', duplicate),
                             ('missing group', missing)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                text = edited(change)
                with self.assertRaises(ValueError):
                    project_native_xml_selection(text, project_path='//CSVTEST',
                                                 columns=COLUMNS)
                source, output = Path(folder) / 'in.xml', Path(folder) / 'out.csv'
                source.write_text(text, encoding='utf-8')
                stdout, stderr = io.StringIO(), io.StringIO()
                with (redirect_stdout(stdout), redirect_stderr(stderr),
                      patch('socket.socket', side_effect=AssertionError('No network'))):
                    code = cli.main(['toolkit-database-csv', str(source),
                                     '--output', str(output),
                                     '--native-xml-project', '//CSVTEST'])
                self.assertEqual(code, 1)
                self.assertFalse(output.exists())
                self.assertFalse(json.loads(stderr.getvalue())[
                    'toolkit_database_csv_evidence']['output_create_attempted'])


if __name__ == '__main__':
    unittest.main()
