from __future__ import annotations

import json
from pathlib import Path
import struct

import pytest

from research.extract_toolkit_executable_surface import (
    DfmFormatError,
    parse_binary_dfm,
)


ROOT = Path(__file__).resolve().parents[1]
SURFACE = ROOT / "docs" / "toolkit-executable-surface.json"


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
        "event_bindings": 1892,
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
