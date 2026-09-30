"""Bounded fan body and error-report output projections from saved PP data.

These are source-derived report models. No programming, live device access,
label transfer, original GUI or generated-page acceptance is implied.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .project_documentation_devices import _group_link, _required_array
from .project_documentation_outputs import OutputProfile, _registration

FAN_FIRMWARE_RANGES = (("2.4.00", "2.4.99"), ("2.5.00", "2.5.99"), ("2.6.00", "2.6.99"))
ERROR_CHANNELS = {"DIMDU4": 4, "DIMPR3A": 3, "DIMPR6A": 6, "DIMPR12A": 12}
ERROR_LABELS = ("Trigger Error Report", "Trigger Error Report Clear")


def _fan_class(unit):
    row = _registration(unit)
    return unit.unit_type.upper() == "RELDF1" and row is not None and row[3:5] == (
        "TRELDF1", "TCBusFanControllerCGateAgent")


def fan_supported(unit):
    # These catalogue ranges share the same unconditional consumed PP schema.
    # This is source mapping coverage, not native/hardware continuum acceptance.
    return _fan_class(unit) and re.fullmatch(r"2\.[456]\.[0-9]{2}", unit.firmware) is not None


def error_output_supported(unit):
    row = _registration(unit)
    return unit.unit_type.upper() in ERROR_CHANNELS and row is not None and row[3:5] == (
        "T" + unit.unit_type.upper(), "TDIMDNUXCGateAgent")


def special_output_profile(unit):
    """Only DIMDUX derivatives share the complete four-logic-group DIN layout."""
    return OutputProfile(tuple(range(ERROR_CHANNELS[unit.unit_type.upper()]))) if error_output_supported(unit) else None


def _one(unit, name, maximum=255):
    values = _required_array(unit, name, 1, maximum)
    if len(unit.array(name)) != 1:
        raise ValueError(f"{name} (requires one explicit value)")
    return values[0]


def _fan_label(unit, speed):
    name = "Label" + speed
    if name not in unit.parameters:
        raise ValueError(name + " (requires explicit PP text)")
    text = unit.parameters[name]
    # The native copy counts UTF-16 units; do not split an astral character or
    # admit an unpaired surrogate that the report encoder cannot represent.
    if any(ord(char) > 0xFFFF or 0xD800 <= ord(char) <= 0xDFFF for char in text):
        raise ValueError(name + " (non-BMP original string-copy semantics unrecovered)")
    length = _one(unit, name + "Length")
    return text[:min(length, 11)]


@dataclass(frozen=True)
class FanData:
    role: str
    master: object | None
    low: int | None
    high: int | None
    labels: tuple[str, str, str, str]


def fan_data(network, unit):
    if not fan_supported(unit):
        raise ValueError("unrecovered fan class/firmware (requires RELDF1 2.4.xx, 2.5.xx or 2.6.xx)")
    trigger = _one(unit, "FanTriggerGroup")
    role, master = "Master", None
    if trigger == 255:
        role = "Stand Alone"
        if not _one(unit, "StandAloneConfig", 1):
            address = _one(unit, "MasterUnitAddress")
            candidate = unit if address == unit.address else next((u for u in network.units if u.address == address), None)
            if candidate is not None:
                if _registration(candidate) is None:
                    raise ValueError("unresolved master unit class/firmware")
                if _fan_class(candidate):
                    role, master = "Slave", candidate
    if master is not None:
        return FanData(role, master, None, None, ("", "", "", ""))
    low, high = _one(unit, "LowToMedThresholdLevel"), _one(unit, "MedToHighThresholdLevel")
    labels = (_fan_label(unit, "Off"), _fan_label(unit, "Low") if low > 0 else "",
              _fan_label(unit, "Med") if low != high else "", _fan_label(unit, "High"))
    return FanData(role, None, low, high, labels)


def fan_lines(network, data):
    from .project_documentation import html_unit
    lines = [f"<b>{data.role} Unit</b><br />"]
    if data.master is not None:
        return lines + ["Master: " + html_unit(network, data.master) + "<br />"]
    percent = lambda value: (value + 2) * 100 // 255
    text = '<table border="1"><tr><th>Fan Speed</th><th>Threshold</th><th>Label</th></tr>'
    text += f"<tr><td>Off</td><td>0%</td><td>{data.labels[0]}</td></tr>"
    if data.low > 0:
        text += f"<tr><td>Low</td><td>1% - {percent(data.low)}%</td><td>{data.labels[1]}</td></tr>"
    if data.low != data.high:
        text += (f"<tr><td>Medium</td><td>{percent(data.low) + 1}% - {percent(data.high)}%</td>"
                 f"<td>{data.labels[2]}</td></tr>")
    text += f"<tr><td>High</td><td>{percent(data.high) + 1}% - 100%</td><td>{data.labels[3]}</td></tr></table>"
    return lines + [text]


def document_fan(out, network, unit):
    """Original one-channel/no-logic Output body followed by the fan appendix."""
    from .project_documentation import document_base
    document_base(out, network, unit)
    if not fan_supported(unit):
        out.mark(network, unit, "Fan controls: unrecovered class/firmware")
        return "partial"
    status = "recovered"
    try:
        application = _required_array(unit, "Application", 1)[0]
        group = _one(unit, "GroupAddress")
        link = "&nbsp;" if group == 255 else _group_link(network, application, group)
        for line in ('<table border="1">', '<tr><th>Channel</th><th>Groups</th></tr>',
                     f'<tr><td>1</td><td>{link}</td></tr>', '</table>', '<br />'):
            out.add(line)
    except ValueError as exc:
        out.mark(network, unit, f"Fan output channel: {exc}")
        status = "partial"
    try:
        lines = fan_lines(network, fan_data(network, unit))
    except ValueError as exc:
        out.mark(network, unit, f"Fan controls: {exc}")
        return "partial"
    for line in lines:
        out.add(line)
    return status


def error_output_action_usage(unit, application, group, address, value):
    from .project_documentation_usage import Usage
    if not error_output_supported(unit):
        return Usage(status="unrecovered", missing=("error-report output class/firmware",))
    if application != 202:
        return Usage()
    try:
        trigger = _one(unit, "TriggerErrorGroup")
    except ValueError as exc:
        return Usage(status="unrecovered", missing=(str(exc),))
    if trigger == 255 or trigger != group:
        return Usage()
    descriptions, missing = [], []
    for parameter, label in zip(("TriggerErrorAcSel", "TriggerErrorClearAcSel"), ERROR_LABELS):
        try:
            selector = _one(unit, parameter)
        except ValueError as exc:
            missing.append(str(exc))
        else:
            if selector == address:
                descriptions.append("<li />" + label)
    return Usage("".join(descriptions), "partial" if missing else "recovered", tuple(missing))


def fan_output_usage(unit, application, group):
    from .project_documentation_usage import Usage
    if not fan_supported(unit):
        return Usage(status="unrecovered", missing=("fan output class/firmware",))
    try:
        primary = _required_array(unit, "Application", 1)[0]
        if primary != application:
            return Usage()
        channel = _one(unit, "GroupAddress")
    except ValueError as exc:
        return Usage(status="unrecovered", missing=(str(exc),))
    return Usage("Channel 1" if channel == group else "")


def error_output_other_usage(unit, application, group):
    from .project_documentation_usage import Usage
    if not error_output_supported(unit):
        return Usage(status="unrecovered", missing=("error-report output class/firmware",))
    if application != 203:
        return Usage()
    try:
        enabled = _one(unit, "EnableErrorGroup")
    except ValueError as exc:
        return Usage(status="unrecovered", missing=(str(exc),))
    return Usage("Error Report Enable Group" if enabled == group else "")
