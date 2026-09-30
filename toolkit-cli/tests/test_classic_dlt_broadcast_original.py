"""Bounded original per-flavour compiler and cache-state observations."""
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/classic-dlt-broadcast-original.json'


class BroadcastOriginalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(FIXTURE.read_text())
        self.rows = self.report['observations']

    def test_explicit_boundaries_and_complete_variant_type_matrix(self):
        self.assertEqual(self.report['format'], 'cbus-classic-dlt-broadcast-original-v1')
        self.assertEqual(len(self.rows), 64)
        self.assertEqual(len(self.report['methods']), 8)
        self.assertFalse(self.report['boundary']['physical_io'])
        self.assertFalse(self.report['boundary']['native_cgate_executed'])
        self.assertFalse(self.report['boundary']['command_builder_executed'])
        self.assertEqual({(r['input']['variant'], r['input']['tag_type']) for r in self.rows[:44]},
                         {(variant, kind) for variant in range(1, 5) for kind in range(4)})

    def test_text_empty_default_and_full_string_unicode_gate(self):
        rows = [r for r in self.rows[:44] if r['input']['tag_type'] == 0]
        self.assertEqual(len(rows), 32)
        for row in rows:
            source, result = row['input'], row['result']
            with self.subTest(variant=source['variant'], value=source['value']):
                self.assertTrue(result['completed_routine'])
                self.assertTrue(result['broadcast_marked'])
                if any(ord(c) > 255 for c in source['value']):
                    self.assertEqual(result['commands'], [])
                else:
                    self.assertEqual(len(result['commands']), 1)
                    command = result['commands'][0]
                    self.assertEqual(command['variant'], f"F{source['variant'] - 1}")
                    self.assertFalse(command['broadcast_marked_at_entry'])
                    if source['value'] in ('', '<Default>'):
                        self.assertEqual((command['type'], command['data']), ('0', '10'))
                    else:
                        self.assertEqual((command['type'], command['data']),
                                         ('00', source['value'][:14].encode('latin1').hex().upper()))

    def test_dynamic_font_composition_and_mark_between_commands(self):
        for row in [r for r in self.rows[:44] if r['input']['tag_type'] in (2, 3)]:
            source, result = row['input'], row['result']
            with self.subTest(variant=source['variant'], kind=source['tag_type']):
                image_id = source['value'].split(',')[0]
                first, second = result['commands']
                self.assertEqual((first['type'], first['data']),
                                 ('DYNAMIC', f"{image_id} 64 16 10 {source['dynamic_data']}"))
                self.assertFalse(first['broadcast_marked_at_entry'])
                self.assertEqual((second['type'], second['data']), ('ICON', image_id))
                self.assertTrue(second['broadcast_marked_at_entry'])
                self.assertTrue(result['broadcast_marked'])

    def test_gates_failure_boundaries_and_invalid_variants(self):
        rows = self.rows[44:58]
        for row in rows:
            source, result = row['input'], row['result']
            with self.subTest(source=source):
                if source['already_broadcast'] or not source['group_present']:
                    self.assertEqual(result['commands'], [])
                    self.assertEqual(result['broadcast_marked'], source['already_broadcast'])
                    self.assertTrue(result['completed_routine'])
                else:
                    self.assertEqual(len(result['commands']), source['fail_command'])
                    self.assertEqual(result['broadcast_marked'], source['fail_command'] == 2)
                    self.assertFalse(result['completed_routine'])
                    self.assertTrue(result['stopped_at_command_failure'])
        for row in self.rows[-2:]:
            self.assertEqual(row['result']['assertion'], 'Invalid Flavour value')
            self.assertEqual(row['result']['commands'], [])
            self.assertFalse(row['result']['broadcast_marked'])

    def test_malformed_graphic_tag_behavior_is_observed_not_admitted(self):
        dynamic, font = self.rows[60:62]
        self.assertEqual(dynamic['result']['commands'][0]['data'].split(' ')[0], dynamic['input']['value'])
        self.assertEqual(dynamic['result']['commands'][1]['data'], '100')
        self.assertEqual(font['result']['commands'][0]['data'].split(' ')[0], '101')
        self.assertEqual(font['result']['commands'][1]['data'], font['input']['value'])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires pinned original Toolkit EXE/MAP')
class BroadcastOriginalReplayTests(unittest.TestCase):
    def test_fresh_original_broadcast_matches_receipt(self):
        from research.classic_dlt_broadcast_original import inspect
        executable = Path(os.environ['CBUS_TOOLKIT_EXE'])
        symbols = Path(os.environ.get('CBUS_TOOLKIT_MAP', executable.with_suffix('.map')))
        self.assertEqual(inspect(executable, symbols), json.loads(FIXTURE.read_text()))


if __name__ == '__main__':
    unittest.main()
