"""Temperature documentors projected from consumed saved PP fields.

The unit and decimal preferences are explicit offline profiles, not observations
of the original running application. No PP editor or device operation is involved.
"""
from __future__ import annotations

from fractions import Fraction

from .project_documentation_devices import _required_array
from .project_documentation_outputs import _registration
from .thermostat_temperature import _binary_round, _celsius_to_fahrenheit

TEMPERATURE_FORMAT_BASIS = "explicit Celsius / period-decimal profile; original running preferences not observed"
PROFILES = {
    "SENTEMP": ("TSENTEMP", "TSENTEMPCGateAgent"),
    "SENTEMPB": ("TSENTEMPPro", "TSENTEMPProCGateAgent"),
    "SENTEMP4": ("TPC_RDTS", "TCBusDigitalTemperatureSensorCGateAgent"),
}


def temperature_supported(unit) -> bool:
    row = _registration(unit)
    return row is not None and row[3:5] == PROFILES.get(unit.unit_type.upper())


def _profile(unit):
    if not temperature_supported(unit):
        raise ValueError("unrecovered temperature sensor class or firmware")
    return unit.unit_type.upper()


def _byte(unit, name):
    return _required_array(unit, name, 1)[0]


def _mode(application):
    return {25: 1, 172: 2, 228: 3}.get(application, 0)


def display_zones(mask: int) -> str:
    return ", ".join(label for bit, label in enumerate(
        ("Unswitched Zone", "Zone 1", "Zone 2", "Zone 3", "Zone 4")) if mask & (1 << bit))


def display_interval(value: int) -> str:
    return (f"{value // 6}m" if value >= 6 else "") + (f"{value % 6 * 10}s" if value % 6 else "")


def _temperature(value, units, *, delta=False, decimals=False):
    value = Fraction(value)
    if units == "fahrenheit":
        value = _celsius_to_fahrenheit(value)
        if delta:
            value = _binary_round(value - 32)
    elif units != "celsius":
        raise ValueError("temperature units must be celsius or fahrenheit")
    if decimals:
        # Original FloatToDecimal rounds discarded decimal digit >= 5 up.
        # Consumed bounded values are exact eighths or converted binary doubles.
        cents = (abs(value) * 100 + Fraction(1, 2)).numerator // (abs(value) * 100 + Fraction(1, 2)).denominator
        text = ("-" if value < 0 else "") + f"{cents // 100}.{cents % 100:02d}"
    else:
        text = str(round(value))  # System.@ROUND uses nearest/even.
    return text + ("°C" if units == "celsius" else "°F")


def temperature_data(unit):
    """Fresh model projection; absent consumed fields never become defaults."""
    kind = _profile(unit)
    data = {"kind": kind}
    if kind == "SENTEMP4":
        data["device_id"] = _byte(unit, "DeviceID")
        channels = []
        for number in range(1, 5):
            prefix = f"Channel{number}"
            raw_name = unit.parameters.get(prefix + "ChannelName")
            if raw_name is None:
                raise ValueError(f"missing {prefix}ChannelName")
            # Delphi Trim removes only code units <= ASCII space.
            name = raw_name.strip("".join(chr(n) for n in range(33))) or f"Channel {number}"
            mode = _byte(unit, prefix + "ChannelMode")
            group = _byte(unit, prefix + "HVACCommunicationGroup") if mode == 172 else 255
            interval = _byte(unit, prefix + "BroadcastInterval")
            threshold = _byte(unit, prefix + "BroadcastThreshold")
            channels.append({"name": name, "hvac": mode == 172 and group != 255,
                             "group": group, "zones": _byte(unit, prefix + "HVACZones") if mode == 172 and group != 255 else 0,
                             "interval": interval * 10 if interval else 60,
                             "threshold": Fraction(threshold, 8) if threshold else Fraction(1, 2)})
        data["channels"] = channels
        return data
    app = data["application"] = _byte(unit, "Application")
    if kind == "SENTEMP":
        high, low = _byte(unit, "TemperatureHigh"), _byte(unit, "TemperatureLow")
        data.update(control=_byte(unit, "ControlGroupAddress"), enable=_byte(unit, "EnableGroupAddress"),
                    economy=_byte(unit, "OffsetGroupAddress"), heating=_byte(unit, "OffsetMode") == 0,
                    target=(high + low + 1) // 2, margin=high - low)
        if data["economy"] != 255:
            data["offset"] = _byte(unit, "TemperatureOffset")
    else:
        mode = data["mode"] = _mode(app)
        if mode == 0:
            high, low = _required_array(unit, "TargetTemperature", 2)
            data.update(control=_byte(unit, "ControlledGroup"), enable=_byte(unit, "GroupAddress"),
                        economy=_byte(unit, "EconomyGroup"), heating=_byte(unit, "ModeHeating") == 0,
                        high=min(50, max(1, high)), low=min(49, low))
            if data["economy"] != 255:
                data["offset"] = min(20, _byte(unit, "EconomyOffset"))
        else:
            if mode in (1, 2):
                data["broadcast_group"] = _byte(unit, "TemperatureGroup" if mode == 1 else "GroupAddress")
            if mode == 2:
                data["zones"] = _byte(unit, "ThermostatRegulationZones")
            if mode == 3:
                data["device_id"] = _byte(unit, "GroupAddress")
            data["trigger"] = _byte(unit, "BroadcastTriggerGroup")
            if data["trigger"] != 255:
                data["selector"] = _byte(unit, "BroadcastTriggerLevel")
            interval, threshold = _byte(unit, "BroadcastInterval"), _byte(unit, "TemperatureChangeThreshold")
            data["interval"] = None if interval == 255 else min(60, max(3, interval or 6))
            data["threshold"] = (None if threshold in (254, 255) else
                                 Fraction(min(32, max(1, threshold // 2 if threshold else 6)), 2))
    return data


def _group(network, application, address):
    from .project_documentation import html_group
    app = network.application(application)
    group = app.group(address) if app is not None else None
    if group is None:
        raise ValueError(f"unresolved Application {application} Group {address}")
    return html_group(network, application, group)


def _level(network, group, address):
    app = network.application(202)
    record = app.group(group) if app is not None else None
    level = next((level for level in record.levels if level.address == address), None) if record else None
    if level is None:
        raise ValueError(f"unresolved Application 202 Group {group} Level {address}")
    return f'<a href="#{network.address}_202_{group}_{address}">{level.name}</a>'


def temperature_lines(network, data, *, units="celsius"):
    if units not in ("celsius", "fahrenheit"):
        raise ValueError("temperature units must be celsius or fahrenheit")
    kind = data["kind"]
    if kind == "SENTEMP4":
        identity = "Unassigned" if data["device_id"] == 255 else str(data["device_id"])
        lines = [f"<b>Device ID: </b>{identity}<br />", '<table border="1"><tr>']
        lines += [f'<th>{channel["name"]}</th>' for channel in data["channels"]]
        lines += ["</tr>", "<tr>"]
        for channel in data["channels"]:
            lines.append("<td>")
            if channel["hvac"]:
                lines += ["<b>Mode:</b> HVAC<br />",
                          f'<b>Communication Group:</b> {_group(network, 172, channel["group"])}<br />',
                          f'<b>Zones:</b> {display_zones(channel["zones"])}<br />']
            else:
                lines.append("<b>Mode:</b> Measurement<br />")
            # Native ignores the Enabled flags and converts threshold as an
            # absolute temperature in Fahrenheit (it does not subtract 32).
            lines += [f'<b>Broadcast Interval:</b> {channel["interval"]} seconds<br />',
                      f'<b>Broadcast Threshold:</b> {_temperature(channel["threshold"], units, decimals=True)}<br />', "</td>"]
        return lines + ["</tr>"]  # Original has no closing </table>.
    app = data["application"]
    if kind == "SENTEMP" or data["mode"] == 0:
        lines = [f'{label} Group: {_group(network, app, data[field])}<br />'
                 for label, field in (("Controlled", "control"), ("Enable", "enable"), ("Economy", "economy"))]
        lines += [f'Mode: {"Heating" if data["heating"] else "Cooling"}<br />']
        fields = (("Target", "target", False), ("Margin", "margin", True)) if kind == "SENTEMP" else (
            ("Target Temperature High", "high", False), ("Target Temperature Low", "low", False))
        lines += [f'{label}: {_temperature(data[field], units, delta=delta)}<br />' for label, field, delta in fields]
        if data["economy"] != 255:
            lines.append(f'Economy Offset: {_temperature(data["offset"], units, delta=True)}<br />')
        return lines
    lines = []
    if data["mode"] in (1, 2):
        label = "Temperature" if data["mode"] == 1 else "Communication"
        lines.append(f'{label} Group: {_group(network, app, data["broadcast_group"])}<br />')
    if data["mode"] == 2:
        lines.append(f'Zones: {display_zones(data["zones"])}<br />')
    if data["mode"] == 3:
        lines.append(f'Device ID: {data["device_id"]}<br />')
    lines.append(f'Broadcast Trigger Group: {_group(network, 202, data["trigger"])}<br />')
    if data["trigger"] != 255:
        lines.append(f'Broadcast Trigger Action Selector: {_level(network, data["trigger"], data["selector"])}<br />')
    lines.append(f'Broadcast Interval: {"Not Used" if data["interval"] is None else display_interval(data["interval"])}<br />')
    threshold = "Not Used" if data["threshold"] is None else _temperature(data["threshold"], units, delta=True, decimals=True)
    return lines + [f"Broadcast Temperature Threshold: {threshold}<br />"]


def document_temperature(out, network, unit, *, units="celsius"):
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        lines = temperature_lines(network, temperature_data(unit), units=units)
    except ValueError as exc:
        out.mark(network, unit, f"Temperature sensor: {exc}")
        return "partial"
    for line in lines:
        out.add(line)
    return "recovered"


def temperature_group_usage(unit, application, group, kind):
    from .project_documentation_usage import Usage
    if kind not in ("input", "output", "other"):
        raise ValueError("Group usage kind must be input, output or other")
    try:
        profile = _profile(unit)
        if profile == "SENTEMP4":
            raise ValueError("SENTEMP4 group usage belongs to the existing digital sensor helper")
        if kind == "output":
            return Usage()
        primary = _byte(unit, "Application")
        if primary != application:
            return Usage()
        mode = _mode(primary) if profile == "SENTEMPB" else 0
        fields = []
        if kind == "input" and mode == 0:
            fields = [("ControlGroupAddress", "Control Group")] if profile == "SENTEMP" else [("ControlledGroup", "Controlled Group")]
        if kind == "other":
            if mode == 0:
                fields = [("AreaGroupAddress", "Area Group")] + ([("EnableGroupAddress", "Enable Group"), ("OffsetGroupAddress", "Economy Group")]
                          if profile == "SENTEMP" else [("GroupAddress", "Enable Group"), ("EconomyGroup", "Economy Group")])
            elif mode == 1:
                fields = [("TemperatureGroup", "Temperature Group")]
            elif mode == 2:
                fields = [("GroupAddress", "Communication Group")]
        descriptions, missing = [], []
        for field, label in fields:
            try:
                if _byte(unit, field) == group:
                    descriptions.append(label)
            except ValueError as exc:
                missing.append(str(exc))
        return Usage("<br/>".join(descriptions), "partial" if missing else "recovered", tuple(missing))
    except ValueError as exc:
        return Usage(status="unrecovered", missing=(str(exc),))
