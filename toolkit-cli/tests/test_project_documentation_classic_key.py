"""Focused classic key documentor cases; synthetic snapshots, no hardware."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_devices as devices
from cbus_toolkit.macros import STAGES

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/experiments/2026-09-30/project-documentor-classic-key-static.json"


def pp(commands=((13, 0, 0, 0),)):
    return {"Application": [56, 255], "DebounceTime": [2], "LongPressTime": [63], "RampRate": [0, 255],
            "GroupAddress": [1, 2, 255, 255, 255], "BlockAllocation": [1] * len(commands),
            "LightLevelStore1": [128, 255, 1, 0], "LightLevelStore2": [0, 254, 2, 3],
            "TimerHighByte": [14, 255, 0, 0], "TimerLowByte": [77, 255, 60, 0],
            "TimerExpiryCommand": [12, 8, 0, 15],
            **{stage: [commands[key][index] for key in range(len(commands))]
               for index, stage in enumerate(STAGES)}}


def network(application=56):
    return doc.Network(254, "Local", "", "", [doc.Application(application, "Lights", "", [
        doc.Group(1, "Kitchen", "", [doc.Level(128, "Evening &<b>scene</b>", 99), doc.Level(30, "Other", 0)]),
        doc.Group(2, "Hall", "", [doc.Level(255, "Full", 12)])])], [])


def render(pps=None, unit_type="KEY1", net=None):
    device = doc.Unit(12, "Key", unit_type, "", "", "1.2.00", "",
                      {name: " ".join(map(str, values)) for name, values in (pp() if pps is None else pps).items()}, {})
    out = doc._Writer()
    status = devices.document_classic_key(out, network() if net is None else net, device)
    start = next((i for i, text in enumerate(out.lines) if text.startswith("<table")), len(out.lines))
    return out, status, out.lines[start:]


def test_on_key_exact_body_timing_and_empty_micro_cell():
    _, status, lines = render()
    assert status == "recovered"
    assert lines == [
        '<table border="1">', '<tr><th>Debounce</th><td>32 ms</td></tr>',
        '<tr><th>Long Press</th><td>1008 ms</td></tr>', '<tr><th>Ramp 1</th><td>Instant</td></tr>',
        '<tr><th>Ramp 2</th><td>4 secs</td></tr>', '</table>', '<br/>', '<table border="1">',
        '<tr><th>Key</th><th>Macro Function</th><th>Micro Functions</th><th>Controls</th></tr>',
        '<tr><td>1</td><td>On</td><td>&nbsp;</td><td><table border="1"><tr><th>Group</th></tr>'
        '<tr><td><a href="#254_56_1">Kitchen</a></td></tr></table></td></tr>', '</table>']


@pytest.mark.parametrize("unit_type,count", devices.CLASSIC_KEY_COUNTS.items())
def test_counts_and_unused_keys_suppress_assigned_group_controls(unit_type, count):
    params = pp(((0, 0, 0, 0),) * count)
    params["GroupAddress"] = [72, 2, 255, 255]  # unused macro never displays unresolved group72
    _, status, lines = render(params, unit_type)
    assert status == "recovered"
    assert lines[9:-1] == [f'<tr><td>{key}</td><td>Unused</td><td>&nbsp;</td><td>&nbsp;</td></tr>'
                           for key in range(1, count + 1)]


def test_custom_all_columns_and_named_preset_lookup_by_address_not_value():
    _, status, lines = render(pp(((12, 6, 7, 1),)))
    assert status == "recovered"
    assert lines[9] == (
        '<tr><td>1</td><td>&#60;Custom&#62;</td><td>'
        '<table border="1"><tr><th>SP</th><th>SR</th><th>LP</th><th>LR</th></tr><tr>'
        '<td>Recall 1</td><td>Recall 2</td><td>Retrigger Timer</td><td>Store 1</td></tr></table></td><td>'
        '<table border="1"><tr><th>Group</th><th>Preset 1</th><th>Preset 2</th><th>Timer</th><th>Expiry</th></tr>'
        '<tr><td><a href="#254_56_1">Kitchen</a></td>'
        '<td><a href="#254_56_1_128">Evening &<b>scene</b></a> (50%)</td><td>0%</td>'
        '<td>1h1m1s</td><td>Recall 1</td></tr></table></td></tr>')


def test_duplicate_groups_use_first_unit_block_even_when_not_assigned_to_key():
    params = pp(((12, 6, 7, 0),))
    params["GroupAddress"] = [1, 1, 2, 1]
    params["BlockAllocation"] = [0b1110]  # first matching block0 is not on this key
    _, status, lines = render(params)
    assert status == "recovered"
    row = lines[9]
    kitchen = '<tr><td><a href="#254_56_1">Kitchen</a></td><td><a href="#254_56_1_128">Evening &<b>scene</b></a> (50%)</td><td>0%</td><td>1h1m1s</td><td>Recall 1</td></tr>'
    assert row.count(kitchen) == 2
    assert row.index(kitchen) < row.index('<a href="#254_56_2">Hall</a>') < row.rindex(kitchen)
    assert '<td>1%</td><td>1%</td><td>0h1m0s</td><td>Idle</td>' in row


@pytest.mark.parametrize("commands", [(11, 7, 0, 7), (13, 7, 15, 0), (13, 8, 13, 8),
                                      (0, 7, 0, 7), (0, 7, 15, 0)])
def test_all_five_native_timer_vectors_and_only_retrigger_adds_timer_column(commands):
    params = pp((commands,))
    params["BlockAllocation"] = [2]
    _, status, lines = render(params)
    assert status == "recovered" and '<td>Timer</td><td>&nbsp;</td>' in lines[9]
    assert ('<th>Timer</th>' in lines[9]) == (7 in commands)
    if 7 in commands:
        assert '<td>18h12m15s</td><td>Off Key</td>' in lines[9]  # unsupported expiry8→Off15


@pytest.mark.parametrize("commands", [(11, 7, 0, 7), (13, 7, 15, 0), (13, 8, 13, 8),
                                      (0, 7, 0, 7), (0, 7, 15, 0)])
def test_timer_macro_load_defaults_only_zero_primary_timer_and_keeps_idle_expiry(commands):
    params = pp((commands,))
    params.update(BlockAllocation=[10], TimerHighByte=[0] * 4,
                  TimerLowByte=[0] * 4, TimerExpiryCommand=[0] * 4)
    unit = doc.Unit(12, "Key", "KEY1", "", "", "1.2.00", "",
                    {name: " ".join(map(str, values)) for name, values in params.items()}, {})
    data = devices.classic_key_data(unit)
    assert data.timers == [0, 300, 0, 0]
    assert data.expiry == [0] * 4  # A real Idle object does not take the nil fallback.
    unit.parameters["TimerLowByte"] = "0 30 0 0"
    assert devices.classic_key_data(unit).timers == [0, 30, 0, 0]
    unit.parameters["BlockAllocation"] = "0"
    unit.parameters["TimerLowByte"] = "0 0 0 0"
    assert devices.classic_key_data(unit).timers == [0] * 4
    unit.parameters["BlockAllocation"] = "2"
    unit.parameters["Application"] = "255"
    assert devices.classic_key_data(unit).timers == [0] * 4  # Rejected template becomes Custom directly.


def test_shared_key_table_keeps_equal_group_addresses_in_separate_applications():
    params = pp(((12, 0, 0, 0),))
    params.update(GroupAddress=[1, 1, 255, 255], BlockAllocation=[3], LightLevelStore1=[128, 255, 0, 0])
    unit = doc.Unit(12, "Key", "KEY1", "", "", "1.2.00", "",
                    {name: " ".join(map(str, values)) for name, values in params.items()}, {})
    net = network()
    net.applications.append(doc.Application(202, "Triggers", "", [
        doc.Group(1, "Modes", "", [doc.Level(255, "All", 0)])]))
    lines = devices.classic_key_lines(net, devices.classic_key_data(unit),
                                      macros=[(26, "Custom")], block_applications=[56, 202, 56, 56])
    row = lines[9]
    assert '<a href="#254_56_1_128">Evening &<b>scene</b></a> (50%)' in row
    assert '<a href="#254_202_1_255">All</a> (100%)' in row
    assert row.index('#254_56_1') < row.index('#254_202_1')


@pytest.mark.parametrize("level,expected", [(0, 0), (1, 1), (2, 1), (127, 50), (128, 50),
                                           (129, 51), (254, 100), (255, 100)])
def test_original_level_percentage_rounding(level, expected):
    params = pp(((0, 12, 9, 0),))
    params["LightLevelStore1"][0] = level
    _, status, lines = render(params, net=doc.Network(254, "", "", "", [
        doc.Application(56, "", "", [doc.Group(1, "Kitchen", "", [])])], []))
    assert status == "recovered" and f'<td>{expected}%</td>' in lines[9]


def test_named_level255_is_linked_and_retains_raw_name():
    params = pp(((0, 12, 9, 0),))
    params["BlockAllocation"] = [2]
    _, status, lines = render(params)
    assert status == "recovered"
    assert '<td><a href="#254_56_2_255">Full</a> (100%)</td>' in lines[9]


@pytest.mark.parametrize("commands,stored1,stored2,label", [
    ((12, 0, 0, 0), 249, 0, "Shutter Toggle"), ((12, 0, 0, 0), 252, 0, "Shutter Open Toggle"),
    ((12, 0, 0, 0), 255, 0, "Shutter Open"), ((6, 0, 0, 0), 0, 2, "Shutter Close Toggle"),
    ((6, 0, 0, 0), 0, 5, "Shutter Stop"), ((9, 0, 0, 0), 0, 0, "Shutter Close"),
    ((12, 0, 0, 0), 128, 0, "&#60;Custom&#62;")])
def test_shutter_rematching_uses_first_assigned_block(commands, stored1, stored2, label):
    params = pp((commands,))
    params["BlockAllocation"] = [10]
    params["LightLevelStore1"][1] = stored1
    params["LightLevelStore2"][1] = stored2
    _, status, lines = render(params)
    assert status == "recovered" and f'<td>{label}</td>' in lines[9]


@pytest.mark.parametrize("commands,label", [((12, 0, 0, 0), "Trigger 1"), ((6, 0, 0, 0), "Trigger 2")])
def test_trigger_application_keeps_trigger_macro_even_at_shutter_levels(commands, label):
    params = pp((commands,))
    params["Application"] = [202, 255]
    params["LightLevelStore1"][0] = 255
    params["LightLevelStore2"][0] = 5
    _, status, lines = render(params, net=network(202))
    assert status == "recovered" and f'<td>{label}</td><td>&nbsp;</td>' in lines[9]


def test_no_blocks_keeps_primary_application_and_suppresses_shutter_remap():
    params = pp(((13, 0, 0, 0), (12, 0, 0, 0)))
    params["BlockAllocation"] = [0, 0]
    params["LightLevelStore1"] = [255] * 4
    _, status, lines = render(params, "KEY2")
    assert status == "recovered"
    assert lines[9] == '<tr><td>1</td><td>On</td><td>&nbsp;</td><td>&nbsp;</td></tr>'
    assert '<td>&#60;Custom&#62;</td>' in lines[10] and 'Shutter' not in lines[10]


def test_application255_macro_subset_only_accepts_unused():
    params = pp(((13, 0, 0, 0), (0, 0, 0, 0)))
    params["Application"] = [255, 255]
    params["BlockAllocation"] = [0, 0]
    _, status, lines = render(params, "KEY2")
    assert status == "recovered"
    assert '<td>&#60;Custom&#62;</td>' in lines[9]
    assert '<td>Unused</td>' in lines[10]


@pytest.mark.parametrize("name,values", [("DebounceTime", [64]), ("LongPressTime", None),
    ("RampRate", [1]), ("GroupAddress", [1]), ("BlockAllocation", []), ("JPCommand", [16]),
    ("LightLevelStore1", [0]), ("TimerHighByte", [256, 0, 0, 0]), ("TimerExpiryCommand", None)])
def test_missing_or_invalid_loader_fields_remain_partial_without_tables(name, values):
    params = pp()
    if values is None:
        del params[name]
    else:
        params[name] = values
    out, status, lines = render(params)
    assert status == "partial" and not lines
    assert name in out.unrecovered[0]["item"]


@pytest.mark.parametrize("unit_type", ["KEYIR4", "KEYAUX4", "KEYBC4", "KEYM4"])
def test_other_classic_and_neo_state_not_silently_admitted(unit_type):
    out, status, lines = render(pp(), unit_type)
    assert status == "partial" and not lines and 'unrecovered classic key class' in out.unrecovered[0]["item"]


def test_unresolved_displayed_group_stays_partial():
    params = pp()
    params["GroupAddress"][0] = 72
    out, status, lines = render(params)
    assert status == "partial" and not lines
    assert 'unresolved Application 56 Group 72' in out.unrecovered[0]["item"]


@pytest.mark.parametrize("ramp,ordinal", [(0, 0), (15, 15), (16, 15), (254, 15), (255, 1)])
def test_native_ramp_conversion(ramp, ordinal):
    params = pp()
    params["RampRate"] = [ramp, ramp]
    _, status, lines = render(params)
    assert status == "recovered"
    assert lines[3] == f'<tr><th>Ramp 1</th><td>{devices.KEY_RAMP_DESCRIPTIONS[ordinal]}</td></tr>'


def test_classic_key_receipt_records_source_only_scope():
    receipt = json.loads(RECEIPT.read_text())
    assert receipt["original_executed"] is False
    assert receipt["original_generated_page_comparison"] == "not_obtained"
    assert all(receipt["checks"].values())
    assert receipt["key_counts"] == devices.CLASSIC_KEY_COUNTS
    assert tuple(receipt["timing_descriptions"]) == devices.KEY_TIMING_DESCRIPTIONS
    assert tuple(receipt["ramp_descriptions"]) == devices.KEY_RAMP_DESCRIPTIONS


@pytest.mark.skipif(not os.environ.get("CBUS_TOOLKIT_EXE"), reason="Requires pinned Toolkit EXE and MAP")
def test_classic_key_static_receipt_reproduces_from_vendor_inputs():
    import sys
    sys.path.insert(0, str(ROOT / "research"))
    from project_documentor_classic_key_static import inspect
    exe = Path(os.environ["CBUS_TOOLKIT_EXE"])
    assert inspect(exe, Path(os.environ.get("CBUS_TOOLKIT_MAP", exe.with_suffix(".map")))) == json.loads(RECEIPT.read_text())
