"""Source-bound original C-Gate evidence for nonempty Level DLT labels."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_level_dlt.json"
CAPTURE_SHA256 = "00b7d0b97201462872d7f74608d094e7ebdc6ef16c0995b5f9ea243b057b1061"
VECTOR = ROOT / "rust/testdata/vectors/cgate_dbsetxml_level_dlt.jsonl"
SOURCES = {
    "capture_script_sha256": ROOT / "toolkit-cli/research/cgate_dbsetxml_level_dlt.py",
    "source_shape_sha256": ROOT / "toolkit-cli/research/cgate_dbsetxml_nested_levels.py",
    "exchange_helper_sha256": ROOT / "toolkit-cli/research/cgate_dbsetxml_duplicate_applications.py",
    "service_harness_sha256": ROOT / "toolkit-cli/research/local_cgate.py",
}


def _capture():
    raw = CAPTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CAPTURE_SHA256
    return json.loads(raw)


def _xml(row):
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[1] == f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
    assert lines[3] == f"[{tag}] 344 End XML snippet\r\n"
    assert len(lines) == 4
    result = lines[2][len(f"[{tag}] 347-"):-2]
    ET.fromstring(result)
    return result


def test_owned_oracle_and_exact_tagged_exchanges():
    capture = _capture()
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    assert vector["schema"] == "cgate-dbsetxml-level-dlt-v1"
    assert vector["native_fixture"] == CAPTURE.name
    assert vector["basis"] == "native-owned-loopback"
    assert vector["generated_label_set_tag"] == 1010
    assert vector["explicit_oid_edit_tag"] == 1013
    assert vector["network_roundtrip_tag"] == 1022
    assert vector["read_tags"] == [row["tag"] for row in capture["cases"]
                                   if row["command"].startswith("DBGETXML ")]
    assert capture["schema"] == "native-cgate-dbsetxml-level-dlt-v1"
    oracle = capture["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
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
    assert [row["tag"] for row in rows] == list(range(1000, 1024))
    for row in rows:
        tag = row["tag"]
        command = row["command"]
        if command.startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {command} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {command}\r\n"
        if command.startswith("DBGETXML "):
            _xml(row)
        else:
            assert row["response_lines"][-1].startswith(f"[{tag}] ")


def test_generated_label_oid_and_save_load_roundtrip():
    capture = _capture()
    rows = {row["tag"]: row for row in capture["cases"]}
    assert "<TagsDLT/>" in _xml(rows[1009])
    for tag in (1004, 1010, 1013, 1022):
        assert rows[tag]["response_lines"][-1].startswith(f"[{tag}] 301 OID=")
    for tag, value in ((1011, "Owned label"), (1014, "Owned edited label"),
                       (1020, "Owned edited label"), (1021, "Owned edited label"),
                       (1023, "Owned edited label")):
        root = ET.fromstring(_xml(rows[tag]))
        label = root.find(".//Level/TagsDLT/TagDLT") if root.tag == "Network" else root.find("TagsDLT/TagDLT")
        assert label is not None
        assert label.findtext("OID") == capture["generated_tag_oid"]
        assert label.findtext("LanguageID") == "1"
        assert label.findtext("FlavourID") == "1"
        assert label.findtext("TagType") == "TEXT"
        assert label.findtext("TagValue") == value
    assert "<OID>" not in rows[1010]["request"].split("<TagsDLT>", 1)[1].split("</TagsDLT>", 1)[0]
    assert capture["generated_tag_oid"] in rows[1013]["request"]
    assert _xml(rows[1021]) == _xml(rows[1023])
