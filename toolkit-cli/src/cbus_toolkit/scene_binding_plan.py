"""Scene-binding planner spec (issue #11 P-D, bead cbus-8w7).

Spec-first offline scaffold only. Pure scene→control binding allocator
over caller-supplied control sets with exclusive binding (one control
drives at most one scene): first request wins, later contests and
unbound scenes escalate. No bindings written, no invocations, no bus
calls, no endpoints, no credentials, no vendor data invented or read.

Honesty boundary: allocation arithmetic is structural. Binding side
effects, scene invocation, learning, and physical behavior require
device acceptance and remain open; every behavioral slot starts
``unassessed``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

UNASSESSED = "unassessed"


@dataclass(frozen=True)
class BindingPlan:
    bindings: tuple[tuple[str, str], ...]
    escalated: tuple[str, ...]
    behavioral_comparison: str = UNASSESSED
    echo: dict[str, Any] = field(default_factory=dict)


def plan_bindings(
    requests: Any,
    controls: Any,
    extra: dict[str, Any] | None = None,
) -> BindingPlan:
    """Allocate controls to scenes exclusively (no side effects).

    ``requests``: sequence of ``{"scene": str, "control": str}`` dicts
    in priority order. ``controls``: caller-supplied collection of
    available control refs. Unknown controls, empty names, and duplicate
    scene names raise. A control already taken escalates the later
    scene name. Returns bindings sorted by scene plus escalated scene
    names in request order.
    """
    if isinstance(requests, (str, bytes)) or not hasattr(requests, "__iter__"):
        raise TypeError("requests must be a sequence of dicts")
    if isinstance(controls, (str, bytes)) or not hasattr(controls, "__iter__"):
        raise TypeError("controls must be a collection of strs")
    pool: set[str] = set()
    for pos, ctrl in enumerate(controls):
        if not isinstance(ctrl, str) or not ctrl:
            raise ValueError(f"controls[{pos}] must be a non-empty str")
        pool.add(ctrl)
    seen_scenes: set[str] = set()
    taken: dict[str, str] = {}
    bindings: dict[str, str] = {}
    escalated: list[str] = []
    for pos, item in enumerate(requests):
        if not isinstance(item, dict):
            raise TypeError(f"request {pos} must be dict")
        try:
            scene, ctrl = item["scene"], item["control"]
        except KeyError as exc:
            raise ValueError(f"request {pos} missing {exc}") from exc
        if not isinstance(scene, str) or not scene:
            raise ValueError(f"request {pos} scene must be non-empty str")
        if not isinstance(ctrl, str) or not ctrl:
            raise ValueError(f"request {pos} control must be non-empty str")
        if scene in seen_scenes:
            raise ValueError(f"duplicate scene: {scene!r}")
        seen_scenes.add(scene)
        if ctrl not in pool:
            raise ValueError(f"request {pos} unknown control: {ctrl!r}")
        if ctrl in taken:
            escalated.append(scene)
        else:
            taken[ctrl] = scene
            bindings[scene] = ctrl
    return BindingPlan(
        bindings=tuple(sorted(bindings.items())),
        escalated=tuple(escalated),
        echo=copy.deepcopy(dict(extra) if extra is not None else {}),
    )
