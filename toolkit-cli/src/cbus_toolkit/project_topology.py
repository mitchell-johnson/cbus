"""Offline Toolkit topology map, navigation and image export for saved projects.

The model reproduces the statically recovered Toolkit 1.18.0.2754
``TTopologyGenerator`` rules (see
``research/experiments/2026-09-29/topology-generator-static.md``):

* every network whose interface is not ``Bridge`` is a local network and gets an
  interface element (PCI, CNI, CNI2 or CBTI) at column 0;
* a network is explored unit by unit in ascending unit-address order; a unit
  whose type is a near-side bridge or wireless-gateway half connects to the
  network whose *number equals that unit's address*;
* the far-side half is the unit in the far network whose address equals the
  near network number and whose type is a far-side bridge half;
* a near bridge whose address equals the parent network is not drawn again;
  reaching an already explored network draws a circular join;
* every network absent from the map produces ``Network "%s" is not accessible``.

Nothing here opens an endpoint, executes vendor code or writes the project.
Original execution, layout, rendering, print and clipboard parity remain
unassessed: the model is a static reconstruction, not an original capture.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Any
from xml.dom import Node, minidom
from xml.sax.saxutils import escape

from .commissioning_route import project_sha256, read_project_snapshot, resolve_network_route
from .project import ProjectDocument, ProjectError


FORMAT = "cbus-project-topology-v1"
UNASSESSED = "unassessed"
# Toolkit GetAvailableY grid: rows 0..2400, a full column raises this message.
MAX_ROW = 2400
TOO_MANY_NETWORKS = "Too many networks for Topology Map"
ORPHAN_TEXT = 'Network "{}" is not accessible'
PRINT_TITLE = 'C-Bus Project "{}" Network Topology Map'
# TCGateUnitCatalog.IsBridge / IsNearBridge / IsBridgeFarSide, compared lower-case.
# ``bridge1f`` is retained in both side lists exactly as recovered.
BRIDGE_TYPES = frozenset({
    "bridge1n", "bridge2n", "bridge1f", "bridge2f", "gatewls", "gatewlsn",
    "gatewlsf", "wgate5n", "wgate5f", "wgate5xn", "wgate5xf",
})
NEAR_BRIDGE_TYPES = frozenset({"bridge1f", "bridge2n", "gatewlsn", "wgate5n", "wgate5xn"})
FAR_BRIDGE_TYPES = frozenset({"bridge1f", "bridge2f", "gatewlsf", "wgate5f", "wgate5xf"})
WIRELESS_GATEWAY_TYPES = frozenset({
    "gatewls", "gatewlsn", "gatewlsf", "wgate5n", "wgate5f", "wgate5xn", "wgate5xf",
})
WIRELESS_UNIT_NAMES = frozenset({"NEOI 1FL", "NEOI 4FL", "NEOI HHR"})
# TNetworkInterface.GetInterfaceType (case-insensitive) -> (enum, drawn element).
_INTERFACE_TYPES = {
    "serial": (0, "PCI"),
    "c-bus home controller": (4, "CNI2"),
    "spacelogiccbushomecontroller": (10, "CNI2"),
    "lorax": (8, "PCI"),
    "loraxusb": (9, "PCI"),
    "etherlite": (2, "CNI"),
    "socket": (1, "CNI"),
    "wiser": (4, "CNI2"),
    "modem": (7, "CBTI"),
}
_IPV4 = re.compile(r"(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])(\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])){3}")
_BRIDGE_ID = re.compile(r"([0-9]{1,3})/([0-9]{1,3})")
# Delphi TColor values are BGR: $FF0000 is blue, $8844FF is RGB #FF4488.
WIRELESS_COLOR = "#0000FF"
WIRED_COLOR = "#FF4488"
PARITY = {
    "model_basis": "static_disassembly_of_original_toolkit",
    "original_toolkit_executed": False,
    "layout_parity": UNASSESSED,
    "visual_parity": UNASSESSED,
    "pixel_parity": UNASSESSED,
    "print_parity": UNASSESSED,
    "clipboard_copy": "not_implemented",
    "network_order_basis": "project_document_order_unverified",
    "unit_order_basis": "ascending_unit_address",
}


def _local_name(node: Node) -> str:
    return node.localName or node.nodeName


def _children(node: Node, name: str) -> list[minidom.Element]:
    return [
        child for child in node.childNodes
        if child.nodeType == Node.ELEMENT_NODE and _local_name(child) == name
        and child.namespaceURI == node.namespaceURI
    ]


def _scalar(node: Node, name: str, *, required: bool = False) -> str:
    values = _children(node, name)
    if len(values) > 1:
        raise ProjectError(f"Ambiguous {name}: multiple matching fields")
    if not values:
        if required:
            raise ProjectError(f"Missing required {name} field")
        return ""
    if any(child.nodeType == Node.ELEMENT_NODE for child in values[0].childNodes):
        raise ProjectError(f"{name} must be a scalar field")
    return "".join(
        child.data for child in values[0].childNodes
        if child.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE)
    )


def _decimal_byte(value: str, label: str) -> int:
    value = value.strip()
    if not re.fullmatch(r"[0-9]{1,3}", value) or int(value) > 255:
        raise ProjectError(f"{label} must be a decimal byte")
    return int(value)


def classify_interface(interface_type: str, interface_address: str) -> dict[str, Any]:
    """Return the recovered Toolkit interface enum, element and locality."""
    key = interface_type.strip().casefold()
    if key == "bridge":
        return {"enum": 5, "element": None, "local": False, "recognized": True}
    if key == "cni":
        host = interface_address.split(":", 1)[0].strip()
        enum, element = (1, "CNI") if _IPV4.fullmatch(host) else (4, "CNI2")
        return {"enum": enum, "element": element, "local": True, "recognized": True}
    if key in _INTERFACE_TYPES:
        enum, element = _INTERFACE_TYPES[key]
        return {"enum": enum, "element": element, "local": True, "recognized": True}
    # GetInterfaceType falls back to 0, which GenerateNetworkTree draws as PCI.
    return {"enum": 0, "element": "PCI", "local": True, "recognized": False}


def is_wireless_unit_type(unit_type: str) -> bool:
    trimmed = unit_type.strip()
    return trimmed[:1].lower() == "w" or trimmed.upper() in WIRELESS_UNIT_NAMES


@dataclass(frozen=True)
class _Unit:
    address: int
    unit_type: str

    @property
    def key(self) -> str:
        return self.unit_type.strip().lower()


@dataclass
class _Network:
    address: int
    name: str
    interface_type: str
    interface_address: str
    units: dict[int, _Unit]
    kind: dict[str, Any] = field(default_factory=dict)

    @property
    def wireless(self) -> bool:
        return any(is_wireless_unit_type(unit.unit_type) for unit in self.units.values())


def _networks(project: ProjectDocument) -> tuple[str, list[_Network]]:
    project.assert_valid()
    name = _scalar(project.project, "TagName")
    result: list[_Network] = []
    seen: set[int] = set()
    for node in _children(project.project, "Network"):
        address = _decimal_byte(_scalar(node, "Address", required=True), "Network Address")
        if address in seen:
            raise ProjectError(f"Ambiguous topology: duplicate network address {address}")
        seen.add(address)
        interfaces = _children(node, "Interface")
        if len(interfaces) != 1:
            raise ProjectError(f"Network {address} must contain exactly one Interface")
        interface_type = _scalar(interfaces[0], "InterfaceType", required=True).strip()
        interface_address = _scalar(interfaces[0], "InterfaceAddress").strip()
        units: dict[int, _Unit] = {}
        for unit_node in _children(node, "Unit"):
            unit_address = _decimal_byte(_scalar(unit_node, "Address", required=True), "Unit Address")
            if unit_address in units:
                raise ProjectError(
                    f"Ambiguous topology: network {address} has duplicate unit address {unit_address}")
            units[unit_address] = _Unit(unit_address, _scalar(unit_node, "UnitType").strip())
        result.append(_Network(address, _scalar(node, "TagName"), interface_type, interface_address,
                               dict(sorted(units.items())),
                               classify_interface(interface_type, interface_address)))
    if not result:
        raise ProjectError("Project contains no networks")
    return name, result


class _Generator:
    """Deterministic replay of the recovered TTopologyGenerator traversal."""

    def __init__(self, networks: list[_Network]) -> None:
        self.networks = networks
        self.by_address = {network.address: network for network in networks}
        self.grid: set[tuple[int, int]] = set()
        self.processed: list[int] = []
        self.elements: list[dict[str, Any]] = []
        self.bridges: dict[str, dict[str, Any]] = {}
        self.tree_parent: dict[int, tuple[int, str] | None] = {}
        self.root_of: dict[int, int] = {}
        self.circular: list[dict[str, Any]] = []

    def available_y(self, x: int, minimum: int) -> int:
        span = range(x, x + 2 * len(self.networks) + 1)
        occupied = [y for (column, y) in self.grid if column in span and minimum <= y <= MAX_ROW]
        highest = max(occupied, default=-1)
        if highest == MAX_ROW:
            raise ProjectError(TOO_MANY_NETWORKS)
        return max(highest + 1, minimum)

    def mark(self, x: int, y: int) -> None:
        self.grid.add((x, y))

    def network_element(self, network: _Network, start: tuple[int, int],
                        finish: tuple[int, int], circular: bool) -> None:
        self.elements.append({
            "type": "Network", "name": network.name, "address": str(network.address),
            "network": network.address, "start_x": start[0], "start_y": start[1],
            "finish_x": finish[0], "finish_y": finish[1], "circular_join": circular,
            "wireless": network.wireless,
        })

    def run(self) -> None:
        for network in self.networks:
            if not network.kind["local"]:
                continue
            y = self.available_y(0, 0)
            self.elements.append({
                "type": network.kind["element"], "name": network.kind["element"],
                "address": f"{network.address}/{network.interface_address}",
                "network": network.address, "x": 0, "y": y,
            })
            self.mark(0, y)
            self.tree_parent.setdefault(network.address, None)
            self.root_of.setdefault(network.address, network.address)
            self.explore(network, None, y, 0, network.address)

    def explore(self, network: _Network, parent: _Network | None, y: int, level: int, root: int) -> None:
        self.processed.append(network.address)
        parent_address = str(parent.address) if parent is not None else "-1"
        found = False
        for unit in network.units.values():
            if unit.key not in BRIDGE_TYPES or unit.key not in NEAR_BRIDGE_TYPES:
                continue
            far = self.by_address.get(unit.address)
            far_unit = far.units.get(network.address) if far is not None else None
            far_unit_text = str(far_unit.address) if far_unit is not None and far_unit.key in FAR_BRIDGE_TYPES else ""
            bridge_id = f"{network.address}/{unit.address}"
            record = self.bridges.setdefault(bridge_id, {"drawn": False, "skipped_as_parent_link": False,
                                                         "circular_join": False, "positions": []})
            if str(unit.address) == parent_address:
                record["skipped_as_parent_link"] = True
                continue
            x = level + 2
            bridge_y = self.available_y(x, y)
            label = f"{unit.address}/{network.address}-{far_unit_text}"
            self.elements.append({
                "type": "Bridge", "name": "Bridge", "address": label, "bridge": bridge_id,
                "x": x, "y": bridge_y, "wireless": unit.key in WIRELESS_GATEWAY_TYPES,
            })
            self.mark(x, bridge_y)
            record["drawn"] = True
            record["positions"].append({"x": x, "y": bridge_y})
            self.network_element(network, (level, y), (x, bridge_y), False)
            if far is not None:
                if far.address not in self.processed:
                    self.tree_parent.setdefault(far.address, (network.address, bridge_id))
                    self.root_of.setdefault(far.address, root)
                    self.explore(far, network, bridge_y, x, root)
                else:
                    record["circular_join"] = True
                    self.circular.append({"network": far.address, "bridge": bridge_id})
                    self.network_element(far, (x, bridge_y), (x + 1, bridge_y), True)
            found = True
        if not found:
            self.network_element(network, (level, y), (level + 1, y), False)


def _unit_record(project_name: str, network: int, unit: _Unit | None, unit_address: int) -> dict[str, Any]:
    return {
        "network": network, "unit": unit_address,
        "unit_type": unit.unit_type if unit is not None else None,
        "path": f"/network/{network}/unit/{unit_address}",
        "cgate_address": f"//{project_name}/{network}/p/{unit_address}",
    }


def _bridge_parent(network: _Network) -> tuple[int | None, str | None]:
    parts = network.interface_address.strip("/").split("/")
    if len(parts) != 3 or parts[1].casefold() != "p":
        return None, "malformed"
    try:
        parent = _decimal_byte(parts[0], "parent")
        unit = _decimal_byte(parts[2], "unit")
    except ProjectError:
        return None, "malformed"
    if unit != network.address:
        return parent, "unit_mismatch"
    return parent, None


class TopologyModel:
    """Generated topology plus navigation resolvers for one project snapshot."""

    def __init__(self, project: ProjectDocument, *, digest: str, size: int) -> None:
        self.project_name, self.networks = _networks(project)
        self.digest = digest
        self.size = size
        self.format = project.format
        self.by_address = {network.address: network for network in self.networks}
        self.generator = _Generator(self.networks)
        self.generator.run()
        in_map = {element["network"] for element in self.generator.elements if element["type"] == "Network"}
        self.orphaned = [network.address for network in self.networks if network.address not in in_map]
        self.project_document = project

    # -- JSON model ---------------------------------------------------------
    def bridges(self) -> list[dict[str, Any]]:
        result = []
        for network in self.networks:
            for unit in network.units.values():
                if unit.key not in NEAR_BRIDGE_TYPES:
                    continue
                bridge_id = f"{network.address}/{unit.address}"
                far = self.by_address.get(unit.address)
                far_unit = far.units.get(network.address) if far is not None else None
                far_ok = far_unit is not None and far_unit.key in FAR_BRIDGE_TYPES
                state = self.generator.bridges.get(bridge_id, {})
                result.append({
                    "id": bridge_id,
                    "toolkit_label": f"{unit.address}/{network.address}-{far_unit.address if far_ok else ''}",
                    "unit_type": unit.unit_type,
                    "wireless_gateway": unit.key in WIRELESS_GATEWAY_TYPES,
                    "near_side": _unit_record(self.project_name, network.address, unit, unit.address),
                    "far_network": unit.address,
                    "far_network_present": far is not None,
                    "far_side": _unit_record(self.project_name, unit.address, far_unit, network.address) if far_ok else None,
                    "drawn": bool(state.get("drawn")),
                    "skipped_as_parent_link": bool(state.get("skipped_as_parent_link")),
                    "circular_join": bool(state.get("circular_join")),
                    "positions": list(state.get("positions", [])),
                })
        return result

    def diagnostics(self) -> list[dict[str, Any]]:
        """CLI-only consistency findings; the Toolkit draws these silently."""
        found: list[dict[str, Any]] = []
        near_targets: dict[int, list[str]] = {}
        for network in self.networks:
            if not network.kind["recognized"]:
                found.append({"code": "unrecognized_interface_type", "network": network.address,
                              "interface_type": network.interface_type,
                              "message": "Toolkit falls back to a PCI element for this interface type"})
            for unit in network.units.values():
                if unit.key not in NEAR_BRIDGE_TYPES:
                    continue
                bridge_id = f"{network.address}/{unit.address}"
                near_targets.setdefault(unit.address, []).append(bridge_id)
                far = self.by_address.get(unit.address)
                if unit.address == network.address:
                    found.append({"code": "bridge_targets_own_network", "bridge": bridge_id,
                                  "message": "Near bridge unit address equals its own network"})
                if far is None:
                    found.append({"code": "bridge_far_network_missing", "bridge": bridge_id,
                                  "message": f"No network {unit.address} exists for the far side"})
                    continue
                far_unit = far.units.get(network.address)
                if far_unit is None:
                    found.append({"code": "bridge_far_unit_missing", "bridge": bridge_id,
                                  "message": f"Network {far.address} has no unit at address {network.address}"})
                elif far_unit.key not in FAR_BRIDGE_TYPES:
                    found.append({"code": "bridge_far_unit_not_far_side", "bridge": bridge_id,
                                  "unit_type": far_unit.unit_type,
                                  "message": f"Network {far.address} unit {network.address} is not a far-side bridge half"})
                if far.kind["local"]:
                    found.append({"code": "bridge_far_network_has_local_interface", "bridge": bridge_id,
                                  "message": f"Network {far.address} is reached by a bridge but has a local interface"})
                else:
                    parent, problem = _bridge_parent(far)
                    if problem is None and parent != network.address:
                        found.append({"code": "bridge_interface_parent_contradiction", "bridge": bridge_id,
                                      "interface_address": far.interface_address,
                                      "message": f"Network {far.address} Bridge interface names parent {parent}, not {network.address}"})
        for target, bridge_ids in sorted(near_targets.items()):
            if len(bridge_ids) > 1:
                found.append({"code": "multiple_near_bridges_to_network", "network": target,
                              "bridges": bridge_ids,
                              "message": f"Network {target} is reached from {len(bridge_ids)} near bridges"})
        for network in self.networks:
            if network.kind["local"]:
                continue
            parent, problem = _bridge_parent(network)
            if problem == "malformed":
                found.append({"code": "bridge_interface_address_malformed", "network": network.address,
                              "interface_address": network.interface_address,
                              "message": "Bridge InterfaceAddress is not PARENT/p/UNIT"})
                continue
            if problem == "unit_mismatch":
                found.append({"code": "bridge_interface_unit_mismatch", "network": network.address,
                              "interface_address": network.interface_address,
                              "message": "Bridge InterfaceAddress unit differs from the network address"})
            parent_network = self.by_address.get(parent) if parent is not None else None
            if parent_network is None:
                found.append({"code": "bridge_interface_parent_missing", "network": network.address,
                              "interface_address": network.interface_address,
                              "message": f"Bridge InterfaceAddress names missing network {parent}"})
            else:
                near = parent_network.units.get(network.address)
                if near is None or near.key not in NEAR_BRIDGE_TYPES:
                    found.append({"code": "bridge_interface_without_near_unit", "network": network.address,
                                  "interface_address": network.interface_address,
                                  "message": f"Network {parent} has no near-side bridge unit at address {network.address}"})
        return found

    def as_dict(self) -> dict[str, Any]:
        generator = self.generator
        bridges = self.bridges()
        warnings = [
            {"kind": "orphaned_network", "network": address,
             "text": ORPHAN_TEXT.format(self.by_address[address].name), "toolkit_rendering": "warning_text"}
            for address in self.orphaned
        ] + [
            {"kind": "circular_join", "network": item["network"], "bridge": item["bridge"],
             "toolkit_rendering": "circular_join_arrow"}
            for item in generator.circular
        ]
        return {
            "format": FORMAT,
            "project": self.identity(),
            "print_title": PRINT_TITLE.format(self.project_name),
            "networks": [
                {
                    "address": network.address, "name": network.name, "path": f"/network/{network.address}",
                    "interface_type": network.interface_type, "interface_address": network.interface_address,
                    "interface_element": network.kind["element"], "interface_enum": network.kind["enum"],
                    "local": network.kind["local"], "wireless": network.wireless,
                    "unit_count": len(network.units),
                    "in_topology_map": network.address not in self.orphaned,
                    "local_root": generator.root_of.get(network.address),
                }
                for network in self.networks
            ],
            "local_networks": [network.address for network in self.networks if network.kind["local"]],
            "interfaces": [dict(element) for element in generator.elements
                           if element["type"] in ("PCI", "CNI", "CNI2", "CBTI")],
            "bridges": bridges,
            "wireless_gateways": [bridge["id"] for bridge in bridges if bridge["wireless_gateway"]],
            "orphaned_networks": list(self.orphaned),
            "circular_joins": [dict(item) for item in generator.circular],
            "warnings": warnings,
            "diagnostics": self.diagnostics(),
            "elements": [dict(element) for element in generator.elements],
            "parity": dict(PARITY),
        }

    def identity(self) -> dict[str, Any]:
        return {"name": self.project_name, "sha256": self.digest, "bytes": self.size, "format": self.format}

    # -- navigation --------------------------------------------------------
    def _network(self, address: int) -> _Network:
        network = self.by_address.get(address)
        if network is None:
            raise ProjectError(f"Network {address} is absent from the project")
        return network

    def navigate(self, address: int) -> dict[str, Any]:
        network = self._network(address)
        chain: list[dict[str, Any]] = []
        current: int | None = address
        while current is not None:
            chain.append({"network": current})
            parent = self.generator.tree_parent.get(current)
            if parent is None:
                break
            chain.append({"bridge": parent[1]})
            current = parent[0]
        in_map = address not in self.orphaned
        root = self.generator.root_of.get(address)
        route: dict[str, Any]
        if root is None:
            route = {"available": False, "reason": "Network is not reachable from a local network"}
        else:
            try:
                bridges = resolve_network_route(self.project_document, source_network=root,
                                                target_network=address)
                route = {"available": True, "planner": "commissioning_route", "source_network": root,
                         "bridges": list(bridges), "depth": len(bridges)}
            except (ProjectError, ValueError) as error:
                route = {"available": False, "planner": "commissioning_route", "source_network": root,
                         "reason": str(error)}
        return {
            "action": "navigate", "network": address, "name": network.name,
            "path": f"/network/{address}",
            "units": [_unit_record(self.project_name, address, unit, unit.address)
                      for unit in network.units.values()],
            "in_topology_map": in_map,
            "local": network.kind["local"],
            "toolkit_tree_path": list(reversed(chain)) if in_map and root is not None else None,
            "route": route,
        }

    def bridge_side(self, bridge_id: str, side: str) -> dict[str, Any]:
        match = _BRIDGE_ID.fullmatch(bridge_id)
        if match is None:
            raise ProjectError("Bridge must be NETWORK/UNIT naming its near-side unit, e.g. 254/3")
        near_net = _decimal_byte(match[1], "Bridge network")
        near_address = _decimal_byte(match[2], "Bridge unit")
        network = self._network(near_net)
        unit = network.units.get(near_address)
        if unit is None or unit.key not in NEAR_BRIDGE_TYPES:
            raise ProjectError(f"Network {near_net} has no near-side bridge unit at address {near_address}")
        bridge = next(item for item in self.bridges() if item["id"] == f"{near_net}/{near_address}")
        if side == "near":
            resolved = bridge["near_side"]
        else:
            resolved = bridge["far_side"]
            if resolved is None:
                far = self.by_address.get(near_address)
                where = f"network {near_address}" if far is not None else f"missing network {near_address}"
                raise ProjectError(
                    f"Far side of bridge {bridge['id']} is unresolved: {where} has no far-side bridge unit at address {near_net}")
        return {"action": f"{side}-side", "bridge": bridge["id"], "toolkit_label": bridge["toolkit_label"],
                "drawn": bridge["drawn"], "wireless_gateway": bridge["wireless_gateway"], **resolved}

    # -- images ------------------------------------------------------------
    def dot(self) -> str:
        lines = [f"digraph {_dot_id('topology')} {{",
                 f"  label={_dot_id(PRINT_TITLE.format(self.project_name))};",
                 "  labelloc=t;", "  rankdir=LR;", "  node [fontname=Helvetica];"]
        nodes: list[str] = []
        edges: list[str] = []
        declared: set[str] = set()

        def node(identifier: str, attributes: str) -> None:
            if identifier not in declared:
                declared.add(identifier)
                nodes.append(f"  {_dot_id(identifier)} [{attributes}];")

        for network in self.networks:
            node(f"network:{network.address}",
                 f"shape=box, label={_dot_id(f'{network.name} addr={network.address}')}, "
                 f"color={_dot_id(WIRELESS_COLOR if network.wireless else WIRED_COLOR)}")
        for element in self.generator.elements:
            kind = element["type"]
            if kind in ("PCI", "CNI", "CNI2", "CBTI"):
                identifier = f"interface:{element['network']}"
                node(identifier, f"shape=ellipse, label={_dot_id(kind + ' ' + element['address'])}")
                edges.append(f"  {_dot_id(identifier)} -> {_dot_id('network:%d' % element['network'])};")
            elif kind == "Bridge":
                identifier = f"bridge:{element['bridge']}"
                color = WIRELESS_COLOR if element["wireless"] else WIRED_COLOR
                node(identifier, f"shape=diamond, label={_dot_id('Bridge ' + element['address'])}, color={_dot_id(color)}")
                near, far = element["bridge"].split("/")
                edges.append(f"  {_dot_id('network:' + near)} -> {_dot_id(identifier)};")
                if int(far) in self.by_address:
                    circular = self.generator.bridges[element["bridge"]]["circular_join"]
                    style = " [style=dashed, label=\"circular join\"]" if circular else ""
                    edges.append(f"  {_dot_id(identifier)} -> {_dot_id('network:' + far)}{style};")
        for index, address in enumerate(self.orphaned):
            text = ORPHAN_TEXT.format(self.by_address[address].name)
            node(f"warning:{index}", f"shape=note, label={_dot_id('Warning: ' + text)}")
        lines.extend(nodes)
        lines.extend(edges)
        lines.append("}")
        return "\n".join(lines) + "\n"

    def svg(self) -> str:
        cx, cy, margin = 90, 60, 40
        columns = [0]
        rows = [0]
        for element in self.generator.elements:
            if "x" in element:
                columns.append(element["x"]); rows.append(element["y"])
            else:
                columns.extend((element["start_x"], element["finish_x"]))
                rows.extend((element["start_y"], element["finish_y"]))
        warnings = [ORPHAN_TEXT.format(self.by_address[address].name) for address in self.orphaned]
        width = margin * 2 + (max(columns) + 1) * cx
        height = margin * 2 + (max(rows) + 1) * cy + 20 * len(warnings) + 20
        width = max(width, 320)
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" font-family="Helvetica, Arial, sans-serif" font-size="11">',
            f"<title>{escape(PRINT_TITLE.format(self.project_name))}</title>",
            f'<rect x="0" y="0" width="{width}" height="{height}" fill="#FFFFFF"/>',
        ]

        def point(x: int, y: int) -> tuple[int, int]:
            return margin + x * cx, margin + 20 + y * cy

        for element in self.generator.elements:
            if element["type"] != "Network":
                continue
            sx, sy = point(element["start_x"], element["start_y"])
            fx, fy = point(element["finish_x"], element["finish_y"])
            color = WIRELESS_COLOR if element["wireless"] else WIRED_COLOR
            dash = ' stroke-dasharray="6 3"' if element["circular_join"] else ""
            parts.append(f'<polyline points="{sx},{sy} {sx},{fy} {fx},{fy}" fill="none" '
                         f'stroke="{color}" stroke-width="2"{dash}/>')
            caption = f"{element['name']} addr={element['address']}"
            parts.append(f'<text x="{sx + 4}" y="{fy - 4}" fill="{color}">{escape(caption)}</text>')
        for element in self.generator.elements:
            kind = element["type"]
            if kind == "Network":
                continue
            x, y = point(element["x"], element["y"])
            if kind == "Bridge":
                color = WIRELESS_COLOR if element["wireless"] else WIRED_COLOR
                parts.append(f'<polygon points="{x},{y - 12} {x + 12},{y} {x},{y + 12} {x - 12},{y}" '
                             f'fill="#FFFFFF" stroke="{color}" stroke-width="2"/>')
            else:
                parts.append(f'<rect x="{x - 18}" y="{y - 10}" width="36" height="20" fill="#FFFFFF" '
                             f'stroke="#000000"/>')
            parts.append(f'<text x="{x}" y="{y + 26}" text-anchor="middle">'
                         f'{escape(kind + " " + element["address"])}</text>')
        base = height - margin - 20 * len(warnings) + 10
        for index, text in enumerate(warnings):
            parts.append(f'<text x="{margin}" y="{base + 20 * index}" fill="#CC0000">'
                         f'{escape("Warning: " + text)}</text>')
        parts.append("</svg>")
        return "\n".join(parts) + "\n"


def _dot_id(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def load_topology(path: Path) -> TopologyModel:
    """Read one bounded project snapshot and build the topology model."""
    snapshot = read_project_snapshot(Path(path))
    project = ProjectDocument.from_snapshot(snapshot, source=Path(path))
    return TopologyModel(project, digest=project_sha256(snapshot), size=len(snapshot))


def _write_new(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    handle = os.open(path, flags, 0o666)
    try:
        try:
            view = memoryview(payload)
            while view:
                written = os.write(handle, view)
                if written <= 0:
                    raise OSError("Image writer made no progress")
                view = view[written:]
            os.fsync(handle)
        finally:
            os.close(handle)
    except BaseException:
        # The file was created exclusively by this call, so a partial image is ours to remove.
        os.unlink(path)
        raise


def run(args) -> tuple[dict[str, Any], int]:
    import hashlib

    selectors = [name for name in ("navigate", "near_side", "far_side") if getattr(args, name) is not None]
    if len(selectors) > 1:
        raise ValueError("Use only one of --navigate, --near-side or --far-side")
    if selectors and (args.format != "json" or args.output is not None):
        raise ValueError("Navigation options produce JSON only; omit --format and --output")
    if args.format == "json" and args.output is not None:
        raise ValueError("--output is only valid with --format dot or svg")
    model = load_topology(args.file)
    if args.navigate is not None:
        return {"project": model.identity(), "navigation": model.navigate(args.navigate)}, 0
    if args.near_side is not None:
        return {"project": model.identity(), "navigation": model.bridge_side(args.near_side, "near")}, 0
    if args.far_side is not None:
        return {"project": model.identity(), "navigation": model.bridge_side(args.far_side, "far")}, 0
    if args.format == "json":
        return model.as_dict(), 0
    image = model.dot() if args.format == "dot" else model.svg()
    payload = image.encode("utf-8")
    result: dict[str, Any] = {
        "project": model.identity(), "image_format": args.format,
        "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
        "orphaned_networks": list(model.orphaned),
        "circular_joins": [dict(item) for item in model.generator.circular],
        "parity": dict(PARITY),
    }
    if args.output is None:
        result["image"] = image
    else:
        _write_new(args.output, payload)
        result["file"] = str(args.output)
    return result, 0


def options(commands) -> None:
    from .cli import _byte

    parser = commands.add_parser(
        "topology",
        help="Build the Toolkit topology map of a saved XML/CBZ project, navigate it, or export DOT/SVG",
    )
    parser.add_argument("file", type=Path)
    parser.add_argument("--format", choices=("json", "dot", "svg"), default="json",
                        help="json model (default) or a deterministic dot/svg image")
    parser.add_argument("--output", type=Path, help="Write the dot/svg image to a new file; never overwrites")
    parser.add_argument("--navigate", type=_byte, metavar="NET",
                        help="Resolve a network to its project path, unit paths and bridge route")
    parser.add_argument("--near-side", metavar="NET/UNIT",
                        help="Resolve the near-side unit of the bridge at NET/UNIT")
    parser.add_argument("--far-side", metavar="NET/UNIT",
                        help="Resolve the far-side unit of the bridge whose near side is NET/UNIT")
