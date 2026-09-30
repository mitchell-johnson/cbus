"""NeoProClassic key reports from explicit saved programming snapshots.

KEYC/CIR use the Classic documentor with an eight-key Neo-derived model. Scene
selector decoding beyond ordinary keys and retained GUI history are not admitted.
Unconsumed scene-table and trigger fields do not become inferred model facts.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .macros import STAGES
from .project_documentation_devices import (
    KEY_RAMP_DESCRIPTIONS, KEY_TIMING_DESCRIPTIONS, _KEY_TIMER_EXPIRY,
    _required_array, classic_key_macro,
)
from .project_documentation_neo import NeoBlock, NeoData, NeoKey, NeoProfile, _key_application, neo_body_lines
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


def neoclassic_data(unit: Unit) -> NeoData:
    """Project ordinary keys and blocks independently of scene-table loading.

    The original loads encoded scene selectors even though ScenesEnabled is
    always false. Require explicit ordinary selectors instead of treating that
    capability getter as proof that the saved scene programming is unused.
    """
    profile = neoclassic_profile(unit)
    if any(_required_array(unit, "SceneKeySelector", 8, 1)):
        raise ValueError("NeoProClassic encoded scene keys (ordinary keys required)")
    applications = tuple(_required_array(unit, "Application", 2))
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
    commands = tuple(zip(*(_required_array(unit, name, 8, 15) for name in STAGES)))
    secondary = _required_array(unit, "SecondApplicationBlocks", 1)[0]
    timers = [h * 256 + l for h, l in zip(high, low)]
    keys = []
    for index, microfunctions in enumerate(commands):
        mask = masks[index]
        application = _key_application(applications, mask, secondary, index)
        primary = next((block for block in range(8) if mask & (1 << block)), None)
        # NEOPRO_CLASSIC adds only Scene templates to KEY's primary subset;
        # ordinary global matching cannot select those all-idle templates.
        # The secondary NEOPRO_S subset is identical to KEY.
        kind, label = classic_key_macro(microfunctions, application,
                                       stored1[primary] if primary is not None else None,
                                       stored2[primary] if primary is not None else None)
        if kind == 6 and primary is not None and timers[primary] == 0:
            timers[primary] = 300
        prefix = "" if index < profile.physical_key_count else (
            "IR Key " if profile.infrared_virtual_keys else "Virtual Key ")
        keys.append(NeoKey(mask, microfunctions, application, kind, label, False, 0, 0, None, prefix))
    blocks = tuple(NeoBlock(applications[int(bool(secondary & (1 << index)))], group,
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
