"""Narrow offline pins for P3 issues 28-32 (wave 8).

Each test pins one refusal/scope edge with no bus, PCI, CNI, C-Gate, or
network I/O. Covers routed-WRITE project freshness (#28), commissioning
scope (#29), occupied-address displacement refusal (#30), attempt-lease
contention (#31), and reconcile journal admission (#32).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cbus_toolkit.commissioning_lease import EndpointLease
from cbus_toolkit.commissioning_route import (
    assert_fresh_project,
    project_sha256,
)
from cbus_toolkit.project import ProjectError
from cbus_toolkit.duplicate_resolution import plan_unravel
from cbus_toolkit.serial_commissioning import SerialCommissionPlan
from cbus_toolkit.serial_reconcile import ReconcileError, verify_journal


class P3Wave8PinTests(unittest.TestCase):
    def test_routed_plan_rejects_stale_project_snapshot(self):
        """#28: a mutated project snapshot fails the pre-handoff freshness check."""
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "commissioning.xml"
            snapshot.write_bytes(b"<project/>")
            digest = project_sha256(b"<project/>")
            assert_fresh_project(snapshot, digest)  # unchanged snapshot passes
            snapshot.write_bytes(b"<project-changed/>")
            with self.assertRaisesRegex(ProjectError, "stale or was substituted"):
                assert_fresh_project(snapshot, digest)

    def test_commissioning_scope_requires_source255_and_free_destination(self):
        """#29: scalar commissioning stays gated to source 255 and dest 2..254."""
        self.assertTrue(SerialCommissionPlan._allowed_addresses(255, 6))
        self.assertTrue(SerialCommissionPlan._allowed_addresses(255, 2))
        self.assertTrue(SerialCommissionPlan._allowed_addresses(255, 254))
        self.assertFalse(SerialCommissionPlan._allowed_addresses(255, 255))
        self.assertFalse(SerialCommissionPlan._allowed_addresses(255, 1))
        self.assertFalse(SerialCommissionPlan._allowed_addresses(6, 6))

    def test_unravel_direct_crowded_database_target_is_refused(self):
        """#30: a database target holding several units refuses unambiguously."""
        plan = plan_unravel(
            {20: ["1.1", "1.10"], 6: ["1.2", "1.3"]},
            {20: "1.1", 6: "1.10"},
            selection=[20],
            match_database=True,
        )
        self.assertEqual(plan.moves, ())
        self.assertRegex(plan.refusal, r"holds several units")

    def test_endpoint_lease_second_holder_is_refused_without_io(self):
        """#31: the cooperating-process lease refuses reentry; other endpoints stay free."""
        host = "127.0.0.1"
        with EndpointLease(host, 65001) as lease:
            with self.assertRaisesRegex(RuntimeError, "already held"):
                with lease:
                    pass
            # A different endpoint is a different lock and must still acquire.
            with EndpointLease(host, 65002):
                pass

    def test_reconcile_refuses_unsupported_journal_format(self):
        """#32: reconcile admits only known completed journals, never arbitrary JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "attempt.json"
            journal.write_text(json.dumps({"format": "bogus"}), encoding="utf-8")
            with self.assertRaisesRegex(ReconcileError, "Unsupported selected-serial"):
                verify_journal(journal)


if __name__ == "__main__":
    unittest.main()
