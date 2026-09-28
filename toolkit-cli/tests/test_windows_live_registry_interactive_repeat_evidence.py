"""Keep the bounded Windows CLI acceptance tied to its sanitized raw result."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research/experiments/2026-09-28"
RECEIPT = EVIDENCE / "live-registry-cli-interactive-repeat.json"
RAW_REDACTED = EVIDENCE / "live-registry-cli-interactive-repeat-redacted.json"


def test_interactive_repeat_receipt_binds_two_distinct_clean_workers():
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    raw_bytes = RAW_REDACTED.read_bytes()
    raw = json.loads(raw_bytes)
    native = receipt["native_case"]

    assert receipt["format"] == "cbus-p902-live-condition-cli-interactive-repeat-acceptance-v1"
    assert receipt["status"] == "passed_bounded_interactive_cli"
    assert native["raw_result_redacted_file"] == RAW_REDACTED.name
    assert native["raw_result_redacted_sha256"] == sha256(raw_bytes).hexdigest()
    assert native["cli_exit_code"] == 0
    assert native["native_harness_exit_code"] == 1
    assert "evidence_export" in native["native_harness_false_negative"]
    assert native["ordered_results"] == [True, False]
    assert native["ordered_caches"] == [{"a": True}, {"a": False}]
    assert native["ordered_registry_values"] == [0, 1]
    assert native["second_evaluation_attempted"] is True
    assert len(set(native["two_distinct_worker_directories"])) == 2
    assert len(set(native["two_distinct_worker_pids"])) == 2
    for key in ("two_verified_sid_guards", "worker_compiler_and_input_hash_cleanup_stages_passed",
                "worker_process_absent_after_cleanup", "owned_registry_key_absent_after_cleanup"):
        assert native[key] is True

    assert raw["repeated_evaluation"] is True
    assert raw["second_evaluation_attempted"] is True
    assert raw["evaluation_completed"] is True
    assert raw["condition_result"] is False
    assert raw["condition_result_cache"] == {"a": False}
    passes = raw["evaluation_passes"]
    assert len(passes) == 2
    assert [item["condition_result"] for item in passes] == [True, False]
    assert [item["condition_result_cache"] for item in passes] == [{"a": True}, {"a": False}]
    workers = []
    redacted_sids = []
    for item in passes:
        assert item["evaluation_completed"] is True
        assert item["observer_closed"] is True
        evidence = item["observer_evidence"]
        assert evidence["closed"] is True
        assert evidence["registry_writes_performed"] is False
        assert evidence["network_accessed"] is False
        guards = evidence["user_context"]
        assert guards["process_token_user_verified"] is True
        assert guards["sid_requirement_satisfied"] is True
        assert guards["interactive_user_context_verified"] is False
        sid = guards["expected_user_sid"]
        assert sid.startswith("[user-sid-sha256:") and sid.endswith("]")
        assert guards["observed_user_sid"] == sid == guards["process_token_user_sid"]
        redacted_sids.append(sid)
        workers.append(evidence["provider_proof"]["worker_pid"])
        stages = evidence["cleanup"]
        assert [(row["stage"], row["status"]) for row in stages[:-1]][:3] == [
            ("finish", "passed"), ("worker_reaped", "passed"),
            ("compiler_reaped", "passed")]
        assert stages[-1] == {"stage": "evidence_export", "status": "started"}
    assert len(set(workers)) == 2
    assert len(set(redacted_sids)) == 1
    assert [item["registry_observations"][0]["result"]["value"] for item in passes] == [0, 1]


def test_indeterminate_vm_attempt_is_not_counted_as_acceptance():
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    attempts = receipt["other_attempts"]
    assert [attempt["result"] for attempt in attempts] == [
        "pre_query_rejection", "indeterminate_vm_freeze"]
    assert attempts[0]["run_id"] != receipt["native_case"]["run_id"]
    assert attempts[1]["run_id"] != receipt["native_case"]["run_id"]
