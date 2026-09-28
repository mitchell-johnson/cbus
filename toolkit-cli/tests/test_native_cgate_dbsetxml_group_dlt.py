"""Source-bound native evidence for complete Group DLT label replacement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_group_dlt.json"
CAPTURE_SHA256 = "d078ce2d67b0819abb4a3f86c1e6492bd96fed56e3472b2e44848475effcb357"
VECTOR = ROOT / "rust/testdata/vectors/cgate_dbsetxml_group_dlt.jsonl"
SOURCES = {
    "capture_script_sha256": ROOT / "toolkit-cli/research/cgate_dbsetxml_group_dlt.py",
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
    xml = lines[2][len(f"[{tag}] 347-"):-2]
    ET.fromstring(xml)
    return xml


def _labels(row):
    root = ET.fromstring(_xml(row))
    group = root if root.tag == "Group" else root.find(".//Group")
    assert group is not None
    return [{field.tag: field.text for field in label}
            for label in group.findall("TagsDLT/TagDLT")]


def test_owned_oracle_sources_and_exact_tagged_exchange():
    capture = _capture()
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    assert capture["schema"] == "native-cgate-dbsetxml-group-dlt-v1"
    assert vector["schema"] == "cgate-dbsetxml-group-dlt-v1"
    assert vector["native_fixture"] == CAPTURE.name
    assert vector["basis"] == "native-owned-loopback"
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
    assert [row["tag"] for row in rows] == list(range(1100, 1134))
    assert vector["read_tags"] == [row["tag"] for row in rows
                                   if row["command"].startswith("DBGETXML ")]
    for row in rows:
        tag = row["tag"]
        command = row["command"]
        if command.startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {command} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
            assert row["response_lines"][-1].startswith(f"[{tag}] 301 OID=")
        else:
            assert row["request"] == f"[{tag}] {command}\r\n"
        if command.startswith("DBGETXML "):
            _xml(row)
        else:
            assert row["response_lines"][-1].startswith(f"[{tag}] ")


def test_group_label_add_edit_second_flavour_and_removal_survive_lifecycle():
    capture = _capture()
    rows = {row["tag"]: row for row in capture["cases"]}
    first = capture["first_tag_oid"]
    second = capture["second_tag_oid"]
    assert first != second
    assert "<TagsDLT/>" in _xml(rows[1109])  # Level only, before Group label add.
    assert "<OID>" not in rows[1110]["request"].split("<TagsDLT>", 1)[1].split("</TagsDLT>", 1)[0]
    assert first in rows[1113]["request"]
    assert first in rows[1121]["request"]
    assert "<OID>" not in rows[1123]["request"].split("<TagValue>Second flavour</TagValue>", 1)[0].rsplit("<TagDLT>", 1)[1]
    for tag, value in ((1111, "Owned group label"), (1112, "Owned group label"),
                       (1114, "Owned edited group label"), (1119, "Owned edited group label"),
                       (1120, "Owned edited group label"), (1122, "Owned edited group label")):
        labels = _labels(rows[tag])
        assert len(labels) == 1
        assert labels[0] == {"OID": first, "LanguageID": "1", "FlavourID": "1",
                             "TagType": "TEXT", "TagValue": value}
    for tag in (1124, 1129, 1130):
        labels = _labels(rows[tag])
        assert [(label["OID"], label["FlavourID"], label["TagValue"])
                for label in labels] == [
                    (first, "1", "Owned edited group label"),
                    (second, "2", "Second flavour")]
    assert _labels(rows[1132]) == []
    assert _labels(rows[1133]) == []
    assert "<TagsDLT/>" in _xml(rows[1132])
