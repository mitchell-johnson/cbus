"""Original-captured rollout branches through an owned typed registry port."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cbus_toolkit.toolkit_update_rollout_registry import (
    CohortRegistryRead, inspect_rollout_owned_registry,
)
from tests.test_toolkit_update_applicability import BASE, encode


FIXTURE = (Path(__file__).resolve().parents[1] / "research" / "fixtures" /
           "toolkit-update-rollout-cohort-original.json")


class Registry:
    def __init__(self, read, *, read_error=None, write_error=None):
        self.snapshot = read
        self.read_error = read_error
        self.write_error = write_error
        self.calls = []

    def read(self):
        self.calls.append(("read",))
        if self.read_error:
            raise self.read_error
        return self.snapshot

    def write_decimal(self, value):
        self.calls.append(("write", value))
        if self.write_error:
            raise self.write_error
        self.snapshot = CohortRegistryRead("present", "REG_SZ", value)


def inspect(visibility=42, read=CohortRegistryRead("present", "REG_SZ", "41"),
            *, sample=None, source=None, registry=None):
    source = copy.deepcopy(BASE if source is None else source)
    node = source["data"][0]
    node["data"]["visibilityInPercent"] = visibility
    registry = registry if registry is not None else Registry(read)
    return inspect_rollout_owned_registry(
        encode(source), node_id=node["nodeId"], registry=registry, sample=sample,
    ), registry


def test_source_binding_and_no_registry_touch_on_unsupported_profile():
    first, registry = inspect()
    assert first.status == "passed"
    assert registry.calls == [("read",)]
    changed = copy.deepcopy(BASE)
    changed["data"][0]["data"]["description"]["default"] = "changed"
    second, _ = inspect(source=changed)
    assert first.catalogue_source_sha256 != second.catalogue_source_sha256
    assert first.selected_node_sha256 != second.selected_node_sha256
    assert first.canonical_node_sha256 != second.canonical_node_sha256
    third, registry = inspect(100)
    assert third.status == "unsupported" and registry.calls == []
    assert third.as_dict()["registry_accessed"] is False


def test_original_stored_rows_and_direct_helper_exclusion():
    fixture = json.loads(FIXTURE.read_text())
    assert fixture["original_case_count"] == 17
    assert fixture["original_helper_token"] == "0x0600012C"
    assert fixture["original_helper_il_sha256"] == (
        "f6dd553c61e7af5a6d216422a6040102de46330e1bc7dad3dc7259f25bfead56")
    assert fixture["owned_registry_key_removed"] is True
    for row in fixture["supported_rows"]:
        result, registry = inspect(row["visibility"],
                                   CohortRegistryRead("present", "REG_SZ", row["stored_cohort"]))
        assert result.gate is row["original_return"], row["case"]
        assert registry.calls == [("read",)]
        assert result.effective_cohort == int(row["stored_cohort"])
    for row in fixture["observed_outside_profile"]:
        if row["case"] == "key-absent":
            read = CohortRegistryRead("key_absent")
        elif row["case"] == "dword-cohort":
            read = CohortRegistryRead("present", "REG_DWORD", row["stored_cohort"])
        else:
            read = CohortRegistryRead("present", "REG_SZ", row["stored_cohort"])
        result, registry = inspect(row["visibility"], read)
        if row["visibility"] == 100:
            assert result.status == "unsupported" and registry.calls == []
        else:
            assert result.gate is row["original_return"], row["case"]
            assert registry.calls == [("read",)]


@pytest.mark.parametrize("read", [
    CohortRegistryRead("entry_absent"),
    CohortRegistryRead("present", "REG_SZ", "-1"),
])
def test_missing_and_literal_sentinel_sample_persist_then_compare(read):
    registry = Registry(read)
    samples = []

    def sample():
        samples.append(87)
        return 87

    first, _ = inspect(0, registry=registry, sample=sample)
    assert first.gate is False
    assert first.sample_attempted and first.cohort_generated
    assert first.write_attempted and first.cohort_persisted
    assert first.effective_cohort == 87
    assert registry.calls == [("read",), ("write", "87")]
    assert samples == [87]
    second, _ = inspect(88, registry=registry, sample=sample)
    assert second.gate is True
    assert second.cohort_generated is False and second.cohort_persisted is False
    assert registry.calls[-1] == ("read",)
    assert samples == [87]


def test_read_sample_and_write_failures_are_indeterminate_and_do_not_claim_trust():
    for registry, sample, error_type, sample_attempted, generated, write_attempted in [
        (Registry(CohortRegistryRead("entry_absent"), read_error=PermissionError()), None,
         "PermissionError", False, False, False),
        (Registry(CohortRegistryRead("entry_absent")), lambda: (_ for _ in ()).throw(RuntimeError()),
         "RuntimeError", True, False, False),
        (Registry(CohortRegistryRead("entry_absent"), write_error=OSError()), lambda: 87,
         "OSError", True, True, True),
    ]:
        decision, _ = inspect(registry=registry, sample=sample)
        receipt = decision.as_dict()
        assert decision.status == "unsupported"
        assert decision.gate is None
        assert receipt["registry_error_type"] == error_type
        assert receipt["sample_attempted"] is sample_attempted
        assert receipt["cohort_generated"] is generated
        assert receipt["write_attempted"] is write_attempted
        assert receipt["cohort_persisted"] is (None if write_attempted else False)
        assert receipt["write_outcome_uncertain"] is write_attempted
        assert receipt["install_permitted"] is False
        assert receipt["updates_available"] is None
        assert receipt["original_updater_registry_identity_verified"] is False
        assert receipt["registry_provider_identity_verified"] is False
        assert receipt["durable_persistence_verified"] is False


def test_commit_then_raise_keeps_persistence_unknown_and_never_retries():
    class CommitThenRaise(Registry):
        def write_decimal(self, value):
            self.calls.append(("write", value))
            self.snapshot = CohortRegistryRead("present", "REG_SZ", value)
            raise OSError("close failed after commit")

    registry = CommitThenRaise(CohortRegistryRead("entry_absent"))
    decision, _ = inspect(registry=registry, sample=lambda: 87)
    receipt = decision.as_dict()
    assert registry.snapshot == CohortRegistryRead("present", "REG_SZ", "87")
    assert registry.calls == [("read",), ("write", "87")]
    assert decision.status == "unsupported" and decision.gate is None
    assert receipt["cohort_persisted"] is None
    assert receipt["write_outcome_uncertain"] is True
    assert "may have committed" in receipt["cohort_persistence_basis"]


@pytest.mark.parametrize("invalid", [None, object()])
def test_untyped_provider_response_is_fail_closed_and_serializable(invalid):
    decision, registry = inspect(registry=Registry(invalid))
    assert registry.calls == [("read",)]
    assert decision.status == "unsupported"
    assert decision.as_dict()["registry_read"] is None
    assert decision.as_dict()["registry_accessed"] is True
    json.dumps(decision.as_dict())


@pytest.mark.parametrize("sample", [-1, 100, True, 41.0, "41"])
def test_invalid_sample_is_not_persisted(sample):
    decision, registry = inspect(read=CohortRegistryRead("entry_absent"),
                                 sample=lambda: sample)
    assert decision.status == "unsupported"
    assert decision.sample_attempted and not decision.cohort_generated
    assert not decision.write_attempted and not decision.cohort_persisted
    assert registry.calls == [("read",)]


@pytest.mark.parametrize("read,status", [
    (CohortRegistryRead("present", "REG_SZ", "2147483648"), "failed"),
    (CohortRegistryRead("present", "REG_SZ", "bad"), "failed"),
    (CohortRegistryRead("present", "REG_SZ", "４１"), "unsupported"),
    (CohortRegistryRead("present", "REG_EXPAND_SZ", "41"), "unsupported"),
    (CohortRegistryRead("present", "REG_DWORD", 0xffffffff), "unsupported"),
    (CohortRegistryRead("present", "REG_DWORD", 0x100000000), "unsupported"),
    (CohortRegistryRead("entry_absent", "REG_SZ", "41"), "unsupported"),
])
def test_typed_and_malformed_storage_branches(read, status):
    decision, registry = inspect(read=read)
    assert decision.status == status
    assert registry.calls == [("read",)]
    assert decision.as_dict()["registry_read"] == {
        "state": read.state, "kind": read.kind,
        "value": None if read.value == "４１" else read.value,
    }
