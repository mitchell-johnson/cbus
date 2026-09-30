"""Fresh model/route guards after durable intent against an owned cmqttd.

Same-owner fixture edits happen only after the actual reconciliation intent has
been replaced/fsynced. They demonstrate that SAVE/COPY/CLOSE cannot rely on a
snapshot from before that delay; this is not a cross-client atomicity claim.
"""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.native import NativeProjects
from cbus_toolkit.programming import xml_text
from cbus_toolkit.project import ProjectDocument
from cbus_toolkit.serial_reconcile import CGateDatabase, ReconcileError, default_record_path, reconcile
from tests import test_serial_reconcile_routed_cgate as routed_fixture

BIN = os.environ.get('CBUS_CMQTTD_BIN')
STAGES = ('baseline_save_intent', 'backup_intent', 'target_save_intent', 'close_intent')
EXPECTED_OPERATIONS = {
    'baseline_save_intent': {'save': 0, 'copy': 0, 'close': 0},
    'backup_intent': {'save': 1, 'copy': 0, 'close': 0},
    'target_save_intent': {'save': 1, 'copy': 1, 'close': 0},
    'close_intent': {'save': 2, 'copy': 1, 'close': 0},
}


@unittest.skipUnless(BIN, 'Select CBUS_CMQTTD_BIN for owned durable-intent guards')
class LoadedProjectBoundaryTests(unittest.TestCase):
    # Reuse owned setup and literal physical peer utilities without inheriting
    # the owner's tests or silently duplicating their parent test count.
    setUp = routed_fixture.LoadedRoutedReconcileTests.setUp
    seed = routed_fixture.LoadedRoutedReconcileTests.seed
    physical = routed_fixture.LoadedRoutedReconcileTests.physical
    database = routed_fixture.LoadedRoutedReconcileTests.database

    def guarded_attempt(self, stage, edit):
        snapshot = self.seed(name='GUARD' + str(STAGES.index(stage)))
        journal = self.physical(snapshot)
        original_journal = journal.read_bytes()
        marker = Path(json.loads(original_journal)['attempt_identity'])
        original_marker = marker.read_bytes()
        operations, fired = [], []
        original_stage, original_operation = CGateDatabase._stage, NativeProjects.operation
        def inject(database, record, current_stage, **fields):
            original_stage(database, record, current_stage, **fields)
            if current_stage == stage and not fired:
                fired.append(True)
                # The intent is physically retained before injection.
                self.assertEqual(json.loads(record.path.read_text())['cgate']['stage'], stage)
                edit(snapshot, database)
        def operation(manager, action, project, *args, **kwargs):
            if project == snapshot.stem:
                operations.append(action)
            return original_operation(manager, action, project, *args, **kwargs)
        with patch.object(CGateDatabase, '_stage', inject), patch.object(NativeProjects, 'operation', operation):
            with self.assertRaises(ReconcileError):
                reconcile(journal, self.database(snapshot), apply=True)
        self.assertEqual(fired, [True])
        expected = EXPECTED_OPERATIONS[stage]
        self.assertEqual({name: operations.count(name) for name in expected}, expected)
        record = json.loads(default_record_path(journal).read_text())
        self.assertEqual(record['phase'], 'db_pending')
        self.assertEqual(record['cgate']['stage'], stage)
        self.assertEqual(record['rollback_errors'], [])
        self.assertEqual(journal.read_bytes(), original_journal)
        self.assertEqual(marker.read_bytes(), original_marker)
        return snapshot

    def test_route_snapshot_substitution_after_each_durable_intent_refuses_before_boundary(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                original = []
                def substitute(snapshot, database):
                    original.append(snapshot.read_bytes())
                    snapshot.write_bytes(original[0] + b' ')
                snapshot = self.guarded_attempt(stage, substitute)
                self.assertEqual(snapshot.read_bytes(), original[0] + b' ')
                loaded = ProjectDocument.from_bytes(xml_text(self.client.command('DBGETXML //' + snapshot.stem)).encode())
                address = '255' if stage in ('baseline_save_intent', 'backup_intent') else '6'
                self.assertEqual(loaded.get_field(f'/network/253/unit/{address}', 'Address'), address)

    def test_same_owner_loaded_edit_after_each_durable_intent_survives_refusal(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                def edit(snapshot, database):
                    address = 255 if stage in ('baseline_save_intent', 'backup_intent') else 6
                    self.client.command(f'DBSET //{snapshot.stem}/253/p/{address}/Description New owned edit')
                snapshot = self.guarded_attempt(stage, edit)
                address = 255 if stage in ('baseline_save_intent', 'backup_intent') else 6
                loaded = ProjectDocument.from_bytes(xml_text(self.client.command('DBGETXML //' + snapshot.stem)).encode())
                self.assertEqual(loaded.get_field(f'/network/253/unit/{address}', 'Description'), 'New owned edit')
                # The owned route snapshot was not altered to accommodate the
                # conflicting edit and is still the original loaded baseline.
                original = ProjectDocument.load(snapshot)
                self.assertEqual(original.get_field('/network/253/unit/255', 'Description'), 'Keep A & B')


if __name__ == '__main__':
    unittest.main()
