"""Regression for the sanitized original C-Gate RELDN8SP cold-load readback."""

import hashlib
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit.toolkit_database_csv import COLUMNS, document_database_csv
from cbus_toolkit.toolkit_database_csv_native import project_native_xml_unit
from tests.test_toolkit_database_csv_reldn8sp import CSV_BYTES


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'research/experiments/2026-09-28/csv-reldn8sp-native-acceptance.json'
NATIVE = ROOT / 'research/fixtures/toolkit-database-csv-reldn8sp-native-sanitized.xml'


class RELDN8SPNativeAcceptanceTests(unittest.TestCase):
    def test_evidence_is_bound_to_sanitized_source_and_original_fixture(self):
        receipt = json.loads(RECEIPT.read_text(encoding='utf-8'))
        self.assertEqual(receipt['format'], 'cbus-csv-reldn8sp-native-acceptance-v1')
        for relative, expected in receipt['artifacts_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                             expected, relative)
        self.assertEqual(receipt['native_cgate']['jar_sha256'],
                         '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630')
        self.assertEqual(receipt['native_cgate']['post_reload_network_state'],
                         'State=new InterfaceState=closed')
        self.assertEqual(receipt['native_cgate']['unit_pp'], {
            'Application': '56 255',
            'AreaGroupAddress': '255',
            'GroupAddress': '8 1 8 4 3 2 7 6 16 15 14 13 12 11 10 9',
        })
        self.assertTrue(receipt['cleanup']['original_home_restored'])
        self.assertTrue(receipt['cleanup']['guest_route_matches_start'])
        self.assertFalse(receipt['toolkit_gui']['csv_export_observed'])

    def test_sanitized_native_readback_projects_the_expected_literal_csv(self):
        root = ET.fromstring(NATIVE.read_bytes())
        network = root.find('./Project/Network')
        self.assertEqual(root.findtext('./Project/Address'), 'XCSVSP2')
        self.assertEqual(network.findtext('./Interface/InterfaceAddress'), '127.0.0.1:1')
        groups = network.findall('./Application/Group')
        self.assertEqual([int(group.findtext('Address')) for group in groups],
                         list(range(1, 17)) + [255])
        result = project_native_xml_unit(NATIVE.read_text(encoding='utf-8'),
                                         '//XCSVSP2/254/p/9', columns=COLUMNS)
        self.assertTrue(result.complete)
        self.assertEqual(result.cached.selected_class, 'TRELDN8SP')
        self.assertEqual(len(result.cached.unit.loader_associations), 25)
        self.assertEqual(len(result.cached.unit.group_identities), 9)
        csv = document_database_csv((result.cached.csv_unit,), columns=COLUMNS).utf8_bytes
        self.assertEqual(csv, CSV_BYTES)
        receipt = json.loads(RECEIPT.read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256(csv).hexdigest(), receipt['python_cli']['csv_sha256'])


if __name__ == '__main__':
    unittest.main()
