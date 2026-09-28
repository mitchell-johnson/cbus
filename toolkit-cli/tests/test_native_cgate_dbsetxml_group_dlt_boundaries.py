"""Source-bound Group TagsDLT acceptance from owned C-Gate build 2001."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_group_dlt_boundaries.json"
CAPTURE_SHA256 = "d862b6dbda13954df106021062276c81f647d9d9319142d8eb215e69789a21f9"
VECTOR = ROOT / "rust/testdata/vectors/cgate_dbsetxml_group_dlt_boundaries.jsonl"
SOURCES = {
    "capture_script_sha256": ROOT / "toolkit-cli/research/cgate_dbsetxml_group_dlt_boundaries.py",
    "source_shape_sha256": ROOT / "toolkit-cli/research/cgate_dbsetxml_nested_levels.py",
    "exchange_helper_sha256": ROOT / "toolkit-cli/research/cgate_dbsetxml_duplicate_applications.py",
    "service_harness_sha256": ROOT / "toolkit-cli/research/local_cgate.py",
}


def _xml(row):
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[1] == f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
    assert lines[3] == f"[{tag}] 344 End XML snippet\r\n"
    assert len(lines) == 4
    xml = lines[2][len(f"[{tag}] 347-"):-2]
    ET.fromstring(xml)
    return xml


def _labels(row):
    root = ET.fromstring(_xml(row))
    return [{field.tag: field.text for field in label}
            for label in root.findall("TagsDLT/TagDLT")]


def test_owned_oracle_source_and_exact_boundary_matrix():
    raw = CAPTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CAPTURE_SHA256
    capture = json.loads(raw)
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    assert capture["schema"] == "native-cgate-dbsetxml-group-dlt-boundaries-v1"
    assert vector["schema"] == "cgate-dbsetxml-group-dlt-boundaries-v1"
    assert vector["native_fixture"] == CAPTURE.name
    assert vector["basis"] == "native-owned-loopback"
    oracle = capture["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "2fe1decd61295e8e61e6157447f2cf1e3782eb101cff937e9a8176ef17fe584e"
    assert oracle["version"] == "3.4.0 build 2001"
    assert all(oracle[key] is True for key in (
        "owned_loopback_listeners", "cleanup_complete", "process_exit_confirmed", "work_removed"))
    assert oracle["physical_endpoint"] is False
    assert len(oracle["listeners"]) == 6
    assert all(address.startswith("127.0.0.1:") for address in oracle["listeners"])
    for key, source in SOURCES.items():
        assert capture[key] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert capture["greeting"].startswith("201 Service ready: Schneider Electric C-Gate")

    rows = capture["cases"]
    assert len(rows) == 30
    assert [row["name"] for row in rows] == vector["case_names"]
    assert [row["set"]["tag"] for row in rows] == list(range(2211, 2299, 3))
    for row in rows:
        for key in ("before", "set", "after"):
            item = row[key]
            tag = item["tag"]
            command = item["command"]
            if key == "set":
                assert item["request"].startswith(f"[{tag}] {command} << END{tag}\r\n")
                assert item["request"].endswith(f"\r\nEND{tag}\r\n")
            else:
                assert item["request"] == f"[{tag}] {command}\r\n"
                _xml(item)
        set_status = int(row["set"]["response_lines"][-1].split()[1])
        assert set_status == (446 if row["name"] == "duplicate_collection" else 301)


def test_group_field_and_duplicate_boundaries():
    capture = json.loads(CAPTURE.read_text(encoding="utf-8"))
    rows = {row["name"]: row for row in capture["cases"]}
    for name, language in (("language_zero", "0"), ("language_256", "256"),
                           ("language_text", "English")):
        assert _labels(rows[name]["after"])[0]["LanguageID"] == language
    for name, flavour in (("flavour_zero", "0"), ("flavour_five", "5"),
                          ("flavour_text", "Primary")):
        assert _labels(rows[name]["after"])[0]["FlavourID"] == flavour
    for name, tag_type in (("type_image", "IMAGE"), ("type_lowercase", "text"),
                           ("type_unknown", "UNRECOGNISED"), ("type_empty", None)):
        assert _labels(rows[name]["after"])[0]["TagType"] == tag_type
    assert [len(_labels(rows[name]["after"])) for name in (
        "two_flavours", "four_flavours", "five_flavours", "sixty_five")] == [2, 4, 5, 65]
    assert [label["FlavourID"] for label in _labels(rows["duplicate_variant"]["after"])] == ["1", "1"]
    assert len({label["OID"] for label in _labels(rows["duplicate_oid"]["after"])}) == 1
    assert _labels(rows["group_oid"]["after"])[0]["OID"] == capture["group_oid"]
    assert _labels(rows["level_oid"]["after"])[0]["OID"] == capture["level_oid"]
    assert _labels(rows["default_namespace"]["after"]) == []
    assert _labels(rows["tag_namespace"]["after"])[0].keys() == {"OID"}
    assert "TagType" not in _labels(rows["field_namespace"]["after"])[0]
    assert rows["duplicate_collection"]["set"]["response_lines"][-1].startswith(
        "[2295] 446 Unable to set XML: ValidationException: Element 'TagsDLT' occurs more than once.")
    assert _xml(rows["duplicate_collection"]["before"]) == _xml(rows["duplicate_collection"]["after"])
