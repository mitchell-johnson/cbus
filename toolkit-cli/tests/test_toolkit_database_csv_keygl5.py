"""Synthetic KEYGL5 CSV association cases pinned to the Toolkit 1.18 loader."""
from contextlib import redirect_stderr, redirect_stdout
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
from cbus_toolkit.toolkit_database_csv_projection import project_cached_csv_unit


FIXTURE = (Path(__file__).resolve().parents[1] / 'research' / 'fixtures' /
           'toolkit-database-csv-keygl5-synthetic.xml')
UNIT = '//CSVTEST/254/p/4'
GROUPS = ('P10', 'S11', 'P12', 'P13', 'E14', 'S15', 'P16', '<Unused>',
          '<Unused>', '<Unused>', '<Unused>', '<Unused>', '<Unused>',
          '<Unused>', '<Unused>', '<Unused>')
HEADER = ('Unit Address,Part Name,Tag Name,Unit Type,Catalog Number,Serial Number,'
          'Firmware Version,Primary Application,Secondary Application,Area,'
          + ''.join(f'Group {number},' for number in range(1, 17)))
ROW = ('4,eDLT Synthetic,Kitchen,KEYGL5,5055EDL,No serial #,5.5.00,'
       'Lighting,Secondary,<Unused>,' + ''.join(value + ',' for value in GROUPS))


def synthetic():
    return FIXTURE.read_text()


def changed_xml(edit):
    root = ET.fromstring(synthetic())
    edit(root)
    return ET.tostring(root, encoding='unicode')


class KEYGL5CSVTests(unittest.TestCase):
    def test_native_and_cached_api_project_exact_sixteen_associations(self):
        outcome = project_native_xml_unit(synthetic(), UNIT, columns=COLUMNS)
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.cached.selected_class, 'TCBusEDLTUnit')
        self.assertEqual(outcome.report.rows, (HEADER, ROW))
        self.assertEqual(outcome.cached.raw_area, None)
        self.assertEqual(outcome.cached.area_identity, None)
        self.assertFalse(outcome.as_dict()['native_database_mutated'])
        self.assertEqual(len(outcome.cached.unit.group_identities), 16)
        self.assertEqual(outcome.cached.unit.group_identities[4],
                         '00000000-0000-0000-0000-000000052982')
        self.assertEqual(outcome.cached.unit.group_identities[7],
                         outcome.cached.unit.group_identities[8])
        cached = project_cached_csv_unit(outcome.cached.unit,
            group_cache=outcome.cached.groups, columns=COLUMNS)
        self.assertEqual(cached.rows, (HEADER, ROW))
        self.assertTrue(all(value.interaction for value in cached.csv_unit.groups))

    def test_native_selection_and_cli_export_exact_rows(self):
        selected = project_native_xml_selection(synthetic(), unit_paths=(UNIT,),
                                                columns=COLUMNS)
        self.assertEqual(selected.report.rows, (HEADER, ROW))
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'synthetic.xml'
            output = Path(folder) / 'report.csv'
            source.write_text(synthetic())
            out, err = io.StringIO(), io.StringIO()
            with (redirect_stdout(out), redirect_stderr(err),
                  patch('socket.socket', side_effect=AssertionError('No network'))):
                code = cli.main(['toolkit-database-csv', str(source), '--output',
                                 str(output), '--native-xml-unit', UNIT])
            self.assertEqual(code, 0, err.getvalue())
            report = json.loads(out.getvalue())
            self.assertEqual(report['projection']['cached_projection']['selected_class'],
                             'TCBusEDLTUnit')
            self.assertEqual(output.read_bytes(),
                             (HEADER + '\r\n' + ROW + '\r\n\r\n').encode())

    def test_unsupported_or_ambiguous_profiles_fail_before_output(self):
        def pp(root, name):
            return next(node for node in root.iter('PP') if node.get('Name') == name)

        def wrong_firmware(root):
            root.find('.//Unit/FirmwareVersion').text = '5.4.00'

        def wrong_catalog(root):
            root.find('.//Unit/CatalogNumber').text = '5055EDL-OTHER'

        def conflicting_application(root):
            pp(root, 'PrimaryApplication').set('Value', '57')

        def duplicate_parameter(root):
            root.find('.//Unit').append(ET.Element('PP', Name='Widget6WidgetType', Value='2'))

        def disabled_secondary(root):
            pp(root, 'Application').set('Value', '56 255')
            pp(root, 'SecondaryApplication').set('Value', '255')

        def missing_enable_group(root):
            application = next(node for node in root.iter('Application')
                               if node.findtext('Address') == '203')
            application.remove(next(application.iter('Group')))

        def missing_unused_group(root):
            application = next(node for node in root.iter('Application')
                               if node.findtext('Address') == '56')
            application.remove(next(node for node in application.iter('Group')
                                    if node.findtext('Address') == '255'))

        cases = (
            ('firmware', wrong_firmware, 'supports only'),
            ('catalog', wrong_catalog, 'supports only'),
            ('application disagreement', conflicting_application, 'disagree'),
            ('duplicate widget parameter', duplicate_parameter,
             'exactly one stored native parameter'),
            ('disabled secondary', disabled_secondary, 'secondary widget'),
            ('missing Enable group', missing_enable_group, 'group reference is absent'),
            ('missing unused group', missing_unused_group, 'group reference is absent'),
        )
        for name, edit, message in cases:
            with self.subTest(name=name):
                text = changed_xml(edit)
                with self.assertRaisesRegex(ValueError, message):
                    project_native_xml_unit(text, UNIT, columns=COLUMNS)
                with tempfile.TemporaryDirectory() as folder:
                    source, output = Path(folder) / 'source.xml', Path(folder) / 'out.csv'
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

    def test_whole_network_rejects_late_unsupported_unit_atomically(self):
        def add_unit(root):
            network = root.find('.//Network')
            other = ET.SubElement(network, 'Unit')
            for name, value in (('Address', 5), ('UnitType', 'KEYGL5'),
                                ('FirmwareVersion', '5.4.00')):
                ET.SubElement(other, name).text = str(value)

        text = changed_xml(add_unit)
        with self.assertRaisesRegex(ValueError, 'supports only'):
            project_native_xml_selection(text, network_path='//CSVTEST/254',
                                         columns=COLUMNS)
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'source.xml', Path(folder) / 'out.csv'
            source.write_text(text)
            out, err = io.StringIO(), io.StringIO()
            with (redirect_stdout(out), redirect_stderr(err),
                  patch('socket.socket', side_effect=AssertionError('No network'))):
                code = cli.main(['toolkit-database-csv', str(source), '--output',
                                 str(output), '--native-xml-network', '//CSVTEST/254'])
            self.assertEqual(code, 1)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
