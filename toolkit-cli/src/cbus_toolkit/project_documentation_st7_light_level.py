"""Fresh TST7SENLL block state and its effective group consumers.

The derived class creates zero InputKeys: its virtual-key limit of -1 means
use MaximumKeyCount, which is zero. Inherited Neo/SENPILL template callbacks
therefore cannot replace a stored zero timer with 300 seconds. InputBlock4's
constructor minimum and both timer attribute callbacks instead enforce ten
seconds. The effective light-level dependency methods do not visit keys or
scenes, even though the inherited agent loads the stored scene collection.
"""
from __future__ import annotations

from .project_documentation_devices import _required_array
from .project_documentation_usage import Usage


def st7_light_level_timer(unit, selected: int) -> int:
    """Project the consumed timer from eight explicitly stored block values."""
    if type(selected) is not int or not 0 <= selected < 8:
        raise ValueError("BroadcastBlock (requires an existing loaded block)")
    high = _required_array(unit, "TimerHighByte", 8)
    low = _required_array(unit, "TimerLowByte", 8)
    stored = high[selected] * 256 + low[selected]
    return max(10, stored) if selected == 4 else stored


def st7_light_level_group_usage(unit, application: int, group: int, kind: str) -> Usage:
    """Preserve the derived VMT's ordered object-identity comparisons."""
    if kind not in {"input", "output", "other"}:
        raise ValueError("Group usage kind must be input, output or other")
    if kind == "output":
        return Usage()
    apps = _required_array(unit, "Application", 2)
    groups = _required_array(unit, "GroupAddress", 8)
    secondary = _required_array(unit, "SecondApplicationBlocks", 1)[0]

    def block(index: int):
        if not 0 <= index < 8:
            raise ValueError("light-level maintenance/broadcast block is outside the eight loaded blocks")
        return apps[int(bool(secondary & (1 << index)))], groups[index]

    if kind == "input":
        selected = _required_array(unit, "PECFunctionBlock", 1)[0]
        candidates = ((block(selected), "Level Group"), (block(2), "On/Off Group"))
    else:
        selected = _required_array(unit, "BroadcastBlock", 1)[0]
        enable = _required_array(unit, "PECEnablerGroup", 1)[0]
        candidates = ((block(selected), "Light Level Broadcast Group"),
                      ((apps[0], enable), "Enable Group"))
    return Usage("<br/>".join(label for identity, label in candidates
                              if identity == (application, group)))
