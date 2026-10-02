"""Literal source-property/name-cache oracles, independent of PP producers."""
from dataclasses import replace
import json
import unittest
from pathlib import Path

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_manager import EdltSceneManager
from cbus_toolkit.edlt_scene_names import FIXED_SUGGESTION_NAMES, assign_name, scene_name, scene_names_view
from cbus_toolkit import edlt_static_grid as grid
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import fixture
from tests.test_edlt_scene_manager import cache, op


def name_control(text, *, scene=1, commit='enter'):
    return op('scene-name-control', scene, events=[{'event': 'input', 'text': text},
                                                 {'event': commit}])


def source_values(spec, *, indices=(255,) * 8, rows=None):
    source = dict(Session(spec).current)
    source.update({f'StaticTextString{index}': (0,) * 64 for index in range(64)})
    for index, row in (rows or {}).items():
        source[f'StaticTextString{index}'] = tuple(row)
    source.update(SceneCount=(8,), PrimaryApplication=(56,), SecondaryApplication=(57,),
                  SceneBucket=tuple(bytes(value for index in indices for value in
                                          (2, 0, 255, 255, index)).ljust(232, b'\xff')))
    source.update({f'Scene{slot}StartAddress': ((slot - 1) * 5,) for slot in range(1, 9)})
    return source


class SceneNamesTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltSceneManager(self.spec)
        self.source = source_values(self.spec)
        self.state = self.editor.load(self.source, metadata=cache())

    def loaded(self, *, indices=(255,) * 8, rows=None):
        return self.editor.load(source_values(self.spec, indices=indices, rows=rows), metadata=cache())

    def test_all64_fallback_names_and_eight_ordinal_getters_are_read_only(self):
        rows = {0: b'Lamp\0'.ljust(64, b'\0'), 1: b'\xe0\x80A\0'.ljust(64, b'\0'),
                2: b'\xed\xa0\x80\0'.ljust(64, b'\0'), 3: b'\xf0\x9f\x98\x80\0'.ljust(64, b'\0'),
                4: b'Before\0After'.ljust(64, b'\0'), 5: b'A' * 64,
                63: b'Lamp\0'.ljust(64, b'\0')}
        state = self.loaded(indices=(0, 1, 2, 3, 4, 5, 63, 255), rows=rows)
        before = state.as_dict()
        expected = ['Lamp', '\ufffdA', '\ufffd\ufffd', '\U0001f600', 'Before', 'A' * 64, 'Lamp', '']
        outcome = self.editor.edit(state, operations=[op('get-name', scene) for scene in range(1, 9)])
        self.assertEqual([json.loads(row)['value'] for row in outcome.operation_results], expected)
        self.assertEqual([row['name'] for row in before['scene_names_view']],
                         [str(slot) + ' - ' + text for slot, text in enumerate(expected, 1)])
        self.assertEqual([row['value'] for row in before['scene_names_view']], list(range(8)))
        self.assertEqual(len(self.editor.retained_names(state)), 64)
        self.assertEqual(before['static_names'][6:63], [''] * 57)
        self.assertEqual(state.as_dict(), before)
        self.assertEqual(dict(outcome.state.static_text_overlay), {})
        self.assertEqual([scene.name_index for scene in outcome.state.scenes], [0, 1, 2, 3, 4, 5, 63, 255])
        self.assertEqual(scene_name(state.static_names, 64), '')
        with self.assertRaises(EdltError):
            scene_names_view(state.static_names, (64, 255, 255, 255, 255, 255, 255, 255))

    def test_source_property_retains_old63_while_additive_releases_it(self):
        state = self.loaded(indices=(63, 255, 255, 255, 255, 255, 255, 255),
                            rows={63: b'Previous\0'.ljust(64, b'\0')})
        source = self.editor.edit(state, operations=[name_control('New')]).state
        additive = self.editor.edit(state, operations=[op('set-name-text', text='New')]).state
        self.assertEqual(source.scenes[0].name_index, 62)
        self.assertEqual(source.static_names[63], 'Previous')
        self.assertEqual(source.static_names[62], 'New')
        self.assertEqual(bytes(source.static_text_overlay['StaticTextString62']), b'New\0' + b'\0' * 60)
        self.assertEqual(additive.scenes[0].name_index, 63)
        self.assertEqual(state.static_names[63], 'Previous')
        self.assertEqual(source.static_text_evidence()['allocations'][0]['used_indices'], [63, 255])

    def test_full_cached_ascii_and_multibyte_names_survive_commit_and_fresh_load_truncates(self):
        for text, expected in (('A' * 64, b'A' * 63 + b'\0'),
                               ('\u0101' * 32, b'\xc4\x81' * 31 + b'\xc4\0'),
                               ('\U0001f600' * 32, b'\xf0\x9f\x98\x80' * 15 + b'\xf0\x9f\x98\0')):
            with self.subTest(text=text):
                edited = self.editor.edit(self.state, operations=[name_control(text)]).state
                self.assertEqual(edited.scenes[0].name_index, 63)
                self.assertEqual(self.editor.scene_name(edited, scene=1), text)
                self.assertEqual(bytes(edited.static_text_overlay['StaticTextString63']), expected)
                plan = self.editor.prepare_save(edited)
                self.assertEqual(plan.terminal.static_names[63], text)
                self.assertEqual(plan.as_dict()['terminal']['scene_names_view'][0]['name'], '1 - ' + text)
                self.assertEqual(bytes(plan.before_save['StaticTextString63']), expected)
                reloaded = self.editor.load(plan.before_save, metadata=cache())
                decoded = 'A' * 63 if text[0] == 'A' else '\u0101' * 31 + '\ufffd' if text[0] == '\u0101' else '\U0001f600' * 15 + '\ufffd'
                self.assertEqual(self.editor.scene_name(reloaded, scene=1), decoded)
        for text in ('A' * 65, '\U0001f600' * 33, '\ud800'):
            with self.subTest(invalid=repr(text)), self.assertRaises(EdltError):
                self.editor.edit(self.state, operations=[name_control(text)])

    def test_loaded64_and_fallback_reuse_precedes_capacity_and_preserves_original_pp(self):
        for row, text in ((b'A' * 64, 'A' * 64), (b'\xe0\x80A\0'.ljust(64, b'\0'), '\ufffdA')):
            with self.subTest(text=text):
                source = source_values(self.spec, rows={63: row})
                for widget in range(1, 14):
                    source[f'Widget{widget}WidgetType'] = (4,)
                    source[f'Widget{widget}WidgetByteValue1'] = (53,)
                    for slot, offset in enumerate((9, 10, 11, 12, 13)):
                        source[f'Widget{widget}WidgetByteValue{offset}'] = (min(63, (widget - 1) * 5 + slot),)
                source['Widget14WidgetType'] = (255,)
                state = self.editor.load(source, metadata=cache())
                result = self.editor.edit(state, operations=[name_control(text)]).state
                self.assertEqual(result.scenes[0].name_index, 63)
                self.assertTrue(result.static_text_evidence()['allocations'][0]['reused'])
                self.assertEqual(dict(result.static_text_overlay), {})
                self.assertEqual(result.loaded.after_load['StaticTextString63'], tuple(row))
                with self.assertRaisesRegex(EdltError, 'full'):
                    self.editor.edit(state, operations=[name_control('Unmatched')])

    def test_stable_net4_blank_and_version_dependent180e_refusal(self):
        whitespace = [*range(9, 14), 32, 133, 160, 5760, *range(8192, 8203),
                      8232, 8233, 8239, 8287, 12288]
        self.assertEqual(len(whitespace), 25)
        for text in ('', *map(chr, whitespace), ''.join(map(chr, whitespace))):
            with self.subTest(blank=repr(text)):
                result = self.editor.edit(self.state, operations=[name_control(text)]).state
                self.assertEqual(result.scenes[0].name_index, 255)
                self.assertEqual(dict(result.static_text_overlay), {})
        for text in ('\x1c', '\x1d', '\x1e', '\x1f', '\u200b', '\ufeff', '\u180eX', ' X '):
            with self.subTest(nonblank=repr(text)):
                result = self.editor.edit(self.state, operations=[name_control(text)]).state
                self.assertEqual(result.scenes[0].name_index, 63)
                self.assertEqual(self.editor.scene_name(result, scene=1), text)
        for text in ('\u180e', ' \u180e\t'):
            with self.subTest(ambiguous=repr(text)), self.assertRaisesRegex(EdltError, 'Framework Unicode table'):
                self.editor.edit(self.state, operations=[name_control(text)])

    def test_source_null_noop_and_nul_storage_preserve_full_name(self):
        result = assign_name(self.state.static_names, 63, None, values=self.state.loaded.after_load,
                             used_indices=lambda: self.fail('Null assignment must not enumerate references'))
        self.assertEqual(result.index, 63); self.assertTrue(result.ignored_null)
        self.assertIs(result.names, self.state.static_names)
        assigned = assign_name(self.state.static_names, 255, 'A\0B', values=self.state.loaded.after_load,
                               used_indices=lambda: (255,))
        self.assertEqual(scene_name(assigned.names, assigned.index), 'A\0B')
        self.assertEqual(bytes(assigned.changes['StaticTextString63']), b'A' + b'\0' * 63)
        with self.assertRaisesRegex(EdltError, 'NUL'):
            self.editor.edit(self.state, operations=[name_control('A\0B')])
        with self.assertRaises(EdltError):
            self.editor.edit(self.state, operations=[op('set-name-text', text='A\0B')])

    def test_pending_input_is_reviewable_but_composition_requires_explicit_callback(self):
        state = self.editor.edit(self.state, operations=[op('scene-name-control', events=[{'event': 'input', 'text': 'Pending'}])]).state
        self.assertTrue(state.as_dict()['pending_name_controls'])
        self.assertEqual(self.editor.scene_name(state, scene=1), '')
        self.assertEqual(state.name_controls[0].text, 'Pending')
        self.assertEqual(dict(state.static_text_overlay), {})
        for prepare in (self.editor.prepare_composition, self.editor.prepare_save):
            with self.assertRaisesRegex(EdltError, 'Pending SceneName'): prepare(state)
        with self.assertRaisesRegex(EdltError, 'Pending SceneName'):
            self.editor.edit(state, operations=[op('scene-name-control', events=[{'event': 'close'}])])
        committed = self.editor.edit(state, operations=[op('scene-name-control', events=[{'event': 'leave'}])]).state
        self.assertFalse(committed.as_dict()['pending_name_controls'])
        self.assertEqual(self.editor.scene_name(committed, scene=1), 'Pending')
        self.editor.prepare_save(committed)
        refreshed = self.editor.edit(state, operations=[op('scene-name-control', events=[{
            'event': 'list-refresh', 'change_type': 'reset', 'new_index': 0, 'old_index': -1, 'selected_index': 1}])]).state
        self.assertFalse(refreshed.as_dict()['pending_name_controls'])
        self.assertEqual(refreshed.name_controls[0].text, '')
        self.assertEqual(dict(refreshed.static_text_overlay), {})

    def test_suppression_and_per_scene_continuation_share_issued_names_only(self):
        state = self.loaded(rows={7: b'Known\0'.ljust(64, b'\0')})
        first = self.editor.edit(state, operations=[op('scene-name-control', events=[{'event': 'arrow-preview', 'key': 'left'}])]).state
        selected = self.editor.edit(first, operations=[op('scene-name-control', events=[{
            'event': 'selected-name', 'selected_index': 7, 'name': 'Known'}])]).state
        self.assertTrue(selected.name_controls[0].pending)
        self.assertFalse(selected.name_controls[0].suppress_next_selection)
        self.assertEqual(selected.scenes[0].name_index, 255)
        final = self.editor.edit(selected, operations=[name_control('Other', scene=2),
            op('scene-name-control', events=[{'event': 'enter'}]), op('get-name'), op('get-name', 2)])
        self.assertEqual([json.loads(row)['value'] for row in final.operation_results[-2:]], ['Known', 'Other'])
        self.assertEqual(final.state.scenes[0].name_index, 7)
        self.assertEqual(final.state.scenes[1].name_index, 63)

    def test_new_names_are_visible_to_later_selection_callbacks_in_same_event_list(self):
        result = self.editor.edit(self.state, operations=[op('scene-name-control', events=[
            {'event': 'input', 'text': 'First'}, {'event': 'enter'},
            {'event': 'selected-name', 'selected_index': 63, 'name': 'First'}])])
        self.assertEqual(result.state.scenes[0].name_index, 63)
        self.assertEqual(len(result.state.name_allocations), 2)
        self.assertTrue(json.loads(result.state.name_allocations[1])['reused'])

    def test_names_and_controls_are_issuer_bound_and_exports_cannot_resume(self):
        issued = self.editor.edit(self.state, operations=[name_control('Original')]).state
        for fake in (replace(issued), replace(issued, static_names=('',) * 64), issued.as_dict()):
            with self.subTest(fake=type(fake).__name__), self.assertRaises(EdltError):
                self.editor.retained_names(fake)
        with self.assertRaises(EdltError): EdltSceneManager(self.spec).retained_names(issued)
        for injected in ('static_names', 'name_controls', 'state', 'resume'):
            with self.subTest(injected=injected), self.assertRaises(EdltError):
                self.editor.edit(self.state, operations=[{**name_control('New'), injected: issued.as_dict()}])
        with self.assertRaisesRegex(EdltError, 'intact'):
            object.__setattr__(issued, 'static_names', ('Injected',) * 64)
            self.editor.scene_name(issued, scene=1)

    def test_parent_names_are_copied_once_and_speculative_models_do_not_mutate_parent(self):
        with grid.scope():
            grid.initialize(self.state.loaded.after_load)
            parent = grid.current(self.state.loaded.after_load)
            parent.names[63] = 'Earlier full name' * 5
            state = self.editor.load(self.source, metadata=cache())
            self.assertEqual(state.static_names[63], 'Earlier full name' * 5)
            parent.names[63] = 'Later'
            self.assertEqual(state.static_names[63], 'Earlier full name' * 5)
            source = self.editor.edit(state, operations=[name_control('New')]).state
            additive = self.editor.edit(state, operations=[op('set-name-text', text='Additive')]).state
            self.editor.validate(source); self.editor.prepare_composition(source)
            self.assertEqual(parent.names[63], 'Later')
            self.assertEqual(source.static_names[63], 'New')
            self.assertEqual(additive.static_names[63], 'Additive')
        self.assertIsNone(grid.current(self.state.loaded.after_load))

    def test_copy_clear_and_indexed_names_views_follow_shared_retained_name(self):
        edited = self.editor.edit(self.state, operations=[name_control('Shared'), op('copy'), op('paste', 2), op('get-name', 2)]).state
        self.assertEqual(self.editor.scene_name(edited, scene=2), 'Shared')
        self.assertEqual([row['scene_name'] for row in edited.as_dict()['scene_names_view'][:2]], ['Shared', 'Shared'])
        cleared = self.editor.edit(edited, operations=[op('clear-scene')]).state
        self.assertEqual(self.editor.scene_name(cleared, scene=1), '')
        self.assertEqual(self.editor.scene_name(cleared, scene=2), 'Shared')
        self.assertEqual(cleared.static_names[63], 'Shared')

    def test_capacity_keeps_old_reference_until_assignment_and_additive_contract_stays_strict(self):
        source = source_values(self.spec, indices=(63, 255, 255, 255, 255, 255, 255, 255),
                               rows={63: b'Old\0'.ljust(64, b'\0')})
        for widget in range(1, 14):
            source[f'Widget{widget}WidgetType'] = (4,)
            source[f'Widget{widget}WidgetByteValue1'] = (53,)
            for slot, offset in enumerate((9, 10, 11, 12, 13)):
                source[f'Widget{widget}WidgetByteValue{offset}'] = (min(61, (widget - 1) * 5 + slot),)
        source['Widget14WidgetType'] = (255,)
        state = self.editor.load(source, metadata=cache())
        self.assertEqual(tuple(self.editor.common.static_references(state.loaded.after_load)), (*range(62), 63, 255))
        with self.assertRaisesRegex(EdltError, 'full'):
            self.editor.edit(state, operations=[name_control('New')])
        additive = self.editor.edit(state, operations=[op('set-name-text', text='New')]).state
        self.assertEqual(additive.scenes[0].name_index, 63)
        for text in ('', '  ', 'A' * 64, '\u0101' * 32):
            with self.subTest(additive=text), self.assertRaises(EdltError):
                self.editor.edit(self.state, operations=[op('set-name-text', text=text)])
        malformed = self.loaded(rows={0: b'\xe0\x80\0'.ljust(64, b'\0')})
        with self.assertRaisesRegex(EdltError, 'invalid UTF-8'):
            self.editor.edit(malformed, operations=[op('set-name-text', text='New')])

    def test_fixed_source_suggestion_membership_is_complete_without_index_order_claim(self):
        vector = json.loads((Path(__file__).resolve().parents[1] / 'research/fixtures/edlt-scene-name-vectors.json').read_text())
        self.assertEqual(list(FIXED_SUGGESTION_NAMES), vector['fixed_suggestion_names'])
        self.assertEqual(len(FIXED_SUGGESTION_NAMES), 64)
        for name in FIXED_SUGGESTION_NAMES:
            with self.subTest(name=name):
                result = self.editor.edit(self.state, operations=[op('scene-name-control', events=[{
                    'event': 'selected-name', 'selected_index': 999, 'name': name}])])
                self.assertEqual(self.editor.scene_name(result.state, scene=1), name)
                self.assertEqual(result.state.scenes[0].name_index, 63)
                self.assertFalse(json.loads(result.operation_results[0])['scene_name_control']['suggestion_order_inferred'])
        with self.assertRaisesRegex(EdltError, 'ordinal member'):
            self.editor.edit(self.state, operations=[op('scene-name-control', events=[{
                'event': 'selected-name', 'selected_index': 0, 'name': 'light'}])])

    def test_independent_complete_literal_name_vectors_full_rows_bucket_getters_and_reload(self):
        vector = json.loads((Path(__file__).resolve().parents[1] / 'research/fixtures/edlt-scene-name-vectors.json').read_text())
        for case in vector['public_name_cases']:
            with self.subTest(case=case['name']):
                state = self.loaded(indices=tuple(vector['base_empty_scenes']['scene_names']),
                    rows={index: bytes.fromhex(row) for index, row in enumerate(case['initial_static_rows_hex'])})
                outcome = self.editor.edit(state, operations=[op('scene-name-control', case['scene'], events=case['events'])])
                self.assertEqual(self.editor.scene_name(outcome.state, scene=case['scene']), case['expected_retained_name'])
                composition = self.editor.prepare_composition(outcome.state)
                plan = self.editor.prepare_save(outcome.state)
                self.assertEqual(outcome.state.scenes[case['scene'] - 1].name_index, case['expected_name_index'])
                for index, row in enumerate(case['expected_static_rows_hex']):
                    self.assertEqual(bytes(plan.before_save[f'StaticTextString{index}']).hex(), row)
                self.assertEqual(bytes(plan.before_save['SceneBucket']).hex(), case['expected_scene_bucket_hex'])
                self.assertEqual(plan.before_save['SceneCount'], (case['expected_scene_count'],))
                self.assertEqual([plan.before_save[f'Scene{scene}StartAddress'][0] for scene in range(1, 9)], case['expected_scene_starts'])
                self.assertEqual([{'value': row['value'], 'name': row['name']}
                                  for row in composition.as_dict()['scene_names_view']],
                                 case['expected_scene_names_value'])
                fresh = self.editor.load(plan.before_save, metadata=cache())
                self.assertEqual(self.editor.scene_name(fresh, scene=case['scene']), case['expected_fresh_name'])


if __name__ == '__main__': unittest.main()
