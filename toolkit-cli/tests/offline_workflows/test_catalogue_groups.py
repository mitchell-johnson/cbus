"""Owned synthetic tests for the pure proposed catalogue/Group policies."""
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import socket

import pytest

from cbus_toolkit.offline_workflows.catalogue_groups import (
    CATALOGUE_PROFILE, GROUP_PROFILE, GROUP_ROWS_FORMAT, CatalogueGroupsError,
    CatalogueIndex, GroupDraft, GroupPolicy, GroupRow, parse_group_rows,
    validate_group_draft,
)


def revision(*, default="true", minimum="1.0", maximum="2.9", spec="same.xml", extra=""):
    return (f"<Revision><UnitType>KEYTEST</UnitType><MinVersion>{minimum}</MinVersion>"
            f"<MaxVersion>{maximum}</MaxVersion><IsDefault>{default}</IsDefault>"
            f"<UnitSpecName>{spec}</UnitSpecName>{extra}</Revision>")


def unit(*, number="SAME", revisions=None, addressable="true", hide="false", extra=""):
    revisions = revision() if revisions is None else revisions
    return (f"<Unit><CatalogNumber>{number}</CatalogNumber>"
            "<AlternativeCatalogNumbers>ALT;OTHER*</AlternativeCatalogNumbers>"
            f"<UnitTitle>Family=Wired;Category=Input;HideInCatalog={hide}</UnitTitle>"
            f"<IsAddressable>{addressable}</IsAddressable>"
            f"<FirmwareRevisions>{revisions}</FirmwareRevisions>{extra}</Unit>")


def catalogue(*units):
    return ("<CBusUnits><Units>" + "".join(units) + "</Units></CBusUnits>").encode()


def strict_policy(**overrides):
    return GroupPolicy(**{"allowed_addresses": tuple(range(256)), "capacity": 256,
                          "duplicate_names": "reject-exact", **overrides})


def validate(rows, *, existing=(), **policy):
    return validate_group_draft(GroupDraft(tuple(rows)), existing_groups=tuple(existing),
        policy=strict_policy(**policy), target_identity="//TEST/254/56",
        baseline_sha256=hashlib.sha256(b"owned baseline").hexdigest())


def error_code(call, code):
    with pytest.raises(CatalogueGroupsError) as caught:
        call()
    assert caught.value.code == code


def test_source_identity_includes_hash_unit_path_and_exact_nested_revision():
    data = catalogue(unit(extra="<SubUnits>" + unit() + "</SubUnits>"), unit())
    index = CatalogueIndex.from_bytes(data)
    assert index.snapshot is data
    assert index.sha256 == hashlib.sha256(data).hexdigest()
    assert [item.source_path for item in index.units] == [
        "/CBusUnits/Units[1]/Unit[1]",
        "/CBusUnits/Units[1]/Unit[1]/SubUnits[1]/Unit[1]",
        "/CBusUnits/Units[1]/Unit[2]",
    ]
    identifiers = [item.revisions[0].item_id for item in index.units]
    assert len(set(identifiers)) == 3
    assert all(index.sha256 in identity for identity in identifiers)
    assert all(item.alternative_catalog_numbers == "ALT;OTHER*" for item in index.units)
    changed = CatalogueIndex.from_bytes(data + b" ")
    assert identifiers[0] != changed.units[0].revisions[0].item_id
    error_code(lambda: changed.select_revision(identifiers[0], "1.5", profile=CATALOGUE_PROFILE), "unknown_item")


def test_multiple_revision_containers_have_distinct_source_identities():
    index = CatalogueIndex.from_bytes(catalogue(unit(extra="<FirmwareRevisions>" + revision(default="false") + "</FirmwareRevisions>")))
    records = index.units[0].revisions
    assert [item.revision_index for item in records] == [1, 2]
    assert records[0].item_id != records[1].item_id
    assert "FirmwareRevisions[2]/Revision[1]" in records[1].source_path


def test_explicit_and_default_selection_reuse_numeric_version_contract():
    index = CatalogueIndex.from_bytes(catalogue(unit(revisions=revision(default="false", minimum="1", maximum="1.9") + revision(minimum="2.0", maximum="2.9"))))
    source = index.units[0]
    selected = index.select_revision(source.revisions[0].item_id, "v1.02.00", profile=CATALOGUE_PROFILE)
    assert selected.firmware == "v1.02.00"
    default = index.select_default(source.unit_id, profile=CATALOGUE_PROFILE)
    assert default.firmware == "2.0"
    assert default.revision is source.revisions[1]
    assert default.as_dict()["creation_admitted"] is False
    assert default.as_dict()["default_pp_admitted"] is False
    assert default.as_dict()["native_compatibility_verified"] is False
    error_code(lambda: index.select_revision(source.revisions[0].item_id, "2.0", profile=CATALOGUE_PROFILE), "firmware_out_of_range")
    error_code(lambda: index.select_revision(source.revisions[0].item_id, "unknown", profile=CATALOGUE_PROFILE), "invalid_firmware")
    error_code(lambda: index.select_default(source.unit_id, profile="native"), "unsupported_profile")


@pytest.mark.parametrize("revisions,diagnostic", [
    (revision(default="false"), "missing_default"),
    (revision() + revision(), "multiple_defaults"),
])
def test_missing_multiple_defaults_are_visible_without_first_last_fallback(revisions, diagnostic):
    index = CatalogueIndex.from_bytes(catalogue(unit(revisions=revisions)))
    source = index.units[0]
    assert diagnostic in source.diagnostics
    error_code(lambda: index.select_default(source.unit_id, profile=CATALOGUE_PROFILE), "ambiguous_default")
    assert index.select_revision(source.revisions[0].item_id, "1.5", profile=CATALOGUE_PROFILE).mode == "explicit"


def test_duplicate_default_declaration_and_unknown_default_refuse_default_mode():
    index = CatalogueIndex.from_bytes(catalogue(unit(revisions=revision(extra="<IsDefault>true</IsDefault>"))))
    source = index.units[0]
    assert ("IsDefault", "true") in source.revisions[0].raw_fields
    assert source.revisions[0].raw_fields.count(("IsDefault", "true")) == 2
    assert "ambiguous_IsDefault" in source.revisions[0].diagnostics
    error_code(lambda: index.select_default(source.unit_id, profile=CATALOGUE_PROFILE), "ambiguous_default")
    error_code(lambda: index.select_revision(source.revisions[0].item_id, "1.5", profile=CATALOGUE_PROFILE), "catalogue_ineligible")
    unresolved = CatalogueIndex.from_bytes(catalogue(unit(revisions=revision(default="future"))))
    error_code(lambda: unresolved.select_default(unresolved.units[0].unit_id, profile=CATALOGUE_PROFILE), "ambiguous_default")


@pytest.mark.parametrize("source,diagnostic", [
    (unit(hide="true"), "hidden_in_catalog"),
    (unit(addressable="false"), "non_addressable"),
    (unit(hide="future"), "unresolved_HideInCatalog"),
    (unit().replace(";HideInCatalog=false", ""), "unresolved_HideInCatalog"),
    (unit().replace("<IsAddressable>true</IsAddressable>", ""), "unresolved_IsAddressable"),
    (unit(extra="<CatalogNumber>OTHER</CatalogNumber>"), "ambiguous_CatalogNumber"),
    (unit(extra="<HideInCatalog>false</HideInCatalog>"), "ambiguous_HideInCatalog"),
])
def test_unresolved_and_ineligible_entries_are_inspectable_but_refuse_selection(source, diagnostic):
    index = CatalogueIndex.from_bytes(catalogue(source))
    item = index.units[0]
    assert diagnostic in item.diagnostics
    error_code(lambda: index.select_revision(item.revisions[0].item_id, "1.5", profile=CATALOGUE_PROFILE), "catalogue_ineligible")


@pytest.mark.parametrize("changes,diagnostic", [
    ({"spec": ""}, "missing_UnitSpecName"),
    ({"minimum": ""}, "missing_MinVersion"),
    ({"minimum": "3", "maximum": "1"}, "invalid_firmware_range"),
    ({"minimum": "1..2"}, "invalid_firmware_range"),
    ({"extra": "<UnitSpecName>other.xml</UnitSpecName>"}, "ambiguous_UnitSpecName"),
    ({"extra": "<Future><Nested/></Future>"}, "nested_scalar_Future"),
])
def test_revision_diagnostics_refuse_unsafe_field_collapse(changes, diagnostic):
    index = CatalogueIndex.from_bytes(catalogue(unit(revisions=revision(**changes))))
    item = index.units[0]
    assert diagnostic in item.revisions[0].diagnostics
    error_code(lambda: index.select_revision(item.revisions[0].item_id, "1.5", profile=CATALOGUE_PROFILE), "catalogue_ineligible")


def test_unrevisioned_parent_is_retained_in_inspection():
    index = CatalogueIndex.from_bytes(catalogue(unit(revisions="", extra="<SubUnits>" + unit() + "</SubUnits>")))
    assert len(index.units) == 2
    assert "missing_revisions" in index.units[0].diagnostics
    assert index.units[0].revisions == ()
    assert index.select_default(index.units[1].unit_id, profile=CATALOGUE_PROFILE).unit is index.units[1]


@pytest.mark.parametrize("data,code", [
    (b"<Other/>", "unsupported_catalogue_shape"),
    (b"<CBusUnits xmlns='urn:unknown'><Units/></CBusUnits>", "unsupported_catalogue_shape"),
    (b"<CBusUnits><Units/></CBusUnits>", "invalid_catalogue"),
    (b"<!DOCTYPE CBusUnits [<!ENTITY x 'expanded'>]><CBusUnits/>", "invalid_catalogue"),
    (b"<broken", "invalid_catalogue"),
    ("not bytes", "invalid_catalogue"),
])
def test_catalogue_malformed_or_unknown_shapes_refuse(data, code):
    error_code(lambda: CatalogueIndex.from_bytes(data), code)


def test_snapshot_views_are_defensive_and_models_are_frozen():
    index = CatalogueIndex.from_bytes(catalogue(unit()))
    report = index.as_dict()
    report["units"][0]["raw_fields"].append(("Injected", "value"))
    report["units"][0]["revisions"].clear()
    assert len(index.units[0].revisions) == 1
    assert not any(name == "Injected" for name, _ in index.units[0].raw_fields)
    with pytest.raises(FrozenInstanceError):
        index.sha256 = "changed"
    result = validate([GroupRow("one", 1, "One")])
    result.as_dict()["accepted_rows"][0]["tag_name"] = "changed"
    assert result.rows[0].tag_name == "One"


def test_group_draft_edit_delete_cancel_preserve_rows_and_stable_order():
    original = GroupDraft().add(GroupRow("first", 1, "One")).add(GroupRow("second", "2", "Two"))
    edited = original.edit("first", address="3", tag_name="Three")
    assert [row.row_id for row in edited.rows] == ["first", "second"]
    assert original.rows[0].address == 1
    deleted = edited.delete("second")
    assert deleted.rows == (GroupRow("first", "3", "Three"),)
    cancelled = deleted.cancel()
    assert cancelled.rows == () and cancelled.state == "cancelled"
    error_code(lambda: cancelled.add(GroupRow("new", 4, "New")), "draft_cancelled")
    error_code(lambda: edited.delete("missing"), "unknown_row")
    error_code(lambda: edited.edit("missing", address=1, tag_name="Name"), "unknown_row")
    error_code(lambda: original.add(GroupRow("first", 4, "New")), "duplicate_row_id")


def test_versioned_group_rows_parse_complete_input_without_prefix_or_type_coercion():
    payload = {"format": GROUP_ROWS_FORMAT, "rows": [
        {"row_id": "a", "address": 1, "tag_name": "One"},
        {"row_id": "b", "address": "2", "tag_name": "Two"},
    ]}
    draft = parse_group_rows(json.dumps(payload).encode())
    assert [row.row_id for row in draft.rows] == ["a", "b"]
    error_code(lambda: parse_group_rows(json.dumps(payload).encode() + b" {}"), "invalid_rows")
    payload["rows"][1]["address"] = True
    error_code(lambda: parse_group_rows(json.dumps(payload).encode()), "invalid_rows")
    error_code(lambda: parse_group_rows(b'{"format":"cbus-offline-group-rows-v1","rows":[],"rows":[]}'), "invalid_rows")
    error_code(lambda: parse_group_rows(b"1\tName"), "invalid_rows")
    error_code(lambda: parse_group_rows(b'{"format":"native-paste","rows":[]}'), "unsupported_rows_format")
    payload["rows"][1]["address"] = 2
    payload["rows"][1]["ignored"] = True
    error_code(lambda: parse_group_rows(json.dumps(payload).encode()), "invalid_rows")


def test_all_rows_are_validated_no_prefix_on_later_error_or_alias_collision():
    result = validate([GroupRow("first", 1, "One"), GroupRow("middle", "01", "Two"),
                       GroupRow("last", 3, "Three"), GroupRow("duplicate", "1", "Other")],
                      existing=[GroupRow("existing", "003", "Existing")])
    assert result.errors == (("middle", "invalid_address"),
                             ("last", "existing_address_collision"),
                             ("duplicate", "duplicate_staged_address"))
    assert result.as_dict()["accepted_rows"] == []
    assert [row["row_id"] for row in result.as_dict()["proposed_rows"]] == ["first", "middle", "last", "duplicate"]


@pytest.mark.parametrize("address", [" 1", "+1", "01", "0x01", "$01", "1.0", "١", "", -1, 256])
def test_group_strict_canonical_decimal_domain_refuses(address):
    result = validate([GroupRow("a", address, "One")])
    assert result.errors == (("a", "invalid_address"),)


@pytest.mark.parametrize("address", [True, False, 1.0, None])
def test_group_row_rejects_boolean_and_noninteger_types(address):
    error_code(lambda: GroupRow("a", address, "One"), "invalid_rows")


def test_explicit_capacity_reserved_domain_name_and_duplicate_policies():
    result = validate([GroupRow("first", 1, "Same"), GroupRow("last", 255, "Same")],
        existing=[GroupRow("base", 0, "Same")], allowed_addresses=tuple(range(255)), capacity=1,
        max_tag_name_chars=3)
    assert result.errors == ((None, "capacity_exceeded"), ("first", "tag_name_too_long"),
        ("first", "duplicate_tag_name"), ("last", "address_outside_policy"),
        ("last", "tag_name_too_long"), ("last", "duplicate_tag_name"))
    allowed = validate([GroupRow("zero", "0", "Same"), GroupRow("end", 255, "Same")], duplicate_names="allow")
    assert allowed.valid
    assert allowed.as_dict()["replacement_graph_admitted"] is False
    assert allowed.as_dict()["native_compatibility_verified"] is False
    assert [row.address for row in allowed.rows] == ["0", 255]


@pytest.mark.parametrize("name", ["", " leading", "trailing ", "x\n", "x\x00", "x\x7f", "\ud800", "\uffff"])
def test_group_names_refuse_controls_surrogates_and_silent_trim(name):
    assert validate([GroupRow("a", 1, name)]).errors == (("a", "invalid_tag_name"),)


def test_unsupported_policy_and_inconsistent_baseline_refuse_or_block_all_rows():
    error_code(lambda: GroupPolicy(tuple(range(256)), 256, "allow", profile="native"), "unsupported_profile")
    for kwargs in ({"capacity": True}, {"allowed_addresses": (True,)},
                   {"allowed_addresses": (1, 1)}, {"duplicate_names": "native"},
                   {"max_tag_name_chars": True}):
        error_code(lambda: strict_policy(**kwargs), "invalid_group_policy")
    result = validate([GroupRow("new", 2, "New")], existing=[GroupRow("a", 1, "One"), GroupRow("b", "01", "Other")])
    assert result.errors == ((None, "ambiguous_existing_address"),)
    assert not result.as_dict()["accepted_rows"]
    result = validate([GroupRow("new", 2, "New")], existing=[GroupRow("a", "bad", "One")])
    assert result.errors == ((None, "invalid_existing_address"),)
    for kwargs, code in (({"target_identity": ""}, "invalid_target"),
                         ({"baseline_sha256": "unbound"}, "invalid_baseline")):
        arguments = dict(existing_groups=(), policy=strict_policy(), target_identity="target", baseline_sha256="0" * 64)
        arguments.update(kwargs)
        error_code(lambda: validate_group_draft(GroupDraft(), **arguments), code)


def test_every_workflow_operation_performs_zero_filesystem_or_socket_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("I/O called from pure workflow")
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    index = CatalogueIndex.from_bytes(catalogue(unit()))
    index.select_default(index.units[0].unit_id, profile=CATALOGUE_PROFILE)
    index.select_revision(index.units[0].revisions[0].item_id, "1.5", profile=CATALOGUE_PROFILE)
    draft = parse_group_rows(json.dumps({"format": GROUP_ROWS_FORMAT,
        "rows": [{"row_id": "a", "address": 1, "tag_name": "One"}]}).encode())
    draft = draft.add(GroupRow("b", 2, "Two")).edit("a", address=3, tag_name="Three").delete("b")
    result = validate_group_draft(draft, existing_groups=(), policy=strict_policy(),
                                 target_identity="target", baseline_sha256="0" * 64)
    assert result.valid
    assert draft.cancel().state == "cancelled"


@pytest.mark.parametrize("extra", [
    "<Wrapped>" + unit() + "</Wrapped>",
    "<SubUnits><Wrapped>" + unit() + "</Wrapped></SubUnits>",
    "<FirmwareRevisions><Wrapped>" + revision() + "</Wrapped></FirmwareRevisions>",
    "<Unit/>" + "<FirmwareRevisions>" + revision() + "</FirmwareRevisions>",
])
def test_catalogue_known_nodes_under_unknown_wrappers_refuse_complete_inspection(extra):
    # A valid visible prefix cannot turn an omitted source row into a complete index.
    error_code(lambda: CatalogueIndex.from_bytes(catalogue(unit(), unit(extra=extra))),
               "unsupported_catalogue_shape")


def test_catalogue_root_wrapper_and_unknown_container_children_refuse():
    data = ("<CBusUnits><Units>" + unit() + "</Units><Other>" + unit() + "</Other></CBusUnits>").encode()
    error_code(lambda: CatalogueIndex.from_bytes(data), "unsupported_catalogue_shape")
    data = ("<CBusUnits><Units>" + unit() + "<Other/></Units></CBusUnits>").encode()
    error_code(lambda: CatalogueIndex.from_bytes(data), "unsupported_catalogue_shape")
