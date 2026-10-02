"""Independent SceneName literal/static evidence; never load the vendor CLR."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_names import FIXED_SUGGESTION_NAMES, assign_name, load_names, scene_name, scene_names_view
from cbus_toolkit.edlt_scene_name_control import run_scene_name_control
from cbus_toolkit.edlt_static_grid import decode_utf8

ROOT = Path(__file__).resolve().parents[1]
ANNEX_PATH = ROOT / 'research/fixtures/edlt-scene-name-source-annex.json'
_spec = importlib.util.spec_from_file_location('edlt_scene_name_static', ROOT / 'research/edlt_scene_name_static.py')
static = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(static)
ANNEX = json.loads(ANNEX_PATH.read_text())
VECTORS = json.loads((ROOT / 'research/fixtures/edlt-scene-name-vectors.json').read_text())


class SceneNameStaticEvidenceTests(unittest.TestCase):
    def test_exact_managed_and_decompiled_symbol_spans(self):
        methods = ANNEX['managed_method_spans']
        self.assertEqual(len(methods), 32)
        self.assertEqual({row['symbol'] for row in methods}, set(static.LOGIC_METHODS + static.UI_METHODS))
        self.assertEqual(len(ANNEX['decompiled_source_symbols']), 26)
        self.assertEqual(len(ANNEX['framework_source_symbols']), 7)
        for row in methods:
            with self.subTest(symbol=row['symbol']):
                self.assertEqual(row['metadata_runtime'], 'v4.0.30319')
                self.assertGreaterEqual(row['body_bytes'], row['header_bytes'] + row['code_bytes'])
                self.assertRegex(row['body_sha256'], r'^[0-9a-f]{64}$')
                self.assertRegex(row['il_sha256'], r'^[0-9a-f]{64}$')
                self.assertEqual(int(row['token'], 16) >> 24, 6)
                self.assertTrue(row['static_decode_only'])
                self.assertTrue(all(0 <= call['il_offset'] < row['code_bytes'] for call in row['calls']))
        self.assertEqual(len(ANNEX['static_checks']), 23)
        self.assertTrue(all(check['passed'] for check in ANNEX['static_checks']))
        chains = {check['id']: check for check in ANNEX['static_checks']}
        self.assertEqual(chains['allocate-before-old-reference-reassignment']['ordered_call_suffixes'], ['GetStaticTextIndex', 'set_NameIndex'])
        self.assertEqual(chains['static-name-save-before-scene-serialization']['ordered_call_suffixes'], ['SaveStaticText', 'SaveScenes'])

    def test_sanitized_pins_and_unexecuted_boundaries(self):
        inputs = ANNEX['original_inputs']
        self.assertEqual(len(inputs), 13)
        self.assertEqual({row['path']: row['sha256'] for row in inputs if row['role'] == 'retained-original-static-input'}, static.VENDOR_PINS)
        for row in inputs:
            self.assertFalse(row['path'].startswith('/'))
            self.assertNotIn('..', Path(row['path']).parts)
        limits = ANNEX['limits']
        self.assertEqual(limits['original_instructions_executed'], 0)
        self.assertEqual(limits['framework_instructions_executed'], 0)
        for name in ('host_gui_executed', 'original_host_framework_binary_verified', 'physical_device_verified', 'native_original_execution_acceptance', 'control_embedded_nul_admitted', 'control_unpaired_surrogate_admitted', 'culture_collation_or_auto_complete_index_verified', 'asynchronous_framework_dispatch_verified', 'implicit_pending_close_verified', 'source_property_arbitrary_dotnet_strings_generalized'):
            self.assertFalse(limits[name])
        for coordinate in ('/private/', '/Volumes/', '/Users/', 'il_hex'):
            self.assertNotIn(coordinate, ANNEX_PATH.read_text())

    def test_source_bounding_ignores_string_and_comment_braces(self):
        raw = b'// header\npublic string Name\n{\n// }\nvar a = "}"; /* { */\nreturn a;\n}\nvoid Next() {}\n'
        row = static.source_span(raw, 'Name', 'public string Name')
        expected = b'public string Name\n{\n// }\nvar a = "}"; /* { */\nreturn a;\n}'
        self.assertEqual((row['start_line'], row['end_line']), (2, 7))
        self.assertEqual(row['sha256'], hashlib.sha256(expected).hexdigest())
        with self.assertRaises(ValueError): static.source_span(raw + raw, 'Name', 'public string Name')
        with self.assertRaises(ValueError): static.require_order(['SaveScenes', 'SaveStaticText'], ['SaveStaticText', 'SaveScenes'], 'save')

    def test_managed_tiny_fat_sections_and_operand_refusal(self):
        image = object.__new__(static.ManagedImage)
        image.pe = SimpleNamespace(get_offset_from_rva=lambda rva: rva)
        image.methods = {'Tiny': [(1, (1,))]}; image.data = b'\0\x0a\x1e\x2a'
        row = image.method('Tiny')
        self.assertEqual((row['header_bytes'], row['code_bytes'], row['body_bytes']), (1, 2, 3))
        self.assertEqual(row['il_sha256'], hashlib.sha256(b'\x1e\x2a').hexdigest())
        self.assertEqual(image.instructions('Tiny')['integer_constants'], [{'il_offset': 0, 'value': 8}])
        with self.assertRaises(ValueError): image.method('Absent')
        image.methods = {'Fat': [(1, (4,))]}
        image.data = b'\0\0\0\0\x0b\x30\x08\0\x05\0\0\0\0\0\0\0\x28\x01\0\0\x06\0\0\0\x01\x04\0\0'
        row = image.method('Fat')
        self.assertEqual((row['header_bytes'], row['code_bytes'], row['extra_sections']), (12, 5, 1))
        self.assertEqual(row['body_bytes'], 24)
        image.counts = {6: 1}; image.tables = {}
        with self.assertRaises(ValueError): image.row(6, 0)
        with self.assertRaises(ValueError): image.row(6, 2)
        image.data = b'\x28\x01'
        with patch.object(image, 'method', return_value={'file_offset': 0, 'header_bytes': 0, 'code_bytes': 2}):
            with self.assertRaisesRegex(ValueError, 'operand overflow'): image.instructions('broken')

    def test_static_pinned_regeneration(self):
        vendor = os.environ.get('CBUS_SCENE_NAME_STATIC_VENDOR_ROOT')
        framework = os.environ.get('CBUS_SCENE_NAME_STATIC_FRAMEWORK_ROOT')
        if not vendor or not framework:
            self.skipTest('Explicit private pinned SceneName vendor/framework sources are not configured')
        rendered = (json.dumps(static.recover(Path(vendor), Path(framework)), indent=2, ensure_ascii=False) + '\n').encode()
        self.assertEqual(rendered, ANNEX_PATH.read_bytes())


class SceneNameLiteralOracles(unittest.TestCase):
    def test_literal_rows_and_eight_scene_header_geometry(self):
        starts = [0, 5, 10, 15, 20, 25, 30, 35]
        self.assertEqual(VECTORS['base_empty_scenes']['scene_starts'], starts)
        for case in VECTORS['public_name_cases']:
            with self.subTest(case=case['name']):
                before, after = case['initial_static_rows_hex'], case['expected_static_rows_hex']
                self.assertEqual(len(before), 64); self.assertEqual(len(after), 64)
                self.assertTrue(all(len(bytes.fromhex(row)) == 64 for row in before + after))
                bucket = bytes.fromhex(case['expected_scene_bucket_hex'])
                self.assertEqual(len(bucket), 232)
                self.assertEqual(bucket[:5], bytes([2, 0, 255, 255, case['expected_name_index']]))
                self.assertEqual(bucket[5:40], bytes([2, 0, 255, 255, 255]) * 7)
                self.assertEqual(bucket[40:], b'\xff' * 192)
                self.assertEqual(case['expected_scene_starts'], starts)
                self.assertEqual(case['expected_scene_count'], 8)
                self.assertEqual(after[63], before[63])
                changed = [index for index in range(64) if before[index] != after[index]]
                self.assertEqual(changed, [] if case['name'] in ('unicode-blank-clear', 'malformed-exact-reuse') else [62])
        cases = {case['name']: case for case in VECTORS['public_name_cases']}
        self.assertEqual(cases['ascii64']['expected_static_rows_hex'][62], '41' * 63 + '00')
        self.assertEqual(cases['multibyte64']['expected_static_rows_hex'][62], 'c481' * 31 + 'c400')
        self.assertEqual(cases['split63']['expected_static_rows_hex'][62], '41' * 62 + 'c400')
        self.assertEqual(cases['astral64']['expected_static_rows_hex'][62], 'f09f9880' * 15 + 'f09f9800')

    def test_fixed_suggestion_membership_only(self):
        names = VECTORS['fixed_suggestion_names']
        self.assertEqual(names, ANNEX['fixed_suggestions']['names'])
        self.assertEqual(names, list(FIXED_SUGGESTION_NAMES))
        self.assertEqual(len(set(names)), 64)
        self.assertFalse(ANNEX['fixed_suggestions']['ordering_proved'])
        self.assertEqual(ANNEX['fixed_suggestions']['value'], -1)

    def test_whitespace_literals_and_180e_ambiguity(self):
        values = {f'StaticTextString{i}': (0,) * 64 for i in range(64)}; names = load_names(values)
        profile = ANNEX['framework_profile']
        self.assertEqual(profile['name'], 'net4-stable-whitespace')
        self.assertEqual(profile['version_ambiguous'], ['U+180E'])
        white = [case['codepoint'] for case in VECTORS['whitespace_cases'] if case.get('blank')]
        self.assertEqual(white, profile['stable_white_codepoints']); self.assertEqual(len(white), 25)
        for case in VECTORS['whitespace_cases']:
            with self.subTest(text=repr(case['text'])):
                if 'refused' in case:
                    with self.assertRaisesRegex(EdltError, 'Framework Unicode table'):
                        assign_name(names, 63, case['text'], values=values, used_indices=lambda: (63, 255))
                else:
                    result = assign_name(names, 63, case['text'], values=values, used_indices=lambda: (63, 255))
                    self.assertEqual(result.index, 255 if case['blank'] else 62)
                    if not case['blank']: self.assertEqual(result.names[62], case['text'])
        self.assertTrue('\x1c'.strip() == '')  # Deliberate Python/.NET distinction.
        self.assertEqual(profile['stable_nonwhite_edges'][0], 'U+001C')

    def test_literal_property_rows_retention_fallback_and_fresh_load(self):
        for case in VECTORS['public_name_cases']:
            with self.subTest(case=case['name']):
                values = {f'StaticTextString{i}': tuple(bytes.fromhex(row)) for i, row in enumerate(case['initial_static_rows_hex'])}
                assigned = assign_name(load_names(values), 63, case['requested_name'], values=values, used_indices=lambda: (63, 255))
                self.assertEqual(assigned.index, case['expected_name_index'])
                self.assertEqual(scene_name(assigned.names, assigned.index), case['expected_retained_name'])
                after = {**values, **assigned.changes}
                self.assertEqual([bytes(after[f'StaticTextString{i}']).hex() for i in range(64)], case['expected_static_rows_hex'])
                self.assertEqual(scene_name(load_names(after), assigned.index), case['expected_fresh_name'])
                view = scene_names_view(assigned.names, (assigned.index, *(255,) * 7))
                self.assertEqual([{'value': row['value'], 'name': row['name']} for row in view], case['expected_scene_names_value'])
                if case['name'] == 'malformed-exact-reuse': self.assertTrue(assigned.reused); self.assertEqual(dict(assigned.changes), {})
        for row in VECTORS['framework_decoding']:
            with self.subTest(hex=row['hex']): self.assertEqual(decode_utf8(bytes.fromhex(row['hex'])), row['text'])

    def test_independent_literal_callback_read_write_sequences(self):
        for case in VECTORS['control_histories']:
            with self.subTest(history=case['name']):
                owned = {'name': case['initial_name']}; known = [owned['name'], 'New', *VECTORS['fixed_suggestion_names']]
                def setter(text): owned['name'] = text; return {'accepted': text}
                if 'refused' in case:
                    with self.assertRaisesRegex(EdltError, case['refused']):
                        run_scene_name_control(case['events'], get_name=lambda: owned['name'], set_name=setter, known_names=known)
                    continue
                result = run_scene_name_control(case['events'], get_name=lambda: owned['name'], set_name=setter, known_names=known).as_dict()
                self.assertEqual([entry['action'] for entry in result['binding_callbacks']], case['expected_actions'])
                self.assertEqual(result['bound_name'], case['expected_bound_name'])
                self.assertEqual(result['state'], {'text': case['expected_text'], 'pending': case['expected_pending'], 'suppress_next_selection': case['expected_suppression']})
                self.assertFalse(result['host_gui_executed']); self.assertFalse(result['suggestion_order_inferred'])


if __name__ == '__main__': unittest.main()
