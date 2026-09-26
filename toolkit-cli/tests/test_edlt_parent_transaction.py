"""Ordered eDLT parent transaction, ownership and persistence boundaries."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from cbus_toolkit.edlt import EdltApplyError, EdltError, _field
from cbus_toolkit.edlt_parent_transaction import (
    CRC_FIELDS, LIGHTING_BINDING_FACTS, MAX_OPERATIONS,
    ORIGINAL_LIGHTING_SELECTION_BINDING_ORDER, EdltParentTransaction,
    normalize_operations,
)
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import cache
from tests.test_edlt_parent_form import fixture


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/fixtures/edlt-parent-transaction-evidence.json'
ACCEPTANCE = ROOT / 'research/fixtures/edlt-parent-transaction-acceptance.json'


def measurement(position=1, **overrides):
    operation = {
        'op': 'measurement', 'page': 1, 'position': position,
        'device_id': 42, 'channel': position + 2, 'decimal_places': 1,
        'gain_value': '1.5', 'offset_value': '-2.5',
        'measurement_culture': 'en-NZ',
    }
    operation.update(overrides)
    return operation


def lighting(position=2, **overrides):
    operation = {
        'op': 'lighting', 'page': 1, 'position': position,
        'group': 12, 'mode': 'dimmer', 'ramp_seconds': 20,
        'label_text': 'Bedroom light', 'restore_level': 99,
    }
    operation.update(overrides)
    return operation


def activation(**overrides):
    operation = {
        'op': 'activation', 'wake_mode': 'primary-event',
        'group': 42, 'level_percent': '50',
    }
    operation.update(overrides)
    return operation


def transaction_cache(editor, values, mode='complete'):
    """Lifecycle facts plus dependencies introduced by the baseline edit."""
    result = cache(editor.lifecycle, values, mode)
    for application, group in ((56, 12), (56, 42), (202, 42)):
        if not any((row['application'], row['group']) == (application, group)
                   for row in result['groups']):
            result['groups'].append({
                'application': application, 'group': group, 'exists': True,
                'dynamic_images': [False] * 4, 'levels': [],
            })
    return result


class ParentTransactionTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.session = Session(self.spec)
        self.source = self.editor.snapshot(self.session.values())
        self.metadata = transaction_cache(self.editor, self.source)

    def plan(self, operations=None, source=None):
        return self.editor.plan(
            self.source if source is None else source,
            metadata=self.metadata,
            operations=operations or (measurement(), lighting(), activation()))

    def test_three_distinct_controls_enter_one_terminal_save_and_crc_pass(self):
        with patch.object(
                self.editor.lifecycle, 'crcs',
                wraps=self.editor.lifecycle.crcs) as crcs, patch.object(
                    self.editor.lifecycle, '_prepare_composed_save',
                    wraps=self.editor.lifecycle._prepare_composed_save) as terminal:
            plan = self.plan()
        document = plan.as_dict()
        self.assertEqual(document['format'],
                         'cbus-edlt-parent-transaction-plan-v1')
        self.assertEqual([row['format'] for row in document['operation_results']], [
            'cbus-edlt-measurement-plan-v1', 'cbus-edlt-lighting-plan-v1',
            'cbus-edlt-activation-plan-v1'])
        self.assertEqual(plan.after_controls[_field(6)], (12,))
        self.assertEqual(plan.after_controls[_field(7)], (2,))
        self.assertEqual(plan.after_controls['ProximityLevel'], (127,))
        self.assertEqual(plan.before_save[_field(8)], (255,))
        self.assertEqual(plan.before_save['Widget7RestoreLevel'], (99,))
        self.assertEqual(set(document['phases']['crc']), set(CRC_FIELDS))
        self.assertEqual(crcs.call_count, 1)
        self.assertEqual(terminal.call_count, 1)
        self.assertEqual(document['execution_counts']['terminal_normalization_passes'], 1)
        self.assertEqual(document['execution_counts']['terminal_crc_passes'], 1)
        self.assertEqual(document['execution_counts']['database_save_calls_by_apply'], 0)
        self.assertFalse(document['native_multi_edit_parent_form_executed'])
        self.assertFalse(document['physical_device_verified'])

    def test_normalized_source_recalculates_all_crcs_without_requiring_byte_changes(self):
        baseline = self.editor.lifecycle.plan(
            self.source, metadata=self.metadata)
        normalized = {**baseline.expected, **baseline.changes}
        metadata = transaction_cache(self.editor, normalized)
        operations = (
            measurement(label_text=None, prefix_text=None, suffix_text=None),
            lighting(label_text=None, status_text=None), activation(),
        )
        with patch.object(
                self.editor.lifecycle, 'crcs',
                wraps=self.editor.lifecycle.crcs) as crcs:
            plan = self.editor.plan(
                normalized, metadata=metadata, operations=operations)
        document = plan.as_dict()
        self.assertEqual(crcs.call_count, 1)
        self.assertEqual(
            set(document['lifecycle']['crc_fields_calculated']),
            set(CRC_FIELDS))
        self.assertLess(len(document['phases']['crc']), len(CRC_FIELDS))
        self.assertLessEqual(set(document['phases']['crc']), set(CRC_FIELDS))

    def test_ordered_distinct_measurements_share_text_only_through_allocator(self):
        plan = self.plan((
            measurement(1, prefix_text='Room'),
            measurement(2, device_id=43, prefix_text='Room'),
            activation(),
        ))
        results = plan.as_dict()['operation_results']
        first = results[0]['allocations']['prefix']
        second = results[1]['allocations']['prefix']
        self.assertFalse(first['reused'])
        self.assertTrue(second['reused'])
        self.assertEqual(first['index'], second['index'])
        self.assertEqual(plan.after_controls[_field(6)], (12,))
        self.assertEqual(plan.after_controls[_field(7)], (12,))
        fields = [row['parameter'] for row in plan.as_dict()['ownership']['parameters']]
        self.assertEqual(len(fields), len(set(fields)))

    def test_duplicate_slots_conflicting_page_modes_and_activation_are_rejected(self):
        bad = (
            (measurement(1), lighting(1)),
            (measurement(1, page_mode='single'),
             lighting(2, page_mode='multiple')),
            (measurement(1), activation(), activation(level_percent='25')),
        )
        messages = ('Duplicate widget byte ownership', 'Conflicting page-mode ownership',
                    'only one activation')
        for operations, message in zip(bad, messages):
            with self.subTest(operations=operations), self.assertRaisesRegex(
                    EdltError, message):
                self.plan(operations)

    def test_operation_grammar_is_bounded_strict_and_requires_a_widget(self):
        bad = (
            [], [measurement()], [activation(), activation()],
            [measurement(), {'op': 'invented'}],
            [{**measurement(), 'unknown': 1}, lighting()],
            [measurement()] * (MAX_OPERATIONS + 1),
        )
        for operations in bad:
            with self.subTest(length=len(operations)), self.assertRaises(EdltError):
                normalize_operations(operations)
        normalized = normalize_operations([activation(), measurement()])
        self.assertEqual(tuple(row['op'] for row in normalized),
                         ('activation', 'measurement'))

    def test_percentage_action_semantics_and_all_validation_precede_writes(self):
        trigger = self.plan((
            measurement(),
            {'op': 'activation', 'wake_mode': 'trigger-event',
             'group': 42, 'action': 7},
        ))
        receipt = trigger.as_dict()['operation_results'][1]['percentage']
        self.assertEqual(receipt['meaning_after'], 'trigger-action-selector')
        self.assertEqual(receipt['bound_raw_after'], 7)
        self.assertFalse(receipt['visible_after'])
        for operations in (
                (measurement(gain_value='NaN'), activation()),
                (measurement(), activation(level_percent='100.1')),
                (measurement(), {**activation(), 'action': 7}),
                (measurement(icon_index=200), activation())):
            with self.subTest(operations=operations), self.assertRaises(EdltError):
                self.editor.configure(
                    self.session, metadata=self.metadata, operations=operations)
            self.assertEqual(self.session.calls, [])

    def test_control_projection_matches_standalone_editors_in_order(self):
        loaded = self.editor.lifecycle.load(self.source, metadata=self.metadata)
        first = self.editor.measurement_editor.plan(
            loaded.after_load, **{k: v for k, v in measurement().items()
                                  if k != 'op'})
        staged = dict(loaded.after_load)
        for offset, value in enumerate(first.record):
            staged[_field(first.widget, offset)] = (value,)
        staged[f'Widget{first.widget}RestoreLevel'] = (first.restore_level,)
        staged['NavWidgetType'] = (0,)
        for allocation in first.allocations.values():
            if allocation:
                staged.update(allocation.changes)
        staged = self.editor.common._place_record(
            staged, first.widget, first.record, normalize_mra=False)
        staged[f'Widget{first.widget}RestoreLevel'] = (first.restore_level,)
        second = self.editor.lighting_editor.plan(
            staged, **{k: v for k, v in lighting().items() if k != 'op'})
        composed = self.plan()
        results = composed.as_dict()['operation_results']
        self.assertEqual(results[0]['record_hex'], first.record.hex())
        self.assertEqual(results[1]['record_hex'], second.record.hex())
        self.assertFalse(results[0]['standalone_changes_applied_directly'])
        self.assertFalse(results[1]['standalone_changes_applied_directly'])

    def test_untouched_fields_match_unedited_retained_lifecycle(self):
        source = {
            **self.source, 'UnrelatedGlobal': (0x67,),
            'Opaque116': (85,), 'Opaque117': (19,),
            'Widget2WidgetByteValue31': (173,),
            **{f'Widget6WidgetByteValue{index}': (index + 100,)
               for index in range(14, 32)},
            **{f'Widget7WidgetByteValue{index}': (index + 80,)
               for index in range(15, 32)},
        }
        metadata = transaction_cache(self.editor, source)
        plan = self.editor.plan(
            source, metadata=metadata,
            operations=(measurement(), lighting(), activation()))
        base = self.editor.lifecycle.plan(source, metadata=metadata)
        final = {**plan.expected, **plan.changes}
        base_final = {**base.expected, **base.changes}
        owned = {row['parameter']
                 for row in plan.as_dict()['ownership']['parameters']}
        terminal = set(plan.as_dict()['preservation'][
            'terminal_lifecycle_fields_changed'])
        allowed = owned | terminal | set(CRC_FIELDS)
        for name in final:
            if name not in allowed:
                self.assertEqual(final[name], base_final[name], name)
        for name in ('UnrelatedGlobal', 'Opaque116', 'Opaque117',
                     'Widget2WidgetByteValue31'):
            self.assertEqual(final[name], source[name])
        for index in range(14, 32):
            self.assertEqual(final[f'Widget6WidgetByteValue{index}'],
                             source[f'Widget6WidgetByteValue{index}'])
        for index in range(15, 32):
            self.assertEqual(final[f'Widget7WidgetByteValue{index}'],
                             source[f'Widget7WidgetByteValue{index}'])

    def test_plan_identity_stale_readback_rollback_and_one_write_each(self):
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
        self.assertEqual(self.editor.snapshot(self.session.values()),
                         dict(plan.expected))
        self.session.calls.clear()
        result = self.editor.apply(self.session, plan)
        self.assertTrue(result['verified'])
        writes = [name for name, _ in self.session.calls]
        self.assertEqual(len(writes), len(set(writes)))
        self.assertEqual(self.editor.snapshot(self.session.values()),
                         {**plan.expected, **plan.changes})

    def test_source_and_retained_native_evidence_are_pinned_and_separated(self):
        evidence = json.loads(EVIDENCE.read_text())
        self.assertEqual(evidence['format'],
                         'cbus-edlt-parent-transaction-evidence-v1')
        self.assertEqual(
            evidence['lighting_selection_binding_order'],
            [event for event, _ in ORIGINAL_LIGHTING_SELECTION_BINDING_ORDER])
        self.assertEqual(evidence['lighting_bindings'],
                         dict(LIGHTING_BINDING_FACTS))
        for row in evidence['retained_native_evidence']:
            path = ROOT / row['path']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             row['sha256'])
        vendor = Path(
            '/Volumes/external/mac-mini-offload/source-cbus/'
            'toolkit-cli-research-vendor/edlt-decompiled')
        if vendor.is_dir():
            for row in evidence['original_sources']:
                self.assertEqual(
                    hashlib.sha256((vendor / row['path']).read_bytes()).hexdigest(),
                    row['sha256'])
        boundaries = evidence['evidence_boundaries']
        self.assertFalse(boundaries['original_full_parent_form_executed'])
        self.assertFalse(boundaries['original_multi_edit_sequence_executed'])
        self.assertFalse(boundaries['physical_device_verified'])
        acceptance = json.loads(ACCEPTANCE.read_text())
        self.assertEqual(acceptance['format'],
                         'cbus-edlt-parent-transaction-acceptance-v1')
        self.assertTrue(acceptance['evidence']['fresh_python_multi_edit'])
        self.assertFalse(acceptance['evidence']['fresh_native_database_multi_edit'])
        self.assertFalse(acceptance['evidence']['fresh_original_parent_form'])

    def test_wrong_profile_schema_fails_closed(self):
        parameters = dict(self.spec.parameters)
        parameters['ProximityLevel'] = replace(
            parameters['ProximityLevel'],
            fields={**parameters['ProximityLevel'].fields,
                    'Address': '0x125'})
        with self.assertRaisesRegex(EdltError, 'layout'):
            EdltParentTransaction(replace(self.spec, parameters=parameters))


@unittest.skipUnless(
    os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
    'Set native C-Gate and specs for parent transaction save/reload acceptance')
class NativeParentTransactionTests(unittest.TestCase):
    def test_native_database_one_save_close_load_preserves_multi_edit(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer

        editor = EdltParentTransaction(
            UnitSpecStore(Path(os.environ['CBUS_UNITSPEC_DIR'])).load('KEYGL5.xml'))
        project = 'PT' + uuid4().hex[:6].upper()
        network = '//' + project + '/254'
        source = '/db' + network + '/p/20'
        with CGateClient(
                os.environ['CBUS_CGATE_TEST_HOST'],
                int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')),
                timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            projects.operation('save', project)
            try:
                database.create_network(
                    project, 254, 'Parent_Transaction_Fixture',
                    'Cni', '127.0.0.1:1')
                database.create_unit(
                    network, 20, 'eDLT', 'KEYGL5', '5.5.00',
                    catalog_number='5055EDL')
                with Programmer(client).load(network, source) as session:
                    session.reset_defaults()
                    session.set('ActivityDuration', '30')
                    before = editor.snapshot(session.values())
                    requirements = editor.lifecycle.requirements(before).as_dict()
                    applications = sorted(
                        row['application'] for row in requirements['applications'])
                    groups = []
                    for row in requirements['groups']:
                        record = {
                            'application': row['application'],
                            'group': row['group'], 'exists': True,
                        }
                        if 'dynamic_images_if_present' in row['facts']:
                            record['dynamic_images'] = [False] * 4
                        if 'complete_levels_if_present' in row['facts']:
                            record['levels'] = list(range(256))
                        groups.append(record)
                    if not any(row['application'] == 56 and row['group'] == 12
                               for row in groups):
                        groups.append({
                            'application': 56, 'group': 12, 'exists': True,
                            'dynamic_images': [False] * 4, 'levels': [],
                        })
                    metadata = {
                        'format': 'cbus-edlt-lifecycle-cache-v1',
                        'applications': applications, 'groups': groups,
                    }
                    plan = editor.plan(
                        before, metadata=metadata,
                        operations=(measurement(), lighting(), activation()))
                    self.assertTrue(editor.apply(session, plan)['verified'])
                    final = editor.snapshot(session.values())
                    session.save_to_source()
                for action in ('save', 'close', 'load'):
                    projects.operation(action, project)
                with Programmer(client).load(network, source) as session:
                    self.assertEqual(editor.snapshot(session.values()), final)
            finally:
                projects.operation('close', project)
                projects.operation('delete', project)


if __name__ == '__main__':
    unittest.main()
