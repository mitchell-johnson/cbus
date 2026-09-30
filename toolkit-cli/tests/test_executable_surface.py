from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import struct

import pytest

from research.extract_toolkit_executable_surface import (
    DfmFormatError,
    parse_binary_dfm,
)


ROOT = Path(__file__).resolve().parents[1]
SURFACE = ROOT / "docs" / "toolkit-executable-surface.json"
ONCOLOR_PROOF = ROOT / "research" / "fixtures" / "toolkit-oncolor-property-proof.json"
ONCOLOR_RTTI_PROOF = ROOT / "research" / "fixtures" / "toolkit-oncolor-rtti-proof.json"


def short(value: str) -> bytes:
    raw = value.encode("cp1252")
    return bytes([len(raw)]) + raw


def string_value(value: str, value_type: int = 6) -> bytes:
    raw = value.encode("cp1252")
    if value_type in (6, 7):
        return bytes([value_type]) + bytes([len(raw)]) + raw
    return bytes([value_type]) + struct.pack("<I", len(raw)) + raw


def component(class_name: str, name: str, properties: list[tuple[str, bytes]], children: list[bytes]) -> bytes:
    return (
        short(class_name)
        + short(name)
        + b"".join(short(key) + value for key, value in properties)
        + b"\0"
        + b"".join(children)
        + b"\0"
    )


def test_binary_dfm_parser_captures_nested_controls_and_events() -> None:
    button = component(
        "TButton",
        "SaveButton",
        [("Caption", string_value("Save")), ("OnClick", string_value("SaveClick", 7))],
        [],
    )
    raw = b"TPF0" + component(
        "TMainForm",
        "MainForm",
        [("OnShow", string_value("FormShow", 7))],
        [button],
    )

    parsed = parse_binary_dfm(raw)

    assert parsed["root_class"] == "TMainForm"
    assert parsed["root_name"] == "MainForm"
    assert parsed["components"] == [
        {"path": "MainForm", "class": "TMainForm", "name": "MainForm"},
        {
            "path": "MainForm/SaveButton",
            "class": "TButton",
            "name": "SaveButton",
        },
    ]
    assert parsed["event_bindings"] == [
        {"component_path": "MainForm", "property": "OnShow", "handler": "FormShow"},
        {
            "component_path": "MainForm/SaveButton",
            "property": "OnClick",
            "handler": "SaveClick",
        },
    ]


def test_binary_dfm_parser_rejects_truncation_and_trailing_data() -> None:
    raw = b"TPF0" + component("TForm", "Form1", [], [])
    with pytest.raises(DfmFormatError, match="unexpected end|exceeds stream"):
        parse_binary_dfm(raw[:-1])
    with pytest.raises(DfmFormatError, match="trailing bytes"):
        parse_binary_dfm(raw + b"x")


def test_original_oncolor_proof_synthetic_regression() -> None:
    proof_raw = ONCOLOR_PROOF.read_bytes()
    assert sha256(proof_raw).hexdigest() == "6ddc04a53652192c504c6a992c748ddee1c7a345e1c35dc8339508004f3d662a"
    regression = json.loads(proof_raw)["synthetic_regression"]
    raw = bytes.fromhex(regression["raw_hex"])
    assert sha256(raw).hexdigest() == regression["sha256"]
    # The original-bound counterexample retains OnShow and OnClick=clRed.
    assert parse_binary_dfm(raw)["event_bindings"] == regression["expected_events"]


@pytest.mark.parametrize("class_name", [
    "TLEDStatusIndicator", "tledstatusindicator",
    "TFlashLEDStatusIndicator", "tflashledstatusindicator",
])
@pytest.mark.parametrize("property_name", ["OnColor", "oncolor", "ONCOLOR"])
def test_scalar_oncolor_classification_is_case_insensitive(class_name: str, property_name: str) -> None:
    raw = b"TPF0" + component(
        class_name, "LED", [(property_name, string_value("clLime", 7))], [],
    )
    assert parse_binary_dfm(raw)["event_bindings"] == []


@pytest.mark.parametrize("class_name", ["TButton", "TUnknownLEDSubclass"])
def test_oncolor_on_other_classes_remains_an_event_candidate(class_name: str) -> None:
    raw = b"TPF0" + component(
        class_name, "Control",
        [("OnColor", string_value("clRed", 7)), ("OnClick", string_value("InheritedClick", 7))], [],
    )
    assert parse_binary_dfm(raw)["event_bindings"] == [
        {"component_path": "Control", "property": "OnColor", "handler": "clRed"},
        {"component_path": "Control", "property": "OnClick", "handler": "InheritedClick"},
    ]


def test_oncolor_proof_is_bound_to_original_inventory_resources() -> None:
    proof = json.loads(ONCOLOR_PROOF.read_bytes())
    surface = json.loads(SURFACE.read_bytes())
    assert proof["provenance"]["exe_sha256"] == surface["sources"]["executable"]["sha256"]
    assert proof["provenance"]["map_sha256"] == surface["sources"]["map"]["sha256"]
    resources = {row["resource_name"]: row for row in surface["resources"]}
    assert len(proof["affected_records"]) == proof["false_records"] == 53
    assert len(proof["counts_by_resource"]) == 7
    for record in proof["affected_records"]:
        resource = resources[record["resource"]]
        assert resource["resource_sha256"] == record["resource_sha256"]
        classes = {row["path"]: row["class"] for row in resource["components"]}
        assert classes[record["component_path"]] == record["component_class"]
        raw = b"TPF0" + component(
            record["component_class"], "LED",
            [(record["property"], string_value(record["value"], record["value_type"]))], [],
        )
        assert parse_binary_dfm(raw)["event_bindings"] == []


def test_original_rtti_proves_scalar_type_and_exact_flash_inheritance() -> None:
    raw = ONCOLOR_RTTI_PROOF.read_bytes()
    assert sha256(raw).hexdigest() == "db04191b9e604ee7d3271c4ec4d10d1b6ab4d837c79cca3a3ee4f6d51c47984a"
    rtti = json.loads(raw)
    proof = json.loads(ONCOLOR_PROOF.read_bytes())
    assert rtti["exe_sha256"] == proof["provenance"]["exe_sha256"]
    classes = {row["typeinfo"]["name"]: row for row in rtti["classes"]}
    base = classes["TLEDStatusIndicator"]
    flash = classes["TFlashLEDStatusIndicator"]
    assert flash["parent_vmt"] == base["vmt_va"]
    assert flash["parent_typeinfo"] == base["typeinfo"]["va"]
    assert [row["name"] for row in flash["own_published_properties"]] == ["FlashController"]
    color = next(row for row in base["own_published_properties"] if row["name"] == "OnColor")
    assert color["type"]["name"] == "TColor"
    assert color["type"]["kind"] == 1  # Delphi tkInteger, not tkMethod.
    methods = {row["symbol"].rsplit(".", 1)[-1]: row for row in proof["native_method_proof"]}
    assert color["getter"] == methods["GetOnColor"]["start"]
    assert color["setter"] == methods["SetOnColor"]["start"]


def test_committed_toolkit_1180_executable_inventory_is_complete_and_unique() -> None:
    surface = json.loads(SURFACE.read_text(encoding="utf-8"))

    assert surface["schema_version"] == 1
    assert surface["sources"]["executable"] == {
        "file_version": "1.18.0.2754",
        "product_version": "1.18.0",
        "sha256": "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab",
        "size": 20518992,
    }
    assert surface["counts"] == {
        "components": 10102,
        "event_bindings": 1839,
        "map_bound_forms": 412,
        "opaque_rcdata_resources": 4,
        "parse_errors": 0,
        "parsed_form_resources": 412,
    }
    resources = surface["resources"]
    assert len(resources) == len({row["resource_name"] for row in resources})
    for resource in resources:
        paths = [row["path"] for row in resource["components"]]
        assert len(paths) == len(set(paths))
        assert all(binding["component_path"] in paths for binding in resource["event_bindings"])
