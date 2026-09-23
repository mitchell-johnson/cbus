import hashlib
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.toolkit_preferences_controls import ToolkitPreferenceControls
from cbus_toolkit.toolkit_preferences_preview import render_address_preview
import test_cli_toolkit_preferences as base_cli_tests
from test_toolkit_preferences_controls import initial, display

ROOT = Path(__file__).resolve().parents[1]


def vectors():
    return json.loads((ROOT / 'research/fixtures/toolkit-preferences-preview-vectors.json').read_text())


class PreferencePreviewTests(unittest.TestCase):
    setUp = base_cli_tests.PreferencesCLITests.setUp
    invoke = base_cli_tests.PreferencesCLITests.invoke

    def test_original_preview_four_flag_combinations(self):
        rows = [row for row in vectors()['rows'] if row['operation'] == 'preview']
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertEqual(render_address_preview(tag_hex=bool(row['initial'][0]),
                tag_override=bool(row['initial'][1])), row['label'])

    def test_original_tag_clicks_and_retained_controls(self):
        operations = {'tag-standard': 'rdoTagNamesStandard', 'tag-hex': 'rdoTagNamesUseHex',
                      'tag-value': 'rdoTagNamesUseValue'}
        rows = [row for row in vectors()['rows'] if row['operation'] in operations]
        self.assertEqual(len(rows), 12)
        for row in rows:
            flags = {**display(), 'tag_hex': bool(row['initial'][0]),
                     'tag_override': bool(row['initial'][1])}
            editor = ToolkitPreferenceControls(initial(), flags)
            editor.set_control(operations[row['operation']], True)
            self.assertEqual(editor.address_preview, row['label'])
            self.assertEqual(editor.as_dict()['address_preview'], row['label'])
            self.assertEqual([int(editor.display_values[name]) for name in ('tag_hex', 'tag_override')], row['final'])

    def test_strict_explicit_flags_and_detached_export(self):
        for bad in (None, 0, 1, 2, 'true', [], {}):
            for name in ('tag_hex', 'tag_override'):
                flags = {'tag_hex': False, 'tag_override': False, name: bad}
                with self.assertRaises(ValueError):
                    render_address_preview(**flags)
        editor = ToolkitPreferenceControls(initial(), display())
        previous = editor.address_preview
        exported = editor.as_dict()
        exported['address_preview'] = 'changed'
        self.assertEqual(editor.address_preview, previous)

    def test_cli_controls_and_ordered_plan_expose_preview_without_writes(self):
        before = self.path.read_bytes()
        shown = self.invoke('preferences', 'controls', self.path)
        self.assertEqual(shown['address_preview'], render_address_preview(
            tag_hex=bool(self.state['display_values']['tag_hex']),
            tag_override=bool(self.state['display_values']['tag_override'])))
        planned = self.invoke('preferences', 'plan', self.path, '--edit', 'rdoTagNamesUseHex=true')
        self.assertEqual(planned['controls']['address_preview'], '010 (0Ah) - Level 10')
        self.assertFalse(planned['storage_applied'])
        self.assertEqual(self.path.read_bytes(), before)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires exact original Toolkit executable')
class OriginalPreferencePreviewTests(unittest.TestCase):
    def test_original_preview_formatter_concatenation_and_click_instructions(self):
        from research.toolkit_preferences_preview_original import OriginalPreferencePreview
        original = OriginalPreferencePreview(os.environ['CBUS_TOOLKIT_EXE'])
        fixture = vectors()
        self.assertEqual(original.executable_sha256, fixture['executable_sha256'])
        for expected in fixture['rows']:
            actual = original.run(expected['operation'], bool(expected['initial'][0]), bool(expected['initial'][1]))
            with self.subTest(operation=expected['operation'], initial=expected['initial']):
                for name in ('operation', 'initial', 'final', 'label', 'original_number_calls'):
                    self.assertEqual(actual[name], expected[name])
                self.assertEqual(actual['fixtures'], expected['fixture_calls'])
                digest = hashlib.sha256(json.dumps(actual['executed_instructions'], sort_keys=True).encode()).hexdigest()
                self.assertEqual(digest, expected['executed_instructions_sha256'])


if __name__ == '__main__':
    unittest.main()
