"""Authored causal late Unit cases, without native Toolkit acceptance."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cbus_toolkit.senlla_inherited_owner import SENLLAInheritedOwner
from cbus_toolkit.senlla_late_unit import SENLLALateUnit
from cbus_toolkit.senlla_owner import SENLLAParameterJournal
from cbus_toolkit.senlla_project_bridge import SENLLAProjectBridge
from cbus_toolkit.sensors import SensorError
from test_senlla_inherited_owner import document, english_metadata_name, snapshot


class SENLLALateUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'owned.xml'
        self.project = document(self.path)

    def owner(self, raw=None, *, load=True, creation_dispatch=None):
        raw = raw or snapshot()
        if creation_dispatch is None:
            # Explicit authored zero-listener metadata context.
            creation_dispatch = lambda request, bridge, runtime: None
        bridge = SENLLAProjectBridge.from_document(self.project, 254, 42,
            storage_path=self.path, metadata_name=english_metadata_name,
            creation_dispatch=creation_dispatch)
        inherited = SENLLAInheritedOwner(raw, bridge)
        journal = SENLLAParameterJournal(raw)
        late = SENLLALateUnit(inherited, journal)
        if load:
            inherited.prekey.load_to_key_blocks()
            inherited.runtime.load_allocations(raw.expected['BlockAllocation'])
            inherited.runtime.finish_corekey_application_refresh()
        return inherited, journal, late

    def test_ctor_registers_nil_refs_and_false_fields_on_same_live_managers(self):
        inherited, journal, late = self.owner(load=False)
        engine = inherited.runtime
        for name, attr in late.attributes.items():
            with self.subTest(name=name):
                self.assertIs(attr.manager, engine.unit_manager)
                self.assertIs(inherited.unit_attribute(name), attr)
        self.assertIs(late.attribute('LightLevelBroadcastActive'), engine.broadcast_active)
        self.assertIs(late.attribute('LightLevelBroadcastBlock'), engine.broadcast_block)
        self.assertIsNone(late.attribute('JoinGroup')._value)
        self.assertFalse(late.attribute('Nightlight')._value)
        self.assertEqual(engine.protected_group_attributes, (
            late.attribute('LightLevelMaintEnableGroup'), late.attribute('JoinGroup'),
            late.attribute('CorridorLinkGroup')))
        self.assertTrue(all(attr.manager is block.manager for attr, block in
                            zip(late.timer_minimum, engine.blocks)))
        self.assertTrue(all(a.manager.parent is obj for a, obj in zip(late.use_low, late.bank_objects)))
        self.assertEqual(journal.captures(), ())
        self.assertEqual(engine.unit.depth, 0)

    def test_st7_uses_current_pp_after_actual_prior_setter_publication(self):
        inherited, journal, late = self.owner(snapshot(PECTargetLux=[10], PECMarginLux=[2]))
        observed = []
        def target_changed(attr):
            observed.append((attr._value, inherited.runtime.unit.depth))
            journal.capture('PECTargetLux', [100], source='authored.target.observer')
            journal.capture('PECMarginLux', [35], source='authored.target.observer')
        late.attribute('LightLevelTargetLux').publisher.subscribe(target_changed)
        late.load_st7()
        self.assertEqual(observed, [(10, 1)])
        self.assertEqual(late.attribute('LightLevelMarginPerc').value, 35)
        self.assertEqual(late.attribute('LightLevelScale').value, 0)
        self.assertIs(late.attribute('InfraredKeyOffset').value, inherited.runtime.keys[0].object)
        self.assertIs(late.attribute('PotentiometerABlock').value, inherited.runtime.blocks[0].object)

    def test_maintenance_commits_before_subscribers_without_allowed_refresh(self):
        inherited, _, late = self.owner(snapshot(PECFunctionActive=[1], PECFunctionBlock=[3]))
        seen = []
        late.attribute('LightLevelMaintActive').publisher.subscribe(
            lambda _: seen.append((inherited.runtime.graph.maintenance_active,
                                   inherited.runtime.graph.maintenance_block,
                                   inherited.runtime.graph.banks[3].switch_allowed)))
        late.attribute('LightLevelMaintBlock').publisher.subscribe(
            lambda _: seen.append((inherited.runtime.graph.maintenance_active,
                                   inherited.runtime.graph.maintenance_block,
                                   inherited.runtime.graph.banks[3].switch_allowed)))
        late.load_st7()
        self.assertEqual(seen, [(True, None, True), (True, 3, True)])
        # Subsequent broadcast block/expiry publications can refresh Allowed.
        self.assertFalse(inherited.runtime.graph.banks[3].switch_allowed)

    def test_source_bank_rows_active_then_off_and_occupancy_feedback_keep_objects(self):
        inherited, _, late = self.owner(snapshot(
            LightLevelStore1=[10] * 8, LightLevelStore2=[20] * 8,
            BlockBankSwitchActive=[1] * 8, BlockGroupLogic=[1] * 8,
            BlockAllocation=[1, 0, 0, 0, 0, 0, 0, 0], PIRLightMovement=[1], PIRDarkMovement=[1]))
        engine = inherited.runtime
        before = (engine.unit, engine.unit_manager, *engine.blocks, *engine.keys)
        late.load_st7()
        calls = [(row['bank'], row['field']) for row in engine.events
                 if row.get('operation') == 'late_bank_setter']
        self.assertEqual(calls, [(i, f) for i in range(8) for f in ('active', 'off')])
        self.assertTrue(engine.graph.occupancy[0].any_movement)
        self.assertFalse(engine.graph.banks[0].switch_active)
        self.assertTrue(all(bank.enable_group_off for bank in engine.graph.banks))
        self.assertTrue(all(a is b for a, b in zip(before,
            (engine.unit, engine.unit_manager, *engine.blocks, *engine.keys))))

    def test_bank_setter_publishes_live_attribute_before_next_current_pp_read(self):
        inherited, journal, late = self.owner(snapshot(BlockBankSwitchActive=[1] * 8))
        bank = late.live_banks.banks[0]
        seen = []
        def active_changed(attr):
            seen.append((attr is bank.active, attr._value, bank.object.depth))
            journal.capture('BlockGroupLogic', [1] * 8, source='authored.bank.active.observer')
        bank.active.publisher.subscribe(active_changed)
        late.load_st7()
        self.assertEqual(seen, [(True, True, 1)])
        self.assertTrue(bank.off.value)
        self.assertIs(late.bank_objects[0], bank.object)
        self.assertIs(late.bank_managers[0], bank.manager)
        self.assertIs(late.use_low[0], bank.use_low)
        self.assertIs(late.use_high[0], bank.use_high)

    def test_surface_power_captures_original_margin_before_current_pp_clear(self):
        inherited, journal, late = self.owner(snapshot(LightLevelTargetGroup=[7],
            LightLevelMarginGroup=[8], LightLevelMarginGroupLevelStore=[0],
            PECTargetLux=[100], PECMarginLux=[20], PowerUpTargetGroupLevel=[90],
            PowerUpMarginGroupLevel=[80]))
        late.load_st7()
        late.load_surface()
        self.assertEqual(late.attribute('PowerUpMarginGroupState').value, 0)
        self.assertEqual(late.attribute('PowerUpMarginGroupPresetLevel').value, 80)
        self.assertEqual(late.attribute('LightLevelTargetGroup').value.identity, (56, 7))
        self.assertEqual(late.attribute('LightLevelMarginGroup').value.identity, (56, 255))
        self.assertFalse(late.attribute('IsUsingLightLevelMarginGroup').value)
        self.assertEqual((late.attribute('LightLevelTargetLux').value,
                          late.attribute('LightLevelMarginPerc').value), (45, 20))
        self.assertEqual(journal.read('LightLevelMarginGroup'), [255])
        self.assertEqual(journal.snapshot.expected['LightLevelMarginGroup'], (8,))
        self.assertEqual(journal.captures()[-1].source, '0x1217836')
        self.assertNotIn((56, 8), inherited.runtime.groups)

    def test_each_surface_getter_uses_current_application_after_storage_callback(self):
        inherited, _, late = self.owner(snapshot(LightLevelTargetGroup=[7], LightLevelMarginGroup=[8]))
        late.load_st7()
        engine = inherited.runtime
        app = engine.get_source_application(57, source='authored.existing.secondary')
        def changed(_):
            engine.primary_application.set(app)
        late.attribute('LightLevelTargetGroup').publisher.subscribe(changed)
        late.load_surface()
        self.assertEqual(late.attribute('LightLevelTargetGroup').value.identity, (56, 7))
        self.assertEqual(late.attribute('LightLevelMarginGroup').value.identity, (57, 255))
        self.assertEqual(late.attribute('BankSwitchHighGroup').value.identity, (57, 0))

    def test_surface_low_flag_observer_can_clear_current_use_before_low_lux(self):
        inherited, _, late = self.owner(snapshot(BankSwitchThresholdBehaviour=[1],
            BankSwitchThresholdGroup=[7], BankSwitchGroupUsed=[1] * 8,
            LightLevelStore2=[20] * 8))
        late.load_st7()
        late.use_high[0].on_changed = lambda _: late.use_low[0].set(False)
        # Force an unequal High setter so its actual subscriber runs.
        late.use_high[0].set(True)
        inherited.runtime.graph = inherited.runtime.graph._bank(0,
            replace(inherited.runtime.graph.banks[0], low_lux=200))
        late.load_surface()
        self.assertFalse(late.use_low[0].value)
        self.assertEqual(inherited.runtime.graph.banks[0].low_lux, 200)
        self.assertEqual([attr.value for attr in late.use_low], [False] + [True] * 7)
        self.assertEqual(inherited.runtime.graph.banks[1].low_lux, 0)

    def test_corridor_equal_ref_before_change_and_timer_minimum_are_live(self):
        inherited, _, late = self.owner()
        engine = inherited.runtime
        block = engine.blocks[2]
        late.set('CorridorLinkCorridorBlock', block.object, source='authored.bind')
        late.set('CorridorLinkActive', True, source='authored.active')
        self.assertEqual((block.timer.value, late.timer_minimum[2].value), (300, 60))
        block.timer.set(1)
        self.assertEqual(block.timer.value, 60)
        publications = []
        late.timer_minimum[2].on_changed = lambda a: publications.append(a._value)
        late.set('CorridorLinkCorridorBlock', block.object, source='authored.equal_ref')
        self.assertEqual(publications, [0, 60])
        late.set('CorridorLinkCorridorBlock', None, source='authored.clear')
        self.assertEqual(late.timer_minimum[2].value, 0)
        self.assertIsNone(late.attribute('CorridorLinkCorridorBlock').value)

    def test_out_of_order_load_invalidates_runtime_and_cannot_serialize(self):
        inherited, _, late = self.owner()
        with self.assertRaisesRegex(SensorError, 'ST7 parent'):
            late.load_surface()
        self.assertTrue(inherited.runtime.failed)
        with self.assertRaisesRegex(SensorError, 'interrupted'):
            late.load_st7()


if __name__ == '__main__':
    unittest.main()
