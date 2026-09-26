"""MRA widget and shared-global composition in one retained parent save."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from cbus_toolkit import cli
from cbus_toolkit.edlt import EdltApplyError, EdltError, _field
from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from cbus_toolkit.edlt_parent_transaction import (
    CRC_FIELDS, SUPPORTED_OPERATION_NAMES, EdltParentTransaction,
)
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt import Session
from tests.test_edlt_parent_metadata import MetadataClient
from tests.test_edlt_parent_panels import extended_fixture, panel_cache
from tests.test_edlt_scene import prepared


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/fixtures/edlt-parent-mra-evidence.json'


def mra_operations():
    return (
        {'op': 'display', 'big_icons': True},
        {'op': 'zone-control', 'page': 1, 'position': 1,
         'variant': 'balance', 'label_text': 'Zone',
         'status_type': 'static', 'status_text': 'Level',
         'on_icon': 0, 'off_icon': 252},
        {'op': 'source-select', 'page': 1, 'position': 2,
         'variant': 'two-absolute', 'source1': 2, 'source2': 3,
         'label_text': 'Music', 'status_text': 'Track', 'on_icon': 1},
        {'op': 'source-control', 'page': 1, 'position': 3,
         'variant': 'dynamic-1-and-2', 'on_icon': 2},
        {'op': 'mra-globals', 'multiplexer': 2, 'zone': 8},
    )


class MRAParentTransactionTests(unittest.TestCase):
    def setUp(self):
        self.spec = extended_fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.session = Session(self.spec)
        self.source = self.editor.snapshot(prepared(self.session.values()))
        self.metadata = panel_cache(self.editor, self.source)

    def plan(self, operations=mra_operations(), *, source=None, metadata=None):
        source = self.source if source is None else source
        metadata = (panel_cache(self.editor, source)
                    if metadata is None else metadata)
        return self.editor.plan(
            source, metadata=metadata, operations=operations)

    def test_three_mra_panels_and_globals_share_one_terminal_save(self):
        plan = self.plan()
        document = plan.as_dict()
        self.assertEqual(len(SUPPORTED_OPERATION_NAMES), 23)
        self.assertEqual(document['supported_operation_types'],
                         list(SUPPORTED_OPERATION_NAMES))
        self.assertEqual(
            [plan.before_save[_field(widget)][0] for widget in range(6, 10)],
            [7, 8, 9, 255])
        self.assertEqual(
            [plan.before_save[_field(widget, 1)][0] for widget in range(6, 9)],
            [0x7d, 0x78, 0x78])
        self.assertEqual(
            [row['format'] for row in document['operation_results']],
            ['cbus-edlt-display-plan-v1', *(['cbus-edlt-mra-plan-v1'] * 4)])
        for result in document['operation_results'][1:4]:
            owned = set(result['owned_parameters'])
            for allocation_name in (
                    'default_status_allocation', 'label_allocation',
                    'status_allocation'):
                allocation = result[allocation_name]
                if allocation is not None:
                    self.assertTrue(set(allocation['changes']) <= owned)
        self.assertEqual(document['operation_metadata_dependencies'], [])
        self.assertEqual(document['transaction_guards']['mra_operations'], 4)
        self.assertEqual(document['transaction_guards'][
            'mra_global_components_owned'], ['multiplexer', 'zone'])
        ownership = document['ownership']['mra_global_bits']
        self.assertEqual(ownership['effective'],
                         {'multiplexer': 2, 'zone': 8})
        self.assertIsNone(ownership['pre_conversion_source_widget'])
        self.assertEqual(ownership['status_mask_preserved'], '0x07')
        self.assertTrue(ownership['distributed_by_terminal_serializer'])
        self.assertEqual(document['execution_counts'][
            'terminal_normalization_passes'], 1)
        self.assertEqual(document['execution_counts']['terminal_crc_passes'], 1)
        self.assertEqual(set(document['lifecycle']['crc_fields_calculated']),
                         set(CRC_FIELDS))
        self.assertTrue(document['lifecycle']['mra_composition_override'])

    def test_first_existing_pre_conversion_globals_and_standby_raw3_survive(self):
        source = dict(self.source)
        source[_field(1)] = (7,)
        source[_field(1, 1)] = (0xed,)  # raw mux3, zone6, status5
        for offset in range(2, 32):
            source[_field(1, offset)] = ((100 + offset) & 255,)
        source[_field(1, 11)] = (255,)
        source[_field(1, 12)] = (255,)
        source[_field(6)] = (0,)
        source[_field(7)] = (0,)
        source[_field(8)] = (8,)
        source[_field(8, 1)] = (2,)
        source[_field(8, 9)] = (255,)
        source[_field(8, 10)] = (255,)
        source[_field(9)] = (255,)
        before_standby = bytes(
            source[_field(1, offset)][0] for offset in range(32))
        plan = self.plan((
            {'op': 'zone-control', 'page': 1, 'position': 1,
             'zone': 2, 'status_type': 'static'},
            {'op': 'source-control', 'page': 1, 'position': 2},
        ), source=source)
        ownership = plan.as_dict()['ownership']['mra_global_bits']
        self.assertEqual(ownership['pre_conversion_source_widget'], 1)
        self.assertEqual(ownership['effective'],
                         {'multiplexer': 4, 'zone': 2})
        after_standby = bytes(
            plan.before_save[_field(1, offset)][0] for offset in range(32))
        self.assertEqual(after_standby[0], 7)
        self.assertEqual(after_standby[1], 0xcd)
        self.assertEqual(after_standby[1] & 7, before_standby[1] & 7)
        self.assertEqual(after_standby[2:], before_standby[2:])
        self.assertEqual(plan.before_save[_field(8, 1)], (0xca,))
        self.assertEqual(plan.after_controls[_field(1, 1)], (0xed,))

    def test_first_functional_source_precedes_new_earlier_widget(self):
        source = dict(self.source)
        source[_field(6)] = (0,)
        source[_field(7)] = (0,)
        source[_field(8)] = (8,)
        source[_field(8, 1)] = (0x58,)
        source[_field(8, 9)] = (255,)
        source[_field(8, 10)] = (255,)
        source[_field(9)] = (255,)
        plan = self.plan((
            {'op': 'zone-control', 'page': 1, 'position': 1,
             'status_type': 'static'},
            {'op': 'source-control', 'page': 1, 'position': 2},
        ), source=source)
        ownership = plan.as_dict()['ownership']['mra_global_bits']
        self.assertEqual(ownership['pre_conversion_source_widget'], 8)
        self.assertEqual(ownership['effective'],
                         {'multiplexer': 2, 'zone': 4})
        self.assertEqual(plan.before_save[_field(6, 1)], (0x5d,))
        self.assertEqual(plan.before_save[_field(8, 1)], (0x58,))

    def test_order_dependencies_and_global_bit_ownership_fail_closed(self):
        globals_first = (
            {'op': 'mra-globals', 'multiplexer': 2},
            {'op': 'zone-control', 'page': 1, 'position': 1},
        )
        with self.assertRaisesRegex(EdltError, 'Create an MRA widget'):
            self.plan(globals_first)
        with self.assertRaisesRegex(EdltError, 'requires multiplexer and/or zone'):
            self.plan((
                {'op': 'zone-control', 'page': 1, 'position': 1},
                {'op': 'mra-globals'},
            ))
        with self.assertRaisesRegex(EdltError, 'MRA global ownership for zone'):
            self.plan((
                {'op': 'zone-control', 'page': 1, 'position': 1, 'zone': 2},
                {'op': 'mra-globals', 'zone': 3},
            ))
        split = self.plan((
            {'op': 'zone-control', 'page': 1, 'position': 1,
             'multiplexer': 2},
            {'op': 'mra-globals', 'zone': 3},
        ))
        self.assertEqual(split.as_dict()['ownership']['mra_global_bits'][
            'effective'], {'multiplexer': 2, 'zone': 3})
        with self.assertRaisesRegex(EdltError, 'Duplicate widget byte ownership'):
            self.plan((
                {'op': 'zone-control', 'page': 1, 'position': 1},
                {'op': 'source-select', 'page': 1, 'position': 1},
            ))

        source = {**self.source, 'UseBigIcon': (0,)}
        metadata = panel_cache(self.editor, source)
        display = {'op': 'display', 'big_icons': True}
        icon = {'op': 'source-control', 'page': 1, 'position': 1,
                'on_icon': 2}
        self.plan((display, icon), source=source, metadata=metadata)
        with self.assertRaisesRegex(EdltError, 'UseBigIcon'):
            self.plan((icon, display), source=source, metadata=metadata)

    def test_all_three_panel_order_permutations_preserve_complete_records(self):
        operations = {
            'zone-control': {'op': 'zone-control', 'page': 1, 'position': 1},
            'source-select': {'op': 'source-select', 'page': 1, 'position': 2},
            'source-control': {'op': 'source-control', 'page': 1, 'position': 3},
        }
        reference = None
        for order in itertools.permutations(operations):
            with self.subTest(order=order):
                plan = self.plan(tuple(operations[name] for name in order))
                self.assertEqual(
                    [plan.before_save[_field(widget)][0]
                     for widget in range(6, 9)], [7, 8, 9])
                final = {**plan.expected, **plan.changes}
                signature = (
                    tuple(bytes(
                        plan.before_save[_field(widget, offset)][0]
                        for offset in range(32))
                          for widget in range(6, 9)),
                    plan.as_dict()['ownership']['mra_global_bits']['effective'],
                    tuple(final[field] for field in CRC_FIELDS),
                )
                if reference is None:
                    reference = signature
                else:
                    self.assertEqual(signature, reference)
                owned = {row['parameter'] for row in plan.as_dict()[
                    'ownership']['parameters']}
                for widget in range(6, 9):
                    self.assertTrue(all(
                        _field(widget, offset) in owned
                        for offset in range(32)))

    def test_unowned_fields_match_retained_baseline_and_apply_is_atomic(self):
        plan = self.plan()
        baseline = self.editor.lifecycle.plan(
            self.source, metadata=self.metadata)
        final = {**plan.expected, **plan.changes}
        baseline_final = {**baseline.expected, **baseline.changes}
        document = plan.as_dict()
        owned = {row['parameter'] for row in document['ownership']['parameters']}
        terminal = set(document['preservation'][
            'terminal_lifecycle_fields_changed'])
        for name in final:
            if name not in owned | terminal | set(CRC_FIELDS):
                self.assertEqual(final[name], baseline_final[name], name)

        session = Session(self.spec)
        session.current = dict(self.source)
        session.failure = _field(7, 1)
        with self.assertRaises(EdltApplyError) as caught:
            self.editor.apply(session, plan)
        self.assertTrue(caught.exception.details['rollback_verified'])
        self.assertEqual(self.editor.snapshot(session.values()), self.source)

        interruption = KeyboardInterrupt('stop before replay')
        session = Session(self.spec)
        session.current = dict(self.source)
        calls = []

        def stop(name, value):
            calls.append((name, value))
            raise interruption

        session.set = stop
        with self.assertRaises(KeyboardInterrupt):
            self.editor.apply(session, plan)
        evidence = interruption.edlt_parent_transaction_evidence
        self.assertEqual(len(calls), 1)
        self.assertEqual(evidence['automatic_retries'], 0)
        self.assertTrue(evidence['pp_state_uncertain'])

    def test_automatic_metadata_adds_no_fictional_audio_dependencies(self):
        client = MetadataClient(self.spec)
        source = self.editor.snapshot(client.values)
        operations = (
            {'op': 'zone-control', 'page': 1, 'position': 1,
             'label_text': 'Audio'},
            {'op': 'source-select', 'page': 1, 'position': 2},
        )
        plan = plan_native_parent_metadata(
            client.xml(), '//TEST/254/p/20', source, self.editor, operations)
        self.assertEqual(
            [(row.kind, row.application, row.address)
             for row in plan.creations],
            [('Application', 203, 203)])
        document = plan.as_dict()['parent_transaction']
        self.assertEqual(document['operation_metadata_dependencies'], [])
        self.assertEqual(document['ownership']['mra_global_bits']['effective'],
                         {'multiplexer': 1, 'zone': 1})

    def test_offline_cli_accepts_all_mra_parent_operations(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'source.json'
            metadata = Path(root) / 'metadata.json'
            operations = Path(root) / 'operations.json'
            source.write_text(json.dumps(self.source))
            metadata.write_text(json.dumps(self.metadata))
            operations.write_text(json.dumps(mra_operations()))
            before = (source.read_bytes(), metadata.read_bytes(),
                      operations.read_bytes())
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr), patch.object(
                    cli, '_edlt_parent_transaction',
                    return_value=self.editor), patch(
                    'cbus_toolkit.cgate.CGateClient',
                    side_effect=AssertionError('offline plan connected')):
                status = cli.main([
                    'edlt', 'parent-transaction-plan', str(source),
                    '--metadata', str(metadata),
                    '--operations', str(operations),
                ])
            self.assertEqual(status, 0, stderr.getvalue())
            document = json.loads(stdout.getvalue())
            self.assertEqual(document['transaction_guards']['mra_operations'], 4)
            self.assertEqual((source.read_bytes(), metadata.read_bytes(),
                              operations.read_bytes()), before)

    def test_retained_component_and_parent_boundaries_are_pinned(self):
        document = json.loads(EVIDENCE.read_text())
        self.assertEqual(document['format'],
                         'cbus-edlt-parent-mra-evidence-v1')
        for row in document['retained_evidence']:
            self.assertEqual(
                hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest(),
                row['sha256'])
        boundary = document['evidence_boundary']
        self.assertTrue(boundary['python_ordered_parent_composition'])
        self.assertTrue(boundary['original_component_behavior'])
        self.assertFalse(boundary['original_mra_multi_edit_parent_executed'])
        self.assertFalse(boundary['physical_audio_behavior_verified'])
        self.assertFalse(boundary['blank_reset_parent_composition'])


@unittest.skipUnless(
    os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
    'Set native C-Gate and specs for MRA parent save/reload acceptance')
class NativeMRAParentTransactionTests(unittest.TestCase):
    def test_native_database_one_save_close_load_preserves_mra_parent_edit(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer

        editor = EdltParentTransaction(
            UnitSpecStore(Path(os.environ['CBUS_UNITSPEC_DIR'])).load(
                'KEYGL5.xml'))
        project = 'PM' + uuid4().hex[:6].upper()
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
                    project, 254, 'Parent_MRA_Fixture',
                    'Cni', '127.0.0.1:1')
                database.create_unit(
                    network, 20, 'eDLT', 'KEYGL5', '5.5.00',
                    catalog_number='5055EDL')
                with Programmer(client).load(network, source) as session:
                    session.reset_defaults()
                    before = editor.snapshot(session.values())
                    requirements = editor.lifecycle.requirements(before).as_dict()
                    metadata = {
                        'format': 'cbus-edlt-lifecycle-cache-v1',
                        'applications': sorted(
                            row['application']
                            for row in requirements['applications']),
                        'groups': [
                            {
                                'application': row['application'],
                                'group': row['group'], 'exists': True,
                                **({'dynamic_images': [False] * 4}
                                   if 'dynamic_images_if_present'
                                   in row['facts'] else {}),
                                **({'levels': list(range(256))}
                                   if 'complete_levels_if_present'
                                   in row['facts'] else {}),
                            }
                            for row in requirements['groups']
                        ],
                    }
                    plan = editor.plan(
                        before, metadata=metadata,
                        operations=mra_operations())
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
