"""Owned native C-Gate 3.4 DBSETXML error and conflict classes, without live I/O."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_errors.json"
VECTORS = ROOT / "rust/testdata/vectors/cgate_dbsetxml_errors.jsonl"
SCRIPT = ROOT / "toolkit-cli/research/cgate_dbsetxml_errors.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def capture():
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def probes():
    return {probe["case"]: probe for probe in capture()["probes"]}


def final(tag):
    row = next(row for row in capture()["cases"] if row["tag"] == tag)
    return row["response_lines"][-1].split(" ", 1)[1].rstrip("\r\n")


def test_capture_is_source_bound_and_disposable():
    evidence = capture()
    assert evidence["schema"] == "native-cgate-dbsetxml-errors-v1"
    assert evidence["capture_script_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert evidence["service_harness_sha256"] == hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    oracle = evidence["oracle"]
    for key, expected in {
        "jar_sha256": "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630",
        "java_sha256": "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4",
        "version": "3.4.0 build 2001",
        "owned_loopback_listeners": True,
        "cleanup_complete": True,
        "process_exit_confirmed": True,
        "work_removed": True,
        "physical_endpoint": False,
    }.items():
        assert oracle[key] == expected
    assert all(listener.startswith("127.0.0.1:") for listener in oracle["listeners"])
    assert len(evidence["probes"]) == 46


def test_refusals_are_446_401_or_440_and_leave_the_network_unchanged():
    probe = probes()
    refused = {name: row for name, row in probe.items() if row["status"] not in (301, None)}
    assert {row["status"] for row in refused.values()} == {401, 440, 446}
    assert all(row["network_unchanged"] for row in refused.values())
    assert final(probe["malformed-not-xml"]["set_tag"]).startswith(
        "446 Unable to set XML: org.xml.sax.SAXParseException;")
    assert final(probe["oversize-tagname-33"]["set_tag"]).endswith(
        "Strings of this type must have a maximum length of 32 characters")
    assert probe["tagname-32"]["status"] == 301
    assert final(probe["root-unknown-element"]["set_tag"]).endswith("XPATH: /Unit/TagName")
    assert final(probe["target-missing-project"]["set_tag"]) == (
        "440 There is no tag database to perform this operation on")


def test_native_accepts_destructive_shapes_and_has_no_prompt_size_limit():
    probe = probes()
    # A Unit or Project body at a Network path replaces that Network.
    for name in ("root-unit-at-network-path", "root-project-at-network-path",
                 "address-unit-non-numeric", "unit-oid-missing", "interface-type-change"):
        assert probe[name]["status"] == 301 and not probe[name]["network_unchanged"]
    assert probe["document-64kib"]["status"] == 301
    assert probe["document-1mib"]["timed_out"] is True


def test_vectors_cover_every_non_size_probe_with_a_disposition():
    probe = probes()
    vectors = [json.loads(line) for line in VECTORS.read_text(encoding="utf-8").splitlines()]
    assert sorted(vector["name"] for vector in vectors) == sorted(
        name for name, row in probe.items() if "readback_tag" in row)
    for vector in vectors:
        native = probe[vector["name"]]
        assert vector["set_tag"] == native["set_tag"]
        assert vector["native_status"] == native["status"]
        disposition = vector["disposition"]
        if disposition.startswith("native"):
            assert vector["rust_status"] == native["status"]
        if disposition == "native-exact":
            assert vector["rust_reply"] == final(native["set_tag"])
        if disposition == "accepted-both":
            assert vector["rust_status"] == native["status"] == 301
        if disposition == "rust-refuses-native-accepts":
            assert native["status"] == 301 and vector["rust_status"] in (400, 446)
