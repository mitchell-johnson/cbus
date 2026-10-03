"""Bounded Neo documentor projections from complete, freshly loaded PP snapshots.

The renderer preserves original table ordering and scene-ramp indexing. It does
not infer missing PP fields, labels or retained in-memory key history. Scene
tables use the existing canonical fixed/compact decoder; scene modification and
join modes remain outside this projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .device_scenes import SceneEntry, _decode
from .macros import MICRO_FUNCTION_LABELS, STAGES
from .project_documentation_devices import (
    KEY_RAMP_DESCRIPTIONS, KEY_TIMING_DESCRIPTIONS, _KEY_TIMER_EXPIRY,
    _classic_preset_cell, _group_link, _required_array, classic_key_macro,
)

if TYPE_CHECKING:
    from .project_documentation import Network, Unit, _Writer

JOIN_PARAMETERS = ("JoinPrimaryApplication", "DualJoinPrimaryApplication",
                   "JoinSecondaryApplication", "DualJoinSecondaryApplication")


@dataclass(frozen=True)
class NeoProfile:
    physical_key_count: int
    is_pro: bool
    infrared_virtual_keys: bool
    key_mask: bool = False
    key_mask_default: int = 1
    bistable: bool = False
    other_dependency_pro: bool | None = None
    join_supported: bool | None = None


@dataclass(frozen=True)
class NeoBlock:
    application: int
    group: int
    stored1: int
    stored2: int
    timer: int
    expiry: int


@dataclass(frozen=True)
class NeoKey:
    mask: int
    commands: tuple[int, ...]
    application: int
    macro_type: int
    macro_label: str
    scene_enabled: bool
    scene_index: int
    scene_ramp: int
    scene_trigger: int | None
    prefix: str


@dataclass(frozen=True)
class NeoData:
    applications: tuple[int, int]
    is_pro: bool
    physical_key_count: int
    timings: tuple[str, str, str, str]
    blocks: tuple[NeoBlock, ...]
    keys: tuple[NeoKey, ...]
    scenes: tuple[tuple[SceneEntry, ...], ...]
    trigger_group: int
    joins: tuple[tuple[int, int], ...]
    bistable_switches: tuple[bool, ...] | None = None


def neo_profile(unit: Unit) -> NeoProfile:
    """Admit explicit class/version combinations backed by the source receipt."""
    from .project_documentation_neo_profiles import profile_facts
    facts = profile_facts(unit)
    return NeoProfile(facts.physical_key_count, facts.is_pro, facts.infrared_virtual_keys,
                      facts.key_mask_default is not None, facts.key_mask_default or 1,
                      facts.bistable, facts.other_dependency_pro,
                      facts.join_supported(unit.firmware))


def _key_application(applications: tuple[int, int], mask: int, secondary: int, key: int) -> int:
    allocated = [block for block in range(8) if mask & (1 << block)]
    if not allocated:
        return applications[0]
    # Mixed keys prefer their own linear block, then the first allocated block.
    # This is a different lookup from GetPrimaryBlock's first-reference result.
    selected = key if key in allocated else allocated[0]
    return applications[int(bool(secondary & (1 << selected)))]


def neo_data(unit: Unit, profile: NeoProfile | None = None, *,
             macro_resolver: Callable[[tuple[int, ...], int, int | None, int | None], tuple[int, str]] | None = None) -> NeoData:
    """Decode eight keys/blocks and eight canonical scene slots without defaults.

    A profile override is for separately source-pinned derived documentors,
    such as DLT. It must establish the same PP loader and scene-table shape.
    """
    profile = neo_profile(unit) if profile is None else profile
    resolve_macro = classic_key_macro if macro_resolver is None else macro_resolver
    if not 0 <= profile.physical_key_count <= 8:
        raise ValueError("unsupported Neo physical key count")
    applications_raw = _required_array(unit, "Application", 2 if profile.is_pro else 1)
    applications = (applications_raw[0], applications_raw[1] if profile.is_pro else 255)
    debounce = _required_array(unit, "DebounceTime", 1, 63)[0]
    long_press = _required_array(unit, "LongPressTime", 1, 63)[0]
    ramps = _required_array(unit, "RampRate", 2)
    timings = (KEY_TIMING_DESCRIPTIONS[debounce], KEY_TIMING_DESCRIPTIONS[long_press],
               *(KEY_RAMP_DESCRIPTIONS[value if value <= 15 else 1 if value == 255 else 15] for value in ramps))
    groups = _required_array(unit, "GroupAddress", 8)
    masks = _required_array(unit, "BlockAllocation", 8)
    stored1 = _required_array(unit, "LightLevelStore1", 8)
    stored2 = _required_array(unit, "LightLevelStore2", 8)
    high, low = (_required_array(unit, name, 8) for name in ("TimerHighByte", "TimerLowByte"))
    expiry = _required_array(unit, "TimerExpiryCommand", 8, 15)
    raw_commands = tuple(zip(*(_required_array(unit, name, 8, 15) for name in STAGES)))
    secondary = _required_array(unit, "SecondApplicationBlocks", 1)[0] if profile.is_pro else 0
    join_values = tuple(_required_array(unit, name, 1)[0] for name in JOIN_PARAMETERS) if profile.is_pro else ()
    if any(group != 255 for group in join_values):
        raise ValueError("Neo join-mode model state is unrecovered")
    joins = ((255, 255), (255, 255)) if profile.is_pro else ()
    connected = 255
    if profile.key_mask:
        mask = _required_array(unit, "KeyMask", 1)[0]
        # KEYEx replaces a mask without bit zero with its exact type default.
        connected = (mask if mask & 1 else profile.key_mask_default) & 15
    bistable = None
    if profile.bistable:
        switches = _required_array(unit, "BistableSwitchBlock", 1)[0]
        bistable = tuple(bool(switches & (1 << key)) for key in range(profile.physical_key_count))
    scene_flags = _required_array(unit, "SceneKeySelector", 8, 1)
    scene_numbers = _required_array(unit, "IndicatorBlockAssignment", 8, 7)
    trigger_group = _required_array(unit, "ControlAppGroupAddress", 1)[0]
    table = tuple(_required_array(unit, "SceneTable", 80))
    pointers = tuple(_required_array(unit, "SceneTablePointer", 8))
    if len(unit.array("SceneTable")) != 80 or len(unit.array("SceneTablePointer")) != 8:
        raise ValueError("SceneTable/SceneTablePointer require exact canonical array lengths 80/8")
    scenes = _decode(table, pointers)
    timers = [h * 256 + l for h, l in zip(high, low)]
    keys = []
    for index, commands in enumerate(raw_commands):
        mask = masks[index]
        application = _key_application(applications, mask, secondary, index)
        primary = next((block for block in range(8) if mask & (1 << block)), None)
        if scene_flags[index]:
            if commands[0] != 14:
                raise ValueError("Neo Scene Modify key model state is unrecovered")
            if (mask != 1 << index or groups[index] != 255 or secondary & (1 << index)
                    or any(other_mask & (1 << index) for other_index, other_mask in enumerate(masks)
                           if other_index != index)):
                raise ValueError("Neo scene key requires an unshared linear primary unused-group block")
            kind, label = 24, "Scene"
            scene_index, scene_ramp = scene_numbers[index], commands[1]
            scene_trigger = commands[2] * 16 + commands[3]
            # AssignTemplate(Scene) uses the registered all-idle microgroup.
            actual_commands = (0, 0, 0, 0)
        else:
            kind, label = resolve_macro(commands, application,
                                            stored1[primary] if primary is not None else None,
                                            stored2[primary] if primary is not None else None)
            # The original template AfterChange runs before the macro lock
            # check, setting a zero primary timer to five minutes for Timer.
            if kind == 6 and primary is not None and timers[primary] == 0:
                timers[primary] = 300
            # Fresh ordinary keys are explicitly assigned Scene1; their new
            # extension's ramp stays Instant and its trigger level stays nil.
            scene_index, scene_ramp, scene_trigger = 0, 0, None
            actual_commands = commands
        if index < profile.physical_key_count:
            prefix = "" if connected & (1 << index) else "Unconnected Key "
        else:
            prefix = "IR Key " if profile.infrared_virtual_keys else "Virtual Key "
        keys.append(NeoKey(mask, actual_commands, application, kind, label, bool(scene_flags[index]),
                           scene_index, scene_ramp, scene_trigger, prefix))
    blocks = tuple(NeoBlock(applications[int(bool(secondary & (1 << index)))], group,
                            stored1[index], stored2[index], timers[index],
                            expiry[index] if expiry[index] in _KEY_TIMER_EXPIRY else 15)
                   for index, group in enumerate(groups))
    return NeoData(applications, profile.is_pro, profile.physical_key_count, timings, blocks,
                   tuple(keys), scenes, trigger_group, joins, bistable)


def _controls(network: Network, data: NeoData, key: NeoKey) -> str:
    if key.macro_type == 16:
        return "&nbsp;"
    if key.scene_enabled:
        return ('<table border="1"><tr><th>Scene</th><th>Ramp Rate</th></tr><tr>'
                f'<td>Scene {key.scene_index + 1}</td><td>{KEY_RAMP_DESCRIPTIONS[key.scene_ramp]}</td></tr></table>')
    selected = [block for index, block in enumerate(data.blocks)
                if key.mask & (1 << index) and block.group != 255]
    if not selected:
        return "&nbsp;"
    result = '<table border="1"><tr><th>Group</th>'
    if 12 in key.commands:
        result += "<th>Preset 1</th>"
    if 6 in key.commands:
        result += "<th>Preset 2</th>"
    if 7 in key.commands:
        result += "<th>Timer</th><th>Expiry</th>"
    result += "</tr>"
    for selected_block in selected:
        # Group identity includes the application. Identical numeric addresses
        # in the two applications are distinct native group objects.
        block = next(block for block in data.blocks if (block.application, block.group) ==
                     (selected_block.application, selected_block.group))
        result += f"<tr><td>{_group_link(network, block.application, block.group)}</td>"
        if 12 in key.commands:
            result += _classic_preset_cell(network, block.application, block.group, block.stored1)
        if 6 in key.commands:
            result += _classic_preset_cell(network, block.application, block.group, block.stored2)
        if 7 in key.commands:
            hours, remaining = divmod(block.timer, 3600)
            minutes, seconds = divmod(remaining, 60)
            result += f"<td>{hours}h{minutes}m{seconds}s</td><td>{MICRO_FUNCTION_LABELS[block.expiry]}</td>"
        result += "</tr>"
    return result + "</table>"


def _trigger_link(network: Network, group_address: int, selector: int) -> str:
    app = network.application(202)
    group = app.group(group_address) if app is not None else None
    level = next((level for level in group.levels if level.address == selector), None) if group else None
    if level is None:
        raise ValueError(f"unresolved Application 202 Group {group_address} Level {selector}")
    return f'<a href="#{network.address}_202_{group_address}_{level.address}">{level.name}</a>'


def neo_body_lines(network: Network, data: NeoData, *, include_scenes: bool = True) -> list[str]:
    """Build shared key tables and the appendix selected by the documentor.

    Classic documentors of Neo-derived models request only the inherited tables.
    Their class ancestry alone does not select the Neo scene appendix.
    """
    from .project_documentation import format_html_string
    lines = ['<table border="1">']
    lines += [f"<tr><th>{label}</th><td>{value}</td></tr>"
              for label, value in zip(("Debounce", "Long Press", "Ramp 1", "Ramp 2"), data.timings)]
    lines += ["</table>", "<br/>", '<table border="1">',
              "<tr><th>Key</th>" + ("<th>Bistable</th>" if data.bistable_switches is not None else "")
              + "<th>Macro Function</th><th>Micro Functions</th><th>Controls</th></tr>"]
    for index, key in enumerate(data.keys):
        micro = "&nbsp;"
        if key.macro_type == 26:
            micro = ('<table border="1"><tr><th>SP</th><th>SR</th><th>LP</th><th>LR</th></tr><tr>'
                     + "".join(f"<td>{MICRO_FUNCTION_LABELS[command]}</td>" for command in key.commands)
                     + "</tr></table>")
        bistable_cell = ""
        if data.bistable_switches is not None:
            value = ("Yes" if data.bistable_switches[index] else "No") if index < data.physical_key_count else "&nbsp;"
            bistable_cell = f"<td>{value}</td>"
        lines.append(f"<tr><td>{key.prefix}{index + 1}</td>{bistable_cell}<td>{format_html_string(key.macro_label)}</td>"
                     f"<td>{micro}</td><td>{_controls(network, data, key)}</td></tr>")
    lines.append("</table>")
    if not include_scenes or not any(data.scenes):
        return lines
    lines += ["<br />", "Scenes<br />", '<table border="1">',
              "<tr><th>Scene</th><th>Triggers</th><th>Groups</th><th>Level</th></tr>"]
    for index, scene in enumerate(data.scenes):
        if not scene:
            continue
        triggers = [key for key in data.keys if key.scene_index == index and key.scene_trigger is not None]
        if triggers:
            trigger_cell = '<table border="1"><tr><th>Action Selector</th><th>Ramp Rate</th></tr>'
            for key in triggers:
                # Original 0xca7e24 indexes InputKeys by scene, not trigger key.
                trigger_cell += f"<tr><td>{_trigger_link(network, data.trigger_group, key.scene_trigger)}</td>"
                trigger_cell += f"<td>{KEY_RAMP_DESCRIPTIONS[data.keys[index].scene_ramp]}</td></tr>"
            trigger_cell += "</table>"
        else:
            trigger_cell = "&nbsp;"
        groups = "<br />".join(_group_link(network, data.applications[0], command.group) for command in scene)
        levels = "<br />".join(f"{(command.level + 2) * 100 // 255}%" for command in scene)
        lines.append(f"<tr><td>{index + 1}</td><td>{trigger_cell}</td><td>{groups}</td><td>{levels}</td></tr>")
    lines.append("</table>")
    return lines


def render_neo_body(out: _Writer, network: Network, data: NeoData) -> None:
    for line in neo_body_lines(network, data):
        out.add(line)


def document_neo(out: _Writer, network: Network, unit: Unit, profile: NeoProfile | None = None) -> str:
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        data = neo_data(unit, profile)
        lines = neo_body_lines(network, data)
    except ValueError as exc:
        out.mark(network, unit, f"Neo key controls/scenes: {exc}")
        return "partial"
    for line in lines:
        out.add(line)
    return "recovered"


DOCUMENTORS = {"NeoInput": document_neo, "NeoProInput": document_neo}
