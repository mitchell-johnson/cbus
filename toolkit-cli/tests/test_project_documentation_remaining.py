"""Literal saved-PP report, usage and selector oracles; no native execution."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
from pathlib import Path

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_gateways as gateway
from cbus_toolkit import project_documentation_light_level as light
from cbus_toolkit.project_documentation_usage import action_selector_usage, group_usage

VECTOR = Path(__file__).resolve().parents[2] / "rust/testdata/vectors/project_documentation_remaining.json"
CASES = json.loads(VECTOR.read_text())["cases"]
SOURCE = Path(__file__).resolve().parents[1] / "research/fixtures/project-documentor-remaining-static.json"


def unit_from_case(case):
    row = deepcopy(case["unit"])
    row["parameters"] = {name: values if isinstance(values, str) else " ".join(map(str, values))
                         for name, values in row["parameters"].items()}
    return doc.Unit(**row)


def vector_network():
    applications = []
    for row in json.loads(VECTOR.read_text())["applications"]:
        groups = [doc.Group(group["address"], group["name"], group["description"],
                            [doc.Level(**level) for level in group["levels"]])
                  for group in row["groups"]]
        applications.append(doc.Application(row["address"], row["name"], row["description"], groups))
    return doc.Network(254, "Synthetic Local", "", "", applications, [])


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_complete_family_body_literal_and_public_dispatch(case):
    unit, network = unit_from_case(case), vector_network()
    family = case["family"]
    data, lines = ((gateway.whaa_data, gateway.whaa_lines) if family == "WHAA" else
                   (gateway.dali_data, gateway.dali_lines) if family == "DALI2B" else
                   (light.light_level_data, light.light_level_lines))
    assert doc.select_documentor(unit.unit_type, unit.firmware) == family
    assert lines(network, data(unit)) == case["body_lines"]
    network.units = [unit]
    text, summary = doc.render(doc.ProjectModel("DOCREST", [network]),
                               generated=datetime(2026, 10, 2, 12, tzinfo=timezone.utc))
    assert summary["units"] == [{"network": 254, "unit": 3, "unit_type": unit.unit_type,
                                  "documentor": "T" + family + "Documentor", "status": "recovered"}]
    assert doc.LINE_BREAK.join(case["body_lines"]) + doc.LINE_BREAK in text
    for expected in case["group_usage"]:
        actual = group_usage(unit, expected["application"], expected["group"], expected["kind"])
        assert (actual.status, actual.html, actual.missing) == (expected["status"], expected["html"], ())
    action_class = doc.DOCUMENTOR_METHODS[family][1]
    for expected in case["actions"]:
        actual = action_selector_usage(unit, action_class, expected["application"], expected["group"],
                                       expected["address"], expected["value"])
        assert (actual.status, actual.html, actual.missing) == (expected["status"], expected["html"], ())


def test_old_sensor_scale_independent_decimal_formula_all_consumed_exponents():
    # Independent source-transcribed constant/formula, never production output
    # serialized back into a golden. Domain includes both signed thresholds.
    with localcontext() as context:
        context.prec = 90
        base = Decimal(12534562598085640323) / Decimal(4611686018427387904)
        expected = [round(Decimal(25) * base ** (Decimal(value) / Decimal(52)))
                    for value in range(-255, 511)]
    assert [light.lux1600(value) for value in range(-255, 511)] == expected
    assert (light.lux1600(0), light.lux1600(52), light.lux1600(104)) == (25, 68, 185)


def test_static_receipt_binds_source_profiles_and_preserves_acceptance_limits():
    receipt = json.loads(SOURCE.read_text())
    assert receipt["exe_sha256"] == "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab"
    assert receipt["map_sha256"] == "f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb"
    assert receipt["original_executed"] is False
    assert receipt["original_generated_page_comparison"] == "not_obtained"
    assert len(receipt["checks"]) == 40 and all(receipt["checks"].values())
    assert len(receipt["methods"]) == 33
    assert {(row["unit_type"], row["firmware_min"], row["firmware_max"], row["class"], row["agent"])
            for row in receipt["factory_profiles"]} == {
        ("SENLL", "1.00", "2.0.00", "TSENLL", "TSENLLCGateAgent"),
        ("PE_CELL", "1.00", "2.0.00", "TSENLL", "TSENLLCGateAgent"),
        ("SENLL", "2.0.01", "9", "TST7SENLL", "TCBusST7LightLevelSensorCGateAgent"),
        ("PC_DAL2B", "0", "9", "TPC_DAL2B", "TCBusPC_DAL2BCGateAgent"),
        ("PC_DAL2C", "0", "9", "TPC_DAL2C", "TCBusPC_DAL2BCGateAgent"),
        ("PC_WHAD", "0", "9", "TPC_WHAD", "TCBusPC_WHAACGateAgent"),
        ("PC_WHAR", "0", "9", "TPC_WHAR", "TCBusPC_WHAACGateAgent"),
        ("PC_WHARB", "0", "9", "TPC_WHARB", "TCBusPC_WHAACGateAgent"),
    }
    assert receipt["lux1600"]["bounded_exponents"] == [-255, 510]
    assert receipt["lux1600"]["vectors"] == 766
    assert Decimal(receipt["lux1600"]["minimum_distance_from_half_integer"]) > Decimal("0.0001")
    assert all(set(row) == {"start", "end", "sha256"} for row in receipt["methods"].values())


@pytest.mark.parametrize("zone,matrix,relative", [(0, 1, 1), (7, 1, 8), (8, 2, 1),
                                                   (15, 2, 8), (16, 3, 1), (255, 3, 8)])
def test_whaa_zone_bands_and_native_last_band_clamp(zone, matrix, relative):
    unit = unit_from_case(next(case for case in CASES if case["id"] == "pc_whad-manual-zone"))
    unit.parameters["ZoneNumber"] = str(zone)
    data = gateway.whaa_data(unit)
    assert (data["matrix"], data["zone"]) == (matrix, relative)


def test_whaa_usage_keeps_duplicate_roles_and_hidden_language_after_dynamic_buttons():
    unit = unit_from_case(next(case for case in CASES if case["id"] == "pc_whad-manual-zone"))
    for name, _ in gateway.WHA_GROUPS:
        unit.parameters[name] = "1"
    assert group_usage(unit, 56, 1, "other").html == (
        "Volume Control<br/>Bass Control<br/>Treble Control<br/>Next Source<br/>Prev Source<br/>"
        "Button A<br/>Button B<br/>Language Group<br/>Absolute Source")


def test_dali_mapping_setters_clear_earlier_duplicates_including_hidden_last_slot():
    unit = unit_from_case(next(case for case in CASES if case["id"] == "pc_dal2b-two-networks"))
    forward = [255] * 256
    forward[1] = forward[5] = 0
    unit.parameters["CBusToDali"] = " ".join(map(str, forward))
    assert gateway.dali_data(unit)["c_to_d"][1] == 255
    assert gateway.dali_data(unit)["c_to_d"][5] == 0
    assert group_usage(unit, 56, 1, "output").html == ""
    assert group_usage(unit, 56, 5, "output").html == "DALI A Unit 0"
    forward[255] = 0
    unit.parameters["CBusToDali"] = " ".join(map(str, forward))
    assert gateway.dali_data(unit)["c_to_d"][5] == 255
    assert gateway.dali_lines(vector_network(), gateway.dali_data(unit))[-2] == ""
    reverse = [255] * 256
    reverse[0] = reverse[64] = 5
    unit.parameters["DaliToCBus"] = " ".join(map(str, reverse))
    assert gateway.dali_data(unit)["d_to_c"][0] == 255
    assert gateway.dali_data(unit)["d_to_c"][64] == 5


def test_dali_explicit_empty_mapping_uses_zero_default_but_absence_refuses():
    unit = unit_from_case(next(case for case in CASES if case["id"] == "pc_dal2b-two-networks"))
    unit.parameters.update(CBusToDali="", DaliToCBus="")
    data = gateway.dali_data(unit)
    assert data["c_to_d"] == (255,) * 255 + (0,)
    assert data["d_to_c"] == (255,) * 255 + (0,)
    assert [row["mapping"] for row in data["networks"]] == [False, True]
    assert gateway.dali_lines(vector_network(), data)[-2] == ""
    del unit.parameters["CBusToDali"]
    with pytest.raises(ValueError, match="CBusToDali"):
        gateway.dali_data(unit)


@pytest.mark.parametrize("address,label", [(0, "DALI A Unit 0"), (63, "DALI A Unit 63"),
    (64, "DALI A Group 1"), (79, "DALI A Group 16"), (80, "DALI A Scene 1"), (95, "DALI A Scene 16"),
    (96, "DALI A Broadcast"), (97, "DALI A Off"), (128, "DALI B Unit 0"), (191, "DALI B Unit 63"),
    (192, "DALI B Group 1"), (207, "DALI B Group 16"), (208, "DALI B Scene 1"), (223, "DALI B Scene 16"),
    (224, "DALI B Broadcast"), (225, "DALI B Off"), (255, "Unused")])
def test_complete_source_dali_action_ranges(address, label):
    assert gateway.dali_action_name(address) == label


@pytest.mark.parametrize("address", [98, 127, 226, 254])
def test_unregistered_dali_actions_are_explicit(address):
    with pytest.raises(ValueError, match="unregistered DALI action"):
        gateway.dali_action_name(address)


def test_dali_native_refresh_sentinel_clamp_and_class_gated_restore():
    base = unit_from_case(next(case for case in CASES if case["id"] == "pc_dal2b-two-networks"))
    for value, expected in ((0, 1), (59, 60), (254, 60), (255, 1)):
        base.parameters["DaliAErrorRefreshTime"] = str(value)
        assert gateway.dali_data(base)["networks"][0]["refresh"] == expected
    base.parameters["DaliARestoreLevel"] = "malformed but unconsumed on 2B"
    assert not gateway.dali_data(base)["networks"][0]["correction"]
    base.unit_type = "PC_DAL2C"
    with pytest.raises(ValueError, match="not a numeric array"):
        gateway.dali_data(base)


def test_dali_unused_error_groups_hide_selector_fields_but_used_missing_level_refuses():
    unit = unit_from_case(next(case for case in CASES if case["id"] == "pc_dal2b-two-networks"))
    unit.parameters["DaliATriggerErrorGroup"] = "255"
    del unit.parameters["DaliATriggerErrorAcSel"]
    assert gateway.dali_data(unit)["networks"][0]["trigger"] == (202, 255, None)
    assert "Trigger Dali Network A" not in gateway.dali_action_selector_usage(unit, 202, 7, 11, 99).html
    network = vector_network()
    network.application(203).group(1).levels.clear()
    out = doc._Writer()
    assert gateway.document_dali(out, network, unit) == "partial"
    assert out.unrecovered[0]["item"].endswith("unresolved Application 203 Group 1 Level 11")


def test_light_level_firmware_boundary_requires_exact_factory_identity():
    unit = unit_from_case(CASES[0])
    assert light.light_level_profile(unit) == "old"
    unit.firmware = "2.0.00"
    assert light.light_level_profile(unit) == "old"
    unit.firmware = "2.0.01"
    assert light.light_level_profile(unit) == "st7"
    unit.unit_type = "SENLLA"
    with pytest.raises(ValueError, match="surface SENLLA"):
        light.light_level_profile(unit)


def test_st7_zero_timer_does_not_invent_template_state_and_scenes_stay_explicit():
    unit = unit_from_case(next(case for case in CASES if case["id"] == "st7-senll-explicit-idle-zero"))
    unit.parameters["JPCommand"] = "0 0 0 0 7 0 0 0"
    with pytest.raises(ValueError, match="zero broadcast timer"):
        light.light_level_data(unit)
    unit.parameters["SceneTable"] = "0 1 2"
    usage = group_usage(unit, 56, 1, "input")
    assert (usage.html, usage.status, usage.missing) == (
        "Light Level Maintenance", "partial", ("light-level scene group dependencies",))


@pytest.mark.parametrize("case,field", [(CASES[0], "Hystersis"), (CASES[2], "SecondApplicationBlocks"),
                                        (CASES[4], "AlternateVolumeControlGroup"), (CASES[8], "CBusToDali")],
                         ids=["old-lux", "st7-application", "whaa-control", "dali-mapping"])
def test_missing_consumed_fields_are_report_markers(case, field):
    unit, network = unit_from_case(case), vector_network()
    del unit.parameters[field]
    network.units = [unit]
    _, summary = doc.render(doc.ProjectModel("DOCREST", [network]), generated=datetime(2026, 10, 2))
    assert summary["units"][0]["status"] == "partial"
    assert any(field in row["item"] for row in summary["unrecovered"])
