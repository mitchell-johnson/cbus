"""Source-bound ICON action, language visibility and built-in catalogue evidence."""
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/classic-dlt-icon-dialog-original.json'


class IconDialogOriginalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(FIXTURE.read_text())

    def test_catalogue_is_pinned_ordered_and_contains_no_image_exports(self):
        catalogue = self.report['catalogue']
        self.assertEqual(catalogue['index']['sha256'],
                         'c6cca64deaed7bb5ad814b2aaf4c37b580396bf38c057aae8bd616fadfd26310')
        self.assertEqual(catalogue['index']['bytes'], 2392)
        self.assertEqual(catalogue['index']['count'], 91)
        self.assertEqual(catalogue['ordered_ids'], list(range(1, 92)))
        self.assertEqual([row['id'] for row in catalogue['rows']], catalogue['ordered_ids'])
        self.assertEqual(len(catalogue['methods']), 18)
        for row in catalogue['rows']:
            self.assertEqual(set(row), {'id', 'label'})
            self.assertTrue(row['label'])
            self.assertNotIn('.bmp', row['label'].lower())
        findings = catalogue['findings']
        self.assertIn('first exact-name match', findings['bitmap_lookup'])
        self.assertIn('does not deduplicate', findings['registration'])
        self.assertIn('Existing process cache prevents reloading', findings['load_gate'])

    def test_original_ok_uses_item_value_and_preserves_unselected_tag(self):
        rows = self.report['observations']['icon_ok']
        self.assertEqual(len(rows), 96)
        self.assertEqual([row['item_integer_value'] for row in rows[:91]], list(range(1, 92)))
        self.assertEqual([row['selected_index'] for row in rows[:91]], list(range(91)))
        for row in rows:
            with self.subTest(index=row['selected_index'], value=row['item_integer_value'],
                              target=row['target'], deferred=row['deferred']):
                selected, result = row['selected_index'] >= 0, row['result']
                self.assertTrue(result['accepted'])
                self.assertEqual(result['tag_type'], 1 if selected else 0)
                self.assertEqual(result['tag_value'], str(row['item_integer_value']) if selected else 'before')
                self.assertEqual(result['index_reads'], 2 if selected else 1)
                self.assertEqual(result['item_reads'], [row['selected_index']] if selected else [])
                self.assertEqual(result['broadcast_marked'], row['deferred'])
                calls = ([{'operation': 'SetTagType', 'value': 1},
                          {'operation': 'SetTagValue', 'value': str(row['item_integer_value'])}]
                         if selected else [])
                if not row['deferred']:
                    calls.append({'operation': 'FinaliseLanguage', 'target': row['target'],
                                  'language': 202, 'supplied_model': None})
                self.assertEqual(result['calls'], calls)
        # Synthetic off-catalogue values expose a distinction from portable admission.
        self.assertEqual(rows[91]['selected_index'], 42)
        self.assertEqual(rows[91]['result']['tag_value'], '1')
        self.assertEqual(rows[92]['result']['tag_value'], '92')

    def test_language_defaults_and_visible_choice_are_distinct(self):
        rows = self.report['observations']['eligibility']
        self.assertEqual([row['language_id'] for row in rows], [None, 0, 1, 14, 64, 116, 202, 255])
        for row in rows:
            with self.subTest(language=row['language_id']):
                self.assertEqual(row['predefined_default'], row['language_id'] == 202)
                self.assertEqual(row['text_default'], row['language_id'] not in (None, 0, 202))
                self.assertEqual(len(row['execute_fragment']), 0 if row['language_id'] is None else 4)
                for visible in row['execute_fragment']:
                    self.assertEqual(visible['icon_hidden'], row['language_id'] != 202)
                    self.assertEqual(visible['checked'],
                                     ('TEXT', 'ICON', 'DYNAMIC', 'FONT')[visible['saved_tag_type']])

    def test_action_catalogue_and_collection_bind_the_same_original(self):
        self.assertEqual(self.report['format'], 'cbus-classic-dlt-icon-dialog-original-v1')
        self.assertEqual(len(self.report['methods']), 9)
        source = self.report['source']
        for key in ('catalogue', 'collection'):
            self.assertEqual(self.report[key]['source_sha256']['CBusToolkit.exe'], source['executable_sha256'])
            self.assertEqual(self.report[key]['source_sha256']['CBusToolkit.map'], source['map_sha256'])
        text = json.loads((ROOT / 'research/fixtures/classic-dlt-language-dialog-original.json').read_text())
        self.assertEqual(self.report['methods']['icon_ok'], text['methods']['text_ok'])
        self.assertEqual(self.report['collection'], text['collection'])
        self.assertIn('this probe hooks finalizers', self.report['rules']['boundary'])
        self.assertIn('does not check catalogue membership', self.report['rules']['handler_validation'])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and
                     os.environ.get('CBUS_CLASSIC_DLT_ICON_REPLAY') == '1',
                     'requires explicit opt-in and verified approved network-denied ICON emulator route')
class IconDialogOriginalReplayTests(unittest.TestCase):
    def test_fresh_source_and_original_action_match_receipt(self):
        from research.classic_dlt_icon_dialog_original import inspect
        executable = Path(os.environ['CBUS_TOOLKIT_EXE'])
        symbols = Path(os.environ.get('CBUS_TOOLKIT_MAP', executable.with_suffix('.map')))
        catalogue = Path(os.environ.get('CBUS_CLASSIC_DLT_ICON_INDEX',
                                        executable.parent / 'Images/DLTP/index.txt'))
        self.assertEqual(inspect(executable, symbols, catalogue), json.loads(FIXTURE.read_text()))


if __name__ == '__main__':
    unittest.main()
