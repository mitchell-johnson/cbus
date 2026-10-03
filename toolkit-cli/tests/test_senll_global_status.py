"""Fresh Global integer-selector writeback, with raw PP baseline preserved."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from cbus_toolkit.light_level_sensors import INVENTORY_LAYOUTS, LAYOUTS, LightLevelSensor
from cbus_toolkit.native_sensor_scenes import scene_save_parameters
from cbus_toolkit.sensors import SensorApplyError, SensorError
from test_light_level_sensors import fixture as legacy_fixture
from test_macros import Reply, Session
from test_senll_control_history import values as legacy_values
from test_senll_source_inventory import fixture as complete_fixture, table, values as complete_values


class SENLLGlobalStatusTests(unittest.TestCase):
    def profile(self, complete=False, loaded=0, **extra):
        spec = complete_fixture() if complete else legacy_fixture()
        current = complete_values() if complete else legacy_values(mask=0)
        current.update(StatusReportInterval=[loaded], **extra)
        return LightLevelSensor(spec), current

    def session(self, sensor, current):
        session = Session(sensor.spec)
        session.unit_type, session.firmware, session.catalog_number = 'SENLL', '2.3.00', '5031PE'
        session.current.update({name: ' '.join(map(str, values)) for name, values in current.items()})
        return session

    def final(self, plan, name):
        return list(plan.changes.get(name, plan.expected[name]))

    def enabled(self, loaded=0):
        return self.profile(True, loaded, PatchEnable=[0, 0], SceneTablePointer=[255] * 8,
                            SceneTable=table((0, 21, 70), (2, 21, 71)))

    def test_loaded_zero_one_two_initialize_to_three_in_both_snapshot_and_control_profiles(self):
        for complete in (False, True):
            for loaded in (0, 1, 2):
                for controls in (None, [{'application': 'primary'}]):
                    with self.subTest(complete=complete, loaded=loaded, controls=controls):
                        sensor, current = self.profile(complete, loaded)
                        before = copy.deepcopy(current)
                        plan = sensor.plan(current, on_off_controls=controls)
                        self.assertEqual(len(plan.expected), 47 if complete else 43)
                        self.assertEqual(plan.expected['StatusReportInterval'], (loaded,))
                        self.assertEqual(plan.changes['StatusReportInterval'], (3,))
                        self.assertEqual(plan.dialog['status_report_interval'], 3)
                        self.assertEqual(plan.dialog['status_report_interval_unit'], 'seconds')
                        self.assertEqual(current, before)

    def test_loaded_valid_selector_values_are_preserved(self):
        for complete in (False, True):
            for loaded in (3, 4, 31, 127, 255):
                with self.subTest(complete=complete, loaded=loaded):
                    sensor, current = self.profile(complete, loaded)
                    plan = sensor.plan(current, on_off_controls=[{'application': 'primary'}])
                    self.assertNotIn('StatusReportInterval', plan.changes)
                    self.assertEqual(plan.dialog['status_report_interval'], loaded)
                    self.assertEqual(plan.expected['StatusReportInterval'], (loaded,))

    def test_explicit_valid_selection_overrides_initialized_integer(self):
        for complete in (False, True):
            for loaded in (0, 1, 2, 31):
                for selected in (3, 17, 255):
                    with self.subTest(complete=complete, loaded=loaded, selected=selected):
                        sensor, current = self.profile(complete, loaded)
                        plan = sensor.plan(current, status_report_interval=selected,
                                           on_off_controls=[{'application': 'primary'}])
                        self.assertEqual(self.final(plan, 'StatusReportInterval'), [selected])
                        self.assertEqual(plan.dialog['status_report_interval'], selected)
                        self.assertEqual(plan.expected['StatusReportInterval'], (loaded,))
                        result = sensor.apply(self.session(sensor, current), plan)
                        self.assertEqual(result['dialog']['status_report_interval'], selected)
                        self.assertTrue(result['verified'])
                        self.assertFalse(result['saved'])

    def test_explicit_values_outside_selector_domain_still_refuse(self):
        sensor, current = self.profile()
        for invalid in (-1, 0, 1, 2, 256, True, 3.0, '3'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(SensorError, '3..255'):
                sensor.plan(current, status_report_interval=invalid)

    def test_ordered_journal_records_initialization_before_controls_and_later_override(self):
        for complete in (False, True):
            for loaded in (0, 1, 2, 3, 255):
                with self.subTest(complete=complete, loaded=loaded):
                    sensor, current = self.profile(complete, loaded)
                    plan = sensor.plan(current, on_off_controls=[{'application': 'primary'}],
                                       status_report_interval=17)
                    phases = plan.control_history['phase_order']
                    self.assertLess(phases.index('hidden_group_load'), phases.index('global_status_initialization'))
                    self.assertLess(phases.index('global_status_initialization'), phases.index('on_off_controls'))
                    self.assertLess(phases.index('on_off_controls'), phases.index('flat_dialog_edits'))
                    row = plan.control_history['global_status_initialization']
                    self.assertEqual(row, {'raw_value': loaded, 'initialized_value': max(3, loaded),
                                           'unit': 'seconds'})
                    self.assertEqual(self.final(plan, 'StatusReportInterval'), [17])
                    receipt = replace(plan, identity=('SENLL', '2.3.00', '5031PE')).as_dict()
                    receipt['control_history']['global_status_initialization']['raw_value'] = 255
                    self.assertEqual(row['raw_value'], loaded)

    def test_configure_and_replace_preserve_immutable_raw_baseline(self):
        sensor, current = self.profile(True, 1)
        plan = sensor.plan(current, on_off_controls=[{'application': 'primary'}])
        current['StatusReportInterval'][0] = 2
        receipt = replace(plan, identity=('SENLL', '2.3.00', '5031PE')).as_dict()
        self.assertEqual(receipt['expected']['StatusReportInterval'], [1])
        receipt['expected']['StatusReportInterval'][0] = 0
        self.assertEqual(plan.expected['StatusReportInterval'], (1,))
        with self.assertRaises(TypeError):
            plan.expected['StatusReportInterval'] = (2,)
        current['StatusReportInterval'][0] = 1
        result = sensor.configure(self.session(sensor, current), on_off_controls=[{'application': 'primary'}])
        self.assertEqual(result['expected']['StatusReportInterval'], [1])
        self.assertEqual(result['changes']['StatusReportInterval'], [3])
        self.assertIsNotNone(result['control_history'])

    def test_second_unchanged_save_is_stable_and_status_set_exactly_once(self):
        for complete in (False, True):
            with self.subTest(complete=complete):
                sensor, current = self.profile(complete, 2)
                session = self.session(sensor, current)
                sensor.configure(session, on_off_controls=[{'application': 'primary'}])
                self.assertEqual([call for call in session.calls if call[0] == 'StatusReportInterval'],
                                 [('StatusReportInterval', '3')])
                plan = sensor.plan(session.values(), on_off_controls=[{'application': 'primary'}])
                self.assertEqual(plan.changes, {})

    def test_status_normalization_coexists_with_ordered_application_collision(self):
        sensor, current = self.profile(False, 0, SecondApplicationBlocks=[4])
        plan = sensor.plan(current, on_off_controls=[{'application': 'primary'}])
        self.assertEqual(self.final(plan, 'GroupAddress'), [255, 20, 255, 255, 255, 25, 255, 255])
        self.assertEqual(self.final(plan, 'SecondApplicationBlocks'), [0])
        self.assertNotIn('BlockAllocation', plan.changes)
        session = self.session(sensor, current)
        sensor.apply(session, plan)
        self.assertEqual(session.current['BlockAllocation'], ' '.join(map(str, current['BlockAllocation'])))
        self.assertEqual(plan.expected['StatusReportInterval'], (0,))
        self.assertEqual(plan.changes['StatusReportInterval'], (3,))

    def test_enabled_scene_before_save_and_global_writeback_share_original47_baseline(self):
        sensor, current = self.enabled(1)
        plan = sensor.plan(current, on_off_controls=[{'group': 21}])
        derived = scene_save_parameters(current)
        for field in ('SceneTable', 'SceneTablePointer'):
            self.assertEqual(self.final(plan, field), derived[field])
            self.assertEqual(plan.expected[field], tuple(current[field]))
        self.assertEqual(self.final(plan, 'GroupAddress')[2], 21)
        self.assertEqual(plan.expected['StatusReportInterval'], (1,))
        self.assertEqual(plan.changes['StatusReportInterval'], (3,))
        session = self.session(sensor, current)
        result = sensor.apply(session, plan)
        self.assertTrue(result['verified'])
        self.assertEqual(session.current['StatusReportInterval'], '3')
        for field in ('PatchEnable', 'AreaGroupAddress'):
            self.assertNotIn(field, plan.changes)

    def test_exact_status_byte_patch_does_not_touch_neighbors(self):
        sensor, current = self.profile(True, 0)
        plan = sensor.plan(current)
        patch = sensor.codec.encode_many({'StatusReportInterval': plan.changes['StatusReportInterval']})
        self.assertEqual([(edit.address, edit.value, edit.mask) for edit in patch.edits], [(66, 3, 255)])
        self.assertEqual(plan.expected['AreaGroupAddress'], (255,))
        self.assertEqual(plan.expected['RampRate'], (1, 3))

    def test_stale_distinct_raw_values_refuse_even_when_normalized_result_matches(self):
        for complete in (False, True):
            for loaded, stale in ((0, 1), (1, 2), (2, 0)):
                with self.subTest(complete=complete, loaded=loaded, stale=stale):
                    sensor, current = self.profile(complete, loaded)
                    session = self.session(sensor, current)
                    plan = sensor.plan(session.values())
                    session.current['StatusReportInterval'] = str(stale)
                    with self.assertRaisesRegex(SensorError, 'changed since'):
                        sensor.apply(session, plan)
                    self.assertEqual(session.calls, [])

    def test_omitted_or_forged_initialized_status_refuses_before_session_io(self):
        for complete in (False, True):
            for loaded in (0, 1, 2, 31):
                sensor, current = self.profile(complete, loaded)
                plan = sensor.plan(current)
                candidates = [(), (0,), (1,), (2,), (True,), (3, 4)]
                if loaded < 3:
                    candidates.append(None)
                for status in candidates:
                    with self.subTest(complete=complete, loaded=loaded, status=status):
                        changes = dict(plan.changes)
                        if status is None:
                            changes.pop('StatusReportInterval')
                        else:
                            changes['StatusReportInterval'] = status
                        session = self.session(sensor, current)
                        session.info = lambda _: self.fail('Rejected plan must not read the native schema')
                        session.values = lambda: self.fail('Rejected plan must not read native values')
                        with self.assertRaisesRegex(SensorError, 'Initialized Global status report interval'):
                            sensor.apply(session, replace(plan, changes=changes))
                        self.assertEqual(session.calls, [])

    def test_missing_status_expected_field_refuses(self):
        sensor, current = self.profile()
        plan = sensor.plan(current)
        expected = dict(plan.expected)
        expected.pop('StatusReportInterval')
        session = self.session(sensor, current)
        with self.assertRaisesRegex(SensorError, 'outside'):
            sensor.apply(session, replace(plan, expected=expected))
        self.assertEqual(session.calls, [])

    def test_status_native_schema_layout_remains_bound(self):
        for complete in (False, True):
            for key, value in (('BitSize', '7'), ('Address', '65')):
                with self.subTest(complete=complete, key=key):
                    sensor, current = self.profile(complete)
                    session = self.session(sensor, current)
                    plan = sensor.plan(current)
                    original_info = session.info
                    def altered_info(name):
                        root = ET.fromstring(original_info(name).lines[0][4:])
                        for node in root.findall('Param'):
                            if node.findtext('Name') == 'StatusReportInterval':
                                node.find(key).text = value
                        return Reply(ET.tostring(root, encoding='unicode'))
                    session.info = altered_info
                    with self.assertRaisesRegex(SensorError, 'Native parameter layout mismatch'):
                        sensor.apply(session, plan)
                    self.assertEqual(session.calls, [])

    def test_wrong_global_readback_stops_without_recovery_or_save(self):
        sensor, current = self.profile(True)
        session = self.session(sensor, current)
        original_set = session.set
        def wrong_status(name, value):
            original_set(name, value)
            if name == 'StatusReportInterval':
                session.current[name] = '0'
        session.set = wrong_status
        with self.assertRaisesRegex(SensorApplyError, 'readback') as caught:
            sensor.configure(session)
        self.assertEqual(caught.exception.attempted[-1], 'StatusReportInterval')
        self.assertFalse(caught.exception.details['saved'])
        self.assertEqual([call for call in session.calls if call[0] == 'StatusReportInterval'],
                         [('StatusReportInterval', '3')])

    def test_failed_global_set_retains_partial_unsaved_evidence_without_retry(self):
        sensor, current = self.profile()
        session = self.session(sensor, current)
        session.failure = 'StatusReportInterval'
        with self.assertRaisesRegex(SensorApplyError, 'simulated failed write') as caught:
            sensor.configure(session)
        self.assertEqual(session.current['StatusReportInterval'], '3')
        self.assertEqual(caught.exception.attempted[-1], 'StatusReportInterval')
        self.assertFalse(caught.exception.details['saved'])
        self.assertFalse(caught.exception.details['device_verified'])
        self.assertEqual([call for call in session.calls if call[0] == 'StatusReportInterval'],
                         [('StatusReportInterval', '3')])

    def test_scene_derived_omission_and_forgery_still_refuse_with_initialized_global(self):
        sensor, current = self.enabled(2)
        plan = sensor.plan(current)
        for field in ('SceneTable', 'SceneTablePointer'):
            for forged in (None, plan.expected[field]):
                with self.subTest(field=field, omitted=forged is None):
                    changes = dict(plan.changes)
                    if forged is None:
                        changes.pop(field)
                    else:
                        changes[field] = forged
                    session = self.session(sensor, current)
                    with self.assertRaisesRegex(SensorError, 'Scene save changes differ'):
                        sensor.apply(session, replace(plan, changes=changes))
                    self.assertEqual(session.calls, [])
        self.assertEqual(set(plan.expected), set(LAYOUTS) | set(INVENTORY_LAYOUTS))

    def test_static_source_receipt_keeps_proprietary_execution_and_hardware_unaccepted(self):
        path = Path(__file__).resolve().parents[1] / 'docs/senll-global-status-source-review.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         '7cca636cf06fe50dc8c1f516ca13718925ce887e88d912dbb80e3c6b39d2084f')
        receipt = json.loads(path.read_text())
        self.assertEqual(receipt['derived_rule']['stored_0_1_2_saved_as'], 3)
        self.assertEqual(receipt['fresh_frame']['dropdown_style'], 'lsEditFixedList')
        self.assertTrue(receipt['fresh_frame']['loading_completed_before_coordinator_initialise'])
        self.assertEqual(receipt['combo_vmt_bindings']['0x49c']['address'], '0x976c24')
        self.assertEqual(len(receipt['methods']), 44)
        for key in ('original_execution', 'original_gui_execution', 'physical_acceptance'):
            self.assertFalse(receipt[key])
        self.assertIn('earlier read-only static recovery audit', receipt['model_or_tests_or_docs_modified_scope'])


if __name__ == '__main__':
    unittest.main()
