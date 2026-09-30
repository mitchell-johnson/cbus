"""Bounded PIR documentor bodies and dependencies from explicit saved PP data.

Old PIR and ST7 PIR have four keys and four blocks. Their documentors both use
ClassicKeyInput action reporting, even though ST7 inherits a NeoPro unit model.
Encoded scene keys and retained GUI transitions are outside this projection.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .project_documentation_devices import (
    ClassicKeyData, _group_link, _required_array, classic_key_data, classic_key_lines,
    classic_key_macro,
)
from .project_documentation_usage import Usage
from .project_documentation_outputs import _registration

if TYPE_CHECKING:
    from .project_documentation import Network, Unit, _Writer

PIR_TYPES = ("SENPIRSS", "SENPIROA", "SENPIRIA", "SENPIRIB")
PIR_MACROS = {(7, 0, 0, 0): (31, "Day Move"), (13, 7, 7, 0): (32, "Night Move"),
              (13, 7, 0, 7): (33, "Any Move"), (13, 15, 7, 15): (34, "Sunset")}
PIR_LABELS = ("PIR Enable/Disable Group: ", "PIR Disable Group: ", "PIR Enable Group: ")


def pir_profile(unit: Unit) -> bool:
    """Return ST7 membership for the pinned native factory range, or refuse."""
    kind = unit.unit_type.upper()
    row = _registration(unit)
    if kind in PIR_TYPES and row is not None:
        if row[3:5] == ("TSENPIROA" if kind == "SENPIROA" else "TSENPIRSS",
                        "TCBusPirSensorInputCGateAgent"):
            return False
        if row[3:5] == ("TST7SENPIROA" if kind == "SENPIROA" else "TST7SENPIRSS",
                        "TCBusST7PIRSensorCGateAgent"):
            return True
    raise ValueError("unrecovered PIR class/firmware (surface multisensor is excluded)")


def pir_macro(commands: tuple[int, ...], application: int,
              stored1: int | None, stored2: int | None) -> tuple[int, str]:
    special = PIR_MACROS.get(tuple(commands))
    if special is not None:
        return special if application != 255 else (26, "<Custom>")
    return classic_key_macro(commands, application, stored1, stored2)


@dataclass(frozen=True)
class PIRData:
    st7: bool
    classic: ClassicKeyData
    block_applications: tuple[int, ...]
    macros: tuple[tuple[int, str], ...]


def pir_data(unit: Unit) -> PIRData:
    st7 = pir_profile(unit)
    apps = _required_array(unit, "Application", 2 if st7 else 1)
    if st7 and any(_required_array(unit, "SceneKeySelector", 4, 1)):
        raise ValueError("PIR encoded scene keys (ordinary keys required)")
    secondary = _required_array(unit, "SecondApplicationBlocks", 1)[0] if st7 else 0
    block_apps = tuple(apps[1] if secondary & (1 << block) else apps[0] for block in range(4))
    # Decode raw timers first; the actual application's SENPIR macro drives the
    # template-change default, after mixed block applications have been resolved.
    data = classic_key_data(unit, key_count=4, macro_resolver=lambda *_: (26, "<Custom>"))
    if any(mask > 15 for mask in data.masks):
        raise ValueError("PIR BlockAllocation (requires four-block masks)")
    macros, timers = [], data.timers.copy()
    for index, (mask, commands) in enumerate(zip(data.masks, data.commands)):
        blocks = [block for block in range(4) if mask & (1 << block)]
        primary = blocks[0] if blocks else None
        # The mixed-app key getter prefers its same-index allocated block.
        app = block_apps[index if index in blocks else blocks[0]] if blocks else apps[0]
        macro = pir_macro(commands, app, data.stored1[primary] if primary is not None else None,
                          data.stored2[primary] if primary is not None else None)
        macros.append(macro)
        if primary is not None and not timers[primary] and (macro[0] == 6 or 29 <= macro[0] <= 35):
            timers[primary] = 300
    return PIRData(st7, replace(data, timers=timers), block_apps, tuple(macros))


def pir_enable_label(unit: Unit) -> tuple[int, int, str]:
    st7 = pir_profile(unit)
    application = _required_array(unit, "Application", 1)[0]
    group = _required_array(unit, "PIREnablerGroup" if st7 else "EnableGroupAddress", 1)[0]
    if group == 255:
        return application, group, PIR_LABELS[0]
    logic = _required_array(unit, "PIREnablerGroupLogic" if st7 else "EnableGroupLogic", 1, 1 if st7 else 255)[0]
    off = bool(logic) if st7 else not bool(logic)
    return application, group, PIR_LABELS[1 if off else 2]


def document_pir(out: _Writer, network: Network, unit: Unit) -> str:
    from .project_documentation import document_base
    document_base(out, network, unit)
    status = "recovered"
    try:
        data = pir_data(unit)
        lines = classic_key_lines(network, data.classic, macros=data.macros,
                                  block_applications=data.block_applications)
    except ValueError as error:
        out.mark(network, unit, f"PIR key controls: {error}")
        status = "partial"
    else:
        for line in lines:
            out.add(line)
    try:
        application, group, label = pir_enable_label(unit)
        suffix = label + _group_link(network, application, group) + "<br />"
    except ValueError as error:
        out.mark(network, unit, f"PIR enable group: {error}")
        return "partial"
    out.add("<br />")
    out.add(suffix)
    return status


def pir_action_selector_usage(unit: Unit, application: int, group: int,
                              address: int, value: int) -> Usage:
    try:
        data = pir_data(unit)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    if application != data.classic.application:
        return Usage()
    descriptions = []
    for key, (mask, commands) in enumerate(zip(data.classic.masks, data.classic.commands), 1):
        for block in range(4):
            if not mask & (1 << block) or (data.block_applications[block], data.classic.groups[block]) != (application, group):
                continue
            if data.classic.stored1[block] != address:
                continue
            if 12 in commands or (7 in commands and data.classic.expiry[block] == 12):
                descriptions.append(f"Key {key}")
            if data.classic.stored2[block] == value and (6 in commands or (7 in commands and data.classic.expiry[block] == 6)):
                descriptions.append(f"Key {key}")
    return Usage("<br/>".join(descriptions))


def pir_group_usage(unit: Unit, application: int, group: int, kind: str) -> Usage:
    if kind not in {"input", "output", "other"}:
        raise ValueError("Group usage kind must be input, output or other")
    try:
        st7 = pir_profile(unit)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    if kind == "output":
        return Usage()
    if kind == "other":
        return _other_usage(unit, st7, application, group)
    try:
        data = pir_data(unit)
        active = _required_array(unit, "PECFunctionActive", 1, 1)[0] if st7 else 0
        maint = _required_array(unit, "PECFunctionBlock", 1)[0] if active else None
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    descriptions = []
    for block in range(4):
        if (data.block_applications[block], data.classic.groups[block]) != (application, group):
            continue
        labels = [f"Key {key + 1}" for key, (mask, macro) in enumerate(zip(data.classic.masks, data.macros))
                  if mask & (1 << block) and macro[0] != 16]
        if active and maint == block:
            labels.append("Light Level Maintenance")
        descriptions.extend(labels or ["Block (Unused)"])
    # ST7's override also enumerates every scene command. Only an explicit empty
    # native scene table is covered; preserve known block uses if it is absent.
    missing = []
    if st7 and application == data.classic.application:
        table = unit.array("SceneTable")
        if table is None or any(not 0 <= value <= 255 for value in table):
            missing.append("SceneTable (explicit empty scene graph required)")
        elif table and table[0] != 255:
            missing.append("PIR scene group dependencies")
    return Usage("<br/>".join(descriptions), "partial" if missing else "recovered", tuple(missing))


def _other_usage(unit: Unit, st7: bool, application: int, group: int) -> Usage:
    descriptions, missing = [], []
    try:
        apps = _required_array(unit, "Application", 2 if st7 else 1)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))

    def append(name, label):
        try:
            values = _required_array(unit, name, 1)
        except ValueError as error:
            missing.append(str(error))
        else:
            if values[0] == group:
                descriptions.append(label)

    if application == apps[0]:
        append("AreaGroupAddress", "Area Group")
    if not st7:
        if application == apps[0]:
            append("EnableGroupAddress", "PIR Enable Group")
    else:
        if application == 203 and group == 255:
            descriptions.append("Key Disable Group")  # Unsupported property loads unused Enable group.
        if application == apps[0]:
            append("CorridorLinkEnablerGroup", "Corridor Link Group")
        if application == 202:
            append("ControlAppGroupAddress", "Control App Group")
        if application == apps[0]:
            append("PECEnablerGroup", "Light Level Maintenance Enable")
            append("PIREnablerGroup", "Occupancy Enable")
            append("CorridorLinkEnablerGroup", "Corridor Link")
        try:
            selected = _required_array(unit, "BroadcastBlock", 1, 3)[0]
            if selected < 4:
                groups = _required_array(unit, "GroupAddress", 4)
                mask = _required_array(unit, "SecondApplicationBlocks", 1)[0]
                app = apps[1] if mask & (1 << selected) else apps[0]
                if (app, groups[selected]) == (application, group):
                    descriptions.append("Light Level Broadcast Group")
        except ValueError as error:
            missing.append(str(error))
    return Usage("<br/>".join(descriptions), "partial" if missing else "recovered", tuple(dict.fromkeys(missing)))
