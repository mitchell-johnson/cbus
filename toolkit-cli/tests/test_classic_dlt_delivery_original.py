"""Retained original delivery decisions, without network or physical calls."""
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/classic-dlt-delivery-original.json'


class DeliveryEvidenceTests(unittest.TestCase):
    def test_explicit_save_and_transfer_gates(self):
        report = json.loads(FIXTURE.read_text())
        self.assertEqual(report['format'], 'cbus-classic-dlt-delivery-original-v1')
        gates = report['observations']['gates']
        self.assertEqual(len(gates), 8)
        self.assertEqual(len({(row['save_labels'], row['transfer'], row['key_count']) for row in gates}), 8)
        for row in gates:
            self.assertEqual(row['result']['eligible'], bool(row['key_count']) and
                             (row['save_labels'] or row['transfer']))
            self.assertEqual(row['result']['actions'], [])

    def test_clear_and_send_decisions_include_missing_bitmap_and_key_numbering(self):
        report = json.loads(FIXTURE.read_text())
        decisions = report['observations']['decisions']
        self.assertEqual(len(decisions), 50)
        self.assertEqual({row['key_index'] for row in decisions}, {0, 7})
        for row in decisions:
            with self.subTest(row=row):
                missing = row.get('flavour_present') is False
                clear = missing or row['tag_value'] in ('', '<Default>') or (
                    row['tag_type'] in (2, 3) and not row['dynamic_data'])
                expected = {'target': 'unit', 'verbs': ['DLTClearLabel', f"KeyNumber={row['key_index'] + 1}"]}
                if not clear:
                    expected = {'target': 'flavour', 'verbs': ['SaveDLTLabel']}
                self.assertEqual(row['result']['actions'], [expected])
                self.assertEqual(row['result']['flavour_marked'], clear and not missing)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires exact original Toolkit EXE/MAP')
class DeliveryReplayTests(unittest.TestCase):
    def test_fresh_original_branches_match_retained_evidence(self):
        from research.classic_dlt_delivery_original import inspect
        executable = Path(os.environ['CBUS_TOOLKIT_EXE'])
        symbols = Path(os.environ.get('CBUS_TOOLKIT_MAP', executable.with_suffix('.map')))
        self.assertEqual(inspect(executable, symbols), json.loads(FIXTURE.read_text()))


if __name__ == '__main__':
    unittest.main()
