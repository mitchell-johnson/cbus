"""Source-pinned Neo group dependencies and the inherited action-use chain.

The shared Neo decoder admits explicit complete fresh PP snapshots. These
strings are original method projections, not an original generated-page capture.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .project_documentation_neo import JOIN_PARAMETERS, NeoData, NeoProfile, neo_data, neo_profile
from .project_documentation_usage import Usage, _array

if TYPE_CHECKING:
    from .project_documentation import Unit

ACTION_SCENE_LABEL = "Triggers Scene "
NEO_GROUP_LABELS = ("Key %d", "Block (Unused)", "Scene %d", "Scene %d (Unused)")
OTHER_LABELS = ("Area Group", "Indicator Brightness Group", "Join Group", "DualJoinGroup",
                "Key Disable Group", "Corridor Link Group", "Control App Group")


def action_usage_from_data(data: NeoData, application: int, group: int,
                           address: int, value: int) -> Usage:
    """Run Classic -> Neo -> optional NeoPro in the original call order."""
    descriptions: list[str] = []

    def append_recalls() -> None:
        for index, key in enumerate(data.keys):
            for block_index, block in enumerate(data.blocks):
                if not key.mask & (1 << block_index):
                    continue
                if (block.application, block.group) != (application, group) or block.stored1 != address:
                    continue
                if 12 in key.commands or (7 in key.commands and block.expiry == 12):
                    descriptions.append(f"Key {index + 1}")
                # The original's stored-1 Address gate encloses the stored-2
                # Value branch. A key may therefore occur twice per block.
                if block.stored2 == value and (6 in key.commands or (7 in key.commands and block.expiry == 6)):
                    descriptions.append(f"Key {index + 1}")

    if application == data.applications[0]:
        append_recalls()
    if application == 202 and group == data.trigger_group:
        for key in data.keys:
            if key.scene_trigger == address:
                # UStrCat3 replaces the inherited result; later keys win.
                descriptions[:] = [ACTION_SCENE_LABEL + str(key.scene_index + 1)]
    if data.is_pro and application == data.applications[1]:
        append_recalls()
    return Usage("<br/>".join(descriptions))


def input_usage_from_data(data: NeoData, application: int, group: int, *, dlt: bool = False) -> Usage:
    """Describe the admitted disabled-join graph, block-major then scene-major.

    DLT has a separate input override: every retained scene is reported as used.
    Neo determines use from each key's scene object, including ordinary keys.
    """
    if any(value != 255 for _, value in data.joins):
        return Usage(status="unrecovered", missing=("Neo join-mode group dependencies",))
    descriptions: list[str] = []
    for block_index, block in enumerate(data.blocks):
        if (block.application, block.group) != (application, group):
            continue
        matches = [f"Key {index + 1}" for index, key in enumerate(data.keys)
                   if index < data.physical_key_count and key.macro_type != 16
                   and key.mask & (1 << block_index)]
        descriptions.extend(matches or ["Block (Unused)"])
    if application == data.applications[0]:
        for scene_index, scene in enumerate(data.scenes):
            used = dlt or any(key.scene_index == scene_index for key in data.keys)
            descriptions.extend(f"Scene {scene_index + 1}" + ("" if used else " (Unused)")
                                for command in scene if command.group == group)
    return Usage("<br/>".join(descriptions))


def neo_action_selector_usage(unit: Unit, application: int, group: int, address: int,
                              value: int, *, profile: NeoProfile | None = None) -> Usage:
    try:
        data = neo_data(unit, profile)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    return action_usage_from_data(data, application, group, address, value)


def neo_group_usage(unit: Unit, application: int, group: int, kind: str, *,
                    profile: NeoProfile | None = None, dlt: bool = False) -> Usage:
    if kind not in {"input", "output", "other"}:
        raise ValueError("Group usage kind must be input, output or other")
    try:
        profile = neo_profile(unit) if profile is None else profile
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    if kind == "output":
        return Usage()  # All admitted classes inherit the empty base method.
    if kind == "other":
        return _other_usage(unit, profile, application, group)
    try:
        data = neo_data(unit, profile)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    return input_usage_from_data(data, application, group, dlt=dlt)


def _other_usage(unit: Unit, profile: NeoProfile, application: int, group: int) -> Usage:
    descriptions: list[str] = []
    missing: list[str] = []
    apps = _array(unit, "Application", 2 if profile.is_pro else 1)

    def append(name: str, label: str) -> None:
        values = _array(unit, name, 1)
        if values is None:
            missing.append(name)
        elif values[0] == group:
            descriptions.append(label)

    if apps is None:
        missing.append("Application")
    elif application == apps[0]:
        append("AreaGroupAddress", "Area Group")
        brightness = unit.parameters.get("IndicatorBrightness")
        if brightness is None:
            missing.append("IndicatorBrightness")
        elif brightness:
            groups = _array(unit, "GroupAddress", 9)
            if groups is None:
                missing.append("GroupAddress")
            elif groups[8] == group:
                descriptions.append("Indicator Brightness Group")
    # Pro profiles with possible join support are admitted only with all four
    # join PP groups disabled. Keep an unknown dependency when Other is queried
    # independently of the body decoder and that boundary is not established.
    possible_join = profile.is_pro and (profile.join_supported if profile.join_supported is not None
                                       else unit.unit_type.upper() not in {"KEYM8", "KEYE1"})
    if possible_join:
        for name in JOIN_PARAMETERS:
            values = _array(unit, name, 1)
            if values is None or values[0] != 255:
                missing.append(name + " (requires disabled join)")
        if application == 255 and group == 255:
            missing.append("unused join-group identity")
    other_pro = profile.is_pro if profile.other_dependency_pro is None else profile.other_dependency_pro
    if other_pro:
        if application == 203:
            append("KeyDisableGroup", "Key Disable Group")
        if apps is not None and application == apps[0]:
            # The native loader sets the group even with CorridorLink disabled.
            append("CorridorMasterGroup", "Corridor Link Group")
        if application == 202:
            append("ControlAppGroupAddress", "Control App Group")
    return Usage("<br/>".join(descriptions), "partial" if missing else "recovered", tuple(missing))
