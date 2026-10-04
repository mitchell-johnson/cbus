"""Source-owned nested thermostat defaults, for composition by one model owner.

The owner supplies fresh source primitives and its fixed internal callbacks.
Getters remain live at each source call site. This component does not accept a
caller notification roster, serialize PP, save a project, or emulate a window.
"""
from __future__ import annotations

from typing import Protocol


TYPE_ROLES = ("cooling", "heating", "heatcool", "venting")
MODE_BITS = {"standby": 1, "heating": 2, "cooling": 4, "heatcool": 8, "venting": 16}
DEFAULT_MODES = (1, 19, 21, 31, 19, 21, 23, 31, 3, 31, 23, 21)
_COOLING = frozenset((2, 3, 5, 6, 7, 8, 9, 10, 11))
_HEATING = frozenset((1, 3, 4, 6, 7, 8, 9, 10, 11))
_HEATCOOL = frozenset((3, 6, 7, 8, 9, 10, 11))
_HEATING_ZONES = _HEATING - {9}


class ZoneDefaultsOwner(Protocol):
    def get_type(self, role: str) -> int: ...
    def set_type(self, role: str, value: int) -> None: ...
    def get_modes(self) -> int: ...
    def set_modes(self, value: int) -> None: ...
    def get_vent_type(self) -> int: ...
    def set_vent_type(self, value: int) -> None: ...
    def get_internal_plant_type(self) -> int: ...
    def get_master_slave(self) -> int: ...
    def get_used_zones(self) -> int: ...
    def installed_zones_is_present(self, role: str) -> bool: ...
    def get_installed_zones(self, role: str) -> int | None: ...
    def set_installed_zones(self, role: str, value: int) -> None: ...
    def get_guard(self, name: str) -> bool: ...
    def set_guard(self, name: str, value: bool) -> None: ...
    def has_registered_hook(self, name: str) -> bool: ...
    def invoke_registered_hook(self, name: str, *args: object) -> None: ...
    def update_fan_speeds(self) -> None: ...
    def is_programmable(self) -> bool: ...
    def set_program_enabled(self, name: str, value: bool) -> None: ...
    def get_zone_mask(self, role: str) -> int: ...
    def set_zone_mask(self, role: str, value: int) -> None: ...
    def include_zone(self, role: str, zone: int) -> None: ...
    def exclude_zone(self, role: str, zone: int) -> None: ...
    def get_quick_checked(self, zone: int) -> bool: ...


def _byte(value: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(f"{label} requires a source byte")
    return value


class ZoneDefaultsModel:
    """Ordered source methods using synchronous primitives on the exact owner."""

    def __init__(self, owner: ZoneDefaultsOwner):
        self.owner = owner

    def _hook(self, name: str, *args: object) -> None:
        if self.owner.has_registered_hook(name):
            self.owner.invoke_registered_hook(name, *args)

    def set_default_plant_modes(self) -> None:
        # PlantTypeAttribute.GetDefaultPlantModes masks its live virtual value.
        value = self.owner.get_internal_plant_type() & 0x7F
        self.owner.set_modes(DEFAULT_MODES[value] if value < 12 else 31)
        self._hook("enable_disable_plant_modes")

    def set_default_plant_types(self, plant_byte: int) -> None:
        value = _byte(plant_byte, "plant type")
        if value > 11:
            return
        o = self.owner
        if value == 0:
            # This method does not clear the four type attributes for None.
            # The owning parent has a separate explicit four-setter tail.
            for role in ("cooling", "heating", "venting"):
                o.set_installed_zones(role, 0)
            return
        for role, supported in (("cooling", _COOLING), ("heating", _HEATING),
                                ("heatcool", _HEATCOOL)):
            if value in supported:
                o.set_type(role, value if o.get_modes() & MODE_BITS[role] else 0)
            else:
                o.set_type(role, 0)
        o.set_type("venting", value if o.get_modes() & 16 else 0)
        for role, supported in (("cooling", _COOLING), ("heating", _HEATING_ZONES)):
            o.set_installed_zones(role, o.get_used_zones() if value in supported else 0)
        o.set_installed_zones("venting", o.get_used_zones())

    def _simple_type_after_change(self, role: str) -> None:
        o = self.owner
        if o.get_guard("zone120"):
            return
        if o.has_registered_hook("zone_manager_plant_type_change"):
            o.invoke_registered_hook("zone_manager_plant_type_change", role, o.get_type(role))
        o.set_guard("zone130", True)
        try:
            o.set_installed_zones(role, 0 if o.get_type(role) == 0 else o.get_used_zones())
        finally:
            # Source clears rather than restores the previous guard value.
            o.set_guard("zone130", False)
        name = "type_after_change:" + role
        if o.has_registered_hook(name):
            o.invoke_registered_hook(name, o.get_type(role))

    def handle_cooling_type_after_change(self) -> None:
        self._simple_type_after_change("cooling")

    def handle_heating_type_after_change(self) -> None:
        self._simple_type_after_change("heating")

    def handle_venting_type_after_change(self) -> None:
        self._simple_type_after_change("venting")

    def handle_heatcool_type_after_change(self) -> None:
        o = self.owner
        if o.get_guard("zone120"):
            return
        if o.has_registered_hook("zone_manager_plant_type_change"):
            o.invoke_registered_hook("zone_manager_plant_type_change", "heatcool", o.get_type("heatcool"))
        self.select_installed_zones()

    def select_installed_zones(self) -> None:
        o = self.owner
        if o.get_guard("zone130"):
            return
        o.set_guard("zone130", True)
        try:
            # These two UsedZones reads can observe different nested state.
            for role in ("heating", "venting"):
                o.set_installed_zones(role, 0 if o.get_type(role) == 0 else o.get_used_zones())
        finally:
            o.set_guard("zone130", False)

    def handle_zone_after_change(self) -> None:
        o = self.owner
        if o.get_guard("zone130"):
            return
        o.set_guard("zone130", True)
        try:
            for role in ("heating", "cooling", "venting"):
                # Source checks object nil, then obtains it again for GetZones.
                if o.installed_zones_is_present(role) and o.get_installed_zones(role) == 0:
                    o.set_type(role, 0)
            self._hook("zone_after_change")
        finally:
            o.set_guard("zone130", False)

    def handle_zone_manager_plant_type_change(self) -> None:
        o = self.owner
        if not o.get_guard("plant15c"):
            # This source local is intentionally retained across Vent callbacks.
            modes = o.get_modes()
            for role in TYPE_ROLES:
                modes = modes | MODE_BITS[role] if o.get_type(role) else modes & ~MODE_BITS[role]
            if not modes & 16:
                o.set_vent_type(0)
            else:
                o.set_vent_type(2 if modes & 4 else 1 if modes & 2 else 2)
            o.set_modes(modes)
        # The programmable override invokes base first, then still runs this
        # tail if base returned at plant15c. It only disables, never enables.
        if o.is_programmable():
            if all(o.get_type(role) in (0, 2) for role in ("heating", "cooling", "heatcool", "venting")):
                o.set_program_enabled("non_evap", False)
            if all(o.get_type(role) not in (2, 6, 10) for role in ("heating", "cooling", "heatcool", "venting")):
                o.set_program_enabled("evap", False)

    def handle_vent_plant_type_change(self) -> None:
        o = self.owner
        if o.get_guard("plant15c") or o.get_guard("plant15d"):
            return
        if o.get_vent_type() == 0:
            o.set_modes(o.get_modes() & ~16)
            o.set_type("venting", 0)
        else:
            o.set_modes(o.get_modes() | 16)
            o.set_type("venting", o.get_internal_plant_type())
            o.update_fan_speeds()

    def update_vent_plant_type(self) -> None:
        o = self.owner
        if o.get_master_slave() == 0 and o.get_internal_plant_type() in (2, 3, 6, 7, 9, 10, 11):
            o.set_vent_type(2)
        elif o.get_internal_plant_type() in (0, 8) and o.get_master_slave() == 0:
            o.set_vent_type(0)
            return
        if o.get_modes() & 2 and not o.get_modes() & 8 and not o.get_modes() & 4 and o.get_master_slave() == 0:
            o.set_vent_type(1)
        if o.get_modes() & 8 or o.get_modes() & 2:
            if not o.get_modes() & 16 and o.get_master_slave() == 0:
                o.set_vent_type(2)
        else:
            # This final branch does not test master/slave.
            o.set_vent_type(2)

    def templates_include_zone(self, zone: int) -> None:
        zone = _byte(zone, "zone")
        o = self.owner
        o.include_zone("used", zone)
        o.include_zone("ui", zone)
        if o.get_master_slave() == 0:
            o.include_zone("internal", zone)
        o.include_zone("measured", zone)
        if o.is_programmable() and o.get_master_slave() == 0:
            o.include_zone("schedule", zone)
        o.include_zone("cbus", zone)
        o.include_zone("controlled", zone)
        for role in ("heating", "cooling", "venting"):
            if o.get_type(role) != 0:
                o.include_zone(role, zone)
        self._hook("templates_zone_change", zone, True)

    def templates_exclude_zone(self, zone: int) -> None:
        zone = _byte(zone, "zone")
        o = self.owner
        for role in ("used", "ui", "internal", "measured"):
            o.exclude_zone(role, zone)
        if o.is_programmable():
            o.exclude_zone("schedule", zone)
        for role in ("cbus", "controlled", "heating", "cooling", "venting"):
            o.exclude_zone(role, zone)
        self._hook("templates_zone_change", zone, False)

    def _zone_in(self, role: str, zone: int) -> bool:
        # Source obtains GetZones even when its byte enum exceeds seven.
        mask = self.owner.get_zone_mask(role)
        return zone <= 7 and bool(mask & (1 << zone))

    def templates_zone_partially_on(self, zone: int) -> bool:
        zone = _byte(zone, "zone")
        o = self.owner
        result = any(self._zone_in(role, zone) for role in ("ui", "internal", "measured"))
        if o.is_programmable() and not result:
            result = self._zone_in("schedule", zone)
        if not result:
            result = any(self._zone_in(role, zone) for role in ("heating", "cooling", "venting"))
        return result

    def templates_zone_fully_on(self, zone: int) -> bool:
        zone = _byte(zone, "zone")
        o = self.owner
        result = all(self._zone_in(role, zone) for role in ("ui", "internal", "measured"))
        if o.is_programmable() and result:
            result = self._zone_in("schedule", zone)
        if result:
            result = all(self._zone_in(role, zone) for role in ("heating", "cooling", "venting"))
        return result

    def templates_checkbox_state_for_zone(self, zone: int) -> int:
        partial = self.templates_zone_partially_on(zone)
        full = self.templates_zone_fully_on(zone)
        return 2 if partial and not full else 1 if full else 0

    def update_flash_zone_variables(self) -> None:
        o = self.owner
        o.set_zone_mask("used", 0)
        o.set_zone_mask("cbus", 0)
        for zone in range(5):
            if o.get_quick_checked(zone):
                o.include_zone("used", zone)
                o.include_zone("cbus", zone)
