"""Pure project-topology planning for one exact routed commissioning exchange.

The planner reads only a caller-supplied :class:`ProjectDocument`.  It mirrors
cmqttd's retained C-Gate bridge convention: a Bridge network names its parent
as ``PARENT/p/INTERFACE_UNIT``, while the emitted route byte is the far-side
network address.  Every transition requires a conventional ``BRIDGE2N`` unit
at that address in the source network.

No endpoint is opened here.  A plan binds the project bytes by SHA-256 so the
CLI can reject a changed project immediately before handing a one-shot CAL
request to the transport.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from xml.dom import Node, minidom

from .pci_routed_recall import RoutedReplyPath
from .project import MAX_DOCUMENT_BYTES, ProjectDocument, ProjectError


MAX_BRIDGES = 6
SUPPORTED_ROOT_INTERFACES = frozenset({"cni", "serial"})
SUPPORTED_BRIDGE_UNIT_TYPES = frozenset({"BRIDGE2N"})
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _local_name(node: Node) -> str:
    return node.localName or node.nodeName


def _children(node: Node, name: str) -> list[minidom.Element]:
    return [
        child
        for child in node.childNodes
        if child.nodeType == Node.ELEMENT_NODE
        and _local_name(child) == name
        and child.namespaceURI == node.namespaceURI
    ]


def _scalar(node: Node, name: str, *, required: bool = True) -> str:
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
        child.data
        for child in values[0].childNodes
        if child.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE)
    )


def _byte(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError(f"{label} must be an integer in 0..255")
    return value


def _decimal_byte(value: str, label: str) -> int:
    if not re.fullmatch(r"[0-9]{1,3}", value):
        raise ProjectError(f"{label} must be a decimal byte")
    result = int(value)
    if result > 255:
        raise ProjectError(f"{label} must be a decimal byte")
    return result


@dataclass(frozen=True)
class _Unit:
    address: int
    unit_type: str


@dataclass(frozen=True)
class _Network:
    address: int
    tag_name: str
    interface_type: str
    interface_address: str
    units: dict[int, _Unit]


@dataclass(frozen=True)
class CommissioningRoutePlan:
    """Immutable route and independent return-path expectation."""

    project_name: str
    project_sha256: str
    project_format: str
    source_network: int
    target_network: int
    target_unit: int
    target_unit_type: str
    local_unit: int
    expected_ack_tag: int | None
    bridges: tuple[int, ...]
    expected: RoutedReplyPath

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.project_sha256):
            raise ValueError("project_sha256 must be 64 lowercase hexadecimal characters")
        for value, label in (
            (self.source_network, "source_network"),
            (self.target_network, "target_network"),
            (self.target_unit, "target_unit"),
            (self.local_unit, "local_unit"),
        ):
            _byte(value, label)
        if self.expected_ack_tag is not None:
            _byte(self.expected_ack_tag, "expected_ack_tag")
        if type(self.bridges) is not tuple or len(self.bridges) > MAX_BRIDGES:
            raise ValueError("bridges must be a tuple of at most six bytes")
        for bridge in self.bridges:
            _byte(bridge, "bridge")
        if not self.project_name or not self.target_unit_type:
            raise ValueError("project and target-unit identity must be present")

    def as_dict(self) -> dict[str, object]:
        result = {
            "format": "cbus-commissioning-route-plan-v1",
            "project_name": self.project_name,
            "project_sha256": self.project_sha256,
            "project_format": self.project_format,
            "source_network": self.source_network,
            "target_network": self.target_network,
            "target_unit": self.target_unit,
            "target_unit_type": self.target_unit_type,
            "local_unit": self.local_unit,
            "bridges": list(self.bridges),
            "route_depth": len(self.bridges),
            "logical_network_resolved": True,
            "project_snapshot_bound": True,
            "physical_bridge_acceptance_verified": False,
            "physical_delivery_verified": False,
            "nonvolatile_persistence_verified": False,
        }
        if self.expected_ack_tag is None:
            result["expected_reply_path"] = self.expected.as_dict()
        else:
            result["expected_ack_tag"] = self.expected_ack_tag
            result["expected_ack_path"] = self.expected.as_dict()
        return result


def project_sha256(payload: bytes) -> str:
    if type(payload) is not bytes:
        raise TypeError("project payload must be bytes")
    return hashlib.sha256(payload).hexdigest()


def read_project_snapshot(path: Path) -> bytes:
    """Read one bounded regular-file snapshot without opening a FIFO or device."""
    if not isinstance(path, Path):
        raise TypeError("project path must be a pathlib.Path")
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ProjectError("Project snapshot must be a regular file")
        if before.st_size > MAX_DOCUMENT_BYTES:
            raise ProjectError("Project file exceeds the configured size limit")
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ProjectError("Project snapshot must be a regular file")
            if opened.st_size > MAX_DOCUMENT_BYTES:
                raise ProjectError("Project file exceeds the configured size limit")
            payload = stream.read(MAX_DOCUMENT_BYTES + 1)
    except OSError as error:
        raise ProjectError(f"Unable to read project snapshot: {error}") from error
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ProjectError("Project file exceeds the configured size limit")
    return payload


def assert_fresh_project(path: Path, expected_sha256: str) -> None:
    """Reject a missing, substituted, or changed project snapshot."""
    if not isinstance(path, Path):
        raise TypeError("project path must be a pathlib.Path")
    if not _SHA256.fullmatch(expected_sha256):
        raise ValueError("expected project SHA-256 is invalid")
    try:
        payload = read_project_snapshot(path)
    except ProjectError as error:
        raise ProjectError(f"Unable to re-read project snapshot: {error}") from error
    actual = project_sha256(payload)
    if actual != expected_sha256:
        raise ProjectError(
            f"Project topology is stale or was substituted: expected {expected_sha256}, got {actual}"
        )


def _project_networks(project: ProjectDocument) -> tuple[str, dict[int, _Network]]:
    project.assert_valid()
    name = _scalar(project.project, "TagName")
    if not name.strip():
        raise ProjectError("Project TagName must not be empty")
    result: dict[int, _Network] = {}
    for network_node in _children(project.project, "Network"):
        address = _decimal_byte(_scalar(network_node, "Address"), "Network Address")
        if address in result:
            raise ProjectError(f"Ambiguous topology: duplicate network address {address}")
        interfaces = _children(network_node, "Interface")
        if len(interfaces) != 1:
            raise ProjectError(
                f"Network {address} must contain exactly one Interface for typed routing"
            )
        interface_type = _scalar(interfaces[0], "InterfaceType")
        interface_address = _scalar(interfaces[0], "InterfaceAddress", required=False)
        units: dict[int, _Unit] = {}
        for unit_node in _children(network_node, "Unit"):
            unit_address = _decimal_byte(_scalar(unit_node, "Address"), "Unit Address")
            if unit_address in units:
                raise ProjectError(
                    f"Ambiguous topology: network {address} has duplicate unit address {unit_address}"
                )
            unit_type = _scalar(unit_node, "UnitType")
            if not unit_type.strip():
                raise ProjectError(
                    f"Network {address} unit {unit_address} has no supported UnitType"
                )
            units[unit_address] = _Unit(unit_address, unit_type.strip())
        result[address] = _Network(
            address,
            _scalar(network_node, "TagName", required=False),
            interface_type.strip(),
            interface_address.strip(),
            units,
        )
    if not result:
        raise ProjectError("Project contains no networks")
    return name, result


def _parent(network: _Network, networks: dict[int, _Network]) -> int | None:
    interface_type = network.interface_type.casefold()
    if interface_type != "bridge":
        if interface_type not in SUPPORTED_ROOT_INTERFACES:
            raise ProjectError(
                f"Network {network.address} uses unsupported root interface {network.interface_type!r}"
            )
        return None
    parts = network.interface_address.strip("/").split("/")
    if len(parts) != 3:
        raise ProjectError(
            f"Network {network.address} has malformed Bridge InterfaceAddress"
        )
    parent = _decimal_byte(parts[0], f"Network {network.address} Bridge parent")
    interface_unit = _decimal_byte(parts[2], f"Network {network.address} Bridge interface unit")
    if parts[1].casefold() != "p" or parent == network.address:
        raise ProjectError(
            f"Network {network.address} has inconsistent Bridge InterfaceAddress"
        )
    if interface_unit != network.address:
        raise ProjectError(
            f"Network {network.address} Bridge InterfaceAddress names unit {interface_unit}; "
            "the supported conventional route requires its far-side network address"
        )
    if parent not in networks:
        raise ProjectError(
            f"Network {network.address} references missing parent network {parent}"
        )
    return parent


def _chain(start: int, networks: dict[int, _Network]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    current = start
    while True:
        if current in seen:
            raise ProjectError(f"Bridge topology contains a cycle involving network {current}")
        seen.add(current)
        result.append(current)
        parent = _parent(networks[current], networks)
        if parent is None:
            return result
        current = parent


def _route(source: int, target: int, networks: dict[int, _Network]) -> tuple[int, ...]:
    source_chain = _chain(source, networks)
    target_chain = _chain(target, networks)
    target_positions = {address: index for index, address in enumerate(target_chain)}
    common: tuple[int, int] | None = None
    for source_index, address in enumerate(source_chain):
        if address in target_positions:
            common = source_index, target_positions[address]
            break
    if common is None:
        raise ProjectError("Source and target networks are disconnected")
    source_lca, target_lca = common
    route = source_chain[1:source_lca + 1]
    route.extend(reversed(target_chain[:target_lca]))
    if len(route) > MAX_BRIDGES:
        raise ProjectError("Network path exceeds the supported six-bridge limit")
    current = source
    for destination in route:
        bridge = networks[current].units.get(destination)
        if bridge is None:
            raise ProjectError(
                f"Network {current} has no bridge unit at conventional address {destination}"
            )
        if bridge.unit_type.upper() not in SUPPORTED_BRIDGE_UNIT_TYPES:
            raise ProjectError(
                f"Network {current} unit {destination} has unsupported bridge type {bridge.unit_type!r}"
            )
        current = destination
    return tuple(route)


def plan_commissioning_route(
    project: ProjectDocument,
    *,
    project_digest: str,
    source_network: int,
    target_network: int,
    target_unit: int,
    local_unit: int,
    expected_ack_tag: int | None = None,
    expected_project_name: str | None = None,
) -> CommissioningRoutePlan:
    """Resolve one unit target into outbound and independent return-route bytes."""
    if type(project) is not ProjectDocument:
        raise TypeError("project must be an exact ProjectDocument")
    if not _SHA256.fullmatch(project_digest):
        raise ValueError("project_digest must be 64 lowercase hexadecimal characters")
    source = _byte(source_network, "source_network")
    target = _byte(target_network, "target_network")
    unit = _byte(target_unit, "target_unit")
    local = _byte(local_unit, "local_unit")
    ack_tag = None if expected_ack_tag is None else _byte(expected_ack_tag, "expected_ack_tag")
    project_name, networks = _project_networks(project)
    if expected_project_name is not None:
        if type(expected_project_name) is not str or not expected_project_name:
            raise ValueError("expected_project_name must be non-empty text")
        if expected_project_name != project_name:
            raise ProjectError(
                f"Project identity mismatch: expected {expected_project_name!r}, got {project_name!r}"
            )
    if source not in networks:
        raise ProjectError(f"Source network {source} is absent from the project")
    if target not in networks:
        raise ProjectError(f"Target network {target} is absent from the project")
    if networks[source].interface_type.casefold() not in SUPPORTED_ROOT_INTERFACES:
        raise ProjectError(
            "Source network must be directly attached through a CNI or Serial interface; "
            "reverse and sibling bridge starts are unsupported"
        )
    target_record = networks[target].units.get(unit)
    if target_record is None:
        raise ProjectError(f"Target unit {unit} is absent from network {target}")
    bridges = _route(source, target, networks)
    # Retained one- and six-bridge Reply Network vectors establish this
    # independent reverse envelope: the nearest bridge is the outer source,
    # followed by every remaining far-side network byte and the replying unit.
    # It is intentionally derived separately from RoutedCALCommand encoding.
    if bridges:
        expected = RoutedReplyPath(bridges[0], local, bridges[1:] + (unit,))
    else:
        expected = RoutedReplyPath(unit, local, ())
    return CommissioningRoutePlan(
        project_name=project_name,
        project_sha256=project_digest,
        project_format=project.format,
        source_network=source,
        target_network=target,
        target_unit=unit,
        target_unit_type=target_record.unit_type,
        local_unit=local,
        expected_ack_tag=ack_tag,
        bridges=bridges,
        expected=expected,
    )
