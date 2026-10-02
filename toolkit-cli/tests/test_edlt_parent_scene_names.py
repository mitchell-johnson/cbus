"""SceneName cache, allocator and getters through real ordered parent owners."""
import json
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from cbus_toolkit.edlt_scene_manager import SceneManagerCache
from cbus_toolkit import edlt_static_grid as grid
from tests.test_edlt import Session
from tests.test_edlt_parent_form import fixture
from tests.test_edlt_parent_transaction import lighting, measurement
from tests.test_edlt_scene_manager import cache, op
from tests.test_edlt_scene_names import source_values, name_control
from tests.test_edlt_static_grid import history, begin, text, COMMIT, project


def scenes(*operations):
    return {'op': 'scene-manager', 'operations': list(operations)}


class ParentSceneNamesTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.source = self.editor.snapshot(source_values(self.spec))
        self.metadata = SceneManagerCache.from_dict(cache())
        self.label = 'A' * 62 + '\u0101'

    def plan(self, *operations, source=None):
        return self.editor.plan(self.source if source is None else source,
                                metadata=self.metadata, operations=operations)

    def test_new_source_name_is_retained_for_later_widget_and_single_terminal_save(self):
        with patch.object(self.editor.lifecycle, '_prepare_composed_save',
                          wraps=self.editor.lifecycle._prepare_composed_save) as terminal:
            plan = self.plan(scenes(name_control(self.label), op('get-name')),
                             lighting(label_text=self.label), measurement())
        self.assertEqual(terminal.call_count, 1)
        self.assertEqual(plan.before_save['SceneBucket'][4], 63)
        self.assertEqual(plan.after_controls['Widget7WidgetByteValue13'], (63,))
        self.assertEqual(bytes(plan.after_controls['StaticTextString63']), b'A' * 62 + b'\xc4\0')
        result = plan.as_dict()
        self.assertEqual(result['operation_results'][0]['nested_operation_results'][1]['value'], self.label)
        self.assertEqual(result['retained_name_views']['static_names'][63], self.label)
        self.assertEqual(result['retained_name_views']['scene_names'][0]['scene_name'], self.label)
        self.assertEqual(len(result['retained_name_views']['static_names']), 64)
        self.assertEqual(len(result['retained_name_views']['scene_names']), 8)
        self.assertIsNone(grid.current(self.source))

    def test_property_old_reference_stays_reserved_in_parent_while_later_widget_can_reuse_name(self):
        source = self.editor.snapshot(source_values(self.spec,
            indices=(63, 255, 255, 255, 255, 255, 255, 255),
            rows={63: b'Old\0'.ljust(64, b'\0')}))
        plan = self.plan(scenes(name_control('New')), lighting(label_text='New'), source=source)
        self.assertEqual(plan.before_save['SceneBucket'][4], 62)
        self.assertEqual(plan.before_save['Widget7WidgetByteValue13'], (62,))
        self.assertEqual(bytes(plan.before_save['StaticTextString63']), b'Old\0' + b'\0' * 60)
        self.assertEqual(bytes(plan.before_save['StaticTextString62']), b'New\0' + b'\0' * 60)
        evidence = plan.as_dict()['operation_results'][0]['nested_operation_results'][0]['scene_name_control']
        self.assertEqual(evidence['binding_callbacks'][0]['result']['used_indices'], [63, 255])

    def test_earlier_and_future_widget_reservations_follow_actual_owning_order(self):
        cases = [
            ((lighting(label_text='First'), scenes(name_control('Second'))), 63, 62, 'First', 'Second'),
            ((scenes(name_control('Second')), lighting(label_text='First')), 62, 63, 'Second', 'First'),
            ((lighting(label_text='First'), scenes(name_control('First'))), 63, 63, 'First', ''),
        ]
        for operations, widget_index, scene_index, row63, row62 in cases:
            with self.subTest(order=[row['op'] for row in operations], scene=scene_index):
                plan = self.plan(*operations)
                self.assertEqual(plan.before_save['Widget7WidgetByteValue13'], (widget_index,))
                self.assertEqual(plan.before_save['SceneBucket'][4], scene_index)
                self.assertEqual(bytes(plan.before_save['StaticTextString63']), (row63 + '\0').encode().ljust(64, b'\0'))
                self.assertEqual(bytes(plan.before_save['StaticTextString62']), (row62 + '\0').encode().ljust(64, b'\0'))

    def test_later_indexed_grid_change_updates_both_scene_views_without_reindexing(self):
        plan = self.plan(history(begin(3), text(self.label), COMMIT),
            scenes(name_control(self.label), name_control(self.label, scene=2), op('get-name'), op('get-name', 2)),
            history(begin(3), text('Revised shared'), COMMIT), measurement())
        result = plan.as_dict()
        manager = result['operation_results'][1]
        self.assertEqual([row['value'] for row in manager['nested_operation_results'][-2:]], [self.label, self.label])
        self.assertEqual([row['scene_name'] for row in manager['composition']['terminal_scene_models'][:2]], [self.label, self.label])
        self.assertEqual([row['scene_name'] for row in result['retained_name_views']['scene_names'][:2]], ['Revised shared'] * 2)
        self.assertEqual([row['name_index'] for row in result['retained_name_views']['scene_names'][:2]], [3, 3])
        self.assertEqual((plan.before_save['SceneBucket'][4], plan.before_save['SceneBucket'][9]), (3, 3))
        self.assertEqual(bytes(plan.before_save['StaticTextString3']), b'Revised shared\0' + b'\0' * 49)

    def test_future_grid_name_never_borrows_allocator_identity_or_known_selection(self):
        plan = self.plan(scenes(name_control(self.label)), history(begin(3), text(self.label), COMMIT))
        self.assertEqual(plan.before_save['SceneBucket'][4], 63)
        self.assertEqual(bytes(plan.before_save['StaticTextString63']), b'A' * 62 + b'\xc4\0')
        self.assertEqual(bytes(plan.before_save['StaticTextString3']), b'A' * 62 + b'\xc4\0')
        with self.assertRaisesRegex(EdltError, 'ordinal member'):
            self.plan(scenes(op('scene-name-control', events=[{
                'event': 'selected-name', 'selected_index': 3, 'name': self.label}])),
                history(begin(3), text(self.label), COMMIT))
        self.assertIsNone(grid.current(self.source))

    def test_getter_only_parent_reads_complete_names_without_static_pp_changes(self):
        source = self.editor.snapshot(source_values(self.spec,
            indices=(3, 3, 255, 255, 255, 255, 255, 255),
            rows={3: b'\xed\xa0\x80\0'.ljust(64, b'\xa5')}))
        plan = self.plan(scenes(*(op('get-name', scene) for scene in range(1, 9))), history(), source=source)
        result = plan.as_dict()
        self.assertEqual([row['value'] for row in result['operation_results'][0]['nested_operation_results']],
                         ['\ufffd\ufffd', '\ufffd\ufffd', '', '', '', '', '', ''])
        for index in range(64):
            self.assertEqual(plan.before_save[f'StaticTextString{index}'], source[f'StaticTextString{index}'])
        self.assertEqual(result['retained_name_views']['scene_names'][0]['name'], '1 - \ufffd\ufffd')
        self.assertEqual(result['retained_name_views']['scene_names'][1]['name'], '2 - \ufffd\ufffd')

    def test_pending_name_input_cannot_enter_parent_and_exception_cache_is_discarded(self):
        session = Session(self.spec)
        with self.assertRaisesRegex(EdltError, 'Pending SceneName'):
            self.plan(history(begin(3), text('Earlier'), COMMIT),
                scenes(op('scene-name-control', events=[{'event': 'input', 'text': 'Uncommitted'}])),
                lighting(label_text='Earlier'))
        self.assertIsNone(grid.current(self.source))
        self.assertEqual(session.calls, [])
        valid = self.plan(scenes(name_control('After failure')), history())
        self.assertEqual(valid.before_save['SceneBucket'][4], 63)
        self.assertEqual(valid.after_controls['StaticTextString3'], self.source['StaticTextString3'])

    def test_nested_name_parent_has_private_scope_and_restores_outer_on_success_and_failure(self):
        with grid.scope():
            grid.initialize(self.source); outer = grid.current(self.source)
            project(self.source, history(begin(3), text('Outer only'), COMMIT))
            inner = self.plan(scenes(name_control('Inner only')), history())
            self.assertEqual(inner.before_save['SceneBucket'][4], 63)
            self.assertEqual(inner.after_controls['StaticTextString3'], self.source['StaticTextString3'])
            self.assertIs(grid.current(self.source), outer)
            self.assertEqual(outer.names[3], 'Outer only')
            self.assertEqual(outer.names[63], '')
            with self.assertRaisesRegex(EdltError, 'ordinal member'):
                self.plan(scenes(op('scene-name-control', events=[{
                    'event': 'selected-name', 'selected_index': 3, 'name': 'Outer only'}])), history())
            self.assertIs(grid.current(self.source), outer)
            self.assertEqual(outer.names[3], 'Outer only')
        self.assertIsNone(grid.current(self.source))

    def test_reset_replaces_initial_retained_names_and_preserves_new_getter_state(self):
        from tests.test_edlt_parent_blank_reset import complete_spec, reset_source
        from tests.test_edlt_reset import metadata as reset_cache
        editor = EdltParentTransaction(complete_spec())
        metadata = SceneManagerCache.from_dict({'format': 'cbus-edlt-scene-manager-cache-v1',
            'application_cache': reset_cache(), 'level_labels': []})
        source = reset_source(editor.spec)
        source['StaticTextString3'] = ' '.join(map(str, b'Earlier only\0'.ljust(64, b'\0')))
        reset = {'op': 'reset', 'active_tab': 'widgets', 'binding_variant': 'audited-local-wiring',
                 'dirty_parameters': ['UnitAddress']}
        plan = editor.plan(source, metadata=metadata, operations=(
            reset,
            scenes(op('get-name'), name_control('Fresh'), op('get-name')), measurement()))
        document = plan.as_dict()
        manager = document['operation_results'][1]
        self.assertEqual(manager['nested_operation_results'][0]['value'], '')
        self.assertEqual(manager['nested_operation_results'][2]['value'], 'Fresh')
        self.assertEqual(plan.before_save['StaticTextString3'], (0,) * 64)
        self.assertEqual(plan.before_save['SceneBucket'][4], 63)
        self.assertEqual(document['retained_name_views']['static_names'][3], '')
        with self.assertRaisesRegex(EdltError, 'ordinal member'):
            editor.plan(source, metadata=metadata, operations=(
                reset,
                scenes(op('scene-name-control', events=[{'event': 'selected-name',
                    'selected_index': 3, 'name': 'Earlier only'}]))))
        self.assertIsNone(grid.current(source))

    def test_canonical_apply_replays_retained_names_and_stale_guard_precedes_writes(self):
        plan = self.plan(scenes(name_control(self.label)), lighting(label_text=self.label), measurement())
        session = Session(self.spec); session.current = dict(self.source)
        result = self.editor.apply(session, plan)
        self.assertTrue(result['verified'])
        self.assertEqual(self.editor.snapshot(session.values()), {**plan.expected, **plan.changes})
        self.assertEqual(result['retained_name_views']['static_names'][63], self.label)
        self.assertEqual(len(session.calls), len({name for name, value in session.calls}))
        stale = Session(self.spec); stale.current = {**self.source, 'StaticTextString63': tuple(b'Changed\0'.ljust(64, b'\0'))}
        with self.assertRaisesRegex(EdltError, 'changed since'):
            self.editor.apply(stale, plan)
        self.assertEqual(stale.calls, [])

    def test_native_progressive_replay_sees_only_actual_prior_widget_and_grid_names(self):
        from tests.test_edlt_parent_add_dialog import ParentAddTests
        helper = ParentAddTests(); helper.setUp()
        for name, value in source_values(helper.spec).items():
            if name in helper.client.values:
                helper.client.values[name] = value if isinstance(value, str) else ' '.join(map(str, value))
        native = helper.plan((lighting(label_text='First'), scenes(name_control('Second'))))
        plan = native.parent_plan
        self.assertEqual(plan.before_save['Widget7WidgetByteValue13'], (63,))
        self.assertEqual(plan.before_save['SceneBucket'][4], 62)
        self.assertEqual(bytes(plan.before_save['StaticTextString63']), b'First\0' + b'\0' * 58)
        self.assertEqual(bytes(plan.before_save['StaticTextString62']), b'Second\0' + b'\0' * 57)
        self.assertEqual(plan.as_dict()['retained_name_views']['scene_names'][0]['scene_name'], 'Second')
        self.assertIsNone(grid.current(self.source))


if __name__ == '__main__': unittest.main()
