"""Exercise new documentors through the existing project report dispatchers."""
from datetime import datetime

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit.project_documentation_usage import action_selector_usage, group_usage
from test_project_documentation_neo import bind_scene, network, pp, unit
from test_project_documentation_scene_controller import network as scene_network, snapshot


@pytest.mark.parametrize("typ,firmware,documentor", [
    ("KEYA3", "2.5.00", "NeoProInput"), ("KEYB4", "2.5.00", "NeoProInput"),
    ("KEYM4", "2.5.00", "NeoProInput"), ("KEYM8", "2.5.00", "NeoProInput"),
    ("KEYE1", "2.5.00", "NeoProInput"),
    ("KEYBL5", "3.0.00", "DLT"), ("KEYML5", "3.0.00", "DLT"), ("KEYDL4", "3.0.00", "DLT"),
])
def test_saved_neo_scene_reaches_body_trigger_and_group_sections(typ, firmware, documentor):
    parameters = pp()
    bind_scene(parameters, 2, 0, 7, 66)
    parameters["SceneTable"][:2] = [1, 128]
    parameters["EnableDynamicLabels"] = [1]
    device = unit(parameters, typ, firmware)
    net = network()
    net.units = [device]
    text, summary = doc.render(doc.ProjectModel("Synthetic", [net]), generated=datetime(2026, 9, 30))
    assert summary["units"] == [{"network": 254, "unit": 12, "unit_type": typ,
                                 "documentor": f"T{documentor}Documentor", "status": "recovered"}]
    assert 'Scenes<br />\r\n<table border="1">' in text
    assert "Triggers Scene 1\r\n</ul>" in text
    assert action_selector_usage(device, "NeoProInput", 202, 9, 66, 2).html == "Triggers Scene 1"
    assert group_usage(device, 56, 1, "input").html == "Key 1<br/>Scene 1"
    if documentor == "DLT":
        assert "</table>\r\nLabels: Dynamic\r\n" in text


def test_older_neo_registration_dispatches_single_application_snapshot():
    parameters = pp()
    parameters["Application"] = [56]
    device = unit(parameters, "KEYM4", "1.4.00")
    net = network()
    out = doc._Writer()
    result = doc.document_unit(out, net, device, doc.ProjectModel("Synthetic", [net]))
    assert result["documentor"] == "TNeoInputDocumentor" and result["status"] == "recovered"
    assert any(line.startswith("<tr><td>IR Key 5</td>") for line in out.lines)


def test_scene_controller_dispatch_preserves_action_and_dependency_duplicates():
    device = snapshot()
    net = scene_network()
    net.units = [device]
    text, summary = doc.render(doc.ProjectModel("Synthetic", [net]), generated=datetime(2026, 9, 30))
    assert summary["units"][0]["documentor"] == "TCustomSceneControllerDocumentor"
    assert summary["units"][0]["status"] == "recovered"
    assert "Scene Master Off<br />Triggers Scene 1<br />Triggers Scene 3\r\n" in text
    assert "Scene 1<br/>Scene 1<br/>Scene 2<br/>Scene 2" in text
    assert "<th>Master Off</th>" in text


def test_incomplete_dlt_controls_keep_label_suffix_without_promoting_body():
    parameters = pp()
    parameters.pop("SceneTable")
    parameters["EnableDynamicLabels"] = [0]
    device = unit(parameters, "KEYBL5", "3.0.00")
    net = network()
    out = doc._Writer()
    result = doc.document_unit(out, net, device, doc.ProjectModel("Synthetic", [net]))
    assert result["status"] == "partial" and out.lines[-1] == "Labels: Static"
    assert not any("<th>Macro Function</th>" in line for line in out.lines)
    assert group_usage(device, 56, 1, "input").status == "unrecovered"
    assert action_selector_usage(device, "NeoProInput", 202, 9, 66, 2).status == "unrecovered"
