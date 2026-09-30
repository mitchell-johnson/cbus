"""Original TEXT acceptance and independent collection/network source receipt."""
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/classic-dlt-language-dialog-original.json'


class LanguageDialogOriginalEvidenceTests(unittest.TestCase):
    def test_entire_input_unicode_guard_precedes_utf16_truncation(self):
        report = json.loads(FIXTURE.read_text())
        self.assertEqual(report['format'], 'cbus-classic-dlt-language-dialog-original-v1')
        self.assertEqual(len(report['observations']), 15)
        for row in report['observations']:
            with self.subTest(text=row['input'], confirm=row['confirm_non_latin1']):
                result = row['result']
                non_latin1 = any(ord(char) > 255 for char in row['input'])
                accepted = not non_latin1 or row['confirm_non_latin1']
                self.assertEqual(result['accepted'], accepted)
                self.assertEqual(result['unicode_prompts'], int(non_latin1))
                if accepted:
                    expected = (row['input'].encode('utf-16-le')[:40].decode('utf-16-le', 'surrogatepass')
                                if row['input'] else '<Default>')
                    self.assertEqual(result['tag_value'], expected)
                    self.assertEqual(result['tag_type'], 0)
                    self.assertEqual(result['copies'], [{'start': 1, 'utf16_count': 20}] if row['input'] else [])
                else:
                    self.assertEqual(result['tag_value'], 'before')
                    self.assertEqual(result['tag_type'], 3)
                    self.assertEqual(result['copies'], [])
                finalised = accepted and not row['deferred']
                self.assertEqual(result['broadcast_marked'], not finalised)
                self.assertEqual(result['calls'], [{
                    'operation': 'FinaliseLanguage', 'target': row['target'],
                    'language': 'selected flavour language', 'supplied_model': None}] if finalised else [])

    def test_collection_network_and_button_use_same_pinned_inputs(self):
        report = json.loads(FIXTURE.read_text())
        for key, count in (('collection', 30), ('network', 20)):
            self.assertEqual(report[key]['source_sha256']['CBusToolkit.exe'], report['source']['executable_sha256'])
            self.assertEqual(report[key]['source_sha256']['CBusToolkit.map'], report['source']['map_sha256'])
            self.assertEqual(len(report[key]['methods']), count)
        collection = report['collection']
        self.assertIn('optional supplied GroupLanguage', collection['arguments']['FinaliseLanguage']['ecx'])
        self.assertIn('StorageDelete, then Extract', collection['rules']['finalise_delete'])
        self.assertIn('Existing fallback flavour0 remains flavour0', collection['rules']['legacy_identity'])
        self.assertIn('compare saved type code and saved value against full model', collection['rules']['finalise_update'])
        examples = report['network']['findings']['fresh_registered_default_examples']
        self.assertEqual(examples[1], {'xml': 'ID0=2 only', 'cache_ids': [1], 'selected_id': 2})
        self.assertEqual(examples[2], {'xml': 'ID2 only', 'cache_ids': [2, 1], 'selected_id': 1})


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires pinned original Toolkit EXE/MAP')
class LanguageDialogOriginalReplayTests(unittest.TestCase):
    def test_fresh_source_and_original_button_match_receipt(self):
        from research.classic_dlt_language_dialog_original import inspect
        executable = Path(os.environ['CBUS_TOOLKIT_EXE'])
        symbols = Path(os.environ.get('CBUS_TOOLKIT_MAP', executable.with_suffix('.map')))
        self.assertEqual(inspect(executable, symbols), json.loads(FIXTURE.read_text()))


if __name__ == '__main__':
    unittest.main()
