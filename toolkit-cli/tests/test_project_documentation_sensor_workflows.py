"""Integration of recovered input/sensor models with project report dispatch."""
from datetime import datetime

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit.project_documentation_usage import action_selector_usage, group_usage
from test_project_documentation_classic_profiles import make_unit
from test_project_documentation_pir import network as pir_network, unit as pir_unit
from test_project_documentation_temperature import network as temperature_network, snapshot as temperature_unit


@pytest.mark.parametrize("typ", ["BCNC4A", "BCNC4B"])
def test_bus_coupler_reports_stored_controls_and_dependencies_without_save_defaults(typ):
    unit = make_unit(typ, commands=((12, 6, 0, 0),) * 4, Application=[202, 255],
                     LightLevelStore1=[11] * 4, LightLevelStore2=[22] * 4, AreaGroupAddress=[9])
    app = doc.Application(202, "Triggers", "", [
        doc.Group(1, "Mode", "", [doc.Level(11, "Stored action", 22)]),
        doc.Group(2, "Other", "", []), doc.Group(9, "Area", "", [])])
    net = doc.Network(254, "Local", "", "", [app], [unit])
    text, summary = doc.render(doc.ProjectModel("Synthetic", [net]), generated=datetime(2026, 9, 30))
    assert summary["units"][0]["status"] == "recovered"
    assert "<th>Preset 1</th><th>Preset 2</th>" in text
    assert action_selector_usage(unit, "ClassicKeyInput", 202, 1, 11, 22).html == "<br/>".join(
        f"Key {key}" for key in range(1, 5) for _ in range(2))
    assert group_usage(unit, 202, 9, "other").html == "Area Group"
    assert group_usage(unit, 202, 1, "input").html == "Key 1<br/>Key 2<br/>Key 3<br/>Key 4"
    unit.firmware = "unknown"
    assert action_selector_usage(unit, "ClassicKeyInput", 202, 1, 11, 22).status == "unrecovered"


@pytest.mark.parametrize("firmware,documentor,polarity", [
    ("1.2.60", "PIR", "PIR Disable Group: "),
    ("2.4.00", "ST7PIRSensor", "PIR Enable Group: "),
])
def test_pir_report_dispatch_includes_keys_appendix_and_primary_only_action_chain(firmware, documentor, polarity):
    unit = pir_unit(firmware=firmware)
    net = pir_network()
    net.units = [unit]
    text, summary = doc.render(doc.ProjectModel("Synthetic", [net]), generated=datetime(2026, 9, 30))
    assert summary["units"][0]["documentor"] == f"T{documentor}Documentor"
    assert summary["units"][0]["status"] == "recovered"
    assert polarity + '<a href="#254_202_8">G8</a>' in text
    # Trigger application sections report selector events, not the separate
    # Input dependency list. The fixture's Level.Value is 33 rather than 22.
    assert "Key 1<br/>Key 1<br/>Key 2" in text
    assert group_usage(unit, 202, 8, "input").html == "Key 1<br/>Key 2<br/>Key 1"
    assert action_selector_usage(unit, "ClassicKeyInput", 202, 8, 11, 22).html.count("Key 1") == 4
    unit.parameters["Application"] = "56 202"
    unit.parameters["SecondApplicationBlocks"] = "3"
    assert action_selector_usage(unit, "ClassicKeyInput", 202, 8, 11, 22).html == ""


@pytest.mark.parametrize("typ,documentor,body", [
    ("SENTEMP", "SENTEMP", "Target: 21°C<br />"),
    ("SENTEMPB", "SENTEMPPro", "Target Temperature High: 22°C<br />"),
    ("SENTEMP4", "DigitalTemperatureSensor", "<b>Broadcast Threshold:</b> 0.50°C<br />"),
])
def test_temperature_body_dispatch_uses_explicit_celsius_profile(typ, documentor, body):
    unit = temperature_unit(typ)
    net = temperature_network()
    net.units = [unit]
    text, summary = doc.render(doc.ProjectModel("Synthetic", [net]), generated=datetime(2026, 9, 30))
    assert summary["units"][0]["documentor"] == f"T{documentor}Documentor"
    assert summary["units"][0]["status"] == "recovered"
    assert body in text
    assert doc.PARITY["temperature_format_basis"].startswith("celsius; period decimal separator")
    if typ != "SENTEMP4":
        assert group_usage(unit, 56, 1, "input").html in {"Control Group", "Controlled Group"}
