"""A bounded, same-source applicability path through a supplied cohort."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from cbus_toolkit.toolkit_update_applicability import inspect_update_applicability
from tests.test_toolkit_update_applicability import AT, BASE, encode


FIXTURE = (Path(__file__).resolve().parents[1] / "research" / "fixtures" /
           "toolkit-update-applicability-cohort-original.json")


def examine(*, visibility=42, cohort="41", variant=None, source=None):
    source = copy.deepcopy(BASE if source is None else source)
    node = source["data"][0]
    node["data"]["visibilityInPercent"] = visibility
    selected = node["files"][0]["id"]
    if variant == "future-start":
        node["data"]["startDate"] = "2099-01-01T00:00:00Z"
    elif variant == "expired":
        node["data"]["expireDate"] = "2000-01-01T00:00:00Z"
    elif variant == "missing-url":
        node["urls"][selected]["url"] = ""
    elif variant in ("missing-media", "unknown-media"):
        del node["files"][0]["metadata"]["mediatype"]
    elif variant == "no-matching-file":
        node["files"][0]["metadata"]["architecture"] = "windows_x86_32"
    elif variant == "nonempty-conditions":
        node["data"]["clientConditionData"]["conditions"] = {
            "A": {"whatToCheck": "fileExists"},
        }
    else:
        assert variant is None
    return inspect_update_applicability(
        encode(source), node_id=node["nodeId"], platform="windows_x86_64",
        at_utc=AT, stored_cohort=cohort,
    )


@pytest.mark.parametrize(("visibility", "cohort", "passed"), [
    (0, "0", False), (1, "0", True), (41, "41", False), (42, "41", True),
    (99, "98", True), (99, "99", False),
])
def test_original_gate_order_for_valid_empty_condition_profile(visibility, cohort, passed):
    result = examine(visibility=visibility, cohort=cohort)
    assert result.status == ("passed" if passed else "failed")
    assert result.applicable_under_supplied_context is passed
    assert result.rollout_gate_reached is True
    assert result.rollout_gate_under_supplied_cohort is passed
    report = result.as_dict()
    assert report["format"] == "cbus-toolkit-update-applicability-cohort-preflight-v1"
    assert report["checks"]["rollout_gate_reached_under_supplied_context"] is True
    assert report["checks"]["rollout_gate_under_supplied_cohort"] is passed
    assert report["supplied_stored_cohort"] == int(cohort)
    assert report["cohort_provenance"].startswith("caller-supplied")
    for name in ("metadata_signature_verified", "publisher_trust_evaluated",
                 "certificate_chain_evaluated", "complete_revocation_status_evaluated",
                 "package_applicability_evaluated", "version_comparison_performed",
                 "install_permitted", "downloaded", "installed", "registry_accessed",
                 "certificate_store_accessed", "cohort_generated", "cohort_persisted",
                 "full_machine_applicability_evaluated"):
        assert report[name] is False
    assert report["updates_available"] is None


@pytest.mark.parametrize("variant", [
    "future-start", "expired", "missing-url", "missing-media", "no-matching-file",
])
def test_predecessor_failure_does_not_reach_rollout(variant):
    result = examine(variant=variant)
    assert result.status == "failed"
    assert result.rollout_gate_reached is False
    assert result.rollout_gate_under_supplied_cohort is None
    assert result.as_dict()["checks"]["rollout_gate_reached_under_supplied_context"] is False


@pytest.mark.parametrize("cohort", ["", "-1", "+1", " 1", "1 ", "100", "001", "４"])
def test_unmodeled_stored_cohort_rejected(cohort):
    with pytest.raises(ValueError, match="stored_cohort"):
        examine(cohort=cohort)


@pytest.mark.parametrize("cohort", [True, 41, 41.0, b"41"])
def test_nontext_stored_cohort_rejected(cohort):
    with pytest.raises(ValueError, match="stored_cohort"):
        examine(cohort=cohort)


@pytest.mark.parametrize("visibility", [None, False, -1, 100, "42", 42.0])
def test_unmodeled_visibility_is_unsupported(visibility):
    result = examine(visibility=visibility)
    assert result.status == "unsupported"
    assert result.rollout_gate_reached is None
    assert result.as_dict()["install_permitted"] is False


def test_nonempty_conditions_not_composed_and_old_profile_unchanged():
    assert examine(variant="nonempty-conditions").status == "unsupported"
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    old = inspect_update_applicability(
        encode(source), node_id=node["nodeId"], platform="windows_x86_64", at_utc=AT,
    )
    assert old.status == "passed"
    assert old.as_dict()["format"] == "cbus-toolkit-update-applicability-preflight-v1"
    assert "supplied_stored_cohort" not in old.as_dict()
    assert old.as_dict()["checks"]["rollout_bypassed_visibility_100"] is True


def test_unproved_uri_is_unsupported_without_a_rollout_decision():
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    node["urls"][node["files"][0]["id"]]["url"] = "https://bad^host.example/package"
    result = examine(source=source)
    assert result.status == "unsupported"
    assert result.rollout_gate_reached is None
    assert result.rollout_gate_under_supplied_cohort is None
    assert result.as_dict()["install_permitted"] is False


def test_first_selected_empty_url_stops_before_rollout_without_file_fallback():
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    first = node["files"][0]["id"]
    later = copy.deepcopy(node["files"][0])
    later["id"] = "later-file"
    node["files"].append(later)
    node["urls"][first]["url"] = ""
    node["urls"][later["id"]] = {"url": "https://updates.example.invalid/later.exe"}
    result = examine(source=source)
    assert result.selected_file_id == first
    assert result.status == "failed"
    assert result.rollout_gate_reached is False
    assert result.rollout_gate_under_supplied_cohort is None


def test_same_source_receipts_and_ambiguous_input():
    first = examine()
    changed = copy.deepcopy(BASE)
    changed["data"][0]["data"]["description"]["default"] = "changed"
    second = examine(source=changed)
    assert first.catalogue_source_sha256 != second.catalogue_source_sha256
    assert first.selected_node_sha256 != second.selected_node_sha256
    assert first.canonical_node_sha256 != second.canonical_node_sha256
    source = copy.deepcopy(BASE)
    source["data"].append(copy.deepcopy(source["data"][0]))
    with pytest.raises(ValueError, match="exactly one"):
        examine(source=source)
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        inspect_update_applicability(
            b'{"success":true,"success":true,"data":[]}', node_id="x",
            platform="windows_x86_64", at_utc=AT, stored_cohort="41",
        )


def test_original_fixture_matches_admitted_rows():
    fixture = json.loads(FIXTURE.read_text())
    assert fixture["original_method_token"] == "0x0600012B"
    assert fixture["original_rollout_helper_token"] == "0x0600012C"
    assert fixture["sesubrick_dad_sha256"] == "21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c"
    assert fixture["original_method_il_sha256"] == "da89b1a0ad366d6059d25bb9e8da195a5c6f2f61c67844de49bb56e0deb0bc9e"
    probe = FIXTURE.parents[1] / "NativeSesuApplicabilityCohortProbe.cs"
    assert hashlib.sha256(probe.read_bytes()).hexdigest() == fixture["owned_probe_source_sha256"]
    assert fixture["original_case_count"] == 15
    assert fixture["original_stdout_line_count"] == 17
    assert len(fixture["admitted_rows"]) == 10
    assert len(fixture["missing_entry_witnesses_outside_cli"]) == 5
    for case in fixture["admitted_rows"]:
        result = examine(
            visibility=case["visibility"], cohort=case["stored_cohort"],
            variant=case["variant"],
        )
        assert result.applicable_under_supplied_context is case["original_return"]
        assert result.rollout_gate_reached is case["original_rollout_reached"]
    assert [case["decimal_cohort_persisted"] for case in
            fixture["missing_entry_witnesses_outside_cli"]] == [True, False, False, False, False]
    assert fixture["default_ipv4_routes_at_capture"] == 0
    assert fixture["default_ipv6_routes_at_capture"] == 0
    assert fixture["original_stderr_bytes"] == 0
    assert fixture["owned_registry_key_removed"] is True
