"""Focused complete-snapshot classic DLT documentor cases."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_dlt as dlt

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research/experiments/2026-09-30"


def complete_pp():
    return {"Application": [56, 57], "GroupAddress": [1, 2] + [255] * 7,
        "DebounceTime": [3], "LongPressTime": [25], "RampRate": [1, 2],
        "BlockAllocation": [1 << index for index in range(8)],
        "LightLevelStore1": [128] * 8, "LightLevelStore2": [255] * 8,
        "TimerHighByte": [0] * 8, "TimerLowByte": [0] * 8, "TimerExpiryCommand": [15] * 8,
        "JPCommand": [1] * 8, "SRCommand": [0] * 8, "LPCommand": [0] * 8, "LRCommand": [0] * 8,
        "SecondApplicationBlocks": [2], "JoinPrimaryApplication": [255],
        "DualJoinPrimaryApplication": [255], "JoinSecondaryApplication": [255],
        "DualJoinSecondaryApplication": [255], "SceneKeySelector": [0] * 8,
        "IndicatorBlockAssignment": [0] * 8, "ControlAppGroupAddress": [4],
        "SceneTable": [255] * 80, "SceneTablePointer": [162, 182, 202, 222, 255, 255, 255, 255],
        "EnableDynamicLabels": [1]}


def unit(kind="KEYBL5", firmware="3.0.00", pp=None):
    pp = complete_pp() if pp is None else pp
    return doc.Unit(12, "DLT", kind, "", "", firmware, "",
                    {name: " ".join(map(str, values)) for name, values in pp.items()}, {})


def network():
    return doc.Network(254, "Local", "", "", [
        doc.Application(56, "Lighting", "", [doc.Group(1, "Kitchen", "", [])]),
        doc.Application(57, "Secondary", "", [doc.Group(2, "Hall", "", [])]),
        doc.Application(202, "Trigger", "", [doc.Group(4, "Scenes", "", [doc.Level(171, "Evening", 3)])]),
    ], [])


def render(device):
    out = doc._Writer()
    status = dlt.document_dlt(out, network(), device)
    return out, status


@pytest.mark.parametrize("kind", dlt.DLT_TYPES)
@pytest.mark.parametrize("enabled,suffix", [(0, "Labels: Static"), (1, "Labels: Dynamic")])
def test_complete_dlt_profile_renders_all_eight_keys_then_exact_suffix(kind, enabled, suffix):
    pp = complete_pp()
    pp["EnableDynamicLabels"] = [enabled]
    out, status = render(unit(kind, pp=pp))
    assert status == "recovered" and not out.unrecovered
    assert out.lines.count("Unit Address: 12<br />") == 1
    assert out.lines[-2:] == ["</table>", suffix]
    rows = [line for line in out.lines if line.startswith("<tr><td>")]
    assert len(rows) == 8
    assert [row.split("</td>", 1)[0] for row in rows] == [f"<tr><td>{index}" for index in range(1, 9)]
    assert '<a href="#254_56_1">Kitchen</a>' in rows[0]
    assert '<a href="#254_57_2">Hall</a>' in rows[1]
    assert "IR Key" not in "".join(rows) and "Virtual Key" not in "".join(rows)
    assert "Scenes<br />" not in out.lines


def test_dlt_scene_body_precedes_suffix_and_trigger_uses_address_not_value():
    pp = complete_pp()
    pp["SceneTable"][:2] = [1, 128]
    pp["GroupAddress"][0] = 255
    pp["SceneKeySelector"][0] = 1
    pp["JPCommand"][0], pp["SRCommand"][0], pp["LPCommand"][0], pp["LRCommand"][0] = 14, 3, 10, 11
    out, status = render(unit(pp=pp))
    assert status == "recovered"
    assert out.lines[-1] == "Labels: Dynamic"
    assert out.lines[-2] == "</table>"
    assert "Scenes<br />" in out.lines
    assert out.lines[-3] == ('<tr><td>1</td><td><table border="1"><tr><th>Action Selector</th>'
        '<th>Ramp Rate</th></tr><tr><td><a href="#254_202_4_171">Evening</a></td>'
        '<td>12 secs</td></tr></table></td><td><a href="#254_56_1">Kitchen</a></td><td>50%</td></tr>')


@pytest.mark.parametrize("values", [None, [], [0, 1], [2], [-1], ["true"], ["invalid"]])
def test_missing_or_ambiguous_flag_does_not_claim_label_mode(values):
    pp = complete_pp()
    if values is None:
        pp.pop("EnableDynamicLabels")
    else:
        pp["EnableDynamicLabels"] = values
    out, status = render(unit(pp=pp))
    assert status == "partial"
    assert not any(line.startswith("Labels:") for line in out.lines)
    assert out.unrecovered and "DLT labels:" in out.unrecovered[-1]["item"]
    assert '<a href="#254_56_1">Kitchen</a>' in "".join(out.lines)


@pytest.mark.parametrize("field,values", [("BlockAllocation", None), ("SceneTable", [255] * 79),
    ("JoinPrimaryApplication", [1]), ("SceneKeySelector", [1] + [0] * 7)])
def test_inherited_unknown_never_promoted_by_known_label_mode(field, values):
    pp = complete_pp()
    if values is None:
        pp.pop(field)
    else:
        pp[field] = values
    out, status = render(unit(pp=pp))
    assert status == "partial" and out.unrecovered
    assert out.lines[-1] == "Labels: Dynamic"


@pytest.mark.parametrize("kind,firmware", [("KEYGL5", "3.0.00"), ("KEYBL5", "2.1.00"),
    ("KEYML5", ""), ("KEYDL4", "3.0.01")])
def test_unadmitted_dlt_profile_is_explicitly_partial(kind, firmware):
    out, status = render(unit(kind, firmware))
    assert status == "partial" and "unrecovered DLT class/firmware" in out.unrecovered[0]["item"]
    assert not any(line.startswith("Labels:") for line in out.lines)


def test_public_documentor_dispatch_uses_complete_dlt_body():
    device, net = unit(), network()
    out = doc._Writer()
    info = doc.document_unit(out, net, device, doc.ProjectModel("Test", [net]))
    assert info["status"] == "recovered"
    assert "Labels: Dynamic" in out.lines


def test_frozen_source_receipt_and_original_wrapper_observations():
    static = json.loads((RESEARCH / "project-documentor-dlt-static.json").read_text())
    assert all(static["checks"].values()) and static["original_executed"] is False
    assert static["types"] == list(dlt.DLT_TYPES)
    assert static["admitted_firmware"] == dlt.DLT_FIRMWARE
    original = json.loads((RESEARCH / "project-documentor-dlt-original-leaf.json").read_text())
    assert static["original_generated_page_comparison"] == original["original_generated_page_comparison"] == "not_obtained"
    assert len(original["observations"]) == 4
    for row in original["observations"]:
        assert row["calls"][0] == "inherited_neopro"
        if row["is_dlt"]:
            device = unit(pp={"EnableDynamicLabels": [int(not row["blocked"])]})
            assert dlt.dlt_label_mode(device) == row["lines"][-1]
        else:
            assert row["lines"] == ["<synthetic inherited body>"]


@pytest.mark.skipif(not os.environ.get("CBUS_TOOLKIT_EXE") or not os.environ.get("CBUS_UNITSPEC_DIR"),
                    reason="Requires explicit pinned Toolkit EXE/MAP and decoded specs")
def test_source_receipt_regenerates():
    sys.path.insert(0, str(ROOT / "research"))
    from project_documentor_dlt_static import inspect
    exe = Path(os.environ["CBUS_TOOLKIT_EXE"])
    assert inspect(exe, Path(os.environ.get("CBUS_TOOLKIT_MAP", exe.with_suffix(".map"))),
                   Path(os.environ["CBUS_UNITSPEC_DIR"])) == json.loads(
        (RESEARCH / "project-documentor-dlt-static.json").read_text())


@pytest.mark.skipif(not os.environ.get("CBUS_TOOLKIT_EXE")
                    or os.environ.get("CBUS_RUN_DOCUMENTOR_ORIGINAL") != "1",
                    reason="Requires explicit pinned Toolkit inputs and executable JIT memory")
def test_original_wrapper_receipt_regenerates(tmp_path):
    exe = Path(os.environ["CBUS_TOOLKIT_EXE"])
    output = tmp_path / "dlt-original.json"
    subprocess.run([sys.executable, str(ROOT / "research/project_documentor_dlt_original.py"),
                    "--executable", str(exe), "--map", os.environ.get("CBUS_TOOLKIT_MAP", str(exe.with_suffix(".map"))),
                    "--output", str(output)], check=True, timeout=30, capture_output=True)
    assert json.loads(output.read_text()) == json.loads(
        (RESEARCH / "project-documentor-dlt-original-leaf.json").read_text())
