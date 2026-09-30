"""Focused saved-snapshot fan and error-report output documentor cases."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_special_outputs as special
from cbus_toolkit.project_documentation_usage import action_selector_usage, group_usage

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research/experiments/2026-09-30"
STATIC = EVIDENCE / "project-documentor-special-outputs-static.json"
ORIGINAL = EVIDENCE / "project-documentor-special-outputs-original.json"


def unit(kind="RELDF1", firmware="2.4.00", address=12, **changes):
    pp = {"Application": [56, 255], "GroupAddress": [1], "FanTriggerGroup": [8],
          "StandAloneConfig": [1], "MasterUnitAddress": [22], "LowToMedThresholdLevel": [85],
          "MedToHighThresholdLevel": [170], "LabelOff": "Off        ", "LabelOffLength": [3],
          "LabelLow": "Low        ", "LabelLowLength": [3], "LabelMed": "Medium     ",
          "LabelMedLength": [6], "LabelHigh": "High       ", "LabelHighLength": [4]}
    pp.update(changes)
    return doc.Unit(address, f"Unit {address}", kind, "", "", firmware, "", {
        k: " ".join(map(str, v)) if isinstance(v, (list, tuple)) else v
        for k, v in pp.items() if v is not None}, {})


def network(*units):
    return doc.Network(254, "Local", "", "", [doc.Application(56, "Lighting", "", [
        doc.Group(1, "Fan", "", []), doc.Group(2, "Other", "", []), doc.Group(255, "Unused", "", [])])], list(units))


def render(u, net=None):
    out = doc._Writer()
    status = special.document_fan(out, network(u) if net is None else net, u)
    return out, status


def test_master_body_includes_native_single_channel_without_logic_parameters():
    out, status = render(unit())
    assert status == "recovered" and not out.unrecovered
    start = out.lines.index('<table border="1">')
    assert out.lines[start:start + 6] == ['<table border="1">', '<tr><th>Channel</th><th>Groups</th></tr>',
        '<tr><td>1</td><td><a href="#254_56_1">Fan</a></td></tr>', '</table>', '<br />', '<b>Master Unit</b><br />']
    assert "1% - 34%" in out.lines[-1] and "35% - 67%" in out.lines[-1] and "68% - 100%" in out.lines[-1]
    assert "<td>Medium</td>" in out.lines[-1]
    assert out.lines.count("Unit Address: 12<br />") == 1


@pytest.mark.parametrize("index", range(6))
def test_fan_appendix_matches_executed_original_method(index):
    case = json.loads(ORIGINAL.read_text())["fan_cases"][index]
    master = unit(address=22)
    u = unit(FanTriggerGroup=[8 if case["is_master"] else 255],
             StandAloneConfig=[int(not case["has_master"])], LowToMedThresholdLevel=[case["low_med"]],
             MedToHighThresholdLevel=[case["med_high"]], **{
                 "Label" + speed: case["labels"][key] for speed, key in
                 (("Off", "off"), ("Low", "low"), ("Med", "medium"), ("High", "high"))}, **{
                 "Label" + speed + "Length": [len(case["labels"][key])] for speed, key in
                 (("Off", "off"), ("Low", "low"), ("Med", "medium"), ("High", "high"))})
    expected = case["lines"][1:]
    if case["has_master"]:
        expected = [expected[0], "Master: " + doc.html_unit(network(master), master) + "<br />"]
    assert special.fan_lines(network(u, master), special.fan_data(network(u, master), u)) == expected


def test_slave_link_self_reference_and_no_unused_threshold_requirements():
    u = unit(FanTriggerGroup=[255], StandAloneConfig=[0], MasterUnitAddress=[12],
             LowToMedThresholdLevel=None, LabelOff=None, LabelOffLength=None)
    out, status = render(u)
    assert status == "recovered"
    assert out.lines[-2:] == ['<b>Slave Unit</b><br />',
        'Master: <a href="#254_unit_12">Unit 12 - RELDF1</a><br />']
    assert not any("Fan Speed" in line for line in out.lines)


@pytest.mark.parametrize("candidate", [None, "RELAY1"])
def test_absent_or_nonfan_master_resolves_to_standalone(candidate):
    u = unit(FanTriggerGroup=[255], StandAloneConfig=[0])
    other = [] if candidate is None else [unit(candidate, address=22)]
    out, status = render(u, network(u, *other))
    assert status == "recovered" and '<b>Stand Alone Unit</b><br />' in out.lines


def test_label_length_clamp_and_raw_bmp_markup_are_preserved():
    u = unit(LabelOff="A<&>abcdeféMORE", LabelOffLength=[255],
             LabelLow=" L ", LabelLowLength=[3], LabelHigh="é ", LabelHighLength=[0])
    data = special.fan_data(network(u), u)
    assert data.labels == ("A<&>abcdefé", " L ", "Medium", "")
    assert "A<&>abcdefé" in special.fan_lines(network(u), data)[-1]


@pytest.mark.parametrize("changes", [{"FanTriggerGroup": None}, {"FanTriggerGroup": [1, 2]},
    {"FanTriggerGroup": [255], "StandAloneConfig": None}, {"LowToMedThresholdLevel": [-1]},
    {"LabelOff": None}, {"LabelOffLength": None}, {"LabelHigh": "🙂"}, {"LabelOffLength": [-1]}])
def test_unknown_fan_pp_marks_partial_without_erasing_known_channel(changes):
    out, status = render(unit(**changes))
    assert status == "partial" and out.unrecovered
    assert '<tr><td>1</td><td><a href="#254_56_1">Fan</a></td></tr>' in out.lines


def test_missing_channel_keeps_known_fan_appendix_partial():
    out, status = render(unit(GroupAddress=None))
    assert status == "partial" and out.lines[-1].startswith('<table border="1"><tr><th>Fan Speed')


def test_master_and_standalone_skip_inactive_role_fields():
    assert render(unit(StandAloneConfig=None, MasterUnitAddress=None))[1] == "recovered"
    assert render(unit(FanTriggerGroup=[255], MasterUnitAddress=None))[1] == "recovered"


@pytest.mark.parametrize("firmware", ["", "bad", "2.3.99", "2.7.00", "9", "2.4.1", "2.4.000", "2.4.00.0", "2.4.\u0660\u0661"])
def test_unadmitted_fan_profile_stays_unknown(firmware):
    assert render(unit(firmware=firmware))[1] == "partial"
    assert special.fan_output_usage(unit(firmware=firmware), 56, 1).status == "unrecovered"


def test_all300_canonical_fan_versions_share_explicit_snapshot_projection():
    reference, _ = render(unit())
    start = reference.lines.index('<table border="1">')
    for minor in (4, 5, 6):
        for patch in range(100):
            u = unit(firmware=f"2.{minor}.{patch:02d}")
            out, status = render(u)
            assert status == "recovered" and not out.unrecovered, u.firmware
            assert out.lines[out.lines.index('<table border="1">'):] == reference.lines[start:], u.firmware
            assert special.fan_output_usage(u, 56, 1).html == "Channel 1"


def test_expanded_fan_profile_keeps_missing_pp_unknown_and_resolves_crossversion_slave():
    assert render(unit(firmware="2.6.54", LabelMedLength=None))[1] == "partial"
    master = unit(firmware="2.4.99", address=22)
    slave = unit(firmware="2.5.37", FanTriggerGroup=[255], StandAloneConfig=[0],
                 LabelOff=None, LowToMedThresholdLevel=None)
    out, status = render(slave, network(master, slave))
    assert status == "recovered" and '<b>Slave Unit</b><br />' in out.lines
    assert out.lines[-1] == 'Master: <a href="#254_unit_22">Unit 22 - RELDF1</a><br />'


def test_fan_output_dependency_consumes_only_primary_and_single_group_including255():
    u = unit(GroupAddress=[255], LowToMedThresholdLevel=None, FanTriggerGroup=None)
    assert special.fan_output_usage(u, 56, 255).html == "Channel 1"
    assert special.fan_output_usage(u, 56, 1).html == ""
    u.parameters.pop("GroupAddress")
    assert special.fan_output_usage(u, 57, 255).status == "recovered"
    assert special.fan_output_usage(u, 56, 255).status == "unrecovered"


@pytest.mark.parametrize("kind,count", list(special.ERROR_CHANNELS.items()))
def test_error_output_profiles_and_ordered_duplicate_actions(kind, count):
    u = unit(kind, TriggerErrorGroup=[9], TriggerErrorAcSel=[11], TriggerErrorClearAcSel=[11])
    assert special.special_output_profile(u).indices == tuple(range(count))
    assert special.error_output_action_usage(u, 202, 9, 11, 99).html == (
        '<li />Trigger Error Report<li />Trigger Error Report Clear')
    assert special.error_output_action_usage(u, 202, 9, 99, 11).html == ""


@pytest.mark.parametrize("kind,count", list(special.ERROR_CHANNELS.items()))
def test_error_output_body_dispatch_uses_complete_per_channel_logic_arrays(kind, count):
    u = unit(kind, GroupAddress=[1] * 12 + [2, 255, 255, 255],
             LogicFunction=[1] * count, **{
                 f"LogicGA{group}Associations": [int(group == 13)] * count
                 for group in range(13, 17)})
    net, out = network(u), doc._Writer()
    record = doc.document_unit(out, net, u, doc.ProjectModel("Synthetic", [net]))
    assert record["status"] == "recovered" and not out.unrecovered
    assert '<tr><th>Channel</th><th>Groups</th><th>Logic Function</th></tr>' in out.lines
    rows = [line for line in out.lines if line.startswith('<tr><td>')]
    assert len(rows) == count
    assert all('Fan</a>' in row and 'Other</a>' in row and '<td>Max</td>' in row for row in rows)
    u.parameters["LogicGA13Associations"] = "0"
    assert doc.document_unit(doc._Writer(), net, u, doc.ProjectModel("Synthetic", [net]))["status"] == "partial"


@pytest.mark.parametrize("index", range(4))
def test_error_actions_match_executed_original_method(index):
    case = json.loads(ORIGINAL.read_text())["error_action_cases"][index]
    u = unit("DIMDU4", TriggerErrorGroup=[9], TriggerErrorAcSel=[11 if case["report_match"] else 22],
             TriggerErrorClearAcSel=[11 if case["clear_match"] else 22])
    assert special.error_output_action_usage(u, 202, 9, 11, 222).html == case["html"]


def test_error_group_gates_missing_fields_but_selector255_is_real_address():
    u = unit("DIMPR6A", TriggerErrorGroup=[255], TriggerErrorAcSel=None, TriggerErrorClearAcSel=None)
    assert special.error_output_action_usage(u, 202, 255, 255, 0).status == "recovered"
    u.parameters["TriggerErrorGroup"] = "8"
    assert special.error_output_action_usage(u, 202, 9, 255, 0).status == "recovered"
    assert special.error_output_action_usage(u, 56, 8, 255, 0).status == "recovered"
    u.parameters["TriggerErrorAcSel"] = "255"
    result = special.error_output_action_usage(u, 202, 8, 255, 0)
    assert result.status == "partial" and result.html == '<li />Trigger Error Report'
    assert "TriggerErrorClearAcSel" in result.missing[0]


def test_error_other_group_has_no255_sentinel_and_no_error_mode_gate():
    u = unit("DIMDU4", EnableErrorGroup=[255])
    assert special.error_output_other_usage(u, 203, 255).html == "Error Report Enable Group"
    assert special.error_output_other_usage(u, 56, 255).html == ""
    u.parameters.pop("EnableErrorGroup")
    assert special.error_output_other_usage(u, 203, 255).status == "unrecovered"


def test_dispatch_uses_fan_body_error_actions_and_other_dependencies():
    out, net, u = doc._Writer(), network(), unit()
    assert doc.document_unit(out, net, u, doc.ProjectModel("Test", [net]))["status"] == "recovered"
    assert '<b>Master Unit</b><br />' in out.lines
    assert group_usage(u, 56, 1, "output").html == "Channel 1"
    e = unit("DIMDU4", TriggerErrorGroup=[9], TriggerErrorAcSel=[11], TriggerErrorClearAcSel=[22], EnableErrorGroup=[5])
    assert action_selector_usage(e, "ErrorReportOutput", 202, 9, 11, 222).html == '<li />Trigger Error Report'
    assert group_usage(e, 203, 5, "other").html == "Error Report Enable Group"


def test_source_and_original_boundaries_are_explicit():
    static, original = json.loads(STATIC.read_text()), json.loads(ORIGINAL.read_text())
    assert all(static["checks"].values()) and not static["original_executed"]
    assert static["original_generated_page_comparison"] == "not_obtained"
    assert static["fan_firmware_ranges"] == [list(pair) for pair in special.FAN_FIRMWARE_RANGES]
    assert static["native_firmware_continuum_acceptance"] == "unassessed"
    assert original["original_methods_executed"] and not original["original_loader_executed"]
    assert not original["original_generated_page_compared"]


@pytest.mark.skipif(not os.environ.get("CBUS_TOOLKIT_EXE") or not os.environ.get("CBUS_UNITSPEC_DIR"),
                    reason="Requires pinned Toolkit EXE/MAP and RELDF1 specification")
def test_static_receipt_regenerates():
    sys.path.insert(0, str(ROOT / "research"))
    from project_documentor_special_outputs_static import inspect
    exe = Path(os.environ["CBUS_TOOLKIT_EXE"])
    assert inspect(exe, Path(os.environ.get("CBUS_TOOLKIT_MAP", exe.with_suffix(".map"))),
                   Path(os.environ["CBUS_UNITSPEC_DIR"]) / "RELDF1.xml") == json.loads(STATIC.read_text())


@pytest.mark.skipif(not os.environ.get("CBUS_TOOLKIT_EXE") or os.environ.get("CBUS_RUN_DOCUMENTOR_ORIGINAL") != "1",
                    reason="Requires pinned Toolkit inputs and permitted JIT memory")
def test_original_receipt_regenerates(tmp_path):
    exe = Path(os.environ["CBUS_TOOLKIT_EXE"])
    output = tmp_path / "special.json"
    subprocess.run([sys.executable, str(ROOT / "research/project_documentor_special_outputs_original.py"),
                    "--exe", str(exe), "--map", os.environ.get("CBUS_TOOLKIT_MAP", str(exe.with_suffix(".map"))),
                    "--output", str(output)], check=True, capture_output=True, timeout=40)
    assert json.loads(output.read_text()) == json.loads(ORIGINAL.read_text())
