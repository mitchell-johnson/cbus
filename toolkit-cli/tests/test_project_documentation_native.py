"""Read-only saved native XML projection; no endpoint or original GUI execution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from cbus_toolkit.project import ProjectError
from cbus_toolkit.project_documentation_native import FORMAT, build_native_model


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def snapshot(*, group="", units="", interface=""):
    return ("<Installation><Project><Address>DOCS</Address><TagName>Documentation</TagName>"
            "<Network><Address>254</Address><TagName>Local</TagName>" + interface
            + "<Application><Address>202</Address><TagName>Trigger Control</TagName>"
            + group + "</Application>" + units + "</Network></Project></Installation>").encode()


GROUP = ('<Group><Address>7</Address><TagName>Scenes</TagName><Description>Triggers</Description>'
         '<Level Value="42"><Address>3</Address><TagName>Evening</TagName></Level></Group>')
UNIT = ('<Unit><Address>12</Address><TagName>Input</TagName><UnitType>KEYE2</UnitType>'
        '<FirmwareVersion>2.5.00</FirmwareVersion><UnitName>Two key</UnitName>'
        '<SerialNumber>1.2.3</SerialNumber><Description>Stored notes</Description>'
        '<Burden>False</Burden><PP Name="Application" Value="0x38 0xff"/></Unit>')


def test_direct_native_fields_and_distinct_level_value_are_preserved():
    raw = snapshot(group=GROUP, units=UNIT,
                   interface='<InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress>')
    result = build_native_model(raw)
    network = result.networks[0]
    assert result.format == FORMAT == "native-cgate-xml-snapshot"
    assert result.digest == hashlib.sha256(raw).hexdigest()
    assert result.size == len(raw)
    assert result.name == "Documentation"
    assert (network.interface_type, network.interface_address) == ("CNI", "127.0.0.1:1")
    level = network.applications[0].groups[0].levels[0]
    assert (level.address, level.value, level.action_value, level.name) == (3, 42, 42, "Evening")
    unit = network.units[0]
    assert (unit.unit_name, unit.serial, unit.description) == ("Two key", "1.2.3", "Stored notes")
    assert unit.parameters == {"Application": "0x38 0xff"}
    assert unit.fields == {"Burden": "False"}


def test_missing_programming_and_names_stay_absent_without_default_spec_loading():
    raw = snapshot(units=UNIT.replace('<PP Name="Application" Value="0x38 0xff"/>', '')
                              .replace('<Burden>False</Burden>', ''))
    raw = raw.replace(b"<TagName>Documentation</TagName>", b"")
    result = build_native_model(raw)
    assert result.name == ""  # Project Address is not a substitute for TagName.
    unit = result.networks[0].units[0]
    assert unit.parameters == {}
    assert unit.fields == {}
    assert unit.array("Application") is None


def test_original_native_network_readback_fixture_projects_nested_interface():
    receipt = json.loads((REPO / "rust/testdata/fixtures/native_cgate_dbgetxml_framing_vm.json").read_text())
    case = next(case for case in receipt["cases"] if case["tag"] == "908")
    line = next(line for line in case["response_lines"] if "347-<Network>" in line)
    network_xml = line.split("347-", 1)[1].strip()
    # Only the enclosing project is synthetic; the network is the unchanged
    # committed C-Gate 3.4.0.2001 readback. No capture is run by this test.
    raw = ('<Installation><Project><Address>XFRAME</Address>' + network_xml
           + '</Project></Installation>').encode()
    model = build_native_model(raw)
    network = model.networks[0]
    assert (network.address, network.name) == (254, "Local")
    assert (network.interface_type, network.interface_address) == ("Cni", "127.0.0.1:1")
    assert [(app.address, app.name) for app in network.applications] == [(56, "Lighting")]
    assert [(unit.address, unit.unit_type, unit.name) for unit in network.units] == [(20, "KEYE1", "Bedroom")]
    assert network.units[0].parameters == {}


def test_original_native_roundtrip_preserves_distinct_level_addresses_and_values():
    receipt = json.loads((REPO / "rust/testdata/fixtures/native_cgate_dbsetxml_nested_levels_roundtrip.json").read_text())
    case = next(case for case in receipt["cases"] if case["tag"] == 909)
    line = next(line for line in case["response_lines"] if "347-<Network>" in line)
    network_xml = line.split("347-", 1)[1].strip()
    raw = ('<Installation><Project><Address>XRTN</Address>' + network_xml
           + '</Project></Installation>').encode()
    network = build_native_model(raw).networks[0]
    assert [(app.address, app.groups[0].address, app.groups[0].levels[0].address,
             app.groups[0].levels[0].value, app.groups[0].levels[0].name)
            for app in network.applications] == [
                (56, 1, 2, 56, "Level56"), (57, 1, 2, 57, "Level57")]


@pytest.mark.parametrize("name", ("dimdn8f", "din4-rel4-rel8", "keygl5", "manager-order",
                                 "reldn8b", "reldn8sp", "senpiria", "registry-batch"))
def test_committed_native_csv_snapshots_match_independent_xml_inventory(name):
    raw = (ROOT / f"research/fixtures/toolkit-database-csv-{name}-synthetic.xml").read_bytes()
    model = build_native_model(raw)
    project = ET.fromstring(raw).find("Project")
    def sentinel_order(rows):
        return sorted(rows, key=lambda row: (row[0] != 255, row[0]))

    expected = sentinel_order((int(network.findtext("Address")),
                       sorted((int(unit.findtext("Address")), unit.findtext("UnitType"),
                               {pp.get("Name"): pp.get("Value") for pp in unit.findall("PP")})
                              for unit in network.findall("Unit")),
                       sentinel_order((int(app.findtext("Address")),
                               sentinel_order((int(group.findtext("Address")), group.findtext("TagName"))
                                      for group in app.findall("Group")))
                              for app in network.findall("Application")))
                      for network in project.findall("Network"))
    actual = [(network.address, [(unit.address, unit.unit_type, unit.parameters) for unit in network.units],
               [(app.address, [(group.address, group.name) for group in app.groups])
                for app in network.applications]) for network in model.networks]
    assert actual == expected


def test_original_sentinel_first_order_applies_only_to_network_application_group():
    project = ET.Element("Project")
    ET.SubElement(project, "Address").text = "DOCS"
    for network_address in (254, 1, 255):
        network = ET.SubElement(project, "Network")
        ET.SubElement(network, "Address").text = str(network_address)
        for application_address in (202, 255, 56):
            application = ET.SubElement(network, "Application")
            ET.SubElement(application, "Address").text = str(application_address)
            for group_address in (7, 255, 1):
                group = ET.SubElement(application, "Group")
                ET.SubElement(group, "Address").text = str(group_address)
                for level_address in (42, 255, 1):
                    level = ET.SubElement(group, "Level", Value=str(level_address))
                    ET.SubElement(level, "Address").text = str(level_address)
        for unit_address in (12, 255, 1):
            unit = ET.fromstring(UNIT)
            unit.find("Address").text = str(unit_address)
            network.append(unit)
    root = ET.Element("Installation")
    root.append(project)
    model = build_native_model(ET.tostring(root))
    assert [network.address for network in model.networks] == [255, 1, 254]
    for network in model.networks:
        assert [app.address for app in network.applications] == [255, 56, 202]
        assert [unit.address for unit in network.units] == [1, 12, 255]
        for application in network.applications:
            assert [group.address for group in application.groups] == [255, 1, 7]
            for group in application.groups:
                assert [level.address for level in group.levels] == [1, 42, 255]


@pytest.mark.parametrize("old,new", (
    (b"<Address>DOCS</Address>", b"<Address>TOO_LONG1</Address>"),
    (b"<Address>254</Address>", b"<Address>bad/path</Address>"),
    (b"<Address>202</Address>", b"<Address>256</Address>"),
    (b"<Address>7</Address>", b"<Address>-1</Address>"),
    (b"<Address>3</Address>", b"<Address>0x03</Address>"),
    (b'<Level Value="42">', b'<Level Value="042">'),
    (b'<Level Value="42">', b'<Level>'),
    (b"<Address>12</Address>", b"<Address>12</Address><Address>13</Address>"),
    (b"<TagName>Input</TagName>", b"<TagName>Input</TagName><TagName>Duplicate</TagName>"),
    (b"<FirmwareVersion>2.5.00</FirmwareVersion>", b""),
    (b"<UnitType>KEYE2</UnitType>", b"<UnitType> </UnitType>"),
    (b"<Description>Triggers</Description>", b"<Description><TagName>nested</TagName></Description>"),
))
def test_malformed_or_ambiguous_fields_fail_closed(old, new):
    with pytest.raises(ProjectError):
        build_native_model(snapshot(group=GROUP, units=UNIT).replace(old, new))


@pytest.mark.parametrize("tag", ("Network", "Application", "Group", "Level", "Unit"))
def test_duplicate_entity_addresses_fail_before_returning_a_model(tag):
    root = ET.fromstring(snapshot(group=GROUP, units=UNIT))
    for parent in root.iter():
        child = parent.find(tag)
        if child is not None:
            parent.append(ET.fromstring(ET.tostring(child)))
            break
    with pytest.raises(ProjectError, match="duplicate"):
        build_native_model(ET.tostring(root))


@pytest.mark.parametrize("pp", (
    '<PP Name="Application"/>', '<PP Value="0"/>', '<PP Name="" Value="0"/>',
    '<PP Name=" Application" Value="0"/>', '<PP Name="Application" Value="0" Other="x"/>',
    '<PP Name="Application" Value="0">1</PP>',
    '<PP Name="Application" Value="0"/><PP Name="Application" Value="1"/>',
    '<Parameters><PP Name="Application" Value="0"/></Parameters>',
))
def test_pp_shape_and_cardinality_fail_closed(pp):
    with pytest.raises(ProjectError):
        build_native_model(snapshot(units=UNIT.replace('<PP Name="Application" Value="0x38 0xff"/>', pp)))


@pytest.mark.parametrize("interface", (
    '<Interface/><Interface/>',
    '<Interface/><InterfaceType>CNI</InterfaceType>',
    '<InterfaceType>CNI</InterfaceType><InterfaceType>PCI</InterfaceType>',
    '<Interface><InterfaceAddress>x</InterfaceAddress><InterfaceAddress>y</InterfaceAddress></Interface>',
))
def test_ambiguous_interface_representation_fails(interface):
    with pytest.raises(ProjectError):
        build_native_model(snapshot(interface=interface))


@pytest.mark.parametrize("number", ("0254", "256"))
def test_invalid_network_number_is_not_reinterpreted_as_address(number):
    with pytest.raises(ProjectError):
        build_native_model(snapshot(interface=f"<NetworkNumber>{number}</NetworkNumber>"))


def test_distinct_native_network_number_does_not_rename_address():
    model = build_native_model(snapshot(interface='<NetworkNumber>253</NetworkNumber>'))
    assert (model.networks[0].address, model.networks[0].network_number) == (254, 253)


@pytest.mark.parametrize("group", (
    '<NetVar><Address>7</Address><TagName>Value</TagName></NetVar>',
    GROUP.replace('Group>', 'GroupTrigger>'),
    GROUP.replace('<Level ', '<LevelTrigger ').replace('</Level>', '</LevelTrigger>'),
    '<Groups>' + GROUP + '</Groups>',
    GROUP.replace('<Group>', '<Group xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="GroupTrigger">'),
    GROUP.replace('<Group>', '<Group xmlns="urn:foreign">'),
))
def test_unproven_typed_or_nested_group_shapes_are_not_silently_omitted(group):
    with pytest.raises(ProjectError):
        build_native_model(snapshot(group=group))


@pytest.mark.parametrize("raw", (
    b'<!DOCTYPE Installation [<!ENTITY test "value">]><Installation/>',
    b'<!DOCTYPE Installation SYSTEM "file:///never-read"><Installation/>',
    b'SQLite format 3\x00', b'PK\x03\x04', b'<Network/>', b'<Project/>', b'\xff',
    b'<Installation><Project><Address>DOCS</Address></Project><Project/></Installation>',
))
def test_unsafe_or_non_snapshot_inputs_are_rejected(raw):
    with pytest.raises(ProjectError):
        build_native_model(raw)


def test_namespace_shadowed_fields_are_rejected():
    raw = snapshot().replace(b'<Address>254</Address>', b'<Address xmlns="urn:foreign">254</Address>')
    with pytest.raises(ProjectError, match="unnamespaced"):
        build_native_model(raw)


def test_native_selection_is_explicit_and_does_not_relabel_legacy_model():
    from cbus_toolkit.project import ProjectDocument
    from cbus_toolkit.project_documentation import build_model

    raw = snapshot()
    legacy = build_model(ProjectDocument.from_bytes(raw))
    native = build_native_model(raw)
    assert native.format == FORMAT
    assert legacy.format != FORMAT


def test_explicit_native_cli_renders_snapshot_and_preserves_acceptance_boundary(tmp_path, capsys, monkeypatch):
    import socket
    from cbus_toolkit.cli import main

    def no_connection(*args, **kwargs):
        raise AssertionError("Saved native documentation must not open an endpoint")

    monkeypatch.setattr(socket, "create_connection", no_connection)
    source = tmp_path / "snapshot.xml"
    output = tmp_path / "documentation.html"
    raw = snapshot(group=GROUP, interface='<InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress>')
    source.write_bytes(raw)
    assert main(["project", "document", str(source), "--native-xml", "--output", str(output),
                 "--generated-at", "2026-09-30T07:05"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project"] == {"name": "Documentation", "sha256": hashlib.sha256(raw).hexdigest(),
                                  "bytes": len(raw), "format": FORMAT}
    assert payload["parity"]["original_toolkit_executed"] is False
    assert payload["parity"]["byte_parity"] == payload["parity"]["visual_parity"] == "unassessed"
    text = output.read_bytes().decode("utf-8-sig")
    assert "Interface Type: CNI</br>" in text
    assert "Interface Address: 127.0.0.1:1</br>" in text
    assert 'name="254_202_7_3">Evening</a>' in text
    assert source.read_bytes() == raw


def test_explicit_native_cli_rejects_unsupported_graph_before_output_creation(tmp_path, capsys):
    from cbus_toolkit.cli import main

    source = tmp_path / "snapshot.xml"
    output = tmp_path / "documentation.html"
    source.write_bytes(snapshot(group='<NetVar><Address>1</Address></NetVar>'))
    assert main(["project", "document", str(source), "--native-xml", "--output", str(output)]) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out or captured.err)
    assert "NetVar" in payload["error"]
    assert not output.exists()
