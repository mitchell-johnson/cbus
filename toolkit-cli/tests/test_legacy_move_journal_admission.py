"""Admission of one legacy displacement link (P3.05 sidecar slice 1).

Hand-builds a single admissible ``cbus-legacy-address-result-v1`` document
for one ``ensure_vacant`` link (non-255 singleton source 6 holding
101136.1559 to free address 2, ``native_method="legacy_address"``,
``reason="displacement"``) with canned before/after identity maps and an
own-namespace marker in a tmp dir. Offline fixtures/tmp only; no hardware,
no network, no binaries or daemons: pure admission logic.

Binding slice (appended): pins the own-namespace attempt binding without
touching production code — marker-namespace separation both directions,
marker-deletion staleness, relocation refusal, scope mismatch, and
tamper-closed reparse.

Occupied-destination slice (appended, tests-only; no production changes):
depth>0 links naming the displaced occupant with a vacated re-proof —
admission with the correct proof plus refusal without the name and on
occupant mismatch.
"""

import json
import tempfile
import unittest
from pathlib import Path

from cbus_toolkit.legacy_reconcile import (
    LEGACY_ATTEMPT_FORMAT,
    LEGACY_PLAN_FORMAT,
    LEGACY_RESULT_FORMAT,
    VerifiedLegacyMove,
    _legacy_fingerprint,
    verify_legacy_journal,
)
from cbus_toolkit.serial_reconcile import ReconcileError, verify_journal

SERIAL = "101136.1559"
LOCAL_SERIAL = "100966.1187"
SOURCE = 6
DESTINATION = 2
LOCAL_UNIT = 16
ENDPOINT = {"host": "127.0.0.1", "port": 10001}


def build_link(directory):
    directory = Path(directory)
    before = {"identities": [
        {"address": SOURCE, "serials": [SERIAL]},
        {"address": LOCAL_UNIT, "serials": [LOCAL_SERIAL]},
    ]}
    after = {"identities": [
        {"address": DESTINATION, "serials": [SERIAL]},
        {"address": LOCAL_UNIT, "serials": [LOCAL_SERIAL]},
    ]}
    plan = {"format": LEGACY_PLAN_FORMAT, "serial": SERIAL, "source": SOURCE,
            "destination": DESTINATION, "endpoint": dict(ENDPOINT), "local_unit": LOCAL_UNIT,
            "expected_local_serial": LOCAL_SERIAL, "reason": "displacement",
            "native_method": "legacy_address", "chain_id": "test-chain-001", "depth": 0,
            "displaced": None, "before": before, "expected_after": after}
    fingerprint = _legacy_fingerprint(plan)
    journal_path = directory / "legacy-move.json"
    marker_path = directory / f".cbus-legacy-address-attempt-sha256-{fingerprint}.json"
    marker = {"format": LEGACY_ATTEMPT_FORMAT, "operation": "apply",
              "attempt_id": "sha256:" + fingerprint,
              "scope": "resolved_journal_directory", "journal": str(journal_path),
              "plan": plan, "send_may_have_occurred": True, "read_only_recovery_only": True}
    value = {"format": LEGACY_RESULT_FORMAT, "operation": "apply", "state": "after_observed",
             "outcome": "observed_expected_change", "plan": plan, "before": before, "after": after,
             "vacated": None, "journal": {"path": str(journal_path)},
             "attempt_identity": str(marker_path), "receipt_matches_request": False,
             "attempt_recorded": True, "attempt_durability_verified": True, "transport_invoked": True,
             "send_attempted": True, "after_collection_complete": True, "expected_identity_change": True,
             "unexpected_changes": [], "errors": [], "atomic_observation": False,
             "firmware_persistence_verified": False, "physical_compatibility_verified": False,
             "exclusive_ownership_required": True, "automatic_retries": 0, "automatic_rollback": False,
             "database_updated": False, "deadline_scope": "transaction_after_validation_and_lock"}
    # Journal-before-send order: the marker is durably reserved first.
    marker_path.write_text(json.dumps(marker, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    journal_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return journal_path, marker_path, value, plan


class LegacyMoveJournalAdmissionTests(unittest.TestCase):
    def test_displacement_link_journal_admits_singleton_non255_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal_path, marker_path, _, _ = build_link(tmp)
            moved = verify_legacy_journal(journal_path)
            self.assertIsInstance(moved, VerifiedLegacyMove)
            self.assertEqual((moved.serial, moved.source, moved.destination), (SERIAL, SOURCE, DESTINATION))
            self.assertEqual(moved.native_method, "legacy_address")
            self.assertEqual(moved.reason, "displacement")
            self.assertEqual((moved.chain_id, moved.depth, moved.displaced), ("test-chain-001", 0, None))
            # The shared dispatcher admits the same journal through verify_journal.
            via_dispatcher = verify_journal(journal_path)
            self.assertEqual((via_dispatcher.serial, via_dispatcher.source, via_dispatcher.destination),
                             (SERIAL, SOURCE, DESTINATION))
            with self.subTest(lane="legacy-refuses-selected-serial-path"):
                other = Path(tmp) / "selected.json"
                other.write_text(json.dumps({"format": "cbus-selected-serial-result-v1"}), encoding="utf-8")
                with self.assertRaises(ReconcileError):
                    verify_legacy_journal(other)
            with self.subTest(lane="dispatcher-refuses-legacy-marker-path"):
                with self.assertRaises(ReconcileError):
                    verify_journal(marker_path)


class LegacyMoveJournalBindingTests(unittest.TestCase):
    """Binding of one legacy displacement link (P3.05 sidecar binding slice).

    Tests-only; no production changes. Offline fixtures/tmp only; no hardware,
    no network.
    """

    def test_marker_namespaces_are_disjoint_both_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal_path, marker_path, _, plan = build_link(tmp)
            fingerprint = _legacy_fingerprint(plan)
            legacy_name = f".cbus-legacy-address-attempt-sha256-{fingerprint}.json"
            selected_name = f".cbus-selected-serial-attempt-sha256-{fingerprint}.json"
            self.assertEqual(marker_path.name, legacy_name)
            # Synthetic-path separation: neither lane's exact filename rule (the
            # Path(marker).name comparisons at legacy_reconcile.py:354 and
            # serial_reconcile.py:252) admits the other's marker namespace.
            self.assertNotEqual(Path(selected_name).name, legacy_name)
            self.assertNotEqual(Path(legacy_name).name, selected_name)
            with self.subTest(direction="legacy-refuses-selected-serial-marker-name"):
                other = Path(tmp) / selected_name
                other.write_bytes(marker_path.read_bytes())
                value = json.loads(journal_path.read_text(encoding="utf-8"))
                value["attempt_identity"] = str(other)
                journal_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")),
                                        encoding="utf-8")
                with self.assertRaisesRegex(ReconcileError, "does not name its plan"):
                    verify_legacy_journal(journal_path)
            with self.subTest(direction="dispatcher-refuses-legacy-marker"):
                with self.assertRaises(ReconcileError):
                    verify_journal(marker_path)

    def test_deleted_marker_makes_the_journal_stale(self):
        # Mirrors the selected-serial stale rule (test_serial_reconcile.py:194-200).
        with tempfile.TemporaryDirectory() as tmp:
            journal_path, marker_path, _, _ = build_link(tmp)
            marker_path.unlink()
            with self.assertRaisesRegex(ReconcileError, "stale"):
                verify_legacy_journal(journal_path)

    def test_relocated_journal_home_is_refused(self):
        # The binding is content-addressed: legacy_reconcile.py:348-379 compares
        # marker content against the journal's embedded records and never the
        # `path` argument under verification (as in the selected-serial lane at
        # serial_reconcile.py:247-280). An identical byte-copy therefore verifies
        # as the same evidence, but a journal moved out of the marker-bound
        # directory that claims its new home is refused ("marker names a
        # different journal").
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            elsewhere = directory / "elsewhere"
            elsewhere.mkdir()
            journal_path, _, _, _ = build_link(directory)
            pristine = journal_path.read_bytes()
            moved = elsewhere / journal_path.name
            with self.subTest(relocation="identical-byte-copy-is-the-same-evidence"):
                moved.write_bytes(pristine)
                try:
                    self.assertIsInstance(verify_legacy_journal(moved), VerifiedLegacyMove)
                finally:
                    moved.unlink()
            with self.subTest(relocation="new-home-unbound-by-marker"):
                moved.write_bytes(pristine)
                journal_path.unlink()
                value = json.loads(moved.read_text(encoding="utf-8"))
                value["journal"] = {"path": str(moved)}
                moved.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")),
                                 encoding="utf-8")
                with self.assertRaisesRegex(ReconcileError, "different journal"):
                    verify_legacy_journal(moved)

    def test_marker_scope_directory_mismatch_is_refused(self):
        # Mirrors the marker field-forging refusal shape in
        # test_rust_serial_reconcile.py:431-436.
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            elsewhere = directory / "elsewhere"
            elsewhere.mkdir()
            journal_path, marker_path, _, _ = build_link(directory)
            pristine_journal = journal_path.read_bytes()
            pristine_marker = marker_path.read_bytes()
            try:
                with self.subTest(scope="marker-moved-out-of-journal-directory"):
                    moved = elsewhere / marker_path.name
                    moved.write_bytes(pristine_marker)
                    marker_path.unlink()
                    value = json.loads(journal_path.read_text(encoding="utf-8"))
                    value["attempt_identity"] = str(moved)
                    journal_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")),
                                            encoding="utf-8")
                    with self.assertRaisesRegex(ReconcileError, "scope"):
                        verify_legacy_journal(journal_path)
            finally:
                journal_path.write_bytes(pristine_journal)
                if not marker_path.exists():
                    marker_path.write_bytes(pristine_marker)
            with self.subTest(scope="forged-scope-field"):
                record = json.loads(marker_path.read_text(encoding="utf-8"))
                record["scope"] = "operator_selected_attempt_store"
                marker_path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")),
                                       encoding="utf-8")
                with self.assertRaisesRegex(ReconcileError, "scope"):
                    verify_legacy_journal(journal_path)

    def test_tampered_journal_copy_fails_closed(self):
        # No _Journal writer exists in the legacy lane (journals/markers are
        # plain files), and no :515-516-style tamper helper exists in the
        # selected-serial lane files at those lines, so refusal is asserted on
        # reparse/proof mismatch: any single flipped byte either breaks strict
        # UTF-8 JSON parsing or breaks a canonical-form/proof comparison.
        with tempfile.TemporaryDirectory() as tmp:
            journal_path, marker_path, _, _ = build_link(tmp)
            pristine = journal_path.read_bytes()
            self.assertIsInstance(verify_legacy_journal(journal_path), VerifiedLegacyMove)
            tampered_path = Path(tmp) / "legacy-move-tampered.json"
            raw = bytearray(pristine)
            offset = len(raw) // 2
            raw[offset] = (raw[offset] + 1) % 256
            tampered_path.write_bytes(bytes(raw))
            with self.subTest(check="direct"):
                with self.assertRaises(ReconcileError):
                    verify_legacy_journal(tampered_path)
            with self.subTest(check="dispatcher"):
                with self.assertRaises(ReconcileError):
                    verify_journal(tampered_path)
            with self.subTest(check="journal-marker-swap"):
                swapped = Path(tmp) / "legacy-move-swapped.json"
                swapped.write_bytes(marker_path.read_bytes())
                with self.assertRaisesRegex(ReconcileError, "uncertain attempt"):
                    verify_legacy_journal(swapped)
            self.assertEqual(journal_path.read_bytes(), pristine)


DISPLACED_SERIAL = "200001.1234"
MISMATCHED_SERIAL = "300002.567"


def build_occupied_link(directory, *, depth=1, displaced=DISPLACED_SERIAL,
                        chain_id="test-chain-002"):
    """Hand-build an occupied-destination legacy link with its vacated re-proof.

    The canned before map holds the mover as a singleton at SOURCE, the
    displaced occupant as a singleton at DESTINATION, and the pinned local
    PCI serial; the vacated re-proof is before with only the displaced
    occupant removed. Journal-before-send order: the marker is written first.
    """
    directory = Path(directory)
    before = {"identities": [
        {"address": DESTINATION, "serials": [DISPLACED_SERIAL]},
        {"address": SOURCE, "serials": [SERIAL]},
        {"address": LOCAL_UNIT, "serials": [LOCAL_SERIAL]},
    ]}
    after = {"identities": [
        {"address": DESTINATION, "serials": [SERIAL]},
        {"address": LOCAL_UNIT, "serials": [LOCAL_SERIAL]},
    ]}
    plan = {"format": LEGACY_PLAN_FORMAT, "serial": SERIAL, "source": SOURCE,
            "destination": DESTINATION, "endpoint": dict(ENDPOINT), "local_unit": LOCAL_UNIT,
            "expected_local_serial": LOCAL_SERIAL, "reason": "displacement",
            "native_method": "legacy_address", "chain_id": chain_id, "depth": depth,
            "displaced": displaced, "before": before, "expected_after": after}
    vacated = (None if displaced is None else {"identities": [
        {"address": SOURCE, "serials": [SERIAL]},
        {"address": LOCAL_UNIT, "serials": [LOCAL_SERIAL]},
    ]})
    fingerprint = _legacy_fingerprint(plan)
    journal_path = directory / "legacy-move-occupied.json"
    marker_path = directory / f".cbus-legacy-address-attempt-sha256-{fingerprint}.json"
    marker = {"format": LEGACY_ATTEMPT_FORMAT, "operation": "apply",
              "attempt_id": "sha256:" + fingerprint,
              "scope": "resolved_journal_directory", "journal": str(journal_path),
              "plan": plan, "send_may_have_occurred": True, "read_only_recovery_only": True}
    value = {"format": LEGACY_RESULT_FORMAT, "operation": "apply", "state": "after_observed",
             "outcome": "observed_expected_change", "plan": plan, "before": before, "after": after,
             "vacated": vacated, "journal": {"path": str(journal_path)},
             "attempt_identity": str(marker_path), "receipt_matches_request": False,
             "attempt_recorded": True, "attempt_durability_verified": True, "transport_invoked": True,
             "send_attempted": True, "after_collection_complete": True, "expected_identity_change": True,
             "unexpected_changes": [], "errors": [], "atomic_observation": False,
             "firmware_persistence_verified": False, "physical_compatibility_verified": False,
             "exclusive_ownership_required": True, "automatic_retries": 0, "automatic_rollback": False,
             "database_updated": False, "deadline_scope": "transaction_after_validation_and_lock"}
    marker_path.write_text(json.dumps(marker, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    journal_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return journal_path, marker_path, value, plan


class LegacyOccupiedDestinationAdmissionTests(unittest.TestCase):
    """Occupied-destination admission with vacated re-proof (P3.05 sidecar slice 2).

    Tests-only; no production changes — the landed admission slice already
    validates the displaced name and the vacated re-proof. Offline
    fixtures/tmp only; no hardware, no network.
    """

    def test_occupied_destination_with_displaced_proof_admits(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal_path, _, value, _ = build_occupied_link(tmp)
            self.assertEqual(value["vacated"], {"identities": [
                {"address": SOURCE, "serials": [SERIAL]},
                {"address": LOCAL_UNIT, "serials": [LOCAL_SERIAL]},
            ]})
            moved = verify_legacy_journal(journal_path)
            self.assertIsInstance(moved, VerifiedLegacyMove)
            self.assertEqual((moved.serial, moved.source, moved.destination), (SERIAL, SOURCE, DESTINATION))
            self.assertEqual(moved.native_method, "legacy_address")
            self.assertEqual(moved.reason, "displacement")
            self.assertEqual((moved.chain_id, moved.depth, moved.displaced),
                             ("test-chain-002", 1, DISPLACED_SERIAL))
            with self.subTest(lane="dispatcher-admits-occupied-link"):
                via_dispatcher = verify_journal(journal_path)
                self.assertEqual((via_dispatcher.depth, via_dispatcher.displaced), (1, DISPLACED_SERIAL))

    def test_occupied_destination_without_displaced_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal_path, _, _, _ = build_occupied_link(tmp, depth=0, displaced=None)
            with self.subTest(check="direct"):
                with self.assertRaisesRegex(ReconcileError, "no displaced occupant"):
                    verify_legacy_journal(journal_path)
            with self.subTest(check="dispatcher"):
                with self.assertRaisesRegex(ReconcileError, "no displaced occupant"):
                    verify_journal(journal_path)

    def test_displaced_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal_path, _, _, _ = build_occupied_link(tmp, displaced=MISMATCHED_SERIAL)
            with self.subTest(check="direct"):
                with self.assertRaisesRegex(ReconcileError, "observed singleton occupant"):
                    verify_legacy_journal(journal_path)
            with self.subTest(check="dispatcher"):
                with self.assertRaisesRegex(ReconcileError, "observed singleton occupant"):
                    verify_journal(journal_path)


if __name__ == "__main__":
    unittest.main()
