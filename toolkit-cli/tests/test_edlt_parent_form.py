"""Bounded parent-form composition, preservation and evidence boundaries."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltApplyError, EdltError, _field
from cbus_toolkit.edlt_parent_form import (
    BINDING_FACTS, ORIGINAL_INITIALIZATION_ORDER, ORIGINAL_LOAD_WORKER_ORDER,
    ORIGINAL_SAVE_ORDER, ORIGINAL_SELECTION_BINDING_ORDER,
    PERCENTAGE_INITIALIZATION_ORDER, EdltParentForm,
)
from cbus_toolkit.unitspec import ParameterSpec, UnitSpecStore
from tests.test_edlt import Session
from tests.test_edlt_activation import fixture as activation_fixture
from tests.test_edlt_lifecycle import cache


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/fixtures/edlt-parent-form-evidence.json'
ACCEPTANCE = ROOT / 'research/fixtures/edlt-parent-form-acceptance.json'


def fixture():
    spec = activation_fixture()
    parameters = dict(spec.parameters)
    for name, bit, default in (
            ('InvertDisplay', 3, 1), ('UseBigIcon', 4, 1)):
        parameters[name] = ParameterSpec(name, 'bit', 'synthetic.xml', {
            'Name': name, 'Type': 'bit', 'Address': '0x118',
            'BitAddress': str(bit), 'BitSize': '1', 'DefaultValue': str(default),
        })
    return replace(spec, parameters=parameters)


def measurement(**overrides):
    result = {
        'page': 1, 'position': 1, 'device_id': 42, 'channel': 3,
        'decimal_places': 1, 'gain_value': '1.5', 'offset_value': '-2.5',
        'measurement_culture': 'en-NZ',
    }
    result.update(overrides)
    return result


def activation(**overrides):
    result = {'wake_mode': 'primary-event', 'group': 42, 'level_percent': '50'}
    result.update(overrides)
    return result


class ParentFormTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentForm(self.spec)
        self.session = Session(self.spec)
        self.source = self.editor.snapshot(self.session.values())
        self.metadata = cache(self.editor.lifecycle, self.source)

    def plan(self, source=None, **options):
        return self.editor.plan(
            self.source if source is None else source,
            metadata=self.metadata, measurement=options.pop('measurement', measurement()),
            activation=options.pop('activation', activation()), **options)

    def test_composes_load_controls_save_crc_and_reports_exact_boundaries(self):
        plan = self.plan()
        document = plan.as_dict()
        final = {**plan.expected, **plan.changes}
        self.assertEqual(document['format'], 'cbus-edlt-parent-form-plan-v1')
        self.assertEqual(set(document['phases']), {'after_load', 'controls', 'before_save', 'crc'})
        self.assertEqual(plan.after_load['InvertDisplay'], (0,))
        self.assertEqual(plan.after_controls[_field(6)], (12,))
        self.assertEqual(plan.after_controls['ProximityMode'], (2,))
        self.assertEqual(plan.after_controls['ProximityLevel'], (127,))
        self.assertEqual(plan.before_save[_field(7)], (255,))
        self.assertEqual(final['Application'], (56, 57))
        self.assertEqual(len(document['phases']['crc']), 5)
        self.assertEqual(document['cross_control']['bound_percentage_before'], '100')
        self.assertEqual(document['cross_control']['bound_percentage_after'],
                         '49.803921568627450980392156863')
        self.assertEqual(document['cross_control']['meaning_after'], 'primary-event-level')
        self.assertTrue(document['cross_control']['visible_after'])
        self.assertTrue(document['preservation']['unrelated_fields_equal_unedited_lifecycle'])
        self.assertFalse(document['native_parent_form_executed'])
        self.assertFalse(document['winforms_focus_and_dialog_behavior_verified'])
        self.assertFalse(document['database_save_reload_verified_for_composition'])
        self.assertFalse(document['physical_device_verified'])

    def test_control_phase_preserves_opaque_and_unrelated_values(self):
        source = {
            **self.source,
            'UnrelatedGlobal': (0x67,), 'Opaque116': (85,), 'Opaque117': (19,),
            'Widget2WidgetByteValue31': (173,),
            **{f'Widget6WidgetByteValue{index}': (index + 100,)
               for index in range(14, 32)},
        }
        metadata = cache(self.editor.lifecycle, source)
        plan = self.editor.plan(
            source, metadata=metadata, measurement=measurement(),
            activation=activation())
        final = {**plan.expected, **plan.changes}
        for name in ('UnrelatedGlobal', 'Opaque116', 'Opaque117',
                     'Widget2WidgetByteValue31'):
            self.assertEqual(final[name], source[name])
        for index in range(14, 32):
            self.assertEqual(final[f'Widget6WidgetByteValue{index}'], (index + 100,))
        base = self.editor.lifecycle.plan(source, metadata=metadata)
        base_final = {**base.expected, **base.changes}
        changed = set(plan.as_dict()['preservation']['composition_delta_from_unedited_lifecycle'])
        for name in final:
            if name not in changed:
                self.assertEqual(final[name], base_final[name], name)

    def test_differential_matches_standalone_measurement_and_activation_models(self):
        loaded = self.editor.lifecycle.load(self.source, metadata=self.metadata)
        standalone_measurement = self.editor.measurement_editor.plan(
            loaded.after_load, **measurement())
        composed = self.plan()
        self.assertEqual(composed.measurement.record, standalone_measurement.record)
        self.assertEqual(composed.measurement.composite_conversions,
                         standalone_measurement.composite_conversions)
        self.assertEqual(
            tuple(composed.after_controls[_field(6, offset)][0] for offset in range(32)),
            tuple(standalone_measurement.record))
        standalone_activation = self.editor.activation_editor.plan(
            composed.after_controls, wake_mode='primary-event', group=42, level=127)
        self.assertEqual(json.loads(composed.activation_document)['raw_values'],
                         standalone_activation.as_dict()['raw_values'])

    def test_mode_visibility_and_shared_raw_value_cross_control_behavior(self):
        for bad in (
                activation(wake_mode='trigger-event'),
                activation(action=7),
                activation(wake_mode='key-press')):
            with self.subTest(bad=bad), self.assertRaises(EdltError):
                self.plan(activation=bad)
        source = {**self.source, 'ProximityMode': (2,), 'ProximityGroup': (42,),
                  'ProximityLevel': (173,)}
        metadata = cache(self.editor.lifecycle, source)
        plan = self.editor.plan(
            source, metadata=metadata, measurement=measurement(),
            activation={'wake_mode': 'trigger-event', 'group': 42, 'action': 7})
        percentage = plan.as_dict()['cross_control']
        self.assertEqual((percentage['meaning_before'], percentage['meaning_after']),
                         ('primary-event-level', 'trigger-action-selector'))
        self.assertEqual(percentage['bound_raw_after'], 7)
        self.assertFalse(percentage['visible_after'])
        with self.assertRaisesRegex(EdltError, 'Standby'):
            self.editor.plan(
                {**source, 'ActivityDuration': (0,)}, metadata=metadata,
                measurement=measurement(), activation=activation())

    def test_all_control_validation_precedes_writes(self):
        for measurement_options, activation_options in (
                (measurement(offset_value='NaN'), activation()),
                (measurement(gain_value='1,5', measurement_culture='canonical'), activation()),
                (measurement(), activation(level_percent='100.1')),
                (measurement(icon_index=200), activation()),
        ):
            with self.subTest(measurement=measurement_options, activation=activation_options):
                with self.assertRaises((EdltError, ValueError)):
                    self.editor.configure(
                        self.session, metadata=self.metadata,
                        measurement=measurement_options, activation=activation_options)
                self.assertEqual(self.session.calls, [])

    def test_plan_identity_stale_state_rollback_and_success(self):
        plan = self.plan()
        forged = replace(plan, evidence='{}')
        with self.assertRaisesRegex(EdltError, 'differs'):
            self.editor.apply(self.session, forged)
        self.assertEqual(self.session.calls, [])
        self.session.current['ProximityLevel'] = '1'
        with self.assertRaisesRegex(EdltError, 'changed since'):
            self.editor.apply(self.session, plan)
        self.session.current = dict(plan.expected)
        self.session.failure = 'ProximityLevel'
        with self.assertRaises(EdltApplyError) as caught:
            self.editor.apply(self.session, plan)
        self.assertTrue(caught.exception.as_dict()['rollback_verified'])
        self.assertEqual(self.editor.snapshot(self.session.values()), dict(plan.expected))
        self.session.calls.clear()
        self.assertTrue(self.editor.apply(self.session, plan)['verified'])
        self.assertEqual(self.editor.snapshot(self.session.values()),
                         {**plan.expected, **plan.changes})

    def test_source_and_retained_native_evidence_are_pinned_and_separated(self):
        evidence = json.loads(EVIDENCE.read_text())
        self.assertEqual(evidence['format'], 'cbus-edlt-parent-form-evidence-v1')
        self.assertEqual(
            evidence['initialization_order'],
            [event for event, _ in ORIGINAL_INITIALIZATION_ORDER])
        self.assertEqual(evidence['load_worker_order'],
                         [event for event, _ in ORIGINAL_LOAD_WORKER_ORDER])
        self.assertEqual(evidence['selection_binding_order'],
                         [event for event, _ in ORIGINAL_SELECTION_BINDING_ORDER])
        self.assertEqual(evidence['percentage_initialization_order'],
                         [event for event, _ in PERCENTAGE_INITIALIZATION_ORDER])
        self.assertEqual(evidence['bindings'], dict(BINDING_FACTS))
        self.assertEqual(evidence['save_order'], list(ORIGINAL_SAVE_ORDER))
        for row in evidence['retained_native_evidence']:
            path = ROOT / row['path']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['sha256'])
        vendor = Path('/Volumes/external/mac-mini-offload/source-cbus/toolkit-cli-research-vendor/edlt-decompiled')
        if vendor.is_dir():
            for row in evidence['original_sources']:
                self.assertEqual(hashlib.sha256((vendor / row['path']).read_bytes()).hexdigest(),
                                 row['sha256'])
        self.assertFalse(evidence['evidence_boundaries']['original_full_parent_form_executed'])
        acceptance = json.loads(ACCEPTANCE.read_text())
        self.assertEqual(acceptance['format'], 'cbus-edlt-parent-form-acceptance-v1')
        self.assertTrue(acceptance['evidence']['fresh_python_composition'])
        self.assertFalse(acceptance['evidence']['fresh_native_database_composition'])
        self.assertFalse(acceptance['evidence']['fresh_original_parent_form'])

    def test_rejects_unknown_options_and_wrong_schema(self):
        with self.assertRaisesRegex(EdltError, 'unsupported fields'):
            self.editor.plan(self.source, metadata=self.metadata,
                             measurement={**measurement(), 'invented': 1}, activation=activation())
        parameters = dict(self.spec.parameters)
        parameters['ProximityLevel'] = replace(
            parameters['ProximityLevel'],
            fields={**parameters['ProximityLevel'].fields, 'Address': '0x125'})
        with self.assertRaisesRegex(EdltError, 'layout'):
            EdltParentForm(replace(self.spec, parameters=parameters))


@unittest.skipUnless(
    os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
    'Set native C-Gate and specs for parent-form database save/reload acceptance')
class NativeParentFormTests(unittest.TestCase):
    def test_native_database_save_close_load_preserves_complete_plan(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer

        editor = EdltParentForm(
            UnitSpecStore(Path(os.environ['CBUS_UNITSPEC_DIR'])).load('KEYGL5.xml'))
        project = 'PF' + uuid4().hex[:6].upper()
        network = '//' + project + '/254'
        source = '/db' + network + '/p/20'
        with CGateClient(
                os.environ['CBUS_CGATE_TEST_HOST'],
                int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            projects.operation('save', project)
            try:
                database.create_network(project, 254, 'Parent_Form_Fixture',
                                        'Cni', '127.0.0.1:1')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00',
                                     catalog_number='5055EDL')
                with Programmer(client).load(network, source) as session:
                    session.reset_defaults()
                    session.set('ActivityDuration', '30')
                    before = editor.snapshot(session.values())
                    requirements = editor.lifecycle.requirements(before).as_dict()
                    applications = sorted(row['application']
                                          for row in requirements['applications'])
                    groups = []
                    for row in requirements['groups']:
                        record = {
                            'application': row['application'], 'group': row['group'],
                            'exists': True,
                        }
                        if 'dynamic_images_if_present' in row['facts']:
                            record['dynamic_images'] = [False] * 4
                        if 'complete_levels_if_present' in row['facts']:
                            record['levels'] = list(range(256))
                        groups.append(record)
                    metadata = {'format': 'cbus-edlt-lifecycle-cache-v1',
                                'applications': applications, 'groups': groups}
                    plan = editor.plan(
                        before, metadata=metadata, measurement=measurement(),
                        activation=activation())
                    result = editor.apply(session, plan)
                    self.assertTrue(result['verified'])
                    final = editor.snapshot(session.values())
                    session.save_to_source()
                for action in ('save', 'close', 'load'):
                    projects.operation(action, project)
                with Programmer(client).load(network, source) as session:
                    self.assertEqual(editor.snapshot(session.values()), final)
                self.assertTrue(any('state=new' in line
                                    for line in client.command('GET ' + network + ' state').lines))
            finally:
                projects.operation('close', project)
                projects.operation('delete', project)


if __name__ == '__main__':
    unittest.main()
