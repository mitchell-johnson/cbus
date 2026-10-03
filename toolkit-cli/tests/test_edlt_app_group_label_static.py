"""Sanitized source proof and separately authored complete-record vectors."""
import json
import os
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
ANNEX=ROOT/'research/fixtures/edlt-app-group-label-source-annex.json'
VECTOR=ROOT/'research/fixtures/edlt-app-group-label-vectors.json'


class AppGroupStaticTests(unittest.TestCase):
    def test_all_six_profiles_bind_exact_offsets_and_panel_choices(self):
        annex=json.loads(ANNEX.read_text());vectors=json.loads(VECTOR.read_text())
        expected={row['family']:row for row in vectors['family_profiles']}
        self.assertEqual(set(expected),{'enable','timer','shutter','multilevel','fan','room-courtesy'})
        for profile in annex['family_profiles']:
            with self.subTest(family=profile['family']):
                literal=expected[profile['family']]
                for key in ('widget_type','label_offset','status_offset'):
                    self.assertEqual(profile[key],literal[key])
                self.assertEqual(profile['unchanged_index_resolution'],not literal['conditional_index_setter'])
                self.assertEqual(profile['label_type_choice_values'],literal['label_type_choices'])
                self.assertEqual(profile['status_type_choice_values'],literal['status_type_choices'])
                self.assertEqual(profile['static_status_offsets'],literal['static_status_targets'])

    def test_exact_method_and_source_hashes_and_all_static_rules(self):
        annex=json.loads(ANNEX.read_text())
        self.assertEqual(len(annex['managed_method_spans']),66)
        self.assertEqual(len(annex['decompiled_source_symbols']),35)
        self.assertEqual(len(annex['static_checks']),62)
        for row in annex['managed_method_spans']:
            with self.subTest(symbol=row['symbol'],token=row['token']):
                self.assertRegex(row['body_sha256'],r'^[0-9a-f]{64}$')
                self.assertRegex(row['il_sha256'],r'^[0-9a-f]{64}$')
                self.assertGreater(row['body_bytes'],0)
        self.assertTrue(all(row['passed'] is True for row in annex['static_checks']))
        ids={row['id'] for row in annex['static_checks']}
        self.assertIn('shutter-does-not-bind-unused-shutter-status-list',ids)
        self.assertIn('fan-panel-inherits-four-static-status-controls',ids)

    def test_source_data_contains_no_private_coordinates_or_execution_claim(self):
        annex=json.loads(ANNEX.read_text())
        text=json.dumps(annex,ensure_ascii=False)
        self.assertIsNone(re.search(r'(?:[A-Za-z]:\\|/(?:Users|private|Volumes)/)',text))
        self.assertEqual(annex['omissions']['local_coordinate_fields_published'],0)
        self.assertEqual(annex['limits']['original_instructions_executed'],0)
        self.assertEqual(annex['limits']['framework_instructions_executed'],0)
        self.assertFalse(annex['limits']['automatic_event_schedule_verified'])
        self.assertFalse(annex['limits']['culture_sorted_suggestion_ordinals_verified'])
        self.assertFalse(annex['limits']['physical_device_verified'])
        self.assertFalse(json.loads(VECTOR.read_text())['provenance']['producer_imported'])

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_VENDOR_ROOT'),
        'Pinned private input must be explicitly configured for read-only static regeneration')
    def test_original_static_annex_regenerates_without_execution(self):
        from research.edlt_app_group_label_static import recover
        self.assertEqual(recover(Path(os.environ['CBUS_TOOLKIT_VENDOR_ROOT'])),json.loads(ANNEX.read_text()))


if __name__=='__main__':unittest.main()
