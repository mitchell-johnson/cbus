"""Offline Toolkit topology map, navigation and image export from saved projects."""
from __future__ import annotations

import io
import json
from xml.dom import minidom
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from cbus_toolkit.cli import main
from cbus_toolkit.project import ProjectError
from cbus_toolkit.project_topology import (
    TOO_MANY_NETWORKS,
    _Generator,
    classify_interface,
    load_topology,
)


def network(address, interface_type="Bridge", interface_address=None, *, units=(), name=None):
    if interface_address is None:
        interface_address = ""
    children = "".join(
        f"<Unit><Address>{unit}</Address><UnitType>{unit_type}</UnitType></Unit>"
        for unit, unit_type in units
    )
    return (
        f"<Network><TagName>{name or f'N{address}'}</TagName><Address>{address}</Address>"
        f"<Interface><InterfaceType>{interface_type}</InterfaceType>"
        f"<InterfaceAddress>{interface_address}</InterfaceAddress></Interface>"
        f"{children}</Network>"
    )


def xml(networks, name="HOUSE"):
    return f"<Installation><Project><TagName>{name}</TagName>{''.join(networks)}</Project></Installation>".encode()


def write(tmp_path, networks, *, filename="house.xml", raw=None):
    path = tmp_path / filename
    path.write_bytes(raw if raw is not None else xml(networks))
    return path


def model(tmp_path, networks):
    return load_topology(write(tmp_path, networks)).as_dict()


def cli(capsys, *argv):
    status = main(["project", "topology", *map(str, argv)])
    captured = capsys.readouterr()
    return status, json.loads(captured.out or captured.err)


def chain(depth):
    """Local 254 followed by `depth` bridged networks 253, 252, ... ."""
    addresses = [254 - index for index in range(depth + 1)]
    result = []
    for index, address in enumerate(addresses):
        units = []
        if index:
            units.append((addresses[index - 1], "BRIDGE2F"))
        if index + 1 < len(addresses):
            units.append((addresses[index + 1], "BRIDGE2N"))
        units.append((5, "KEYGL5"))
        if index == 0:
            result.append(network(address, "CNI", "127.0.0.1:10001", units=units))
        else:
            result.append(network(address, "Bridge", f"{addresses[index - 1]}/p/{address}", units=units))
    return addresses, result


def test_single_pci_network_draws_interface_and_stub_connection(tmp_path):
    result = model(tmp_path, [network(254, "Serial", "COM1", units=((12, "RELDN8"),), name="Local")])
    assert result["local_networks"] == [254]
    assert result["interfaces"] == [
        {"type": "PCI", "name": "PCI", "address": "254/COM1", "network": 254, "x": 0, "y": 0}]
    assert result["elements"][1] == {
        "type": "Network", "name": "Local", "address": "254", "network": 254,
        "start_x": 0, "start_y": 0, "finish_x": 1, "finish_y": 0,
        "circular_join": False, "wireless": False}
    assert result["bridges"] == [] and result["warnings"] == [] and result["diagnostics"] == []
    assert result["print_title"] == 'C-Bus Project "HOUSE" Network Topology Map'
    for key in ("layout_parity", "visual_parity", "pixel_parity", "print_parity"):
        assert result["parity"][key] == "unassessed"
    assert result["parity"]["original_toolkit_executed"] is False


@pytest.mark.parametrize("depth", range(1, 7))
def test_chains_up_to_six_bridges_layout_navigate_and_route(tmp_path, depth, capsys):
    addresses, networks = chain(depth)
    path = write(tmp_path, networks)
    result = load_topology(path).as_dict()
    bridges = [element for element in result["elements"] if element["type"] == "Bridge"]
    assert [(item["x"], item["y"]) for item in bridges] == [(2 * (hop + 1), 0) for hop in range(depth)]
    assert [item["address"] for item in bridges] == [
        f"{addresses[hop + 1]}/{addresses[hop]}-{addresses[hop]}" for hop in range(depth)]
    assert result["orphaned_networks"] == [] and result["circular_joins"] == []
    assert result["diagnostics"] == []
    target = addresses[-1]
    status, payload = cli(capsys, path, "--navigate", target)
    assert status == 0
    navigation = payload["navigation"]
    assert navigation["path"] == f"/network/{target}"
    assert [unit["path"] for unit in navigation["units"]] == [
        f"/network/{target}/unit/5", f"/network/{target}/unit/{addresses[-2]}"]
    expected_tree = [{"network": 254}]
    for hop in range(depth):
        expected_tree += [{"bridge": f"{addresses[hop]}/{addresses[hop + 1]}"}, {"network": addresses[hop + 1]}]
    assert navigation["toolkit_tree_path"] == expected_tree
    assert navigation["route"] == {"available": True, "planner": "commissioning_route",
                                   "source_network": 254, "bridges": addresses[1:], "depth": depth}
    near_net, far_net = addresses[-2], addresses[-1]
    status, near = cli(capsys, path, "--near-side", f"{near_net}/{far_net}")
    assert status == 0 and near["navigation"]["path"] == f"/network/{near_net}/unit/{far_net}"
    status, far = cli(capsys, path, "--far-side", f"{near_net}/{far_net}")
    assert status == 0 and far["navigation"]["path"] == f"/network/{far_net}/unit/{near_net}"
    assert far["navigation"]["cgate_address"] == f"//HOUSE/{far_net}/p/{near_net}"


def test_seven_bridges_are_drawn_but_route_planner_limit_is_reported(tmp_path, capsys):
    addresses, networks = chain(7)
    path = write(tmp_path, networks)
    assert len([e for e in load_topology(path).as_dict()["elements"] if e["type"] == "Bridge"]) == 7
    status, payload = cli(capsys, path, "--navigate", addresses[-1])
    assert status == 0
    assert payload["navigation"]["route"]["available"] is False
    assert "six-bridge limit" in payload["navigation"]["route"]["reason"]


def test_branch_topology_uses_toolkit_available_row_rule(tmp_path):
    result = model(tmp_path, [
        network(254, "CNI", "10.0.0.2:10001", units=((1, "BRIDGE2N"), (2, "BRIDGE2N"))),
        network(1, "Bridge", "254/p/1", units=((3, "BRIDGE2N"), (254, "BRIDGE2F"))),
        network(2, "Bridge", "254/p/2", units=((254, "BRIDGE2F"),)),
        network(3, "Bridge", "1/p/3", units=((1, "BRIDGE2F"),)),
    ])
    placed = {e["bridge"]: (e["x"], e["y"]) for e in result["elements"] if e["type"] == "Bridge"}
    # Network 1 is explored depth-first before bridge 254/2 is placed below it.
    assert placed == {"254/1": (2, 0), "1/3": (4, 0), "254/2": (2, 1)}
    stubs = [(e["network"], e["start_x"], e["start_y"], e["finish_x"], e["finish_y"])
             for e in result["elements"] if e["type"] == "Network"]
    assert stubs == [(254, 0, 0, 2, 0), (1, 2, 0, 4, 0), (3, 4, 0, 5, 0), (254, 0, 0, 2, 1), (2, 2, 1, 3, 1)]
    assert {n["address"]: n["local_root"] for n in result["networks"]} == {254: 254, 1: 254, 2: 254, 3: 254}


def test_orphaned_network_warning_uses_recovered_text(tmp_path, capsys):
    path = write(tmp_path, [
        network(254, "Serial", "COM1"),
        network(40, "Bridge", "77/p/40", name="Garage"),
    ])
    result = load_topology(path).as_dict()
    assert result["orphaned_networks"] == [40]
    assert result["warnings"] == [{"kind": "orphaned_network", "network": 40,
                                   "text": 'Network "Garage" is not accessible',
                                   "toolkit_rendering": "warning_text"}]
    codes = {item["code"] for item in result["diagnostics"]}
    assert "bridge_interface_parent_missing" in codes
    status, payload = cli(capsys, path, "--navigate", 40)
    assert status == 0
    assert payload["navigation"]["in_topology_map"] is False
    assert payload["navigation"]["toolkit_tree_path"] is None
    assert payload["navigation"]["route"]["available"] is False


def test_circular_join_when_two_branches_reach_one_network(tmp_path):
    result = model(tmp_path, [
        network(254, "CNI", "10.0.0.2:10001", units=((1, "BRIDGE2N"), (2, "BRIDGE2N"))),
        network(1, "Bridge", "254/p/1", units=((3, "BRIDGE2N"),)),
        network(2, "Bridge", "254/p/2", units=((3, "BRIDGE2N"),)),
        network(3, "Bridge", "1/p/3", units=((1, "BRIDGE2F"),)),
    ])
    assert result["circular_joins"] == [{"network": 3, "bridge": "2/3"}]
    join = [e for e in result["elements"] if e["type"] == "Network" and e["circular_join"]]
    assert join == [{"type": "Network", "name": "N3", "address": "3", "network": 3, "start_x": 4,
                     "start_y": 1, "finish_x": 5, "finish_y": 1, "circular_join": True, "wireless": False}]
    assert {"kind": "circular_join", "network": 3, "bridge": "2/3",
            "toolkit_rendering": "circular_join_arrow"} in result["warnings"]
    codes = [item["code"] for item in result["diagnostics"]]
    assert "multiple_near_bridges_to_network" in codes
    assert "bridge_interface_parent_contradiction" in codes
    bridge = next(item for item in result["bridges"] if item["id"] == "2/3")
    assert bridge["circular_join"] is True and bridge["far_side"] is None


def test_loop_back_to_local_network_is_a_circular_join(tmp_path):
    result = model(tmp_path, [
        network(254, "CNI", "10.0.0.2:10001", units=((1, "BRIDGE2N"),)),
        network(1, "Bridge", "254/p/1", units=((2, "BRIDGE2N"),)),
        network(2, "Bridge", "1/p/2", units=((254, "BRIDGE2N"),)),
    ])
    assert result["circular_joins"] == [{"network": 254, "bridge": "2/254"}]


def test_bridge1f_parent_link_is_skipped_and_leaves_stub(tmp_path):
    result = model(tmp_path, [
        network(254, "Serial", "COM1", units=((3, "BRIDGE1F"),)),
        network(3, "Bridge", "254/p/3", units=((254, "BRIDGE1F"),)),
    ])
    bridges = {item["id"]: item for item in result["bridges"]}
    assert bridges["3/254"]["skipped_as_parent_link"] is True and bridges["3/254"]["drawn"] is False
    assert bridges["254/3"]["far_side"]["unit_type"] == "BRIDGE1F"
    stub = result["elements"][-1]
    assert (stub["network"], stub["start_x"], stub["finish_x"]) == (3, 2, 3)


def test_wireless_gateways_and_interface_classification(tmp_path):
    result = model(tmp_path, [
        network(254, "CNI", "cni.local:10001", units=((9, "GATEWLSN"),)),
        network(9, "Bridge", "254/p/9", units=((254, "GATEWLSF"), (4, "WDIM")), name="Patio"),
    ])
    assert result["interfaces"][0]["type"] == "CNI2"
    assert result["wireless_gateways"] == ["254/9"]
    wireless = {n["address"]: n["wireless"] for n in result["networks"]}
    assert wireless == {254: False, 9: True}
    assert next(e for e in result["elements"] if e["type"] == "Bridge")["wireless"] is True
    table = {
        ("Serial", "COM1"): "PCI", ("CNI", "192.168.0.9:10001"): "CNI", ("cni", "host"): "CNI2",
        ("Socket", ""): "CNI", ("Etherlite", ""): "CNI", ("Wiser", ""): "CNI2",
        ("C-Bus Home Controller", ""): "CNI2", ("SpaceLogicCBusHomeController", ""): "CNI2",
        ("modem", ""): "CBTI", ("Lorax", ""): "PCI", ("LoraxUSB", ""): "PCI", ("Mystery", ""): "PCI",
    }
    for (kind, address), element in table.items():
        assert classify_interface(kind, address)["element"] == element
    assert classify_interface("Mystery", "")["recognized"] is False
    assert classify_interface("bridge", "254/p/3")["local"] is False


def test_contradictory_bridge_addresses_are_diagnosed_not_hidden(tmp_path, capsys):
    path = write(tmp_path, [
        network(254, "CNI", "10.0.0.2:10001", units=((3, "BRIDGE2N"), (8, "BRIDGE2N"), (6, "BRIDGE2N"))),
        network(3, "Bridge", "254/p/3", units=((254, "RELDN8"),)),
        network(5, "Bridge", "254/p/5"),
        network(6, "Serial", "COM2"),
        network(7, "Bridge", "254/7"),
        network(9, "Bridge", "254/p/10"),
    ])
    result = load_topology(path).as_dict()
    codes = {(item["code"], item.get("bridge") or item.get("network")) for item in result["diagnostics"]}
    assert ("bridge_far_unit_not_far_side", "254/3") in codes
    assert ("bridge_far_network_missing", "254/8") in codes
    assert ("bridge_far_network_has_local_interface", "254/6") in codes
    assert ("bridge_interface_without_near_unit", 5) in codes
    assert ("bridge_interface_address_malformed", 7) in codes
    assert ("bridge_interface_unit_mismatch", 9) in codes
    status, payload = cli(capsys, path, "--far-side", "254/8")
    assert status == 1 and "Far side of bridge 254/8 is unresolved" in payload["error"]
    status, payload = cli(capsys, path, "--far-side", "254/3")
    assert status == 1 and "has no far-side bridge unit at address 254" in payload["error"]
    status, payload = cli(capsys, path, "--near-side", "254/8")
    assert status == 0 and payload["navigation"]["unit_type"] == "BRIDGE2N"


def test_cbz_input_matches_xml_model(tmp_path, capsys):
    _, networks = chain(2)
    raw = xml(networks)
    xml_path = write(tmp_path, networks)
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("HOUSE.xml", raw)
        archive.writestr("notes.txt", b"attachment")
    cbz_path = write(tmp_path, None, filename="house.cbz", raw=buffer.getvalue())
    from_xml, from_cbz = load_topology(xml_path).as_dict(), load_topology(cbz_path).as_dict()
    assert from_cbz["project"]["format"] == "legacy-cbz"
    for key in ("networks", "bridges", "elements", "warnings", "diagnostics"):
        assert from_cbz[key] == from_xml[key]
    images = []
    for path in (xml_path, cbz_path):
        for fmt in ("dot", "svg"):
            status, payload = cli(capsys, path, "--format", fmt)
            assert status == 0
            images.append(payload["image"])
    assert images[0] == images[2] and images[1] == images[3]
    assert cbz_path.read_bytes() == buffer.getvalue()


def test_dot_and_svg_exports_are_deterministic_and_well_formed(tmp_path, capsys):
    path = write(tmp_path, [
        network(254, "CNI", "10.0.0.2:10001", units=((1, "BRIDGE2N"), (2, "WGATE5N"))),
        network(1, "Bridge", "254/p/1", units=((2, "BRIDGE2N"),)),
        network(2, "Bridge", "254/p/2", units=((254, "WGATE5F"),), name="Patio &lt;&amp;&gt; &quot;x&quot;"),
        network(40, "Bridge", "77/p/40"),
    ])
    first = load_topology(path)
    second = load_topology(path)
    assert first.dot() == second.dot() and first.svg() == second.svg()
    document = minidom.parseString(first.svg().encode())
    assert document.documentElement.tagName == "svg"
    assert 'Warning: Network "N40" is not accessible' in first.svg()
    assert "Patio &lt;&amp;&gt;" in first.svg() and '\\"x\\"' in first.dot()
    assert 'style=dashed, label="circular join"' in first.dot()
    output = tmp_path / "map.svg"
    status, payload = cli(capsys, path, "--format", "svg", "--output", output)
    assert status == 0 and "image" not in payload
    assert output.read_text() == first.svg()
    assert payload["parity"]["pixel_parity"] == "unassessed"
    status, payload = cli(capsys, path, "--format", "svg", "--output", output)
    assert status == 1 and payload["type"] == "FileExistsError"
    assert output.read_text() == first.svg()


@pytest.mark.parametrize("networks, message", [
    ([], "no networks"),
    (["<Network><TagName>A</TagName><Address>1</Address></Network>"], "exactly one Interface"),
    ([network(1, "Serial", "COM1").replace("</Network>", "<Interface><InterfaceType>CNI</InterfaceType></Interface></Network>")],
     "exactly one Interface"),
    ([network(1, "Serial", "COM1"), network(1, "Serial", "COM2")], "Duplicate Network address"),
    ([network(1, "Serial", "COM1", units=((3, "BRIDGE2N"), (3, "RELDN8")))], "Duplicate Unit address"),
    ([network("x1", "Serial", "COM1")], "Address must be an integer"),
    (["<Network><TagName>A</TagName><Address>0x10</Address><Interface><InterfaceType>Serial</InterfaceType></Interface></Network>"],
     "decimal byte"),
])
def test_invalid_projects_fail_closed(tmp_path, capsys, networks, message):
    path = write(tmp_path, networks)
    with pytest.raises(ProjectError, match=message):
        load_topology(path)
    status, payload = cli(capsys, path)
    assert status == 1 and message in payload["error"]


def test_invalid_files_and_selectors(tmp_path, capsys):
    sqlite = write(tmp_path, None, filename="db.xml", raw=b"SQLite format 3\x00" + b"\x00" * 64)
    assert cli(capsys, sqlite)[0] == 1
    dtd = write(tmp_path, None, filename="dtd.xml", raw=b'<!DOCTYPE p [<!ENTITY x "y">]><Project/>')
    assert "DTD" in cli(capsys, dtd)[1]["error"]
    assert "regular file" in cli(capsys, tmp_path)[1]["error"]
    path = write(tmp_path, [network(254, "Serial", "COM1", units=((12, "RELDN8"),))])
    for argv, text in (
        (("--navigate", 9), "Network 9 is absent"),
        (("--near-side", "254-12"), "NETWORK/UNIT"),
        (("--near-side", "254/12"), "no near-side bridge unit"),
        (("--far-side", "999/1"), "decimal byte"),
        (("--navigate", 254, "--near-side", "254/1"), "only one of"),
        (("--navigate", 254, "--format", "svg"), "JSON only"),
        (("--output", tmp_path / "x.json"), "only valid with --format dot or svg"),
    ):
        status, payload = cli(capsys, path, *argv)
        assert status == 1 and text in payload["error"], argv
    assert not (tmp_path / "x.json").exists()


def test_available_row_exhaustion_raises_recovered_message():
    generator = _Generator([])
    generator.mark(0, 2400)
    with pytest.raises(ProjectError, match=TOO_MANY_NETWORKS):
        generator.available_y(0, 0)
    assert _Generator([]).available_y(0, 7) == 7

