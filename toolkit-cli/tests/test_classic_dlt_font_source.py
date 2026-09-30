"""Static source facts for FONT preparation; no CPU or renderer execution."""
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/classic-dlt-font-source.json'


class FontSourceEvidenceTests(unittest.TestCase):
    def test_descriptor_and_gui_are_different_bounds(self):
        report = json.loads(FIXTURE.read_text())
        self.assertEqual(report['format'], 'cbus-classic-dlt-font-source-v1')
        descriptor = report['descriptor']
        self.assertEqual(descriptor['fields'], ['image_id', 'version', 'font_name', 'size_text',
                                               'charset_name', 'style', 'x', 'y', 'invert', 'text'])
        self.assertIsNone(descriptor['escaping'])
        self.assertEqual(descriptor['version_written'], '1')
        self.assertIn('Exactly9 commas only', descriptor['predicate'])
        self.assertIn('1024', descriptor['parser'])
        self.assertIn('retains existing TFont style', descriptor['style'])
        self.assertEqual(descriptor['size_default'], 8)
        self.assertEqual(descriptor['position_default'], 0)
        self.assertEqual(descriptor['charset_fallback'], 1)
        self.assertEqual(len(descriptor['charset_values']), 14)
        controls = report['form']['controls']
        self.assertEqual(controls['edtLabelFont']['Properties.MaxLength'], 20)
        self.assertEqual(controls['cmbFontSize']['Properties.Items.Strings'],
                         [str(size) for size in range(6, 19)] + ['20'])
        self.assertEqual(controls['rgSaveFontOption']['Items.Strings'], ['Update Existing', 'Create New'])

    def test_persistence_requires_bitmap_codepage_and_fresh_project(self):
        report = json.loads(FIXTURE.read_text())
        persistence = report['persistence']
        self.assertIn('rejects IDs<=0', report['allocation']['zero_id_mismatch'])
        self.assertEqual(persistence['save_order'], ['save graphic bitmap', 'save project graphic index'])
        self.assertEqual(persistence['ansi']['codepage_argument'], 0)
        self.assertEqual(persistence['ansi']['flags'], 0)
        self.assertIsNone(persistence['ansi']['used_default_character_pointer'])
        self.assertIn('without clearing existing items', persistence['reload'])
        self.assertIn('not the original FONT save', persistence['coupling'])
        rendering = report['rendering']
        self.assertEqual(rendering['intermediate_size'], [82, 40])
        self.assertEqual(rendering['final_size'], [62, 16])
        self.assertEqual(rendering['windows_apis'], ['GetTextExtentPoint32', 'ExtTextOut'])
        self.assertIn('not proof of transmitted bitmap width', rendering['wire_boundary'])
        self.assertEqual(rendering['y_correction_by_size_0_to_20'],
                         [0, 5, 5, 5, 5, 5, 5, 4, 2, 1, 0, -1, -2, -2, -3, -4, -4, -5, -5, -8, -8])
        self.assertTrue(report['boundary']['static_only'])
        self.assertTrue(all(not value for key, value in report['boundary'].items() if key != 'static_only'))
        self.assertEqual(len(report['methods']), 41)
        previous = json.loads((ROOT / 'research/fixtures/classic-dlt-icon-dialog-original.json').read_text())
        self.assertEqual(report['source'], previous['source'])
        self.assertEqual(report['form']['sha256'],
                         'd55ee037540cebd52dfa04c42efaa5ed27ef0da627511bc31a38f0d0a0aa15be')


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires pinned original EXE/MAP for static inspection')
class FontSourceStaticInputTests(unittest.TestCase):
    def test_fresh_static_inspection_matches_receipt(self):
        from research.classic_dlt_font_source import inspect
        executable = Path(os.environ['CBUS_TOOLKIT_EXE'])
        symbols = Path(os.environ.get('CBUS_TOOLKIT_MAP', executable.with_suffix('.map')))
        self.assertEqual(inspect(executable, symbols), json.loads(FIXTURE.read_text()))


if __name__ == '__main__':
    unittest.main()
