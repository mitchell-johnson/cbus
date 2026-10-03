"""Authored shared-object prekey cases; no original runtime or backend proof."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_inputs import SCHEMA, SENLLAInputSnapshot
from cbus_toolkit.senlla_prekey import PrekeyOwnerRequest, SENLLAPrekey
from cbus_toolkit.sensors import SensorError


def raw(**changes):
    values = {name: 'INPUT' if row[0] == 'sixbit' else [0] * row[2]
              for name, row in SCHEMA.items()}
    values.update(Application=[56, 57], AreaGroupAddress=[255],
                  GroupAddress=[255] * 8, SceneTable=[255] * 80,
                  PatchEnable=[157, 64], LightLevel=[10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
    values.update(changes)
    return SENLLAInputSnapshot(('SENLLA', '2.4.00', '5754PE'), values)


class SourceOwner:
    """Authored executor confirming only the object at the actual lookup.

    This records causal boundaries and represents no native creation/storage
    acceptance. It deliberately supplies no future final KeyEventContext.
    """
    def __init__(self):
        self.calls = []
        self.actual_applications = set()
        self.actual_groups = set()
        self.creations = []
        self.inherited_calls = []
        self.before_lookup = None
        self.before_inherited = None

    def source(self, request, engine):
        self.calls.append((request.as_dict(), engine.unit.depth))
        if self.before_lookup:
            self.before_lookup(request, engine)
        if request.kind == 'application':
            if request.address not in self.actual_applications:
                if not request.create:
                    return
                self.actual_applications.add(request.address)
                self.creations.append(('application', request.address))
            engine.add_source_application(request.address)
        else:
            identity = (request.application, request.address)
            if identity not in self.actual_groups:
                if not request.create:
                    return
                self.actual_groups.add(identity)
                self.creations.append(('group', *identity))
            engine.add_source_group(engine.apps[request.application], request.address)

    def inherited(self, request, owner):
        self.inherited_calls.append((request.as_dict(), owner.runtime.unit.depth))
        if self.before_inherited:
            self.before_inherited(request, owner)


def fresh(snapshot=None, source_owner=None):
    executor = source_owner or SourceOwner()
    return SENLLAPrekey(snapshot or raw(), source_dispatch=executor.source,
                       inherited_dispatch=executor.inherited), executor


class SENLLAPrekeyTests(unittest.TestCase):
    def test_constructor_nil_references_and_post_bank_link_state(self):
        owner, executor = fresh()
        state = owner.snapshot()
        engine = owner.runtime
        self.assertEqual(engine.unit.depth, 0)
        self.assertIsNone(engine.primary_application._value)
        self.assertIsNone(engine.secondary_application._value)
        self.assertIsNone(engine.area._value)
        self.assertEqual(engine.apps, {})
        self.assertEqual(engine.groups, {})
        for block in engine.blocks:
            self.assertIsNone(block.application._value)
            self.assertIsNone(block.group._value)
            self.assertIsNone(block.expiry._value)
            self.assertIsNone(block.expiry_override._value)
            self.assertFalse(block.secondary._value)
            self.assertEqual([getattr(block, name)._value for name in
                              ('light_level', 'store1', 'store2', 'timer', 'timer_cached')], [0] * 5)
        for key in engine.keys:
            self.assertIsNone(key.application._value)
            self.assertIsNone(key.template._value)
            self.assertEqual(key.refs, [])
            self.assertEqual(key.application_state._value, 0)
        self.assertTrue(all(bank.switch_allowed and not bank.switch_active and
                            bank.high_lux == bank.low_lux == 0 for bank in engine.graph.banks))
        self.assertFalse(state['initialized'])
        self.assertEqual(state['status_report_interval'], 0)
        self.assertEqual(executor.calls, [])

    def test_same_objects_managers_attributes_and_counter_continue_through_allocations(self):
        owner, _ = fresh(raw(BlockAllocation=[5, 0, 0, 0, 0, 0, 0, 0]))
        engine = owner.runtime
        identities = (engine.unit, engine.unit_manager, engine.block_collection,
                      engine.blocks, engine.keys, engine._bank_block_links,
                      *(block.group for block in engine.blocks),
                      *(key.template for key in engine.keys))
        returned = owner.load_to_key_blocks()
        self.assertIs(returned, engine)
        self.assertEqual(engine.unit.depth, 1)
        self.assertEqual(engine.phase, 'get_key_blocks')
        engine.load_allocations(owner.raw.expected['BlockAllocation'])
        engine.finish_corekey_application_refresh()
        self.assertEqual(engine.keys[0].refs, [0, 2])
        self.assertEqual(engine.unit.depth, 0)
        after = (engine.unit, engine.unit_manager, engine.block_collection,
                 engine.blocks, engine.keys, engine._bank_block_links,
                 *(block.group for block in engine.blocks),
                 *(key.template for key in engine.keys))
        self.assertTrue(all(before is now for before, now in zip(identities, after)))

    def test_first_primary_area_callback_binds_all_eight_keys_before_secondary_lookup(self):
        owner, executor = fresh()
        observations = []
        def observe(request, engine):
            observations.append((request.kind, request.application, request.address,
                                 engine.unit.depth, tuple(key.application._value for key in engine.keys)))
        executor.before_lookup = observe
        engine = owner.load_to_key_blocks()
        self.assertEqual([(kind, app, address, depth) for kind, app, address, depth, _ in observations],
                         [('application', None, 56, 2), ('group', 56, 255, 3),
                          ('application', None, 57, 2)])
        secondary = observations[-1]
        self.assertTrue(all(app is engine.apps[56] for app in secondary[-1]))
        self.assertTrue(all(key.application._value is engine.apps[56] for key in engine.keys))
        self.assertTrue(all(key.template._value is None for key in engine.keys))
        self.assertTrue(all(block.application._value is engine.apps[56] for block in engine.blocks))
        self.assertIs(engine.area._value, engine.groups[(56, 255)])
        # A secondary manager's unused object is not manufactured to admit a
        # handoff when no source getter has touched it.
        self.assertNotIn((57, 255), engine.groups)

    def test_inherited_owner_positions_area_status_and_all_bits_before_rows(self):
        owner, executor = fresh(raw(AreaGroupAddress=[20], StatusReportInterval=[2],
                                   SecondApplicationBlocks=[165], GroupAddress=[20] * 8))
        observations = []
        executor.before_inherited = lambda request, state: observations.append(
            (request.operation, state.runtime.area._value, state.status_report_interval._value))
        engine = owner.load_to_key_blocks()
        self.assertEqual([item[0]['operation'] for item in executor.inherited_calls],
                         ['base_agent_after_load', 'unit_metadata_after_applications',
                          'learn_after_inherited_unit', 'core_scalars_before_blocks'])
        self.assertEqual([item[1] for item in executor.inherited_calls], [1, 1, 1, 1])
        self.assertIsNone(observations[0][1])
        self.assertIs(observations[1][1], engine.groups[(56, 255)])
        self.assertIs(observations[-1][1], engine.groups[(56, 20)])
        self.assertEqual(observations[-1][2], 2)  # Global min3 is later.
        requests = [event['request'] for event in engine.events
                    if event.get('operation') == 'prekey_block_request']
        self.assertEqual(len(requests), 66)
        self.assertEqual([item['field'] for item in requests[:10]],
                         ['secondary'] * 8 + ['light_index', 'loaded_light_count'])
        self.assertEqual([item['value'] for item in requests[:8]],
                         [True, False, True, False, False, True, False, True])
        self.assertEqual([block.group._value.identity for block in engine.blocks],
                         [(57, 20), (56, 20), (57, 20), (56, 20),
                          (56, 20), (57, 20), (56, 20), (57, 20)])

    def test_false_probe_queries_actual_manager_before_default_creation(self):
        executor = SourceOwner()
        # Existing source data may be absent from the engine's encountered
        # registry. A source probe must distinguish that from actual absence.
        executor.actual_applications.update((56, 57))
        executor.actual_groups.add((57, 255))
        owner, _ = fresh(raw(SecondApplicationBlocks=[1]), executor)
        engine = owner.load_to_key_blocks()
        probes = [request for request, _depth in executor.calls
                  if request['kind'] == 'group' and request['application'] == 57]
        self.assertEqual([(request['address'], request['create']) for request in probes], [(255, False)])
        self.assertNotIn(('group', 57, 255), executor.creations)
        self.assertIs(engine.blocks[0].group._value, engine.groups[(57, 255)])
        owner, executor = fresh(raw(SecondApplicationBlocks=[1]))
        owner.load_to_key_blocks()
        probes = [request for request, _depth in executor.calls
                  if request['kind'] == 'group' and request['application'] == 57]
        self.assertEqual([(request['address'], request['create']) for request in probes],
                         [(255, False), (255, True)])
        self.assertEqual(executor.creations.count(('group', 57, 255)), 1)

    def test_indexed_level_literals_and_source_array_growth(self):
        expected = ((0, [10, 20, 30, 40, 50, 60, 70, 80], 10),
                    (1, [20, 30, 40, 50, 60, 70, 80, 90], 10),
                    (2, [30, 40, 50, 60, 70, 80, 90, 100], 10),
                    (3, [40, 50, 60, 70, 80, 90, 100, 0], 11),
                    (255, [0] * 8, 263))
        for index, levels, count in expected:
            with self.subTest(index=index):
                owner, _ = fresh(raw(LightIndex=[index]))
                engine = owner.load_to_key_blocks()
                current = [block.light_level._value for block in engine.blocks]
                self.assertEqual(current, levels)
                rebuilt = owner.plan.parameters(current, light_index=owner.light_index)
                self.assertEqual(len(rebuilt['LightLevel']), count)
                self.assertEqual(rebuilt['LightLevel'][:index], [255] * index)
                self.assertEqual(owner.loaded_light_count, 10)

    def test_registered_expiry_zero_unsigned_timer_and_all_membership_literals(self):
        normal = (0, 15, 15, 15, 4, 15, 6, 15, 15, 9, 10, 15, 12, 15, 15, 15)
        for value, expected in enumerate(normal):
            with self.subTest(raw=value):
                owner, _ = fresh(raw(TimerExpiryCommand=[value] * 8,
                                     TimerHighByte=[1] * 8, TimerLowByte=[44] * 8))
                engine = owner.load_to_key_blocks()
                self.assertTrue(all(block.expiry._value is engine.micro[expected] for block in engine.blocks))
                self.assertTrue(all(block.timer._value == 300 for block in engine.blocks))
                self.assertTrue(all(block.timer_cached._value == 0 and
                                    block.expiry_override._value is None for block in engine.blocks))

    def test_expiry_membership_uses_current_pointer_after_publication(self):
        owner, _ = fresh(raw(TimerExpiryCommand=[3] * 8))
        engine = owner.runtime
        active = [False]
        def change_current(_):
            if engine.blocks[0].expiry._value is engine.micro[3] and not active[0]:
                active[0] = True
                engine.blocks[0].expiry.set(engine.micro[6])
        engine.blocks[0].object.publisher.subscribe(change_current)
        owner.load_to_key_blocks()
        self.assertIs(engine.blocks[0].expiry._value, engine.micro[6])
        self.assertTrue(all(block.expiry._value is engine.micro[15] for block in engine.blocks[1:]))
        reads = [event for event in engine.events
                 if event.get('operation') == 'prekey_current_expiry_membership']
        self.assertEqual([event['value'] for event in reads], [6] + [3] * 7)

    def test_later_rows_use_current_light_index_and_current_secondary_group_owner(self):
        owner, _ = fresh(raw(TimerExpiryCommand=[3] + [0] * 7, GroupAddress=[20] * 8))
        engine = owner.runtime
        armed = [True]
        def nested(_):
            if armed[0] and engine.blocks[0].expiry._value is engine.micro[3]:
                armed[0] = False
                owner.light_index = 2
                engine.blocks[0].secondary.set(True)
        engine.blocks[0].object.publisher.subscribe(nested)
        owner.load_to_key_blocks()
        self.assertEqual([block.light_level._value for block in engine.blocks],
                         [10, 40, 50, 60, 70, 80, 90, 100])
        self.assertIs(engine.blocks[0].group._value, engine.groups[(57, 20)])
        self.assertIs(engine.blocks[1].group._value, engine.groups[(56, 20)])
        self.assertEqual(owner.raw.expected['SecondApplicationBlocks'], (0,))
        self.assertEqual(owner.raw.expected['LightIndex'], (0,))
        self.assertEqual(owner.light_index, 2)
        reads = [event for event in engine.events
                 if event.get('operation') == 'prekey_current_indexed_level']
        self.assertEqual([event['light_index'] for event in reads], [0] + [2] * 7)
        groups = [event for event in engine.events
                  if event.get('operation') == 'prekey_current_group_getter']
        self.assertEqual([event['application'] for event in groups], [57] + [56] * 7)

    def test_bank_store_publications_run_while_outer_unit_is_updating(self):
        owner, _ = fresh(raw(LightLevelStore1=[1, 2, 3, 4, 5, 6, 7, 8],
                             LightLevelStore2=[8, 7, 6, 5, 4, 3, 2, 1]))
        engine = owner.runtime
        depths = []
        engine.blocks[0].object.publisher.subscribe(lambda _: depths.append(engine.unit.depth))
        owner.load_to_key_blocks()
        self.assertIn(3, depths)  # Initial primary callback.
        self.assertIn(1, depths)  # Raw scalar/group setters, no row wrapper.
        self.assertEqual([bank.high_lux for bank in engine.graph.banks], [10, 20, 30, 40, 50, 60, 70, 80])
        self.assertEqual([bank.low_lux for bank in engine.graph.banks], [80, 70, 60, 50, 40, 30, 20, 10])
        self.assertTrue(all(bank.switch_allowed and not bank.switch_active for bank in engine.graph.banks))
        self.assertEqual(engine.unit.depth, 1)

    def test_actual_app255_remains_bound_and_collision_waits_until_after_allocations(self):
        for mask in (0, 254):
            with self.subTest(mask=mask):
                owner, _ = fresh(raw(Application=[56, 255], SecondApplicationBlocks=[mask],
                                     GroupAddress=[20] * 8))
                engine = owner.load_to_key_blocks()
                secondary = engine.secondary_application._value
                self.assertIs(secondary, engine.apps[255])
                self.assertEqual([block.group._value.identity[1] for block in engine.blocks], [20] * 8)
                engine.load_allocations(owner.raw.expected['BlockAllocation'])
                engine.finish_corekey_application_refresh()
                self.assertIs(engine.secondary_application._value, secondary)
                self.assertEqual([block.secondary._value for block in engine.blocks], [False] * 8)
                expected = [20] * 8 if mask == 0 else [20] + [255] * 7
                self.assertEqual([block.group._value.identity[1] for block in engine.blocks], expected)

    def test_equal_primary_reference_still_runs_dedicated_area_and_binding_callbacks(self):
        owner, executor = fresh()
        def inherited(request, state):
            if request.operation == 'unit_metadata_after_applications':
                before = len(state.runtime.events)
                primary = state.runtime.primary_application.value
                state.runtime.primary_application.set(primary)
                events = state.runtime.events[before:]
                self.assertTrue(any(event.get('object') == 'unit.area' and
                                    event.get('operation') == 'begin' for event in events))
                self.assertTrue(all(key.application._value is primary for key in state.runtime.keys))
        executor.before_inherited = inherited
        owner.load_to_key_blocks()

    def test_failures_keep_causal_requests_invalidate_and_refuse_replay(self):
        owner = SENLLAPrekey(raw(), source_dispatch=None, inherited_dispatch=lambda *_: None)
        with self.assertRaises(SensorError):
            owner.load_to_key_blocks()
        self.assertTrue(owner.runtime.failed)
        self.assertEqual(owner.runtime.unit.depth, 0)
        lookup = [event['request'] for event in owner.runtime.events
                  if event.get('operation') == 'source_lookup']
        self.assertEqual(lookup[0]['kind'], 'application')
        self.assertEqual(lookup[0]['address'], 56)
        with self.assertRaises(SensorError):
            owner.load_to_key_blocks()
        owner, executor = fresh()
        def failure(request, state):
            if request.operation == 'core_scalars_before_blocks':
                raise RuntimeError('authored owning scalar failure')
        executor.before_inherited = failure
        with self.assertRaisesRegex(RuntimeError, 'authored'):
            owner.load_to_key_blocks()
        self.assertTrue(owner.runtime.failed)
        self.assertEqual(owner.runtime.unit.depth, 0)
        self.assertTrue(all(block.object.depth == 0 for block in owner.runtime.blocks))

    def test_guarded_input_and_executor_return_contracts(self):
        for value in (None, {}, raw().parameters(), True):
            with self.subTest(value=type(value).__name__), self.assertRaises(SensorError):
                SENLLAPrekey(value)
        for apps in ([0, 57], [255, 56], [56, 202]):
            with self.subTest(apps=apps), self.assertRaises(SensorError):
                SENLLAPrekey(raw(Application=apps))
        for name in ('source_dispatch', 'inherited_dispatch'):
            with self.subTest(name=name), self.assertRaises(SensorError):
                SENLLAPrekey(raw(), **{name: {}})
        owner, _ = fresh()
        owner.inherited_dispatch = lambda *_: {'future': 'context'}
        with self.assertRaises(SensorError):
            owner.load_to_key_blocks()
        self.assertTrue(owner.runtime.failed)

    def test_raw_snapshot_requests_and_inspection_are_detached(self):
        snapshot = raw(StatusReportInterval=[2])
        owner, _ = fresh(snapshot)
        before = snapshot.parameters()
        exported = owner.snapshot()
        exported['expected']['GroupAddress'][0] = 20
        exported['runtime']['keys'][0]['references'].append(0)
        owner.load_to_key_blocks()
        exported = owner.snapshot()
        exported['requests'][0]['parameters'].append('GroupAddress')
        self.assertEqual(snapshot.parameters(), before)
        self.assertEqual(owner.raw.parameters(), before)
        self.assertEqual(owner.snapshot()['requests'][0]['parameters'], [])
        self.assertEqual(owner.status_report_interval._value, 2)
        self.assertEqual(owner.runtime.keys[0].refs, [])
        request = PrekeyOwnerRequest('operation', 'source', ('Project',))
        with self.assertRaises(FrozenInstanceError):
            request.operation = 'other'
        for flag in ('complete_toolkit_save', 'saved', 'original_execution', 'physical_acceptance'):
            self.assertFalse(owner.snapshot()[flag])

    def test_derived_source_receipt_preserves_scope_and_initial_literal_fields(self):
        source = json.loads((Path(__file__).parents[1] /
                             'research/fixtures/senlla-prekey-source.json').read_text())
        self.assertEqual(source['raw_application255_is_actual_object'], True)
        self.assertEqual(source['get_key_blocks_entry_unit_depth'], 1)
        self.assertEqual(source['constructor_key_application'], None)
        self.assertEqual(source['entry_key_application'], 'primary')
        self.assertEqual(source['allowed_expiry_types'], [0, 15, 4, 9, 12, 6, 10])
        self.assertFalse(source['original_execution'])
        self.assertFalse(source['complete_toolkit_save'])
        self.assertTrue(source['method_pins'])


if __name__ == '__main__':
    unittest.main()
