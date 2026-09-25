"""Project topology navigation spec (issue #11 box 7, bead cbus-9me).

Spec-first offline scaffold only. Pure neighbor listing and shortest-
path search over a caller-supplied adjacency map; no live discovery,
no bus calls, no endpoints, no credentials.

Honesty boundary: graph algorithms are structural. Live topology,
bridge liveness, and multi-bridge route behavior require network
acceptance and remain open; every behavioral slot starts
``unassessed``.
"""
from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"


@dataclass(frozen=True)
class PathResult:
    path: tuple[int, ...]
    found: bool
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def _graph(adjacency: Any) -> dict[int, list[int]]:
    if not isinstance(adjacency, dict) or not adjacency:
        raise ValueError("adjacency must be a non-empty dict")
    graph: dict[int, list[int]] = {}
    for net, nbrs in adjacency.items():
        if isinstance(net, bool) or not isinstance(net, int):
            raise ValueError("network ids must be ints")
        if isinstance(nbrs, (str, bytes)) or not hasattr(nbrs, "__iter__"):
            raise TypeError(f"neighbors of {net} must be a sequence")
        seen: list[int] = []
        for n in nbrs:
            if isinstance(n, bool) or not isinstance(n, int):
                raise ValueError(f"neighbor of {net} must be int")
            if n == net:
                raise ValueError(f"network {net} links to itself")
            if n not in seen:
                seen.append(n)
        graph[net] = sorted(seen)
    for net, nbrs in graph.items():
        for n in nbrs:
            if n not in graph:
                raise ValueError(f"network {net} links unknown {n}")
    return graph


def neighbors(
    adjacency: Any, network: Any, extra: dict[str, Any] | None = None
) -> tuple[int, ...]:
    """Return sorted neighbors of a network (caller-supplied graph)."""
    graph = _graph(adjacency)
    if isinstance(network, bool) or not isinstance(network, int):
        raise ValueError("network must be int")
    if network not in graph:
        raise ValueError(f"unknown network: {network}")
    _ = extra
    return tuple(graph[network])


def find_path(
    adjacency: Any,
    source: Any,
    destination: Any,
    extra: dict[str, Any] | None = None,
) -> PathResult:
    """Shortest path by BFS (deterministic: sorted neighbors).

    Returns found=False with empty path when disconnected. Same
    source/destination returns the single-node path. Unknown nodes
    raise ``ValueError``.
    """
    graph = _graph(adjacency)
    for label, node in (("source", source), ("destination", destination)):
        if isinstance(node, bool) or not isinstance(node, int):
            raise ValueError(f"{label} must be int")
        if node not in graph:
            raise ValueError(f"unknown {label}: {node}")
    if source == destination:
        return PathResult(
            path=(source,), found=True,
            echo=copy.deepcopy(dict(extra) if extra is not None else {}),
        )
    prev: dict[int, int | None] = {source: None}
    queue: deque[int] = deque([source])
    while queue:
        node = queue.popleft()
        for nbr in graph[node]:
            if nbr not in prev:
                prev[nbr] = node
                if nbr == destination:
                    queue.clear()
                    break
                queue.append(nbr)
    if destination not in prev:
        return PathResult(path=(), found=False,
                          echo=copy.deepcopy(dict(extra) if extra is not None else {}))
    legs: list[int] = [destination]
    while legs[-1] != source:
        parent = prev[legs[-1]]
        assert parent is not None
        legs.append(parent)
    return PathResult(
        path=tuple(reversed(legs)), found=True,
        echo=copy.deepcopy(dict(extra) if extra is not None else {}),
    )
