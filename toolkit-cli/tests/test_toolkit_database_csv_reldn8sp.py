"""Source-pinned RELDN8SP two-pass group load and CSV projection."""
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
    CSVAreaObservation, loads_cached_projection, project_cached_csv_unit,
)
from tests.test_cgate import peer


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/toolkit-database-csv-reldn8sp-synthetic.xml'
REVIEW = ROOT / 'research/experiments/2026-09-28/csv-reldn8sp-profile-review.json'
VENDOR = Path('/private/tmp/cbus-toolkit-installer-audit/extracted-20260926/app')
PATH = '//CSVTEST/254/p/9'
HEADER = ('Unit Address,Part Name,Tag Name,Unit Type,Catalog Number,Serial Number,'
          'Firmware Version,Primary Application,Secondary Application,Area,'
          + ''.join(f'Group {number},' for number in range(1, 17)))
ROW = ('9,DIN Relay SP Synthetic,Nine relay SP,RELDN8SP,SYNTHETIC,No serial #,'
       '2.7.00,Lighting,,<Unused>,"Kitchen, east",Circuit 08,Circuit 04,'
       'Circuit 03,Circuit 06,Circuit 16,Circuit 15,Circuit 14,Circuit 13,'
       + '<N/A>,' * 7)
CSV_BYTES = (HEADER + '\r\n' + ROW + '\r\n\r\n').encode()
STORED = (8, 1, 8, 4, 3, 2, 7, 6, 16, 15, 14, 13, 12, 11, 10, 9)
RELOADED = tuple(STORED[index] for index in (1, 2, 3, 4, 7, 8, 9, 10, 11))


def synthetic():
    return FIXTURE.read_text(encoding='utf-8')


def edited(change):
    root = ET.fromstring(synthetic())
    change(root, root.find('./Project/Network/Unit'))
    return ET.tostring(root, encoding='unicode')


def parameter(unit, name):
    return next(node for node in unit.findall('PP') if node.get('Name') == name)


def cached_input(native):
    return {
        'format': 'cbus-toolkit-database-cached-projection-v1',
        'unit': native.cached.unit.as_dict(),
        'group_cache': [replace(group, references=()).as_dict()
                        for group in native.cached.groups],
        'area_observations': [{'raw': '255', 'completed': True}] * 2,
        'group_save': None,
    }


class RELDN8SPCSVTests(unittest.TestCase):
    def test_source_receipt_distinguishes_load_operations_from_final_manager(self):
        review = json.loads(REVIEW.read_text(encoding='utf-8'))
        self.assertEqual(review['synthetic_fixture']['sha256'],
                         hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
        self.assertFalse(review['original_execution'])
        self.assertEqual(review['loader']['association_operations'], 25)
        self.assertTrue(review['loader']['group_manager_clear_between_passes'])
        self.assertEqual(review['loader']['final_group_manager_count'], 9)
        self.assertEqual(review['loader']['second_pass_stored_indices_zero_based'],
                         [1, 2, 3, 4, 7, 8, 9, 10, 11])

    @unittest.skipUnless((VENDOR / 'CBusToolkit.exe').exists()
                         and (VENDOR / 'CBusToolkit.map').exists(),
                         'Pinned original Toolkit EXE/MAP not provisioned')
    def test_fresh_original_source_review_matches_committed_receipt(self):
        from research.csv_reldn8sp_profile_review import source_review
        self.assertEqual(source_review(VENDOR / 'CBusToolkit.exe',
                                       VENDOR / 'CBusToolkit.map', FIXTURE),
                         json.loads(REVIEW.read_text(encoding='utf-8')))

    def test_native_and_cached_keep_both_load_phases_and_export_nine_groups(self):
        native = project_native_xml_unit(synthetic(), PATH, columns=COLUMNS)
        self.assertTrue(native.complete)
        self.assertEqual(native.cached.selected_class, 'TRELDN8SP')
        self.assertEqual(native.report.rows, (HEADER, ROW))
        self.assertEqual(native.cached.raw_area, '255')
        self.assertEqual([event.event for event in native.cached.events].count('area_load'), 2)
        self.assertIn('marshalling_box_groups_replaced',
                      [event.event for event in native.cached.events])
        groups = {group.identity: group for group in native.cached.groups}
        loaded = native.cached.unit.loader_associations
        self.assertEqual(tuple(groups[identity].address for identity in loaded),
                         STORED + RELOADED)
        self.assertEqual(native.cached.unit.group_identities, loaded[16:])
        self.assertEqual(tuple(group.interaction for group in
                               native.cached.csv_unit.groups), (True,) * 9)
        cached = project_cached_csv_unit(native.cached.unit,
            group_cache=tuple(replace(group, references=())
                              for group in native.cached.groups),
            area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
            columns=COLUMNS)
        self.assertEqual(cached.rows, native.report.rows)
        self.assertEqual(loads_cached_projection(json.dumps(cached_input(native)).encode(),
                                                  columns=COLUMNS).rows, native.report.rows)

    def test_public_cached_offline_and_one_request_live_exports(self):
        native = project_native_xml_unit(synthetic(), PATH, columns=COLUMNS)
        response = (b'[1] 343-Begin XML snippet\r\n[1] 347-'
                    + synthetic().replace('\n', '').encode()
                    + b'\r\n[1] 344 End XML snippet\r\n')
        with tempfile.TemporaryDirectory() as folder:
            xml_source = Path(folder) / 'synthetic.xml'
            xml_source.write_text(synthetic(), encoding='utf-8')
            cached_source = Path(folder) / 'cached.json'
            cached_source.write_text(json.dumps(cached_input(native)), encoding='utf-8')
            before = hashlib.sha256(xml_source.read_bytes()).hexdigest()
            for source, mode in ((xml_source, ('--native-xml-unit', PATH)),
                                 (xml_source, ('--native-xml-project', '//CSVTEST')),
                                 (cached_source, ('--cached-projection',))):
                with self.subTest(mode=mode):
                    output = Path(folder) / 'offline.csv'
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with (redirect_stdout(stdout), redirect_stderr(stderr),
                          patch('socket.socket', side_effect=AssertionError('No network'))):
                        code = cli.main(['toolkit-database-csv', str(source),
                                         '--output', str(output), *mode])
                    self.assertEqual(code, 0, stderr.getvalue())
                    self.assertEqual(output.read_bytes(), CSV_BYTES)
                    output.unlink()
            self.assertEqual(hashlib.sha256(xml_source.read_bytes()).hexdigest(), before)

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

    def test_incomplete_native_and_cached_profiles_fail_before_output_creation(self):
        def firmware(_, unit): unit.find('FirmwareVersion').text = '2.8.00'
        def secondary(_, unit): parameter(unit, 'Application').set('Value', '56 57')
        def area(_, unit): parameter(unit, 'AreaGroupAddress').set('Value', '13')
        def short(_, unit): parameter(unit, 'GroupAddress').set('Value', '8 1 8 4')
        def duplicate(_, unit): unit.append(ET.Element('PP', Name='GroupAddress', Value='8'))
        def hidden_missing(root, _):
            application = root.find('./Project/Network/Application')
            application.remove(next(group for group in application.findall('Group')
                                    if group.findtext('Address') == '10'))
        for name, change in (('firmware', firmware), ('secondary', secondary),
                             ('Area13', area), ('short groups', short),
                             ('duplicate PP', duplicate), ('hidden stored group', hidden_missing)):
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

        native = project_native_xml_unit(synthetic(), PATH, columns=COLUMNS)
        base = cached_input(native)
        for name, mutate in (
            ('missing history', lambda unit: unit.pop('loader_associations')),
            ('truncated history', lambda unit: unit['loader_associations'].pop()),
            ('wrong reload', lambda unit: unit['loader_associations'].__setitem__(16,
                                                                                  unit['loader_associations'][0])),
        ):
            with self.subTest(name=name):
                raw = json.loads(json.dumps(base))
                mutate(raw['unit'])
                with self.assertRaises(ValueError):
                    loads_cached_projection(json.dumps(raw).encode(), columns=COLUMNS)


if __name__ == '__main__':
    unittest.main()
