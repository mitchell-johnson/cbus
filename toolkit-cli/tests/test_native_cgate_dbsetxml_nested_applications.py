"""Source-bound original C-Gate evidence for nested same-OID Applications."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_nested_applications.json"
VECTOR = ROOT / "rust/testdata/vectors/cgate_dbsetxml_nested_applications.jsonl"
SCRIPT = ROOT / "toolkit-cli/research/cgate_dbsetxml_nested_applications.py"
EXCHANGE = ROOT / "toolkit-cli/research/cgate_dbsetxml_duplicate_applications.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"
SHARED = "33333333-3333-4333-8333-333333333333"


def capture():
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def rows():
    return {row["tag"]: row for row in capture()["cases"]}


def xml(row):
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[1] == f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
    assert lines[-1] == f"[{tag}] 344 End XML snippet\r\n"
    return lines[2][len(f"[{tag}] 347-"):-2]


def test_capture_is_pinned_owned_and_complete():
    evidence = capture()
    assert evidence["schema"] == "native-cgate-dbsetxml-nested-applications-v1"
    assert evidence["capture_script_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert evidence["exchange_helper_sha256"] == hashlib.sha256(EXCHANGE.read_bytes()).hexdigest()
    assert evidence["service_harness_sha256"] == hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    oracle = evidence["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["version"] == "3.4.0 build 2001"
    for key in ("owned_loopback_listeners", "cleanup_complete", "process_exit_confirmed", "work_removed"):
        assert oracle[key] is True
    assert oracle["physical_endpoint"] is False
    assert len(oracle["listeners"]) == 6
    assert all(listener.startswith("127.0.0.1:") for listener in oracle["listeners"])
    assert evidence["shared_oid"] == SHARED
    assert len(evidence["cases"]) == 67
    assert [row["tag"] for row in evidence["cases"]] == list(range(700, 767))
    assert [(shape["project"], shape["kind"], shape["addresses"], shape["submit_tag"])
            for shape in evidence["shapes"]] == [
        ("XNG1", "Group", [56], 704),
        ("XNG2", "Group", [56, 57], 719),
        ("XNN2", "NetVar", [56, 57], 745),
    ]
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    assert vector["native_fixture"] == CAPTURE.name
    assert vector["basis"] == "native-owned-loopback"
    assert vector["set_tags"] == [row["tag"] for row in evidence["cases"]
                                  if row["command"].startswith(("DBSETXML ", "DBSET "))]
    assert vector["read_tags"] == [row["tag"] for row in evidence["cases"]
                                   if row["command"].startswith(("DBGETXML ", "DBGET "))]
    for row in evidence["cases"]:
        tag = row["tag"]
        assert row["response_lines"][-1].startswith(f"[{tag}] ")
        if row["command"].startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {row['command']} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {row['command']}\r\n"


def test_nested_children_order_selection_replacement_and_save_reload():
    case = rows()
    for shape in capture()["shapes"]:
        start = shape["submit_tag"]
        kind = shape["kind"]
        addresses = shape["addresses"]
        count = len(addresses)
        assert case[start]["response_lines"][-1].startswith(f"[{start}] 301 OID=")

        def applications(tag):
            nodes = ET.fromstring(xml(case[tag])).findall("Application")
            assert [int(node.findtext("Address")) for node in nodes] == addresses
            assert [node.findtext("OID") for node in nodes] == [SHARED] * count
            for node, address in zip(nodes, addresses):
                child = node.find(kind)
                assert child is not None
                assert child.findtext("Address") == "1"
                assert child.findtext("OID") == f"44444444-4444-4444-8444-0000000000{address}"
            return [node.findtext("TagName") for node in nodes]

        assert applications(start + 1) == [f"App{address}" for address in addresses]
        after_reload = start + 7 + 2 * count
        assert applications(after_reload) == [f"App{address}" for address in addresses]
        assert xml(case[start + 1]) == xml(case[after_reload])
        for tag in (start + 2 + 2 * count, after_reload + 1):
            selected = ET.fromstring(xml(case[tag]))
            assert selected.findtext("Address") == str(addresses[-1])
            assert selected.find(kind) is not None
        if count == 2:
            replace_tag = after_reload + 2
            assert case[replace_tag]["response_lines"][-1].startswith(f"[{replace_tag}] 301 OID={SHARED}")
            assert applications(replace_tag + 1) == ["Changed56", "App57"]
            selected = ET.fromstring(xml(case[replace_tag + 2]))
            assert selected.findtext("Address") == "57"
            assert selected.find(kind) is not None
            assert applications(replace_tag + 8) == ["Changed56", "App57"]
            assert xml(case[replace_tag + 1]) == xml(case[replace_tag + 8])
