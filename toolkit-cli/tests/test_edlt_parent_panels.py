"""Extended KEYGL5 parent panel composition and dependency guards."""
from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt import EdltError, _field
from cbus_toolkit.edlt_parent_transaction import (
    CRC_FIELDS, SUPPORTED_OPERATION_NAMES, EdltParentTransaction,
)
from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from tests.test_edlt import Session
from tests.test_edlt_parent_metadata import MetadataClient
from tests.test_edlt_parent_form import fixture as parent_fixture
from tests.test_edlt_parent_transaction import transaction_cache
from tests.test_edlt_scene import prepared


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/fixtures/edlt-parent-panels-evidence.json'


def extended_fixture():
    """Merge the independently accepted panel schemas into one test profile."""
    spec = parent_fixture()
    parameters = dict(spec.parameters)
    for module_name in (
            'hvac', 'time_date', 'general', 'display', 'standby', 'colours',
            'navigation', 'quick_status', 'page_control'):
        panel_spec = importlib.import_module(
            'tests.test_edlt_' + module_name).fixture()
        for name, parameter in panel_spec.parameters.items():
            if name not in parameters:
                parameters[name] = parameter
    return replace(spec, parameters=parameters)


def all_panel_operations():
    return (
        {'op': 'navigation', 'page_mode': 'multiple',
         'variant': 'page-names',
         'page_names': {1: 'Kitchen', 2: 'Living'}},
        {'op': 'display', 'big_icons': True},
        {'op': 'standby', 'enabled': True, 'after_seconds': 30,
         'nightlight_user_keys': True, 'nightlight_colour': 'on-colour'},
        {'op': 'general', 'long_press_ms': 500, 'debounce_ms': 50,
         'status_report_seconds': 10, 'tools_page_locked': True,
         'power_restore': 'previous'},
        {'op': 'colours', 'active_screen_group': 22,
         'idle_screen_group': 23},
        {'op': 'quick-status', 'mode': 'page-key', 'group': 20,
         'low_threshold': 85, 'high_threshold': 170},
        {'op': 'page-control', 'group': 21},
        {'op': 'time-date', 'page': 0, 'position': 2, 'slices': 2,
         'display': 'time-date', 'date_format': 4,
         'time_format': '24-hour', 'leading_zero': True},
        {'op': 'measurement', 'page': 0, 'position': 4,
         'device_id': 42, 'channel': 3, 'decimal_places': 1,
         'gain_value': '1.5'},
        {'op': 'lighting', 'page': 1, 'position': 1, 'group': 12,
         'mode': 'dimmer', 'ramp_seconds': 20, 'label_text': 'Light'},
        {'op': 'enable', 'page': 1, 'position': 2, 'variable': 13,
         'level': 127, 'label_text': 'Enable'},
        {'op': 'fan', 'page': 1, 'position': 3, 'group': 14,
         'speeds': 3, 'label_text': 'Fan'},
        {'op': 'multilevel', 'page': 1, 'position': 4, 'group': 15,
         'levels': 3, 'label_text': 'Level'},
        {'op': 'room-courtesy', 'page': 2, 'position': 1, 'group': 16,
         'mode': 'bell-press', 'label_text': 'Courtesy'},
        {'op': 'scene', 'page': 2, 'position': 2, 'scene': 2,
         'label_type': 'scene', 'status_text': 'Scene'},
        {'op': 'shutter', 'page': 2, 'position': 3, 'group': 17,
         'mode': 'two-key-presets', 'preset_left': 6,
         'preset_right': 248, 'label_text': 'Blind'},
        {'op': 'timer', 'page': 2, 'position': 4, 'group': 18,
         'duration_seconds': 60, 'target_level': 100,
         'expiry_level': 1, 'ramp_seconds': 4, 'label_text': 'Timer'},
        {'op': 'hvac', 'page': 3, 'position': 1, 'group': 7,
         'zone': 4, 'decimal_places': 2, 'units': 'fahrenheit',
         'icon_index': 38, 'label_text': 'Room'},
        {'op': 'activation', 'wake_mode': 'primary-event', 'group': 19,
         'level_percent': '50'},
    )


def panel_cache(editor, source):
    metadata = transaction_cache(editor, source)
    for application in (56, 57, 172, 202, 203):
        if application not in metadata['applications']:
            metadata['applications'].append(application)
    levels = [0, 1, 2, 7, 42, 77, 88, 254, 255]
    dependencies = (
        (56, 9), (56, 12), (203, 13), (56, 14), (56, 15),
        (56, 16), (56, 17), (56, 18), (172, 7), (56, 19),
        (56, 20), (203, 21), (56, 22), (56, 23), (202, 42),
    )
    for application, group in dependencies:
        row = next((record for record in metadata['groups']
                    if (record['application'], record['group']) ==
                    (application, group)), None)
        if row is None:
            row = {'application': application, 'group': group}
            metadata['groups'].append(row)
        row.update(exists=True, dynamic_images=[False] * 4, levels=levels)
    return metadata


class ExtendedParentPanelTests(unittest.TestCase):
    def setUp(self):
        self.spec = extended_fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.session = Session(self.spec)
        self.source = self.editor.snapshot(prepared(self.session.values()))
        self.metadata = panel_cache(self.editor, self.source)

    def plan(self, operations=None, metadata=None):
        return self.editor.plan(
            self.source, metadata=self.metadata if metadata is None else metadata,
            operations=operations or all_panel_operations())

    def test_all_non_mra_widget_and_direct_settings_panels_share_one_save(self):
        plan = self.plan()
        document = plan.as_dict()
        formats = [row['format'] for row in document['operation_results']]
        self.assertEqual(len(formats), 19)
        self.assertEqual(document['supported_operation_types'],
                         list(SUPPORTED_OPERATION_NAMES))
        self.assertEqual(document['execution_counts']['retained_load_models'], 1)
        self.assertEqual(document['execution_counts'][
            'terminal_normalization_passes'], 1)
        self.assertEqual(document['execution_counts']['terminal_crc_passes'], 1)
        self.assertEqual(set(document['lifecycle']['crc_fields_calculated']),
                         set(CRC_FIELDS))
        self.assertEqual(plan.after_controls[_field(2)], (11,))
        self.assertEqual(plan.after_controls[_field(3)], (0,))
        self.assertEqual(plan.after_controls[_field(4)], (12,))
        self.assertEqual(
            [plan.after_controls[_field(widget)][0]
             for widget in range(6, 15)],
            [2, 14, 4, 16, 15, 6, 3, 5, 13])
        self.assertEqual(plan.after_controls['ActivityDuration'], (30,))
        self.assertEqual(plan.after_controls['UseBigIcon'], (1,))
        self.assertEqual(plan.after_controls['QuickStatusGroup'], (20,))
        self.assertEqual(plan.after_controls['KeySetsEnableGroup'], (21,))
        self.assertEqual(plan.after_controls['ProximityGroup'], (19,))
        self.assertEqual(document['transaction_guards']['navigation_mode'],
                         'multiple')
        self.assertEqual(document['transaction_guards']['settings_panels'], [
            'colours', 'display', 'general', 'navigation', 'page-control',
            'quick-status', 'standby'])
        self.assertTrue(document['operation_metadata_dependencies'])
        self.assertTrue(all(
            row['parent_panel_binding'][
                'standalone_dependency_validation_reused']
            for row in document['operation_results']))
        self.assertFalse(document['native_multi_edit_parent_form_executed'])
        self.assertFalse(document['physical_device_verified'])

        self.session.current = dict(self.source)
        result = self.editor.apply(self.session, plan)
        written = [name for name, _ in self.session.calls]
        self.assertTrue(result['verified'])
        self.assertEqual(len(written), len(plan.changes))
        self.assertEqual(len(written), len(set(written)))

    def test_ordered_dependencies_and_multi_slot_ownership_fail_closed(self):
        source = {**self.source, 'UseBigIcon': (0,), 'ActivityDuration': (0,)}
        metadata = panel_cache(self.editor, source)
        display = {'op': 'display', 'big_icons': True}
        hvac = {'op': 'hvac', 'page': 1, 'position': 1, 'group': 7,
                'icon_index': 38}
        measurement = {'op': 'measurement', 'page': 1, 'position': 2,
                       'device_id': 1, 'channel': 1}
        self.editor.plan(
            source, metadata=metadata,
            operations=(display, hvac, measurement))
        with self.assertRaisesRegex(EdltError, 'UseBigIcon'):
            self.editor.plan(
                source, metadata=metadata,
                operations=(hvac, display, measurement))

        standby = {'op': 'standby', 'enabled': True, 'after_seconds': 30}
        colours = {'op': 'colours', 'idle_screen_brightness': 20}
        self.editor.plan(
            source, metadata=metadata,
            operations=(standby, colours, measurement))
        with self.assertRaisesRegex(EdltError, 'Standby must already be enabled'):
            self.editor.plan(
                source, metadata=metadata,
                operations=(colours, standby, measurement))

        two_slice = {'op': 'time-date', 'page': 0, 'position': 2,
                     'slices': 2}
        covered = {'op': 'measurement', 'page': 0, 'position': 3,
                   'device_id': 1, 'channel': 1}
        with self.assertRaisesRegex(EdltError, 'Duplicate widget byte ownership'):
            self.editor.plan(
                self.source, metadata=self.metadata,
                operations=(two_slice, covered))

        # A settings panel between sparse functional placements must retain
        # the normalized validation view without claiming the blank fillers.
        sparse = self.editor.plan(
            self.source, metadata=self.metadata,
            operations=(
                {'op': 'lighting', 'page': 2, 'position': 1, 'group': 12,
                 'mode': 'dimmer', 'page_mode': 'multiple'},
                {'op': 'general', 'long_press_ms': 500},
                {'op': 'measurement', 'page': 2, 'position': 2,
                 'device_id': 1, 'channel': 1, 'page_mode': 'multiple'},
            ))
        self.assertEqual(sparse.after_controls[_field(10)], (2,))
        self.assertEqual(sparse.after_controls[_field(11)], (12,))

    def test_missing_operation_group_fails_before_session_mutation(self):
        metadata = panel_cache(self.editor, self.source)
        metadata['groups'] = [
            row for row in metadata['groups']
            if (row['application'], row['group']) != (172, 7)]
        operations = (
            {'op': 'display', 'big_icons': True},
            {'op': 'hvac', 'page': 1, 'position': 1, 'group': 7},
        )
        with self.assertRaisesRegex(EdltError, 'application 172 group 7'):
            self.editor.configure(
                self.session, metadata=metadata, operations=operations)
        self.assertEqual(self.session.calls, [])

    def test_dynamic_bindings_require_known_matching_network_metadata(self):
        operations = (
            {'op': 'lighting', 'page': 1, 'position': 1, 'group': 12,
             'mode': 'dimmer', 'label_type': 'dynamic-icon',
             'label_index': 1},
            {'op': 'measurement', 'page': 1, 'position': 2,
             'device_id': 1, 'channel': 1},
        )
        text_metadata = panel_cache(self.editor, self.source)
        row = next(row for row in text_metadata['groups']
                   if (row['application'], row['group']) == (56, 12))
        row['dynamic_images'] = [False] * 4
        with self.assertRaisesRegex(EdltError, 'resolves variant 1 as dynamic-text'):
            self.editor.plan(
                self.source, metadata=text_metadata, operations=operations)

        unknown_metadata = panel_cache(self.editor, self.source)
        row = next(row for row in unknown_metadata['groups']
                   if (row['application'], row['group']) == (56, 12))
        row.pop('dynamic_images', None)
        with self.assertRaisesRegex(EdltError, 'explicit cached dynamic image'):
            self.editor.plan(
                self.source, metadata=unknown_metadata, operations=operations)

        icon_metadata = panel_cache(self.editor, self.source)
        row = next(row for row in icon_metadata['groups']
                   if (row['application'], row['group']) == (56, 12))
        row['dynamic_images'] = [False, True, False, False]
        plan = self.editor.plan(
            self.source, metadata=icon_metadata, operations=operations)
        dependency = next(
            row for row in plan.as_dict()['operation_metadata_dependencies']
            if row.get('field') == 'dynamic_images')
        self.assertEqual(
            (dependency['application'], dependency['group'],
             dependency['variant'], dependency['is_icon']),
            (56, 12, 1, True))

        # The effective bound display is authoritative even when the second
        # operation omits its type. This catches retained dynamic status
        # bindings that the lifecycle's Lighting constructor does not inspect.
        seeded = self.editor.lighting_editor.plan(
            self.source, page=1, position=1, group=12, mode='dimmer',
            status_type='dynamic-icon', status_index=1)
        retained = {**seeded.expected, **seeded.changes}
        retained_metadata = panel_cache(self.editor, retained)
        row = next(row for row in retained_metadata['groups']
                   if (row['application'], row['group']) == (56, 12))
        row.pop('dynamic_images', None)
        with self.assertRaisesRegex(EdltError, 'explicit cached dynamic image'):
            self.editor.plan(
                retained, metadata=retained_metadata,
                operations=(
                    {'op': 'lighting', 'page': 1, 'position': 1,
                     'group': 12, 'mode': 'dimmer'},
                    {'op': 'measurement', 'page': 1, 'position': 2,
                     'device_id': 1, 'channel': 1},
                ))

    def test_navigation_consumes_only_effective_dynamic_variants(self):
        metadata = panel_cache(self.editor, self.source)
        metadata['groups'].append({
            'application': 56, 'group': 30, 'exists': True,
            'dynamic_images': [True], 'levels': [],
        })
        metadata['groups'].append({
            'application': 56, 'group': 255, 'exists': True,
            'dynamic_images': [False] * 4, 'levels': [],
        })
        logo = self.editor.plan(
            self.source, metadata=metadata,
            operations=(
                {'op': 'navigation', 'page_mode': 'multiple',
                 'variant': 'logo', 'dynamic_group': 30},
                {'op': 'measurement', 'page': 1, 'position': 1,
                 'device_id': 1, 'channel': 1},
            ))
        logo_variants = [
            row['variant'] for row in logo.as_dict()[
                'operation_metadata_dependencies']
            if row.get('field') == 'dynamic_images' and row['group'] == 30
        ]
        self.assertEqual(logo_variants, [0])

        row = next(row for row in metadata['groups']
                   if (row['application'], row['group']) == (56, 30))
        row['dynamic_images'] = [False, True, False, True]
        labels = self.editor.plan(
            self.source, metadata=metadata,
            operations=(
                {'op': 'navigation', 'page_mode': 'multiple',
                 'variant': 'dynamic-labels', 'dynamic_group': 30,
                 'page_name_indices': {1: 3, 2: 1, 3: 1, 4: 3}},
                {'op': 'measurement', 'page': 1, 'position': 1,
                 'device_id': 1, 'channel': 1},
            ))
        label_variants = [
            dependency['variant'] for dependency in labels.as_dict()[
                'operation_metadata_dependencies']
            if dependency.get('field') == 'dynamic_images'
            and dependency['group'] == 30
        ]
        self.assertEqual(label_variants, [3, 1])

    def test_unowned_fields_match_an_unedited_retained_lifecycle(self):
        plan = self.plan()
        baseline = self.editor.lifecycle.plan(
            self.source, metadata=self.metadata)
        final = {**plan.expected, **plan.changes}
        baseline_final = {**baseline.expected, **baseline.changes}
        owned = {row['parameter'] for row in plan.as_dict()[
            'ownership']['parameters']}
        terminal = set(plan.as_dict()['preservation'][
            'terminal_lifecycle_fields_changed'])
        for name in final:
            if name not in owned | terminal | set(CRC_FIELDS):
                self.assertEqual(final[name], baseline_final[name], name)
        self.assertEqual(final['UnrelatedGlobal'], self.source['UnrelatedGlobal'])

    def test_native_metadata_planner_creates_extended_dependencies_in_order(self):
        client = MetadataClient(self.spec)
        source = self.editor.snapshot(client.values)
        operations = (
            {'op': 'navigation', 'page_mode': 'multiple',
             'variant': 'page-names', 'page_names': {1: 'Kitchen'}},
            {'op': 'display', 'big_icons': True},
            {'op': 'measurement', 'page': 1, 'position': 1,
             'device_id': 42, 'channel': 1},
            {'op': 'enable', 'page': 1, 'position': 2,
             'variable': 13, 'level': 127},
            {'op': 'hvac', 'page': 1, 'position': 3,
             'group': 7, 'icon_index': 38},
            {'op': 'quick-status', 'mode': 'page-key', 'group': 20},
            {'op': 'page-control', 'group': 21},
        )
        plan = plan_native_parent_metadata(
            client.xml(), '//TEST/254/p/20', source,
            self.editor, operations)
        self.assertEqual(
            [(row.kind, row.application, row.address)
             for row in plan.creations],
            [('Application', 172, 172), ('Application', 203, 203),
             ('Group', 56, 20), ('Group', 172, 7),
             ('NetVar', 203, 13), ('NetVar', 203, 21)])
        document = plan.as_dict()
        self.assertEqual(document['static_labels']['count'], 64)
        self.assertTrue(document['static_labels']['complete'])
        self.assertEqual(len(document['parent_transaction'][
            'operation_results']), len(operations))
        self.assertEqual(plan.snapshot.project_metadata,
                         plan_native_parent_metadata(
                             client.xml(), '//TEST/254/p/20', source,
                             self.editor, operations).snapshot.project_metadata)

    def test_native_metadata_planner_derives_or_rejects_dynamic_dependencies(self):
        operations = (
            {'op': 'lighting', 'page': 1, 'position': 1, 'group': 12,
             'mode': 'dimmer', 'label_type': 'dynamic-text',
             'label_index': 1},
            {'op': 'measurement', 'page': 1, 'position': 2,
             'device_id': 1, 'channel': 1},
        )
        client = MetadataClient(self.spec)
        client.applications[56]['groups'][12] = {
            'oid': '00000000-0000-0000-0000-000000000120',
            'tag': 'Dynamic labels', 'levels': (),
            'tags': ({'variant': 1, 'type': 'TEXT', 'value': 'Light'},),
        }
        source = self.editor.snapshot(client.values)
        plan = plan_native_parent_metadata(
            client.xml(), '//TEST/254/p/20', source,
            self.editor, operations)
        self.assertEqual(plan.cache.find(56, 12).dynamic_images,
                         (False, False, False, False))

        client.applications[56]['groups'][12]['tags'] = (
            {'variant': 1, 'type': 'ICON', 'value': '12'},)
        with self.assertRaisesRegex(ValueError, 'not derivable from DBGETXML'):
            plan_native_parent_metadata(
                client.xml(), '//TEST/254/p/20', source,
                self.editor, operations)

    def test_extended_panel_sources_and_acceptance_fixtures_are_pinned(self):
        document = json.loads(EVIDENCE.read_text())
        self.assertEqual(document['format'],
                         'cbus-edlt-parent-panels-evidence-v1')
        boundary = document['implemented_boundary']
        self.assertEqual(
            boundary['widget_operations'] + boundary['settings_operations'],
            list(SUPPORTED_OPERATION_NAMES))
        for row in document['accepted_panel_fixtures']:
            self.assertEqual(
                hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest(),
                row['sha256'])
        vendor = Path(
            '/Volumes/external/mac-mini-offload/source-cbus/'
            'toolkit-cli-research-vendor/edlt-decompiled')
        if vendor.is_dir():
            for row in document['original_sources']:
                self.assertEqual(
                    hashlib.sha256((vendor / row['path']).read_bytes()).hexdigest(),
                    row['sha256'])
        remaining = document['remaining_boundary']
        self.assertFalse(remaining['mra_original_parent_multi_edit_execution'])
        self.assertFalse(remaining['original_full_parent_form_executed'])
        self.assertFalse(remaining['physical_device_verified'])


if __name__ == '__main__':
    unittest.main()
