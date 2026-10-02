"""Literal .NET fallback and retained grid-cell histories; no vendor execution."""
import json
from pathlib import Path
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_static_grid import (StaticGrid, current, decode_utf8,
                                          initialize, scope)
from cbus_toolkit.edlt_static_text_dialog import normalize, project
from tests import test_edlt_parent_transaction as fixture

FACTS = json.loads((Path(__file__).resolve().parents[2] /
    'rust/testdata/vectors/edlt_static_grid_editor.json').read_text())


def history(*events, close='button'):
    return {'op': 'static-text-dialog', 'events': list(events), 'close': close}


def begin(index): return {'event': 'begin', 'index': index}
def text(value): return {'event': 'input', 'text': value}
COMMIT = {'event': 'commit'}
CANCEL = {'event': 'cancel'}


class StaticGridTests(unittest.TestCase):
    def setUp(self):
        self.values = {f'StaticTextString{i}': (0,) * 64 for i in range(64)}

    def test_original_framework_literal_decoder_groups(self):
        for row in FACTS['decoded_rows']:
            with self.subTest(row=row['name']):
                self.assertEqual(decode_utf8(bytes.fromhex(row['hex'])), row['text'])

    def test_unedited_malformed_rows_and_trailing_bytes_are_not_rewritten(self):
        self.values['StaticTextString3'] = tuple(bytes.fromhex('eda080').ljust(64, b'\xa5'))
        self.values['StaticTextString4'] = (196, 0) + (165,) * 62
        changes, result = project(self.values, history())
        self.assertEqual(changes, {})
        self.assertEqual(result['rows'], [])
        self.assertEqual(StaticGrid(self.values).names[4], '\ufffd')

    def test_edit_equal_to_loaded_replacement_preserves_invalid_prefix(self):
        self.values['StaticTextString3'] = (237, 160, 128, 0) + (165,) * 60
        changes, _ = project(self.values, history(begin(3), text('\ufffd\ufffd'), COMMIT))
        self.assertEqual(changes, {})

    def test_real_edit_replaces_only_target_row(self):
        self.values['StaticTextString3'] = (237, 160, 128, 0) + (165,) * 60
        changes, result = project(self.values, history(begin(3), text('Fixed'), COMMIT))
        self.assertEqual(set(changes), {'StaticTextString3'})
        self.assertEqual(changes['StaticTextString3'], tuple(b'Fixed\0'.ljust(64, b'\0')))
        self.assertEqual(result['cell_commits'][0]['cause'], 'explicit-cell-commit')

    def test_cancel_discards_only_current_pending_cell_not_previous_commit(self):
        changes, result = project(self.values, history(
            begin(1), text('committed'), COMMIT, begin(1), text('discarded'), CANCEL, CANCEL))
        self.assertEqual(changes['StaticTextString1'][:10], tuple(b'committed\0'))
        self.assertEqual(result['cancelled_cell_edits'], [{'index': 1, 'discarded_text': 'discarded'}])
        self.assertFalse(result['cancel_rollback'])

    def test_focus_to_another_cell_commits_pending_text(self):
        changes, result = project(self.values, history(begin(63), text('last'),
            {'event': 'focus', 'index': 0, 'column': 'value'}))
        self.assertEqual(changes['StaticTextString63'][:5], tuple(b'last\0'))
        self.assertEqual(result['cell_commits'][0]['cause'], 'cell-focus-validation')
        self.assertEqual(result['editor_events'][-1]['current_column'], 'value')

    def test_same_cell_focus_does_not_imply_commit(self):
        with self.assertRaisesRegex(EdltError, 'Pending static cell close'):
            project(self.values, history(begin(3), text('pending'), {'event':'focus','index':3}))

    def test_pending_button_and_window_close_refuse_without_cache_mutation(self):
        with scope():
            initialize(self.values)
            for close in ('button', 'window'):
                with self.subTest(close=close), self.assertRaisesRegex(EdltError, 'Pending static cell close'):
                    project(self.values, history(begin(1), text('first'), COMMIT,
                        begin(2), text('pending'), close=close))
                self.assertEqual(current(self.values).names[1], '')

    def test_retained_cache_survives_split_pp_prefix_and_dialog_reopen(self):
        name = 'A' * 62 + 'ā'
        with scope():
            changes, first = project(self.values, history(begin(3), text(name), COMMIT))
            pp = {**self.values, **changes}
            self.assertEqual(first['rows'][0]['loaded_text'], 'A' * 62 + '\ufffd')
            changes2, second = project(pp, history(begin(3), CANCEL))
            self.assertEqual(changes2, {})
            self.assertEqual(second['rows'][0]['committed_text'], name)
            self.assertFalse(second['rows'][0]['bytes_changed'])
        self.assertIsNone(current(self.values))

    def test_nested_and_exception_scopes_restore_private_parent_context(self):
        with scope():
            initialize(self.values)
            outer = current(self.values)
            project(self.values, history(begin(3), text('Outer'), COMMIT))
            with self.assertRaisesRegex(RuntimeError, 'exit'):
                with scope():
                    initialize(self.values)
                    self.assertEqual(current(self.values).names[3], '')
                    raise RuntimeError('exit')
            self.assertIs(current(self.values), outer)
            self.assertEqual(outer.names[3], 'Outer')
        self.assertIsNone(current(self.values))

    def test_unterminated_64byte_loaded_row_is_not_repaired_on_equal_edit(self):
        self.values['StaticTextString3'] = (65,) * 64
        changes, _ = project(self.values, history(begin(3), text('A'*64), COMMIT))
        self.assertEqual(changes, {})

    def test_value_column_nested_begin_and_input_without_editor_refuse(self):
        for operation in (history({'event':'begin','index':3,'column':'value'}),
                          history(begin(3), begin(4)), history(text('unbound'))):
            with self.subTest(operation=operation), self.assertRaises(EdltError):
                project(self.values, operation)

    def test_events_keep_original_name_utf16_bound_and_exact_schema(self):
        normalize(history(begin(3), text('😀'*32), COMMIT))
        for operation in (history(begin(3), text('😀'*33), COMMIT),
                          history(begin(True), COMMIT), history({'event':'delete','index':3}),
                          {'op':'static-text-dialog','edits':[],'events':[]}):
            with self.subTest(operation=operation), self.assertRaises(EdltError):
                normalize(operation)


class RetainedParentGridTests(unittest.TestCase):
    def setUp(self):
        self.helper = fixture.ParentTransactionTests(); self.helper.setUp()

    def test_long_grid_name_reused_by_later_widget_even_when_pp_truncated(self):
        label = 'A' * 62 + 'ā'
        plan = self.helper.plan((history(begin(3), text(label), COMMIT),
            fixture.lighting(label_text=label), fixture.measurement()))
        self.assertEqual(plan.after_controls['Widget7WidgetByteValue13'], (3,))
        self.assertEqual(plan.after_controls['StaticTextString3'], tuple(bytes([65]*62+[196,0])))
        self.assertEqual(plan.after_controls['StaticTextString63'], self.helper.source['StaticTextString63'])

    def test_widget_allocation_enters_retained_table_for_later_grid(self):
        plan = self.helper.plan((history(), fixture.lighting(label_text='Allocated'),
            history(begin(63), text('Allocated'), COMMIT), fixture.measurement()))
        result = plan.as_dict()['operation_results'][2]
        self.assertEqual(result['rows'], [])
        self.assertEqual(plan.after_controls['Widget7WidgetByteValue13'], (63,))

    def test_bad_dialog_does_not_leak_cache_into_next_parent_or_standalone_allocator(self):
        with self.assertRaises(EdltError):
            self.helper.plan((history(begin(3), text('Cache'), COMMIT, begin(4)), fixture.measurement()))
        self.assertIsNone(current(self.helper.source))
        allocation = self.helper.editor.common.allocate_static_text(self.helper.source, 'Cache')
        self.assertEqual(allocation.index, 63)
        with self.assertRaisesRegex(EdltError, 'exceeds63'):
            self.helper.editor.common.allocate_static_text(self.helper.source, 'A'*64)

    def test_nested_ordinary_parent_does_not_borrow_enclosing_grid_cache(self):
        with scope():
            initialize(self.helper.source)
            outer=current(self.helper.source)
            project(self.helper.source, history(begin(3), text('Outer only'), COMMIT))
            plan=self.helper.plan((fixture.lighting(label_text='Outer only'), fixture.measurement()))
            self.assertEqual(plan.after_controls['Widget7WidgetByteValue13'], (63,))
            self.assertIs(current(self.helper.source),outer)
            self.assertEqual(outer.names[3],'Outer only')

    def test_nested_static_parent_has_its_own_loaded_names_and_restores_outer(self):
        with scope():
            initialize(self.helper.source)
            outer=current(self.helper.source)
            project(self.helper.source, history(begin(3), text('Outer only'), COMMIT))
            plan=self.helper.plan((history(begin(4),text('Inner only'),COMMIT),
                                  fixture.lighting(label_text='Outer only'),fixture.measurement()))
            self.assertEqual(plan.after_controls['Widget7WidgetByteValue13'],(63,))
            self.assertEqual(plan.after_controls['StaticTextString3'],self.helper.source['StaticTextString3'])
            self.assertIs(current(self.helper.source),outer)
            self.assertEqual(outer.names[3],'Outer only')
            self.assertEqual(outer.names[4],'')

    def test_nested_static_parent_exception_restores_outer_cache(self):
        with scope():
            initialize(self.helper.source)
            outer=current(self.helper.source)
            project(self.helper.source, history(begin(3),text('Outer only'),COMMIT))
            with self.assertRaisesRegex(EdltError,'Pending static cell close'):
                self.helper.plan((history(begin(4),text('Inner only'),COMMIT,begin(5)),
                                  fixture.measurement()))
            self.assertIs(current(self.helper.source),outer)
            self.assertEqual(outer.names[3],'Outer only')
            self.assertEqual(outer.names[4],'')

    def test_new_parent_load_uses_stored_fallback_instead_of_previous_long_cache(self):
        label='A'*62+'ā'
        first=self.helper.plan((history(begin(3),text(label),COMMIT),fixture.measurement()))
        pp={**first.expected,**first.changes}
        second=self.helper.plan((history(),fixture.lighting(label_text='A'*62+'\ufffd'),
                                 fixture.measurement()),source=pp)
        self.assertEqual(second.after_controls['Widget7WidgetByteValue13'],(3,))
        with self.assertRaisesRegex(EdltError,'exceeds63'):
            self.helper.plan((history(),fixture.lighting(label_text=label),
                              fixture.measurement()),source=pp)

    def test_malformed_loaded_name_reused_without_canonicalizing_unrelated_rows(self):
        source = {**self.helper.source, 'StaticTextString3': (237,160,128,0)+(165,)*60}
        plan = self.helper.plan((history(), fixture.lighting(label_text='\ufffd\ufffd'),
            fixture.measurement()), source=source)
        self.assertEqual(plan.after_controls['Widget7WidgetByteValue13'], (3,))
        self.assertEqual(plan.after_controls['StaticTextString3'], source['StaticTextString3'])

    def test_native_ordered_add_replay_and_canonical_parent_have_independent_matching_cache(self):
        from tests.test_edlt_parent_add_dialog import ParentAddTests
        helper = ParentAddTests(); helper.setUp()
        label = 'A' * 62 + 'ā'
        plan = helper.plan((history(begin(3), text(label), COMMIT),
            {'op':'add-dialog','field':'QuickStatusGroup','address':99,'name':'Added'},
            fixture.lighting(label_text=label)))
        self.assertEqual(plan.parent_plan.after_controls['Widget7WidgetByteValue13'], (3,))
        self.assertEqual([r.address for r in plan.creations if r.name == 'Added'], [99])
        self.assertIsNone(current(self.helper.source))

    def test_reset_initializes_fresh_cache_instead_of_old_loaded_names(self):
        from tests.test_edlt_application_add_dialog import ResetApplicationParentTests
        from tests.test_edlt_parent_blank_reset import reset_operations
        helper = ResetApplicationParentTests(); helper.setUp()
        helper.client.values['StaticTextString3'] = ' '.join(map(str, b'Before reset\0'.ljust(64,b'\0')))
        plan = helper.plan((reset_operations()[0], history(),
                            fixture.lighting(group=42, label_text='Before reset')))
        self.assertEqual(plan.parent_plan.after_controls['Widget7WidgetByteValue13'], (63,))
        self.assertEqual(plan.parent_plan.after_controls['StaticTextString3'], (0,)*64)


class RetainedSceneGridTests(unittest.TestCase):
    def setUp(self):
        from tests.test_edlt_parent_scene_manager import ParentSceneManagerTests
        self.helper=ParentSceneManagerTests();self.helper.setUp()
        self.label='A'*62+'ā'

    def operations(self, *, future=False):
        grid=history(begin(3),text(self.label),COMMIT)
        scene={'op':'scene-manager','operations':[{'op':'set-name-text','scene':1,'text':self.label}]}
        return ((scene,grid) if future else (grid,scene))+(fixture.measurement(),)

    def test_scene_manager_reuses_actual_earlier_cached_name_before_length_gate(self):
        h=self.helper
        plan=h.editor.plan(h.source,metadata=h.metadata,operations=self.operations())
        self.assertEqual(plan.before_save['SceneBucket'][4],3)
        self.assertEqual(plan.after_controls['StaticTextString3'],tuple(bytes([65]*62+[196,0])))
        self.assertEqual(plan.after_controls['StaticTextString63'],h.source['StaticTextString63'])
        self.assertIsNone(current(h.source))

    def test_future_or_unmatched_long_name_is_not_authorized_by_shape_deferral(self):
        h=self.helper
        for operations in (self.operations(future=True),
                           (history(),self.operations()[1],fixture.measurement())):
            with self.subTest(operations=operations),self.assertRaisesRegex(EdltError,'exceeds63'):
                h.editor.plan(h.source,metadata=h.metadata,operations=operations)
            self.assertIsNone(current(h.source))

    def test_standalone_scene_manager_keeps_strict_new_text_limit(self):
        manager=self.helper.editor._editor('scene-manager')
        state=manager.load(self.helper.source,metadata=self.helper.metadata)
        with self.assertRaisesRegex(EdltError,'exceeds63'):
            manager.edit(state,operations=self.operations()[1]['operations'])

    def test_cli_shape_normalization_does_not_read_metadata_or_leak_cache(self):
        from cbus_toolkit import edlt_parent_transaction_cli as boundary
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'operations.json';path.write_text(json.dumps(self.operations()))
            args=SimpleNamespace(operations=path,metadata=None)
            with patch.object(boundary,'metadata',return_value=self.helper.metadata) as read:
                rows=boundary.operations(args);read.assert_not_called()
                result=boundary.settings(args);read.assert_called_once_with(None)
            self.assertEqual(rows[1]['operations'][0]['text'],self.label)
            self.assertEqual(result['operations'],rows)
            self.assertIsNone(current(self.helper.source))

    def test_native_ordered_replay_uses_same_scene_name_cache(self):
        from tests.test_edlt_parent_add_dialog import ParentAddTests
        h=ParentAddTests();h.setUp()
        rows=self.operations()[:2]
        plan=h.plan((rows[0],{'op':'add-activation-action-dialog','name':'Added'},rows[1]))
        self.assertEqual(plan.parent_plan.before_save['SceneBucket'][4],3)
        self.assertEqual(plan.parent_plan.after_controls['StaticTextString3'],tuple(bytes([65]*62+[196,0])))
        self.assertIsNone(current(self.helper.source))

    def test_native_no_add_replays_earlier_grid_before_scene_manager(self):
        from tests.test_edlt_parent_add_dialog import ParentAddTests
        h=ParentAddTests();h.setUp()
        plan=h.plan(self.operations()[:2])
        self.assertEqual(plan.parent_plan.before_save['SceneBucket'][4],3)
        self.assertEqual(plan.parent_plan.after_controls['StaticTextString3'],tuple(bytes([65]*62+[196,0])))
        self.assertIsNone(current(self.helper.source))
        for rows in (self.operations(future=True)[:2],
                     (history(),self.operations()[1])):
            with self.subTest(rows=rows),self.assertRaisesRegex(EdltError,'exceeds63'):
                h.plan(rows)
            self.assertIsNone(current(self.helper.source))

    def test_native_earlier_widget_reserves_name_and_slot_before_scene_manager(self):
        from tests.test_edlt_parent_add_dialog import ParentAddTests
        for scene_text, index in [('First',63),('Second',62)]:
            h=ParentAddTests();h.setUp()
            rows=(history(),fixture.lighting(label_text='First'),
                {'op':'scene-manager','operations':[{'op':'set-name-text','scene':1,'text':scene_text}]})
            plan=h.plan(rows)
            self.assertEqual(plan.parent_plan.before_save['Widget7WidgetByteValue13'],(63,))
            self.assertEqual(plan.parent_plan.before_save['SceneBucket'][4],index)
            self.assertEqual(plan.parent_plan.before_save['StaticTextString63'],tuple(b'First\0'.ljust(64,b'\0')))
            self.assertEqual(plan.parent_plan.before_save[f'StaticTextString{index}'],tuple((scene_text+'\0').encode().ljust(64,b'\0')))
            self.assertIsNone(current(self.helper.source))

    def test_native_blank_retains_its_dedicated_projection_before_scene_manager(self):
        from tests.test_edlt_parent_add_dialog import ParentAddTests
        h=ParentAddTests();h.setUp()
        h.client.values['NavWidgetType']='0'
        grid, scene=self.operations()[:2]
        plan=h.plan((grid,{'op':'blank','page':1,'position':2},scene))
        self.assertEqual(plan.parent_plan.before_save['SceneBucket'][4],3)
        self.assertEqual(plan.parent_plan.after_controls['Widget7WidgetType'],(0,))
        self.assertEqual(plan.parent_plan.before_save['Widget7WidgetType'],(255,))
        self.assertEqual(len(plan.parent_plan.as_dict()['lifecycle']['blank_transitions']),1)
        self.assertIsNone(current(self.helper.source))

    def test_reset_does_not_authorize_previous_long_scene_name(self):
        from tests.test_edlt_application_add_dialog import ResetApplicationParentTests
        from tests.test_edlt_parent_blank_reset import reset_operations
        h=ResetApplicationParentTests();h.setUp()
        h.client.values['StaticTextString3']=' '.join(['65']*64)
        scene={'op':'scene-manager','operations':[{'op':'set-name-text','scene':1,'text':'A'*64}]}
        with self.assertRaisesRegex(EdltError,'exceeds63'):
            h.plan((reset_operations()[0],history(),scene))
        self.assertIsNone(current(self.helper.source))

    def test_shape_validation_and_bad_signature_restore_actual_outer_cache(self):
        from cbus_toolkit.edlt_parent_transaction import normalize_operations
        with scope():
            initialize(self.helper.source);outer=current(self.helper.source)
            project(self.helper.source,history(begin(3),text('Outer only'),COMMIT))
            normalize_operations(self.operations())
            normalize_operations(operations=self.operations())
            self.assertIs(current(self.helper.source),outer)
            self.assertEqual(outer.names[3],'Outer only')
            with self.assertRaises(TypeError):
                self.helper.editor.plan(self.helper.source,operations=self.operations(),unexpected=True)
            self.assertIs(current(self.helper.source),outer)
            self.assertEqual(outer.names[3],'Outer only')
