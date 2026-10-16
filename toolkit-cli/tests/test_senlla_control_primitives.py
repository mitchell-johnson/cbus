"""Authored control/callback vectors, with an explicit Windows API test double.

The double tests ordering and cache mechanics. It is not Windows NLS acceptance
or execution of the original application. Production uses the actual APIs.
"""
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_control_primitives import (
    NativeText, NativeTextRequired, PersistentControlPrimitives,
    ProgrammaticCollection, ProgrammaticCombo, SENLLA_FUNCTIONS,
    SourceControlStrings, SourceDisplayPreferences, SourceObjectChoice,
    SourceObjectCollection, WindowsTextPrimitives, no_occupancy_functions,
)
from cbus_toolkit.senlla_key_controls import (
    ControlDependency, ControlDependencyRequired, FunctionChoice,
)
from cbus_toolkit.senlla_lifecycle import FlashObject
from cbus_toolkit.sensors import SensorError
from test_senlla_key_events import load, owner


class WindowsAPIDouble(WindowsTextPrimitives):
    def __init__(self):
        self.calls = []
        self.result = None

    def compare_ignore_case(self, first, second):
        self.calls.append(('compare', first, second))
        if self.result is not None:
            return self.result
        # Deliberately authored ASCII test profile, never a host NLS authority.
        left, right = first.upper(), second.upper()
        return (left > right) - (left < right)

    def uppercase(self, value):
        self.calls.append(('upper', value))
        return value.upper()


def source_strings():
    return SourceControlStrings(
        tuple(FunctionChoice(value, f'F{value:02d}') for value in range(35)),
        'UNUSED', 'MULTIPLE', 'MODIFY-NIL', 'MODIFY-DISPLAY',
    )


class ObjectReads:
    """Actual same-identity lazy reads, with authored current TagNames/order."""
    def __init__(self):
        self.managers = {}
        self.reads = []

    def __call__(self, runtime, key, kind):
        if kind == 'scene':
            collection = self.managers.setdefault('scenes', FlashObject('actual.scenes'))
            def rows():
                return runtime.scenes
            def describe(native):
                self.reads.append(('describe_scene', native.identity))
                return SourceDisplayPreferences.scene_text(runtime.scenes.index(native))
        else:
            app = runtime.keys[key].application.value
            collection = (None if app is None else self.managers.setdefault(
                app, FlashObject(f'actual.groups:{app.identity}')))
            def rows():
                return [] if app is None else [value for (address, _), value in runtime.groups.items()
                                               if address == app.identity]
            def describe(native):
                self.reads.append(('describe_group', native.identity))
                return f'G{native.identity[1]:03d}'
        def count():
            self.reads.append(('count', kind, key))
            return len(rows())
        def object_at(index):
            self.reads.append(('object', kind, key, index))
            return rows()[index]
        def item(index):
            native = object_at(index)
            return SourceObjectChoice(native, describe(native))
        return SourceObjectCollection(collection, count, item, describe, object_at)


def prepare(*, runtime=None, masks=None, selector=None):
    runtime = runtime or load(owner(), fresh=False, masks=masks, selector=selector)
    api = WindowsAPIDouble()
    reads = ObjectReads()
    provider = PersistentControlPrimitives(source_strings(), text=NativeText(api), group_objects=reads)
    controls = provider.initial_controls(runtime)
    return runtime, provider, controls, api, reads


def install(runtime, controls):
    runtime.install_m8_hooks(control_dispatch=controls)
    controls.finish_m8_guard()


class PrimitiveTextTest(unittest.TestCase):
    def test_compare_calls_authority_even_identical_and_empty_and_preserves_failure(self):
        api = WindowsAPIDouble()
        text = NativeText(api)
        api.result = -2
        self.assertEqual(text.compare('same', 'same'), -2)
        self.assertEqual(text.compare('', ''), -2)
        self.assertEqual(api.calls, [('compare', 'same', 'same'), ('compare', '', '')])
        self.assertEqual(text.index_of(['same'], 'same'), -1)

    def test_unknown_nls_refuses_including_identical(self):
        text = NativeText()
        # This portable refusal test deliberately disconnects Windows itself.
        text.windows = None
        for first, second in [('same', 'same'), ('', ''), ('a', 'A')]:
            with self.subTest(first=first, second=second):
                with self.assertRaises(NativeTextRequired) as error:
                    text.compare(first, second)
                self.assertEqual(error.exception.request.operation, 'CompareStringW')
        self.assertTrue(text.equal_uppercase('same', 'same'))
        self.assertFalse(text.equal_uppercase('a', 'aa'))
        with self.assertRaises(NativeTextRequired):
            text.equal_uppercase('a', 'A')

    def test_index_first_duplicate_and_source_moving_pivot_sort(self):
        text = NativeText(WindowsAPIDouble())
        self.assertEqual(text.index_of(['B', 'a', 'A'], 'a'), 1)
        self.assertEqual(text.sorted_indices(['B', 'A', 'B', 'A']), (3, 1, 0, 2))
        self.assertEqual(text.sorted_indices([]), ())

    def test_duplicate_index_stays_selected_until_actual_text_lookup(self):
        combo = ProgrammaticCombo('actual', NativeText(WindowsAPIDouble()))
        combo.add_item(1, 'same')
        combo.add_item(2, 'same')
        combo.set_index(1)
        self.assertEqual((combo.item_index, combo.text), (1, 'same'))
        combo.set_text('same')
        self.assertEqual(combo.item_index, 1)
        combo.set_index(99)
        self.assertEqual(combo.item_index, 1)
        self.assertEqual(sum(row['operation'] == 'click' for row in combo.events), 1)

    def test_text_equality_preserves_original_variant_cache(self):
        combo = ProgrammaticCombo('actual', NativeText(WindowsAPIDouble()))
        combo.set_text('')
        self.assertIsNone(combo.edit_value)
        self.assertEqual(combo.edit_value_kind, 'empty')
        combo.replace_empty_selection('X')
        self.assertEqual((combo.text, combo.edit_value_kind, combo.selection), ('X', 'string', (1, 0)))

    def test_prefix_lookup_and_fixed_list_validation_are_separate(self):
        text = NativeText(WindowsAPIDouble())
        combo = ProgrammaticCombo('actual', text)
        combo.add_item(1, 'ALPHA')
        combo.add_item(2, 'ALPINE')
        combo.set_text('alp')
        self.assertEqual((combo.item_index, combo.text), (0, 'alp'))
        combo.drop_down_style = 0
        combo.set_text('other')
        self.assertEqual((combo.item_index, combo.text), (0, 'alp'))
        combo.set_text('alpine')
        self.assertEqual(combo.item_index, 1)
        combo.replace_empty_selection('NOT-A-LABEL')
        self.assertEqual((combo.text, combo.edit_value_kind, combo.item_index), ('', 'null', -1))

    def test_installed_property_change_delivers_current_index_inside_outer_click_lock(self):
        combo = ProgrammaticCombo('actual', NativeText(WindowsAPIDouble()))
        combo.add_item(0, 'A')
        combo.add_item(1, 'B')
        seen = []
        combo.property_on_change = lambda current: seen.append(
            (current.text, current.item_index, current.edit_value, current.click_depth))
        combo.set_index(1)
        combo.set_text('A')
        self.assertEqual(seen, [('B', 1, 'B', 1), ('A', 0, 'B', 0)])
        self.assertEqual(combo.edit_value, 'A')
        combo.set_text('A')
        combo.set_index(0)
        self.assertEqual(len(seen), 2)

    def test_duplicate_label_index_change_skips_property_change_without_text_write(self):
        combo = ProgrammaticCombo('actual', NativeText(WindowsAPIDouble()))
        combo.add_item(0, 'SAME')
        combo.add_item(1, 'SAME')
        seen = []
        combo.property_on_change = lambda current: seen.append(current.item_index)
        combo.set_index(0)
        combo.set_index(1)
        self.assertEqual(seen, [0])
        self.assertEqual(combo.item_index, 1)

    def test_nested_property_change_final_index_comparison_reads_current_and_unlocks_on_failure(self):
        combo = ProgrammaticCombo('actual', NativeText(WindowsAPIDouble()))
        combo.add_item(0, 'A')
        combo.add_item(1, 'B')
        combo.set_index(0)
        seen = []
        def changed(current):
            seen.append((current.item_index, current.click_depth))
            if current.item_index == 1:
                current.set_index(0)
        combo.property_on_change = changed
        before = sum(row['operation'] == 'click' for row in combo.events)
        combo.set_index(1)
        self.assertEqual(seen, [(1, 1), (0, 2)])
        self.assertEqual((combo.item_index, combo.text, combo.edit_value, combo.click_depth), (0, 'A', 'A', 0))
        # The inner comparison differs, but outer click depth1 suppresses
        # dynamic Click. The outer comparison is CURRENT0 == captured0.
        self.assertEqual(sum(row['operation'] == 'click' for row in combo.events), before)
        def fails(_):
            raise RuntimeError('actual installed callback failed')
        combo.property_on_change = fails
        with self.assertRaisesRegex(RuntimeError, 'installed callback'):
            combo.set_index(1)
        self.assertEqual((combo.item_index, combo.text, combo.edit_value, combo.click_depth), (1, 'B', 'B', 0))

    def test_utf16_selection_and_prefix_do_not_count_python_characters(self):
        combo = ProgrammaticCombo('actual', NativeText(WindowsAPIDouble()))
        combo.add_item(0, '😀AB')
        combo.set_text('😀A')
        self.assertEqual(combo.item_index, 0)
        combo.replace_empty_selection('😀')
        self.assertEqual(combo.selection, (2, 0))

    def test_items_counter_and_lookup_changes_do_not_reset_selection(self):
        combo = ProgrammaticCombo('actual', NativeText(WindowsAPIDouble()))
        combo.add_item(0, 'A')
        combo.set_index(0)
        combo.begin_items()
        combo.begin_items()
        combo.clear_items()
        combo.end_items()
        self.assertEqual(combo.item_index, 0)
        before = sum(row['operation'] == 'lookup_properties_changed' for row in combo.events)
        combo.end_items()
        self.assertEqual(sum(row['operation'] == 'lookup_properties_changed' for row in combo.events), before + 1)
        self.assertEqual(combo.item_index, 0)
        with self.assertRaises(SensorError):
            combo.end_items()


class PrimitiveCollectionsTest(unittest.TestCase):
    def test_internal_clear_descending_and_empty_clear_no_publication(self):
        values = [FlashObject(str(index)) for index in range(3)]
        collection = ProgrammaticCollection('actual', values)
        seen = []
        collection.publisher.subscribe(lambda _: seen.append([value.name for value in collection.items]))
        collection.clear()
        self.assertEqual(seen, [['0', '1'], ['0'], []])
        collection.clear()
        self.assertEqual(len(seen), 3)

    def test_end_publishes_real_current_rows_even_equal_or_empty(self):
        collection = ProgrammaticCollection('actual')
        seen = []
        collection.publisher.subscribe(lambda _: seen.append(tuple(collection.items)))
        collection.begin_update()
        collection.clear()
        value = FlashObject('value')
        collection.append(value)
        self.assertEqual(seen, [])
        collection.end_update()
        self.assertEqual(seen, [(value,)])
        collection.begin_update()
        collection.end_update()
        self.assertEqual(seen, [(value,), (value,)])
        self.assertEqual(collection.depth, 0)

    def test_numeric_subset_and_address_grammar(self):
        self.assertEqual(len(SENLLA_FUNCTIONS), 25)
        self.assertEqual(len(no_occupancy_functions(56)), 22)
        self.assertEqual(len(no_occupancy_functions(202)), 24)
        self.assertEqual(no_occupancy_functions(255), (16,))
        self.assertEqual(no_occupancy_functions(0), no_occupancy_functions(56))
        for enabled, hexadecimal, expected in [(False, False, 'TAG'), (False, True, 'TAG'),
                                                (True, False, '026 - TAG'), (True, True, '026 (1Ah) - TAG')]:
            with self.subTest(enabled=enabled, hexadecimal=hexadecimal):
                prefs = SourceDisplayPreferences(enabled, hexadecimal)
                self.assertEqual(prefs.object_text('group', address=26, tag_name='TAG'), expected)
                self.assertEqual(prefs.object_text('group', address=255, tag_name='TAG'), 'TAG')
                self.assertEqual(prefs.object_text('level', address=26, tag_name='TAG'), 'TAG')
        prefs = SourceDisplayPreferences(True, True)
        self.assertEqual(prefs.object_text('level', address=255, tag_name='TAG', level_extended=True),
                         '255 (FFh) - TAG')
        self.assertEqual(prefs.block_text(7, 'G'), '8 : G')
        self.assertEqual(prefs.scene_text(0), 'Scene 1')


class PersistentProviderTest(unittest.TestCase):
    def test_initial_binding_is_actual_all_group_then_per_row_function(self):
        runtime, provider, controls, api, reads = prepare()
        self.assertEqual(runtime.phase, 'm8_hooks')
        self.assertFalse(runtime.hooks_installed)
        self.assertEqual([row.kind for row in provider._object_list_order], ['group'] * 8)
        self.assertEqual([row.key for row in provider._object_list_order], list(range(8)))
        self.assertEqual([row['key'] for row in provider.events if row['operation'] == 'scalar_bound'], list(range(8)))
        self.assertTrue(all(combo.item_index == 0 and combo.text == 'F16' for combo in provider.combos))
        self.assertTrue(all(combo.text == 'UNUSED' and combo.items == [] for combo in provider.groups))
        self.assertTrue(api.calls)
        self.assertEqual(provider.pending, [])
        install(runtime, controls)
        self.assertFalse(controls.initializing)
        self.assertEqual(provider.pending, [])
        self.assertEqual([row[0] for row in provider._key_followers[0]], ['object', 'function'])

    def test_missing_actual_windows_comparison_interrupts_after_items_finally(self):
        runtime = load(owner(), fresh=False)
        text = NativeText()
        text.windows = None
        provider = PersistentControlPrimitives(source_strings(), text=text, group_objects=ObjectReads())
        with self.assertRaises(NativeTextRequired):
            provider.initial_controls(runtime)
        self.assertTrue(runtime.failed)
        self.assertTrue(provider.controls.failed)
        self.assertEqual(provider.combos[0].update_depth, 0)
        self.assertEqual(provider.pending, [])

    def test_source_metadata_reads_distinguish_pointer_after_add_from_tostring(self):
        runtime, provider, controls, _, reads = prepare(masks=[1] + [0] * 7)
        binding = provider._object_bindings[0, 'group']
        self.assertIs(binding.current, runtime.keys[0].primary_group._value)
        reads.reads.clear()
        provider._render_object(binding)
        self.assertEqual(sum(row[0] == 'object' for row in reads.reads), 3)
        self.assertEqual(sum(row[0] == 'describe_group' for row in reads.reads), 4)
        self.assertEqual(provider.groups[0].text, 'G255')
        self.assertEqual(provider.groups[0].item_index, 0)
        # One direct post-Add pointer read executes no hidden description.
        context = reads(runtime, 0, 'group')
        before = len(reads.reads)
        self.assertIs(context.object(0), runtime.groups[(56, 255)])
        self.assertEqual(reads.reads[before:], [('object', 'group', 0, 0)])

    def test_initial_scene_nil_has_no_prepare_group_tail_display(self):
        runtime = load(owner(), fresh=False)
        runtime.set_template(0, 24)
        runtime.keys[0].scene.set(None)
        runtime, provider, controls, _, _ = prepare(runtime=runtime)
        self.assertFalse(provider.groups[0].visible)
        self.assertTrue(provider.scene_visible[0])
        self.assertEqual(provider.scenes[0].text, '')
        self.assertEqual(provider.scenes[0].nil_text, 'UNUSED')
        self.assertEqual(provider.scenes[0].items, [])
        self.assertFalse(provider._object_bindings[0, 'group'].bound)
        self.assertEqual([kind for kind, _ in provider._key_followers[0]], ['object', 'function'])

    def test_modify_display_and_scalar_nil_are_independent_resources(self):
        runtime = load(owner(), fresh=False)
        runtime.set_template(0, 25)
        runtime, provider, controls, _, _ = prepare(runtime=runtime)
        self.assertEqual(provider.groups[0].text, 'MODIFY-DISPLAY')
        self.assertEqual(provider.groups[0].nil_text, '')
        self.assertFalse(provider.groups[0].enabled)
        self.assertFalse(provider.groups[0].scalar_active)
        # Native SENLLA subset excludes25. Function preparation resets the
        # model to16 after the earlier independent Group Modify preparation.
        self.assertEqual(runtime._template_type(0), 16)
        install(runtime, controls)
        self.assertEqual(provider.groups[0].nil_text, 'UNUSED')
        self.assertEqual(provider.groups[0].text, 'MODIFY-DISPLAY')

    def test_final_template_attribute_not_just_key_generic_is_observed(self):
        runtime, provider, controls, _, _ = prepare()
        install(runtime, controls)
        provider.events.clear()
        runtime.keys[0].object.begin_update()
        try:
            runtime.set_template(0, 0)
            self.assertEqual(provider.combos[0].text, 'F00')
            self.assertEqual(runtime.keys[0].object.depth, 1)
            self.assertTrue(any(row['operation'] == 'primitive' and row.get('key') == 0
                                for row in provider.events))
        finally:
            runtime.keys[0].object.end_update()
        self.assertEqual(provider.pending, [])
        self.assertEqual(provider.combos[0].update_depth, 0)

    def test_late_scene_controller_follows_function_and_group_in_actual_binding_order(self):
        runtime, provider, controls, _, _ = prepare()
        install(runtime, controls)
        runtime.set_template(0, 24)
        self.assertEqual([kind for kind, _ in provider._key_followers[0]], ['object', 'function', 'object'])
        self.assertTrue(provider._object_bindings[0, 'group'].bound)
        self.assertTrue(provider._object_bindings[0, 'scene'].bound)
        self.assertFalse(provider.groups[0].visible)
        self.assertIsNotNone(runtime.keys[0].scene._value)
        provider.events.clear()
        runtime.keys[0].object.resolve_change()
        runtime.keys[0].object.changed()
        deliveries = [row for row in provider.events if row['operation'] == 'root_key_delivery' and row['key'] == 0]
        self.assertEqual([(row['ordinal'], row['kind']) for row in deliveries],
                         [(0, 'object'), (1, 'function'), (2, 'object')])

    def test_root_collection_change_has_link_then_handle_current_passes_and_no_empty_clear(self):
        runtime, provider, controls, _, _ = prepare()
        install(runtime, controls)
        provider.events.clear()
        root = controls.bindings.primary
        controls.collection_changed(root, root.choices)
        deliveries = [row for row in provider.events if row['operation'] == 'list_delivery']
        self.assertEqual([(row['route'], row['key']) for row in deliveries],
                         [('link', key) for key in range(8)] + [('handle', key) for key in range(8)])
        provider.load_function_root(root, ())
        provider.events.clear()
        provider.load_function_root(root, ())
        self.assertFalse(any(row['operation'] == 'list_delivery' for row in provider.events))

    def test_broadcast_binding_owns_actual_list_publication_and_normal_flow_posts_none(self):
        runtime, provider, controls, _, _ = prepare()
        install(runtime, controls)
        root = provider.create_broadcast_root()
        self.assertEqual(tuple(choice.template for choice in root.choices), no_occupancy_functions(56))
        collection = provider.bind_light_frame(broadcast_items=list(range(8)))
        seen = []
        collection.publisher.subscribe(lambda _: seen.append([row.name for row in collection.items]))
        runtime.keys[0].object.resolve_change()
        runtime.keys[0].object.changed()
        self.assertEqual(seen, [[f'block:{index}' for index in range(8)]])
        self.assertEqual(collection.depth, 0)
        self.assertEqual(provider.broadcast_depth, 0)
        self.assertEqual(provider.pending, [])
        self.assertEqual(controls.deferred, [])

    def test_scheduler_delivers_only_posted_messages_and_does_not_acknowledge_manual_handler(self):
        runtime, provider, _, _, _ = prepare()
        provider(ControlDependency('scheduler', 'PostWM0x426', '0xf96210', 0), runtime)
        self.assertEqual(provider.pending, [0])
        with self.assertRaises(ControlDependencyRequired):
            provider(ControlDependency('scheduler', 'HandleComboChange', '0xf961e4', 0), runtime)
        self.assertEqual(provider.pending, [])
        with self.assertRaises(SensorError):
            provider(ControlDependency('scheduler', 'HandleComboChange', '0xf961e4', 0), runtime)

    def test_frozen_numeric_fixture_carries_source_order_and_scope(self):
        fixture = json.loads((Path(__file__).parents[1] / 'research/fixtures/senlla-control-primitives-source.json').read_text())
        self.assertEqual(fixture['subsets']['SENLLA'], list(SENLLA_FUNCTIONS))
        self.assertEqual(fixture['bindings']['initial_order'], ['all8_group_or_scene', 'per_row_function_root_then_scalar'])
        self.assertFalse(fixture['acceptance']['original_execution'])
        self.assertFalse(fixture['acceptance']['windows_nls_executed_in_portable_tests'])


if __name__ == '__main__':
    unittest.main()
