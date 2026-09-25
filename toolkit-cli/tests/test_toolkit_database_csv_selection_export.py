"""Multi-unit composition of the admitted native CSV projection profiles."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from cbus_toolkit import cli, toolkit_database_csv_cli as boundary
from cbus_toolkit import toolkit_database_csv_native as native
from cbus_toolkit.toolkit_database_csv import COLUMNS, MAX_UNITS
from tests.test_cgate import peer
from tests.test_toolkit_database_csv import FIXTURE
from tests.test_toolkit_database_csv_native import native_xml, oid


def selection_xml(*, unsupported=False, duplicate_address=False, duplicate_oid=False,
                  empty=False, with_oids=True):
    """Synthetic composition of existing admitted per-unit test fixtures."""
    root = ET.fromstring(native_xml(with_oids=with_oids))
    network = root.find('Project/Network')
    relay = network.find('Unit')
    network.remove(relay)
    if not empty:
        keye = ET.fromstring(native_xml(unit_type='KEYE3', with_oids=with_oids)).find(
            'Project/Network/Unit')
        keye.find('Address').text = '4' if duplicate_address else '9'
        keye.find('TagName').text = 'Key, "Nine"'
        if with_oids and not duplicate_oid:
            keye.find('OID').text = oid(509)
        if unsupported:
            keye.find('FirmwareVersion').text = 'unobserved'
        network.append(keye)
        network.append(relay)
    return ET.tostring(root, encoding='unicode')


class NativeXMLCSVSelectionTests(unittest.TestCase):
    def test_original_address_order_vector_with_admitted_native_profiles(self):
        # Reuse only the captured address-column contract. The original vector's
        # KEYGL5 metadata is not an admitted native projection profile.
        vector = next(case for case in json.loads(FIXTURE.read_text())['vectors']
                      if case['input']['id'] == 'manager-order')
        root = ET.fromstring(native_xml(with_oids=False))
        network = root.find('Project/Network')
        template = network.find('Unit')
        network.remove(template)
        for values in vector['input']['units']:
            unit = copy.deepcopy(template)
            unit.find('Address').text = str(values['address'])
            network.append(unit)
        result = native.project_native_xml_selection(ET.tostring(root, encoding='unicode'),
            network_path='//CSVTEST/254', columns=('address',))
        self.assertEqual(list(result.report.rows), vector['output'])
        self.assertEqual(result.report.utf8_bytes,
                         ('\r\n'.join(vector['output']) + '\r\n\r\n').encode())

    def test_explicit_order_one_parse_one_header_and_original_quoting(self):
        xml = selection_xml()
        with patch.object(native, '_container', wraps=native._container) as parse:
            result = native.project_native_xml_selection(xml,
                unit_paths=('//CSVTEST/254/p/4', '//CSVTEST/254/p/9'),
                columns=('tag_name', 'address', 'group_7'))
        self.assertEqual(parse.call_count, 1)
        self.assertTrue(result.complete)
        self.assertEqual(result.report.csv_text,
            'Unit Address,Tag Name,Group 7,\r\n'
            '4,OwnedUnit,<N/A>,\r\n9,"Key, ""Nine""",<Unused>,\r\n\r\n')
        self.assertEqual(result.report.unit_count, 2)
        evidence = result.as_dict()
        self.assertEqual(evidence['unit_paths'], ['//CSVTEST/254/p/4', '//CSVTEST/254/p/9'])
        self.assertEqual(evidence['unit_order'], 'explicit_selection')
        self.assertEqual(evidence['xml_sha256'], hashlib.sha256(xml.encode()).hexdigest())
        self.assertFalse(evidence['native_database_mutated'])
        self.assertFalse(evidence['original_manager_enumeration_verified'])
        self.assertTrue(all(item['xml_sha256'] == evidence['xml_sha256']
                            for item in evidence['projections']))

    def test_network_keeps_snapshot_document_order_including_oidless_units(self):
        result = native.loads_native_xml_selection(selection_xml(with_oids=False).encode(),
            network_path='//CSVTEST/254', columns=('address',))
        self.assertEqual(result.report.rows, ('Unit Address,', '9,', '4,'))
        self.assertEqual(result.as_dict()['unit_order'], 'snapshot_document')
        self.assertEqual(result.as_dict()['network_path'], '//CSVTEST/254')
        self.assertEqual([item.cached.unit.identity for item in result.projections],
                         ['//CSVTEST/254/p/9', '//CSVTEST/254/p/4'])

    def test_empty_network_has_original_empty_report_header_and_blank_line(self):
        result = native.project_native_xml_selection(selection_xml(empty=True),
            network_path='//CSVTEST/254', columns=('address',))
        self.assertEqual(result.report.csv_text, 'Unit Address,\r\n\r\n')
        self.assertEqual(result.report.unit_count, 0)

    def test_explicit_selection_can_exclude_unsupported_unit_but_network_cannot(self):
        xml = selection_xml(unsupported=True)
        result = native.project_native_xml_selection(xml,
            unit_paths=('//CSVTEST/254/p/4',), columns=COLUMNS)
        self.assertEqual(result.report.unit_count, 1)
        with self.assertRaisesRegex(ValueError, '//CSVTEST/254/p/9.*captured'):
            native.project_native_xml_selection(xml,
                network_path='//CSVTEST/254', columns=COLUMNS)

    def test_duplicate_selected_addresses_or_object_ids_are_ambiguous(self):
        for options in ({'duplicate_address': True}, {'duplicate_oid': True}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'duplicate'):
                native.project_native_xml_selection(selection_xml(**options),
                    network_path='//CSVTEST/254', columns=COLUMNS)

    def test_selector_validation_precedes_xml_parse(self):
        invalid = ({}, {'unit_paths': ()}, {'unit_paths': ['//CSVTEST/254/p/4']},
            {'unit_paths': ('//CSVTEST/254/p/4',) * 2},
            {'unit_paths': ('//CSVTEST/254/p/4', '//OTHER/254/p/9')},
            {'unit_paths': ('//CSVTEST/254/p/4',) * (MAX_UNITS + 1)},
            {'unit_paths': ('//CSVTEST/254/p/4',), 'network_path': '//CSVTEST/254'},
            {'network_path': '//CSVTEST/0254'}, {'network_path': '//CSVTEST/256'},
            {'network_path': '//CSVTEST/254/p/4'}, {'network_path': 254})
        for selector in invalid:
            with self.subTest(selector=repr(selector)[:200]):
                with patch.object(native, '_container', side_effect=AssertionError('No XML parse')):
                    with self.assertRaises(ValueError):
                        native.project_native_xml_selection('<invalid>', columns=COLUMNS, **selector)

    def test_missing_project_network_unit_and_duplicate_network_are_rejected(self):
        xml = selection_xml()
        root = ET.fromstring(xml)
        project = root.find('Project')
        project.append(copy.deepcopy(project.find('Network')))
        cases = ((xml, {'network_path': '//OTHER/254'}),
                 (xml, {'network_path': '//CSVTEST/1'}),
                 (xml, {'unit_paths': ('//CSVTEST/254/p/1',)}),
                 (ET.tostring(root, encoding='unicode'), {'network_path': '//CSVTEST/254'}))
        for text, selector in cases:
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                native.project_native_xml_selection(text, columns=COLUMNS, **selector)

    def test_explicit_selection_can_span_networks_in_one_project(self):
        root = ET.fromstring(selection_xml(with_oids=False))
        project = root.find('Project')
        second = copy.deepcopy(project.find('Network'))
        second.find('Address').text = '253'
        project.append(second)
        result = native.project_native_xml_selection(ET.tostring(root, encoding='unicode'),
            unit_paths=('//CSVTEST/253/p/4', '//CSVTEST/254/p/9'), columns=('address',))
        self.assertEqual(result.report.rows, ('Unit Address,', '4,', '9,'))

    def test_byte_input_bounds_and_columns_are_not_bypassed_by_empty_network(self):
        for raw in (b'', 'not bytes', b' ' * (8 * 1024 * 1024 + 1)):
            with self.subTest(raw_type=type(raw)), self.assertRaises(ValueError):
                native.loads_native_xml_selection(raw, network_path='//CSVTEST/254', columns=COLUMNS)
        with self.assertRaises(ValueError):
            native.project_native_xml_selection(selection_xml(empty=True),
                network_path='//CSVTEST/254', columns=())


class DatabaseCSVSelectionCLITests(unittest.TestCase):
    def invoke(self, arguments, *, offline=True):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            if offline:
                with patch('socket.socket', side_effect=AssertionError('No network')):
                    code = cli.main(list(map(str, arguments)))
            else:
                code = cli.main(list(map(str, arguments)))
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_offline_explicit_selection_and_network_export_without_overwrite(self):
        for flags, expected in (
            (['--native-xml-units', '//CSVTEST/254/p/4', '//CSVTEST/254/p/9'], (4, 9)),
            (['--native-xml-network', '//CSVTEST/254'], (9, 4))):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as folder:
                source, output = Path(folder) / 'project.xml', Path(folder) / 'report.csv'
                source.write_text(selection_xml())
                before = source.read_bytes()
                args = ['toolkit-database-csv', source, *flags, '--output', output,
                        '--columns', 'address']
                code, result = self.invoke(args)
                self.assertEqual(code, 0)
                self.assertEqual(result['report']['unit_count'], 2)
                saved = ('Unit Address,\r\n' + ''.join(str(n) + ',\r\n' for n in expected) + '\r\n').encode()
                self.assertEqual(output.read_bytes(), saved)
                self.assertEqual(source.read_bytes(), before)
                code, result = self.invoke(args)
                self.assertEqual(code, 1)
                self.assertFalse(result['toolkit_database_csv_evidence']['output_created'])
                self.assertEqual(output.read_bytes(), saved)

    def test_late_unsupported_unit_and_ambiguous_selection_fail_before_output_creation(self):
        for xml in (selection_xml(unsupported=True), selection_xml(duplicate_oid=True)):
            with self.subTest(xml=xml[-150:]), tempfile.TemporaryDirectory() as folder:
                source, output = Path(folder) / 'project.xml', Path(folder) / 'report.csv'
                source.write_text(xml)
                code, result = self.invoke(['toolkit-database-csv', source,
                    '--native-xml-units', '//CSVTEST/254/p/4', '//CSVTEST/254/p/9',
                    '--output', output])
                self.assertEqual(code, 1)
                self.assertFalse(result['toolkit_database_csv_evidence']['output_create_attempted'])
                self.assertFalse(output.exists())

    def test_missing_area_in_selection_remains_read_only(self):
        root = ET.fromstring(selection_xml())
        network = root.find('Project/Network')
        application = network.find('Application')
        for group in application.findall('Group'):
            if group.findtext('Address') == '13':
                application.remove(group)
        for unit in network.findall('Unit'):
            if unit.findtext('UnitType') == 'RELAY4':
                unit.find("PP[@Name='AreaGroupAddress']").set('Value', '0xd')
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'project.xml', Path(folder) / 'report.csv'
            source.write_bytes(ET.tostring(root))
            before = source.read_bytes()
            code, result = self.invoke(['toolkit-database-csv', source,
                '--native-xml-network', '//CSVTEST/254', '--output', output])
            self.assertEqual(code, 1)
            self.assertIn('unperformed database mutation', result['error']['message'])
            self.assertFalse(result['toolkit_database_csv_evidence']['output_create_attempted'])
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(output.exists())

    def test_offline_invalid_selection_stops_before_source_access(self):
        with patch.object(boundary.os, 'lstat', side_effect=AssertionError('No input read')):
            code, result = self.invoke(['toolkit-database-csv', 'not-read.xml',
                '--native-xml-units', '//CSVTEST/254/p/4', '//OTHER/254/p/4',
                '--output', 'not-created.csv'])
        self.assertEqual(code, 1)
        self.assertEqual(result['toolkit_database_csv_evidence']['stage'], 'validate')
        self.assertFalse(result['toolkit_database_csv_evidence']['output_create_attempted'])

    def test_live_selection_and_network_use_one_project_snapshot(self):
        response = b'[1] 343-Begin XML snippet\r\n[1] 347-' + selection_xml().encode() + b'\r\n[1] 344 End XML snippet\r\n'
        for flags, expected in ((['--units', '//CSVTEST/254/p/4', '//CSVTEST/254/p/9'], (4, 9)),
                                (['--network', '//CSVTEST/254'], (9, 4))):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'live.csv'
                with peer([[response]]) as ((host, port), sent):
                    code, result = self.invoke(['cgate', '--host', host, '--port', port,
                        'database-csv', *flags, '--output', output, '--columns', 'address'], offline=False)
                self.assertEqual(code, 0)
                self.assertEqual(sent, [b'[1] DBGETXML //CSVTEST\r\n'])
                self.assertEqual(result['report']['unit_count'], 2)
                self.assertFalse(result['native_database_mutated'])
                self.assertEqual(output.read_text().splitlines(),
                    ['Unit Address,', *(str(n) + ',' for n in expected), ''])

    def test_live_late_unsupported_unit_creates_no_output(self):
        response = b'[1] 343-Begin XML snippet\r\n[1] 347-' + selection_xml(unsupported=True).encode() + b'\r\n[1] 344 End XML snippet\r\n'
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'live.csv'
            with peer([[response]]) as ((host, port), sent):
                code, result = self.invoke(['cgate', '--host', host, '--port', port,
                    'database-csv', '--units', '//CSVTEST/254/p/4', '//CSVTEST/254/p/9',
                    '--output', output], offline=False)
            self.assertEqual(code, 1)
            self.assertEqual(sent, [b'[1] DBGETXML //CSVTEST\r\n'])
            self.assertIn('//CSVTEST/254/p/9', result['error'])
            self.assertFalse(output.exists())

    def test_live_selector_and_mutation_rejections_happen_before_connection(self):
        invalid = ({}, {'unit': '//CSVTEST/254/p/4', 'network': '//CSVTEST/254'},
            {'units': ['//CSVTEST/254/p/4'], 'network': '//CSVTEST/254'},
            {'units': ['//CSVTEST/254/p/4', '//OTHER/254/p/4']},
            {'units': ['//CSVTEST/254/p/4'] * 2},
            {'network': '//CSVTEST/0254'},
            {'units': ['//CSVTEST/254/p/4'], 'apply_missing_area': True, 'backup_project': 'BACKUP'},
            {'network': '//CSVTEST/254', 'apply_missing_area': True, 'backup_project': 'BACKUP'})
        for options in invalid:
            args = dict(area='cgate', action='database-csv', unit=None, units=None,
                network=None, columns=None, apply_missing_area=False, backup_project=None)
            args.update(options)
            factory = Mock()
            with self.subTest(options=options), self.assertRaises(ValueError):
                boundary.live(SimpleNamespace(**args), factory, None)
            factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
