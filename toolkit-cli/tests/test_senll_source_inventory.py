"""Source-ordered Area/Scene getter inventory with literal byte layouts."""
import copy
from dataclasses import replace
import unittest
import xml.etree.ElementTree as ET

from cbus_toolkit.light_level_sensors import INVENTORY_LAYOUTS, LAYOUTS, LightLevelSensor
from cbus_toolkit.sensors import SensorApplyError, SensorError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from test_light_level_sensors import fixture as legacy_fixture
from test_macros import Reply, Session
from test_senll_control_history import values as legacy_values


# Independent byte-layout vectors; no private specification content is copied.
FIELDS = {'AreaGroupAddress': (67, 1), 'SceneTablePointer': (152, 8),
          'PatchEnable': (160, 2), 'SceneTable': (162, 80)}
DISABLED_PATCH = [157, 64]


def fixture():
    old = legacy_fixture()
    parameters = dict(old.parameters)
    for name, (address, count) in FIELDS.items():
        default = DISABLED_PATCH if name == 'PatchEnable' else [255] * count
        parameters[name] = ParameterSpec(name, 'int', 'synthetic-senll-inventory.xml',
            {'Name': name, 'Type': 'int', 'Address': str(address), 'ArraySize': str(count),
             'BitSize': '8', 'BitAddress': '0', 'ArraySkip': '0',
             'DefaultValue': ' '.join(map(str, default))})
    return UnitSpec(old.filename, old.metadata, old.sources, parameters)


def values(**extra):
    result = legacy_values(groups=[255] * 8, mask=0)
    result.update(AreaGroupAddress=[255], SceneTablePointer=[255] * 8,
                  PatchEnable=list(DISABLED_PATCH), SceneTable=[255] * 80)
    result.update(extra)
    return result


def table(*pairs):
    result = [255] * 80
    for offset, group, level in pairs:
        result[offset:offset + 2] = [group, level]
    return result


class SENLLSourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.sensor = LightLevelSensor(self.spec)

    def plan(self, current=None, *controls, **options):
        return self.sensor.plan(values() if current is None else current,
                                on_off_controls=list(controls) or None, **options)

    def final(self, plan, field):
        return list(plan.changes.get(field, plan.expected[field]))

    def session(self, current=None):
        session = Session(self.spec)
        session.unit_type, session.firmware, session.catalog_number = 'SENLL', '2.3.00', '5031PE'
        session.current.update({name: ' '.join(map(str, value)) for name, value in (current or values()).items()})
        return session

    def test_absent_inventory_keeps_both_historical_profiles(self):
        old = legacy_values()
        sensor = LightLevelSensor(legacy_fixture())
        flat = sensor.plan(old)
        self.assertEqual(set(flat.expected), set(LAYOUTS))
        self.assertIsNone(flat.control_history)
        explicit = sensor.plan(old, on_off_controls=[{'application': 'primary'}])
        self.assertEqual(explicit.control_history['metadata_profile'], 'raw_blocks_and_selected_hidden_getters')
        self.assertEqual(explicit.control_history['unmodelled_group_inventories'],
                         ['AreaGroupAddress', 'SceneTable/SceneTablePointer'])
        self.assertNotIn('source_inventory', explicit.control_history)
        self.assertEqual(self.final(explicit, 'GroupAddress')[2], 255)

    def test_complete_snapshot_binds_all47_bytes_and_preserves_noncanonical_inventory(self):
        current = values(AreaGroupAddress=[20], SceneTablePointer=[0, 2, 1, 255, 9, 3, 80, 160],
                         SceneTable=table((0, 21, 70), (78, 22, 11)))
        before = copy.deepcopy(current)
        plan = self.plan(current, {'group': 21})
        self.assertEqual(len(plan.expected), 47)
        self.assertEqual(set(plan.expected), set(LAYOUTS) | set(FIELDS))
        for name in FIELDS:
            self.assertEqual(plan.expected[name], tuple(current[name]))
            self.assertNotIn(name, plan.changes)
        self.assertEqual(current, before)
        journal = plan.control_history
        self.assertEqual(journal['metadata_profile'], 'complete_area_scene_and_hidden_getters')
        self.assertEqual(journal['unmodelled_group_inventories'], [])
        self.assertEqual(journal['source_inventory']['fields'], {name: current[name] for name in FIELDS})
        self.assertTrue(journal['source_inventory']['scene_groups_after_block_refresh']['pointer_and_padding_bytes_preserved'])

    def test_any_partial_inventory_refuses_before_a_history(self):
        for field in FIELDS:
            for keep_only in (True, False):
                with self.subTest(field=field, keep_only=keep_only):
                    current = values()
                    for other in FIELDS:
                        if (other != field) == keep_only:
                            current.pop(other)
                    with self.assertRaisesRegex(SensorError, 'together'):
                        self.plan(current, {'application': 'primary'})
                    with self.assertRaisesRegex(SensorError, 'together'):
                        self.sensor.snapshot(current)

    def test_inventory_values_require_complete8bit_integer_arrays(self):
        for field, (_address, count) in FIELDS.items():
            for bad in ([], [0] * (count + 1), [256] * count, [-1] * count,
                        [True] * count, [1.0] * count, ['not-a-byte'] * count):
                with self.subTest(field=field, bad=bad[:2]):
                    current = values(**{field: bad})
                    with self.assertRaisesRegex(SensorError, 'Invalid current'):
                        self.sensor.snapshot(current)
        current = values()
        current.update({name: ' '.join(hex(value) for value in current[name]) for name in FIELDS})
        result = self.sensor.snapshot(current)
        self.assertEqual(result['PatchEnable'], (157, 64))
        self.assertEqual(result['SceneTable'], (255,) * 80)

    def test_inventory_layouts_are_optional_but_every_present_layout_is_exact(self):
        self.assertEqual(dict(INVENTORY_LAYOUTS), {name: (address, count, 8, 0, 0)
                                                  for name, (address, count) in FIELDS.items()})
        for field in FIELDS:
            for attribute, replacement in (('Address', '1'), ('ArraySize', '3'), ('BitSize', '7'),
                                           ('BitAddress', '1'), ('ArraySkip', '1'), ('Type', 'bit')):
                with self.subTest(field=field, attribute=attribute):
                    spec = fixture()
                    original = spec.get(field)
                    edited = {**original.fields, attribute: replacement}
                    spec.parameters[field] = ParameterSpec(field, edited['Type'], original.source, edited)
                    sensor = LightLevelSensor(spec)
                    with self.assertRaisesRegex(SensorError, 'Unsupported.*layout'):
                        sensor.snapshot(values())

    def test_area_getter_can_establish_missing_primary_during_earlier_load(self):
        current = values(Application=[56, 255], GroupAddress=[255, 255, 20, 255, 255, 255, 255, 255],
                         SecondApplicationBlocks=[4], AreaGroupAddress=[20])
        plan = self.plan(current, {'application': 'primary'})
        self.assertEqual(self.final(plan, 'GroupAddress')[2], 20)
        self.assertEqual(self.final(plan, 'SecondApplicationBlocks'), [0])
        history = plan.control_history
        self.assertEqual(history['source_inventory']['area_group_before_block_refresh'], [56, 20])
        self.assertLess(history['phase_order'].index('area_group_load'),
                        history['phase_order'].index('secondary_application_refresh'))
        self.assertEqual(history['load'][0]['hidden_group_callbacks'], [])
        self.assertFalse(history['controls'][0]['secondary_changed'])

    def test_scene_getters_remain_unavailable_to_earlier_missing_app2_load(self):
        current = values(Application=[56, 255], GroupAddress=[255, 255, 20, 255, 255, 255, 255, 255],
                         SecondApplicationBlocks=[4], SceneTable=table((0, 20, 70)))
        with self.assertRaisesRegex(SensorError, 'creation/decline'):
            self.plan(current, {'application': 'primary'})
        current['AreaGroupAddress'] = [20]
        plan = self.plan(current, {'application': 'primary'})
        self.assertEqual(self.final(plan, 'GroupAddress')[2], 20)

    def test_scene_walk_reads_every_even_offset_ignores_unused_and_preserves_duplicates(self):
        current = values(SceneTable=table((0, 21, 70), (2, 255, 20), (38, 21, 71), (78, 22, 11)),
                         SceneTablePointer=[0, 255, 0, 255, 0, 255, 0, 255])
        plan = self.plan(current, {'group': 21}, {'group': 22})
        history = plan.control_history
        scene = history['source_inventory']['scene_groups_after_block_refresh']
        self.assertEqual(scene['scanned_even_offsets'], list(range(0, 80, 2)))
        self.assertEqual(scene['groups'], [{'offset': 0, 'group': [56, 21]},
                                         {'offset': 38, 'group': [56, 21]},
                                         {'offset': 78, 'group': [56, 22]}])
        self.assertEqual(self.final(plan, 'GroupAddress')[2], 22)
        self.assertEqual(plan.control_history['controls'][0]['hidden_group_callbacks'], [])
        self.assertLess(history['phase_order'].index('secondary_application_refresh'),
                        history['phase_order'].index('scene_group_load'))
        self.assertLess(history['phase_order'].index('scene_group_load'),
                        history['phase_order'].index('hidden_group_load'))

    def test_first_unused_scene_group_suppresses_the_whole_walk(self):
        current = values(SceneTable=table((2, 21, 70), (78, 22, 11)))
        plan = self.plan(current, {'application': 'primary'})
        scene = plan.control_history['source_inventory']['scene_groups_after_block_refresh']
        self.assertTrue(scene['first_group_suppresses_getters'])
        self.assertEqual(scene['scanned_even_offsets'], [])
        self.assertEqual(scene['groups'], [])
        with self.assertRaisesRegex(SensorError, 'creation/decline'):
            self.plan(current, {'group': 21})

    def test_area_and_scene_groups_offer_authority_but_not_extra_collision_callbacks(self):
        current = values(AreaGroupAddress=[20], SceneTable=table((0, 21, 70)))
        plan = self.plan(current, {'group': 20}, {'group': 21})
        for row in plan.control_history['controls']:
            self.assertEqual(row['hidden_group_callbacks'], [])
        self.assertEqual(self.final(plan, 'GroupAddress')[2], 21)
        current['PECEnablerGroup'] = [21]
        with self.assertRaisesRegex(SensorError, 'excluded'):
            self.plan(current, {'group': 21})

    def test_enabled_scene_save_uses_exact_disabled_sentinel_and_preserves_patch(self):
        for patch in ([0, 0], [157, 65], [156, 64], [255, 255]):
            with self.subTest(patch=patch):
                current = values(PatchEnable=patch)
                self.assertEqual(self.sensor.snapshot(current)['PatchEnable'], tuple(patch))
                for plan in (self.plan(current, {'application': 'primary'}), self.plan(current)):
                    self.assertEqual(self.final(plan, 'PatchEnable'), patch)
                    self.assertNotIn('PatchEnable', plan.changes)
                    self.assertEqual(self.final(plan, 'SceneTable'), [255] * 80)
                    self.assertEqual(self.final(plan, 'SceneTablePointer'),
                                     [162, 182, 202, 222, 255, 255, 255, 255])
        self.assertEqual(self.plan().expected['PatchEnable'], (157, 64))

    def test_complete_flat_path_binds_inventory_without_changing_numeric_controls(self):
        current = values(AreaGroupAddress=[20], SceneTable=table((0, 21, 70)))
        plan = self.plan(current, on_off_group=31)
        self.assertIsNone(plan.control_history)
        self.assertEqual(len(plan.expected), 47)
        self.assertEqual(self.final(plan, 'GroupAddress')[2], 31)
        self.assertTrue(set(FIELDS).isdisjoint(plan.changes))

    def test_complete_flat_save_requires_proven_lighting_object_profile(self):
        for applications in ([48, 48], [95, 255], [95, 95]):
            with self.subTest(applications=applications):
                self.assertEqual(self.plan(values(Application=applications)).expected['Application'], tuple(applications))
        for applications in ([47, 255], [96, 255], [255, 255], [56, 202], [56, 0]):
            with self.subTest(applications=applications):
                current = values(Application=applications)
                with self.assertRaisesRegex(SensorError, 'Complete.*Lighting'):
                    self.plan(current)
                session = self.session(current)
                with self.assertRaisesRegex(SensorError, 'Complete.*Lighting'):
                    self.sensor.configure(session)
                self.assertEqual(session.calls, [])
                # The absent-inventory flat profile retains its earlier scope.
                old = {name: value for name, value in current.items() if name not in FIELDS}
                self.assertEqual(LightLevelSensor(legacy_fixture()).plan(old).expected['Application'], tuple(applications))

    def test_every_inventory_byte_is_stale_guarded_before_any_write(self):
        for field in FIELDS:
            with self.subTest(field=field):
                session = self.session()
                plan = self.plan(session.values(), {'application': 'primary'})
                changed = list(plan.expected[field])
                changed[-1] ^= 1
                session.current[field] = ' '.join(map(str, changed))
                with self.assertRaisesRegex(SensorError, 'changed since'):
                    self.sensor.apply(session, plan)
                self.assertEqual(session.calls, [])

    def test_native_schema_checks_all_inventory_layouts_before_any_write(self):
        for field in FIELDS:
            with self.subTest(field=field):
                session = self.session()
                plan = self.plan(session.values(), {'application': 'primary'})
                original_info = session.info
                def altered_info(name):
                    root = ET.fromstring(original_info(name).lines[0][4:])
                    for node in root.findall('Param'):
                        if node.findtext('Name') == field:
                            node.find('BitSize').text = '7'
                    return Reply(ET.tostring(root, encoding='unicode'))
                session.info = altered_info
                with self.assertRaisesRegex(SensorError, 'Native parameter layout mismatch'):
                    self.sensor.apply(session, plan)
                self.assertEqual(session.calls, [])

    def test_readonly_inventory_changes_are_rejected_and_apply_checks_full_readback(self):
        session = self.session()
        plan = self.plan(session.values(), {'application': 'primary'})
        for field in FIELDS:
            with self.subTest(field=field):
                corrupted = replace(plan, changes={**plan.changes, field: plan.expected[field]})
                with self.assertRaisesRegex(SensorError, 'outside|Scene save'):
                    self.sensor.apply(session, corrupted)
                self.assertEqual(session.calls, [])
        original_set = session.set
        def corrupt_readonly_after_write(name, value):
            original_set(name, value)
            session.current['SceneTablePointer'] = '0 255 255 255 255 255 255 255'
        session.set = corrupt_readonly_after_write
        with self.assertRaisesRegex(SensorApplyError, 'readback'):
            self.sensor.apply(session, plan)

    def test_enabled_scene_normalization_is_derived_at_apply_and_cannot_be_omitted_or_forged(self):
        current = values(PatchEnable=[0, 0], SceneTable=table((0, 20, 1), (2, 20, 2), (6, 30, 4)),
                         SceneTablePointer=[0, 255, 255, 255, 255, 255, 255, 255])
        for controls in (None, [{'application': 'primary'}]):
            session = self.session(current)
            plan = self.sensor.plan(session.values(), on_off_controls=controls)
            self.assertEqual(self.final(plan, 'SceneTable'), [20, 1, 30, 4] + [255] * 76)
            self.assertEqual(self.final(plan, 'SceneTablePointer'), [162, 182, 202, 222, 255, 255, 255, 255])
            for applications in ((56, 202), (255, 255)):
                with self.assertRaisesRegex(SensorError, 'Complete.*Lighting'):
                    self.sensor.apply(session, replace(plan, changes={**plan.changes, 'Application': applications}))
                self.assertEqual(session.calls, [])
            for field in ('SceneTable', 'SceneTablePointer'):
                for omitted in (True, False):
                    changes = dict(plan.changes)
                    if omitted:
                        changes.pop(field)
                    else:
                        bad = list(changes[field])
                        bad[0] ^= 1
                        changes[field] = tuple(bad)
                    with self.subTest(field=field, omitted=omitted, controls=controls):
                        with self.assertRaisesRegex(SensorError, 'source-derived'):
                            self.sensor.apply(session, replace(plan, changes=changes))
                        self.assertEqual(session.calls, [])
            result = self.sensor.apply(session, plan)
            self.assertTrue(result['verified'])
            self.assertEqual(session.current['SceneTable'], '20 1 30 4 ' + ' '.join(['255'] * 76))
            self.assertEqual(session.current['PatchEnable'], '0 0')
            self.assertEqual(session.current['AreaGroupAddress'], '255')

    def test_configure_preserves_inventory_and_serialized_receipts_are_detached(self):
        current = values(AreaGroupAddress=[20], SceneTable=table((0, 21, 70)))
        session = self.session(current)
        result = self.sensor.configure(session, on_off_controls=[{'group': 21}])
        self.assertTrue(result['verified'])
        self.assertFalse(result['saved'])
        self.assertEqual(len(result['expected']), 47)
        for field in FIELDS:
            self.assertEqual(session.current[field], ' '.join(map(str, current[field])))
        self.assertTrue(set(FIELDS).isdisjoint(name for name, _value in session.calls))
        plan = self.plan(current, {'group': 21})
        receipt = plan.as_dict()
        receipt['control_history']['source_inventory']['fields']['SceneTablePointer'][0] = 0
        self.assertEqual(plan.as_dict()['control_history']['source_inventory']['fields']['SceneTablePointer'][0], 255)


if __name__ == '__main__':
    unittest.main()
