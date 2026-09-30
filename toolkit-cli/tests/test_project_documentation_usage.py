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
    assert group_usage(unit(IndicatorBrightness=" "), 202, 8, "other").html == "Area Group<br/>Indicator Brightness Group"
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
    from project_documentor_direct_usage_static import inspect as inspect_direct
    direct = json.loads((root / 'research/fixtures/project-documentor-direct-usage-static.json').read_text())
    assert inspect_direct(exe, map_file) == direct


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
    completed = subprocess.run([sys.executable, str(root / 'research/project_documentor_usage_original.py'),
                                '--executable', str(exe), '--map-file',
                                os.environ.get('CBUS_TOOLKIT_MAP', str(exe.with_suffix('.map'))),
                                '--output', str(result), '--direct-actions'],
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    direct = json.loads((root / 'research/fixtures/project-documentor-direct-actions-original.json').read_text())
    assert json.loads(result.read_text()) == direct


def test_fan_input_uses_master_trigger_group_and_first_channel():
    u = unit("RELDF1", Application=[56], GroupAddress=[8], FanTriggerGroup=[20])
    assert group_usage(u, 56, 8, "input").html == "Fan Speed Cycle"
    assert group_usage(u, 56, 9, "input").html == ""
    assert group_usage(u, 202, 8, "input").html == ""
    assert group_usage(u, 56, 8, "other").status == "recovered"
    assert group_usage(u, 56, 8, "output").status == "unrecovered"
    u.parameters["FanTriggerGroup"] = "255"
    u.parameters.pop("Application")
    assert group_usage(u, 56, 8, "input").status == "recovered"
    u.parameters.pop("FanTriggerGroup")
    assert group_usage(u, 56, 8, "input").missing == ("FanTriggerGroup",)


def test_temperature_other_uses_fixed_apps_and_mode_gated_channel_order():
    u = unit("SENTEMP4", ErrorReportingEnableGroup=[8], Channel1ChannelMode=[172],
             Channel1HVACCommunicationGroup=[8], Channel2ChannelMode=[228],
             Channel2HVACCommunicationGroup=[8], Channel3ChannelMode=[172],
             Channel3HVACCommunicationGroup=[8], Channel4ChannelMode=[172],
             Channel4HVACCommunicationGroup=[9])
    assert group_usage(u, 172, 8, "other").html == "Communication Group Channel 1<br/>Communication Group Channel 3"
    assert group_usage(u, 203, 8, "other").html == "Error Report Enable Group"
    assert group_usage(u, 56, 8, "other").html == ""
    assert group_usage(u, 172, 8, "input").status == "recovered"
    assert group_usage(u, 172, 8, "output").status == "recovered"
    u.parameters.pop("Channel2HVACCommunicationGroup")
    assert group_usage(u, 172, 8, "other").status == "recovered"
    u.parameters.pop("Channel3HVACCommunicationGroup")
    result = group_usage(u, 172, 8, "other")
    assert (result.html, result.status, result.missing) == (
        "Communication Group Channel 1", "partial", ("Channel3HVACCommunicationGroup",))


def test_direct_actions_use_trigger_app_address_and_skip_unused_group():
    for typ, doc, group_name, level_name, label in (
        ("RELDF1", "FanController", "FanTriggerGroup", "FanActionSelector", "Fan Speed Cycle"),
        ("SENTEMPB", "SENTEMPPro", "BroadcastTriggerGroup", "BroadcastTriggerLevel", "Trigger Temperature Broadcast"),
    ):
        u = unit(typ, Application=[56], **{group_name: [8], level_name: [11]})
        assert action_selector_usage(u, doc, 202, 8, 11, 222).html == "<li />" + label
        assert action_selector_usage(u, doc, 202, 8, 22, 11).html == ""
        assert action_selector_usage(u, doc, 56, 8, 11, 11).html == ""
        u.parameters.pop(level_name)
        assert action_selector_usage(u, doc, 202, 8, 11, 11).missing == (level_name,)
        u.parameters[group_name] = "255"
        assert action_selector_usage(u, doc, 202, 8, 11, 11).status == "recovered"


def test_temperature_broadcast_match_overwrites_error_description():
    u = unit("SENTEMP4", ErrorReportingTriggerGroup=[8], ErrorReportingActionSelector=[11],
             BroadcastTriggerGroup=[8], BroadcastActionSelector=[11])
    assert action_selector_usage(u, "DigitalTemperatureSensor", 202, 8, 11, 99).html == "<li />Trigger Temperature Report"
    u.parameters["BroadcastActionSelector"] = "12"
    assert action_selector_usage(u, "DigitalTemperatureSensor", 202, 8, 11, 99).html == "<li />Trigger Error Report"
    u.parameters.pop("BroadcastActionSelector")
    assert action_selector_usage(u, "DigitalTemperatureSensor", 202, 8, 11, 99).status == "unrecovered"
    u.parameters["BroadcastActionSelector"] = "11"
    u.parameters.pop("ErrorReportingTriggerGroup")
    # Native final result is still known despite an unresolved overwritten branch.
    assert action_selector_usage(u, "DigitalTemperatureSensor", 202, 8, 11, 99).status == "recovered"


def test_direct_actions_match_executed_original_method_vectors():
    import json
    from pathlib import Path

    receipt = json.loads((Path(__file__).parents[1] / "research" / "fixtures" /
                          "project-documentor-direct-actions-original.json").read_text())
    assert len(receipt["cases"]) == 8
    mapping = {
        "FanController": ("RELDF1", (("TCBusFanControllerUnit.GetFanActionSelector", "FanTriggerGroup", "FanActionSelector"),)),
        "SENTEMPPro": ("SENTEMPB", (("TSENTEMPPro.GetBroadcastActionSelector", "BroadcastTriggerGroup", "BroadcastTriggerLevel"),)),
        "DigitalTemperatureSensor": ("SENTEMP4", (
            ("TCBusDigitalTemperatureSensor.GetErrorReportingActionSelector", "ErrorReportingTriggerGroup", "ErrorReportingActionSelector"),
            ("TCBusDigitalTemperatureSensor.GetTriggerBroadcastActionSelector", "BroadcastTriggerGroup", "BroadcastActionSelector"))),
    }
    for case in receipt["cases"]:
        typ, fields = mapping[case["documentor"]]
        parameters = {group: [case["group"]] for _, group, _ in fields}
        parameters.update({selector: [case["address"] if case["matches"][getter] else 99]
                           for getter, _, selector in fields})
        actual = action_selector_usage(unit(typ, **parameters), case["documentor"], 202,
                                       case["group"], case["address"], case["value"])
        assert actual.status == "recovered", case["name"]
        assert actual.html == case["html"], case["name"]


def test_new_direct_din_output_profile_usage_and_ncc_remains_unknown():
    u = unit("ANODN4", Application=[56], GroupAddress=[8, 9, 8, 255] + [255] * 8 + [8, 255, 255, 255],
             LogicGA13Associations=[0, 1, 0, 0])
    assert group_usage(u, 56, 8, "output").html == "Channel 1<br/>Channel 3<br/>Logic Group"
    assert group_usage(u, 56, 8, "output").status == "recovered"
    assert group_usage(unit("DIMDH4"), 56, 8, "output").status == "unrecovered"
