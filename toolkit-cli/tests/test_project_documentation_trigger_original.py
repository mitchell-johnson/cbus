"""Compare the trigger wrapper against captured original-instruction execution.

Leaf action strings are explicit inputs on both sides, so these tests assess
root traversal/nesting only, independently of per-device action projections.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_usage as usage

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/fixtures/project-documentor-trigger-original.json"


def _receipt():
    return json.loads(RECEIPT.read_text())


@pytest.mark.parametrize("index", range(6))
def test_trigger_wrapper_matches_original_instruction_capture(monkeypatch, index):
    case = _receipt()["cases"][index]
    levels = [doc.Level(level["address"], level["tag"], level["value"]) for level in case["levels"]]
    group = doc.Group(case["group"], case["tag"], case["description"], levels)
    application = doc.Application(202, "Trigger Control", "", [group])
    units = [doc.Unit(row["address"], row["tag"], row["type"], "", "", row["firmware"], "", {}, {})
             for row in case["units"]]
    # Preserve explicit manager order to isolate wrapper traversal from the
    # renderer's separately documented numeric-order snapshot adaptation.
    network = doc.Network(case["network"], "Network", "", "", [application], units)
    model = doc.ProjectModel("SYNTHETIC", [network])
    actions = []

    def action(unit, _documentor, application_number, group_number, address, value):
        assert (application_number, group_number) == (202, case["group"])
        actions.append({"unit": unit.address, "address": address, "value": value})
        return usage.Usage(case["action_html"].get(f"{address}/{unit.address}", ""))

    monkeypatch.setattr(usage, "action_selector_usage", action)
    writer = doc._Writer()
    doc._group(writer, network, application, group, model)
    assert writer.lines == case["result"]["lines"], case["name"]
    assert actions == case["result"]["action_calls"], case["name"]
    assert case["result"]["factory_calls"] == [
        {"type": row["type"], "firmware": row["firmware"]}
        for _level in case["levels"] for row in case["units"]]
    assert writer.unrecovered == []


def test_trigger_capture_boundary_and_source_identity():
    evidence = _receipt()
    assert evidence["format"] == "cbus-project-documentor-trigger-original-v1"
    assert evidence["exe_sha256"] == "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab"
    assert evidence["map_sha256"] == "f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb"
    assert evidence["original_wrapper_instructions_executed"]
    assert not evidence["original_factory_or_action_methods_executed"]
    assert not evidence["original_generated_page_compared"]
    assert len(evidence["cases"]) == 6


def test_trigger_original_capture_reproduces_when_configured(tmp_path):
    executable = os.environ.get("CBUS_TOOLKIT_EXE")
    if not executable or os.environ.get("CBUS_RUN_DOCUMENTOR_ORIGINAL") != "1":
        pytest.skip("Set CBUS_TOOLKIT_EXE and CBUS_RUN_DOCUMENTOR_ORIGINAL=1 for original trigger-wrapper probe")
    exe = Path(executable)
    map_file = Path(os.environ.get("CBUS_TOOLKIT_MAP", exe.with_suffix(".map")))
    evidence = _receipt()
    assert hashlib.sha256(exe.read_bytes()).hexdigest() == evidence["exe_sha256"]
    output = tmp_path / "trigger.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "research/project_documentor_trigger_original.py"),
         "--executable", str(exe), "--map-file", str(map_file), "--output", str(output)],
        text=True, capture_output=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(output.read_text()) == evidence
