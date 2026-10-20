"""DB slice for one legacy displacement link (P3.05 sidecar slice 3).

Exercises ``legacy_reconcile.reconcile_legacy_journal`` against canned tmp-dir
journals plus an in-memory fake database object. Offline only: no hardware, no
network, no binaries or daemons. The fake implements the minimal mapping
protocol documented on ``reconcile_legacy_journal``; real project-file binding
is future work and this slice never touches the selected-serial lane.
"""

import json
import tempfile
import unittest
from pathlib import Path

from cbus_toolkit.legacy_reconcile import (
    LEGACY_RECORD_FORMAT,
    _legacy_db_digest,
    reconcile_legacy_journal,
)
from cbus_toolkit.serial_reconcile import ReconcileError
from tests.test_legacy_move_journal_admission import (
    DESTINATION,
    LOCAL_SERIAL,
    LOCAL_UNIT,
    SERIAL,
    SOURCE,
    build_link,
    build_occupied_link,
    DISPLACED_SERIAL,
)


class FakeLegacyDatabase:
    """In-memory address->serial store with call counters for ordering proofs."""

    def __init__(self, mapping):
        self._units = dict(mapping)
        self.snapshot_calls = 0
        self.plan_calls = 0
        self.apply_calls = 0

    def identity(self):
        return {"kind": "fake-legacy-db", "name": "test"}

    def snapshot(self):
        self.snapshot_calls += 1
        return dict(self._units)

    def plan(self, unit, destination):
        self.plan_calls += 1
        if self._units.get(unit["address"]) != unit["serial"]:
            raise ReconcileError("Fake unit is stale")
        before = _legacy_db_digest(self._units)
        expected_map = dict(self._units)
        del expected_map[unit["address"]]
        expected_map[destination] = unit["serial"]
        return {"before_sha256": before, "expected_sha256": _legacy_db_digest(expected_map),
                "source_path": f"/unit/{unit['address']}",
                "destination_path": f"/unit/{destination}"}

    def apply(self, unit, destination, plan):
        self.apply_calls += 1
        if plan["before_sha256"] != _legacy_db_digest(self._units):
            raise ReconcileError("Fake project changed after planning")
        if self._units.get(unit["address"]) != unit["serial"]:
            raise ReconcileError("Fake unit is stale")
        if destination in self._units:
            raise ReconcileError("Fake destination is occupied")
        del self._units[unit["address"]]
        self._units[destination] = unit["serial"]
        if plan["expected_sha256"] != _legacy_db_digest(self._units):
            raise ReconcileError("Fake candidate differs from its plan")


class LegacyReconcileDbTests(unittest.TestCase):
    def test_dry_run_plans_without_writing_then_apply_moves_and_rerun_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal_path, _, _, _ = build_link(tmp)
            record_path = Path(tmp) / "custom-record.json"
            database = FakeLegacyDatabase({SOURCE: SERIAL, LOCAL_UNIT: LOCAL_SERIAL})
            before = dict(database._units)
            planned = reconcile_legacy_journal(journal_path, database, record_path=record_path)
            self.assertEqual(planned["outcome"], "planned")
            self.assertFalse(planned["bus_io_performed"])
            self.assertFalse(planned["hardware_programmed"])
            self.assertEqual(database._units, before)
            self.assertEqual(database.apply_calls, 0)
            # Journal-before-send ordering: a dry run writes no record file.
            self.assertFalse(record_path.exists())
            self.assertFalse((Path(str(journal_path) + ".reconcile-legacy.json")).exists())

            result = reconcile_legacy_journal(journal_path, database, apply=True, record_path=record_path)
            self.assertEqual((result["outcome"], result["database_changed"]), ("reconciled", True))
            self.assertEqual(database._units, {DESTINATION: SERIAL, LOCAL_UNIT: LOCAL_SERIAL})
            self.assertEqual(database.apply_calls, 1)
            record = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["format"], LEGACY_RECORD_FORMAT)
            self.assertEqual(record["phase"], "db_done")
            phases = [h.get("phase") for h in record["history"] if "phase" in h]
            self.assertEqual(phases, ["physical_done", "db_pending", "db_done"])
            self.assertEqual(record["journal"]["sha256"], result["journal"]["sha256"])

            # Read-only recovery: rerun is a no-op without replaying the move.
            again = reconcile_legacy_journal(journal_path, database, apply=True, record_path=record_path)
            self.assertEqual(again["outcome"], "already_reconciled")
            self.assertEqual(database.apply_calls, 1)
            self.assertEqual(database._units, {DESTINATION: SERIAL, LOCAL_UNIT: LOCAL_SERIAL})

    def test_stale_marker_refuses_before_any_database_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal_path, marker_path, _, _ = build_link(tmp)
            marker_path.unlink()
            database = FakeLegacyDatabase({SOURCE: SERIAL, LOCAL_UNIT: LOCAL_SERIAL})
            with self.assertRaisesRegex(ReconcileError, "stale"):
                reconcile_legacy_journal(journal_path, database)
            # Pre-I/O refusal: verification failed, so the database was never read.
            self.assertEqual((database.snapshot_calls, database.plan_calls, database.apply_calls), (0, 0, 0))

    def test_occupied_database_refuses_without_mutation_and_premoved_db_is_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal_path, _, _, _ = build_occupied_link(tmp)
            # The displaced occupant still sits at the destination: refuse read-only.
            occupied = FakeLegacyDatabase({SOURCE: SERIAL, DESTINATION: DISPLACED_SERIAL,
                                           LOCAL_UNIT: LOCAL_SERIAL})
            before = dict(occupied._units)
            with self.assertRaisesRegex(ReconcileError, "occupied"):
                reconcile_legacy_journal(journal_path, occupied, apply=True)
            self.assertEqual(occupied._units, before)
            self.assertEqual(occupied.apply_calls, 0)
            with self.subTest(check="dry-run-also-refuses"):
                with self.assertRaisesRegex(ReconcileError, "occupied"):
                    reconcile_legacy_journal(journal_path, occupied)

            # A database that already shows the mover at the destination is
            # read-only recovery: no apply call either way.
            premoved = FakeLegacyDatabase({DESTINATION: SERIAL, LOCAL_UNIT: LOCAL_SERIAL})
            dry = reconcile_legacy_journal(journal_path, premoved)
            self.assertEqual(dry["outcome"], "database_already_matches")
            self.assertEqual(premoved.apply_calls, 0)
            done = reconcile_legacy_journal(journal_path, premoved, apply=True)
            self.assertEqual(done["outcome"], "database_already_matches")
            self.assertEqual(premoved.apply_calls, 0)
            self.assertEqual(premoved._units, {DESTINATION: SERIAL, LOCAL_UNIT: LOCAL_SERIAL})


if __name__ == "__main__":
    unittest.main()
