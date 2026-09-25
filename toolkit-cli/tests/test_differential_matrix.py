"""Phase 4+: differential matrix with rubric + two attempted rows (TDD).

Enumerates all 38 ledger areas x workflow/negative-path slots and proves
the exact differential state: only ``edlt-reset-controls`` /
``nominal_workflow`` and ``edlt-retained-scene-editing`` /
``nominal_workflow`` are accepted (per the executable rubric in
``cbus_toolkit.differential``); every other slot stays ``unassessed``,
``accepted_areas`` stays 0 (area rule requires all six slots), and
``complete`` stays false. Flipping any further slot requires independent
original-Toolkit evidence satisfying the rubric.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from cbus_toolkit import differential

ROOT = Path(__file__).resolve().parents[1]


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

    def test_matrix_holds_exact_two_row_state(self):
        matrix = differential.build_matrix()
        self.assertFalse(matrix["complete"])
        self.assertEqual(matrix["accepted_areas"], 0)
        self.assertFalse(matrix["census_complete"])
        for area_id, entry in matrix["areas"].items():
            with self.subTest(area=area_id):
                if area_id == "edlt-reset-controls":
                    self.assertEqual(entry["differential_status"], "pending")
                    self.assertEqual(
                        entry["workflows"]["nominal_workflow"],
                        differential.ACCEPTED,
                    )
                    self.assertEqual(
                        entry["workflows"]["error_path"], "unassessed"
                    )
                    self.assertEqual(
                        entry["workflows"]["device_firmware_variation"],
                        "unassessed",
                    )
                    for slot in differential.NEGATIVE_SLOTS:
                        self.assertEqual(
                            entry["negative_paths"][slot], "unassessed"
                        )
                    self.assertEqual(
                        entry["evidence_paths"],
                        list(differential.RESET_CONTROLS_EVIDENCE_PATHS),
                    )
                elif area_id == "edlt-retained-scene-editing":
                    self.assertEqual(entry["differential_status"], "pending")
                    self.assertEqual(
                        entry["workflows"]["nominal_workflow"],
                        differential.ACCEPTED,
                    )
                    self.assertEqual(
                        entry["workflows"]["error_path"], "unassessed"
                    )
                    self.assertEqual(
                        entry["workflows"]["device_firmware_variation"],
                        "unassessed",
                    )
                    for slot in differential.NEGATIVE_SLOTS:
                        self.assertEqual(
                            entry["negative_paths"][slot], "unassessed"
                        )
                    self.assertEqual(
                        entry["evidence_paths"],
                        list(differential.SCENE_MANAGER_EVIDENCE_PATHS),
                    )
                else:
                    self.assertEqual(entry["differential_status"], "pending")
                    self.assertEqual(entry["evidence_paths"], [])
                    for slot in differential.WORKFLOW_SLOTS:
                        self.assertEqual(entry["workflows"][slot], "unassessed")
                    for slot in differential.NEGATIVE_SLOTS:
                        self.assertEqual(
                            entry["negative_paths"][slot], "unassessed"
                        )

    def test_rubric_accepts_only_reset_and_scene_manager_nominal(self):
        for slot in differential.ALL_SLOTS:
            with self.subTest(slot=slot):
                accepted, reason = differential.slot_meets_rubric(
                    slot, dict(differential.RESET_CONTROLS_EVIDENCE)
                )
                self.assertTrue(reason)
                if slot == "nominal_workflow":
                    self.assertTrue(accepted, reason)
                else:
                    self.assertFalse(accepted, reason)
        for slot in differential.ALL_SLOTS:
            with self.subTest(slot=slot):
                accepted, reason = differential.slot_meets_rubric(
                    slot, dict(differential.SCENE_MANAGER_EVIDENCE)
                )
                self.assertTrue(reason)
                if slot == "nominal_workflow":
                    self.assertTrue(accepted, reason)
                else:
                    self.assertFalse(accepted, reason)
        with self.assertRaises(KeyError):
            differential.slot_meets_rubric("no-such-slot", {})

    def test_rubric_rejects_empty_evidence(self):
        for slot in differential.ALL_SLOTS:
            with self.subTest(slot=slot):
                accepted, _ = differential.slot_meets_rubric(slot, {})
                self.assertFalse(accepted)

    def test_area_rule_requires_all_six_slots(self):
        matrix = differential.build_matrix()
        self.assertFalse(
            differential.is_area_accepted(
                matrix["areas"]["edlt-reset-controls"]
            )
        )
        self.assertFalse(
            differential.is_area_accepted(
                matrix["areas"]["edlt-retained-scene-editing"]
            )
        )
        accepted_entry = {
            "workflows": dict.fromkeys(
                differential.WORKFLOW_SLOTS, differential.ACCEPTED
            ),
            "negative_paths": dict.fromkeys(
                differential.NEGATIVE_SLOTS, differential.ACCEPTED
            ),
        }
        self.assertTrue(differential.is_area_accepted(accepted_entry))

    def test_per_area_status_and_evidence_paths(self):
        matrix = differential.build_matrix()
        for area_id in differential.ledger_area_ids(differential.load_ledger()):
            with self.subTest(area=area_id):
                status = differential.area_status(matrix, area_id)
                self.assertEqual(status["ledger_id"], area_id)
                self.assertEqual(
                    differential.evidence_paths_for(matrix, area_id),
                    status["evidence_paths"],
                )
        self.assertEqual(
            differential.evidence_paths_for(matrix, "edlt-reset-controls"),
            list(differential.RESET_CONTROLS_EVIDENCE_PATHS),
        )
        self.assertEqual(
            differential.evidence_paths_for(
                matrix, "edlt-retained-scene-editing"
            ),
            list(differential.SCENE_MANAGER_EVIDENCE_PATHS),
        )
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

    def test_reset_evidence_constants_match_committed_fixtures_offline(self):
        # Fix #1 (OFFLINE, no vendor spec/bridge): the hardcoded evidence
        # constants must match the committed fixtures.
        vectors = json.loads(
            (
                ROOT / "research/fixtures/edlt-reset-windows-vectors.json"
            ).read_text(encoding="utf-8")
        )
        acceptance = json.loads(
            (ROOT / "research/fixtures/edlt-reset-acceptance.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(vectors["original_execution_count"], 44)
        self.assertEqual(vectors["all_parameter_phase_count"], 520)
        self.assertEqual(len(vectors["cases"]), 44)
        captured = acceptance["captured_original_vectors"]
        self.assertEqual(captured["executions"], 44)
        self.assertEqual(captured["phases"], 520)
        self.assertEqual(captured["parameter_phase_comparisons"], 454480)
        self.assertEqual(captured["parameter_phase_comparisons"], 520 * 874)
        self.assertIs(acceptance["toolkit_parity_complete"], False)
        self.assertIs(acceptance["physical_device_verified"], False)
        evidence = differential.RESET_CONTROLS_EVIDENCE
        self.assertEqual(evidence["original_executions"], 44)
        self.assertEqual(evidence["phase_count"], 520)
        self.assertEqual(evidence["parameter_phase_comparisons"], 454480)

    def test_scene_manager_evidence_constants_match_committed_fixtures_offline(self):
        # Row 2 (OFFLINE, no vendor spec/bridge): the hardcoded evidence
        # constants must match the committed fixtures.
        vectors = json.loads(
            (
                ROOT / "research/fixtures/edlt-scene-manager-vectors.json"
            ).read_text(encoding="utf-8")
        )
        acceptance = json.loads(
            (
                ROOT / "research/fixtures/edlt-scene-manager-acceptance.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(vectors["format"], "cbus-original-scene-manager-vectors-v1")
        self.assertIs(vectors["physical_device_verified"], False)
        self.assertEqual(len(vectors["cases"]), 34)
        research = acceptance["original_research"]
        self.assertEqual(research["retained_model_cases"], 10)
        self.assertEqual(research["bounded_actual_control_cases"], 3)
        self.assertEqual(research["validation_cases"], 13)
        self.assertEqual(research["getter_and_cache_cases"], 8)
        self.assertEqual(
            research["retained_model_cases"]
            + research["bounded_actual_control_cases"]
            + research["validation_cases"]
            + research["getter_and_cache_cases"],
            len(vectors["cases"]),
        )
        module_runs = [
            run for run in acceptance["runs"] if "original_cases" in run
        ]
        self.assertEqual(len(module_runs), 2)
        for run in module_runs:
            self.assertEqual(run["original_cases"], 17)
            self.assertEqual(run["native_cases"], 8)
        native = acceptance["native"]
        self.assertEqual(native["cases_per_module_run"], 8)
        self.assertEqual(native["full_parameters_compared"], 874)
        self.assertEqual(native["crcs_compared"], 5)
        self.assertTrue(native["each_case_saved_closed_loaded"])
        self.assertIs(acceptance["physical_device_verified"], False)
        evidence = differential.SCENE_MANAGER_EVIDENCE
        self.assertEqual(evidence["original_executions"], 17)
        self.assertEqual(evidence["vector_cases"], 34)
        self.assertEqual(evidence["native_cases"], 8)


if __name__ == "__main__":
    unittest.main()
