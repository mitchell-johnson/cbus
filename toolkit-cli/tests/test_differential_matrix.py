"""Phase 4+: differential matrix with rubric + five attempted rows (TDD).

Enumerates all 38 ledger areas x workflow/negative-path slots and proves
the exact differential state: only ``edlt-reset-controls`` /
``nominal_workflow``, ``edlt-retained-scene-editing`` /
``nominal_workflow``, and ``edlt-global-category-programming`` /
``nominal_workflow`` are accepted (per the executable rubric in
``cbus_toolkit.differential``); the fourth attempted row
``thermostat-configuration`` and the fifth attempted row
``all-unit-parameter-encoding`` stay 0/6 (all slots ``unassessed``); every
other slot stays ``unassessed``, ``accepted_areas`` stays 0 (area rule
requires all six slots), and ``complete`` stays false. Flipping any
further slot requires independent original-Toolkit evidence satisfying
the rubric.
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

    def test_matrix_holds_exact_five_row_state(self):
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
                elif area_id == "edlt-global-category-programming":
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
                        list(differential.GLOBAL_PROGRAMMING_EVIDENCE_PATHS),
                    )
                elif area_id == "thermostat-configuration":
                    # Fourth attempted row: audited 0/6. All six slots stay
                    # unassessed; the evidence paths record the audit trail.
                    self.assertEqual(entry["differential_status"], "pending")
                    for slot in differential.WORKFLOW_SLOTS:
                        self.assertEqual(entry["workflows"][slot], "unassessed")
                    for slot in differential.NEGATIVE_SLOTS:
                        self.assertEqual(
                            entry["negative_paths"][slot], "unassessed"
                        )
                    self.assertEqual(
                        entry["evidence_paths"],
                        list(
                            differential.THERMOSTAT_CONFIGURATION_EVIDENCE_PATHS
                        ),
                    )
                elif area_id == "all-unit-parameter-encoding":
                    # Fifth attempted row: audited 0/6 (native-oracle
                    # evidence-kind finding). All six slots stay
                    # unassessed; the evidence paths record the audit trail.
                    self.assertEqual(entry["differential_status"], "pending")
                    for slot in differential.WORKFLOW_SLOTS:
                        self.assertEqual(entry["workflows"][slot], "unassessed")
                    for slot in differential.NEGATIVE_SLOTS:
                        self.assertEqual(
                            entry["negative_paths"][slot], "unassessed"
                        )
                    self.assertEqual(
                        entry["evidence_paths"],
                        list(
                            differential.ALL_UNIT_PARAMETER_ENCODING_EVIDENCE_PATHS
                        ),
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

    def test_rubric_accepts_only_three_nominal_slots(self):
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
        for slot in differential.ALL_SLOTS:
            with self.subTest(slot=slot):
                accepted, reason = differential.slot_meets_rubric(
                    slot, dict(differential.GLOBAL_PROGRAMMING_EVIDENCE)
                )
                self.assertTrue(reason)
                if slot == "nominal_workflow":
                    self.assertTrue(accepted, reason)
                else:
                    self.assertFalse(accepted, reason)
        # Fourth attempted row: the rubric rejects every slot (0/6).
        for slot in differential.ALL_SLOTS:
            with self.subTest(slot=slot):
                accepted, reason = differential.slot_meets_rubric(
                    slot, dict(differential.THERMOSTAT_CONFIGURATION_EVIDENCE)
                )
                self.assertTrue(reason)
                self.assertFalse(accepted, reason)
        # Fifth attempted row: the rubric rejects every slot (0/6) --
        # zero original-Toolkit executions despite native-oracle scale.
        for slot in differential.ALL_SLOTS:
            with self.subTest(slot=slot):
                accepted, reason = differential.slot_meets_rubric(
                    slot,
                    dict(differential.ALL_UNIT_PARAMETER_ENCODING_EVIDENCE),
                )
                self.assertTrue(reason)
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
        self.assertFalse(
            differential.is_area_accepted(
                matrix["areas"]["edlt-global-category-programming"]
            )
        )
        self.assertFalse(
            differential.is_area_accepted(
                matrix["areas"]["thermostat-configuration"]
            )
        )
        self.assertFalse(
            differential.is_area_accepted(
                matrix["areas"]["all-unit-parameter-encoding"]
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
        self.assertEqual(
            differential.evidence_paths_for(
                matrix, "edlt-global-category-programming"
            ),
            list(differential.GLOBAL_PROGRAMMING_EVIDENCE_PATHS),
        )
        self.assertEqual(
            differential.evidence_paths_for(
                matrix, "thermostat-configuration"
            ),
            list(differential.THERMOSTAT_CONFIGURATION_EVIDENCE_PATHS),
        )
        self.assertEqual(
            differential.evidence_paths_for(
                matrix, "all-unit-parameter-encoding"
            ),
            list(differential.ALL_UNIT_PARAMETER_ENCODING_EVIDENCE_PATHS),
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

    def test_global_programming_evidence_constants_match_committed_fixtures_offline(self):
        # Row 3 (OFFLINE, no vendor spec/bridge): the hardcoded evidence
        # constants must match the committed fixtures.
        vectors = json.loads(
            (
                ROOT / "research/fixtures/edlt-global-programming-vectors.json"
            ).read_text(encoding="utf-8")
        )
        acceptance = json.loads(
            (
                ROOT
                / "research/fixtures/edlt-global-programming-acceptance.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(vectors["format"], "cbus-edlt-global-original-vectors-v1")
        self.assertEqual(len(vectors["parameters"]), 874)
        self.assertEqual(len(vectors["sources"]), 2)
        for row in vectors["sources"]:
            self.assertEqual(len(row["masks"]), 16)
            self.assertEqual(
                [case["mask"] for case in row["masks"]], list(range(16))
            )
        self.assertEqual(len(vectors["reversed_order"]), 2)
        self.assertEqual(len(vectors["sequential"]), 2)
        self.assertEqual(len(vectors["negative_results"]), 7)
        scope = vectors["scope"]
        self.assertIs(scope["original_model_category_path"], True)
        self.assertIs(scope["original_full_form"], False)
        self.assertIs(scope["source_project_setter_executed"], False)
        self.assertIs(scope["physical_device_verified"], False)
        fixed = acceptance["fixed_original_vectors"]
        self.assertEqual(fixed["parameters_per_source_snapshot"], 874)
        self.assertEqual(fixed["masks"], 16)
        self.assertEqual(fixed["source_contexts"], 2)
        self.assertEqual(fixed["matrix_vectors"], 32)
        self.assertEqual(fixed["reverse_input_order_vectors"], 2)
        self.assertEqual(fixed["retained_same_model_sequential_payloads"], 2)
        self.assertIs(fixed["original_negative_results_preserved"], True)
        historical = acceptance["historical_research"]
        self.assertEqual(historical["original_matrix"]["cases"], 40)
        self.assertEqual(
            historical["prior_native_total_verified_transactions"], 74
        )
        for run in acceptance["tests"]:
            self.assertEqual(run["tests"], 28)
            self.assertEqual(run["skips"], 0)
            self.assertEqual(run["native_module_cases"], 35)
            self.assertEqual(run["native_module_targets_saved_closed_loaded"], 36)
            self.assertEqual(run["native_cli_targets_saved_closed_loaded"], 2)
            self.assertEqual(run["full_parameters_verified_per_target"], 874)
            self.assertEqual(
                run["logical_shared_bitfield_raw_bytes_verified_per_target"],
                39,
            )
            self.assertEqual(run["crc_raw_bytes_verified_per_target"], 10)
        self.assertIs(acceptance["physical_device_verified"], False)
        self.assertIs(acceptance["destination_full_crc_validity_verified"], False)
        self.assertIs(acceptance["export_is_review_only"], True)
        evidence = differential.GLOBAL_PROGRAMMING_EVIDENCE
        self.assertEqual(evidence["original_executions"], 32)
        self.assertEqual(evidence["matrix_vectors"], 32)
        self.assertEqual(evidence["reverse_vectors"], 2)
        self.assertEqual(evidence["sequential_payloads"], 2)
        self.assertEqual(evidence["native_module_targets"], 36)
        self.assertEqual(evidence["native_cli_targets"], 2)


    def test_thermostat_evidence_constants_match_committed_fixtures_offline(self):
        # Row 4 (OFFLINE, no vendor spec/bridge): the hardcoded evidence
        # constants must match the committed fixtures. Verdict is 0/6, so
        # this pins the audit numbers, not a flip.
        temp_vectors = json.loads(
            (
                ROOT / "research/fixtures/thermostat-temperature-vectors.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(len(temp_vectors["methods"]), 14)
        self.assertEqual(len(temp_vectors["extended_original_emulator"]), 28840)
        self.assertEqual(len(temp_vectors["native_windows_original"]), 1176)
        self.assertEqual(
            temp_vectors["source_reports"]["emulator"]["cases"], 28840
        )
        self.assertEqual(
            temp_vectors["source_reports"]["Windows"]["pilot_cases"], 28
        )
        self.assertEqual(
            temp_vectors["source_reports"]["Windows"]["full_cases"], 1176
        )
        temp_acceptance = json.loads(
            (
                ROOT
                / "research/fixtures/thermostat-temperature-acceptance.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(temp_acceptance["original_methods"], 14)
        self.assertEqual(
            temp_acceptance["fresh_original_cases_per_python"], 28840
        )
        temp_native = json.loads(
            (
                ROOT
                / "research/fixtures/thermostat-temperature-native-acceptance.json"
            ).read_text(encoding="utf-8")
        )
        phases = {phase["phase"]: phase for phase in temp_native["phases"]}
        self.assertEqual(phases["pilot"]["cases"], 28)
        self.assertEqual(phases["full"]["cases"], 1176)
        self.assertIn("No full thermostat form", temp_acceptance["scope"])
        self.assertIn("database save/load", temp_acceptance["scope"])
        levels_vectors = json.loads(
            (
                ROOT
                / "research/fixtures/thermostat-schedule-levels-vectors.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(len(levels_vectors["cases"]), 14)
        levels_acceptance = json.loads(
            (
                ROOT
                / "research/fixtures/thermostat-schedule-levels-acceptance.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            levels_acceptance["tests"]["313"][
                "captured_original_cases_compared"
            ],
            14,
        )
        self.assertEqual(
            levels_acceptance["tests"]["313"]["fresh_original_executions"],
            0,
        )
        self.assertIs(
            levels_acceptance["tests"]["313"][
                "native_storage_or_vm_called"
            ],
            False,
        )
        selection_vectors = json.loads(
            (
                ROOT
                / "research/fixtures/thermostat-scheduling-selection-vectors.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(selection_vectors["original_cases"], 12)
        self.assertEqual(len(selection_vectors["cases"]), 12)
        outer_vectors = json.loads(
            (
                ROOT
                / "research/fixtures/thermostat-scheduling-outer-vectors.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(len(outer_vectors["cases"]), 12)
        unit_load_vectors = json.loads(
            (
                ROOT
                / "research/fixtures/thermostat-unit-load-original-vectors.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(len(unit_load_vectors), 12)
        self.assertEqual(
            [case["id"] for case in unit_load_vectors],
            [f"L{i:02}" for i in range(1, 13)],
        )
        unit_load_original = json.loads(
            (
                ROOT
                / "research/experiments/2026-09-24/thermostat-unit-load-original.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(unit_load_original["cases"], 12)
        self.assertEqual(
            unit_load_original["original_instruction_entries"], 71832
        )
        composition_acceptance = json.loads(
            (
                ROOT
                / "research/experiments/2026-09-24/thermostat-native-composition-acceptance.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(composition_acceptance["tests_run"], 2)
        for case in composition_acceptance["cases"]:
            self.assertEqual(case["target_project_save_count"], 1)
        self.assertIn(
            "native collection-order equivalence",
            " ".join(composition_acceptance["not_claimed"]),
        )
        composition_review = json.loads(
            (
                ROOT
                / "research/experiments/2026-09-24/thermostat-native-composition-review.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(composition_review["composition_tests"]["tests"], 14)
        self.assertIs(
            composition_review["evidence_boundaries"][
                "new_original_instruction_execution"
            ],
            False,
        )
        evidence = differential.THERMOSTAT_CONFIGURATION_EVIDENCE
        self.assertEqual(evidence["original_executions"], 28840)
        self.assertEqual(evidence["original_methods"], 14)
        self.assertEqual(evidence["native_windows_pilot_cases"], 28)
        self.assertEqual(evidence["native_windows_full_cases"], 1176)
        self.assertEqual(evidence["captured_inner_outcomes"], 14)
        self.assertEqual(evidence["predicate_captures"], 12)
        self.assertEqual(evidence["outer_workflow_captures"], 12)
        self.assertEqual(evidence["afterload_outcomes"], 12)
        self.assertEqual(evidence["afterload_instruction_entries"], 71832)
        self.assertEqual(evidence["composition_native_tests"], 2)
        self.assertEqual(evidence["composition_target_saves_per_case"], 1)
        # Row-level rubric flags stay False: no single bounded scope has
        # both the >=10-original leg and the native-persistence leg.
        self.assertIs(evidence["has_native_persistence"], False)
        self.assertIs(evidence["has_acceptance_record"], False)
        self.assertIs(evidence["has_bounded_scope_note"], False)

    def test_all_unit_parameter_encoding_evidence_constants_match_committed_fixtures_offline(self):
        # Row 5 (OFFLINE, no vendor spec/bridge): the hardcoded evidence
        # constants must match the committed fixtures. Verdict is 0/6, so
        # this pins the audit numbers, not a flip. The numbers below are
        # native-oracle comparisons (our codec vs native C-Gate), NOT
        # original-Toolkit executions -- hence original_executions 0.
        catalog = json.loads(
            (ROOT / "docs/catalog-acceptance-summary.json").read_text(
                encoding="utf-8"
            )
        )
        combined = catalog["combined_boundary_workflows"]
        self.assertEqual(combined["selected"], 6497)
        self.assertEqual(combined["verified_cases"], 6487)
        self.assertEqual(combined["excluded_cases"], 10)
        self.assertEqual(combined["successful_parameter_comparisons"], 616722)
        workflow = catalog["boundary_workflow"]
        self.assertEqual(workflow["selected"], 6497)
        self.assertEqual(workflow["completed"], 6497)
        self.assertEqual(workflow["not_run"], 0)
        self.assertEqual(workflow["status_counts"]["pass"], 6382)
        self.assertEqual(
            workflow["status_counts"]["vendor_catalog_rejected"], 105
        )
        self.assertEqual(
            workflow["status_counts"]["vendor_command_limitation"], 10
        )
        self.assertEqual(
            workflow["status_counts"]["pass"]
            + workflow["status_counts"]["vendor_catalog_rejected"],
            6487,
        )
        self.assertEqual(
            workflow["status_counts"]["pass"]
            + workflow["status_counts"]["vendor_catalog_rejected"]
            + workflow["status_counts"]["vendor_command_limitation"],
            6497,
        )
        self.assertEqual(workflow["successful_parameter_comparisons"], 552391)
        alternative = catalog["boundary_alternative_database_load"]
        self.assertEqual(
            alternative["successful_alternative_parameter_comparisons"], 64331
        )
        self.assertEqual(
            workflow["successful_parameter_comparisons"]
            + alternative["successful_alternative_parameter_comparisons"],
            616722,
        )
        self.assertIn("all Toolkit workflows", catalog["does_not_establish"])
        memory = json.loads(
            (ROOT / "docs/native-memory-acceptance.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(memory["format"], "cbus-native-memory-acceptance-v1")
        self.assertEqual(memory["distinct_layouts"], 163)
        self.assertEqual(len(memory["cases"]), 163)
        self.assertEqual(memory["summary"]["pass"], 161)
        self.assertEqual(memory["summary"]["unexercised"], 2)
        self.assertEqual(memory["summary"]["passing_change_trials"], 322)
        self.assertIn("Toolkit workflow parity", memory["scope"])
        evidence = differential.ALL_UNIT_PARAMETER_ENCODING_EVIDENCE
        self.assertEqual(evidence["original_executions"], 0)
        self.assertEqual(evidence["boundary_selected"], 6497)
        self.assertEqual(evidence["boundary_verified"], 6487)
        self.assertEqual(evidence["boundary_pass"], 6382)
        self.assertEqual(evidence["vendor_catalog_rejected"], 105)
        self.assertEqual(evidence["vendor_command_limitation"], 10)
        self.assertEqual(evidence["successful_parameter_comparisons"], 616722)
        self.assertEqual(evidence["boundary_workflow_comparisons"], 552391)
        self.assertEqual(evidence["boundary_alternative_comparisons"], 64331)
        self.assertEqual(evidence["distinct_layouts"], 163)
        self.assertEqual(evidence["layouts_pass"], 161)
        self.assertEqual(evidence["layouts_unexercised"], 2)
        self.assertEqual(evidence["passing_change_trials"], 322)
        # Native-oracle scale with zero original-Toolkit executions: the
        # rubric's nominal gate reports the executions leg missing first.
        self.assertIs(evidence["has_replay_test"], False)
        self.assertIs(evidence["has_native_persistence"], False)
        self.assertIs(evidence["has_acceptance_record"], True)
        self.assertIs(evidence["has_bounded_scope_note"], True)
        self.assertEqual(evidence["original_error_cases"], 0)
        self.assertEqual(evidence["distinct_profiles"], 0)


if __name__ == "__main__":
    unittest.main()
