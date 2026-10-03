import copy
from dataclasses import replace
import unittest

from cbus_toolkit.senlla_bank_graph import SENLLABankGraph
from cbus_toolkit.senlla_key_events import (BlockValues, KeyEventContext, SENLLAKeyEvents,
                                          SourceControlRequired, SourceObjectRequired)
from cbus_toolkit.sensors import SensorError


def owner(*, secondary=0, groups=None, store1=None, store2=None, timers=None, expiry=None,
          primary=56, application2=57, protected=()):
    groups = groups or [255] * 8
    first = store1 or [0] * 8
    second = store2 or [0] * 8
    timers = timers or [0] * 8
    expiry = expiry or [0] * 8
    apps = tuple(dict.fromkeys((primary, *((application2,) if application2 is not None else ()), 202)))
    identities = {(app, 255) for app in apps}
    identities.add((202, 7))
    rows = []
    for index in range(8):
        side = bool(secondary & (1 << index))
        app = application2 if side else primary
        identities.add((app, groups[index]))
        rows.append(BlockValues(side, (app, groups[index]), store1=first[index], store2=second[index],
                                timer=timers[index], expiry=expiry[index]))
    identities.update(protected)
    context = KeyEventContext(primary, application2, apps, tuple(sorted(identities)), protected,
                              trigger_levels=((202, 7, 165),))
    graph = SENLLABankGraph.fresh().load_stored_levels(first, second)
    return SENLLAKeyEvents(context, rows, graph)


def load(runtime, *, masks=None, stages=None, selector=None, indicator=None, fresh=True):
    runtime.load_allocations(masks or [0] * 8)
    runtime.finish_corekey_application_refresh()
    runtime.load_scenes([255] * 80, [162, 182, 202, 222, 255, 255, 255, 255],
                        [157, 64], (202, 7))
    runtime.load_key_values(stages or [[0] * 4 for _ in range(8)], selector or [0] * 8,
                            indicator or [0] * 8)
    if fresh:
        runtime.fresh_function_bindings()
        # Isolate the owned model kernel with a fake form executor. These
        # literals do not assert original controls/framework were executed.
        runtime.install_m8_hooks(control_dispatch=lambda request, engine: None)
    return runtime


class SENLLAKeyEventsTest(unittest.TestCase):
    def test_unassociated_secondary_invoke_preserves_scene_under_parent_depth(self):
        runtime = load(owner(secondary=1), stages=[[14, 4, 10, 5]] + [[0] * 4] * 7,
                       selector=[1] + [0] * 7, indicator=[7] + [0] * 7)
        result = runtime.parameters()
        self.assertEqual(result['BlockAllocation'], [1, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(result['SecondApplicationBlocks'], [0])
        self.assertEqual(result['SceneKeySelector'], [1, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(result['IndicatorBlockAssignment'], [7, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual([result[name][0] for name in ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand')],
                         [14, 4, 10, 5])
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot['keys'][0]['template'], 24)
        self.assertEqual(snapshot['keys'][0]['indicator_block_number'], 1)
        self.assertEqual(snapshot['keys'][0]['scene_trigger'], 165)
        self.assertFalse(any(event['operation'] == 'block_swap' for event in snapshot['events']))
        self.assertTrue(any(event.get('object') == 'key:0' and event['operation'] == 'begin'
                            and event['depth'] == 2 for event in snapshot['events']))

    def test_unassociated_secondary_modify_fresh_reset_has_no_timer_defaults(self):
        runtime = load(owner(secondary=1), stages=[[11, 7, 0, 7]] + [[0] * 4] * 7,
                       selector=[1] + [0] * 7, indicator=[6] + [0] * 7, fresh=False)
        loaded = runtime.snapshot()
        self.assertEqual(loaded['keys'][0]['template'], 25)
        self.assertEqual(loaded['keys'][0]['stages'], [11, 7, 0, 7])
        self.assertEqual(loaded['keys'][0]['indicator_block_number'], 7)
        self.assertEqual(loaded['blocks'][0]['timer'], 0)
        runtime.fresh_function_bindings()
        runtime.install_m8_hooks(control_dispatch=lambda request, engine: None)
        result = runtime.parameters()
        self.assertEqual(result['SceneKeySelector'], [0] * 8)
        self.assertEqual(result['IndicatorBlockAssignment'], [6] + [0] * 7)
        self.assertEqual(result['JPCommand'], [0] * 8)
        self.assertEqual(result['TimerHighByte'], [0] * 8)
        self.assertEqual(result['TimerLowByte'], [0] * 8)
        self.assertEqual(result['TimerExpiryCommand'], [0] * 8)

    def test_later_primary_scene_swap_moves_earlier_indicator_and_block_data(self):
        runtime = load(owner(groups=[255, 20, 255, 255, 255, 255, 255, 255],
                             store1=[10, 20, 0, 0, 0, 0, 0, 0],
                             store2=[30, 40, 0, 0, 0, 0, 0, 0],
                             timers=[100, 200, 0, 0, 0, 0, 0, 0],
                             expiry=[4, 9, 0, 0, 0, 0, 0, 0]),
                       masks=[2, 0, 0, 0, 0, 0, 0, 0],
                       stages=[[13, 0, 0, 0], [14, 4, 10, 5]] + [[0] * 4] * 6,
                       selector=[0, 1, 0, 0, 0, 0, 0, 0], indicator=[1, 5, 0, 0, 0, 0, 0, 0])
        result = runtime.parameters()
        self.assertEqual(result['BlockAllocation'], [1, 2, 0, 0, 0, 0, 0, 0])
        self.assertEqual(result['GroupAddress'], [20, 255, 255, 255, 255, 255, 255, 255])
        self.assertEqual(result['IndicatorBlockAssignment'], [0, 5, 0, 0, 0, 0, 0, 0])
        self.assertEqual(result['LightLevelStore1'][:2], [20, 10])
        self.assertEqual(result['LightLevelStore2'][:2], [40, 30])
        self.assertEqual(result['TimerLowByte'][:2], [200, 100])
        self.assertEqual(result['TimerExpiryCommand'][:2], [9, 4])
        events = runtime.snapshot()['events']
        self.assertEqual([(event['first'], event['second']) for event in events
                          if event['operation'] == 'block_swap'], [(0, 1)])
        self.assertEqual(sum(event.get('object') == 'key:0.indicator' and event['operation'] == 'begin'
                             for event in events), 2)  # raw load plus swap setter
        self.assertEqual(sum(event.get('object') == 'key:0.indicator' and event['operation'] == 'references'
                             for event in events), 3)  # explicit Changed after swap setter

    def test_raw_secondary_reference_precedes_scene_load_and_can_change_current_template(self):
        runtime = load(owner(secondary=1), masks=[1] + [0] * 7,
                       stages=[[14, 4, 10, 5]] + [[0] * 4] * 7,
                       selector=[1] + [0] * 7, indicator=[7] + [0] * 7)
        # Raw allocation has already derived ordinary0 before Scene24 is set.
        self.assertEqual(runtime.snapshot()['keys'][0]['template'], 0)
        self.assertEqual(runtime.parameters()['JPCommand'][0], 13)
        self.assertEqual(runtime.parameters()['SceneKeySelector'][0], 0)
        self.assertEqual(runtime.parameters()['IndicatorBlockAssignment'][0], 0)

    def test_collision_adds_destination_before_removing_source_and_keeps_order(self):
        runtime = owner(secondary=2, groups=[20, 20, 255, 255, 255, 255, 255, 255])
        runtime.load_allocations([5] + [0] * 7)
        runtime.set_secondary(0, True)
        state = runtime.snapshot()
        self.assertEqual(state['keys'][0]['references'], [2, 1])
        self.assertEqual(state['blocks'][0]['group'], (57, 255))
        self.assertEqual([(event['operation'], event['block']) for event in state['events']
                          if event.get('key') == 0 and event['operation'] in ('reference_add', 'reference_remove')][-2:],
                         [('reference_add', 1), ('reference_remove', 0)])

    def test_equal_secondary_boolean_does_not_scan_duplicates(self):
        runtime = owner(groups=[20, 20, 255, 255, 255, 255, 255, 255])
        runtime.load_allocations([1] + [0] * 7)
        before = runtime.snapshot()
        runtime.set_secondary(0, False)
        self.assertEqual(runtime.snapshot(), before)

    def test_secondary_refresh_visits_zero_reference_keys_and_publishes_source_block(self):
        runtime = owner()
        runtime.graph = runtime.graph.with_maintenance(active=True, block=0)
        runtime.load_allocations([1] + [0] * 7)
        snapshot = runtime.snapshot()
        self.assertEqual([(event['block'], event['key']) for event in snapshot['events']
                          if event['operation'] == 'block_secondary_key_refresh'],
                         [(0, key) for key in range(8)])
        self.assertEqual([event['block'] for event in snapshot['events']
                          if event['operation'] == 'block_published'], [0] * 8)
        self.assertEqual([key['references'] for key in snapshot['keys']], [[0]] + [[]] * 7)
        self.assertFalse(runtime.graph.banks[0].switch_allowed)
        self.assertEqual([key['application_state'] for key in snapshot['keys']], [0] * 8)

    def test_secondary_refresh_skips_only_currently_updating_keys(self):
        runtime = owner()
        runtime.keys[0].object.begin_update()
        try:
            runtime._run(lambda: runtime._block_secondary_refresh(0))
        finally:
            runtime.keys[0].object.end_update()
        events = runtime.snapshot()['events']
        self.assertEqual([event['key'] for event in events
                          if event['operation'] == 'block_secondary_key_refresh'], list(range(1, 8)))
        self.assertEqual([event['block'] for event in events
                          if event['operation'] == 'block_published'], [0] * 7)

    def test_ordinary_locked_defaults_and_unrecognized_nibbles_preserve_raw(self):
        runtime = load(owner(), masks=[1, 2, 0, 0, 0, 0, 0, 0],
                       stages=[[0, 7, 15, 0], [1, 1, 1, 1]] + [[0] * 4] * 6)
        result = runtime.parameters()
        self.assertEqual([result[name][:2] for name in ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand')],
                         [[0, 1], [7, 1], [15, 1], [0, 1]])
        self.assertEqual(result['TimerHighByte'][:2], [1, 0])
        self.assertEqual(result['TimerLowByte'][:2], [44, 0])
        self.assertEqual(result['TimerExpiryCommand'][:2], [0, 0])
        self.assertEqual([key['template'] for key in runtime.snapshot()['keys'][:2]], [6, 26])

    def test_fresh_recall_uses_nil_identity_for_multi_reference_keys(self):
        runtime = load(owner(store1=[249, 252, 0, 0, 0, 0, 0, 0]),
                       masks=[5, 10, 0, 0, 0, 0, 0, 0],
                       stages=[[12, 0, 0, 0], [12, 0, 0, 0]] + [[0] * 4] * 6)
        self.assertEqual([key['template'] for key in runtime.snapshot()['keys'][:2]], [17, 16])
        self.assertEqual(runtime.parameters()['JPCommand'][:2], [12, 0])
        self.assertTrue(any(event['operation'] == 'recall_conflict_warning'
                            for event in runtime.snapshot()['events']))

    def test_cross_application_unused_objects_are_distinct_for_recall(self):
        runtime = load(owner(secondary=2, store1=[249, 252, 0, 0, 0, 0, 0, 0]),
                       masks=[1, 2, 0, 0, 0, 0, 0, 0],
                       stages=[[12, 0, 0, 0], [12, 0, 0, 0]] + [[0] * 4] * 6)
        self.assertEqual([key['template'] for key in runtime.snapshot()['keys'][:2]], [17, 18])
        self.assertFalse(any(event['operation'] == 'recall_conflict_warning'
                             for event in runtime.snapshot()['events']))

    def test_loaded_micro0_is_distinct_from_conditional_existing_nil_expiry(self):
        stages = [[11, 7, 0, 7]] + [[0] * 4] * 7
        nonnil = load(owner(), masks=[1] + [0] * 7, stages=stages)
        conditional_nil = load(owner(expiry=[None] + [0] * 7), masks=[1] + [0] * 7, stages=stages)
        self.assertEqual(nonnil.parameters()['TimerExpiryCommand'][0], 0)
        self.assertEqual(conditional_nil.parameters()['TimerExpiryCommand'][0], 15)
        self.assertEqual(nonnil.block_values()[0].expiry, 0)
        self.assertEqual(conditional_nil.block_values()[0].expiry, 15)

    def test_actual_application255_normalizes_blocks_and_transfers_collision(self):
        runtime = owner(application2=255, secondary=1,
                        groups=[20, 20, 255, 255, 255, 255, 255, 255])
        runtime.load_allocations([1] + [0] * 7)
        self.assertEqual(runtime.snapshot()['keys'][0]['application'], 255)
        runtime.finish_corekey_application_refresh()
        state = runtime.snapshot()
        self.assertEqual(state['secondary_application'], 255)
        self.assertEqual(state['keys'][0]['references'], [1])
        self.assertEqual(state['keys'][0]['application'], 56)
        self.assertEqual([block['secondary'] for block in state['blocks']], [False] * 8)
        self.assertEqual(state['blocks'][0]['group'], (56, 255))

    def test_missing_scene_group_is_a_causal_creation_request_before_object_invention(self):
        runtime = owner()
        runtime.load_allocations([0] * 8)
        runtime.finish_corekey_application_refresh()
        with self.assertRaises(SourceObjectRequired) as raised:
            runtime.load_scenes([40, 9] + [255] * 78, [162, 255, 255, 255, 255, 255, 255, 255],
                                [157, 64], (202, 7))
        self.assertEqual(raised.exception.request,
                         {'kind': 'group', 'application': 56, 'address': 40, 'source': 'scene_table_getter'})
        request = raised.exception.request
        request['address'] = 1
        self.assertEqual(raised.exception.request['address'], 40)
        self.assertNotIn((56, 40), runtime.groups)
        self.assertTrue(runtime.snapshot()['failed'])

    def test_missing_trigger_level_refuses_at_invoke_getter_after_scene_binding(self):
        base = owner()
        runtime = SENLLAKeyEvents(replace(base.context, trigger_levels=()), base.block_values(), base.graph)
        runtime.load_allocations([0] * 8)
        runtime.finish_corekey_application_refresh()
        runtime.load_scenes([255] * 80, [162] + [255] * 7, [157, 64], (202, 7))
        with self.assertRaises(SourceObjectRequired) as raised:
            runtime.load_key_values([[14, 4, 10, 5]] + [[0] * 4] * 7, [1] + [0] * 7, [7] + [0] * 7)
        self.assertEqual(raised.exception.request,
                         {'kind': 'level', 'application': 202, 'address': 165,
                          'source': 'scene_trigger_getter', 'group': 7})
        self.assertEqual(runtime.snapshot()['keys'][0]['scene'], 7)
        self.assertEqual(runtime.snapshot()['keys'][0]['scene_trigger'], None)

    def test_unlocked_modify_template_assigns_default_ramp_macro3(self):
        runtime = load(owner())
        runtime.set_template(0, 25)
        key = runtime.snapshot()['keys'][0]
        self.assertEqual(key['template'], 25)
        self.assertEqual(key['scene_ramp_template'], 3)
        self.assertEqual(key['macro_type'], 3)
        self.assertEqual(key['stages'], [0, 11, 2, 14])
        self.assertEqual(runtime.parameters()['SceneKeySelector'][0], 1)

    def test_preload_macro_type0_has_nil_stage_references(self):
        runtime = owner()
        initial = runtime.snapshot()['keys']
        self.assertEqual([key['template'] for key in initial], [None] * 8)
        self.assertEqual([key['macro_type'] for key in initial], [0] * 8)
        self.assertEqual([key['stages'] for key in initial], [[None] * 4] * 8)

    def test_selected_modify_zero_jp_is_nonnil_micro0_and_sets_scene_before_raw_macro(self):
        runtime = load(owner(), selector=[1] + [0] * 7,
                       stages=[[0, 0, 0, 0]] * 8, fresh=False)
        state = runtime.snapshot()
        self.assertEqual(state['keys'][0]['scene_ramp_function'], 0)
        self.assertEqual(state['keys'][0]['template'], 25)
        self.assertEqual(state['keys'][0]['stages'], [0, 0, 0, 0])
        self.assertEqual(state['keys'][0]['scene'], 0)
        events = state['events']
        scene_starts = [index for index, event in enumerate(events)
                        if event.get('object') == 'key:0.scene' and event['operation'] == 'begin']
        self.assertEqual(len(scene_starts), 2)
        ramp_starts = [index for index, event in enumerate(events)
                       if event.get('object') == 'key:0.scene_ramp_template'
                       and event['operation'] == 'begin']
        self.assertLess(scene_starts[0], ramp_starts[-1])
        self.assertLess(ramp_starts[-1], scene_starts[1])

    def test_template23_uses_invoke_serializer_and_existing_trigger255_getter(self):
        runtime = load(owner())
        runtime.bind_context(replace(runtime.context,
                          trigger_levels=runtime.context.trigger_levels + ((202, 7, 255),)))
        runtime.set_template(0, 23)
        result = runtime.parameters()
        self.assertEqual(result['SceneKeySelector'][0], 1)
        self.assertEqual(result['IndicatorBlockAssignment'][0], 0)
        self.assertEqual([result[field][0] for field in ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand')],
                         [14, 0, 15, 15])
        self.assertEqual(runtime.snapshot()['keys'][0]['scene_trigger'], 255)
        self.assertTrue(runtime.snapshot()['keys'][0]['scene_learning'])

    def test_label_flavour_uses_logical_plus1_and_invoke_resets_raw_enum_after_ramp(self):
        runtime = load(owner())
        self.assertEqual([key['label_flavour'] for key in runtime.snapshot()['keys']], [1] * 8)
        runtime.set_label_flavour(0, 4)
        self.assertEqual(runtime.snapshot()['keys'][0]['label_flavour'], 4)
        start = len(runtime.events)
        runtime.set_template(0, 24)
        self.assertEqual(runtime.snapshot()['keys'][0]['label_flavour'], 1)
        events = runtime.events[start:]
        ramp = next(index for index, event in enumerate(events)
                    if event.get('object') == 'key:0.scene_ramp_template' and event['operation'] == 'begin')
        flavour = next(index for index, event in enumerate(events)
                       if event.get('object') == 'key:0.label_flavour' and event['operation'] == 'begin')
        self.assertLess(ramp, flavour)
        start = len(runtime.events)
        runtime.set_template(0, 24)
        self.assertFalse(any(event.get('object') == 'key:0.label_flavour' and event['operation'] == 'begin'
                             for event in runtime.events[start:]))
        with self.assertRaises(SensorError):
            runtime.set_label_flavour(0, 0)

    def test_invoke_nil_trigger_refuses_missing_creation_instead_of_numeric_zero(self):
        runtime = load(owner())
        runtime.set_template(0, 24)
        with self.assertRaises(SourceObjectRequired) as caught:
            runtime.parameters()
        self.assertEqual(caught.exception.request,
                         {'kind': 'level', 'application': 202, 'address': 255,
                          'source': 'scene_trigger_before_save_getter', 'group': 7})
        self.assertTrue(runtime.failed)

    def test_invoke_branch_is_captured_before_nil_trigger_setter_nested_template_change(self):
        runtime = load(owner())
        runtime.bind_context(replace(runtime.context,
                          trigger_levels=runtime.context.trigger_levels + ((202, 7, 255),)))
        runtime.set_template(0, 23)
        changed = []
        def dispatch(request, engine):
            if request.key == 0 and not changed and engine.snapshot()['keys'][0]['scene_trigger'] == 255:
                changed.append(True)
                engine.set_template(0, 16)
        runtime.control_dispatch = dispatch
        result = runtime.parameters()
        self.assertEqual(runtime.snapshot()['keys'][0]['template'], 16)
        self.assertEqual(result['SceneKeySelector'][0], 1)
        self.assertEqual([result[field][0] for field in ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand')],
                         [14, 0, 15, 15])

    def test_nil_trigger_callback_cannot_rewrite_earlier_corekey_pp_capture(self):
        runtime = load(owner(groups=[20, 21, 255, 255, 255, 255, 255, 255]), masks=[1] + [0] * 7)
        runtime.bind_context(replace(runtime.context,
                          trigger_levels=runtime.context.trigger_levels + ((202, 7, 255),)))
        runtime.set_template(0, 23)
        current_before = runtime.snapshot()
        self.assertEqual(current_before['blocks'][0]['group'], (56, 255))
        self.assertEqual(current_before['keys'][1]['references'], [])
        mutated = []
        def dispatch(request, engine):
            if request.key == 0 and not mutated and engine.snapshot()['keys'][0]['scene_trigger'] == 255:
                mutated.append(True)
                engine.set_group(0, (56, 20))
                engine.set_template(1, 24)
                engine.blocks[1].store1.set(91)
                engine.set_secondary(7, True)
        runtime.control_dispatch = dispatch
        start = len(runtime.events)
        result = runtime.parameters()
        current_after = runtime.snapshot()
        self.assertEqual(result['BlockAllocation'], [1, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(result['GroupAddress'], [255, 21, 255, 255, 255, 255, 255, 255])
        self.assertEqual(result['LightLevelStore1'], [0] * 8)
        self.assertEqual(current_after['keys'][1]['references'], [1])
        self.assertEqual(current_after['blocks'][0]['group'], (56, 20))
        self.assertEqual(current_after['blocks'][1]['group'], (56, 255))
        self.assertEqual(current_after['blocks'][1]['store1'], 91)
        # The later CoreNeoPro mask and later key row see current callbacks.
        self.assertEqual(result['SecondApplicationBlocks'], [128])
        self.assertEqual(result['SceneKeySelector'][:2], [1, 1])
        self.assertEqual(result['JPCommand'][:2], [14, 14])
        events = runtime.events[start:]
        corekey = next(index for index, event in enumerate(events) if event['operation'] == 'corekey_save_capture')
        scenes = next(index for index, event in enumerate(events) if event['operation'] == 'core_neo_scene_save_capture')
        trigger = next(index for index, event in enumerate(events)
                       if event.get('object') == 'key:0.scene_trigger' and event['operation'] == 'begin')
        self.assertLess(corekey, scenes)
        self.assertLess(scenes, trigger)

    def test_snapshot_is_detached_and_does_not_rearm_publishers(self):
        runtime = load(owner(), masks=[1] + [0] * 7)
        before = [(key.object._published, key.template._published) for key in runtime.keys]
        first = runtime.snapshot()
        second = runtime.snapshot()
        self.assertEqual(before, [(key.object._published, key.template._published) for key in runtime.keys])
        first['keys'][0]['references'].clear()
        first['bank_graph']['references']['ordered_references'][0].clear()
        first['events'][next(i for i, event in enumerate(first['events'])
                            if event['operation'] == 'reference_add')]['references'].clear()
        self.assertEqual(runtime.snapshot(), second)

    def test_indicator_constructor_is_zero_and_equal_direct_assignment_publishes(self):
        runtime = owner()
        self.assertEqual([key['indicator_block_number'] for key in runtime.snapshot()['keys']], [0] * 8)
        indicator = runtime.keys[3].indicator
        start = len(runtime.events)
        indicator.set(0)
        events = runtime.events[start:]
        self.assertEqual([event['operation'] for event in events
                          if event.get('object') == 'key:3.indicator'],
                         ['begin', 'assign', 'end', 'resolve', 'managed', 'references', 'changed'])
        reference = next(index for index, event in enumerate(events)
                         if event.get('object') == 'key:3.indicator' and event['operation'] == 'references')
        key_publish = next(index for index, event in enumerate(events)
                           if event.get('object') == 'key:3' and event['operation'] == 'managed')
        target_base = next(index for index, event in enumerate(events)
                           if event.get('object') == 'key:3.indicator' and event['operation'] == 'changed')
        self.assertLess(reference, key_publish)
        self.assertLess(key_publish, target_base)
        self.assertEqual(runtime.keys[3].object.depth, 0)

    def test_application_refresh_resolves_then_publishes_without_update_pairs(self):
        runtime = owner()
        runtime.load_allocations([0] * 8)
        start = len(runtime.events)
        runtime.finish_corekey_application_refresh()
        events = runtime.events[start:]
        for index in range(8):
            publications = [event for event in events if event.get('object') == f'key:{index}']
            # One parent pair belongs to the actual equal key Application
            # reference setter. Neither explicit publication adds a pair.
            self.assertEqual(sum(event['operation'] == 'begin' for event in publications), 1)
            self.assertEqual(sum(event['operation'] == 'end' for event in publications), 1)
            self.assertEqual(sum(event['operation'] == 'changed' and event['depth'] == 0
                                 for event in publications), 3)
            self.assertTrue(any(event['operation'] == 'changed' for event in publications))
        self.assertEqual(runtime.unit.depth, 0)

    def test_application_macro_refresh_scans_only_current_matching_side_not_mixed_keys(self):
        runtime = owner(secondary=2)
        runtime.load_allocations([3, 2, 0, 0, 0, 0, 0, 0])
        self.assertEqual([key['application_state'] for key in runtime.snapshot()['keys']],
                         [2, 1, 0, 0, 0, 0, 0, 0])
        start = len(runtime.events)
        runtime.finish_corekey_application_refresh()
        checks = [(event['secondary'], event['key']) for event in runtime.events[start:]
                  if event['operation'] == 'application_macro_subset_check']
        self.assertEqual(checks, [(False, key) for key in range(2, 8)] + [(True, 1)])

    def test_broadcast_reassignment_clears_old_override_and_writes_equal_nil_all8(self):
        runtime = load(owner())
        runtime.set_broadcast_block(0)
        runtime.set_broadcast_active(True)
        self.assertEqual([block['expiry_override'] for block in runtime.snapshot()['blocks']], [8] + [None] * 7)
        start = len(runtime.events)
        runtime.set_broadcast_block(1)
        self.assertEqual([block['expiry_override'] for block in runtime.snapshot()['blocks']],
                         [None, 8, None, None, None, None, None, None])
        events = runtime.events[start:]
        self.assertEqual({event['object'] for event in events
                          if event['operation'] == 'begin' and event.get('object', '').endswith('.expiry_override')},
                         {f'block:{index}.expiry_override' for index in range(8)})
        self.assertTrue(any(event['operation'] == 'reference_reset' and event.get('object') == 'block:0.expiry_override'
                            for event in events))

    def test_nil_application_failure_occurs_after_bool_and_reference_assignments(self):
        runtime = load(owner(application2=None))
        with self.assertRaisesRegex(SensorError, 'application object'):
            runtime.set_secondary(0, True)
        state = runtime.snapshot()
        self.assertTrue(state['failed'])
        self.assertTrue(state['blocks'][0]['secondary'])
        self.assertIsNone(state['blocks'][0]['application'])
        with self.assertRaisesRegex(SensorError, 'interrupted'):
            runtime.parameters()

    def test_installed_missing_group_decision_refuses_after_application_assignment(self):
        runtime = load(owner(groups=[20, 255, 255, 255, 255, 255, 255, 255]))
        with self.assertRaisesRegex(SensorError, 'installed native unit decision'):
            runtime.set_secondary(0, True)
        state = runtime.snapshot()
        self.assertTrue(state['blocks'][0]['secondary'])
        self.assertEqual(state['blocks'][0]['application'], 57)
        self.assertEqual(state['blocks'][0]['group'], (56, 20))
        self.assertEqual(state['created_groups'], [])

    def test_collection_update_suppresses_group_notification_without_deferred_refresh(self):
        runtime = load(owner(groups=[20, 255, 255, 255, 255, 255, 255, 255]), masks=[1] + [0] * 7)
        runtime.block_collection.begin_update()
        runtime.set_group(0, (56, 255))
        runtime.block_collection.end_update()
        self.assertEqual(runtime.snapshot()['keys'][0]['primary_group'], (56, 20))
        self.assertEqual(runtime.snapshot()['blocks'][0]['group'], (56, 255))
        self.assertTrue(any(event['operation'] == 'block_group_notification_suppressed'
                            for event in runtime.snapshot()['events']))

    def test_causal_context_binding_preserves_identity_without_hidden_callbacks(self):
        runtime = load(owner(groups=[20, 255, 255, 255, 255, 255, 255, 255]), masks=[1] + [0] * 7)
        group = runtime.groups[(56, 20)]
        key_group = runtime.keys[0].primary_group._value
        old = runtime.snapshot()
        context = replace(runtime.context,
                          group_identities=runtime.context.group_identities + ((56, 21),),
                          protected_groups=((56, 20),), join_active=True)
        runtime.bind_context(context)
        self.assertIs(runtime.groups[(56, 20)], group)
        self.assertIs(runtime.keys[0].primary_group._value, key_group)
        self.assertEqual(runtime.snapshot()['blocks'], old['blocks'])
        self.assertEqual(runtime.snapshot()['bank_graph'], old['bank_graph'])
        self.assertEqual(runtime.events[-1], {'operation': 'owning_context_bound'})
        self.assertIn((56, 21), runtime.groups)
        # The actual later Group setter, rather than context binding, owns the
        # now-protected-group collision and clears this block.
        runtime.set_group(0, (56, 20))
        self.assertEqual(runtime.snapshot()['blocks'][0]['group'], (56, 255))

    def test_causal_context_binding_refuses_removal_and_application_replacement(self):
        runtime = load(owner())
        with self.assertRaisesRegex(SensorError, 'discard'):
            runtime.bind_context(replace(runtime.context, group_identities=((56, 255), (57, 255)),
                                         trigger_levels=()))
        with self.assertRaisesRegex(SensorError, 'owning setter'):
            runtime.bind_context(replace(runtime.context, secondary_application=None))
        self.assertFalse(runtime.failed)

    def test_bank_graph_adoption_uses_suppressed_owned_feedback(self):
        runtime = load(owner(), masks=[1] + [0] * 7)
        graph = runtime.graph.set_high_lux(0, 130)
        start = len(runtime.events)
        runtime.adopt_bank_graph(graph)
        state = runtime.snapshot()
        self.assertEqual(state['blocks'][0]['store1'], 13)
        self.assertEqual(state['bank_graph']['banks'][0]['high_lux'], 130)
        self.assertEqual(state['keys'][0]['references'], [0])
        events = runtime.events[start:]
        self.assertTrue(any(event['operation'] == 'bank_feedback_suppressed' and event['block'] == 0
                            for event in events))
        self.assertFalse(any(event['operation'] == 'block_published' for event in events))
        with self.assertRaisesRegex(SensorError, 'ordered key references'):
            runtime.adopt_bank_graph(SENLLABankGraph.fresh())
        self.assertFalse(runtime.failed)

    def test_general_hook_requires_controls_before_first_template_activation(self):
        runtime = load(owner(), fresh=False)
        runtime.fresh_function_bindings()
        with self.assertRaises(SourceControlRequired) as caught:
            runtime.install_m8_hooks()
        self.assertEqual(caught.exception.request,
                         {'key': 0, 'operation': 'general_key_controls',
                          'source': 'ST7.CBusUnitInputKeyChanged', 'classification': False})
        self.assertIsNone(runtime.keys[0].function_hook)
        self.assertTrue(runtime.failed)
        with self.assertRaisesRegex(SensorError, 'interrupted'):
            runtime.parameters()

    def test_general_hook_executor_precedes_recall_and_rereads_nested_changes(self):
        runtime = load(owner(store1=[249, 252, 0, 0, 0, 0, 0, 0]),
                       masks=[1, 2, 0, 0, 0, 0, 0, 0],
                       stages=[[12, 0, 0, 0]] * 2 + [[0] * 4] * 6, fresh=False)
        runtime.fresh_function_bindings()
        requests = []
        def dispatch(request, engine):
            requests.append((request.key, engine.keys[request.key].function_hook is not None,
                             engine.snapshot()['keys'][1]['template']))
            if len(requests) == 1:
                engine.set_template(0, 16)
        runtime.install_m8_hooks(control_dispatch=dispatch)
        # Key general hook is active before its template hook. Its nested
        # setter delivers the general hook recursively with current16.
        self.assertEqual(requests[0], (0, False, 18))
        self.assertEqual(requests[1], (0, False, 18))
        self.assertEqual(runtime.snapshot()['keys'][0]['template'], 16)
        self.assertEqual(runtime.snapshot()['keys'][1]['template'], 18)
        self.assertEqual([key for key, _, _ in requests[2:]], list(range(1, 8)))

    def test_owned_indicator_and_extension_publish_general_hook_in_reference_phase(self):
        runtime = load(owner(), fresh=False)
        runtime.fresh_function_bindings()
        requests = []
        runtime.install_m8_hooks(control_dispatch=lambda request, engine: requests.append(request.key))
        requests.clear()
        start = len(runtime.events)
        runtime.keys[3].indicator.set(1)
        self.assertEqual(requests, [3])
        events = runtime.events[start:]
        request = next(index for index, event in enumerate(events)
                       if event['operation'] == 'general_key_control_request')
        target_base = next(index for index, event in enumerate(events)
                           if event.get('object') == 'key:3.indicator' and event['operation'] == 'changed')
        self.assertLess(request, target_base)
        requests.clear()
        runtime.keys[3].scene_rate.set(4)
        self.assertEqual(requests, [3])
        self.assertEqual(runtime.snapshot()['keys'][3]['scene_rate'], 4)

    def test_owned_indicator_relay_respects_parent_update_depth(self):
        runtime = load(owner(), fresh=False)
        runtime.fresh_function_bindings()
        requests = []
        runtime.install_m8_hooks(control_dispatch=lambda request, engine: requests.append(request.key))
        requests.clear()
        runtime.keys[3].object.begin_update()
        runtime.keys[3].indicator.set(2)
        self.assertEqual(requests, [])
        runtime.keys[3].object.end_update()
        self.assertEqual(requests, [3])

    def test_phase_order_and_interrupted_runtime_refuse_projection(self):
        runtime = owner()
        self.assertEqual(runtime.snapshot()['unit_depth'], 1)
        with self.assertRaisesRegex(SensorError, 'phase'):
            runtime.finish_corekey_application_refresh()
        with self.assertRaisesRegex(SensorError, 'interrupted'):
            runtime.load_allocations([0] * 8)
        with self.assertRaisesRegex(SensorError, 'interrupted'):
            runtime.parameters()

    def test_admission_bounds_and_inputs_preserved(self):
        runtime = owner()
        rows = [[0, 0, 0, 0] for _ in range(8)]
        original = copy.deepcopy(rows)
        load(runtime, stages=rows)
        self.assertEqual(rows, original)
        with self.assertRaises(SensorError):
            KeyEventContext(47, None, (47,), ((47, 255),))
        with self.assertRaises(SensorError):
            BlockValues(False, (56, 255), timer=65536)
        with self.assertRaises(SensorError):
            BlockValues(1, (56, 255))
        with self.assertRaises(SensorError):
            owner().load_allocations([True] * 8)
        with self.assertRaises(SensorError):
            runtime.set_template(0, True)


if __name__ == '__main__':
    unittest.main()
