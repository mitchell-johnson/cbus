"""Bounded SESU rollout comparator; original rows are in the retained fixture."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from cbus_toolkit.toolkit_update_rollout import inspect_rollout_cohort
from tests.test_toolkit_update_applicability import BASE, encode


FIXTURES = Path(__file__).resolve().parents[1] / "research" / "fixtures"


def inspect(visibility=42, cohort="41", *, source=None):
    source = copy.deepcopy(BASE if source is None else source)
    source["data"][0]["data"]["visibilityInPercent"] = visibility
    return inspect_rollout_cohort(
        encode(source), node_id=source["data"][0]["nodeId"], stored_cohort=cohort,
    )


@pytest.mark.parametrize(("visibility", "cohort", "accepted"), [
    (0, "0", False), (1, "0", True), (41, "41", False),
    (42, "41", True), (5, "04", True), (99, "98", True), (99, "99", False),
])
def test_strict_greater_than_under_supplied_stored_cohort(visibility, cohort, accepted):
    report = inspect(visibility, cohort)
    assert report.status == ("passed" if accepted else "failed")
    assert report.gate_under_supplied_cohort is accepted
    assert report.visibility_in_percent == visibility
    assert report.supplied_stored_cohort == int(cohort)
    value = report.as_dict()
    for field in ("metadata_signature_verified", "publisher_trust_evaluated",
                  "certificate_chain_evaluated", "complete_revocation_status_evaluated",
                  "full_machine_applicability_evaluated", "version_comparison_performed",
                  "install_permitted", "network_request_initiated", "registry_accessed",
                  "cohort_generated", "cohort_persisted", "downloaded", "installed"):
        assert value[field] is False
    assert value["updates_available"] is None


def test_exact_source_binding_changes_with_visibility_and_other_selected_fields():
    first = inspect(42, "41")
    changed_visibility = inspect(41, "41")
    assert first.catalogue_source_sha256 != changed_visibility.catalogue_source_sha256
    assert first.selected_node_sha256 != changed_visibility.selected_node_sha256
    assert first.canonical_node_sha256 != changed_visibility.canonical_node_sha256
    source = copy.deepcopy(BASE)
    source["data"][0]["data"]["description"]["default"] = "altered"
    changed_source = inspect(42, "41", source=source)
    assert first.catalogue_source_sha256 != changed_source.catalogue_source_sha256
    assert first.selected_node_sha256 != changed_source.selected_node_sha256
    assert first.canonical_node_sha256 != changed_source.canonical_node_sha256


@pytest.mark.parametrize("cohort", ["", "-1", "+1", " 1", "1 ", "100", "2147483648", "１"])
def test_unmodeled_cohort_text_is_rejected(cohort):
    with pytest.raises(ValueError, match="stored_cohort"):
        inspect(42, cohort)


@pytest.mark.parametrize("cohort", [None, 41, True, 41.0])
def test_nontext_cohort_is_rejected(cohort):
    with pytest.raises(ValueError, match="stored_cohort"):
        inspect(42, cohort)


@pytest.mark.parametrize("visibility", [None, False, 100, -1, 101, "42", 42.0])
def test_unmodeled_visibility_is_unsupported(visibility):
    result = inspect(visibility, "41")
    assert result.status == "unsupported"
    assert result.gate_under_supplied_cohort is None
    assert result.as_dict()["install_permitted"] is False


def test_nonempty_conditions_and_ambiguous_catalogue_are_not_admitted():
    source = copy.deepcopy(BASE)
    source["data"][0]["data"]["clientConditionData"]["conditions"] = {
        "a": {"whatToCheck": "fileExists"},
    }
    assert inspect(source=source).status == "unsupported"
    source = copy.deepcopy(BASE)
    source["data"].append(copy.deepcopy(source["data"][0]))
    with pytest.raises(ValueError, match="exactly one"):
        inspect(source=source)
    source = copy.deepcopy(BASE)
    source["statusCode"] = True
    with pytest.raises(ValueError, match="statusCode"):
        inspect(source=source)
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        inspect_rollout_cohort(
            b'{"success":true,"success":true,"data":[]}',
            node_id="x", stored_cohort="41",
        )


def test_missing_or_untyped_package_model_is_unsupported():
    def from_source(source):
        return inspect_rollout_cohort(
            encode(source), node_id=source["data"][0]["nodeId"], stored_cohort="41",
        )

    source = copy.deepcopy(BASE)
    del source["data"][0]["data"]["visibilityInPercent"]
    assert from_source(source).status == "unsupported"

    source = copy.deepcopy(BASE)
    source["data"][0]["data"]["type"] = "OtherData"
    assert from_source(source).status == "unsupported"

    source = copy.deepcopy(BASE)
    source["data"][0]["data"]["clientConditionData"]["conditions"] = None
    assert from_source(source).status == "unsupported"


def test_original_fixture_identity_and_supported_case_subset():
    path = FIXTURES / "toolkit-update-rollout-cohort-original.json"
    fixture = json.loads(path.read_text())
    assert fixture["sesubrick_dad_sha256"] == "21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c"
    assert fixture["original_helper_token"] == "0x0600012C"
    assert fixture["original_helper_rva"] == "0x5190"
    probe = path.parents[1] / "NativeSesuRolloutProbe.cs"
    assert hashlib.sha256(probe.read_bytes()).hexdigest() == fixture["owned_probe_source_sha256"]
    assert fixture["original_case_count"] == 17
    assert fixture["original_stderr_bytes"] == 0
    assert fixture["default_ipv4_routes_at_capture"] == 0
    assert fixture["default_ipv6_routes_at_capture"] == 0
    for row in fixture["supported_rows"]:
        result = inspect(row["visibility"], row["stored_cohort"])
        assert result.gate_under_supplied_cohort is row["original_return"]
    assert len(fixture["supported_rows"]) == 7
    assert len(fixture["observed_outside_profile"]) == 8
    assert fixture["original_case_count"] == (len(fixture["supported_rows"])
        + len(fixture["observed_outside_profile"]) + 2)
    assert fixture["missing_entry_seed"]["persisted_as_decimal_string"] is True
    assert fixture["stored_minus_one_sentinel"]["initial_value"] == "-1"
    assert fixture["stored_minus_one_sentinel"]["persisted_as_decimal_string"] is True
    assert fixture["owned_registry_key_removed"] is True
