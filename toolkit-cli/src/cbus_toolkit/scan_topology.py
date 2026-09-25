"""Pure offline scan/unravel topology planner (no I/O, no endpoints).

Covers one RED/GREEN slice of multi-bridge scan reconciliation: bridge
topology validation (cycles, duplicate networks, empty input) and
deterministic local-vs-remote inventory reconciliation
(moves/adds/duplicates/conflicts).

All inputs are explicit arguments. This module performs no I/O, opens no
endpoints, and stores no credentials. Snapshots are plain mappings of
``network_id -> list of (unit_address, serial)`` pairs; any non-integer
keys are treated as unrelated metadata and echoed back verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
import copy


@dataclass(frozen=True)
class BridgeNode:
    """One bridge attachment point in the scanned topology."""

    network_id: int
    bridge_address: int
    child_networks: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        child_networks = tuple(self.child_networks)
        object.__setattr__(self, "child_networks", child_networks)
        if not isinstance(self.network_id, int) or isinstance(self.network_id, bool):
            raise ValueError(f"invalid network_id {self.network_id!r}")
        if not isinstance(self.bridge_address, int) or isinstance(self.bridge_address, bool):
            raise ValueError(f"invalid bridge_address {self.bridge_address!r}")
        for child in child_networks:
            if not isinstance(child, int) or isinstance(child, bool):
                raise ValueError(f"invalid child network_id {child!r}")
        if not 0 <= self.network_id <= 255:
            raise ValueError(f"invalid network_id {self.network_id!r}")
        if not 0 <= self.bridge_address <= 255:
            raise ValueError(f"invalid bridge_address {self.bridge_address!r}")
        for child in child_networks:
            if not 0 <= child <= 255:
                raise ValueError(f"invalid child network_id {child!r}")
        if len(set(child_networks)) != len(child_networks):
            raise ValueError(f"duplicate child network in {child_networks!r}")


# A snapshot maps integer network_id -> list of (unit_address, serial)
# pairs. Non-integer keys are unrelated metadata preserved verbatim in
# the plan echo and never interpreted as topology.
InventorySnapshot = dict[Any, Any]


def _split_snapshot(snapshot: Mapping[Any, Any], label: str) -> tuple[dict[int, list[tuple[int, str]]], dict[Any, Any]]:
    if not isinstance(snapshot, Mapping):
        raise ValueError(f"{label} snapshot must be a mapping")
    networks: dict[int, list[tuple[int, str]]] = {}
    extra: dict[Any, Any] = {}
    for key, value in snapshot.items():
        if isinstance(key, int) and not isinstance(key, bool):
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"network {key} entries must be a list of (unit_address, serial) pairs")
            entries: list[tuple[int, str]] = []
            seen_units: set[int] = set()
            for item in value:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    raise ValueError(f"network {key} entries must be a list of (unit_address, serial) pairs")
                unit_address, serial = item[0], item[1]
                if (not isinstance(unit_address, int) or isinstance(unit_address, bool)
                        or not 0 <= unit_address <= 255):
                    raise ValueError(f"invalid unit_address {unit_address!r} for network {key}")
                if not isinstance(serial, str) or not serial:
                    raise ValueError(f"invalid serial {serial!r} for network {key}")
                if unit_address in seen_units:
                    raise ValueError(
                        f"duplicate location (network {key}, unit {unit_address}) in {label} snapshot"
                    )
                seen_units.add(unit_address)
                entries.append((unit_address, serial))
            entries.sort(key=lambda entry: (entry[0], entry[1]))
            networks[key] = entries
        else:
            extra[key] = value
    return networks, extra


def validate_topology(bridges: Sequence[BridgeNode]) -> list[BridgeNode]:
    """Validate bridge topology and return nodes in stable network_id order.

    Raises:
        ValueError: "topology must contain at least one bridge" for empty
            input, "duplicate network_id: {id}" for repeated networks,
            "unknown child network: {id}" for dangling references, or
            "topology cycle detected involving network {id}" for cycles.
    """
    if bridges is None:
        raise ValueError("topology must contain at least one bridge")
    try:
        nodes = list(bridges)
    except TypeError:
        raise ValueError("topology must contain at least one bridge")
    if len(nodes) == 0:
        raise ValueError("topology must contain at least one bridge")
    for node in nodes:
        if not isinstance(node, BridgeNode):
            raise ValueError("each bridge must be a BridgeNode")
    seen: set[int] = set()
    for node in nodes:
        if node.network_id in seen:
            raise ValueError(f"duplicate network_id: {node.network_id}")
        seen.add(node.network_id)
    children: dict[int, tuple[int, ...]] = {node.network_id: node.child_networks for node in nodes}
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = {network_id: WHITE for network_id in children}

    def visit(network_id: int, stack: tuple[int, ...]) -> None:
        color[network_id] = GRAY
        for child in children[network_id]:
            if child not in color:
                raise ValueError(f"unknown child network: {child}")
            if color[child] == GRAY:
                raise ValueError(f"topology cycle detected involving network {child}")
            if color[child] == WHITE:
                visit(child, stack + (child,))
        color[network_id] = BLACK

    for network_id in sorted(color):
        if color[network_id] == WHITE:
            visit(network_id, (network_id,))
    return sorted(nodes, key=lambda node: node.network_id)


def plan_reconciliation(
    local_snapshot: Mapping[Any, Any],
    remote_snapshot: Mapping[Any, Any],
) -> dict[str, Any]:
    """Build a deterministic reconciliation plan from two snapshots (no I/O).

    Returns a dict with ``moves``, ``adds``, ``removes``, ``duplicates``,
    ``conflicts`` (all stably sorted) plus an ``echo`` of unrelated snapshot
    fields::

        {"local_extra": {...}, "remote_extra": {...}}

    ``removes`` lists units present only in the local snapshot (mirror of
    ``adds`` for the remote side); previously local-only units were silently
    ignored, now they are reported explicitly. The ``echo`` payload is a
    deep copy: mutating the plan echo never mutates the caller snapshot and
    vice versa.

    Raises:
        ValueError: "snapshots must contain at least one network" when
            neither snapshot carries any integer-keyed network, or
            "duplicate location (network {net}, unit {unit}) in {label}
            snapshot" when one snapshot assigns two serials to the same
            (network, unit) location.
    """
    local_networks, local_extra = _split_snapshot(local_snapshot, "local")
    remote_networks, remote_extra = _split_snapshot(remote_snapshot, "remote")
    if not local_networks and not remote_networks:
        raise ValueError("snapshots must contain at least one network")

    local_by_serial: dict[str, list[tuple[int, int]]] = {}
    for network_id in sorted(local_networks):
        for unit_address, serial in local_networks[network_id]:
            local_by_serial.setdefault(serial, []).append((network_id, unit_address))
    remote_by_serial: dict[str, list[tuple[int, int]]] = {}
    for network_id in sorted(remote_networks):
        for unit_address, serial in remote_networks[network_id]:
            remote_by_serial.setdefault(serial, []).append((network_id, unit_address))

    local_by_location: dict[tuple[int, int], str] = {}
    for network_id, entries in local_networks.items():
        for unit_address, serial in entries:
            location = (network_id, unit_address)
            if location in local_by_location and local_by_location[location] != serial:
                raise ValueError(
                    f"duplicate location (network {network_id}, unit {unit_address}) in local snapshot"
                )
            local_by_location[location] = serial
    remote_by_location: dict[tuple[int, int], str] = {}
    for network_id, entries in remote_networks.items():
        for unit_address, serial in entries:
            location = (network_id, unit_address)
            if location in remote_by_location and remote_by_location[location] != serial:
                raise ValueError(
                    f"duplicate location (network {network_id}, unit {unit_address}) in remote snapshot"
                )
            remote_by_location[location] = serial

    moves: list[dict[str, Any]] = []
    adds: list[dict[str, Any]] = []
    removes: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []

    for serial in sorted(set(local_by_serial) | set(remote_by_serial)):
        local_locations = sorted(set(local_by_serial.get(serial, [])))
        remote_locations = sorted(set(remote_by_serial.get(serial, [])))
        distinct = sorted(set(local_locations) | set(remote_locations))
        if len(distinct) > 1:
            if len(local_locations) == 1 and len(remote_locations) == 1 and local_locations != remote_locations:
                moves.append({
                    "serial": serial,
                    "from": [local_locations[0][0], local_locations[0][1]],
                    "to": [remote_locations[0][0], remote_locations[0][1]],
                })
            else:
                duplicates.append({
                    "serial": serial,
                    "locations": [[network_id, unit_address] for network_id, unit_address in distinct],
                })
        elif len(remote_locations) == 1 and not local_locations:
            network_id, unit_address = remote_locations[0]
            adds.append({"serial": serial, "network_id": network_id, "unit_address": unit_address})
        elif len(local_locations) == 1 and not remote_locations:
            network_id, unit_address = local_locations[0]
            removes.append({"serial": serial, "network_id": network_id, "unit_address": unit_address})

    conflicts: list[dict[str, Any]] = []
    for network_id, unit_address in sorted(set(local_by_location) & set(remote_by_location)):
        local_serial = local_by_location[(network_id, unit_address)]
        remote_serial = remote_by_location[(network_id, unit_address)]
        if local_serial != remote_serial:
            conflicts.append({
                "network_id": network_id,
                "unit_address": unit_address,
                "local_serial": local_serial,
                "remote_serial": remote_serial,
            })

    moves.sort(key=lambda item: item["serial"])
    adds.sort(key=lambda item: (item["serial"], item["network_id"], item["unit_address"]))
    removes.sort(key=lambda item: (item["serial"], item["network_id"], item["unit_address"]))
    duplicates.sort(key=lambda item: item["serial"])
    conflicts.sort(key=lambda item: (item["network_id"], item["unit_address"]))

    return {
        "moves": moves,
        "adds": adds,
        "removes": removes,
        "duplicates": duplicates,
        "conflicts": conflicts,
        "echo": {"local_extra": copy.deepcopy(local_extra), "remote_extra": copy.deepcopy(remote_extra)},
    }
