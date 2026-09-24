"""Phase 4: differential matrix scaffolding stays empty/red (TDD).

Enumerates all 38 ledger areas x workflow/negative-path slots and proves
no differential acceptance is claimed yet. This is the honest starting
point for the fresh-wheel + differential harness; flipping any slot to
accepted requires independent original-Toolkit evidence in a later phase.
"""
from __future__ import annotations

import unittest

from cbus_toolkit import differential


class DifferentialMatrixTests(unittest.TestCase):
    def test_ledger_has_38_areas_and_census_incomplete(self):
        ledger = differential.load_ledger()
        self.assertEqual(len(ledger["features"]), 38)
        self.assertFalse(ledger["census_complete"])

    def test_matrix_enumerates_every_ledger_area(self):
        ledger = differential.load_ledger()
        matrix = differential.build_matrix(ledger)
        self.assertEqual(matrix["ledger_areas"], 38)
        self.assertEqual(set(matrix["areas"]), set(differential.ledger_area_ids(ledger)))

    def test_matrix_starts_empty_red(self):
        matrix = differential.build_matrix()
        self.assertFalse(matrix["complete"])
        self.assertEqual(matrix["accepted_areas"], 0)
        self.assertFalse(matrix["census_complete"])
        for area_id, entry in matrix["areas"].items():
            with self.subTest(area=area_id):
                self.assertEqual(entry["differential_status"], "pending")
                self.assertEqual(entry["evidence_paths"], [])
                for slot in differential.WORKFLOW_SLOTS:
                    self.assertEqual(entry["workflows"][slot], "unassessed")
                for slot in differential.NEGATIVE_SLOTS:
                    self.assertEqual(entry["negative_paths"][slot], "unassessed")

    def test_per_area_status_and_evidence_paths(self):
        matrix = differential.build_matrix()
        for area_id in differential.ledger_area_ids(differential.load_ledger()):
            with self.subTest(area=area_id):
                status = differential.area_status(matrix, area_id)
                self.assertEqual(status["ledger_id"], area_id)
                self.assertEqual(differential.evidence_paths_for(matrix, area_id), [])
        with self.assertRaises(KeyError):
            differential.area_status(matrix, "no-such-area")

    def test_summary_reports_incomplete(self):
        summary = differential.summary(differential.build_matrix())
        self.assertEqual(summary["ledger_areas"], 38)
        self.assertEqual(summary["accepted_areas"], 0)
        self.assertFalse(summary["complete"])
        self.assertFalse(summary["census_complete"])

    def test_pending_acceptance_ids_remain_pending(self):
        matrix = differential.build_matrix()
        for area_id in ("toolkit-differential-acceptance", "unit-hardware-acceptance"):
            with self.subTest(area=area_id):
                self.assertEqual(matrix["areas"][area_id]["ledger_status"], "pending")
                self.assertEqual(
                    matrix["areas"][area_id]["differential_status"], "pending"
                )


if __name__ == "__main__":
    unittest.main()
