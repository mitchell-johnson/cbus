"""Bind the bounded Windows same-instance observation to its checked-in sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/experiments/2026-09-28/preference-original-same-instance-registry32.json"
PRIOR = ROOT / "research/experiments/2026-09-28/preference-interactive-repeat.json"
PROBE = ROOT / "research/windows_preferences_original_same_instance.py"
RECEIPT_SHA256 = "b667846e0a04c3079035ecc563f87e2f4429c4a7f1e937d7db39f81751aac586"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_original_same_instance_receipt_is_source_bound_and_bounded() -> None:
    assert digest(RECEIPT) == RECEIPT_SHA256
    receipt = json.loads(RECEIPT.read_bytes())
    prior = json.loads(PRIOR.read_bytes())
    assert receipt["format"] == "cbus-p902-original-same-instance-registry32-acceptance-v1"
    assert receipt["status"] == "passed_bounded_original_instruction_registry32"
    assert receipt["provenance"]["probe_sha256"] == digest(PROBE)
    assert receipt["python_api_differential"]["existing_interactive_cli_receipt_sha256"] == digest(PRIOR)
    assert receipt["execution"]["launcher_primary_token_sid_sha256"] == prior["guest_runtime"]["launcher_primary_token_sid_sha256"]
    assert receipt["execution"]["same_sid_hash_as_prior_interactive_cli_receipt"] is True
    assert receipt["execution"]["same_manager_object_both_loads"] is True
    assert receipt["execution"]["original_gui_process"] is False
    observation = receipt["observation"]
    assert (observation["initial_in_memory"], observation["first_load_in_memory"],
            observation["second_load_in_memory"]) == (False, False, True)
    assert observation["hkcu_registry32_after_first"] == ["True", 1]
    assert observation["original_selected_case_passed"] is True
    assert receipt["python_api_differential"]["selected_values_and_order_match"] is True
    assert receipt["restoration"]["six_fixed_registry32_trees_snapshotted"] is True
    assert receipt["restoration"]["hkcu_value_trees_restored"] is True
    assert receipt["restoration"]["hklm_value_trees_unchanged"] is True
    assert receipt["restoration"]["private_exports_removed"] is True
