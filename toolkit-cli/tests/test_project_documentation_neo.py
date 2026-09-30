"""Neo report bodies use synthetic complete PP snapshots and pinned receipts."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_neo as neo
from cbus_toolkit.macros import STAGES

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/experiments/2026-09-30/project-documentor-neo-static.json"


def pp():
    return {"Application": [56, 202], "DebounceTime": [2], "LongPressTime": [63], "RampRate": [0, 255],
            "GroupAddress": [1, 2] + [255] * 7, "BlockAllocation": [1, 2] + [0] * 6,
            "LightLevelStore1": [64, 255] + [0] * 6, "LightLevelStore2": [128] * 8,
            "TimerHighByte": [0] * 8, "TimerLowByte": [30] * 8, "TimerExpiryCommand": [15] * 8,
            "SceneKeySelector": [0] * 8, "IndicatorBlockAssignment": list(range(8)),
            "SceneTable": [255] * 80, "SceneTablePointer": [162, 182, 202, 222, 255, 255, 255, 255],
            "ControlAppGroupAddress": [9], "SecondApplicationBlocks": [0], "KeyMask": [1],
            **{name: [255] for name in neo.JOIN_PARAMETERS},
            **{stage: [13, 15, 0, 0, 0, 0, 0, 0] if index == 0 else [0] * 8
               for index, stage in enumerate(STAGES)}}


def unit(params=None, typ="KEYM8", firmware="2.5.00"):
    return doc.Unit(12, "Neo", typ, "", "", firmware, "",
                    {name: " ".join(map(str, values)) for name, values in (pp() if params is None else params).items()}, {})


def network():
    return doc.Network(254, "Local", "", "", [
        doc.Application(56, "Lighting", "", [doc.Group(1, "Kitchen", "", [doc.Level(64, "Low", 99)]),
                                                  doc.Group(2, "Hall", "", [])]),
        doc.Application(202, "Trigger", "", [doc.Group(1, "Mode", "", []),
            doc.Group(9, "Scenes", "", [doc.Level(66, "Dinner &<b>party</b>", 2), doc.Level(67, "Away", 66)]),
            doc.Group(255, "Unused", "", [doc.Level(66, "Disabled trigger", 1)])])], [])


def body(params=None, typ="KEYM8", firmware="2.5.00", net=None):
    out = doc._Writer()
    result = neo.document_neo(out, network() if net is None else net, unit(params, typ, firmware))
    start = next((i for i, line in enumerate(out.lines) if line.startswith("<table")), len(out.lines))
    return out, result, out.lines[start:]


def bind_scene(params, key, scene, ramp, selector):
    params["SceneKeySelector"][key] = 1
    params["IndicatorBlockAssignment"][key] = scene
    for stage, value in zip(STAGES, (14, ramp, selector >> 4, selector & 15)):
        params[stage][key] = value
    params["BlockAllocation"][key] = 1 << key
    params["GroupAddress"][key] = 255
    params["SecondApplicationBlocks"][0] &= ~(1 << key)


@pytest.mark.parametrize("firmware,is_pro", [("1.3.01", False), ("1.5.02", False), ("1.5.03", True), ("2.9.99", True)])
def test_keym8_profiles_and_exact_empty_scene_body(firmware, is_pro):
    params = pp()
    if not is_pro:
        params["Application"] = [56]
        for field in (*neo.JOIN_PARAMETERS, "SecondApplicationBlocks"):
            del params[field]
    data = neo.neo_data(unit(params, firmware=firmware))
    assert data.is_pro is is_pro and data.physical_key_count == 8
    _, status, lines = body(params, firmware=firmware)
    assert status == "recovered" and len(lines) == 18
    assert lines[:9] == ['<table border="1">', '<tr><th>Debounce</th><td>32 ms</td></tr>',
        '<tr><th>Long Press</th><td>1008 ms</td></tr>', '<tr><th>Ramp 1</th><td>Instant</td></tr>',
        '<tr><th>Ramp 2</th><td>4 secs</td></tr>', '</table>', '<br/>', '<table border="1">',
        '<tr><th>Key</th><th>Macro Function</th><th>Micro Functions</th><th>Controls</th></tr>']
    assert lines[9] == ('<tr><td>1</td><td>On</td><td>&nbsp;</td><td><table border="1"><tr><th>Group</th></tr>'
                        '<tr><td><a href="#254_56_1">Kitchen</a></td></tr></table></td></tr>')
    assert lines[-2] == '<tr><td>8</td><td>Unused</td><td>&nbsp;</td><td>&nbsp;</td></tr>'
    assert lines[-1] == '</table>' and 'Scenes<br />' not in lines


@pytest.mark.parametrize("mask,unconnected", [(0, (2, 3, 4)), (2, (2, 3, 4)), (1, (2, 3, 4)),
                                           (7, (4,)), (255, ())])
def test_keye1_native_four_physical_keys_mask_normalization_and_virtual_rows(mask, unconnected):
    params = pp()
    params["KeyMask"] = [mask]
    _, status, lines = body(params, typ="KEYE1")
    assert status == "recovered"
    for key in range(1, 5):
        prefix = 'Unconnected Key ' if key in unconnected else ''
        assert lines[8 + key].startswith(f'<tr><td>{prefix}{key}</td>')
    for key in range(5, 9):
        assert lines[8 + key].startswith(f'<tr><td>Virtual Key {key}</td>')


def test_secondary_group_identity_and_first_matching_unit_block():
    params = pp()
    params["SecondApplicationBlocks"] = [8]
    params["GroupAddress"][:4] = [1, 2, 1, 1]
    params["BlockAllocation"][0] = 12
    params["LightLevelStore1"][2:4] = [240, 128]
    for stage, value in zip(STAGES, (12, 6, 7, 0)):
        params[stage][0] = value
    _, status, lines = body(params)
    assert status == "recovered"
    assert '<a href="#254_56_1_64">Low</a> (25%)' in lines[9]
    assert '<a href="#254_202_1">Mode</a></td><td>50%</td>' in lines[9]
    assert '94%' not in lines[9]  # unused duplicate-block value240 never wins


def test_mixed_application_prefers_linear_block_but_shutter_stored_level_uses_first_reference():
    params = pp()
    params["GroupAddress"] = [255] * 9
    params["SecondApplicationBlocks"] = [2]
    params["BlockAllocation"][1] = 3
    for stage, value in zip(STAGES, (12, 0, 0, 0)):
        params[stage][1] = value
    params["LightLevelStore1"][0] = 255
    data = neo.neo_data(unit(params))
    assert data.keys[1].application == 202 and data.keys[1].macro_label == "Trigger 1"
    params["BlockAllocation"][2] = 3  # key3 has no linear block, falls back to block1 primary
    for stage, value in zip(STAGES, (12, 0, 0, 0)):
        params[stage][2] = value
    data = neo.neo_data(unit(params))
    assert data.keys[2].application == 56 and data.keys[2].macro_label == "Shutter Open"


def test_scene_controls_and_appendix_preserve_original_wrong_key_ramp_index():
    params = pp()
    params["SceneTable"][:4] = [1, 255, 2, 64]
    bind_scene(params, 2, 0, 2, 66)
    bind_scene(params, 4, 0, 10, 67)
    data = neo.neo_data(unit(params))
    assert data.keys[2].commands == (0, 0, 0, 0)
    assert data.keys[0].scene_index == 0 and data.keys[0].scene_trigger is None
    _, status, lines = body(params)
    assert status == "recovered"
    assert '<td>Scene</td><td>&nbsp;</td>' in lines[11]
    assert '<td>Scene 1</td><td>8 secs</td>' in lines[11]
    assert '<td>Scene 1</td><td>180 secs</td>' in lines[13]
    assert lines[-6:-2] == ['<br />', 'Scenes<br />', '<table border="1">',
                            '<tr><th>Scene</th><th>Triggers</th><th>Groups</th><th>Level</th></tr>']
    assert lines[-2] == ('<tr><td>1</td><td><table border="1"><tr><th>Action Selector</th><th>Ramp Rate</th></tr>'
        '<tr><td><a href="#254_202_9_66">Dinner &<b>party</b></a></td><td>Instant</td></tr>'
        '<tr><td><a href="#254_202_9_67">Away</a></td><td>Instant</td></tr></table></td>'
        '<td><a href="#254_56_1">Kitchen</a><br /><a href="#254_56_2">Hall</a></td><td>100%<br />25%</td></tr>')
    assert lines[-1] == '</table>'


def test_scene_appendix_without_bound_trigger_and_empty_scene_binding():
    params = pp()
    params["SceneTable"][:2] = [1, 127]
    bind_scene(params, 7, 7, 4, 66)
    _, status, lines = body(params)
    assert status == "recovered"
    assert '<td>Scene 8</td><td>20 secs</td>' in lines[16]
    assert lines[-2] == '<tr><td>1</td><td>&nbsp;</td><td><a href="#254_56_1">Kitchen</a></td><td>50%</td></tr>'


def test_group255_has_real_scene_trigger_when_snapshot_contains_original_level():
    params = pp()
    params["ControlAppGroupAddress"] = [255]
    params["SceneTable"][:2] = [1, 255]
    bind_scene(params, 2, 0, 0, 66)
    _, status, lines = body(params)
    assert status == "recovered"
    assert '<a href="#254_202_255_66">Disabled trigger</a>' in lines[-2]


@pytest.mark.parametrize("field,value", [("SceneTable", [255]), ("SceneTablePointer", [162]),
    ("GroupAddress", [1]), ("SceneKeySelector", [0]), ("DebounceTime", [64]),
    ("SecondApplicationBlocks", None), ("JoinPrimaryApplication", [1])])
def test_missing_and_unsupported_model_fields_never_become_defaults(field, value):
    params = pp()
    if value is None:
        del params[field]
    else:
        params[field] = value
    out, status, lines = body(params)
    assert status == "partial" and not lines and out.unrecovered


def test_noncanonical_scene_records_and_modify_scene_fail_closed():
    params = pp()
    params["SceneTable"][:4] = [1, 255, 1, 128]  # duplicate native group normalization excluded
    assert body(params)[1] == "partial"
    params = pp()
    bind_scene(params, 0, 0, 0, 66)
    params["JPCommand"][0] = 12
    out, status, lines = body(params)
    assert status == "partial" and not lines
    assert 'Scene Modify' in out.unrecovered[0]["item"]


@pytest.mark.parametrize("field", ["SceneTable", "SceneTablePointer"])
def test_extra_scene_storage_is_not_silently_truncated(field):
    params = pp()
    params[field].append(255)
    out, status, lines = body(params)
    assert status == "partial" and not lines
    assert "exact canonical array lengths" in out.unrecovered[0]["item"]


def test_missing_scene_selector_label_and_group_are_explicit_partial():
    params = pp()
    params["SceneTable"][:2] = [1, 255]
    bind_scene(params, 2, 0, 0, 80)
    out, status, lines = body(params)
    assert status == "partial" and not lines
    assert 'Level 80' in out.unrecovered[0]["item"]
    params = pp()
    params["SceneTable"][:2] = [80, 255]
    assert body(params)[1] == "partial"


@pytest.mark.parametrize("firmware", ["", "1.4", "1.5.2", "1.3.00", "3.0.00", "1.4.00junk"])
def test_unknown_keym8_firmware_never_selects_a_profile(firmware):
    assert body(firmware=firmware)[1] == "partial"


def test_two_digit_minor_selects_pro_numerically():
    assert neo.neo_profile(unit(firmware="1.10.00")).is_pro is True


@pytest.mark.parametrize("typ,count,virtual", [("KEYM4", 4, "IR Key "), ("KEYA3", 3, "Virtual Key "),
                                             ("KEYB4", 4, "Virtual Key ")])
def test_additional_source_profiles_label_physical_and_virtual_keys(typ, count, virtual):
    _, status, lines = body(typ=typ)
    assert status == "recovered"
    for key in range(1, 9):
        assert lines[8 + key].startswith(f'<tr><td>{virtual if key > count else ""}{key}</td>')


def test_timer_template_load_defaults_only_its_zero_primary_timer():
    params = pp()
    for stage, value in zip(STAGES, (11, 7, 0, 7)):
        params[stage][0] = value
    params["BlockAllocation"][0] = 3
    params["TimerLowByte"][:2] = [0, 0]
    params["TimerExpiryCommand"][0] = 0
    data = neo.neo_data(unit(params))
    assert [block.timer for block in data.blocks[:2]] == [300, 0]
    _, status, lines = body(params)
    assert status == "recovered"
    assert '<td>0h5m0s</td><td>Idle</td>' in lines[9]
    assert '<td>0h0m0s</td><td>Off Key</td>' in lines[9]


@pytest.mark.parametrize("mutation", ["wrong_mask", "shared", "ordinary_group", "secondary"])
def test_scene_bindings_needing_native_block_relocation_remain_partial(mutation):
    params = pp()
    bind_scene(params, 2, 0, 0, 66)
    if mutation == "wrong_mask":
        params["BlockAllocation"][2] = 0
    elif mutation == "shared":
        params["BlockAllocation"][3] = 4
    elif mutation == "ordinary_group":
        params["GroupAddress"][2] = 1
    else:
        params["SecondApplicationBlocks"][0] = 4
    out, status, lines = body(params)
    assert status == "partial" and not lines
    assert 'unshared linear' in out.unrecovered[0]["item"]


def test_neo_static_receipt_keeps_source_only_acceptance():
    report = json.loads(RECEIPT.read_text())
    assert report["original_executed"] is False
    assert report["original_generated_page_comparison"] == "not_obtained"
    assert all(report["checks"].values())


@pytest.mark.skipif(not os.environ.get("CBUS_TOOLKIT_EXE"), reason="Requires pinned Toolkit EXE and MAP")
def test_neo_static_receipt_reproduces_from_vendor_inputs():
    import sys
    sys.path.insert(0, str(ROOT / "research"))
    from project_documentor_neo_static import inspect
    exe = Path(os.environ["CBUS_TOOLKIT_EXE"])
    assert inspect(exe, Path(os.environ.get("CBUS_TOOLKIT_MAP", exe.with_suffix(".map")))) == json.loads(RECEIPT.read_text())
