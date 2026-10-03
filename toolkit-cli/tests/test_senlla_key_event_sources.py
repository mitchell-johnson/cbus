"""Literal source-position kernel cases; these are not full Toolkit saves."""
import unittest

from cbus_toolkit.senlla_key_events import SourceLevelRequest
from cbus_toolkit.sensors import SensorError
from test_senlla_key_events import owner


def at_scenes(*, groups=None, stores=None, masks=None):
    runtime = owner(groups=groups, store1=stores)
    runtime.load_allocations(masks or [0] * 8)
    runtime.finish_corekey_application_refresh()
    runtime.scenes_enabled.set(True)
    runtime.set_control_app_group(runtime.groups[(202, 7)])
    return runtime


def key_values(runtime, *, stages=None, selector=None):
    runtime.load_key_values(stages or [[0] * 4 for _ in range(8)],
                            selector or [0] * 8, [0] * 8)
    runtime.fresh_function_bindings()
    # Isolated class/model kernel only; native controls remain another owner.
    runtime.install_m8_hooks(control_dispatch=lambda request, engine: None)


class SENLLAKeyEventSourcesTest(unittest.TestCase):
    def test_allocation_reads_later_mask_after_actual_first_key_callback(self):
        runtime = owner()
        current = [1] + [0] * 7
        reads = []
        runtime.keys[0].primary_group.publisher.subscribe(lambda _: current.__setitem__(1, 4))
        def read(name, source, engine):
            reads.append((name, source))
            return current
        runtime.load_allocations([0] * 8, parameter_read=read)
        self.assertEqual(runtime.keys[0].refs, [0])
        self.assertEqual(runtime.keys[1].refs, [2])
        self.assertEqual(reads, [('BlockAllocation', '0xcc7784')] * 8)

    def test_pointer_serialization_reads_counts_without_resolving_command_references(self):
        runtime = at_scenes()
        runtime.add_source_group(runtime.apps[56], 7)
        runtime.load_scenes_causal([7,1]+[255]*78,
                                  [162,255,255,255,255,255,255,255], [0,0])
        command = runtime.scenes[0].commands.items[0]
        def unexpected_read():
            raise AssertionError('Pointer source does not read command Group')
        command.group.resolve_change = unexpected_read
        self.assertEqual(runtime._scene_pointers(), [162,182,202,222,255,255,255,255])
        with self.assertRaisesRegex(AssertionError,'Pointer source'):
            runtime._scene_table()

    def test_scene_cache_is_read_after_actual_clear_and_empty_skips_pointer_read(self):
        runtime = at_scenes()
        current = {'SceneTable':[7,1]+[255]*78,
                   'SceneTablePointer':[162,255,255,255,255,255,255,255]}
        # A nonempty source collection clears through the owning Unit route.
        runtime._add_scene('test.existing_actual_scene')
        runtime.unit.on_changed = lambda _: current.update(SceneTable=[255]*80)
        reads = []
        def read(name, source, engine):
            reads.append((name,source,len(engine.scene_collection.items)))
            return current[name]
        runtime.load_scenes_causal([7,1]+[255]*78, current['SceneTablePointer'], [0,0],
                                  parameter_read=read)
        self.assertEqual(reads, [('SceneTable','0xccafb1',0)])
        self.assertTrue(all(not scene.commands.items for scene in runtime.scenes))

    def test_key_cache_reads_current_selector_and_trigger_order_after_prior_callback(self):
        runtime = at_scenes()
        runtime.load_scenes_causal([255]*80,[162,255,255,255,255,255,255,255],[0,0])
        cache = {'SceneKeySelector':[1]+[0]*7,'IndicatorBlockAssignment':[0]*8,
                 'JPCommand':[14]+[0]*7,'SRCommand':[2]+[0]*7,
                 'LPCommand':[1]+[0]*7,'LRCommand':[7]+[0]*7}
        requests, reads = [], []
        def lookup(request, engine):
            requests.append(request.address)
            engine.add_source_level(engine.groups[request.group], request.address)
            if request.address == 23:
                cache['SRCommand'][0] = 3
                cache['SceneKeySelector'][1] = 1
                cache['JPCommand'][1] = 14
                cache['LRCommand'][1] = 8
        runtime.level_dispatch = lookup
        def read(name, source, engine):
            reads.append((name,source))
            return cache[name]
        runtime.load_key_values([[14,2,1,7]]+[[0]*4 for _ in range(7)],
                               [1]+[0]*7,[0]*8,parameter_read=read)
        self.assertEqual(requests,[23,8])
        self.assertEqual(runtime.keys[0]._scene_rate._value,3)
        self.assertEqual(runtime.keys[1]._scene_trigger._value.identity,(202,7,8))
        self.assertEqual(reads[:7], [('SceneKeySelector','0xcca5d1'),('JPCommand','0xcca5ee'),
            ('IndicatorBlockAssignment','0xcca679'),('LRCommand','0xcca6e0'),
            ('LPCommand','0xcca712'),('SRCommand','0xcca77d'),('SceneKeySelector','0xcca5d1')])

    def test_live_bank_dispatch_receives_each_current_nested_occupancy_event(self):
        runtime = at_scenes()
        class Dispatcher:
            def __init__(self):
                self.flags, self.publications = [], []
            def sync_graph_observation(self):
                return True
            def block_changed(self,index,engine):
                self.publications.append(index)
            def occupancy_bank_event(self,key,engine):
                self.flags.append(engine.current_occupancy_flags(key))
                if self.flags == [(False,True,False,False),(True,False,False,False)]:
                    engine._set_flag(key,3,True)
        dispatcher = Dispatcher()
        runtime.live_bank_dispatch = dispatcher
        runtime._set_flag(0,1,True)
        runtime._set_flag(0,0,True)
        self.assertEqual(dispatcher.flags,[(False,True,False,False),
            (True,False,False,False),(True,False,False,True),(True,False,False,True)])
        # The newer actual bank tracked listeners execute physical setters;
        # the kernel's older central hook is observation only.
        runtime._block_published(0)
        self.assertEqual(dispatcher.publications,[0])
        self.assertEqual(runtime.graph.occupancy[0].flags,(True,False,False,True))

    def test_actual_empty_scene_collection_and_add_before_group_getter(self):
        runtime = at_scenes()
        seen = []
        def lookup(request, current):
            self.assertEqual(request.kind, 'group')
            scene = current.scene_collection.items[-1]
            seen.append((request.address, len(current.scene_collection.items),
                         len(scene.commands.items), scene.commands.items[-1].group._value))
            current.add_source_group(current.apps[request.application], request.address)
        runtime.source_dispatch = lookup
        table = [7,1,7,2,8,3] + [255] * 74
        runtime.load_scenes_causal(table, [162,168,255,255,255,255,255,255], [0,0])
        self.assertEqual(seen, [(7,1,1,None),(8,1,2,None)])
        self.assertEqual([len(scene.commands.items) for scene in runtime.scenes], [2,0,0,0,0,0,0,0])
        self.assertEqual(runtime.scene_commands[0], ((7,1),(8,3)))
        self.assertEqual(len(runtime.scene_collection.items), 8)
        self.assertFalse(any(scene.live_groups for scene in runtime.scenes))

    def test_duplicate_lookup_uses_current_command_group_after_creation_callback(self):
        runtime = at_scenes()
        requests = []
        def lookup(request, current):
            requests.append(request.address)
            current.add_source_group(current.apps[56], request.address)
            if request.address == 8:
                current.scene_collection.items[0].commands.items[0].set_group(current.groups[(56,8)])
        runtime.source_dispatch = lookup
        runtime.load_scenes_causal([7,1,8,2,7,3]+[255]*74,
                                  [162,255,255,255,255,255,255,255], [0,0])
        self.assertEqual(requests, [7,8])
        self.assertEqual(runtime.scene_commands[0], ((8,1),(8,2),(7,3)))

    def test_control_group_membership_compares_current_object_pointer(self):
        runtime = at_scenes()
        group9 = runtime.add_source_group(runtime.apps[202], 9)
        old = runtime.levels[(202,7,165)]
        same_address_other_object = runtime.add_source_level(group9,165,value=4)
        runtime.keys[0].scene_trigger.set(old)
        runtime.set_control_app_group(group9)
        self.assertIsNone(runtime.keys[0].scene_trigger._value)
        runtime.keys[0].scene_trigger.set(same_address_other_object)
        runtime.set_control_app_group(group9)
        self.assertIs(runtime.keys[0].scene_trigger._value, same_address_other_object)
        runtime.set_control_app_group(None)
        self.assertTrue(all(key._scene_trigger._value is None for key in runtime.keys))

    def test_ascending_level_getters_use_current_control_group_and_keep_value_distinct(self):
        runtime = at_scenes()
        group9 = runtime.add_source_group(runtime.apps[202], 9)
        requests = []
        def lookup(request, current):
            self.assertIs(type(request), SourceLevelRequest)
            requests.append((request.group, request.address))
            current.add_source_level(current.groups[request.group], request.address, value=4)
            if request.address == 23:
                self.assertIsNone(current.keys[0]._scene_trigger._value)
        runtime.level_dispatch = lookup
        # Existing level165 has Value165 in the projected literal inventory;
        # an actual existing backend value can be changed independently.
        runtime.levels[(202,7,165)].level_value.set(4)
        runtime.load_scenes_causal([255]*80, [162,255,255,255,255,255,255,255], [0,0])
        runtime.keys[0]._scene_trigger.after_change = lambda attr: (
            runtime.set_control_app_group(group9) if attr._value is not None else None)
        key_values(runtime, stages=[[14,2,10,5],[14,3,1,7]]+[[0]*4 for _ in range(6)], selector=[1,1]+[0]*6)
        self.assertEqual(requests, [((202,9),23)])
        self.assertEqual(runtime.keys[1]._scene_trigger._value.identity, (202,9,23))
        self.assertEqual(runtime.level_value(runtime.levels[(202,7,165)]), 4)
        self.assertEqual(runtime.level_value(runtime.levels[(202,9,23)]), 4)

    def test_invoke_save_uses_level_address_and_captures_earlier_pp_before_nil_getter(self):
        runtime = at_scenes(groups=[7]+[255]*7, stores=[90]+[0]*7, masks=[1]+[0]*7)
        runtime.load_scenes_causal([7,1]+[255]*78, [162,255,255,255,255,255,255,255], [0,0])
        key_values(runtime, stages=[[14,2,10,5]]+[[0]*4 for _ in range(7)], selector=[1]+[0]*7)
        runtime.keys[0].scene_trigger.set(None)
        writes = []
        def lookup(request, current):
            current.add_source_level(current.groups[request.group], request.address, value=4)
            current.blocks[0].store1.set(255)
        runtime.level_dispatch = lookup
        def capture(request, current):
            writes.append(request.as_dict())
        output = runtime.parameters(parameter_dispatch=capture)
        self.assertEqual(output['LightLevelStore1'], [90]+[0]*7)
        self.assertEqual(runtime.blocks[0].store1._value,255)
        self.assertEqual(output['LPCommand'][0],15)
        self.assertEqual(output['LRCommand'][0],15)
        self.assertEqual(runtime.level_value(runtime.levels[(202,7,255)]),4)
        first_append = next(i for i,event in enumerate(writes) if event['operation']=='append')
        self.assertLess(next(i for i,event in enumerate(writes) if event['name']=='SceneTable'), first_append)
        self.assertEqual(writes[-1]['name'], 'SecondApplicationBlocks')

    def test_actual_scene_save_reads_current_commands_and_skips_disabled_cache(self):
        runtime = at_scenes(groups=[7]+[255]*7)
        group8 = runtime.add_source_group(runtime.apps[56],8)
        runtime.load_scenes_causal([7,1]+[255]*78, [162,255,255,255,255,255,255,255], [0,0])
        key_values(runtime)
        command = runtime.scenes[0].commands.items[0]
        command.set_group(group8)
        command.set_level(9)
        self.assertEqual(runtime.parameters()['SceneTable'][:4], [8,9,255,255])
        runtime.scenes_enabled.set(False)
        output = runtime.parameters()
        self.assertNotIn('SceneTable',output)
        self.assertNotIn('SceneTablePointer',output)

    def test_nil_control_group_skips_load_getter_but_refuses_native_invoke_save(self):
        runtime = at_scenes()
        runtime.set_control_app_group(None)
        runtime.load_scenes_causal([255]*80,[162,255,255,255,255,255,255,255],[0,0])
        key_values(runtime, stages=[[14,2,10,5]]+[[0]*4 for _ in range(7)], selector=[1]+[0]*7)
        self.assertIsNone(runtime.keys[0]._scene_trigger._value)
        with self.assertRaisesRegex(SensorError,'nil ControlAppGroup'):
            runtime.parameters()
        self.assertTrue(runtime.failed)


if __name__ == '__main__':
    unittest.main()
