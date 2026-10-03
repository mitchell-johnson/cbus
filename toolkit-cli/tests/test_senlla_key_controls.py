"""Authored native-profile control vectors; primitive adapter is a test double.

These tests isolate source-owned ordering and CURRENT reads. They do not claim
Windows framework, locale comparison or deferred scheduler acceptance.
"""
import json
from dataclasses import replace
from pathlib import Path
import unittest

from cbus_toolkit.senlla_key_controls import (
    ComboState, ControlBindings, ControlDependencyRequired, FunctionChoice,
    FunctionRoot, SENLLAKeyControls,
)
from cbus_toolkit.senlla_key_events import KeyControlRequest
from cbus_toolkit.sensors import SensorError
from test_senlla_key_events import load, owner


class PrimitiveDouble:
    def __init__(self):
        self.requests = []
        self.effect = None
        self.compare = None
        self.controls = None

    def __call__(self, request, engine):
        self.requests.append(request)
        if self.effect:
            self.effect(request, engine)
        if request.operation == 'SetFunctionListRoot':
            # Explicit one-delivery test profile; production owns actual
            # controller multiplicity/order and may issue several callbacks.
            self.controls.list_changed(request.key, self.controls.roots[request.key])
        if request.kind == 'comparison':
            if self.compare:
                return self.compare(request)
            items, text = request.value
            return items.index(text) if text in items else -1
        if request.kind == 'description':
            return f'current-{request.value}'
        if request.operation == 'FinalizePopulateText':
            if engine.keys[request.key].template.value is None:
                self.controls.text[request.key] = ''
            elif not self.controls.text[request.key]:
                self.controls.text[request.key] = request.value
        return None


def prepare(*, primitive=True, primary=None, secondary=None, broadcast=False, stages=None, masks=None):
    runtime = load(owner(), fresh=False, stages=stages, masks=masks)
    runtime.fresh_function_bindings()
    choices = tuple(FunctionChoice(template, f'f{template}') for template in (16, 0, 1, 6, 23, 24, 26, 34))
    first = FunctionRoot('actual-primary', primary or choices)
    second = FunctionRoot('actual-secondary', secondary or choices)
    third = FunctionRoot('actual-broadcast', (FunctionChoice(16, 'f16'),)) if broadcast else None
    bindings = ControlBindings(first, second, third, 'unused', 'multiple', 'modify')
    adapter = PrimitiveDouble() if primitive else None
    # Explicit conditional entry state; this is not an assertion that these
    # contents were produced by the ordinary raw-load/form constructor.
    controls = SENLLAKeyControls(bindings, roots=[first] * 8,
                combo_states=[ComboState(choices, 0, 'f16', False)] * 8,
                group_text=['unused'] * 8, extension_visible=[False] * 8,
                subset_names=['SENLLA'] * 8, allow_other_keys=[False, False],
                dependency_executor=adapter)
    if adapter:
        adapter.controls = controls
    controls.attach(runtime)
    return runtime, controls, adapter


def install(runtime, controls):
    runtime.install_m8_hooks(control_dispatch=controls)
    controls.finish_m8_guard()


class SENLLAKeyControlsTest(unittest.TestCase):
    def test_same_root_and_scalar_do_not_rebuild_items(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        self.assertEqual(adapter.requests, [])
        self.assertEqual(controls.snapshot()['roots'], ['actual-primary'] * 8)
        runtime.keys[0].object.resolve_change()
        runtime.keys[0].object.changed()
        self.assertEqual([r.operation for r in adapter.requests], ['UpdateGroupCombo'])
        self.assertFalse(any(event['operation'] == 'scalar_current_changed' for event in controls.events))

    def test_different_root_marks_dirty_before_native_enable_primitive(self):
        runtime, controls, adapter = prepare(masks=[1] + [0] * 7)
        install(runtime, controls)
        runtime.set_secondary(0, True)
        self.assertIs(controls.roots[0], controls.bindings.secondary)
        self.assertTrue(controls.dirty[0])
        self.assertFalse(any(r.operation == 'ItemsBeginUpdate' for r in adapter.requests))
        self.assertTrue(any(r.operation == 'UpdateFunctionEnableState' for r in adapter.requests))

    def test_absent_current_template_runs_real_source_reset16(self):
        choices = (FunctionChoice(16, 'f16'), FunctionChoice(0, 'f0'))
        runtime, controls, adapter = prepare(primary=choices, secondary=choices)
        install(runtime, controls)
        runtime.set_template(0, 1)
        self.assertEqual(runtime._template_type(0), 16)
        self.assertTrue(any(e['operation'] == 'template_reset' and e['key'] == 0 for e in controls.events))
        # The newer general hook restores the original pointer before the
        # older scalar observer reads it, so no transient list render occurs.
        self.assertFalse(any(r.operation == 'ItemsIndexOf' for r in adapter.requests))
        self.assertEqual(controls.text[0], 'f16')

    def test_render_source_order_and_programmatic_indices_do_not_post_message(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        runtime.set_template(0, 0)
        operations = [r.operation for r in adapter.requests]
        begin = operations.index('SetListControllerActive')
        self.assertEqual(operations[begin:begin + 5], [
            'SetListControllerActive', 'SetListControllerActive', 'ItemsBeginUpdate', 'SetItemIndex', 'ItemsClear'])
        end = operations.index('ItemsEndUpdate')
        self.assertEqual(operations[end:end + 3], ['ItemsEndUpdate', 'SelectAll', 'InvalidateFunctionControl'])
        self.assertEqual(operations[-4:], ['ItemsIndexOf', 'SetItemIndex', 'SetText', 'UpdateFunctionEnableState'])
        self.assertEqual(controls.item_index[0], 1)
        self.assertEqual(controls.text[0], 'f0')
        self.assertEqual(controls.deferred, [])

    def test_native_comparison_result_controls_duplicate_label_index(self):
        choices = (FunctionChoice(16, 'idle'), FunctionChoice(0, 'same'), FunctionChoice(1, 'same'))
        runtime, controls, adapter = prepare(primary=choices, secondary=choices)
        adapter.compare = lambda request: 1
        install(runtime, controls)
        runtime.set_template(0, 1)
        self.assertEqual(controls.item_index[0], 1)
        self.assertEqual(controls.text[0], 'same')
        self.assertEqual(runtime._template_type(0), 1)
        self.assertEqual(controls.deferred, [])

    def test_current_template_reread_after_render_index_callback(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        changed = False
        def effect(request, engine):
            nonlocal changed
            if request.source == '0xbbc6f6' and not changed:
                changed = True
                engine.set_template(0, 1)
        adapter.effect = effect
        runtime.set_template(0, 0)
        self.assertEqual(runtime._template_type(0), 1)
        self.assertEqual(controls.text[0], 'f1')
        self.assertEqual(controls.item_index[0], 1)  # prior f0 IndexOf capture
        self.assertEqual(sum(r.operation == 'ItemsBeginUpdate' for r in adapter.requests), 1)
        self.assertFalse(controls.rendering[0])

    def test_current_root_and_ordinal_reread_after_add_callback(self):
        first = (FunctionChoice(16, 'f16'), FunctionChoice(0, 'f0'), FunctionChoice(1, 'f1'))
        second = (FunctionChoice(16, 'f16'), FunctionChoice(1, 'f1'), FunctionChoice(0, 'f0'))
        runtime, controls, adapter = prepare(primary=first, secondary=second, masks=[1] + [0] * 7)
        install(runtime, controls)
        changed = False
        def effect(request, engine):
            nonlocal changed
            if request.operation == 'ItemsAddObject' and request.value[2] == 1 and not changed:
                changed = True
                engine.set_secondary(0, True)
        adapter.effect = effect
        runtime.set_template(0, 0)
        self.assertEqual([x.template for x in controls.items[0]], [16, 0, 0])
        self.assertIs(controls.roots[0], controls.bindings.secondary)
        self.assertEqual(controls.item_index[0], 1)
        self.assertFalse(controls.dirty[0])  # native unconditional clear after captured loop

    def test_direct_current_target_publication_renders_without_pointer_change(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        current = runtime.keys[0].template.value
        current.resolve_change()
        current.changed()
        self.assertEqual(sum(r.operation == 'ItemsBeginUpdate' for r in adapter.requests), 8)
        self.assertEqual([runtime._template_type(i) for i in range(8)], [16] * 8)

    def test_template_change_unsubscribes_old_current_target(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        runtime.set_template(0, 0)
        adapter.requests.clear()
        runtime.templates[16].resolve_change()
        runtime.templates[16].changed()
        rendered = [r.key for r in adapter.requests if r.operation == 'ItemsBeginUpdate']
        self.assertEqual(rendered, [7, 6, 5, 4, 3, 2, 1])

    def test_initializing_flag_suppresses_only_group_rebinding(self):
        runtime, controls, adapter = prepare()
        runtime.install_m8_hooks(control_dispatch=controls)
        runtime.set_template(0, 0)
        self.assertFalse(any(r.operation == 'UpdateGroupCombo' for r in adapter.requests))
        self.assertTrue(any(r.operation == 'ItemsBeginUpdate' for r in adapter.requests))
        controls.finish_m8_guard()
        adapter.requests.clear()
        runtime.keys[0].object.resolve_change()
        runtime.keys[0].object.changed()
        self.assertEqual([r.operation for r in adapter.requests], ['UpdateGroupCombo'])

    def test_current_broadcast_root_can_be_actual_nil_before_later_creation(self):
        runtime, controls, adapter = prepare(masks=[1] + [0] * 7)
        install(runtime, controls)
        runtime.set_broadcast_block(0)
        runtime.set_broadcast_active(True)
        controls(KeyControlRequest(0), runtime)
        self.assertIsNone(controls.bindings.broadcast)
        self.assertIsNone(controls.roots[0])
        later = FunctionRoot('later-f8', (FunctionChoice(16, 'f16'),))
        controls.bind_broadcast_root(later)
        self.assertIsNone(controls.roots[0])
        controls(KeyControlRequest(0), runtime)
        self.assertIs(controls.roots[0], later)

    def test_nil_list_root_has_zero_rows_without_nil_scalar_inference(self):
        runtime, controls, adapter = prepare(masks=[1] + [0] * 7)
        install(runtime, controls)
        runtime.set_broadcast_block(0)
        runtime.set_broadcast_active(True)
        runtime.set_template(0, 1)
        self.assertIsNone(controls.roots[0])
        self.assertEqual(controls.items[0], ())
        self.assertEqual(controls.item_index[0], -1)
        self.assertEqual(controls.text[0], 'f1')
        self.assertIs(runtime.keys[0].template.value, runtime.templates[1])

    def test_broadcast_candidates_reread_after_actual_add_callback(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        controls.bind_broadcast_root(FunctionRoot('later-f8', (FunctionChoice(16, 'f16'),)))
        controls.bind_light_frame(broadcast_items=[7])
        changed = False
        def effect(request, engine):
            nonlocal changed
            if request.operation == 'BroadcastCollectionAdd' and request.value == 0 and not changed:
                changed = True
                engine.graph = engine.graph.with_maintenance(active=True, block=1)
                engine.broadcast_active._value = True  # supplied primitive's isolated CURRENT fact
        adapter.effect = effect
        controls(KeyControlRequest(0), runtime)
        self.assertEqual(controls.broadcast_items, [0, 2, 3, 4, 5, 6, 7])
        self.assertEqual([r.operation for r in adapter.requests][-1], 'BroadcastItemsEndUpdate')

    def test_broadcast_excludes_current_scene_and_occupancy_references(self):
        runtime, controls, adapter = prepare(masks=[1, 2] + [0] * 6)
        install(runtime, controls)
        controls.bind_broadcast_root(FunctionRoot('later-f8', (FunctionChoice(16, 'f16'),)))
        controls.bind_light_frame(broadcast_items=[])
        # Conditional current model facts in an isolated owner primitive;
        # these are not raw-loader reachability or native flag callback claims.
        runtime.keys[0].template._value = runtime.templates[23]
        occupancy = list(runtime.graph.occupancy)
        occupancy[1] = replace(occupancy[1], light=True)
        runtime.graph = replace(runtime.graph, occupancy=tuple(occupancy))
        controls(KeyControlRequest(2), runtime)
        self.assertEqual(controls.broadcast_items, [2, 3, 4, 5, 6, 7])

    def test_paired_override_clear_requires_actual_consumer_binding(self):
        runtime, controls, adapter = prepare()
        controls.allow_other_keys[:] = [True, True]  # explicit prior source field values
        install(runtime, controls)
        requests = [r for r in adapter.requests if r.operation == 'SetPairedKeyBlockOverrides']
        self.assertEqual(len(requests), 1)
        self.assertIs(requests[0].value, False)
        self.assertEqual(controls.allow_other_keys, [False, False])

    def test_collection_notification_marks_matching_roots_without_render(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        def effect(request, engine):
            if request.operation == 'DeliverFunctionListNotifications':
                # Explicit actual subscriber order in the isolated adapter;
                # production does not invent an aggregate key-index loop.
                for key in reversed(range(8)):
                    controls.list_changed(key, controls.bindings.primary)
        adapter.effect = effect
        controls.collection_changed(controls.bindings.primary,
                                    (FunctionChoice(0, 'f0'), FunctionChoice(16, 'f16')))
        self.assertEqual([r.key for r in adapter.requests[1:]], list(reversed(range(8))))
        self.assertTrue(all(controls.dirty))
        self.assertFalse(any(r.operation == 'ItemsBeginUpdate' for r in adapter.requests))

    def test_deferred_delivery_is_owner_issued_and_not_implicitly_drained(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        controls.post_combo_change(2)
        controls.post_combo_change(0)
        self.assertEqual(controls.deferred, [2, 0])
        self.assertFalse(any(r.operation == 'HandleComboChange' for r in adapter.requests))
        controls.deliver_combo_change(2)
        self.assertEqual(controls.deferred, [0])
        self.assertEqual(adapter.requests[-1].operation, 'HandleComboChange')

    def test_actual_owner_delivery_order_is_not_guessed_from_posts(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        controls.post_combo_change(2)
        controls.post_combo_change(0)
        controls.deliver_combo_change(0)
        self.assertEqual(controls.deferred, [2])
        self.assertEqual(adapter.requests[-1].key, 0)

    def test_missing_primitive_interrupts_actual_owner_at_causal_position(self):
        runtime, controls, _ = prepare(primitive=False)
        install(runtime, controls)
        with self.assertRaises(ControlDependencyRequired) as failure:
            runtime.set_template(0, 0)
        self.assertEqual(failure.exception.request['operation'], 'UpdateGroupCombo')
        self.assertTrue(controls.failed)
        self.assertTrue(runtime.failed)
        self.assertEqual(runtime._template_type(0), 0)
        with self.assertRaises(SensorError):
            controls(KeyControlRequest(0), runtime)

    def test_final_state_return_is_rejected_and_render_guard_is_restored(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        adapter.effect = lambda request, engine: None
        controls.dependency_executor = lambda request, engine: {'keys': [16] * 8}
        with self.assertRaisesRegex(SensorError, 'not return final state'):
            runtime.set_template(0, 0)
        self.assertTrue(runtime.failed)
        self.assertFalse(controls.rendering[0])

    def test_population_exception_runs_items_end_and_clears_render_guard(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        def effect(request, engine):
            if request.operation == 'ItemsAddObject':
                raise RuntimeError('primitive exception')
        adapter.effect = effect
        with self.assertRaisesRegex(RuntimeError, 'primitive exception'):
            runtime.set_template(0, 0)
        self.assertEqual(adapter.requests[-1].operation, 'ItemsEndUpdate')
        self.assertFalse(controls.rendering[0])
        self.assertTrue(runtime.failed)
        self.assertEqual([x.template for x in controls.items[0]], [16])

    def test_input_state_and_identity_validation(self):
        with self.assertRaises(SensorError):
            ComboState((), 0, '', False)
        with self.assertRaises(SensorError):
            FunctionRoot('same', (FunctionChoice(16, 'idle'), FunctionChoice(16, 'idle')))
        first = FunctionRoot('same', (FunctionChoice(16, 'idle'),))
        second = FunctionRoot('same', (FunctionChoice(16, 'idle'),))
        with self.assertRaises(SensorError):
            ControlBindings(first, second, None, '', '', '')
        second = FunctionRoot('other', (FunctionChoice(16, 'different'),))
        with self.assertRaises(SensorError):
            ControlBindings(first, second, None, '', '', '')

    def test_invalid_comparison_interrupts_after_items_end(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        adapter.compare = lambda request: -2
        with self.assertRaisesRegex(SensorError, 'actual index'):
            runtime.set_template(0, 0)
        self.assertTrue(any(r.operation == 'ItemsEndUpdate' for r in adapter.requests))
        self.assertFalse(controls.rendering[0])
        self.assertTrue(runtime.failed)

    def test_scheduler_refusal_retains_committed_post_position(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        controls.dependency_executor = None
        with self.assertRaises(ControlDependencyRequired) as failure:
            controls.post_combo_change(4)
        self.assertEqual(failure.exception.request['kind'], 'scheduler')
        self.assertEqual(controls.deferred, [4])
        self.assertTrue(runtime.failed)

    def test_snapshot_detaches_lists_and_reads_no_model_getters(self):
        runtime, controls, adapter = prepare()
        install(runtime, controls)
        snapshot = controls.snapshot()
        snapshot['roots'][0] = 'changed'
        snapshot['items'][0].clear()
        snapshot['deferred'].append(0)
        self.assertEqual(controls.roots[0].identity, 'actual-primary')
        self.assertTrue(controls.items[0])
        self.assertEqual(controls.deferred, [])

    def test_source_fixture_literal_extension_predicate(self):
        fixture = json.loads((Path(__file__).parents[1] / 'research/fixtures/senlla-key-controls-source.json').read_text())
        expected = set(fixture['literal_vectors']['extension_visible_types'])
        self.assertEqual(expected, {3, 6, 12, 13, 14, 15, 23, 24, 29, 30, 31, 32, 33, 34})
        for value in range(59):
            with self.subTest(template=value):
                self.assertEqual(value in SENLLAKeyControls._EXTENSION, value in expected)


if __name__ == '__main__':
    unittest.main()
