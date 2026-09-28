"""Owned build-2001 evidence for mutations through a duplicated Unit OID."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_duplicate_unit_oid_mutations.json"
SCRIPT = ROOT / "toolkit-cli/research/cgate_duplicate_unit_oid_mutations.py"
HELPER = ROOT / "toolkit-cli/research/cgate_dbsetxml_duplicate_oids.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"
REVERSE_FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_duplicate_unit_oid_reverse_order.json"
REVERSE_SCRIPT = ROOT / "toolkit-cli/research/cgate_duplicate_unit_oid_reverse_order.py"


def evidence() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def status(row: dict) -> int:
    return int(row["response_lines"][-1].split()[1])


def unit(row: dict) -> ET.Element:
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[-1] == f"[{tag}] 344 End XML snippet\r\n"
    assert lines[2].startswith(f"[{tag}] 347-")
    return ET.fromstring(lines[2][len(f"[{tag}] 347-") :].rstrip("\r\n"))


def test_capture_is_source_bound_owned_and_sequential() -> None:
    captured = evidence()
    assert captured["schema"] == "native-cgate-duplicate-unit-oid-mutations-v1"
    for source, key in (
        (SCRIPT, "capture_script_sha256"),
        (HELPER, "exchange_helper_sha256"),
        (HARNESS, "service_harness_sha256"),
    ):
        assert captured[key] == hashlib.sha256(source.read_bytes()).hexdigest()
    oracle = captured["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["version"] == "3.4.0 build 2001"
    for key in ("owned_loopback_listeners", "cleanup_complete", "process_exit_confirmed", "work_removed"):
        assert oracle[key] is True
    assert oracle["physical_endpoint"] is False
    assert len(oracle["listeners"]) == 6
    assert all(listener.startswith("127.0.0.1:") for listener in oracle["listeners"])

    rows = list(captured["setup"])
    for case in captured["cases"]:
        rows.extend((case["reset"], *case["before"], case["oid_before"], case["applied"],
                     *case["after"], case["oid_after"], *case["lifecycle"],
                     *case["reloaded"], case["oid_reloaded"]))
    assert len(rows) == 89
    assert [row["tag"] for row in rows] == list(range(300, 389))
    for row in rows:
        tag = row["tag"]
        assert row["response_lines"][-1].startswith(f"[{tag}] {status(row)} ")
        if row["command"].startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {row['command']} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {row['command']}\r\n"


def test_native_last_unit_selection_copy_and_reload() -> None:
    captured = evidence()
    assert [case["name"] for case in captured["cases"]] == [
        "set_safe", "set_unsafe", "set_xml", "copy_safe", "delete"
    ]
    for case in captured["cases"]:
        name = case["name"]
        assert status(case["reset"]) == 301
        assert [unit(row).findtext("Address") for row in case["before"]] == ["20", "21"]
        assert unit(case["oid_before"]).findtext("Address") == "21"
        assert unit(case["after"][0]).findtext("UnitName") == "First room"
        assert [status(row) for row in case["lifecycle"]] == [200] * 4
        assert unit(case["reloaded"][0]).findtext("UnitName") == "First room"
        if name == "delete":
            assert status(case["applied"]) == 200
            assert status(case["after"][1]) == 401
            assert status(case["oid_after"]) == 401
            assert status(case["reloaded"][1]) == 401
            assert unit(case["oid_reloaded"]).findtext("Address") == "20"
            continue
        assert status(case["applied"]) in (200, 301)
        assert unit(case["oid_after"]).findtext("Address") == "21"
        assert unit(case["oid_reloaded"]).findtext("Address") == "21"
        if name in ("set_safe", "set_unsafe"):
            assert unit(case["after"][1]).findtext("UnitName") == "ByOID"
        elif name == "set_xml":
            assert unit(case["after"][1]).findtext("UnitName") == "Changed room"
        else:
            assert status(case["applied"]) == 301
            copied = unit(case["after"][2])
            assert copied.findtext("Address") == "22"
            assert copied.findtext("TagName") == "Copied"
            assert copied.findtext("UnitName") == "Second room"
            assert copied.findtext("OID") != captured["shared_oid"]
            assert copied.find("PP").get("Value") == "21"
            assert unit(case["reloaded"][2]).find("PP").get("Value") == "21"


def test_reversed_submission_selects_final_unit_not_highest_address() -> None:
    captured = json.loads(REVERSE_FIXTURE.read_text(encoding="utf-8"))
    assert captured["schema"] == "native-cgate-duplicate-unit-oid-reverse-order-v1"
    for source, key in (
        (REVERSE_SCRIPT, "capture_script_sha256"),
        (HELPER, "exchange_helper_sha256"),
        (HARNESS, "service_harness_sha256"),
    ):
        assert captured[key] == hashlib.sha256(source.read_bytes()).hexdigest()
    oracle = captured["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["physical_endpoint"] is False
    for key in ("owned_loopback_listeners", "cleanup_complete", "process_exit_confirmed", "work_removed"):
        assert oracle[key] is True
    case, = captured["cases"]
    assert case["name"] == "set_safe"
    rows = [*captured["setup"], case["reset"], *case["before"], case["oid_before"],
            case["applied"], *case["after"], case["oid_after"],
            *case["lifecycle"], *case["reloaded"], case["oid_reloaded"]]
    assert [row["tag"] for row in rows] == list(range(300, 321))
    reset_request = case["reset"]["request"]
    assert reset_request.index("<Address>21</Address><UnitType>") < reset_request.index(
        "<Address>20</Address><UnitType>")
    assert unit(case["oid_before"]).findtext("Address") == "20"
    assert status(case["applied"]) == 200
    assert unit(case["after"][0]).findtext("UnitName") == "Selected"
    assert unit(case["after"][1]).findtext("UnitName") == "Second room"
    assert unit(case["oid_after"]).findtext("Address") == "20"
    assert [status(row) for row in case["lifecycle"]] == [200] * 4
    assert unit(case["oid_reloaded"]).findtext("Address") == "20"
    assert unit(case["oid_reloaded"]).findtext("UnitName") == "Selected"
