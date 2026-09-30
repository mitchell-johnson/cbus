from cbus_toolkit.project_documentation import Unit
from cbus_toolkit.project_documentation_usage import action_selector_usage, group_usage


def unit(typ="KEY4", **parameters):
    defaults = {"Application": [202], "GroupAddress": [8, 8, 9, 10, 8, 255, 255, 255],
                "AreaGroupAddress": [8], "IndicatorBrightness": [255], "BlockAllocation": [3, 1, 4, 8],
                "JPCommand": [12, 0, 0, 0], "SRCommand": [6, 0, 0, 0],
                "LPCommand": [0, 0, 0, 0], "LRCommand": [0, 0, 0, 0],
                "LightLevelStore1": [11, 11, 12, 13], "LightLevelStore2": [22, 22, 33, 44],
                "TimerExpiryCommand": [15, 15, 15, 15]}
    defaults.update(parameters)
    return Unit(1, "Unit", typ, typ, "", "1.2.67", "", {
        k: " ".join(map(str, v)) if isinstance(v, list) else v
        for k, v in defaults.items() if v is not None}, {})


def test_classic_input_block_major_order_duplicates_and_unused():
    u = unit(JPCommand=[12, 13, 0, 0])
    assert group_usage(u, 202, 8, "input").html == "Key 1<br/>Key 2<br/>Key 1"
    assert group_usage(u, 202, 9, "input").html == "Block (Unused)"
    assert group_usage(u, 56, 8, "input").html == ""
    assert group_usage(u, 202, 8, "output").status == "recovered"


def test_classic_other_order_and_native_fixed_brightness_group():
    assert group_usage(unit(), 202, 8, "other").html == "Area Group<br/>Indicator Brightness Group"
    assert group_usage(unit(IndicatorBrightness=""), 202, 8, "other").html == "Area Group"
    assert group_usage(unit("KEYBC2"), 202, 8, "other").html == "Area Group"
    partial = group_usage(unit(AreaGroupAddress=None), 202, 8, "other")
    assert (partial.html, partial.status, partial.missing) == (
        "Indicator Brightness Group", "partial", ("AreaGroupAddress",))


def test_classic_action_order_is_key_major_and_keeps_duplicate_uses():
    result = action_selector_usage(unit(), "ClassicKeyInput", 202, 8, 11, 22)
    assert (result.status, result.html) == ("recovered", "Key 1<br/>Key 1<br/>Key 1<br/>Key 1")


def test_native_recall2_branch_is_nested_under_stored1_address_match():
    assert action_selector_usage(unit(), "ClassicKeyInput", 202, 8, 99, 22).html == ""
    assert action_selector_usage(unit(), "ClassicKeyInput", 202, 8, 11, 99).html == "Key 1<br/>Key 1"


def test_timer_recall_uses_retrigger_code_seven_not_start_code_eight():
    u = unit(JPCommand=[7, 8, 0, 0], SRCommand=[0, 0, 0, 0], TimerExpiryCommand=[6, 12, 15, 15])
    assert action_selector_usage(u, "ClassicKeyInput", 202, 8, 11, 22).html == "Key 1<br/>Key 1"


def test_missing_or_invalid_consumed_pp_data_cannot_claim_absence():
    for change in ({"BlockAllocation": None}, {"SRCommand": [99, 0, 0, 0]}):
        assert group_usage(unit(**change), 202, 8, "input").status == "unrecovered"
        assert action_selector_usage(unit(**change), "ClassicKeyInput", 202, 8, 11, 22).status == "unrecovered"
    assert group_usage(unit("KEYGL5"), 202, 8, "input").status == "unrecovered"
    assert action_selector_usage(unit("KEYGL5"), "NeoProInput", 202, 8, 11, 22).status == "unrecovered"
    assert action_selector_usage(unit(), "UnitType", 202, 8, 11, 22).status == "recovered"


def test_classic_output_uses_logic_labels_not_channel_labels():
    u = unit("RELAY2", GroupAddress=[8, 9, 8, 255, 255, 8],
             LogicGA0Associations=[1, 0], LogicGA2Associations=[0, 0], LogicGA5Associations=[0, 1])
    assert group_usage(u, 202, 8, "output").html == "Logic Group<br/>Logic Group (Unused)<br/>Logic Group"
    assert group_usage(u, 202, 8, "other").html == "Area Group"
    assert group_usage(u, 202, 8, "input").html == ""


def test_din_order_is_channels_then_logic_including_unused_and_duplicates():
    u = unit("DIMDN4", GroupAddress=[8, 9, 8, 10] + [255] * 8 + [8, 8, 9, 255],
             LogicGA13Associations=[0, 1, 0, 0], LogicGA14Associations=[0, 0, 0, 0])
    result = group_usage(u, 202, 8, "output")
    assert result.html == "Channel 1<br/>Channel 3<br/>Logic Group<br/>Logic Group (Unused)"
    assert result.status == "recovered"
    assert group_usage(u, 202, 8, "other").html == ""
    u.parameters.pop("LogicGA13Associations")
    result = group_usage(u, 202, 8, "output")
    assert result.status == "partial" and result.missing == ("LogicGA13Associations",)
    assert result.html == "Channel 1<br/>Channel 3<br/>Logic Group (Unused)"


def test_classic_actions_match_executed_original_method_vectors():
    import json
    from pathlib import Path

    receipt = json.loads((Path(__file__).parents[1] / "research" / "fixtures" /
                          "project-documentor-action-original.json").read_text())
    assert len(receipt["cases"]) == 10
    for case in receipt["cases"]:
        blocks, keys = case["blocks"], case["keys"]
        padded = blocks + [{"group": 255, "stored1": 0, "stored2": 0, "expiry": 15}] * (4 - len(blocks))
        parameters = {"Application": [202 if case.get("same_application", True) else 56],
                      "GroupAddress": [b["group"] for b in padded],
                      "LightLevelStore1": [b["stored1"] for b in padded],
                      "LightLevelStore2": [b["stored2"] for b in padded],
                      "TimerExpiryCommand": [b["expiry"] for b in padded],
                      "BlockAllocation": [sum(1 << b for b in key["blocks"]) for key in keys]}
        for index, stage in enumerate(("JPCommand", "SRCommand", "LPCommand", "LRCommand")):
            parameters[stage] = [(key["commands"] + [0] * 4)[index] for key in keys]
        result = action_selector_usage(unit("KEY" + str(len(keys)), **parameters), "ClassicKeyInput",
                                       202, case["group"], case["address"], case["value"])
        assert result.status == "recovered", case["name"]
        assert result.html == case["html"], case["name"]


def test_usage_static_receipt_reproduces_when_configured():
    import json
    import os
    from pathlib import Path
    import sys
    import pytest

    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source:
        pytest.skip('Set CBUS_TOOLKIT_EXE to verify original documentor usage evidence')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'research'))
    from project_documentor_usage_static import inspect
    exe = Path(source)
    map_file = Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map')))
    static = json.loads((root / 'research/fixtures/project-documentor-usage-static.json').read_text())
    assert inspect(exe, map_file) == static


def test_original_vectors_reproduce_in_opt_in_subprocess(tmp_path):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    import pytest

    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source or os.environ.get('CBUS_RUN_DOCUMENTOR_ORIGINAL') != '1':
        pytest.skip('Set CBUS_TOOLKIT_EXE and CBUS_RUN_DOCUMENTOR_ORIGINAL=1; requires executable memory')
    root = Path(__file__).resolve().parents[1]
    exe = Path(source)
    result = tmp_path / 'original-actions.json'
    completed = subprocess.run([sys.executable, str(root / 'research/project_documentor_usage_original.py'),
                                '--executable', str(exe), '--map-file',
                                os.environ.get('CBUS_TOOLKIT_MAP', str(exe.with_suffix('.map'))),
                                '--output', str(result)], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    original = json.loads((root / 'research/fixtures/project-documentor-action-original.json').read_text())
    assert json.loads(result.read_text()) == original
