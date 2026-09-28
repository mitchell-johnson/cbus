"""Source-bound original C-Gate evidence for post-load Level XML roundtrip."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_nested_levels_roundtrip.json"
VECTOR = ROOT / "rust/testdata/vectors/cgate_dbsetxml_nested_levels_roundtrip.jsonl"
SCRIPT = ROOT / "toolkit-cli/research/cgate_dbsetxml_nested_levels_roundtrip.py"
SOURCE_SHAPE = ROOT / "toolkit-cli/research/cgate_dbsetxml_nested_levels.py"
EXCHANGE = ROOT / "toolkit-cli/research/cgate_dbsetxml_duplicate_applications.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"
CAPTURE_SHA256 = "33f7ac5fb6dd6937138382de8b7bec0ca56598a18c0c05a9a48f348dcce48c52"


def evidence():
    data = CAPTURE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == CAPTURE_SHA256
    return json.loads(data)


def xml(row):
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[1] == f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
    assert lines[-1] == f"[{tag}] 344 End XML snippet\r\n"
    assert len(lines) == 4
    return lines[2][len(f"[{tag}] 347-"):-2]


def test_owned_capture_and_exact_requests():
    captured = evidence()
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    assert captured["schema"] == "native-cgate-dbsetxml-nested-levels-roundtrip-v1"
    assert len(captured["cases"]) == 108
    assert [row["tag"] for row in captured["cases"]] == list(range(900, 1008))
    assert [(shape["project"], shape["kind"], shape["target"], shape["set_tag"])
            for shape in captured["shapes"]] == [
                ("XRTN", "Group", "network", 910),
                ("XRTG", "Group", "group", 928),
                ("XRTL", "Group", "level", 946),
                ("XRVN", "NetVar", "network", 964),
                ("XRVV", "NetVar", "netvar", 982),
                ("XRVL", "NetVar", "level_oid", 1000),
            ]
    for source, key in ((SCRIPT, "capture_script_sha256"),
                        (SOURCE_SHAPE, "source_shape_sha256"),
                        (EXCHANGE, "exchange_helper_sha256"),
                        (HARNESS, "service_harness_sha256")):
        assert captured[key] == hashlib.sha256(source.read_bytes()).hexdigest()
    oracle = captured["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["version"] == "3.4.0 build 2001"
    assert all(oracle[key] is True for key in
               ("owned_loopback_listeners", "cleanup_complete", "process_exit_confirmed", "work_removed"))
    assert oracle["physical_endpoint"] is False
    assert len(oracle["listeners"]) == 6
    assert all(listener.startswith("127.0.0.1:") for listener in oracle["listeners"])
    assert vector["native_fixture"] == CAPTURE.name
    assert vector["basis"] == "native-owned-loopback"
    assert vector["initial_set_tags"] == [shape["set_tag"] - 6 for shape in captured["shapes"]]
    assert vector["roundtrip_set_tags"] == [shape["set_tag"] for shape in captured["shapes"]]
    assert vector["read_tags"] == [row["tag"] for row in captured["cases"]
                                   if row["command"].startswith("DBGETXML ")]
    for row in captured["cases"]:
        tag = row["tag"]
        assert row["response_lines"][-1].startswith(f"[{tag}] ")
        if row["command"].startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {row['command']} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {row['command']}\r\n"
        if row["command"].startswith("DBGETXML "):
            ET.fromstring(xml(row))


def test_post_load_network_group_netvar_and_level_roundtrip():
    rows = {row["tag"]: row for row in evidence()["cases"]}
    for shape in evidence()["shapes"]:
        tag = shape["set_tag"]
        target = shape["target"]
        before = xml(rows[tag - 1])
        after = xml(rows[tag + 1])
        network = xml(rows[tag + 2])
        reloaded = xml(rows[tag + 7])
        assert rows[tag]["response_lines"][-1].startswith(f"[{tag}] 301 OID=")
        submitted = rows[tag]["request"].split(f" << END{tag}\r\n", 1)[1]
        assert submitted == '<?xml version="1.0" encoding="utf-8"?>\n' + before + f"\r\nEND{tag}\r\n"
        assert before == after
        assert network == reloaded
        assert before.count("<TagsDLT/>") == (2 if target == "network" else 1)
        assert network.count("<TagsDLT/>") == 2
        assert [int(app.findtext("Address")) for app in ET.fromstring(network).findall("Application")] == [56, 57]
