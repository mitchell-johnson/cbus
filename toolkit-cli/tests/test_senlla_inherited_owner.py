"""Authored live inherited Unit cases; no vendor runtime acceptance."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from cbus_toolkit.project import ProjectDocument
from cbus_toolkit.senlla_inherited_owner import (
    SENLLAInheritedOwner, UnitEnumAttribute, UnitStringAttribute)
from cbus_toolkit.senlla_inputs import SCHEMA, SENLLAInputSnapshot
from cbus_toolkit.senlla_lifecycle import AttributeManager, FlashObject
from cbus_toolkit.senlla_project_bridge import SENLLAProjectBridge
from cbus_toolkit.sensors import SensorError


def snapshot(**changes):
    values = {name: 'INPUT' if row[0] == 'sixbit' else [0] * row[2]
              for name, row in SCHEMA.items()}
    values.update(Application=[56, 57], AreaGroupAddress=[255],
                  GroupAddress=[255] * 8, PatchEnable=[157, 64],
                  SceneTable=[255] * 80, Project='raw', UnitName='sensor')
    values.update(changes)
    return SENLLAInputSnapshot(('SENLLA', '2.4.00', '5754PE'), values)


def document(path):
    project = ProjectDocument.new('SITE')
    project.add('network', '/', address=254, name='Local')
    project.add('unit', '/network/254', address=42, name='Motion', fields={
        'UnitType': 'SENLLA', 'FirmwareVersion': '2.4.00', 'CatalogNumber': '5754PE'})
    project.save(path)
    return project


def english_metadata_name(kind, application, address, source, runtime):
    """Authored CURRENT English descriptor context, not a vendor dataset."""
    if kind == 'application':
        return {56: 'Lighting', 95: 'DALI', 202: 'Trigger Control',
                203: 'Enable Control', 255: '<Unused>'}.get(address, str(address))
    if kind == 'group':
        if address == 255:
            return '<Unused>'
        prefix = {202: 'Trigger Group', 203: 'Enable Network Variable'}.get(application, 'Group')
        return prefix + ' ' + str(address)
    return 'Action Selector ' + str(address)


class SENLLAInheritedOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'owned.xml'
        self.project = document(self.path)

    def owner(self, raw=None, *, parameter_read=None, **providers):
        providers.setdefault('creation_dispatch', lambda request, bridge, runtime: None)
        providers.setdefault('metadata_name', english_metadata_name)
        bridge = SENLLAProjectBridge.from_document(self.project, 254, 42,
                                                   storage_path=self.path, **providers)
        return SENLLAInheritedOwner(raw or snapshot(), bridge, parameter_read=parameter_read)

    def test_live_attributes_are_created_on_same_unit_before_pp_load(self):
        owner = self.owner()
        runtime = owner.runtime
        for attr in owner.attributes.values():
            self.assertIs(attr.manager, runtime.unit_manager)
        self.assertIs(owner.attributes['StatusReportInterval'], owner.prekey.status_report_interval)
        self.assertEqual(owner.attributes['Project']._value, '')
        self.assertFalse(owner.attributes['LearnedFlagCopy']._value)
        self.assertIsNone(runtime.primary_application._value)
        self.assertEqual(owner.tag_name._value, 'Motion')

    def test_later_phase_registers_actual_same_manager_attribute_without_setter(self):
        owner = self.owner()
        from cbus_toolkit.senlla_lifecycle import IntegerAttribute
        attr = IntegerAttribute(owner.runtime.unit_manager, 45, name='unit.late.target')
        self.assertIs(owner.register_unit_attribute('LateTarget', attr), attr)
        self.assertIs(owner.unit_attribute('LateTarget'), attr)
        self.assertEqual((owner.runtime.unit.depth, attr.depth), (0, 0))
        with self.assertRaises(SensorError):
            owner.register_unit_attribute('LateTarget', attr)
        with self.assertRaisesRegex(SensorError, 'SAME'):
            owner.register_unit_attribute('Other', IntegerAttribute(None, 1))
        with self.assertRaisesRegex(SensorError, 'source-registered'):
            owner.unit_attribute('Missing')

    def test_source_prefix_reads_metadata_and_core_scalars_at_actual_positions(self):
        owner = self.owner(snapshot(DebounceTime=[63], LongPressTime=[22],
                                    EEPROMLevelStore=[1], RampRate=[254, 255], IRBank=[2],
                                    LearnMode=[1], LearnAnyApp=[1], LearnedFlag=[1],
                                    EEPROMCheckSumActive=[255], StatusReportInterval=[2]))
        runtime = owner.prekey.load_to_key_blocks()
        self.assertIs(runtime, owner.runtime)
        self.assertEqual(runtime.unit.depth, 1)
        values = owner.snapshot_state()['current_attributes']
        self.assertEqual((values['Project'], values['CBusUnitName']), ('RAW', 'sensor'))
        self.assertEqual([values[name] for name in ('DebounceTime', 'LongPressTime',
                         'RampRate1', 'RampRate2', 'InfraredBank')], [63, 22, 15, 1, 3])
        self.assertTrue(values['EEPROMLevelStore'])
        self.assertEqual([values[name] for name in ('LearnMode', 'LearnAnyApplication',
                         'LearnedFlag', 'LearnedFlagCopy', 'InfraredClipsal', 'InfraredNEC')],
                         [False] * 6)
        self.assertEqual(values['InfraredBankP'], 0)
        self.assertNotIn('EEPROMCheckSumActive', owner.attributes)
        self.assertEqual(owner.non_sent_parameters()['EEPROMCheckSumActive'], [255])
        setters = [event for event in runtime.events
                   if event.get('operation') == 'inherited_unit_setter']
        self.assertEqual([row['field'] for row in setters], ['Project', 'CBusUnitName',
                         'DebounceTime', 'LongPressTime', 'EEPROMLevelStore',
                         'RampRate1', 'RampRate2', 'InfraredBank'])

    def test_late_ir_and_global_are_separate_then_capture_current_attributes(self):
        owner = self.owner(snapshot(IRBank=[2], DisableIR=[0], DisableIRNEC=[1],
                                    StatusReportInterval=[1], UnitAddress=[9]))
        owner.prekey.load_to_key_blocks()
        with self.assertRaisesRegex(SensorError, 'late NeoPro'):
            owner.scalar_parameters()
        owner.load_neopro_infrared()
        self.assertEqual(owner.scalar_parameters()['StatusReportInterval'], [1])
        owner.initialize_global()
        owner.attributes['DebounceTime'].set(17)
        owner.attributes['CBusUnitName'].set('edited')
        parameters = owner.scalar_parameters()
        self.assertEqual({name: parameters[name] for name in ('Project', 'UnitName',
                         'UnitAddress', 'DebounceTime', 'IRBank', 'DisableIR', 'DisableIRNEC',
                         'StatusReportInterval')}, {'Project': 'SITE', 'UnitName': 'EDITED',
                         'UnitAddress': [42], 'DebounceTime': [17], 'IRBank': [2],
                         'DisableIR': [0], 'DisableIRNEC': [1], 'StatusReportInterval': [3]})
        with self.assertRaisesRegex(SensorError, 'replayed'):
            owner.load_neopro_infrared()
        self.assertEqual(owner.snapshot.expected['UnitAddress'], (9,))

    def test_every_core_ir_ordinal_and_ramp_normalization(self):
        for raw, expected in enumerate((1, 2, 3, 0)):
            with self.subTest(ir=raw):
                owner = self.owner(snapshot(IRBank=[raw]))
                owner.prekey.load_to_key_blocks()
                self.assertEqual(owner.attributes['InfraredBank']._value, expected)
        for raw, expected in ((0, 0), (1, 1), (15, 15), (16, 15), (254, 15), (255, 1)):
            with self.subTest(ramp=raw):
                owner = self.owner(snapshot(RampRate=[raw, raw]))
                owner.prekey.load_to_key_blocks()
                self.assertEqual([owner.attributes[name]._value for name in
                                  ('RampRate1', 'RampRate2')], [expected, expected])

    def test_current_getters_follow_creation_and_prior_scalar_callbacks(self):
        bound = snapshot(RampRate=[2, 3], IRBank=[1])
        current = bound.parameters()
        reads = []
        def read(name, source, runtime):
            reads.append((name, source, runtime.unit.depth))
            return current[name]
        def creation(request, bridge, runtime):
            current['Project'] = 'created'
        owner = self.owner(bound, parameter_read=read, creation_dispatch=creation)
        owner.attributes['Project'].publisher.subscribe(
            lambda _: current.__setitem__('UnitName', 'callback'))
        owner.attributes['DebounceTime'].publisher.subscribe(
            lambda _: current.__setitem__('LongPressTime', [17]))
        current['DebounceTime'] = [7]
        owner.attributes['RampRate1'].publisher.subscribe(
            lambda _: current.__setitem__('RampRate', [9, 255]))
        owner.prekey.load_to_key_blocks()
        self.assertEqual(owner.attributes['Project']._value, 'CREATED')
        self.assertEqual(owner.attributes['CBusUnitName']._value, 'callback')
        self.assertEqual(owner.attributes['LongPressTime']._value, 17)
        self.assertEqual((owner.attributes['RampRate1']._value,
                          owner.attributes['RampRate2']._value), (2, 1))
        self.assertEqual([(name, source) for name, source, _ in reads], [
            ('Project', '0xcbe700'), ('UnitName', '0xcbe72e'),
            ('DebounceTime', '0xcc862a'), ('LongPressTime', '0xcc8666'),
            ('EEPROMLevelStore', '0xcc7a0a'), ('RampRate', '0xcc86a6'),
            ('RampRate', '0xcc86e7'), ('IRBank', '0xcc80a8')])
        self.assertEqual(owner.snapshot.expected['RampRate'], (2, 3))
        self.assertEqual(owner.snapshot.expected['UnitName'], 'sensor')

    def test_late_ir_reads_current_agent_after_each_earlier_setter(self):
        bound = snapshot(IRBank=[1])
        current = bound.parameters()
        owner = self.owner(bound, parameter_read=lambda name, source, runtime: current[name])
        owner.prekey.load_to_key_blocks()
        current['IRBank'] = [2]
        current['DisableIRNEC'] = [1]
        owner.attributes['InfraredBankP'].publisher.subscribe(
            lambda _: current.__setitem__('DisableIR', [1]))
        owner.load_neopro_infrared()
        self.assertEqual([owner.attributes[name]._value for name in
                          ('InfraredBankP', 'InfraredClipsal', 'InfraredNEC')],
                         [2, False, False])
        reads = [(event['field'], event['source']) for event in owner.runtime.events
                 if event['operation'] == 'inherited_parameter_read']
        self.assertEqual(reads[-3:], [('IRBank', '0xced1a0'),
                                     ('DisableIR', '0xced1c8'), ('DisableIRNEC', '0xced1f8')])

    def test_current_reader_refuses_invalid_bound_field_and_detaches_array(self):
        owner = self.owner(parameter_read=lambda name, source, runtime: [True]
                           if name == 'DebounceTime' else snapshot().expected[name])
        with self.assertRaisesRegex(SensorError, 'exact unsigned integers'):
            owner.prekey.load_to_key_blocks()
        self.assertTrue(owner.runtime.failed)
        values = [2, 3]
        owner = self.owner(parameter_read=lambda name, source, runtime: values)
        loaded = owner._read('RampRate', '0xcc86a6')
        values[0] = 255
        self.assertEqual(loaded, (2, 3))
        with self.assertRaisesRegex(SensorError, 'callable'):
            self.owner(parameter_read=False)

    def test_tag_name_notifications_require_owner_and_see_manager_depth(self):
        observed = []
        owner = self.owner(tag_name_dispatch=lambda owner, bridge: observed.append(
            (owner.tag_name._value, owner.runtime.unit.depth, owner.tag_name.manager.depth)))
        owner.tag_name.set('Changed')
        self.assertEqual(observed, [('Changed', 1, 1)])
        self.assertEqual(owner.runtime.unit.depth, 0)
        # TagName is not the loaded CBusUnitName and does not implicitly DBSET.
        self.assertEqual(owner.bridge.unit_record()['TagName'], 'Motion')
        other = self.owner()
        with self.assertRaisesRegex(SensorError, 'notification/timer owner'):
            other.tag_name.set('Needs owner')
        self.assertEqual(other.runtime.unit.depth, 1)  # actual dedicated throw prevents manager End

    def test_same_unit_and_block_objects_continue_to_corekey_end(self):
        owner = self.owner(snapshot(BlockAllocation=[5, 0, 0, 0, 0, 0, 0, 0]))
        runtime = owner.runtime
        before = (runtime.unit, runtime.unit_manager, *runtime.blocks, *runtime.keys,
                  *owner.attributes.values())
        owner.prekey.load_to_key_blocks()
        runtime.load_allocations(owner.snapshot.expected['BlockAllocation'])
        runtime.finish_corekey_application_refresh()
        self.assertEqual(runtime.keys[0].refs, [0, 2])
        self.assertEqual(runtime.unit.depth, 0)
        after = (runtime.unit, runtime.unit_manager, *runtime.blocks, *runtime.keys,
                 *owner.attributes.values())
        self.assertTrue(all(a is b for a, b in zip(before, after)))

    def test_state_and_parameter_receipts_are_detached(self):
        owner = self.owner()
        owner.prekey.load_to_key_blocks()
        owner.load_neopro_infrared()
        state = owner.snapshot_state()
        state['current_attributes']['Project'] = 'BAD'
        preserved = owner.non_sent_parameters()
        preserved['PatchEnable'][0] = 0
        current = owner.scalar_parameters()
        current['IRBank'][0] = 3
        self.assertEqual(owner.attributes['Project']._value, 'RAW')
        self.assertEqual(owner.snapshot.expected['PatchEnable'], (157, 64))
        self.assertEqual(owner.scalar_parameters()['IRBank'], [0])

    def test_safe_source_receipt_binds_specific_early_and_late_authority(self):
        fixture = json.loads((Path(__file__).resolve().parents[1] / 'research' / 'fixtures' /
                              'senlla-inherited-owner-source.json').read_text())
        self.assertEqual(fixture['method_count'], len(fixture['methods']))
        self.assertEqual(fixture['method_count'], 194)
        rules = fixture['source_rules']
        self.assertEqual(rules['early_core_ir_raw_0_1_2_3_to_ordinal'], [1, 2, 3, 0])
        self.assertFalse(rules['learn_properties']['enabled'])
        self.assertEqual(rules['indicator_brightness_properties']['target'], '0xcfb620')
        self.assertFalse(fixture['original_instructions_executed'])
        self.assertFalse(fixture['vendor_specifications_included'])


class NativeUnitAttributeTests(unittest.TestCase):
    def manager(self):
        unit = FlashObject('unit')
        return unit, AttributeManager(unit)

    def test_string_before_change_mutates_candidate_and_acceptance_before_begin(self):
        unit, manager = self.manager()
        observed = []
        def before(attr, decision):
            observed.append((unit.depth, manager.depth, decision.previous, decision.proposed))
            decision.proposed = 'native'
            decision.changed = True
        attr = UnitStringAttribute(manager, 'same', maximum=8, before_change=before,
                                   after_change=lambda _: observed.append((unit.depth, manager.depth)))
        attr.set('same')
        self.assertEqual(attr._value, 'native')
        self.assertEqual(observed, [(0, 0, 'same', 'same'), (1, 1)])
        self.assertEqual(unit.depth, 0)

    def test_string_decline_and_utf16_maximum_raise_before_update(self):
        unit, manager = self.manager()
        attr = UnitStringAttribute(manager, 'old', maximum=3,
                                   before_change=lambda _, decision: setattr(decision, 'changed', False))
        attr.set('too long')
        self.assertEqual(attr._value, 'old')
        attr.before_change = None
        attr.set('😀a')
        with self.assertRaisesRegex(SensorError, 'UTF-16'):
            attr.set('😀aa')
        self.assertEqual(attr._value, '😀a')
        self.assertEqual((unit.depth, manager.depth, attr.depth), (0, 0, 0))

    def test_utf16_equal_astral_and_surrogate_strings_do_not_publish(self):
        unit, manager = self.manager()
        before = []
        publications = []
        original = '\U0001f601'
        equivalent = '\ud83d\ude01'
        self.assertNotEqual(original, equivalent)
        attr = UnitStringAttribute(manager, original, maximum=2,
            before_change=lambda _, decision: before.append((decision.changed,
                decision.previous, decision.proposed, unit.depth, manager.depth)),
            after_change=lambda _: publications.append('dedicated'))
        attr.publisher.subscribe(lambda _: publications.append('attribute'))
        unit.publisher.subscribe(lambda _: publications.append('unit'))
        attr.set(equivalent)
        self.assertEqual(before, [(False,original,equivalent,0,0)])
        self.assertEqual(publications, [])
        self.assertEqual(attr._value, original)
        self.assertEqual((attr.depth, manager.depth, unit.depth), (0,0,0))

    def test_enum_bounds_equal_noop_getter_rearms_and_callback_finally(self):
        unit, manager = self.manager()
        calls = []
        attr = UnitEnumAttribute(manager, maximum=3, after_change=lambda _: calls.append(unit.depth))
        attr.set(0)
        self.assertEqual(calls, [])
        attr.set(3)
        self.assertEqual(calls, [1])
        self.assertEqual(attr.value, 3)
        for value in (-1, 4, True, '1'):
            with self.subTest(value=value), self.assertRaises(SensorError):
                attr.set(value)
        def fail(_):
            raise RuntimeError('actual observer')
        attr.after_change = fail
        with self.assertRaisesRegex(RuntimeError, 'actual observer'):
            attr.set(2)
        self.assertEqual((unit.depth, manager.depth, attr.depth), (1, 1, 0))
        # Native AttributeManager.End is not a finally: dedicated throw leaves
        # manager/parent depth1. The owning engine invalidates this lifecycle.


if __name__ == '__main__':
    unittest.main()
