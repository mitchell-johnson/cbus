"""CGL exchange differential spec (issue #11 box 7, bead cbus-9me).

Spec-first offline scaffold only. Pure manifest-diff planner over
caller-supplied CGL exchange manifests; no file I/O, no C-Gate calls,
no endpoints, no credentials, no vendor payloads invented or read.

Honesty boundary: manifest comparison is structural (unit identity,
route entries, archive shape tags). It establishes no vendor
backup/restore equivalence, no multi-bridge route liveness, and no
print/image-export fidelity. Every device/behavior comparison slot
starts ``unassessed``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"


@dataclass(frozen=True)
class CglDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]
    route_changes: tuple[str, ...]
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def _manifest_units(manifest: Any, label: str) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise TypeError(f"{label} manifest must be dict")
    units = manifest.get("units", {})
    if not isinstance(units, dict):
        raise ValueError(f"{label} manifest 'units' must be a dict")
    for key in units:
        if not isinstance(key, str) or not key:
            raise ValueError(f"{label} unit id must be a non-empty str")
    return units


def _manifest_routes(manifest: Any, label: str) -> dict[str, Any]:
    routes = manifest.get("routes", {})
    if not isinstance(routes, dict):
        raise ValueError(f"{label} manifest 'routes' must be a dict")
    for key, val in routes.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{label} route id must be a non-empty str")
        if not isinstance(val, str):
            raise ValueError(f"{label} route target must be str")
    return routes


def diff_manifests(
    before: Any, after: Any, extra: dict[str, Any] | None = None
) -> CglDiff:
    """Diff two CGL exchange manifests structurally.

    Manifest shape: ``{"units": {id: attrs}, "routes": {id: target}}``.
    Attribute values compare by ``!=``; attrs dicts are caller-opaque.
    Returns sorted added/removed/changed unit ids and human-readable
    route-change strings (``"route <id>: <old> -> <new>"``,
    ``"route <id> added/removed"``). ``extra`` echoes by deep copy.
    """
    b_units = _manifest_units(before, "before")
    a_units = _manifest_units(after, "after")
    b_routes = _manifest_routes(before, "before")
    a_routes = _manifest_routes(after, "after")
    added = sorted(k for k in a_units if k not in b_units)
    removed = sorted(k for k in b_units if k not in a_units)
    changed = sorted(
        k for k in a_units if k in b_units and a_units[k] != b_units[k]
    )
    route_changes: list[str] = []
    for rid in sorted(set(b_routes) | set(a_routes)):
        if rid not in b_routes:
            route_changes.append(f"route {rid} added")
        elif rid not in a_routes:
            route_changes.append(f"route {rid} removed")
        elif b_routes[rid] != a_routes[rid]:
            route_changes.append(
                f"route {rid}: {b_routes[rid]} -> {a_routes[rid]}"
            )
    return CglDiff(
        added=tuple(added),
        removed=tuple(removed),
        changed=tuple(changed),
        route_changes=tuple(route_changes),
        echo=copy.deepcopy(dict(extra) if extra is not None else {}),
    )
