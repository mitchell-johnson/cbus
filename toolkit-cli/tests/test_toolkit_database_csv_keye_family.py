"""Synthetic, source-pinned CSV projection of the remaining TKEYEx registrations."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from cbus_toolkit import cli
from cbus_toolkit.toolkit_database_csv_native import (
    project_native_xml_selection, project_native_xml_unit,
)
from cbus_toolkit.toolkit_database_csv_projection import (
    CSVAreaObservation, CachedCSVUnit, project_cached_csv_unit,
)
from tests.test_cgate import peer
from tests.test_toolkit_database_csv_native import native_xml


TYPES = ('KEYE4', 'KEYEIR1', 'KEYEIR2', 'KEYEIR3', 'KEYEIR4')
COLUMNS = ('unit_type', 'secondary', 'area', 'group_1', 'group_2',
           'group_8', 'group_9')
HEADER = 'Unit Type,Secondary Application,Area,Group 1,Group 2,Group 8,Group 9,'


def family_xml():
    # The separate primary and secondary caches intentionally use the same
    # group addresses. The ninth stored slot is retained in the primary cache.
    root = ET.fromstring(native_xml(
        unit_type=TYPES[0], with_oids=False, secondary_address=57,
        secondary_blocks=0b01010101,
        keye_groups=(1, 2, 3, 4, 5, 6, 7, 8, 1)))
    network = root.find('Project/Network')
    first = network.find('Unit')
    for index, kind in enumerate(TYPES):
        unit = first if index == 0 else copy.deepcopy(first)
        unit.find('Address').text = str(4 + index)
        unit.find('UnitType').text = kind
        unit.find('TagName').text = f'Synthetic {kind}'
        if index:
            network.append(unit)
    return ET.tostring(root, encoding='unicode')


def invoke(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main([str(value) for value in args])
    result = json.loads(out.getvalue() if code == 0 else err.getvalue())
    return code, result


class KEYEFamilyCSVTests(unittest.TestCase):
    def test_five_registered_types_keep_primary_secondary_and_ninth_slot(self):
        xml = family_xml()
        for index, kind in enumerate(TYPES):
            with self.subTest(kind=kind):
                result = project_native_xml_unit(xml, f'//CSVTEST/254/p/{4 + index}',
                                                 columns=COLUMNS)
                self.assertTrue(result.complete)
                self.assertEqual(result.cached.selected_class, 'TKEYEx')
                self.assertEqual(result.report.rows,
                    (HEADER, f'{kind},HVAC,<Unused>,Secondary1,Group2,Group8,<N/A>,'))
                self.assertEqual(len(result.cached.unit.group_identities), 9)
                self.assertEqual(result.cached.unit.group_identities[0],
                                 '//CSVTEST/254/57/1')
                self.assertEqual(result.cached.unit.group_identities[1],
                                 '//CSVTEST/254/56/2')
                self.assertEqual(result.cached.unit.group_identities[8],
                                 '//CSVTEST/254/56/1')
                self.assertFalse(result.as_dict()['native_database_mutated'])

    def test_whole_network_offline_and_live_export_one_snapshot(self):
        xml = family_xml()
        expected_rows = tuple(
            f'{kind},HVAC,<Unused>,Secondary1,Group2,Group8,<N/A>,' for kind in TYPES)
        selected = project_native_xml_selection(xml, network_path='//CSVTEST/254',
                                                columns=COLUMNS)
        self.assertEqual(selected.report.rows, (HEADER, *expected_rows))
        self.assertEqual(selected.as_dict()['unit_paths'],
                         [f'//CSVTEST/254/p/{address}' for address in range(4, 9)])
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'synthetic.xml'
            output = Path(folder) / 'offline.csv'
            source.write_text(xml)
            original = source.read_bytes()
            with patch('socket.socket', side_effect=AssertionError('No network')):
                code, result = invoke(['toolkit-database-csv', source, '--output', output,
                    '--native-xml-network', '//CSVTEST/254', '--columns', *COLUMNS])
            self.assertEqual(code, 0, result)
            self.assertEqual(result['report']['unit_count'], 5)
            self.assertEqual(output.read_bytes(),
                ('\r\n'.join((HEADER, *expected_rows)) + '\r\n\r\n').encode())
            self.assertEqual(source.read_bytes(), original)

            live_output = Path(folder) / 'live.csv'
            response = (b'[1] 343-Begin XML snippet\r\n[1] 347-' +
                        xml.encode() + b'\r\n[1] 344 End XML snippet\r\n')
            with peer([[response]]) as ((host, port), sent):
                code, result = invoke(['cgate', '--host', host, '--port', port,
                    'database-csv', '--network', '//CSVTEST/254', '--output', live_output,
                    '--columns', *COLUMNS])
            self.assertEqual(code, 0, result)
            self.assertEqual(sent, [b'[1] DBGETXML //CSVTEST\r\n'])
            self.assertEqual(live_output.read_bytes(), output.read_bytes())
            self.assertFalse(result['native_database_mutated'])

    def test_incomplete_cached_keye_and_sensor_associations_reject(self):
        xml = family_xml()
        result = project_native_xml_unit(xml, '//CSVTEST/254/p/4', columns=COLUMNS)
        cached = result.cached
        for count in (8, 10):
            with self.subTest(count=count):
                identities = (cached.unit.group_identities[:count] if count < 9 else
                              cached.unit.group_identities +
                              (cached.unit.group_identities[-1],))
                unit = CachedCSVUnit(**{
                    **cached.unit.__dict__, 'group_identities': identities})
                with self.assertRaisesRegex(ValueError, 'exactly nine stored groups'):
                    project_cached_csv_unit(unit, group_cache=cached.groups,
                        area_observations=(CSVAreaObservation('255'),
                                           CSVAreaObservation('255')),
                        columns=COLUMNS)
        sensor = project_native_xml_unit(native_xml(unit_type='SENPIROA'),
                                         '//CSVTEST/254/p/4', columns=COLUMNS).cached
        shortened = CachedCSVUnit(**{
            **sensor.unit.__dict__,
            'group_identities': sensor.unit.group_identities[:-1],
        })
        with self.assertRaisesRegex(ValueError, 'exactly eight stored groups'):
            project_cached_csv_unit(shortened, group_cache=sensor.groups,
                area_observations=(CSVAreaObservation('255'),
                                   CSVAreaObservation('255')),
                columns=COLUMNS)

    def test_bad_late_profile_or_missing_selected_group_creates_no_file(self):
        def wrong_late_firmware(root):
            root.findall('.//Unit/FirmwareVersion')[-1].text = '2.4.00'

        def missing_primary_group(root):
            root.find('.//Application/Group/Address').text = '99'

        for name, edit in (
            ('firmware', wrong_late_firmware),
            ('missing group', missing_primary_group),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = ET.fromstring(family_xml())
                edit(root)
                source = Path(folder) / 'synthetic.xml'
                output = Path(folder) / 'report.csv'
                source.write_bytes(ET.tostring(root))
                original = source.read_bytes()
                with patch('socket.socket', side_effect=AssertionError('No network')):
                    code, result = invoke(['toolkit-database-csv', source, '--output',
                        output, '--native-xml-network', '//CSVTEST/254'])
                self.assertEqual(code, 1, result)
                self.assertFalse(output.exists())
                self.assertFalse(result['toolkit_database_csv_evidence'][
                    'output_create_attempted'])
                self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
