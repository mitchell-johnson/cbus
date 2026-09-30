"""Focused synthetic cases for the statically recovered per-device HTML bodies."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_devices as devices

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/experiments/2026-09-30/project-documentor-devices-static.json"


def unit(unit_type="RELAY4", **pps):
    return doc.Unit(12, "Test", unit_type, "", "", "4.4.00", "",
                    {name: " ".join(map(str, values)) for name, values in pps.items()}, {})


def network():
    return doc.Network(254, "Local", "", "", [doc.Application(56, "Lighting", "", [
        doc.Group(1, "Kitchen", "", []), doc.Group(2, "Hall", "", []),
        doc.Group(255, "Unused", "", [])])], [])


def classic_pp(count=4):
    return {"Application": [56, 255], "GroupAddress": [1, 2, 255, 255, 255, 40],
            "LogicFunctionAndPowerUpDelay": [254, 255, 2, 3][:count],
            **{f"LogicGA{slot}Associations": [0] * count for slot in range(6)}}


def render(renderer, device):
    out = doc._Writer()
    status = renderer(out, network(), device)
    start = next((i for i, text in enumerate(out.lines) if text.startswith("<table")), len(out.lines))
    return out, status, out.lines[start:]


@pytest.mark.parametrize("unit_type,count", list(devices.CLASSIC_OUTPUT_CHANNELS.items()))
def test_classic_output_channel_counts_and_empty_cells(unit_type, count):
    _, status, lines = render(devices.document_classic_output, unit(unit_type, **classic_pp(count)))
    assert status == "recovered"
    assert lines == ['<table border="1">',
                     "<tr><th>Channel</th><th>Groups</th><th>Logic Function</th></tr>",
                     *[f"<tr><td>{channel}</td><td>&nbsp;</td><td>&nbsp;</td></tr>"
                       for channel in range(1, count + 1)], "</table>", "<br />"]


def test_classic_group_order_duplicates_ga5_quirk_and_function_low_bit():
    pp = classic_pp()
    pp["LogicGA0Associations"] = [1, 1, 1, 0]
    pp["LogicGA1Associations"] = [1, 1, 0, 0]
    pp["LogicGA5Associations"] = [1, 0, 0, 0]
    # A nonzero association to an unused group is omitted, not a group 255 link.
    pp["LogicGA2Associations"] = [1, 1, 1, 1]
    _, status, lines = render(devices.document_classic_output, unit(**pp))
    assert status == "recovered"
    kitchen = '<a href="#254_56_1">Kitchen</a>'
    hall = '<a href="#254_56_2">Hall</a>'
    assert lines[2:6] == [
        f"<tr><td>1</td><td>{kitchen}, {hall}, {kitchen}</td><td>Min</td></tr>",
        f"<tr><td>2</td><td>{kitchen}, {hall}</td><td>Max</td></tr>",
        f"<tr><td>3</td><td>{kitchen}</td><td>&nbsp;</td></tr>",
        "<tr><td>4</td><td>&nbsp;</td><td>&nbsp;</td></tr>"]


def test_classic_ga5_can_display_unused_slot_zero_and_nonboolean_association_is_true():
    pp = classic_pp(1)
    pp["GroupAddress"][0] = 255
    pp["LogicGA5Associations"] = [2]
    _, status, lines = render(devices.document_classic_output, unit("RELAY1", **pp))
    assert status == "recovered"
    assert lines[2] == "<tr><td>1</td><td>Unused</td><td>&nbsp;</td></tr>"


@pytest.mark.parametrize("name,values", [("Application", []), ("GroupAddress", [1, 2]),
                                         ("LogicGA3Associations", None),
                                         ("LogicFunctionAndPowerUpDelay", [0, 0, 0]),
                                         ("LogicGA0Associations", [-1, 0, 0, 0])])
def test_classic_missing_or_invalid_consumed_pp_never_becomes_default(name, values):
    pp = classic_pp()
    if values is None:
        pp.pop(name)
    else:
        pp[name] = values
    out, status, lines = render(devices.document_classic_output, unit(**pp))
    assert status == "partial" and not lines
    assert name in out.unrecovered[0]["item"]
    assert out.lines[0] == "Unit Address: 12<br />"


def dmx_pp():
    return {"Application": [56, 255], "GroupAddress": [1, 2, 1] + [255] * 9,
            **{f"DMXSlotMapping{bank}": [0] * 32 for bank in range(1, 17)}}


def test_dmx_slot_order_shared_groups_duplicate_rows_and_original_prefix():
    pp = dmx_pp()
    pp["DMXSlotMapping1"][0:4] = [2, 1, 3, 12]
    pp["DMXSlotMapping2"][0] = 1
    pp["DMXSlotMapping16"][31] = 2
    _, status, lines = render(devices.document_dmx_gateway, unit("DMXDO12", **pp))
    assert status == "recovered"
    first = '</td></tr><tr><td><a href="#254_56_1">Kitchen</a></td><td>2, 3, 33'
    assert lines == ['<table border="1"><tr><th>Group</th><th>DMX Slots</th></tr>', first,
                     '</td></tr><tr><td><a href="#254_56_2">Hall</a></td><td>1, 512', first, "</table>"]


def test_dmx_explicit_zero_mappings_omit_rows_without_guessing():
    _, status, lines = render(devices.document_dmx_gateway, unit("DMXDO12", **dmx_pp()))
    assert status == "recovered"
    assert lines == ['<table border="1"><tr><th>Group</th><th>DMX Slots</th></tr>', "</table>"]


@pytest.mark.parametrize("bank,values", [(1, None), (4, [0] * 31), (16, [13] + [0] * 31)])
def test_dmx_incomplete_or_out_of_range_mapping_stays_partial(bank, values):
    pp = dmx_pp()
    if values is None:
        pp.pop(f"DMXSlotMapping{bank}")
    else:
        pp[f"DMXSlotMapping{bank}"] = values
    out, status, lines = render(devices.document_dmx_gateway, unit("DMXDO12", **pp))
    assert status == "partial" and not lines
    assert f"DMXSlotMapping{bank}" in out.unrecovered[0]["item"]


def test_device_static_receipt_is_source_only_and_records_original_quirks():
    receipt = json.loads(RECEIPT.read_text())
    assert receipt["original_executed"] is False
    assert receipt["original_generated_page_comparison"] == "not_obtained"
    assert all(receipt["checks"].values())
    assert receipt["classic_channel_counts"] == devices.CLASSIC_OUTPUT_CHANNELS
    assert receipt["dmx_channel_count"] == devices.DMX_CHANNELS


@pytest.mark.skipif(not os.environ.get("CBUS_TOOLKIT_EXE"), reason="Requires pinned Toolkit EXE and MAP")
def test_device_static_receipt_reproduces_from_vendor_inputs():
    import sys
    sys.path.insert(0, str(ROOT / "research"))
    from project_documentor_devices_static import inspect
    exe = Path(os.environ["CBUS_TOOLKIT_EXE"])
    assert inspect(exe, Path(os.environ.get("CBUS_TOOLKIT_MAP", exe.with_suffix(".map")))) == json.loads(
        RECEIPT.read_text())


@pytest.mark.parametrize("kind", ["ClassicOutput", "DMXGateway"])
def test_missing_displayed_group_is_partial_instead_of_fabricated_label(kind):
    if kind == "ClassicOutput":
        pp = classic_pp()
        pp["GroupAddress"][0] = 72
        pp["LogicGA0Associations"][0] = 1
        device = unit(**pp)
    else:
        pp = dmx_pp()
        pp["GroupAddress"][0] = 72
        pp["DMXSlotMapping1"][0] = 1
        device = unit("DMXDO12", **pp)
    out, status, lines = render(devices.DOCUMENTORS[kind], device)
    assert status == "partial" and not lines
    assert "unresolved Application 56 Group 72" in out.unrecovered[0]["item"]
