"""Source and ownership checks for the original project.start lifecycle capture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_config_project_start.json"
VECTORS = ROOT / "rust/testdata/vectors/cgate_config_project_start.jsonl"
CAPTURE = ROOT / "rust/cbus-cgate/research/native_config_project_start_probe.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def test_native_project_start_capture_is_owned_source_bound_and_exact() -> None:
    report = json.loads(FIXTURE.read_text())
    assert report["schema"] == "native-cgate-config-project-start-v1"
    oracle = report["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["capture_script_sha256"] == hashlib.sha256(CAPTURE.read_bytes()).hexdigest()
    assert oracle["harness_sha256"] == hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    assert oracle["physical_endpoint"] is False
    assert set(oracle["children"]) == {
        "seed", "single_start", "saved_restart", "multiple_start", "missing_start"
    }
    assert all(
        child[key] is True
        for child in oracle["children"].values()
        for key in ("listeners_owned", "process_exit_confirmed", "cleanup_complete", "work_removed")
    )
    assert report["single_start"]["startup_poll"][-1]["response"][0].endswith(
        "123 project=XSTARTA state=started"
    )
    for raw in VECTORS.read_text().splitlines():
        vector = json.loads(raw)
        rows = report[vector["case"]][vector["phase"]][vector["index"]]["response"]
        assert [row.split("] ", 1)[1] for row in rows] == vector["reply"], vector["id"]


def test_native_project_start_scope_retains_missing_and_selection_boundary() -> None:
    report = json.loads(FIXTURE.read_text())
    assert report["single_start"]["settled"][1]["response"] == [
        "[settled-use] 123 project=XSTARTB"
    ]
    assert report["multiple_start"]["settled"][1]["response"] == [
        "[settled-use] 123 project=XSTARTB"
    ]
    assert report["saved_restart"]["settled"][1]["response"] == [
        "[restart-list] 123 project=XSTARTB state=started"
    ]
    assert report["missing_start"]["settled"][0]["response"] == [
        "[settled-list] 124 no projects found"
    ]
    assert report["missing_start"]["fresh"][0]["response"] == [
        "[fresh-list] 123 project=XSTARTB state=stopped"
    ]
