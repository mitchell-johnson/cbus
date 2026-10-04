"""Explicit selection of source-prepared thermostat Boolean bindings.

These are the 34 properties passed to PrepareFlashCheckbox by the retained
UI, Plant, Temperature and Zone Management panels. One fresh settings owner
issues the bindings and runs its synchronous callbacks. This module does not
claim native Enabled/Visible/focus/mouse admission or dispatch a GUI Click.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from .thermostat_templates import ThermostatTemplateError


# Exact retained expressions, including the four named mode Booleans. There
# is no prepared Standby checkbox, nor direct Installed/Controlled/Schedule
# mask control in this offered property-binding family.
_BINDING_SPECS = (
    ("UI", "chbUnswitchedZone", "UIAllocatedZones.UnswitchedZone", "ui", 0),
    ("UI", "chbZone1", "UIAllocatedZones.Zone1", "ui", 1),
    ("UI", "chbZone2", "UIAllocatedZones.Zone2", "ui", 2),
    ("UI", "chbZone3", "UIAllocatedZones.Zone3", "ui", 3),
    ("UI", "chbZone4", "UIAllocatedZones.Zone4", "ui", 4),
    ("Plant", "chbPlantUnswitchedZone", "InternalPlantZones.UnswitchedZone", "internal", 0),
    ("Plant", "chbPlantZone1", "InternalPlantZones.Zone1", "internal", 1),
    ("Plant", "chbPlantZone2", "InternalPlantZones.Zone2", "internal", 2),
    ("Plant", "chbPlantZone3", "InternalPlantZones.Zone3", "internal", 3),
    ("Plant", "chbPlantZone4", "InternalPlantZones.Zone4", "internal", 4),
    ("Plant", "chbPlantModeHeat", "InternalPlantModes.Heat", "modes", 1),
    ("Plant", "chbPlantModeCool", "InternalPlantModes.Cool", "modes", 2),
    ("Plant", "chbPlantModeHeatCool", "InternalPlantModes.HeatCool", "modes", 3),
    ("Plant", "chbPlantModeVent", "InternalPlantModes.Vent", "modes", 4),
    ("TempControl", "chbMeasuredUnswitchedZone", "MeasuredZones.UnswitchedZone", "measured", 0),
    ("TempControl", "chbMeasuredZone1", "MeasuredZones.Zone1", "measured", 1),
    ("TempControl", "chbMeasuredZone2", "MeasuredZones.Zone2", "measured", 2),
    ("TempControl", "chbMeasuredZone3", "MeasuredZones.Zone3", "measured", 3),
    ("TempControl", "chbMeasuredZone4", "MeasuredZones.Zone4", "measured", 4),
    ("ZoneManagement", "chbCoolingUnswitchedZone", "CoolingPlantInstalledZones.UnswitchedZone", "cooling", 0),
    ("ZoneManagement", "chbCoolingZone1", "CoolingPlantInstalledZones.Zone1", "cooling", 1),
    ("ZoneManagement", "chbCoolingZone2", "CoolingPlantInstalledZones.Zone2", "cooling", 2),
    ("ZoneManagement", "chbCoolingZone3", "CoolingPlantInstalledZones.Zone3", "cooling", 3),
    ("ZoneManagement", "chbCoolingZone4", "CoolingPlantInstalledZones.Zone4", "cooling", 4),
    ("ZoneManagement", "chbVentingUnswitchedZone", "VentingPlantInstalledZones.UnswitchedZone", "venting", 0),
    ("ZoneManagement", "chbVentingZone1", "VentingPlantInstalledZones.Zone1", "venting", 1),
    ("ZoneManagement", "chbVentingZone2", "VentingPlantInstalledZones.Zone2", "venting", 2),
    ("ZoneManagement", "chbVentingZone3", "VentingPlantInstalledZones.Zone3", "venting", 3),
    ("ZoneManagement", "chbVentingZone4", "VentingPlantInstalledZones.Zone4", "venting", 4),
    ("ZoneManagement", "chbHeatingUnswitchedZone", "HeatingPlantInstalledZones.UnswitchedZone", "heating", 0),
    ("ZoneManagement", "chbHeatingZone1", "HeatingPlantInstalledZones.Zone1", "heating", 1),
    ("ZoneManagement", "chbHeatingZone2", "HeatingPlantInstalledZones.Zone2", "heating", 2),
    ("ZoneManagement", "chbHeatingZone3", "HeatingPlantInstalledZones.Zone3", "heating", 3),
    ("ZoneManagement", "chbHeatingZone4", "HeatingPlantInstalledZones.Zone4", "heating", 4),
)
ZONE_BINDINGS = tuple(row[2] for row in _BINDING_SPECS)


def normalize_zone_operation(row):
    """Closed explicit binding grammar; unknown operation families return None."""
    if not isinstance(row, Mapping):
        raise ThermostatTemplateError("Prepared zone operation must be a record")
    if type(row.get("op")) is not str:
        raise ThermostatTemplateError("Thermostat operation op must be text")
    if row["op"] != "zone-checkbox-binding":
        return None
    if set(row) != {"op", "binding", "checked"}:
        raise ThermostatTemplateError("Zone property binding requires exactly op, binding and checked")
    if type(row["binding"]) is not str or row["binding"] not in ZONE_BINDINGS:
        raise ThermostatTemplateError("Zone binding must select one of the 34 prepared source expressions")
    if type(row["checked"]) is not bool:
        raise ThermostatTemplateError("Zone binding checked must be an exact Boolean")
    return {"op": row["op"], "binding": row["binding"], "checked": row["checked"]}


class _PreparedBoolean:
    __slots__ = ("owner", "spec")

    def __init__(self, owner, spec):
        self.owner, self.spec = owner, spec


class PreparedZoneControls:
    """Bindings issued by, and inseparable from, one fresh synchronous owner."""

    def __init__(self, owner):
        from .thermostat_quick_zone_controls import ThermostatControlModel
        if type(owner) is not ThermostatControlModel:
            raise ThermostatTemplateError("Zone bindings require the exact fresh thermostat owner")
        self._owner = owner
        self._bindings = {spec[2]: _PreparedBoolean(owner, spec) for spec in _BINDING_SPECS}
        self._records = tuple((name, item, item.spec) for name, item in self._bindings.items())
        self._operations = []

    def verify(self):
        from .thermostat_quick_zone_controls import ThermostatControlModel
        if (type(self._owner) is not ThermostatControlModel or self._owner.zone_controls is not self
                or tuple(self._bindings) != ZONE_BINDINGS or len(self._records) != len(_BINDING_SPECS)):
            raise ThermostatTemplateError("Zone bindings no longer belong to the original source owner")
        for spec, (name, original, original_spec) in zip(_BINDING_SPECS, self._records):
            item = self._bindings[name]
            if (type(item) is not _PreparedBoolean or item is not original
                    or item.owner is not self._owner or item.spec != spec or original_spec != spec):
                raise ThermostatTemplateError("Zone selection requires the originally issued prepared binding")

    def apply(self, row, position):
        operation = normalize_zone_operation(row)
        if operation is None:
            raise ThermostatTemplateError("Expected a prepared zone property-binding operation")
        self._owner._verify_owner()
        self.verify()
        if (type(position) is not int or position != self._owner._position
                or (self._operations and position <= self._operations[-1]["position"])):
            raise ThermostatTemplateError("Zone binding position must belong to the current fresh history")
        binding = self._bindings[operation["binding"]]
        panel, component, expression, role, bit = binding.spec
        owner = self._owner
        field = expression.split(".", 1)[0]
        before = owner.values[field]
        start = len(owner._trace)
        owner._record("explicit-prepared-Boolean-binding", expression=expression,
                      panel=panel, component=component, checked=operation["checked"],
                      exact_owned_binding=True, native_click_dispatched=False)
        # Use the same actual Boolean primitive as nested Include/Exclude.
        # Its equality guard and synchronous source callbacks see live state;
        # do not substitute a whole mask or rearm dirty flags artificially.
        owner._set_zone_boolean(role, bit, operation["checked"])
        after = owner.values[field]
        receipt = {"position": position, **operation, "panel": panel, "component": component,
                   "role": role, "bit": bit, "before_mask": before, "after_mask": after,
                   "before_checked": bool(before & (1 << bit)),
                   "after_checked": bool(after & (1 << bit)),
                   "source_calls": deepcopy(owner._trace[start:]),
                   "exact_owned_prepared_binding": True, "native_click_dispatched": False,
                   "native_enabled_visible_focus_admission_verified": False}
        self._operations.append(receipt)
        return deepcopy(receipt)

    def as_dict(self):
        self.verify()
        return {"profile": "explicit-source-prepared-zone-Boolean-bindings-v1",
                "binding_count": 34, "bindings": list(ZONE_BINDINGS),
                "operations": deepcopy(self._operations),
                "same_synchronous_settings_owner": True,
                "native_enabled_visible_focus_admission_verified": False,
                "native_mouse_or_click_dispatched": False,
                "caller_subscriber_registry_admitted": False}
