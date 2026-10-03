"""Source-position journal regressions; no whole owning workflow acceptance."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from cbus_toolkit.senlla_owner import SENLLAParameterJournal, SENLLAOwner, OwnerPhaseRequired
from cbus_toolkit.sensors import SensorError
from test_senlla_inputs import fixture, current
from cbus_toolkit.senlla_inputs import SENLLAInputs


class SENLLAOwnerLoadTest(unittest.TestCase):
    """Concrete load composition with authored zero-listener metadata.

    These tests use actual project persistence and the owning adapters, but
    neither invoke Windows text APIs nor stand in for fresh Show/Apply/save.
    """
    def owner(self, raw=None, *, creation=None, defer_smart_observers=True):
        from test_senlla_inherited_owner import snapshot, document, english_metadata_name
        from test_senlla_control_primitives import source_strings
        from cbus_toolkit.senlla_project_bridge import SENLLAProjectBridge
        from cbus_toolkit.senlla_inherited_owner import SENLLAInheritedOwner
        from cbus_toolkit.senlla_control_primitives import PersistentControlPrimitives, NativeText
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'owned.xml'
        project = document(path)
        raw = raw or snapshot()
        # Explicit authored no-extra-listener profile, not workflow acceptance.
        bridge = SENLLAProjectBridge.from_document(project, 254, 42, storage_path=path,
            metadata_name=english_metadata_name,
            creation_dispatch=creation or (lambda request, bridge, runtime: None))
        inherited = SENLLAInheritedOwner(raw, bridge,
            defer_smart_observers=defer_smart_observers)
        owner = SENLLAOwner(raw, inherited_owner=inherited,
            control_provider=PersistentControlPrimitives(source_strings(), text=NativeText()))
        return owner, bridge, raw

    def test_same_objects_complete_raw_load_and_refuse_uncomposed_controls(self):
        owner, bridge, raw = self.owner()
        engine = owner.runtime
        retained = (engine.unit, engine.unit_manager, engine.primary_application,
                    *engine.blocks, *engine.keys, *owner.late.live_banks.banks)
        self.assertEqual(engine.scenes, ())
        self.assertIs(owner.load(), owner)
        self.assertEqual(owner.phase, 'fresh_identification')
        self.assertEqual(engine.unit.depth, 0)
        self.assertTrue(all(a is b for a, b in zip(retained, (
            engine.unit, engine.unit_manager, engine.primary_application,
            *engine.blocks, *engine.keys, *owner.late.live_banks.banks))))
        self.assertEqual(len(engine.scenes), 8)
        self.assertEqual(engine.control_app_group._value.identity, (202, 0))
        self.assertIsNone(owner.late.attribute('KeyDisableGroup')._value)
        self.assertEqual(owner.late.attribute('JoinApplication')._value.identity, 203)
        self.assertEqual(owner.late.attribute('JoinGroup')._value.identity, (203, 0))
        self.assertEqual(owner.late.attribute('LightLevelTargetLux')._value, 45)
        self.assertEqual(owner.journal.read('LightLevelMarginGroup'), [255])
        self.assertEqual(raw.expected['LightLevelMarginGroup'], (0,))
        self.assertEqual([x['phase'] for x in owner.events], [
            'prekey_handoff', 'core_neo_load', 'core_neo_keys_changed',
            'neopro_load', 'st7_load', 'surface_load', 'fresh_identification'])
        with self.assertRaises(OwnerPhaseRequired):
            owner.initialize()
        with self.assertRaises(SensorError):
            owner.parameters()
        self.assertFalse(owner.snapshot()['complete_toolkit_save'])
        self.assertFalse(owner.failed)

    def test_causal_scene_and_invoke_levels_are_actual_backend_records(self):
        from test_senlla_inherited_owner import snapshot
        owner, bridge, raw = self.owner(snapshot(
            ControlAppGroupAddress=[7], SceneTable=[9, 44] + [255] * 78,
            SceneTablePointer=[162] + [255] * 7,
            SceneKeySelector=[1] + [0] * 7, JPCommand=[14] + [0] * 7,
            SRCommand=[3] + [0] * 7, LPCommand=[1] + [0] * 7, LRCommand=[7] + [0] * 7))
        owner.load()
        engine = owner.runtime
        self.assertIs(engine.scenes[0].commands.items[0].group._value, engine.groups[(56, 9)])
        self.assertEqual(engine.scenes[0].commands.items[0].level._value, 44)
        self.assertEqual(engine.keys[0]._scene_trigger._value.identity, (202, 7, 23))
        self.assertEqual(engine.keys[0]._scene_rate._value, 3)
        created = [(event['kind'], event.get('application'), event.get('group'), event['address'])
                   for event in bridge.events if event['operation'] == 'backend_metadata_created']
        self.assertIn(('group', 56, None, 9), created)
        self.assertIn(('level', 202, 7, 23), created)
        self.assertEqual(bridge.level_value(engine, engine.levels[(202,7,23)]), 23)
        self.assertEqual(raw.expected['SceneTable'][:2], (9, 44))

    def test_current_metadata_callback_grows_cache_and_changes_later_allocation(self):
        from test_senlla_inherited_owner import snapshot
        holder = {}
        def creation(request, bridge, runtime):
            if request.kind == 'application' and request.address == 56 and request.stage == 'before_backend_creation':
                journal = holder['owner'].journal
                journal.capture('LightLevel', [11,22,33,44,55,66,77,88,99,110,121], source='authored.metadata.observer')
                journal.capture('LightIndex', [3], source='authored.metadata.observer')
                journal.capture('BlockAllocation', [1] + [0] * 7, source='authored.metadata.observer')
        owner, _, raw = self.owner(snapshot(), creation=creation)
        holder['owner'] = owner
        owner.load()
        self.assertEqual(owner.prekey.loaded_light_count, 11)
        self.assertEqual([block.light_level._value for block in owner.runtime.blocks],
                         [44,55,66,77,88,99,110,121])
        self.assertEqual(owner.runtime.keys[0].refs, [0])
        self.assertEqual(raw.expected['BlockAllocation'], (0,) * 8)
        self.assertEqual(len(raw.expected['LightLevel']), 10)

    def test_original_power_groups_precede_surface_margin_cache_mutation(self):
        from test_senlla_inherited_owner import snapshot
        owner, _, _ = self.owner(snapshot(LightLevelTargetGroup=[7], LightLevelMarginGroup=[9],
            PECTargetLux=[40], PECMarginLux=[8], LightLevelMarginGroupLevelStore=[0],
            PowerUpMarginGroupLevel=[29], PowerUpTargetGroupLevel=[17]))
        owner.load()
        late = owner.late
        self.assertEqual(late.attribute('PowerUpMarginGroupState')._value, 0)
        self.assertEqual(late.attribute('PowerUpMarginGroupPresetLevel')._value, 29)
        self.assertEqual(late.attribute('LightLevelMarginGroup')._value.identity, (56,255))
        self.assertEqual(late.attribute('LightLevelTargetLux')._value, 45)
        self.assertEqual(late.attribute('LightLevelMarginPerc')._value, 20)
        self.assertEqual(owner.journal.read('LightLevelMarginGroup'), [255])

    def test_missing_real_metadata_owner_fails_at_causal_getter(self):
        from test_senlla_inherited_owner import snapshot, document, english_metadata_name
        from test_senlla_control_primitives import source_strings
        from cbus_toolkit.senlla_project_bridge import SENLLAProjectBridge, MetadataOwnerRequired
        from cbus_toolkit.senlla_inherited_owner import SENLLAInheritedOwner
        from cbus_toolkit.senlla_control_primitives import PersistentControlPrimitives, NativeText
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'owned.xml'
        bridge = SENLLAProjectBridge.from_document(document(path),254,42,storage_path=path,
            metadata_name=english_metadata_name)
        raw = snapshot()
        owner = SENLLAOwner(raw, inherited_owner=SENLLAInheritedOwner(
            raw, bridge, defer_smart_observers=True),
            control_provider=PersistentControlPrimitives(source_strings(),text=NativeText()))
        # Source finally executes the actual partial Unit refresh as well;
        # its nil-primary failure may replace the first metadata refusal.
        with self.assertRaises(SensorError):
            owner.load()
        self.assertTrue(owner.failed)
        with self.assertRaises(SensorError):
            owner.load()


class SENLLAParameterJournalTest(unittest.TestCase):
    def snapshot(self):
        spec = fixture()
        return SENLLAInputs(spec).snapshot(current(), identity=('SENLLA','2.4.00','5754PE'))

    def test_native_capture_order_preserves_earlier_values_during_later_callbacks(self):
        journal = SENLLAParameterJournal(self.snapshot())
        groups = [7] + [255]*7
        stores = [90] + [0]*7
        journal.capture('GroupAddress', groups, source='CoreKey.SetBlockValues')
        journal.capture('LightLevelStore1', stores, source='CoreKey.SetBlockValues')
        groups[0], stores[0] = 9, 255
        # A later key getter/control callback can inspect the actual earlier
        # PP captures, before Surface's later native bank overlay runs.
        self.assertEqual(journal.read('GroupAddress'), [7]+[255]*7)
        self.assertEqual(journal.read('LightLevelStore1'), [90]+[0]*7)
        journal.capture('JPCommand', [14]+[0]*7, source='CoreNeo.SetKeyValues')
        journal.capture('LightLevelStore1', stores, source='Surface.BeforeSave')
        self.assertEqual([x.name for x in journal.captures()],
                         ['GroupAddress','LightLevelStore1','JPCommand','LightLevelStore1'])
        self.assertEqual(journal.read('LightLevelStore1'), [255]+[0]*7)
        self.assertEqual(journal.read('GroupAddress'), [7]+[255]*7)

    def test_growth_and_raw_protected_rows_are_explicit(self):
        raw = self.snapshot()
        journal = SENLLAParameterJournal(raw)
        journal.capture('LightLevel', [255]*263, source='CoreKey.SetBlockValues')
        self.assertEqual(len(journal.read('LightLevel')), 263)
        self.assertEqual(journal.read('PatchEnable'), list(raw.expected['PatchEnable']))
        # Internal PP assignment precedes the programming filter. A cached
        # protected value may differ without changing the physical baseline.
        journal.capture('LearnMode', [1], source='Learn.BeforeSave.Setter')
        journal.set_programmable('LearnMode', False, source='Learn.BeforeSave.Disabled')
        self.assertEqual(journal.read('LearnMode'), [1])
        self.assertEqual(journal.as_dict()['physical_baseline']['LearnMode'],
                         list(raw.expected['LearnMode']))
        with self.assertRaisesRegex(SensorError, 'all native programmable'):
            journal.programming_values()
        with self.assertRaises(SensorError):
            journal.capture('LightLevel', [255]*264, source='invalid')
        with self.assertRaises(SensorError):
            journal.capture('PECMarginLux', [256], source='invalid')

    def test_programming_filter_omits_internal_protected_value_at_send_position(self):
        journal = SENLLAParameterJournal(self.snapshot())
        journal.capture('LearnMode', [1], source='Learn.BeforeSave.Setter')
        # This isolated journal test supplies every final filter. Full owner
        # acceptance must execute the actual source marker setters instead.
        for name in journal.parameters():
            journal.set_programmable(name, name == 'GroupAddress', source='test.FinalFilter')
        journal.capture('GroupAddress', [7]+[255]*7, source='CoreKey.SetBlockValues')
        self.assertEqual(journal.programming_values(), {'GroupAddress':[7]+[255]*7})
        self.assertEqual(journal.read('LearnMode'), [1])

    def test_detached_inspection_does_not_replace_native_captures(self):
        journal = SENLLAParameterJournal(self.snapshot())
        journal.capture('BlockAllocation', [1]+[0]*7, source='CoreKey.SetKeyBlocks')
        exported = journal.as_dict()
        exported['parameters']['BlockAllocation'][0] = 128
        exported['captures'][0]['value'][0] = 128
        self.assertEqual(journal.read('BlockAllocation'), [1]+[0]*7)
        self.assertEqual(journal.captures()[0].value, (1,0,0,0,0,0,0,0))

    def test_fresh_save_agent_is_distinct_from_load_cache_and_physical_rows(self):
        journal = SENLLAParameterJournal(self.snapshot())
        journal.capture('LightLevelMarginGroup',[255],source='0x1217836')
        load = journal.parameters()
        journal.begin_save_agent()
        self.assertEqual(len(journal.parameters()),86)
        self.assertEqual(journal.read('JPCommand'),[])
        self.assertEqual(journal.read('Application'),[])
        self.assertEqual(journal.read('AreaGroupAddress'),[])
        self.assertEqual(journal.read('StatusReportInterval'),[0])
        self.assertEqual(journal.read('LearnMode'),[0])
        self.assertEqual(journal.read('Project'),'')
        self.assertEqual(journal.as_dict()['load_cache'],load)
        self.assertEqual(journal.as_dict()['physical_baseline'],self.snapshot().parameters())
        self.assertFalse(journal.as_dict()['programmable']['SerialNo'])
        self.assertFalse(journal.as_dict()['programmable']['CUSTYPE'])
        with self.assertRaisesRegex(SensorError,'no attribute'):
            journal.capture('CUSTYPE',[0]*8,source='test.fabricated')
        with self.assertRaisesRegex(SensorError,'actual agent attribute'):
            journal.set_programmable('CUSTYPE',True,source='test.fabricated')
        with self.assertRaisesRegex(SensorError,'once'):
            journal.begin_save_agent()

    def test_fresh_command_append_and_index_writes_retain_each_native_position(self):
        journal = SENLLAParameterJournal(self.snapshot())
        journal.begin_save_agent()
        for key in range(8):
            journal.capture_index('SceneKeySelector',key,int(key==0),source='CoreNeo.Selector')
            journal.capture_index('IndicatorBlockAssignment',key,7-key,source='CoreNeo.Indicator')
            journal.append('JPCommand',key+1,source='CoreNeo.AttribAppend')
        self.assertEqual(journal.read('JPCommand'),[1,2,3,4,5,6,7,8])
        self.assertEqual(journal.read('SceneKeySelector'),[1,0,0,0,0,0,0,0])
        self.assertEqual(journal.read('IndicatorBlockAssignment'),[7,6,5,4,3,2,1,0])
        self.assertEqual(journal.captures()[2].value,(1,))
        self.assertEqual(journal.captures()[5].value,(1,2))
        with self.assertRaisesRegex(SensorError,'unsigned width'):
            journal.append('JPCommand',9,source='invalid.ninth')

    def test_fresh_cache_requires_edited_preparation_and_refuses_retained_agent_mode(self):
        journal = SENLLAParameterJournal(self.snapshot())
        with self.assertRaisesRegex(SensorError,'synchronous default'):
            journal.begin_save_agent(mode='live_agent')
        journal.begin_save_agent()
        for name in journal.parameters():
            # An isolated send-filter test, not ordinary-save acceptance.
            journal.set_programmable(name,name=='JPCommand',source='test.actual_marker')
        for value in range(8):
            journal.append('JPCommand',value,source='CoreNeo.AttribAppend')
        with self.assertRaisesRegex(SensorError,'edited-state'):
            journal.programming_values()
        journal.prepare_save_agent()
        self.assertEqual(journal.programming_values(),{'JPCommand':list(range(8))})
        self.assertEqual(journal.physical_parameters()['SerialNo'],
                         self.snapshot().parameters()['SerialNo'])
        detached = journal.as_dict()
        detached['load_cache']['JPCommand'][0] = 15
        self.assertEqual(journal.as_dict()['load_cache']['JPCommand'],
                         self.snapshot().parameters()['JPCommand'])


if __name__ == '__main__':
    unittest.main()
