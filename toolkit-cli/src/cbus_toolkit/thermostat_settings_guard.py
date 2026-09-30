"""Thermostat arithmetic guards and bounded original dialog rules.

The pure scalar-setting validators use a spec-first offline contract where
every range is a caller-supplied fact, never an embedded vendor limit.
No device I/O, no endpoints, no credentials, no vendor data invented
or read.

Honesty boundary: range conformance is structural arithmetic. Control
behavior, scheduling execution, and on-device effects require
per-profile physical acceptance and remain open; every behavioral slot
starts ``unassessed``. The separate ``recovered_dialog_rules`` and
``quick_zone_transition`` helpers reproduce the explicitly named Toolkit 1.18
methods pinned by research/thermostat_settings_form_static.py. They neither
execute a dialog nor establish the complete form lifecycle or edit admission.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Union

UNASSESSED = "unassessed"
Number = Union[int, float]


@dataclass(frozen=True)
class SettingCheck:
    ok: bool
    note: str
    behavioral_comparison: str = UNASSESSED


def _num(name: str, value: Any) -> Number:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    return value


def check_setting(name: str, value: Any, spec: Any) -> SettingCheck:
    """Check one scalar setting against a caller-supplied range spec.

    ``spec`` is a dict with numeric ``min``/``max`` and optional
    positive numeric ``step`` (value must satisfy
    ``(value - min) % step == 0`` within float tolerance 1e-9).
    ``name`` must be a non-empty str. Out-of-range returns ok=False
    (no exception); malformed spec/name/value raise.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty str")
    v = _num("value", value)
    if not isinstance(spec, dict):
        raise TypeError("spec must be dict")
    try:
        lo, hi = spec["min"], spec["max"]
    except KeyError as exc:
        raise ValueError(f"spec missing {exc}") from exc
    lo, hi = _num("spec.min", lo), _num("spec.max", hi)
    if lo > hi:
        raise ValueError("spec.min must be <= spec.max")
    step = spec.get("step", None)
    if step is not None:
        step = _num("spec.step", step)
        if step <= 0:
            raise ValueError("spec.step must be > 0")
    if not lo <= v <= hi:
        return SettingCheck(ok=False, note=f"{name} out of range")
    if step is not None:
        remainder = (float(v) - float(lo)) % float(step)
        if not (remainder <= 1e-9 or float(step) - remainder <= 1e-9):
            return SettingCheck(ok=False, note=f"{name} off step")
    return SettingCheck(ok=True, note=f"{name} within range")


def check_heat_cool(
    heat: Any, cool: Any, min_deadband: Any
) -> SettingCheck:
    """Check heat/cool setpoint separation (pure arithmetic).

    Requires numeric ``heat`` <= ``cool`` with
    ``cool - heat >= min_deadband`` (>= 0). Violations return ok=False.
    """
    h, c = _num("heat", heat), _num("cool", cool)
    d = _num("min_deadband", min_deadband)
    if d < 0:
        raise ValueError("min_deadband must be >= 0")
    if h > c:
        return SettingCheck(ok=False, note="heat above cool")
    if c - h < d:
        return SettingCheck(ok=False, note="deadband too small")
    return SettingCheck(ok=True, note="heat/cool separated")


# GetAllowedPlantModes, virtual plant indexes 0..11. Bit 0 is Off; the
# four editable mode checkboxes use bits 1..4. The original masks the enum
# with 0x7f and returns all modes for an unknown remaining index.
ALLOWED_PLANT_MODES = (1, 19, 21, 31, 19, 21, 31, 31, 3, 31, 31, 31)
ZONE_STATE_PARAMETERS = (
    "UIAllocatedZones", "InternalPlantZones", "MeasuredZones",
    "HeatingPlantInstalledZones", "CoolingPlantInstalledZones", "VentingPlantInstalledZones",
)
ZONE_TRANSITION_PARAMETERS = (
    "UIAllocatedZones", "InternalPlantZones", "MeasuredZones", "InstalledZones",
    "ControlledZones", "HeatingPlantInstalledZones", "CoolingPlantInstalledZones",
    "VentingPlantInstalledZones",
)


def _byte(values: Mapping[str, int], name: str) -> int:
    value = values[name]
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(name + " must be a one-byte integer")
    return value


def _zone_values(values: Mapping[str, int], family: str) -> tuple[int, ...]:
    if family not in ("programmable", "basic"):
        raise ValueError("Unknown thermostat family: " + str(family))
    names = ZONE_STATE_PARAMETERS + (("ScheduleControlledZones",) if family == "programmable" else ())
    # TZones models only the five zone bits, even when a raw PP byte has more.
    return tuple(_byte(values, name) & 31 for name in names)


def quick_zone_state(values: Mapping[str, int], family: str) -> dict[str, object]:
    """ZonePartiallyOn/ZoneFullyOn/CheckBoxStateForZone, without side effects.

    InstalledZones and zone-manager ControlledZones are deliberately absent
    from these formulas. State 2 is the original grayed checkbox, and still
    counts as selected for GetZoneNTicked and UpdateFlashZoneVariables.
    """
    used, full = 0, 31
    for mask in _zone_values(values, family):
        used |= mask
        full &= mask
    return {
        "used_zones": used,
        "fully_selected_zones": full,
        "checkbox_states": tuple(1 if full & (1 << zone) else 2 if used & (1 << zone) else 0
                                 for zone in range(5)),
    }


def recovered_dialog_rules(values: Mapping[str, int], family: str) -> dict[str, object]:
    """Read back the recovered rule subset for explicit model values.

    Zone results describe calls after quick-zone state has been recomputed.
    Plant action results are their individual OnUpdate results. They do not
    claim all parent visibility, event ordering or original form validation.
    Vent normalization is the isolated, unguarded EnableDisablePlantModes
    effect, returned separately; this helper never applies it to raw PP data.
    """
    from .thermostat_post_load import VIRTUAL_11_OUTPUTS, pp_name, virtual_plant_type

    zones = quick_zone_state(values, family)
    used = int(zones["used_zones"])
    master = _byte(values, "ControlledZones") > 0
    if _byte(values, "InternalPlantType") == 8:
        for output in VIRTUAL_11_OUTPUTS:
            _byte(values, pp_name(output))
    plant = virtual_plant_type(values)
    plant_index = plant & 127
    allowed = ALLOWED_PLANT_MODES[plant_index] if plant_index < len(ALLOWED_PLANT_MODES) else 31
    modes = _byte(values, "InternalPlantModes") & 31
    vent = _byte(values, "VentPlantType")
    heat = bool(allowed & (2 | 8))
    cool = bool(allowed & (4 | 8))
    normalized_vent = vent
    if master:
        # The source checks control Enabled, not Checked. Keep the original
        # order: heating fallback, cooling fallback, then neither available.
        if not heat and normalized_vent == 1:
            normalized_vent = 2
        if not cool and normalized_vent == 2:
            normalized_vent = 1
        if not heat and not cool:
            normalized_vent = 0
    enabled_zones = {"UIAllocatedZones": used, "MeasuredZones": used,
                     "InternalPlantZones": used if master else 0}
    for side in ("Heating", "Cooling", "Venting"):
        enabled_zones[side + "PlantInstalledZones"] = (
            used if master and _byte(values, side + "PlantType") != 0 else 0)
    return {
        "format": "cbus-thermostat-dialog-rule-subset-v1",
        "original_dialog_executed": False,
        "dialog_enable_rules_reproduced": False,
        "evidence_kind": "pinned-original-static-methods",
        "phase": "individual-methods-after-quick-zone-recompute",
        "master": master,
        "virtual_plant_type": plant,
        **zones,
        "zone_control_enabled_masks": enabled_zones,
        "basic_hidden_controls": ("gbPlantZones", "btnDamperGroups") if family == "basic" else (),
        "allowed_plant_modes": allowed,
        "plant_mode_checkbox_enabled_mask": allowed & 30 if master else 0,
        "vent_plant_type_enabled": master and bool(modes & 16),
        "unguarded_enable_modes_vent_result": normalized_vent,
        "fan_control_action_enabled": bool(modes & 16) and vent != 0,
        "fan_coil_action_enabled": plant == 11 and modes not in (0, 1),
        "evaporative_cooling_action_enabled": plant != 0 and any(
            _byte(values, name) in (2, 6, 10)
            for name in ("CoolingPlantType", "HeatingPlantType", "VentingPlantType", "HeatCoolPlantType")),
        "remaining": ("complete dialog event ordering", "remaining controls and parent visibility",
                      "control-to-raw-edit admission", "original dialog execution"),
    }


def quick_zone_transition(values: Mapping[str, int], family: str, zone: int, include: bool,
                          *, unswitched_removal_confirmed: bool = False) -> dict[str, int]:
    """Pure accepted IncludeZone/ExcludeZone checkbox transition.

    This is a separate GUI action, not a rule for editing InstalledZones alone.
    It refuses deselecting the last quick zone, and requires the caller's
    explicit answer for the original unswitched-zone removal prompt. It
    returns PP values without changing its input or doing any I/O. One call
    represents one action from a loaded snapshot, not a continuing GUI session.
    """
    if type(zone) is not int or not 0 <= zone <= 4:
        raise ValueError("zone must be 0 (unswitched) through 4")
    if type(include) is not bool or type(unswitched_removal_confirmed) is not bool:
        raise TypeError("zone selection and confirmation must be Boolean")
    used = int(quick_zone_state(values, family)["used_zones"])
    bit = 1 << zone
    if not include:
        if used & ~bit == 0:
            raise ValueError("The original quick-zone control refuses deselecting the last zone")
        if zone == 0 and not unswitched_removal_confirmed:
            raise ValueError("The original unswitched-zone removal requires an explicit confirmation")
    master = _byte(values, "ControlledZones") > 0
    result = dict(values)
    names = list(ZONE_TRANSITION_PARAMETERS)
    if family == "programmable":
        names.append("ScheduleControlledZones")
    for name in names:
        old = _byte(values, name) & 31
        if include:
            if name in ("InternalPlantZones", "ScheduleControlledZones") and not master:
                continue
            side = name.removesuffix("PlantInstalledZones")
            if side in ("Heating", "Cooling", "Venting") and _byte(values, side + "PlantType") == 0:
                continue
            result[name] = old | bit
        else:
            result[name] = old & ~bit
    return result
