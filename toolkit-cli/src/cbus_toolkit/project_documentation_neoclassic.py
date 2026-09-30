"""NeoProClassic key reports from explicit saved programming snapshots.

KEYC/CIR use the Classic documentor with an eight-key Neo-derived model. Ordinary
keys and canonical scene/modify bindings are admitted; retained GUI history
requires separate projections.
Unconsumed scene-table and trigger fields do not become inferred model facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .macros import STAGES
from .project_documentation_devices import (
    KEY_RAMP_DESCRIPTIONS, KEY_TIMING_DESCRIPTIONS, _KEY_TIMER_EXPIRY,
    _required_array, classic_key_macro,
)
from .project_documentation_neo import NeoBlock, NeoData, NeoKey, NeoProfile, neo_body_lines
from .project_documentation_outputs import _registration

if TYPE_CHECKING:
    from .project_documentation import Network, Unit, _Writer

NEOCLASSIC_TYPES = {"KEYC1": (1, False), "KEYC2": (2, False), "KEYC4": (4, False),
                    "KEYCIR1": (0, True), "KEYCIR4": (4, True)}


def neoclassic_profile(unit: Unit) -> NeoProfile:
    typ = unit.unit_type.upper()
    row = _registration(unit)
    if (typ not in NEOCLASSIC_TYPES or row is None
            or row[3:5] != ("T" + typ, "TCBusNeoProInputCGateAgent")):
        raise ValueError("unrecovered NeoProClassic class/firmware")
    count, infrared = NEOCLASSIC_TYPES[typ]
    return NeoProfile(count, True, infrared)


@dataclass(frozen=True)
class NeoClassicProgramming:
    applications: tuple[int, int]
    block_applications: tuple[int, ...]
    groups: tuple[int, ...]
    masks: tuple[int, ...]
    commands: tuple[tuple[int, ...], ...]
    scene_keys: tuple[bool, ...]
    scene_key_templates: tuple[int, ...]
    scene_indexes: tuple[int, ...] | None
    scene_ramps: tuple[int, ...]
    scene_triggers: tuple[int | None, ...]


def neoclassic_programming(unit: Unit, *, include_scene_indexes: bool = True) -> NeoClassicProgramming:
    """Decode fields shared by body and dependency consumers, without timings.

    Scene24 template assignment refreshes block references before checking the
    macro lock. The admitted saved graph already has the resulting unshared,
    linear, primary unused-group block, so no relocation/history is inferred.
    """
    neoclassic_profile(unit)
    applications = tuple(_required_array(unit, "Application", 2))
    secondary = _required_array(unit, "SecondApplicationBlocks", 1)[0]
    groups = tuple(_required_array(unit, "GroupAddress", 8))
    masks = tuple(_required_array(unit, "BlockAllocation", 8))
    raw_commands = tuple(zip(*(_required_array(unit, name, 8, 15) for name in STAGES)))
    flags = _required_array(unit, "SceneKeySelector", 8, 1)
    # Only scene extension consumers read indicator slots, and ordinary key
    # slots are never consumed. Actions and empty/secondary input scene scans
    # can normalize the graph without projecting extension scene references.
    scene24 = [bool(flag and commands[0] == 14) for flag, commands in zip(flags, raw_commands)]
    scene_numbers = unit.array("IndicatorBlockAssignment") if include_scene_indexes and any(scene24) else None
    if include_scene_indexes and any(scene24) and (
            scene_numbers is None or any(index >= len(scene_numbers) or not 0 <= scene_numbers[index] <= 7
                                         for index, flag in enumerate(scene24) if flag)):
        raise ValueError("IndicatorBlockAssignment (requires explicit scene-key indexes 0..7)")
    commands, templates, indexes, ramps, triggers = [], [], [], [], []
    for index, microfunctions in enumerate(raw_commands):
        if flags[index]:
            if microfunctions[0] != 14:
                from .project_documentation_neoclassic_modify import scene_modify_projection
                projection = scene_modify_projection(index, microfunctions, masks=masks, groups=groups,
                                                      secondary=secondary)
                commands.append(projection.commands)
                templates.append(projection.macro_type)
                indexes.append(projection.scene_index)
                ramps.append(projection.scene_ramp)
                triggers.append(projection.scene_trigger)
                continue
            if (masks[index] != 1 << index or groups[index] != 255 or secondary & (1 << index)
                    or any(other_mask & (1 << index) for other_index, other_mask in enumerate(masks)
                           if other_index != index)):
                raise ValueError("NeoProClassic scene key requires an unshared linear primary unused-group block")
            commands.append((0, 0, 0, 0))
            templates.append(24)
            indexes.append(scene_numbers[index] if include_scene_indexes else 0)
            ramps.append(microfunctions[1])
            triggers.append(microfunctions[2] * 16 + microfunctions[3])
        else:
            commands.append(microfunctions)
            templates.append(0)
            # Fresh ordinary key extensions are assigned Scene 1, Instant,
            # and no trigger level. Indicator PP is not consumed for them.
            indexes.append(0)
            ramps.append(0)
            triggers.append(None)
    return NeoClassicProgramming(applications,
        tuple(applications[int(bool(secondary & (1 << block)))] for block in range(8)),
        groups, masks, tuple(commands), tuple(map(bool, flags)), tuple(templates),
        tuple(indexes) if include_scene_indexes else None, tuple(ramps), tuple(triggers))


def neoclassic_data(unit: Unit) -> NeoData:
    """Project report controls independently of scene-command table loading.

    The original loads encoded scene selectors even though ScenesEnabled is
    always false. Decode actual selectors and refuse unrecovered transitions
    instead of treating that capability as proof of unused scene programming.
    """
    profile = neoclassic_profile(unit)
    programming = neoclassic_programming(unit)
    applications = programming.applications
    debounce = _required_array(unit, "DebounceTime", 1, 63)[0]
    long_press = _required_array(unit, "LongPressTime", 1, 63)[0]
    ramps = _required_array(unit, "RampRate", 2)
    timings = (KEY_TIMING_DESCRIPTIONS[debounce], KEY_TIMING_DESCRIPTIONS[long_press],
               *(KEY_RAMP_DESCRIPTIONS[value if value <= 15 else 1 if value == 255 else 15] for value in ramps))
    groups, masks, commands = programming.groups, programming.masks, programming.commands
    stored1 = _required_array(unit, "LightLevelStore1", 8)
    stored2 = _required_array(unit, "LightLevelStore2", 8)
    high, low = (_required_array(unit, name, 8) for name in ("TimerHighByte", "TimerLowByte"))
    expiry = _required_array(unit, "TimerExpiryCommand", 8, 15)
    timers = [h * 256 + l for h, l in zip(high, low)]
    keys = []
    for index, microfunctions in enumerate(commands):
        mask = masks[index]
        # GetApplicationForKey prefers the allocated linear block, then its
        # first allocated block; the decoded block identities retain that rule.
        allocated = [block for block in range(8) if mask & (1 << block)]
        selected = index if index in allocated else allocated[0] if allocated else None
        application = programming.block_applications[selected] if selected is not None else applications[0]
        primary = next((block for block in range(8) if mask & (1 << block)), None)
        # NEOPRO_CLASSIC adds only Scene templates to KEY's primary subset;
        # ordinary global matching cannot select those all-idle templates.
        # The secondary NEOPRO_S subset is identical to KEY.
        if programming.scene_keys[index]:
            kind = programming.scene_key_templates[index]
            label = "Scene" if kind == 24 else "<Scene Modify>"
        else:
            kind, label = classic_key_macro(microfunctions, application,
                                           stored1[primary] if primary is not None else None,
                                           stored2[primary] if primary is not None else None)
        if kind == 6 and primary is not None and timers[primary] == 0:
            timers[primary] = 300
        prefix = "" if index < profile.physical_key_count else (
            "IR Key " if profile.infrared_virtual_keys else "Virtual Key ")
        keys.append(NeoKey(mask, microfunctions, application, kind, label, programming.scene_keys[index],
                           programming.scene_indexes[index], programming.scene_ramps[index],
                           programming.scene_triggers[index], prefix))
    blocks = tuple(NeoBlock(programming.block_applications[index], group,
                            stored1[index], stored2[index], timers[index],
                            expiry[index] if expiry[index] in _KEY_TIMER_EXPIRY else 15)
                   for index, group in enumerate(groups))
    # These fields are deliberately unconsumed here. Input dependencies supply
    # separately decoded scenes; Classic actions never query the trigger group.
    return NeoData(applications, True, profile.physical_key_count, timings, blocks,
                   tuple(keys), (), 255, ())


def document_neoclassic(out: _Writer, network: Network, unit: Unit) -> str:
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        lines = neo_body_lines(network, neoclassic_data(unit), include_scenes=False)
    except ValueError as error:
        out.mark(network, unit, f"NeoProClassic key controls: {error}")
        return "partial"
    for line in lines:
        out.add(line)
    return "recovered"
