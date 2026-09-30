"""Owned native C-Gate acceptance for blank-address eDLT group Add dialogs."""
import os
from pathlib import Path
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.edlt_parent_metadata import (
    NativeEdltParentTransaction, _snapshot,
)
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer, xml_text
from cbus_toolkit.unitspec import UnitSpecStore


@unittest.skipUnless(
    all(os.environ.get(name) for name in ('CBUS_CGATE_TEST_HOST',
                                          'CBUS_UNITSPEC_DIR')),
    'Select an owned native C-Gate and exact vendor schema for Add dialogs')
class NativeAddDialogTests(unittest.TestCase):
    def test_add_bind_save_reload_preserves_existing_metadata_and_pp(self):
        editor = EdltParentTransaction(UnitSpecStore(
            Path(os.environ['CBUS_UNITSPEC_DIR']).resolve()).load('KEYGL5.xml'))
        token = uuid4().hex[:6].upper()
        project, backup = 'AD' + token, 'AB' + token
        network = '//' + project + '/254'
        source = '/db' + network + '/p/20'
        operations = (
            {'op': 'add-dialog', 'field': 'QuickStatusGroup',
             'name': 'Status Lights'},
            {'op': 'add-dialog', 'field': 'IndicatorOnColourControlGroup'},
            {'op': 'add-dialog', 'field': 'KeySetsEnableGroup'},
            {'op': 'quick-status', 'mode': 'page-key'},
            {'op': 'measurement', 'page': 1, 'position': 1,
             'device_id': 42, 'channel': 3},
        )
        with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],
                         int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')),
                         timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Add_Fixture', 'Cni',
                                        '127.0.0.1:1')
                database.create_unit(network, 20, 'Add_Fixture', 'KEYGL5',
                                     '5.5.00', catalog_number='5055EDL')
                database.add(network, 'application', 56, 'Lighting')
                database.add(network + '/56', 'group', 0, 'Hall')
                database.add(network + '/56', 'group', 1, 'Porch')
                database.add(network, 'application', 203, 'Enable Control')
                database.add(network + '/203', 'netvar', 0, 'Existing')
                for operation in ('save', 'close', 'load'):
                    projects.operation(operation, project)
                manager = NativeEdltParentTransaction(client, editor)
                plan = manager.plan(source, operations=operations,
                                    exclusive_project=True)
                self.assertEqual(
                    [(row.field, row.application, row.address, row.name)
                     for row in plan.add_dialogs],
                    [('QuickStatusGroup', 56, 2, 'Status Lights'),
                     ('IndicatorOnColourControlGroup', 56, 3, 'Group 3'),
                     ('KeySetsEnableGroup', 203, 1,
                      'Enable Network Variable 1')])
                expected = {**plan.parent_plan.expected,
                            **plan.parent_plan.changes}
                result = manager.apply(
                    plan, backup_project=backup).as_dict()
                self.assertTrue(result['saved'])
                self.assertTrue(result['persistence_verified'])
                self.assertTrue(result['existing_metadata_preserved'])
                for operation in ('close', 'load'):
                    projects.operation(operation, project)
                text = xml_text(database.get('//' + project, xml=True))
                snapshot = _snapshot(text, network + '/p/20', editor)
                groups = {(app.address, group.address): group.tag
                          for app in snapshot.applications
                          for group in app.groups}
                self.assertEqual(groups, {
                    (56, 0): 'Hall', (56, 1): 'Porch',
                    (56, 2): 'Status Lights', (56, 3): 'Group 3',
                    (203, 0): 'Existing',
                    (203, 1): 'Enable Network Variable 1'})
                with Programmer(client).load(network, source) as session:
                    self.assertEqual(editor.snapshot(session.values()),
                                     editor.snapshot(expected))
                self.assertEqual(expected['QuickStatusGroup'], (2,))
                self.assertEqual(expected['IndicatorOnColourControlGroup'], (3,))
                self.assertEqual(expected['KeySetsEnableGroup'], (1,))
            finally:
                for name in (backup, project):
                    for operation in ('close', 'delete'):
                        try:
                            projects.operation(operation, name)
                        except Exception:
                            pass


if __name__ == '__main__':
    unittest.main()
