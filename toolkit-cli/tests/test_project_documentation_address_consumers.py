"""Independent database identity, report address and physical-number consumers."""
from copy import deepcopy
from datetime import datetime

import pytest

from cbus_toolkit.project import ProjectError
from cbus_toolkit import project_documentation as doc


def network(address, identity=None, number=None, name="Network"):
    return doc.Network(address, name, "CNI", "invented", [], [], number, identity)


def bridge():
    return doc.Unit(4, "Bridge", "BRIDGE2N", "Bridge", "000000000001", "1.0.00", "", {
        "Application": "56 255", "ApplicationConnectEnabled": "1",
        "BridgeCount": "1", "BridgeAddress": "62 255 255 255 255 255 255",
    }, {})


def model():
    local = network(255, "HOST", 254, "Local")
    local.units.append(bridge())
    return doc.ProjectModel("Invented", [local, network(255, "FAR", 4, "Far"),
        network(42, "DEST", 62, "Destination"), network(62, "SHADOW", 99, "Shadow"),
        network(255, "Unknown")], format="native-cgate-xml-snapshot")


def test_bridge_consumes_numbers_and_formats_report_addresses_without_aliasing_database_identity():
    project = model()
    before = deepcopy(project)
    out = doc._Writer()
    assert doc.document_bridge(out, project.networks[0], project.networks[0].units[0], project) == "recovered"
    assert 'Adjacent Network: <a href="#255">Far</a><br/>' in out.lines
    assert 'Send Messages to Remote Network: <a href="#42">Destination</a><br/>' in out.lines
    assert not any("Shadow" in line for line in out.lines)
    assert project == before


def test_duplicate_physical_numbers_are_checked_only_for_consumed_references():
    project = model()
    project.networks.extend([network(255, "DUP1", 99), network(255, "DUP2", 255)])
    out = doc._Writer()
    assert doc.document_bridge(out, project.networks[0], project.networks[0].units[0], project) == "recovered"
    project.networks.append(network(255, "DUPFAR", 4))
    out = doc._Writer()
    assert doc.document_bridge(out, project.networks[0], project.networks[0].units[0], project) == "partial"
    assert out.unrecovered == [{"network": "HOST", "unit": 4,
        "item": "Bridge adjacent network (ambiguous NetworkNumber 4)"}]


def test_native_unknown_numbers_do_not_become_database_address_fallbacks_or_proven_absence():
    project = model()
    project.networks[1].network_number = None
    out = doc._Writer()
    assert doc.document_bridge(out, project.networks[0], project.networks[0].units[0], project) == "partial"
    assert "Unresolved NetworkNumber 4" in out.unrecovered[0]["item"]
    assert not any("no far side" in line for line in out.lines)


def test_empty_forwarding_prefix_consumes_the_initialized_destination_number_255():
    project = model()
    project.networks[0].units[0].parameters["BridgeAddress"] = "255 255 255 255 255 255 255"
    destination = network(42, "DEFAULT", 255, "Default destination")
    project.networks.append(destination)
    out = doc._Writer()
    assert doc.document_bridge(out, project.networks[0], project.networks[0].units[0], project) == "recovered"
    assert 'Send Messages to Remote Network: <a href="#42">Default destination</a><br/>' in out.lines
    project.networks.append(network(255, "DUPDEFAULT", 255))
    out = doc._Writer()
    assert doc.document_bridge(out, project.networks[0], project.networks[0].units[0], project) == "partial"
    assert "ambiguous NetworkNumber 255" in out.unrecovered[0]["item"]


def test_legacy_numeric_profile_keeps_its_existing_address_lookup():
    local = network(254)
    far = network(4, name="Far")
    destination = network(62, name="Destination")
    local.units.append(bridge())
    project = doc.ProjectModel("Legacy", [local, far, destination], format="XML")
    out = doc._Writer()
    assert doc.document_bridge(out, local, local.units[0], project) == "recovered"
    assert 'Send Messages to Remote Network: <a href="#62">Destination</a><br/>' in out.lines


def test_native_proven_destination_absence_is_unknown_network_but_unknown_numbers_are_unresolved():
    project = model()
    project.networks.pop()  # Every remaining physical Number is explicitly known.
    project.networks[0].units[0].parameters["BridgeAddress"] = "255 255 255 255 255 255 255"
    out = doc._Writer()
    assert doc.document_bridge(out, project.networks[0], project.networks[0].units[0], project) == "recovered"
    assert 'Send Messages to Remote Network: Unknown Network<br/>' in out.lines
    project.networks.append(network(255, "UNKNOWN"))
    out = doc._Writer()
    assert doc.document_bridge(out, project.networks[0], project.networks[0].units[0], project) == "partial"
    assert "Unresolved NetworkNumber 255" in out.unrecovered[0]["item"]


def test_metadata_and_unrecovered_ownership_keep_exact_identities_despite_colliding_report_anchors():
    first = network(255, "Alpha")
    second = network(255, "alpha")
    project = doc.ProjectModel("Saved", doc._unique([second, first], "network"),
                               format="native-cgate-xml-snapshot")
    text, summary = doc.render(project, generated=datetime(2026, 10, 3))
    assert summary["networks"] == ["Alpha", "alpha"]
    assert set(project.by_address) == {"Alpha", "alpha"}
    assert text.count('<a name="255">Network') == 2
    assert {row["network"] for row in summary["unrecovered"]} == {"Alpha", "alpha"}
    with pytest.raises(ProjectError, match="duplicate network address Alpha"):
        doc._unique([first, deepcopy(first)], "network")
