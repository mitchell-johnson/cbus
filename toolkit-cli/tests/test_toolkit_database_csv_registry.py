"""Toolkit 1.18 CSV factory registry and the profiles it admits by shared agent."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from cbus_toolkit import cli
from cbus_toolkit import toolkit_database_csv_registry as registry
from cbus_toolkit.toolkit_database_csv import COLUMNS
from cbus_toolkit.toolkit_database_csv_native import (
    project_native_xml_selection,
    project_native_xml_unit,
)
from cbus_toolkit.toolkit_database_csv_projection import (
    CSVAreaObservation,
    admitted_profiles,
    project_cached_csv_unit,
)
from tests.test_cgate import peer


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'research/experiments/2026-09-30/csv-factory-registry-static.json'
CURRENT_RECEIPT = ROOT / 'research/fixtures/toolkit-database-csv-neopro-registry.json'
FIXTURE = ROOT / 'research/fixtures/toolkit-database-csv-registry-batch-synthetic.xml'
HEADER = ('Unit Address,Part Name,Tag Name,Unit Type,Catalog Number,Serial Number,'
          'Firmware Version,Primary Application,Secondary Application,Area,'
          + ''.join(f'Group {number},' for number in range(1, 17)))
PREFIX = 'Registry Batch Synthetic'
KITCHEN = '"Kitchen, east"'


def _row(address, tag, kind, firmware, labels, secondary=''):
    return (f'{address},{PREFIX},{tag},{kind},SYNTHETIC,No serial #,{firmware},Lighting,'
            f'{secondary},<Unused>,' + ''.join(label + ',' for label in labels)
            + '<N/A>,' * (16 - len(labels)))


def _circuits(*numbers):
    return [KITCHEN if number == 1 else f'Circuit {number:02d}' for number in numbers]


# (address, class, row): each newly admitted type, in numeric address order.
UNITS = (
    (10, 'TANODN4', _row(10, 'Analogue four', 'ANODN4', '2.7.00', _circuits(4, 3, 2, 1))),
    (11, 'TDIMDS8', _row(11, 'Eight dimmer', 'DIMDS8', '2.7.00', _circuits(*range(16, 8, -1)))),
    (12, 'TDIMPR1', _row(12, 'One dimmer', 'DIMPR1', '2.7.00', _circuits(5))),
    (13, 'TDIMPR2', _row(13, 'Two dimmer', 'DIMPR2', '2.7.00', _circuits(2, 2))),
    (14, 'TDIMPR4', _row(14, 'Four professional', 'DIMPR4', '2.7.00', _circuits(1, 2, 3, 4))),
    (15, 'TRELDC4', _row(15, 'Four contactor', 'RELDC4', '2.7.00', _circuits(12, 11, 10, 9))),
    (16, 'TRELDB1', _row(16, 'One relay', 'RELDB1', '2.7.00', _circuits(16))),
    (17, 'TANOMB8', _row(17, 'Analogue box', 'ANOMB8', '2.7.00', _circuits(*range(1, 10)))),
    (18, 'TDSIMB8', _row(18, 'DSI box', 'DSIMB8', '2.7.00', _circuits(*range(9, 0, -1)))),
    (19, 'TRELMB8', _row(19, 'Relay box', 'RELMB8', '2.7.00',
                         _circuits(2, 3, 4, 5, 8, 9, 10, 11, 12))),
    (20, 'TST7SENPIRSS', _row(20, 'Ceiling sensor', 'SENPIRIB', '2.2.00',
                              [KITCHEN, 'Zone 2', 'Circuit 03', 'Zone 4', 'Circuit 05',
                               'Zone 6', 'Circuit 07', 'Zone 8'], 'Secondary')),
)
ROWS = tuple(row for _, _, row in UNITS)
CSV_BYTES = ('\r\n'.join((HEADER, *ROWS)) + '\r\n\r\n').encode()
NEW_TYPES = ('ANODN4', 'ANOMB8', 'DIMDS8', 'DIMPR1', 'DIMPR2', 'DIMPR4', 'DSIMB8',
             'RELDB1', 'RELDC4', 'RELMB8', 'SENPIRIB')
EARLIER_TYPES = ('DIMDN4', 'DIMDN4F', 'DIMDN8', 'DIMDN8F', 'KEYE1', 'KEYE2', 'KEYE3', 'KEYE4',
                 'KEYEIR1', 'KEYEIR2', 'KEYEIR3', 'KEYEIR4', 'KEYGL5', 'RELAY4', 'RELDN12',
                 'RELDN4', 'RELDN8', 'RELDN8B', 'RELDN8SP', 'SENPIRIA', 'SENPIROA')


def receipt():
    return json.loads(RECEIPT.read_text(encoding='utf-8'))


def synthetic():
    return FIXTURE.read_text(encoding='utf-8')


def edited(kind, change):
    root = ET.fromstring(synthetic())
    unit = next(row for row in root.iter('Unit') if row.findtext('UnitType') == kind)
    change(root, unit)
    return ET.tostring(root, encoding='unicode')


def parameter(unit, name):
    return next(node for node in unit.findall('PP') if node.get('Name') == name)


class FactoryRegistryTests(unittest.TestCase):
    def test_receipt_is_the_complete_static_denominator(self):
        value = receipt()
        self.assertEqual(value['format'], 'cbus-toolkit-csv-factory-registry-static-v1')
        self.assertFalse(value['original_execution'])
        self.assertEqual(value['original_inputs'], {
            'CBusToolkit.exe': '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab',
            'CBusToolkit.map': 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'})
        summary = value['summary']
        self.assertEqual(summary['static_registrations'], len(value['registrations']))
        self.assertEqual(value['factories']['unit']['callsites'],
                         summary['static_registrations'] + summary['dynamic_registration_sites'])
        self.assertEqual((summary['static_registrations'], summary['unit_types'],
                          summary['agent_registrations'], summary['documentor_registrations']),
                         (425, 262, 365, 223))
        self.assertEqual(summary['admitted_types'] + summary['unadmitted_types'],
                         summary['unit_types'])
        self.assertEqual(sorted(value['admitted_types']), sorted((*EARLIER_TYPES, *NEW_TYPES)))
        self.assertEqual(len(value['dynamic_registrations']), 2)
        for row in value['registrations']:
            with self.subTest(row=row['class_registration']):
                if row['admitted']:
                    self.assertTrue(row['association_model'])
                    self.assertNotIn('refusal_reason', row)
                else:
                    self.assertTrue(row['refusal_reason'])
                    self.assertNotIn('association_model', row)

    def test_admitted_profiles_match_their_registered_class_and_firmware_range(self):
        rows = json.loads(CURRENT_RECEIPT.read_text(encoding='utf-8'))['registrations']
        for kind, firmware, klass in admitted_profiles():
            with self.subTest(kind=kind, firmware=firmware):
                matches = [row for row in registry.registrations_for(kind, firmware)
                           if row[3] == klass]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0][5], '')
                self.assertTrue(any(row['admitted'] and row['class'] == klass
                                    and row['unit_type'].upper() == kind for row in rows))

    def test_each_new_type_shares_agent_and_report_methods_with_an_earlier_profile(self):
        rows = [row for row in receipt()['registrations'] if row['admitted']]
        earlier = [row for row in rows if row['unit_type'] in EARLIER_TYPES]

        def behaviour(row):
            slots = {name: row['report_slots'][name]
                     for name in ('area', 'interaction', 'primary', 'secondary')}
            return row['agent'], json.dumps(row['agent_methods'], sort_keys=True), json.dumps(slots)

        for row in rows:
            if row['unit_type'] not in NEW_TYPES:
                continue
            with self.subTest(kind=row['unit_type']):
                shared = [item for item in earlier if behaviour(item) == behaviour(row)]
                self.assertTrue(shared, row['unit_type'])
                if row['agent'] in ('TDinRailOutputCGateAgent', 'TMarshallingBoxCGateAgent'):
                    self.assertEqual(row['report_slots']['predicate_kind'], 'dimmer')
                    self.assertIsInstance(row['report_slots']['channels'], int)

    def test_reldn8_registry_selects_marshalling_box_remap(self):
        row, = [row for row in receipt()['registrations'] if row['unit_type'] == 'RELDN8']
        self.assertEqual(row['agent'], 'TMarshallingBoxCGateAgent')
        self.assertEqual(row['agent_methods']['load_groups'],
                         'TMarshallingBoxCGateAgent.LoadGroups')
        self.assertEqual(row['report_slots']['channels'], 8)
        self.assertIn('[1, 2, 3, 4, 7, 8, 9, 10]', row['association_model'])

    def test_generated_module_matches_receipt(self):
        expected = tuple((row['unit_type'], row['firmware_min'], row['firmware_max'], row['class'],
                          row['agent'] or '', '' if row['admitted'] else row['refusal_reason'])
                         for row in json.loads(CURRENT_RECEIPT.read_text(encoding='utf-8'))['registrations'])
        self.assertEqual(registry.REGISTRATIONS, expected)

    def test_refusal_reasons_name_the_registry_decision(self):
        for kind, firmware, needle in (
            ('RELAY1', '4.4', 'relay predicate with RELAY4'),
            ('DIMDD8', '1.3.0', 'TNCCOutputCGateAgent has no admitted CSV association model'),
            ('KEY4', '1.0', 'TCBusKeyInputCGateAgent'),
            ('SENPIRIB', '2.4.00', 'TCBusSurfaceMountPIRSensorCGateAgent'),
            ('DIMDN8', '2.6.00', 'admitted only at its pinned firmware'),
            ('NOTAUNIT', '1.0', 'no static Toolkit 1.18 unit-factory registration'),
        ):
            with self.subTest(kind=kind):
                self.assertIn(needle, registry.refusal_reason(kind, firmware))

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_TOOLKIT_MAP'),
                         'Pinned original Toolkit EXE/MAP not provisioned')
    def test_fresh_original_exe_map_extraction_matches_committed_receipt(self):
        from research.csv_factory_registry_static import dumps, registry_module, source_registry
        actual = source_registry(os.environ['CBUS_TOOLKIT_EXE'], os.environ['CBUS_TOOLKIT_MAP'],
                                 admitted_profiles())
        self.assertEqual(dumps(actual), CURRENT_RECEIPT.read_text(encoding='utf-8'))
        self.assertEqual(registry_module(actual, receipt_path=CURRENT_RECEIPT.relative_to(ROOT).as_posix()),
                         (ROOT / 'src/cbus_toolkit/toolkit_database_csv_registry.py')
                         .read_text(encoding='utf-8'))


class RegistryBatchCSVTests(unittest.TestCase):
    def test_native_and_cached_projection_of_each_new_type(self):
        for address, selected_class, expected in UNITS:
            with self.subTest(selected_class=selected_class):
                native = project_native_xml_unit(synthetic(), f'//CSVREG/254/p/{address}',
                                                 columns=COLUMNS)
                self.assertTrue(native.complete)
                self.assertEqual(native.cached.selected_class, selected_class)
                self.assertEqual(native.report.rows, (HEADER, expected))
                self.assertEqual(native.cached.raw_area, '255')
                cached = project_cached_csv_unit(native.cached.unit,
                    group_cache=tuple(replace(group, references=())
                                      for group in native.cached.groups),
                    area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
                    columns=COLUMNS)
                self.assertEqual(cached.rows, (HEADER, expected))

    def test_relmb8_retains_sixteen_loads_and_nine_marshalling_reloads(self):
        native = project_native_xml_unit(synthetic(), '//CSVREG/254/p/19', columns=COLUMNS)
        unit = native.cached.unit
        self.assertEqual(len(unit.loader_associations), 25)
        self.assertEqual(unit.group_identities, unit.loader_associations[16:])
        self.assertEqual([event.event for event in native.cached.events].count(
            'marshalling_box_groups_replaced'), 1)
        with self.assertRaisesRegex(ValueError, 'RELMB8 requires sixteen DIN loads'):
            replace(unit, group_identities=unit.group_identities[:-1])

    def test_whole_project_cli_and_live_export_write_exact_bytes(self):
        result = project_native_xml_selection(synthetic(), project_path='//CSVREG',
                                              columns=COLUMNS)
        self.assertEqual(result.report.rows, (HEADER, *ROWS))
        self.assertEqual([unit.findtext('Address') for unit in ET.fromstring(synthetic()).iter('Unit')],
                         [str(address) for address in range(20, 9, -1)])
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'synthetic.xml', Path(folder) / 'project.csv'
            source.write_text(synthetic(), encoding='utf-8')
            out, err = io.StringIO(), io.StringIO()
            with (redirect_stdout(out), redirect_stderr(err),
                  patch('socket.socket', side_effect=AssertionError('No network'))):
                code = cli.main(['toolkit-database-csv', str(source), '--output', str(output),
                                 '--native-xml-project', '//CSVREG'])
            self.assertEqual(code, 0, err.getvalue())
            self.assertEqual(output.read_bytes(), CSV_BYTES)
            response = (b'[1] 343-Begin XML snippet\r\n[1] 347-'
                        + synthetic().replace('\n', '').encode()
                        + b'\r\n[1] 344 End XML snippet\r\n')
            live = Path(folder) / 'live.csv'
            with peer([[response]]) as ((host, port), sent):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = cli.main(['cgate', '--host', host, '--port', str(port),
                                     'database-csv', '--project', '//CSVREG',
                                     '--output', str(live)])
            self.assertEqual(code, 0, err.getvalue())
            self.assertEqual(sent, [b'[1] DBGETXML //CSVREG\r\n'])
            self.assertEqual(live.read_bytes(), CSV_BYTES)

    def test_unadmitted_and_malformed_inputs_reject_before_output(self):
        def relay1(_, unit): unit.find('UnitType').text = 'RELAY1'
        def ncc(_, unit): unit.find('UnitType').text = 'DIMDD8'
        def late(_, unit): unit.find('FirmwareVersion').text = '2.4.00'
        def firmware(_, unit): unit.find('FirmwareVersion').text = '2.6.00'
        def secondary(_, unit): parameter(unit, 'Application').set('Value', '56 57')
        def unused_secondary(_, unit): parameter(unit, 'Application').set('Value', '56 255')
        def short(_, unit): parameter(unit, 'GroupAddress').set('Value', '1 2 3 4')
        def missing(root, _):
            application = root.find('./Project/Network/Application')
            application.remove(next(group for group in application.findall('Group')
                                    if group.findtext('Address') == '12'))

        for name, kind, change, needle in (
            ('shared relay agent', 'DIMPR1', relay1, 'relay predicate with RELAY4'),
            ('unimplemented agent', 'DIMDS8', ncc, 'TNCCOutputCGateAgent'),
            ('other SENPIRIB agent', 'SENPIRIB', late, 'TCBusSurfaceMountPIRSensorCGateAgent'),
            ('firmware', 'RELDC4', firmware, 'pinned firmware'),
            ('secondary', 'ANOMB8', secondary, 'unused secondary'),
            ('mask without secondary', 'SENPIRIB', unused_secondary, 'secondary group blocks'),
            ('short group array', 'DSIMB8', short, 'element count'),
            ('missing remapped group', 'RELMB8', missing, 'absent'),
        ):
            with self.subTest(name=name):
                text = edited(kind, change)
                with self.assertRaisesRegex(ValueError, needle):
                    project_native_xml_selection(text, project_path='//CSVREG', columns=COLUMNS)
                with tempfile.TemporaryDirectory() as folder:
                    source, output = Path(folder) / 'in.xml', Path(folder) / 'out.csv'
                    source.write_text(text, encoding='utf-8')
                    out, err = io.StringIO(), io.StringIO()
                    with (redirect_stdout(out), redirect_stderr(err),
                          patch('socket.socket', side_effect=AssertionError('No network'))):
                        code = cli.main(['toolkit-database-csv', str(source),
                                         '--output', str(output),
                                         '--native-xml-project', '//CSVREG'])
                    self.assertEqual(code, 1)
                    self.assertFalse(output.exists())

    def test_fixture_is_synthetic_and_hash_pinned(self):
        text = synthetic()
        self.assertNotIn('Interface', text)
        self.assertEqual(ET.fromstring(text).findtext('Project/Address'), 'CSVREG')
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                         'da0e2db5685f3b55c45d55c69f756fbd86c5d6f166103ef5aae1966e0b7ea8aa')


if __name__ == '__main__':
    unittest.main()
