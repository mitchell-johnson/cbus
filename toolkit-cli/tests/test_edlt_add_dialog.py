"""Blank-address ComboBoxAddEdit group Add dialogs in the parent transaction."""
import hashlib
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_add_dialog import (
    MESSAGES, REFUSED_TARGETS, TARGETS, AddDialogError, accept_group_dialog,
)
from cbus_toolkit.edlt_parent_metadata import (
    NativeEdltParentTransaction, plan_native_parent_metadata,
)
from cbus_toolkit.edlt_parent_transaction import (
    EdltParentTransaction, normalize_operations,
)
from tests.test_edlt_parent_metadata import (
    FakeProgrammer, MetadataClient, NativeSession, oid,
)
from tests.test_edlt_parent_panels import extended_fixture


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/fixtures/edlt-add-dialog-evidence.json'
UNIT = '//TEST/254/p/20'


def evidence():
    return json.loads(EVIDENCE.read_text())


def measurement():
    return {'op': 'measurement', 'page': 1, 'position': 1,
            'device_id': 42, 'channel': 1}


class AddDialogModelTests(unittest.TestCase):
    def test_independent_cases(self):
        for case in evidence()['cases']:
            with self.subTest(case['name']):
                groups = case['groups']
                groups = ({value: 'G' + str(value) for value in range(255)}
                          if groups == '0..254' else
                          {int(key): value for key, value in groups.items()})
                call = lambda: accept_group_dialog(
                    'QuickStatusGroup', case['application'], groups,
                    case['project'], address=case.get('address'),
                    name=case.get('dialog_name'))
                if 'error' in case:
                    with self.assertRaisesRegex(
                            AddDialogError, f'error {case["error"]}:'):
                        call()
                    continue
                result = call()
                for key, value in case['expected'].items():
                    self.assertEqual(getattr(result, key), value, key)

    def test_messages_targets_and_hashes_match_evidence(self):
        document = evidence()
        self.assertEqual({int(key): value for key, value in
                          document['messages'].items()}, dict(MESSAGES))
        boundary = document['implemented_boundary']
        self.assertEqual(boundary['group_add_targets'], list(TARGETS))
        self.assertEqual(boundary['refused_targets'], list(REFUSED_TARGETS))
        vendor = os.environ.get('CBUS_TOOLKIT_RESEARCH_VENDOR')
        if not vendor:
            self.skipTest('Set CBUS_TOOLKIT_RESEARCH_VENDOR to verify source hashes')
        for row in document['original_sources']:
            path = Path(vendor) / row['path']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             row['sha256'], row['path'])

    def test_address_must_be_a_listed_free_address(self):
        with self.assertRaisesRegex(AddDialogError, 'listed free'):
            accept_group_dialog('QuickStatusGroup', 56, {3: 'A'}, 'P',
                                address=3)
        with self.assertRaisesRegex(AddDialogError, 'listed free'):
            accept_group_dialog('QuickStatusGroup', 56, {}, 'P', address=255)


class AddDialogPlanTests(unittest.TestCase):
    def setUp(self):
        self.spec = extended_fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.client = MetadataClient(self.spec)
        self.client.applications[56]['groups'] = {
            0: {'oid': oid(500), 'tag': 'Hall', 'levels': ()},
            1: {'oid': oid(501), 'tag': 'Porch', 'levels': ()},
        }

    def plan(self, operations, values=None):
        if values is not None:
            self.client.values.update(values)
        return plan_native_parent_metadata(
            self.client.xml(), UNIT, self.editor.snapshot(self.client.values),
            self.editor, operations)

    def test_add_creates_group_and_binds_owning_panel(self):
        plan = self.plan((
            {'op': 'add-dialog', 'field': 'QuickStatusGroup'},
            {'op': 'add-dialog', 'field': 'KeySetsEnableGroup',
             'name': ' Pages '},
            {'op': 'quick-status', 'mode': 'page-key'},
            measurement()))
        document = plan.as_dict()
        self.assertEqual(
            [(row['field'], row['application'], row['address'], row['name'],
              row['kind']) for row in document['add_dialogs']],
            [('QuickStatusGroup', 56, 2, 'Group 2', 'Group'),
             ('KeySetsEnableGroup', 203, 0, 'Pages', 'NetVar')])
        self.assertEqual(
            [row['op'] for row in document['resolved_operations']],
            ['page-control', 'quick-status', 'measurement'])
        self.assertEqual(
            [(row.kind, row.application, row.address, row.name)
             for row in plan.creations],
            [('Application', 203, 203, 'Enable Control'),
             ('Group', 56, 2, 'Group 2'), ('NetVar', 203, 0, 'Pages')])
        self.assertEqual(plan.parent_plan.changes['QuickStatusGroup'], (2,))
        self.assertEqual(plan.parent_plan.changes['KeySetsEnableGroup'], (0,))
        self.assertEqual(plan.operations[0]['op'], 'add-dialog')
        self.assertFalse(document['add_dialog_boundary'][
            'original_dialog_executed'])

    def test_earlier_operation_groups_and_add_order_are_allocated(self):
        plan = self.plan((
            {'op': 'lighting', 'page': 1, 'position': 1, 'group': 2,
             'mode': 'dimmer'},
            {'op': 'add-dialog', 'field': 'IndicatorOnColourControlGroup'},
            {'op': 'add-dialog', 'field': 'QuickStatusGroup',
             'address': 40},
            {**measurement(), 'position': 2}))
        self.assertEqual(
            [(row.field, row.address, row.name) for row in plan.add_dialogs],
            [('IndicatorOnColourControlGroup', 3, 'Group 3'),
             ('QuickStatusGroup', 40, 'Group 40')])
        self.assertEqual(
            [row['op'] for row in plan.as_dict()['resolved_operations']],
            ['lighting', 'colours', 'quick-status', 'measurement'])

    def test_proximity_group_follows_wake_mode(self):
        plan = self.plan((
            {'op': 'add-dialog', 'field': 'ProximityGroup'},
            {'op': 'activation', 'action': 7}, measurement()),
            values={'ProximityMode': '0x3'})
        self.assertEqual((plan.add_dialogs[0].application,
                          plan.add_dialogs[0].name), (202, 'Trigger Group 0'))
        with self.assertRaisesRegex(EdltError, 'wake_mode'):
            self.plan((
                {'op': 'add-dialog', 'field': 'ProximityGroup'},
                {'op': 'activation', 'wake_mode': 'primary-event',
                 'level_percent': '50'}, measurement()))

    def test_refusals(self):
        cases = (
            ((({'op': 'add-dialog', 'field': 'PrimaryApplication'},
               measurement())), 'add-application-dialog'),
            ((({'op': 'add-dialog', 'field': 'CorridorLinkingLinkGroup'},
               measurement())), 'ordered group list'),
            ((({'op': 'add-dialog', 'field': 'Nope'}, measurement())),
             'field must be one of'),
            ((({'op': 'quick-status', 'mode': 'page-key'},
               {'op': 'add-dialog', 'field': 'QuickStatusGroup'},
               measurement())), 'must precede'),
            ((({'op': 'add-dialog', 'field': 'QuickStatusGroup'},
               {'op': 'quick-status', 'group': 9}, measurement())),
             'also sets group'),
            ((({'op': 'add-dialog', 'field': 'QuickStatusGroup'},
               {'op': 'add-dialog', 'field': 'QuickStatusGroup'},
               measurement())), 'only once'),
            ((({'op': 'add-dialog', 'field': 'QuickStatusGroup',
                'name': 'Hall'}, measurement())), 'error 2203'),
            ((({'op': 'add-dialog', 'field': 'QuickStatusGroup',
                'name': 'TEST'}, measurement())), 'error 2204'),
        )
        for operations, message in cases:
            with self.subTest(message):
                with self.assertRaisesRegex((EdltError, ValueError), message):
                    self.plan(operations)
        with self.assertRaisesRegex(EdltError, 'add-dialog requires a configured'):
            self.plan(({'op': 'add-dialog', 'field': 'QuickStatusGroup'},
                       measurement()), values={'PrimaryApplication': '0xff'})

    def test_ordered_list_and_caller_cache_paths_refuse(self):
        with self.assertRaisesRegex(ValueError, 'cannot share a plan'):
            self.plan(({'op': 'add-dialog', 'field': 'QuickStatusGroup'},
                       {'op': 'corridor', 'edits': []}, measurement()))
        with self.assertRaisesRegex(EdltError, 'automatic'):
            normalize_operations(
                ({'op': 'add-dialog', 'field': 'QuickStatusGroup'},
                 measurement()))

    def test_cli_documents_admit_add_dialog_only_for_automatic_metadata(self):
        import tempfile
        from types import SimpleNamespace
        from cbus_toolkit import edlt_parent_transaction_cli as cli
        rows = [{'op': 'add-dialog', 'field': 'QuickStatusGroup'},
                measurement()]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'operations.json'
            path.write_text(json.dumps(rows))
            args = SimpleNamespace(operations=path)
            self.assertEqual(cli.operations(args)[0]['op'], 'add-dialog')
            with self.assertRaisesRegex(EdltError, 'automatic'):
                normalize_operations(cli._read_operations(path))

    def test_simulated_native_apply_creates_binds_saves_and_reloads(self):
        session = NativeSession(self.spec, self.client)
        manager = NativeEdltParentTransaction(
            self.client, self.editor, programmer=FakeProgrammer(session))
        plan = manager.plan(UNIT, operations=(
            {'op': 'add-dialog', 'field': 'QuickStatusGroup',
             'name': 'Status'}, measurement()), exclusive_project=True)
        result = manager.apply(plan, backup_project='BACKUP').as_dict()
        self.assertTrue(result['saved'] and result['persistence_verified'])
        self.assertEqual(self.client.applications[56]['groups'][2]['tag'],
                         'Status')
        self.assertEqual(self.client.values['QuickStatusGroup'], '2')
        self.assertEqual(
            [command for command in self.client.commands
             if command.startswith('DBADDSAFE')],
            ['DBADDSAFE //TEST/254 Application 203 Enable Control',
             'DBADDSAFE //TEST/254/56 Group 2 Status'])
        self.assertEqual(self.client.applications[56]['groups'][0]['tag'],
                         'Hall')


if __name__ == '__main__':
    unittest.main()
