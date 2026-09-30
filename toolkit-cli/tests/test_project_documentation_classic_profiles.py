"""Synthetic report-only profiles; no device edits, hardware or default PP."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_classic_profiles as profiles
from cbus_toolkit.macros import STAGES

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/experiments/2026-09-30/project-documentor-classic-profiles-static.json"


def make_unit(typ="KEYIR1", commands=None, firmware="1.2.67", **overrides):
    commands = commands or ((0, 0, 0, 0),) * profiles.CLASSIC_PROFILE_COUNTS.get(typ, 4)
    pp = {"Application": [56, 255], "DebounceTime": [2], "LongPressTime": [3], "RampRate": [0, 255],
          "GroupAddress": [1, 2, 255, 255], "BlockAllocation": [1] * len(commands),
          "LightLevelStore1": [128, 255, 249, 0], "LightLevelStore2": [0, 5, 2, 0],
          "TimerHighByte": [0] * 4, "TimerLowByte": [0] * 4, "TimerExpiryCommand": [0] * 4,
          **{stage: [command[index] for command in commands] for index, stage in enumerate(STAGES)}}
    pp.update(overrides)
    return doc.Unit(12, "Key", typ, "", "", firmware, "",
                    {name: " ".join(map(str, values)) for name, values in pp.items() if values is not None}, {})


def render(unit):
    network = doc.Network(254, "Local", "", "", [
        doc.Application(app, "App", "", [doc.Group(1, "Kitchen", "", []), doc.Group(2, "Hall", "", [])])
        for app in (56, 202, 255)], [])
    out = doc._Writer()
    status = profiles.document_classic_profile(out, network, unit)
    start = next((i for i, line in enumerate(out.lines) if line.startswith("<table")), len(out.lines))
    return out, status, out.lines[start:]


@pytest.mark.parametrize("typ,count", profiles.CLASSIC_PROFILE_COUNTS.items())
def test_original_counts_physical_numbering_and_no_bistable_column(typ, count):
    out, status, lines = render(make_unit(typ))
    assert status == "recovered" and not out.unrecovered
    assert lines[8] == '<tr><th>Key</th><th>Macro Function</th><th>Micro Functions</th><th>Controls</th></tr>'
    assert lines[9:-1] == [f'<tr><td>{key}</td><td>Unused</td><td>&nbsp;</td><td>&nbsp;</td></tr>'
                           for key in range(1, count + 1)]
    assert lines[-1] == "</table>"


@pytest.mark.parametrize("typ", profiles.CLASSIC_PROFILE_COUNTS)
@pytest.mark.parametrize("firmware", ("", "unknown", "1.x.67", "-1", "10.0.0"))
def test_unknown_firmware_cannot_select_original_class(typ, firmware):
    out, status, lines = render(make_unit(typ, firmware=firmware))
    assert status == "partial" and not lines
    assert "class/firmware" in out.unrecovered[0]["item"]


@pytest.mark.parametrize("typ", profiles.CLASSIC_PROFILE_COUNTS)
def test_every_profile_requires_consumed_values_including_full_four_blocks(typ):
    out, status, lines = render(make_unit(typ, LightLevelStore1=[128, 255]))
    assert status == "partial" and not lines
    assert "LightLevelStore1" in out.unrecovered[0]["item"]


@pytest.mark.parametrize("typ", ("KEYAUX4", "DINAUX4"))
@pytest.mark.parametrize("app,label", ((56, "Aux On/Off"), (202, "Aux On/Off"), (255, "&#60;Custom&#62;")))
def test_aux_reconciliation_and_application_subset(typ, app, label):
    unit = make_unit(typ, ((13, 15, 0, 15),) * 4, Application=[app, 255])
    data, macros = profiles.classic_profile_data(unit)
    _, status, lines = render(unit)
    assert status == "recovered" and f"<td>{label}</td>" in lines[9]
    assert data.commands == [(13, 15, 0, 15)] * 4
    assert macros == [((26, "<Custom>") if app == 255 else (28, "Aux On/Off"))] * 4


@pytest.mark.parametrize("typ", ("KEYIR1", "KEYIR4", "KEYBC2", "KEYBC4", "BCNC4A", "BCNC4B"))
def test_non_aux_bell_press_is_not_relabelled(typ):
    count = profiles.CLASSIC_PROFILE_COUNTS[typ]
    _, status, lines = render(make_unit(typ, ((13, 15, 0, 15),) * count))
    assert status == "recovered" and "<td>Bell Press</td>" in lines[9]


@pytest.mark.parametrize("typ", ("KEYAUX4", "DINAUX4", "BCNC4A", "BCNC4B"))
def test_timer_event_defaults_primary_only_without_changing_loaded_idle_expiry(typ):
    device = make_unit(typ, ((11, 7, 0, 7), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0)),
                       BlockAllocation=[3, 0, 0, 0])
    data, _ = profiles.classic_profile_data(device)
    assert data.timers == [300, 0, 0, 0] and data.expiry == [0] * 4
    _, status, lines = render(device)
    assert status == "recovered" and "<td>0h5m0s</td><td>Idle</td>" in lines[9]


@pytest.mark.parametrize("typ", ("BCNC4A", "BCNC4B"))
def test_bcnc_report_preserves_custom_snapshot_instead_of_running_save_defaults(typ):
    device = make_unit(typ, ((12, 6, 7, 1),) * 4)
    before = dict(device.parameters)
    _, status, lines = render(device)
    assert status == "recovered" and "&#60;Custom&#62;" in lines[9]
    assert "<td>Store 1</td>" in lines[9] and device.parameters == before


@pytest.mark.parametrize("typ", ("KEYCIR1", "KEYCIR4", "KEYC1", "KEYC2", "KEYC4"))
def test_neopro_classic_cannot_be_misclassified_as_plain_classic(typ):
    out, status, lines = render(make_unit(typ, firmware="2.5.00"))
    assert status == "partial" and not lines and out.unrecovered


def test_classic_profile_receipt_boundary_and_checks():
    receipt = json.loads(RECEIPT.read_text())
    assert receipt["original_executed"] is False
    assert receipt["original_generated_page_comparison"] == "not_obtained"
    assert receipt["classic_profile_counts"] == profiles.CLASSIC_PROFILE_COUNTS
    assert all(receipt["checks"].values())
    assert receipt["aux_macro_comparison"]["equal"]


def test_classic_profile_receipt_reproduces_when_original_supplied():
    exe, map_file = os.environ.get("CBUS_TOOLKIT_EXE"), os.environ.get("CBUS_TOOLKIT_MAP")
    if not exe or not map_file:
        pytest.skip("explicit pinned original Toolkit EXE/MAP required")
    import sys
    sys.path.insert(0, str(ROOT / "research"))
    from project_documentor_classic_profiles_static import inspect
    assert inspect(Path(exe), Path(map_file)) == json.loads(RECEIPT.read_text())
