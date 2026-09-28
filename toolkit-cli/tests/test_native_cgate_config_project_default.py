"""Integrity and scope checks for the owned project.default C-Gate oracle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_config_project_default.json"
CAPTURE = ROOT / "rust/cbus-cgate/research/native_config_project_default_probe.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def test_native_project_default_evidence_is_owned_and_source_pinned() -> None:
    report = json.loads(FIXTURE.read_text())
    assert report["schema"] == "native-cgate-config-project-default-v1"
    oracle = report["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["capture_script_sha256"] == hashlib.sha256(CAPTURE.read_bytes()).hexdigest()
    assert oracle["harness_sha256"] == hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    assert oracle["physical_endpoint"] is False
    assert all(
        oracle[child][key] is True
        for child in ("first_child", "second_child")
        for key in ("listeners_owned", "process_exit_confirmed", "cleanup_complete", "work_removed")
    )
    assert len(report["first_child"]) == 9
    assert len(report["second_child"]) == 6
    assert report["first_child"][0]["response"] == ["[initial] 123 project=null"]
    assert report["first_child"][8]["response"] == ["[pending] 123 project="]
    assert report["second_child"][0]["response"] == ["[unloaded] 123 project=null"]
    assert report["second_child"][2]["response"] == ["[loaded] 123 project=XDFLT"]
    assert report["second_child"][4]["response"] == ["[read-later] 303 project.default=XOTHER"]
    assert report["second_child"][5]["response"] == ["[still-startup] 123 project=XDFLT"]
