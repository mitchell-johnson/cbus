"""Toolkit thermostat report bodies from complete consumed saved parameters.

This is a fresh, read-only projection of pinned native loaders. It does not run
the original loader, create its missing objects or borrow prior process state.
"""
from __future__ import annotations

from fractions import Fraction

from .project_documentation_devices import _required_array, _group_link
from .project_documentation_outputs import _registration
from .project_documentation_usage import Usage
from .thermostat_post_load import OUTPUTS, DAMPERS, VIRTUAL_11_OUTPUTS, pp_name
from .thermostat_temperature import convert_temperature

PROFILES = {
    "PC_TSA": ("TPC_TSA", "TCBusProgrammableThermostatCGateAgent"),
    "PC_TSA5": ("TPC_TSA5", "TCBusProgrammableThermostatCGateAgent"),
    "PC_TSB": ("TPC_TSB", "TCBusBasicThermostatCGateAgent"),
    "PC_TSB5": ("TPC_TSB5", "TCBusBasicThermostatCGateAgent"),
}
PLANT_LABELS = (
    "None", "Furnace (Gas, Oil, Electric)", "Evaporative",
    "Heat pump - reverse cycle", "Heat pump - heating only", "Heat pump - cooling only",
    "Furnace / Evap Cooling", "Furnace / Heat pump - cooling only", "Hydronic",
    "Hydronic / Heat pump - cooling only", "Hydronic / Evaporative", "Fan Coil",
)
ZONE_LABELS = ("Unswitched Zone", "Zone 1", "Zone 2", "Zone 3", "Zone 4")
FAN_LABELS = ("Automatic operation", "Continuous operation", "Setback")
INPUT_LABELS = ("Cool Activation", "Cool Stage 1", "Cool Stage 2", "Cool Stage 3",
                "Cool Fan Low", "Cool Fan Medium", "Cool Fan High", "Heat Activation",
                "Heat Stage 1", "Heat Stage 2", "Heat Stage 3", "Heat Fan Low",
                "Heat Fan Medium", "Heat Fan High", "Damper Zone 1", "Damper Zone 2",
                "Damper Zone 3", "Damper Zone 4")


def thermostat_profile(unit):
    row = _registration(unit)
    if row is None or row[3:5] != PROFILES.get(unit.unit_type.upper()):
        raise ValueError("unrecovered thermostat class or firmware")
    return unit.unit_type.upper()


def _byte(unit, name):
    return _required_array(unit, name, 1)[0]


def _primary(unit):
    # Inherited TCBusUnitCGateAgent uses Application[0]. ApplicationNumber is
    # separately loaded into TCBusParameters and does not replace that object.
    return _required_array(unit, "Application", 1)[0]


def _programs(unit, kind):
    if kind.startswith("PC_TSB"):
        return False, False
    evap, non = (_byte(unit, name) for name in ("EvapProgramEnabled", "NonEvapProgramEnabled"))
    return bool(evap if evap <= 1 else 0), bool(non if non <= 1 else 1)


def _plant(unit):
    value = _byte(unit, "InternalPlantType")
    if value == 8 and any(_byte(unit, pp_name(name)) != 255 for name in VIRTUAL_11_OUTPUTS):
        value = 11
    if value > 11:
        raise ValueError("InternalPlantType enumeration outside recovered range")
    return value


def display_fan_delay(half_minutes):
    """Original minute/30-second concatenation, including the zero ``0s``."""
    return (f"{half_minutes // 2}m" + ("30s" if half_minutes % 2 else "")
            if half_minutes >= 2 else f"{half_minutes % 2 * 30}s")


def thermostat_data(unit, *, units="celsius"):
    kind = thermostat_profile(unit)
    if units not in ("celsius", "fahrenheit"):
        raise ValueError("temperature units must be celsius or fahrenheit")
    zones = {name: _byte(unit, name) for name in (
        "InstalledZones", "ControlledZones", "CoolingPlantInstalledZones",
        "HeatingPlantInstalledZones", "VentingPlantInstalledZones", "UIAllocatedZones", "MeasuredZones")}
    fan_mode = _byte(unit, "FanOperationMode")
    if fan_mode > 2:
        raise ValueError("FanOperationMode enumeration outside recovered range")
    data = {"kind": kind, "zones": zones, "slave": zones["ControlledZones"] == 0,
            "plant": _plant(unit), "fan_mode": fan_mode, "units": units,
            "guard": _byte(unit, "GuardEnable") > 0, "fans": {}}
    if data["slave"]:
        data["master"] = (_byte(unit, "MasterNetworkAddress"), _byte(unit, "MasterAddress"))
    if kind.startswith("PC_TSA"):
        zone = _byte(unit, "ZoneTemperatureDisplay")
        if zone > 4:
            raise ValueError("ZoneTemperatureDisplay enumeration outside recovered range")
        data["ui_zone"] = zone
        data["evap"], data["nonevap"] = _programs(unit, kind)
        if data["evap"] or data["nonevap"]:
            data["schedule"] = tuple(_byte(unit, "RemoteSchedule" + role + "Group")
                                     for role in ("On", "Off", "Override"))
    if data["guard"]:
        for side in ("Lower", "Upper"):
            raw = _byte(unit, "Guard" + side + "Temperature")
            signed = raw - 256 if raw >= 128 else raw
            data[side.lower()] = convert_temperature("CGateTempToUnitTemp", signed, units=units)
    for side in ("Heating", "Cooling"):
        prefix = side + "PlantFan"
        fan = {"enabled": _byte(unit, prefix + "Enable") > 0}
        if fan["enabled"]:
            fan.update(direct=_byte(unit, prefix + "SpeedControlEnable") > 0,
                       speeds=_byte(unit, prefix + "Speeds"),
                       default=_byte(unit, prefix + "DefaultSpeed"))
            for direction in ("On", "Off"):
                # Stored five-second ticks become half-minute units by / 6.
                fan[direction.lower()] = round(Fraction(_byte(unit, prefix + direction + "Delay"), 6))
        data["fans"][side] = fan
    if kind.endswith("5"):
        data["relays"] = (_primary(unit), tuple(_byte(unit, f"InternalRelay{n}GroupNumber")
                                               for n in range(1, 6)))
    return data


def _master_link(network, data, model):
    from .project_documentation import html_unit
    number, address = data["master"]
    if address == 255:
        raise ValueError("unresolved thermostat MasterAddress 255")
    target = network if number == 255 else None
    if number != 255:
        # NetworkByNetworkNumber does not look up the lexical Address. Require
        # that independent identity rather than substituting the report link.
        targets = [item for item in model.networks
                   if getattr(item, "network_number", None) == number] if model is not None else []
        if len(targets) != 1:
            raise ValueError("explicit master network number requires one resolved NetworkNumber")
        target = targets[0]
    master = next((item for item in target.units if item.address == address), None) if target else None
    if master is None or master.unit_type.upper() not in PROFILES:
        raise ValueError("unresolved thermostat Master unit")
    thermostat_profile(master)
    return html_unit(target, master)


def thermostat_lines(network, data, *, model=None):
    def row(label, value):
        return f"<tr><th>{label}</th><td>{value}</td></tr>"

    lines = ["Master/Slave: " + ("Slave" if data["slave"] else "Master") + "<br/>"]
    if data["slave"]:
        lines.append("Master Unit: " + _master_link(network, data, model) + "<br/>")
    lines.append("Plant Type: " + PLANT_LABELS[data["plant"]] + "<br/>")
    if "ui_zone" in data:
        lines.append("UI Displayed Temperature Zone: " + ZONE_LABELS[data["ui_zone"]] + "<br/>")
    for index, zone in enumerate(ZONE_LABELS):
        if not data["zones"]["InstalledZones"] & (1 << index):
            continue
        lines.extend(['<table border="1">', '<tr><th colspan="2">' + zone + '</th></tr>'])
        for label, field in (("Plant Zone", "ControlledZones"), ("Cooling Operation", "CoolingPlantInstalledZones"),
                             ("Heating Operation", "HeatingPlantInstalledZones"), ("Venting Operation", "VentingPlantInstalledZones"),
                             ("User Controlled", "UIAllocatedZones"), ("Local Temperature Sensor", "MeasuredZones")):
            lines.append(row(label, "Yes" if data["zones"][field] & (1 << index) else "No"))
        lines.extend(["</table>", "<br/>"])
    if data["guard"]:
        suffix = "°C" if data["units"] == "celsius" else "°F"
        lines.extend(["Guard Enabled<br/>", f"Lower Activation Threshold: {data['lower']}{suffix}<br/>",
                      f"Upper Activation Threshold: {data['upper']}{suffix}<br/>"])
    else:
        lines.append("Guard Disabled<br/>")
    lines.extend(["<br/>", "Fan Operation Mode: " + FAN_LABELS[data["fan_mode"]] + "<br/>", "<table>"])
    for side in ("Heating", "Cooling"):
        fan = data["fans"][side]
        lines.extend(['<td vAlign="top"><table border="1">', '<tr><th colspan="2">' + side + ' Fan</th></tr>',
                      row("Fan Operation", "Enabled" if fan["enabled"] else "Disabled")])
        if fan["enabled"]:
            lines.extend([row("Allow Direct Fan Speed Control", "Yes" if fan["direct"] else "No"),
                          row("Fan Speeds", fan["speeds"]), row("Default Speed", fan["default"]),
                          row("Fan On Delay", display_fan_delay(fan["on"])),
                          row("Fan Off Delay", display_fan_delay(fan["off"]))])
        lines.append("</table></td>")
    lines.append("</tr></table>")
    if "ui_zone" in data:
        lines.extend(['<table border="1">', '<tr><th colspan="2">Scheduling</th></tr>',
                      row("Non-Evaporative Plant Equipment", "Enabled" if data["nonevap"] else "Disabled"),
                      row("Evaporative Plant Equipment", "Enabled" if data["evap"] else "Disabled")])
        if "schedule" in data:
            lines.extend(row(label, _group_link(network, 203, group)) for label, group in
                         zip(("Enable Group", "Disable Group", "Override Group"), data["schedule"]))
        lines.append("</table>")
    if "relays" in data:
        application, relays = data["relays"]
        lines.extend(['<table border="1">', '<tr><th colspan="2">Internal Relays</th></tr>'])
        lines.extend(row(f"Relay {index}", _group_link(network, application, group))
                     for index, group in enumerate(relays, 1))
        lines.append("</table>")
    return lines


def document_thermostat(out, network, unit, model=None, *, units="celsius"):
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        lines = thermostat_lines(network, thermostat_data(unit, units=units), model=model)
    except ValueError as error:
        out.mark(network, unit, str(error))
        return "partial"
    for line in lines:
        out.add(line)
    return "recovered"


def thermostat_group_usage(unit, application, group, kind, *, network=None):
    if kind not in {"input", "output", "other"}:
        raise ValueError("Group usage kind must be input, output or other")
    try:
        profile = thermostat_profile(unit)
        primary = _primary(unit)
        refs = []
        if kind == "input":
            outputs = tuple(_byte(unit, pp_name(name)) for name in OUTPUTS)
            prefix = f"[CG{_byte(unit, 'ZoneGroup'):02d}]"
            for address in outputs:
                if address == 255:
                    continue
                app = network.application(primary) if network is not None else None
                record = app.group(address) if app is not None else None
                if record is None or record.name.startswith(prefix):
                    raise ValueError("thermostat output requires an existing non-autogenerated group: "
                                     f"Application {primary} Group {address}")
            refs.extend((primary, address, label) for address, label in zip(outputs, INPUT_LABELS[:14]))
            refs.extend((primary, _byte(unit, pp_name(name)) if profile.startswith("PC_TSA") else 255, label)
                        for name, label in zip(DAMPERS, INPUT_LABELS[14:]))
        elif kind == "output":
            refs.extend((primary, _byte(unit, f"InternalRelay{n}GroupNumber"), f"Internal Relay {n}")
                        for n in range(1, 6))
        else:
            refs.append((172, _byte(unit, "ZoneGroup"), "Zone Group"))
            source = _byte(unit, "RemoteSetbackControlSource")
            target = 203 if source == 2 else primary if source == 1 else None
            refs.extend((target, _byte(unit, "RemoteSetback" + role + "Group"), "Remote Setback " + role)
                        for role in ("On", "Off") if target is not None)
            evap, non = _programs(unit, profile)
            enabled = evap or non if profile.startswith("PC_TSA") else _byte(unit, "RemoteScheduleEnable") > 0
            refs.extend((203, _byte(unit, "RemoteSchedule" + role + "Group") if enabled else 255,
                         "Schedule " + role) for role in ("On", "Off", "Override"))
        return Usage("<br/>".join(label for app, address, label in refs if (app, address) == (application, group)))
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))


def thermostat_action_selector_usage(unit, application, group, address, value):
    try:
        thermostat_profile(unit)
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
    return Usage()  # Effective TUnitTypeDocumentor.ActionSelectorUse is empty.
